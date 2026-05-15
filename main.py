import eventlet
eventlet.monkey_patch()

import os
import re
import json
import uuid
import requests
from datetime import datetime
from flask import Flask, render_template, redirect, request, session, url_for, flash, jsonify, abort
from dotenv import load_dotenv
from pymongo import MongoClient
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

mongo_client = MongoClient(MONGO_URI)
db = mongo_client["eifellog_db"]

users_collection = db["users"]
profile_activity_collection = db["profile_activity"]
profile_gallery_collection = db["profile_gallery"]


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
        "last_login": now
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


# ==========================================
# SERVER START
# ==========================================

if __name__ == "__main__":
    print("Starte Eifel LOG Server mit MongoDB und Eventlet auf Port 5005...")
    eventlet.wsgi.server(eventlet.listen(("0.0.0.0", 5005)), app)