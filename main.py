import eventlet
eventlet.monkey_patch()

import os
import re
import json
import uuid
import hmac
import hashlib
import secrets
import requests
from datetime import datetime
from functools import wraps

from flask import Flask, render_template, redirect, request, session, url_for, flash, jsonify, abort
from dotenv import load_dotenv
from pymongo import MongoClient, ASCENDING
from werkzeug.utils import secure_filename


# ==========================================
# GRUNDKONFIGURATION
# ==========================================

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", os.urandom(24))
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024

PROFILE_UPLOAD_FOLDER = os.path.join("static", "uploads", "profiles")
ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}

TRACKER_API_KEY = os.getenv("TRACKER_API_KEY", "").strip()


# ==========================================
# LOCAL TRACKER / WEBVIEW2 CORS
# ==========================================

@app.after_request
def add_tracker_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = (
        "Content-Type, Authorization, X-Tracker-Token, X-Tracker-Code, X-Tracker-Api-Key"
    )
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


@app.route("/api/<path:any_path>", methods=["OPTIONS"])
def api_options(any_path):
    return jsonify({"success": True})


# ==========================================
# DISCORD OAUTH2 KONFIGURATION
# ==========================================

DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
DISCORD_REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI")
DISCORD_GUILD_ID = os.getenv("DISCORD_GUILD_ID")

OAUTH_URL = "https://discord.com/api/oauth2/authorize"
TOKEN_URL = "https://discord.com/api/oauth2/token"
API_BASE_URL = "https://discord.com/api/v10"


# ==========================================
# MONGODB KONFIGURATION
# ==========================================

MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "eifellog")

if not MONGO_URI:
    raise RuntimeError("MONGO_URI fehlt. Bitte in deiner .env setzen.")

mongo_client = MongoClient(MONGO_URI)
db = mongo_client[MONGO_DB_NAME]

users_collection = db["users"]
profile_activity_collection = db["profile_activity"]
profile_gallery_collection = db["profile_gallery"]


def ensure_indexes():
    try:
        users_collection.create_index([("discord_id", ASCENDING)], unique=False)
        users_collection.create_index([("username_lc", ASCENDING)], unique=False)
        users_collection.create_index([("tracker_code_hash", ASCENDING)], unique=False)
        users_collection.create_index([("tracker_client_token_hash", ASCENDING)], unique=False)
    except Exception as error:
        print(f"MongoDB Index-Erstellung fehlgeschlagen: {error}")


ensure_indexes()


# ==========================================
# EIFEL LOG ROLLEN IDS
# ==========================================

ROLE_FAHRER = os.getenv("ROLE_FAHRER")
ROLE_GESCHAEFTSLEITUNG = os.getenv("ROLE_GESCHAEFTSLEITUNG")
ROLE_PROJEKTLEITUNG = os.getenv("ROLE_PROJEKTLEITUNG")
ROLE_FUHRPARKMANAGEMENT = os.getenv("ROLE_FUHRPARKMANAGEMENT")
ROLE_BUCHHALTUNG = os.getenv("ROLE_BUCHHALTUNG")
ROLE_HR_CONTROLLING = os.getenv("ROLE_HR_CONTROLLING")
ROLE_DISPOSITION = os.getenv("ROLE_DISPOSITION")
ROLE_PERSONALMANAGEMENT = os.getenv("ROLE_PERSONALMANAGEMENT")

ALLOWED_HUB_ROLES = [
    ROLE_FAHRER,
    ROLE_GESCHAEFTSLEITUNG,
    ROLE_PROJEKTLEITUNG,
    ROLE_FUHRPARKMANAGEMENT,
    ROLE_BUCHHALTUNG,
    ROLE_HR_CONTROLLING,
    ROLE_DISPOSITION,
    ROLE_PERSONALMANAGEMENT
]


# ==========================================
# HILFSFUNKTIONEN
# ==========================================

def now_utc():
    return datetime.utcnow()


def safe_str(value, fallback=""):
    if value is None:
        return fallback

    return str(value).strip()


def clean_roles(roles):
    return [str(role).strip() for role in roles if role]


def has_dashboard_permission(user_roles):
    clean_user_roles = clean_roles(user_roles)
    clean_allowed_roles = clean_roles(ALLOWED_HUB_ROLES)

    return any(role in clean_user_roles for role in clean_allowed_roles)


def get_primary_role_name(user_roles):
    clean_user_roles = clean_roles(user_roles)

    if str(ROLE_GESCHAEFTSLEITUNG).strip() in clean_user_roles:
        return "Geschäftsleitung"

    if str(ROLE_PROJEKTLEITUNG).strip() in clean_user_roles:
        return "Projektleitung"

    if str(ROLE_PERSONALMANAGEMENT).strip() in clean_user_roles:
        return "Personalmanagement"

    if str(ROLE_HR_CONTROLLING).strip() in clean_user_roles:
        return "HR Controlling"

    if str(ROLE_BUCHHALTUNG).strip() in clean_user_roles:
        return "Buchhaltung"

    if str(ROLE_DISPOSITION).strip() in clean_user_roles:
        return "Disposition"

    if str(ROLE_FUHRPARKMANAGEMENT).strip() in clean_user_roles:
        return "Fuhrparkmanagement"

    return "Fahrer"


def normalize_username(username, fallback="driver"):
    username = str(username or "").strip()
    username = username.replace(" ", "-")
    username = re.sub(r"[^A-Za-z0-9_.-]", "", username)
    username = username[:32].strip(".-_")

    if not username:
        username = fallback

    return username


def username_exists(username, exclude_discord_id=None):
    username_lc = username.lower()

    query = {"username_lc": username_lc}

    if exclude_discord_id:
        query["discord_id"] = {"$ne": str(exclude_discord_id)}

    existing = users_collection.find_one(query)

    if existing:
        return True

    regex_query = {
        "username": {
            "$regex": f"^{re.escape(username)}$",
            "$options": "i"
        }
    }

    if exclude_discord_id:
        regex_query["discord_id"] = {"$ne": str(exclude_discord_id)}

    return users_collection.find_one(regex_query) is not None


def create_unique_username(preferred_username, discord_id):
    base = normalize_username(preferred_username, fallback=f"driver-{str(discord_id)[-4:]}")
    candidate = base
    counter = 1

    while username_exists(candidate, exclude_discord_id=discord_id):
        candidate = f"{base}-{counter}"
        counter += 1

    return candidate


def find_user_by_username(username):
    username = normalize_username(username)
    username_lc = username.lower()

    user = users_collection.find_one({"username_lc": username_lc})

    if user:
        return user

    return users_collection.find_one({
        "username": {
            "$regex": f"^{re.escape(username)}$",
            "$options": "i"
        }
    })


def find_user_for_tracker_name(driver_name):
    driver_name = safe_str(driver_name)

    if not driver_name:
        return None

    normalized = normalize_username(driver_name)
    normalized_lc = normalized.lower()

    possible_queries = [
        {"username_lc": normalized_lc},
        {"username": {"$regex": f"^{re.escape(driver_name)}$", "$options": "i"}},
        {"display_name": {"$regex": f"^{re.escape(driver_name)}$", "$options": "i"}},
        {"discord_username": {"$regex": f"^{re.escape(driver_name)}$", "$options": "i"}},
    ]

    for query in possible_queries:
        user = users_collection.find_one(query)

        if user:
            return user

    return None


def get_current_user():
    user_session = session.get("user")

    if not user_session:
        return None

    if isinstance(user_session, dict):
        discord_id = user_session.get("id")

        if discord_id:
            return users_collection.find_one({"discord_id": str(discord_id)})

        username = user_session.get("username")

        if username:
            return find_user_by_username(username)

    if isinstance(user_session, str):
        return find_user_by_username(user_session)

    return None


def allowed_image(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS


def save_profile_image(file_field):
    file = request.files.get(file_field)

    if not file or not file.filename:
        return None

    if not allowed_image(file.filename):
        flash("Nur PNG, JPG, JPEG, WEBP oder GIF Bilder sind erlaubt.", "error")
        return None

    os.makedirs(PROFILE_UPLOAD_FOLDER, exist_ok=True)

    original_filename = secure_filename(file.filename)
    extension = original_filename.rsplit(".", 1)[1].lower()
    filename = f"{uuid.uuid4().hex}.{extension}"

    filepath = os.path.join(PROFILE_UPLOAD_FOLDER, filename)
    file.save(filepath)

    return url_for("static", filename=f"uploads/profiles/{filename}")


def get_discord_avatar_url(user_doc):
    custom_avatar = user_doc.get("avatar_url")

    if custom_avatar:
        return custom_avatar

    discord_id = user_doc.get("discord_id")
    avatar_hash = user_doc.get("avatar")

    if discord_id and avatar_hash:
        extension = "gif" if str(avatar_hash).startswith("a_") else "png"
        return f"https://cdn.discordapp.com/avatars/{discord_id}/{avatar_hash}.{extension}?size=256"

    return url_for("static", filename="eifellog.jpg")


def make_external_url(possible_url):
    possible_url = safe_str(possible_url)

    if not possible_url:
        return ""

    if possible_url.startswith("http://") or possible_url.startswith("https://"):
        return possible_url

    if possible_url.startswith("/"):
        return request.host_url.rstrip("/") + possible_url

    return request.host_url.rstrip("/") + "/" + possible_url.lstrip("/")


def prepare_profile_data(user_doc):
    profile_data = dict(user_doc)

    profile_data["_id"] = str(profile_data.get("_id"))

    profile_data["avatar_url"] = get_discord_avatar_url(profile_data)
    profile_data["display_name"] = profile_data.get("display_name") or profile_data.get("username") or "Eifel LOG Fahrer"
    profile_data["username"] = profile_data.get("username") or "driver"
    profile_data["rank"] = profile_data.get("rank") or "Driver"
    profile_data["status"] = profile_data.get("status") or "Bereit für die nächste Tour."
    profile_data["bio"] = profile_data.get("bio") or "Dieses Profil wurde noch nicht ausgefüllt."
    profile_data["location"] = profile_data.get("location") or "Nicht angegeben"
    profile_data["favorite_truck"] = profile_data.get("favorite_truck") or "Nicht angegeben"

    profile_data["show_email"] = bool(profile_data.get("show_email", False))
    profile_data["show_discord"] = bool(profile_data.get("show_discord", True))
    profile_data["show_stats"] = bool(profile_data.get("show_stats", True))
    profile_data["show_activity"] = bool(profile_data.get("show_activity", True))
    profile_data["public_profile"] = bool(profile_data.get("public_profile", True))

    if not profile_data.get("member_since"):
        created_at = profile_data.get("created_at")

        if isinstance(created_at, datetime):
            profile_data["member_since"] = created_at.strftime("%d.%m.%Y")
        else:
            profile_data["member_since"] = "Neu"

    last_login = profile_data.get("last_login")

    if isinstance(last_login, datetime):
        profile_data["last_seen"] = last_login.strftime("%d.%m.%Y %H:%M")
    elif not profile_data.get("last_seen"):
        profile_data["last_seen"] = "Unbekannt"

    return profile_data


def get_profile_stats(user_doc):
    return {
        "km": user_doc.get("profile_km", "0"),
        "deliveries": user_doc.get("profile_deliveries", "0"),
        "convoys": user_doc.get("profile_convoys", "0"),
        "rating": user_doc.get("profile_rating", "0.0")
    }


def load_json_file(path):
    if not os.path.exists(path):
        return []

    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception as error:
        print(f"Fehler beim Laden von {path}: {error}")
        return []


def get_activity_for_user(username):
    items = profile_activity_collection.find(
        {"username_lc": username.lower()},
        {"_id": 0}
    ).sort("created_at", -1).limit(10)

    return list(items)


def get_gallery_for_user(username):
    items = profile_gallery_collection.find(
        {"username_lc": username.lower()},
        {"_id": 0}
    ).sort("created_at", -1).limit(12)

    return list(items)


# ==========================================
# TRACKER CODE / TOKEN HILFSFUNKTIONEN
# ==========================================

def hash_secret(value):
    value = safe_str(value)

    if not value:
        return ""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def secure_compare(value_a, value_b):
    return hmac.compare_digest(safe_str(value_a), safe_str(value_b))


def generate_tracker_code():
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

    part_1 = "".join(secrets.choice(alphabet) for _ in range(4))
    part_2 = "".join(secrets.choice(alphabet) for _ in range(4))
    part_3 = "".join(secrets.choice(alphabet) for _ in range(4))

    return f"EL-{part_1}-{part_2}-{part_3}"


def generate_client_token():
    return f"elt_{secrets.token_urlsafe(48)}"


def normalize_tracker_code(code):
    code = safe_str(code).upper()
    code = code.replace(" ", "")
    return code


def user_has_tracker_access(user_doc):
    if not user_doc:
        return False

    if user_doc.get("tracker_enabled") is False:
        return False

    return True


def tracker_profile_payload(user_doc):
    profile = prepare_profile_data(user_doc)
    stats = get_profile_stats(user_doc)

    avatar_url = make_external_url(profile.get("avatar_url"))
    banner_url = make_external_url(user_doc.get("banner_url"))

    return {
        "id": str(user_doc.get("_id")),
        "discordId": safe_str(user_doc.get("discord_id")),
        "username": profile.get("username"),
        "displayName": profile.get("display_name"),
        "driverName": profile.get("display_name") or profile.get("username"),
        "discordUsername": safe_str(user_doc.get("discord_username")),
        "avatarUrl": avatar_url,
        "bannerUrl": banner_url,
        "role": get_primary_role_name(user_doc.get("roles", [])),
        "roles": user_doc.get("roles", []),
        "status": profile.get("status"),
        "bio": profile.get("bio"),
        "location": profile.get("location"),
        "favoriteTruck": profile.get("favorite_truck"),
        "memberSince": profile.get("member_since"),
        "lastSeen": profile.get("last_seen"),
        "stats": {
            "km": stats.get("km"),
            "deliveries": stats.get("deliveries"),
            "convoys": stats.get("convoys"),
            "rating": stats.get("rating")
        }
    }


def tracker_api_key_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not TRACKER_API_KEY:
            return jsonify({
                "success": False,
                "error": "TRACKER_API_KEY ist serverseitig nicht konfiguriert."
            }), 500

        provided_key = request.headers.get("X-Tracker-Api-Key") or request.args.get("api_key")

        if not secure_compare(provided_key, TRACKER_API_KEY):
            return jsonify({
                "success": False,
                "error": "Ungültiger API-Key."
            }), 401

        return func(*args, **kwargs)

    return wrapper


# ==========================================
# ROUTES - ÖFFENTLICH
# ==========================================

@app.route("/")
def home():
    return render_template("index.html")


@app.route("/about")
def about():
    return render_template("about.html")


# ==========================================
# AUTHENTIFIZIERUNG
# ==========================================

@app.route("/login")
def login():
    auth_url = (
        f"{OAUTH_URL}"
        f"?client_id={DISCORD_CLIENT_ID}"
        f"&redirect_uri={DISCORD_REDIRECT_URI}"
        f"&response_type=code"
        f"&scope=identify%20guilds%20guilds.members.read"
    )

    return redirect(auth_url)


@app.route("/callback")
def callback():
    code = request.args.get("code")

    if not code:
        flash("Login abgebrochen.", "error")
        return redirect(url_for("home"))

    token_payload = {
        "client_id": DISCORD_CLIENT_ID,
        "client_secret": DISCORD_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": DISCORD_REDIRECT_URI
    }

    headers = {
        "Content-Type": "application/x-www-form-urlencoded"
    }

    token_response = requests.post(TOKEN_URL, data=token_payload, headers=headers)

    if token_response.status_code != 200:
        flash("Fehler bei der Discord-Kommunikation. Bitte Client ID/Secret prüfen.", "error")
        return redirect(url_for("home"))

    token = token_response.json().get("access_token")

    if not token:
        flash("Discord hat kein gültiges Access Token zurückgegeben.", "error")
        return redirect(url_for("home"))

    auth_headers = {
        "Authorization": f"Bearer {token}"
    }

    user_response = requests.get(f"{API_BASE_URL}/users/@me", headers=auth_headers)

    if user_response.status_code != 200:
        flash("Discord-Benutzerdaten konnten nicht geladen werden.", "error")
        return redirect(url_for("home"))

    user_data = user_response.json()

    member_response = requests.get(
        f"{API_BASE_URL}/users/@me/guilds/{DISCORD_GUILD_ID}/member",
        headers=auth_headers
    )

    if member_response.status_code == 404:
        flash("Du musst Mitglied auf dem Eifel LOG Discord Server sein!", "error")
        return redirect(url_for("home"))

    if member_response.status_code != 200:
        flash("Discord-Rollen konnten nicht geprüft werden.", "error")
        return redirect(url_for("home"))

    member_data = member_response.json()
    user_roles = member_data.get("roles", [])

    discord_id = str(user_data["id"])
    discord_username = user_data.get("username", "driver")
    avatar = user_data.get("avatar")

    existing_user = users_collection.find_one({"discord_id": discord_id})

    if existing_user and existing_user.get("username"):
        profile_username = existing_user.get("username")
    else:
        profile_username = create_unique_username(discord_username, discord_id)

    now = datetime.utcnow()

    update_data = {
        "discord_id": discord_id,
        "discord_username": discord_username,
        "avatar": avatar,
        "roles": user_roles,
        "last_login": now,
        "tracker_enabled": True
    }

    if not existing_user or not existing_user.get("username"):
        update_data["username"] = profile_username
        update_data["username_lc"] = profile_username.lower()

    users_collection.update_one(
        {"discord_id": discord_id},
        {
            "$set": update_data,
            "$setOnInsert": {
                "created_at": now,
                "display_name": discord_username,
                "avatar_url": "",
                "banner_url": "",
                "rank": "Driver",
                "status": "Bereit für die nächste Tour.",
                "bio": "",
                "location": "",
                "discord": "",
                "truckersmp_id": "",
                "steam": "",
                "website": "",
                "favorite_truck": "",
                "show_email": False,
                "show_discord": True,
                "show_stats": True,
                "show_activity": True,
                "public_profile": True,
                "member_since": now.strftime("%d.%m.%Y"),
                "last_seen": now.strftime("%d.%m.%Y %H:%M"),
                "profile_km": "0",
                "profile_deliveries": "0",
                "profile_convoys": "0",
                "profile_rating": "0.0"
            }
        },
        upsert=True
    )

    session["user"] = {
        "id": discord_id,
        "username": profile_username,
        "discord_username": discord_username,
        "avatar": avatar,
        "roles": user_roles
    }

    flash("Erfolgreich eingeloggt!", "success")
    return redirect(url_for("dashboard"))


@app.route("/logout")
def logout():
    session.pop("user", None)
    flash("Erfolgreich abgemeldet.", "success")
    return redirect(url_for("home"))


# ==========================================
# TRACKER API - LOGIN.HTML / INDEX.HTML
# ==========================================

@app.route("/api/tracker/login", methods=["GET", "POST", "OPTIONS"])
def tracker_login():
    if request.method == "OPTIONS":
        return jsonify({"success": True})

    if request.method == "GET":
        return jsonify({
            "success": False,
            "message": "Dieser Endpoint ist aktiv, erwartet aber POST mit JSON.",
            "method": "POST",
            "contentType": "application/json",
            "example": {
                "driverName": "Fahrername",
                "trackerCode": "EL-XXXX-XXXX-XXXX",
                "remember": True
            }
        }), 200

    data = request.get_json(silent=True) or {}

    driver_name = safe_str(data.get("driverName"))
    tracker_code = normalize_tracker_code(data.get("trackerCode") or data.get("accessCode"))
    remember = bool(data.get("remember", True))

    if not driver_name:
        return jsonify({
            "success": False,
            "error": "Fahrername fehlt."
        }), 400

    if not tracker_code:
        return jsonify({
            "success": False,
            "error": "Tracker-Code fehlt."
        }), 400

    user_doc = find_user_for_tracker_name(driver_name)

    if not user_doc:
        return jsonify({
            "success": False,
            "error": "Fahrer wurde nicht gefunden."
        }), 404

    if not user_has_tracker_access(user_doc):
        return jsonify({
            "success": False,
            "error": "Tracker-Zugriff ist für diesen Fahrer deaktiviert."
        }), 403

    incoming_code_hash = hash_secret(tracker_code)
    stored_hash = user_doc.get("tracker_code_hash", "")
    legacy_plain_code = normalize_tracker_code(user_doc.get("tracker_code"))

    valid_code = False

    if stored_hash and secure_compare(incoming_code_hash, stored_hash):
        valid_code = True

    if legacy_plain_code and secure_compare(tracker_code, legacy_plain_code):
        valid_code = True

        users_collection.update_one(
            {"_id": user_doc["_id"]},
            {
                "$set": {
                    "tracker_code_hash": incoming_code_hash,
                    "tracker_code_migrated_at": now_utc()
                },
                "$unset": {
                    "tracker_code": ""
                }
            }
        )

    if not valid_code:
        return jsonify({
            "success": False,
            "error": "Tracker-Code ist ungültig."
        }), 401

    client_token = generate_client_token()
    client_token_hash = hash_secret(client_token)

    users_collection.update_one(
        {"_id": user_doc["_id"]},
        {
            "$set": {
                "tracker_client_token_hash": client_token_hash,
                "tracker_last_login": now_utc(),
                "tracker_last_driver_name": driver_name,
                "tracker_enabled": True
            },
            "$inc": {
                "tracker_login_count": 1
            }
        }
    )

    fresh_user = users_collection.find_one({"_id": user_doc["_id"]})

    return jsonify({
        "success": True,
        "message": "Tracker freigeschaltet.",
        "remember": remember,
        "clientToken": client_token,
        "profile": tracker_profile_payload(fresh_user)
    })


@app.route("/api/tracker/session", methods=["GET", "POST", "OPTIONS"])
def tracker_session_login():
    if request.method == "OPTIONS":
        return jsonify({"success": True})

    if request.method == "GET":
        return jsonify({
            "success": False,
            "message": "Dieser Endpoint ist aktiv, erwartet aber POST mit clientToken.",
            "method": "POST",
            "example": {
                "clientToken": "elt_..."
            }
        }), 200

    data = request.get_json(silent=True) or {}

    client_token = (
        safe_str(data.get("clientToken"))
        or safe_str(request.headers.get("X-Tracker-Token"))
        or safe_str(request.headers.get("Authorization")).replace("Bearer ", "").strip()
    )

    if not client_token:
        return jsonify({
            "success": False,
            "error": "Kein gespeicherter Tracker-Token vorhanden."
        }), 401

    client_token_hash = hash_secret(client_token)

    user_doc = users_collection.find_one({
        "tracker_client_token_hash": client_token_hash
    })

    if not user_doc:
        return jsonify({
            "success": False,
            "error": "Gespeicherte Sitzung ist ungültig. Bitte Tracker-Code erneut eingeben."
        }), 401

    if not user_has_tracker_access(user_doc):
        return jsonify({
            "success": False,
            "error": "Tracker-Zugriff ist deaktiviert."
        }), 403

    users_collection.update_one(
        {"_id": user_doc["_id"]},
        {
            "$set": {
                "tracker_last_session_login": now_utc()
            }
        }
    )

    fresh_user = users_collection.find_one({"_id": user_doc["_id"]})

    return jsonify({
        "success": True,
        "message": "Tracker-Sitzung gültig.",
        "profile": tracker_profile_payload(fresh_user)
    })


@app.route("/api/tracker/profile", methods=["GET", "POST", "OPTIONS"])
def tracker_profile():
    if request.method == "OPTIONS":
        return jsonify({"success": True})

    if request.method == "GET":
        client_token = (
            safe_str(request.headers.get("X-Tracker-Token"))
            or safe_str(request.headers.get("Authorization")).replace("Bearer ", "").strip()
            or safe_str(request.args.get("clientToken"))
        )
    else:
        data = request.get_json(silent=True) or {}
        client_token = safe_str(data.get("clientToken"))

    if not client_token:
        return jsonify({
            "success": False,
            "error": "Tracker-Token fehlt."
        }), 401

    user_doc = users_collection.find_one({
        "tracker_client_token_hash": hash_secret(client_token)
    })

    if not user_doc:
        return jsonify({
            "success": False,
            "error": "Tracker-Token ist ungültig."
        }), 401

    if not user_has_tracker_access(user_doc):
        return jsonify({
            "success": False,
            "error": "Tracker-Zugriff ist deaktiviert."
        }), 403

    return jsonify({
        "success": True,
        "profile": tracker_profile_payload(user_doc)
    })


@app.route("/api/tracker/logout", methods=["GET", "POST", "OPTIONS"])
def tracker_logout():
    if request.method == "OPTIONS":
        return jsonify({"success": True})

    if request.method == "GET":
        return jsonify({
            "success": False,
            "message": "Dieser Endpoint ist aktiv, erwartet aber POST mit clientToken."
        }), 200

    data = request.get_json(silent=True) or {}
    client_token = safe_str(data.get("clientToken"))

    if client_token:
        users_collection.update_one(
            {"tracker_client_token_hash": hash_secret(client_token)},
            {
                "$unset": {
                    "tracker_client_token_hash": ""
                },
                "$set": {
                    "tracker_logged_out_at": now_utc()
                }
            }
        )

    return jsonify({
        "success": True,
        "message": "Tracker lokal abgemeldet."
    })


@app.route("/api/tracker/code/create", methods=["GET", "POST", "OPTIONS"])
@tracker_api_key_required
def tracker_create_code_admin():
    if request.method == "OPTIONS":
        return jsonify({"success": True})

    if request.method == "GET":
        return jsonify({
            "success": False,
            "message": "Dieser Endpoint ist aktiv, erwartet aber POST mit X-Tracker-Api-Key.",
            "example": {
                "driverName": "Fahrername",
                "forceNew": False
            }
        }), 200

    data = request.get_json(silent=True) or {}

    driver_name = safe_str(data.get("driverName"))
    discord_id = safe_str(data.get("discordId"))
    force_new = bool(data.get("forceNew", False))

    if not driver_name and not discord_id:
        return jsonify({
            "success": False,
            "error": "driverName oder discordId fehlt."
        }), 400

    if discord_id:
        user_doc = users_collection.find_one({"discord_id": discord_id})
    else:
        user_doc = find_user_for_tracker_name(driver_name)

    if not user_doc:
        return jsonify({
            "success": False,
            "error": "Fahrer wurde nicht gefunden."
        }), 404

    existing_hash = user_doc.get("tracker_code_hash")

    if existing_hash and not force_new:
        return jsonify({
            "success": True,
            "message": "Für diesen Fahrer existiert bereits ein Tracker-Code. Aus Sicherheitsgründen wird er nicht erneut angezeigt. Nutze forceNew=true für einen neuen Code.",
            "trackerCode": None,
            "driver": tracker_profile_payload(user_doc)
        })

    tracker_code = generate_tracker_code()

    users_collection.update_one(
        {"_id": user_doc["_id"]},
        {
            "$set": {
                "tracker_code_hash": hash_secret(tracker_code),
                "tracker_code_created_at": now_utc(),
                "tracker_enabled": True
            },
            "$unset": {
                "tracker_code": ""
            }
        }
    )

    fresh_user = users_collection.find_one({"_id": user_doc["_id"]})

    return jsonify({
        "success": True,
        "message": "Tracker-Code erstellt.",
        "trackerCode": tracker_code,
        "driver": tracker_profile_payload(fresh_user)
    })


@app.route("/api/tracker/code/my", methods=["GET", "POST", "OPTIONS"])
def tracker_create_code_for_logged_in_user():
    if request.method == "OPTIONS":
        return jsonify({"success": True})

    if request.method == "GET":
        return jsonify({
            "success": False,
            "message": "Dieser Endpoint ist aktiv, erwartet aber POST und eine eingeloggte Dashboard-Session."
        }), 200

    current_user = get_current_user()

    if not current_user:
        return jsonify({
            "success": False,
            "error": "Bitte zuerst im Dashboard einloggen."
        }), 401

    data = request.get_json(silent=True) or {}
    force_new = bool(data.get("forceNew", False))

    existing_hash = current_user.get("tracker_code_hash")

    if existing_hash and not force_new:
        return jsonify({
            "success": True,
            "message": "Tracker-Code existiert bereits. Er wird nicht erneut angezeigt.",
            "trackerCode": None,
            "driver": tracker_profile_payload(current_user)
        })

    tracker_code = generate_tracker_code()

    users_collection.update_one(
        {"_id": current_user["_id"]},
        {
            "$set": {
                "tracker_code_hash": hash_secret(tracker_code),
                "tracker_code_created_at": now_utc(),
                "tracker_enabled": True
            },
            "$unset": {
                "tracker_code": ""
            }
        }
    )

    fresh_user = users_collection.find_one({"_id": current_user["_id"]})

    return jsonify({
        "success": True,
        "message": "Tracker-Code erstellt.",
        "trackerCode": tracker_code,
        "driver": tracker_profile_payload(fresh_user)
    })


# ==========================================
# ÖFFENTLICHE PROFILE
# ==========================================

@app.route("/profile")
def my_profile_redirect():
    current_user = get_current_user()

    if not current_user:
        flash("Bitte melde dich an, um dein eigenes Profil zu öffnen.", "error")
        return redirect(url_for("hub"))

    username = current_user.get("username")

    if not username:
        flash("Dein Account hat noch keinen Benutzernamen.", "error")
        return redirect(url_for("dashboard"))

    return redirect(url_for("profile", username=username))


@app.route("/profile/<username>", methods=["GET", "POST"])
def profile(username):
    profile_user = find_user_by_username(username)

    if not profile_user:
        abort(404)

    current_user = get_current_user()

    is_own_profile = (
        current_user is not None
        and str(current_user.get("discord_id")) == str(profile_user.get("discord_id"))
    )

    if request.method == "POST":
        if not is_own_profile:
            abort(403)

        old_username = profile_user.get("username")
        new_username = normalize_username(
            request.form.get("username", old_username),
            fallback=old_username
        )

        if username_exists(new_username, exclude_discord_id=profile_user.get("discord_id")):
            flash("Dieser Benutzername ist bereits vergeben.", "error")
            return redirect(url_for("profile", username=old_username))

        uploaded_avatar = save_profile_image("avatar_file")
        uploaded_banner = save_profile_image("banner_file")

        form_avatar_url = request.form.get("avatar_url", "").strip()
        form_banner_url = request.form.get("banner_url", "").strip()

        current_avatar_url = profile_user.get("avatar_url", "")
        current_banner_url = profile_user.get("banner_url", "")

        avatar_url = uploaded_avatar or form_avatar_url or current_avatar_url
        banner_url = uploaded_banner or form_banner_url or current_banner_url

        display_name = request.form.get("display_name", "").strip()[:40]
        rank = request.form.get("rank", "Driver").strip()[:40]
        status = request.form.get("status", "").strip()[:120]
        bio = request.form.get("bio", "").strip()[:900]
        location = request.form.get("location", "").strip()[:60]
        discord = request.form.get("discord", "").strip()[:80]
        truckersmp_id = request.form.get("truckersmp_id", "").strip()[:40]
        steam = request.form.get("steam", "").strip()[:120]
        website = request.form.get("website", "").strip()[:180]
        favorite_truck = request.form.get("favorite_truck", "").strip()[:80]

        show_email = request.form.get("show_email") == "1"
        show_discord = request.form.get("show_discord") == "1"
        show_stats = request.form.get("show_stats") == "1"
        show_activity = request.form.get("show_activity") == "1"
        public_profile = request.form.get("public_profile") == "1"

        now = datetime.utcnow()

        users_collection.update_one(
            {"discord_id": str(profile_user.get("discord_id"))},
            {
                "$set": {
                    "username": new_username,
                    "username_lc": new_username.lower(),
                    "display_name": display_name,
                    "avatar_url": avatar_url,
                    "banner_url": banner_url,
                    "rank": rank,
                    "status": status,
                    "bio": bio,
                    "location": location,
                    "discord": discord,
                    "truckersmp_id": truckersmp_id,
                    "steam": steam,
                    "website": website,
                    "favorite_truck": favorite_truck,
                    "show_email": show_email,
                    "show_discord": show_discord,
                    "show_stats": show_stats,
                    "show_activity": show_activity,
                    "public_profile": public_profile,
                    "updated_at": now,
                    "last_seen": now.strftime("%d.%m.%Y %H:%M")
                }
            }
        )

        if new_username != old_username:
            profile_activity_collection.update_many(
                {"username_lc": old_username.lower()},
                {
                    "$set": {
                        "username": new_username,
                        "username_lc": new_username.lower()
                    }
                }
            )

            profile_gallery_collection.update_many(
                {"username_lc": old_username.lower()},
                {
                    "$set": {
                        "username": new_username,
                        "username_lc": new_username.lower()
                    }
                }
            )

        if isinstance(session.get("user"), dict):
            session["user"]["username"] = new_username
            session.modified = True

        flash("Profil wurde erfolgreich gespeichert.", "success")
        return redirect(url_for("profile", username=new_username))

    profile_data = prepare_profile_data(profile_user)
    stats = get_profile_stats(profile_user)

    activity = get_activity_for_user(profile_data["username"])
    gallery = get_gallery_for_user(profile_data["username"])

    return render_template(
        "profile.html",
        profile=profile_data,
        is_own_profile=is_own_profile,
        stats=stats,
        activity=activity,
        gallery=gallery
    )


# ==========================================
# DRIVER HUB
# ==========================================

@app.route("/hub")
def hub():
    if "user" in session:
        return redirect(url_for("dashboard"))

    return render_template("hub.html")


# ==========================================
# DASHBOARD
# ==========================================

@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        flash("Bitte logge dich zuerst ein.", "error")
        return redirect(url_for("hub"))

    user = session["user"]
    user_roles = user.get("roles", [])

    if not has_dashboard_permission(user_roles):
        flash("Zugriff verweigert! Du benötigst eine anerkannte Rolle, um das Dashboard zu betreten.", "error")
        return redirect(url_for("home"))

    db_user = users_collection.find_one({"discord_id": str(user["id"])})

    if db_user:
        needs_signature = not db_user.get("policy_signed", False)
    else:
        needs_signature = True

    primary_role_name = get_primary_role_name(user_roles)

    news_items = load_json_file("news.json")

    user_documents = []
    all_documents = load_json_file("documents.json")

    user_id_str = str(user["id"])

    for document in all_documents:
        if str(document.get("discord_id")) == user_id_str:
            user_documents.append(document)

    return render_template(
        "dashboard.html",
        current_user=user,
        needs_signature=needs_signature,
        primary_role_name=primary_role_name,
        news_items=news_items,
        user_documents=user_documents
    )


# ==========================================
# STANDARD ROUTEN
# ==========================================

@app.route("/downloads")
def downloads():
    if "user" not in session:
        return redirect(url_for("login"))

    return render_template("download.html")


@app.route("/fuhrpark")
def fuhrpark():
    if "user" not in session:
        return redirect(url_for("login"))

    return render_template("fuhrpark.html")


# ==========================================
# API ROUTEN
# ==========================================

@app.route("/api/sign_policy", methods=["POST"])
def sign_policy():
    if "user" not in session:
        return jsonify({
            "success": False,
            "error": "Not logged in"
        }), 401

    data = request.get_json() or {}
    signature = data.get("signature")

    if not signature:
        return jsonify({
            "success": False,
            "error": "No signature provided"
        }), 400

    users_collection.update_one(
        {"discord_id": str(session["user"]["id"])},
        {
            "$set": {
                "policy_signed": True,
                "policy_signature": signature,
                "policy_signed_at": datetime.utcnow()
            }
        }
    )

    return jsonify({
        "success": True
    })


@app.route("/api/health")
def health_check():
    return jsonify({
        "success": True,
        "service": "EifelLog",
        "database": MONGO_DB_NAME,
        "time": now_utc().isoformat() + "Z"
    })


# ==========================================
# SERVER START
# ==========================================

if __name__ == "__main__":
    print(f"Starte Eifel LOG Server mit MongoDB DB '{MONGO_DB_NAME}' und Eventlet auf Port 5005...")
    eventlet.wsgi.server(eventlet.listen(("0.0.0.0", 5005)), app)