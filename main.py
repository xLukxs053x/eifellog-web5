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
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, render_template, redirect, request, session, url_for, flash, jsonify, abort
from dotenv import load_dotenv
from pymongo import MongoClient, ASCENDING, DESCENDING
from bson.objectid import ObjectId
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
        "Content-Type, Authorization, X-Tracker-Token, X-Tracker-Code, X-Tracker-Api-Key, X-Requested-With"
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
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "eifellog_db")

if not MONGO_URI:
    raise RuntimeError("MONGO_URI fehlt. Bitte in deiner .env setzen.")

mongo_client = MongoClient(MONGO_URI)
db = mongo_client[MONGO_DB_NAME]

users_collection = db["users"]
profile_activity_collection = db["profile_activity"]
profile_gallery_collection = db["profile_gallery"]
fahrer_registration_collection = db["fahrer_registration_requests"]
token_request_collection = db["token_requests"]
system_documents_collection = db["system_documents"]
tasks_collection = db["tasks"]
buchhaltung_requests_collection = db["buchhaltung_requests"]


def ensure_indexes():
    try:
        users_collection.create_index([("discord_id", ASCENDING)], unique=False)
        users_collection.create_index([("username_lc", ASCENDING)], unique=False)
        users_collection.create_index([("tracker_code_hash", ASCENDING)], unique=False)
        users_collection.create_index([("tracker_client_token_hash", ASCENDING)], unique=False)
        users_collection.create_index([("tracker_live_updated_at", DESCENDING)], unique=False)
        users_collection.create_index([("tracker_online", ASCENDING)], unique=False)

        fahrer_registration_collection.create_index([("discord_id", ASCENDING)], unique=False)
        fahrer_registration_collection.create_index([("status", ASCENDING)], unique=False)
        fahrer_registration_collection.create_index([("created_at", DESCENDING)], unique=False)
        fahrer_registration_collection.create_index([("claimed_by.discord_id", ASCENDING)], unique=False)
        fahrer_registration_collection.create_index([("deadline_at", ASCENDING)], unique=False)

        token_request_collection.create_index([("discord_id", ASCENDING)], unique=False)
        token_request_collection.create_index([("status", ASCENDING)], unique=False)
        token_request_collection.create_index([("created_at", DESCENDING)], unique=False)

        system_documents_collection.create_index([("discord_id", ASCENDING)], unique=False)
        system_documents_collection.create_index([("created_at", DESCENDING)], unique=False)
        system_documents_collection.create_index([("type", ASCENDING)], unique=False)
        
        tasks_collection.create_index([("status", ASCENDING)], unique=False)
        tasks_collection.create_index([("created_at", DESCENDING)], unique=False)
        
        buchhaltung_requests_collection.create_index([("created_at", DESCENDING)], unique=False)
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

# Hardcoded Rollen IDs basierend auf Vorgaben
ROLE_PERSONALABTEILUNG_ID = "1473725287505072174"
ROLE_GESCHAEFTSFUEHRUNG_ID = "1473721587122438322"
ROLE_PROJEKTLEITUNG_ID = "1473721587122438321"
ROLE_BUCHHALTUNG_ID = "1473730533593845951"

PERSONALABTEILUNG_ALLOWED_ROLES = {
    ROLE_PERSONALABTEILUNG_ID,
    ROLE_GESCHAEFTSFUEHRUNG_ID,
    ROLE_PROJEKTLEITUNG_ID
}


# ==========================================
# ALLGEMEINE HILFSFUNKTIONEN
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

    if str(ROLE_GESCHAEFTSLEITUNG).strip() in clean_user_roles: return "Geschäftsleitung"
    if str(ROLE_PROJEKTLEITUNG).strip() in clean_user_roles: return "Projektleitung"
    if str(ROLE_PERSONALMANAGEMENT).strip() in clean_user_roles: return "Personalmanagement"
    if str(ROLE_HR_CONTROLLING).strip() in clean_user_roles: return "HR Controlling"
    if str(ROLE_BUCHHALTUNG).strip() in clean_user_roles: return "Buchhaltung"
    if str(ROLE_DISPOSITION).strip() in clean_user_roles: return "Disposition"
    if str(ROLE_FUHRPARKMANAGEMENT).strip() in clean_user_roles: return "Fuhrparkmanagement"

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
    if existing: return True

    regex_query = {"username": {"$regex": f"^{re.escape(username)}$", "$options": "i"}}
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
    user = users_collection.find_one({"username_lc": username.lower()})
    if user: return user

    return users_collection.find_one({"username": {"$regex": f"^{re.escape(username)}$", "$options": "i"}})


def find_user_for_tracker_name(driver_name):
    driver_name = safe_str(driver_name)
    if not driver_name: return None

    normalized = normalize_username(driver_name)
    possible_queries = [
        {"username_lc": normalized.lower()},
        {"username": {"$regex": f"^{re.escape(driver_name)}$", "$options": "i"}},
        {"display_name": {"$regex": f"^{re.escape(driver_name)}$", "$options": "i"}},
        {"discord_username": {"$regex": f"^{re.escape(driver_name)}$", "$options": "i"}},
    ]

    for query in possible_queries:
        user = users_collection.find_one(query)
        if user: return user
    return None


def get_current_user():
    user_session = session.get("user")
    if not user_session: return None

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
    if not file or not file.filename: return None
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
    if custom_avatar: return custom_avatar

    discord_id = user_doc.get("discord_id")
    avatar_hash = user_doc.get("avatar")

    if discord_id and avatar_hash:
        extension = "gif" if str(avatar_hash).startswith("a_") else "png"
        return f"https://cdn.discordapp.com/avatars/{discord_id}/{avatar_hash}.{extension}?size=256"

    return url_for("static", filename="eifellog.jpg")


def make_external_url(possible_url):
    possible_url = safe_str(possible_url)
    if not possible_url: return ""
    if possible_url.startswith("http://") or possible_url.startswith("https://"): return possible_url
    if possible_url.startswith("/"): return request.host_url.rstrip("/") + possible_url
    return request.host_url.rstrip("/") + "/" + possible_url.lstrip("/")


def format_datetime_for_template(value):
    if isinstance(value, datetime):
        return value.strftime("%d.%m.%Y %H:%M")
    if value:
        return str(value)
    return ""


def datetime_to_iso(value):
    if isinstance(value, datetime):
        return value.isoformat() + "Z"
    if value:
        return str(value)
    return ""


def parse_number(value, fallback=0.0):
    if value is None: return fallback
    if isinstance(value, (int, float)): return float(value)

    value = str(value).replace("km", "").replace("KM", "").replace("€", "").replace("%", "").replace(".", "").replace(",", ".").strip()
    try:
        return float(value)
    except Exception:
        return fallback


def parse_int(value, fallback=0):
    try:
        return int(round(parse_number(value, fallback)))
    except Exception:
        return fallback

# AKTENZEICHEN GENERIEREN
def generate_aktenzeichen():
    part1 = "".join(secrets.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ") for _ in range(2))
    part2 = "".join(secrets.choice("0123456789") for _ in range(5))
    return f"AZ-{part1}-{part2}"

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
    profile_data["aktenzeichen"] = profile_data.get("aktenzeichen") or "Nicht vergeben"

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
        "jobs": user_doc.get("profile_jobs", user_doc.get("profile_deliveries", "0")),
        "convoys": user_doc.get("profile_convoys", "0"),
        "rating": user_doc.get("profile_rating", "0.0"),
        "income": user_doc.get("profile_income", user_doc.get("profile_revenue", "0")),
        "revenue": user_doc.get("profile_revenue", user_doc.get("profile_income", "0"))
    }


def load_json_file(path):
    if not os.path.exists(path): return []
    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception as error:
        print(f"Fehler beim Laden von {path}: {error}")
        return []


# ==========================================
# SYSTEM-DOKUMENTE / FAHRER-REGISTRIERUNG
# ==========================================

def object_id_or_none(value):
    value = safe_str(value)
    if value and ObjectId.is_valid(value):
        return ObjectId(value)
    return None


def request_lookup_query(request_id):
    request_id = safe_str(request_id)
    query_items = [{"request_id": request_id}, {"id": request_id}]
    object_id = object_id_or_none(request_id)
    if object_id:
        query_items.append({"_id": object_id})
    return {"$or": query_items}


def current_staff_identity():
    session_user = session.get("user") or {}
    discord_id = safe_str(session_user.get("id"))
    username = safe_str(session_user.get("username") or session_user.get("discord_username"), "Personalabteilung")

    db_user = None
    if discord_id:
        db_user = users_collection.find_one({"discord_id": discord_id})

    display_name = username
    if db_user:
        display_name = (db_user.get("display_name") or db_user.get("username") or db_user.get("discord_username") or username)

    return {
        "discord_id": discord_id,
        "username": username,
        "display_name": display_name,
        "at": now_utc()
    }


def request_is_claimed_by_actor(request_doc, actor):
    claimed_by = request_doc.get("claimed_by") or {}
    claimed_discord_id = safe_str(claimed_by.get("discord_id"))
    actor_discord_id = safe_str(actor.get("discord_id"))
    return bool(claimed_discord_id and actor_discord_id and claimed_discord_id == actor_discord_id)


def require_request_claimed_by_actor(request_doc, actor):
    status = safe_str(request_doc.get("status"), "pending")

    if status != "claimed":
        return jsonify({
            "success": False,
            "message": "Dieser Antrag muss zuerst geclaimt werden. Claimen übernimmt nur die Bearbeitung und gibt den Antrag nicht frei."
        }), 409

    if not request_is_claimed_by_actor(request_doc, actor):
        claimed_by = request_doc.get("claimed_by") or {}
        claimed_name = claimed_by.get("display_name") or claimed_by.get("username") or "einem anderen Sachbearbeiter"
        return jsonify({
            "success": False,
            "message": f"Dieser Antrag ist bereits von {claimed_name} geclaimt. Nur der zuständige Sachbearbeiter kann ihn annehmen oder ablehnen."
        }), 403

    return None


def calculate_registration_deadline(start_time=None):
    start_time = start_time or now_utc()
    is_workday = start_time.weekday() < 5
    is_business_time = 9 <= start_time.hour < 18
    hours = 1 if is_workday and is_business_time else 2
    deadline = start_time + timedelta(hours=hours)
    return deadline, f"{hours} Stunde" if hours == 1 else f"{hours} Stunden"


def create_system_document_for_user(discord_id, title, sender, content, doc_type="system", needs_signature=False, extra=None):
    now = now_utc()
    doc = {
        "document_id": uuid.uuid4().hex,
        "discord_id": str(discord_id),
        "title": safe_str(title, "System Dokument"),
        "sender": safe_str(sender, "System"),
        "date": now.strftime("%d.%m.%Y %H:%M"),
        "content": content or "",
        "type": doc_type,
        "needs_signature": bool(needs_signature),
        "created_at": now,
        "read": False,
        "is_alert": extra.get("important", False) if extra else False # Mark as important
    }
    if extra:
        doc.update(extra)

    system_documents_collection.insert_one(doc)
    return doc


def prepare_system_document_for_dashboard(document):
    return {
        "title": document.get("title") or "System Dokument",
        "sender": document.get("sender") or "System",
        "date": document.get("date") or format_datetime_for_template(document.get("created_at")) or "Heute",
        "content": document.get("content") or "",
        "needs_signature": bool(document.get("needs_signature", False)),
        "type": document.get("type") or "system",
        "is_alert": document.get("is_alert", False)
    }


def get_system_documents_for_user(discord_id, limit=30, user_doc=None, latest_registration=None):
    discord_id = safe_str(discord_id)
    if not discord_id: return []

    registration_approved = user_registration_is_approved(discord_id, user_doc=user_doc, latest_registration=latest_registration)
    approved_ids = approved_registration_request_ids(discord_id, user_doc=user_doc, latest_registration=latest_registration)

    documents = system_documents_collection.find(
        {"discord_id": discord_id, "archived": {"$ne": True}, "hidden": {"$ne": True}},
        {"_id": 0}
    ).sort("created_at", DESCENDING).limit(limit)

    prepared_documents = []

    for document in documents:
        if document_contains_tracker_code(document):
            if not registration_approved:
                continue
            document_request_id = safe_str(document.get("registration_request_id") or document.get("request_id"))
            if approved_ids:
                if not document_request_id or document_request_id not in approved_ids:
                    continue
        prepared_documents.append(prepare_system_document_for_dashboard(document))

    return prepared_documents


def get_latest_registration_request_for_user(discord_id):
    return fahrer_registration_collection.find_one(
        {"discord_id": str(discord_id), "archived": {"$ne": True}},
        sort=[("created_at", DESCENDING)]
    )


def get_latest_token_request_for_user(discord_id):
    return token_request_collection.find_one(
        {"discord_id": str(discord_id), "archived": {"$ne": True}},
        sort=[("created_at", DESCENDING)]
    )

TOKEN_DOCUMENT_TYPES = {"driver_registration_approval", "new_token_approval", "manual_token_create"}

def registration_public_id(request_doc):
    if not request_doc: return ""
    return safe_str(request_doc.get("request_id") or request_doc.get("_id"))

def document_contains_tracker_code(document):
    document_type = safe_str(document.get("type"))
    if document.get("contains_tracker_code") is True: return True
    if document_type in TOKEN_DOCUMENT_TYPES: return True
    title = safe_str(document.get("title")).lower()
    return "token" in title or "tracker" in title

def user_registration_is_approved(discord_id, user_doc=None, latest_registration=None):
    discord_id = safe_str(discord_id)
    if not discord_id: return False

    if latest_registration is None:
        latest_registration = get_latest_registration_request_for_user(discord_id)

    if latest_registration:
        return safe_str(latest_registration.get("status")) == "approved"

    if user_doc:
        return safe_str(user_doc.get("fahrer_registration_status")) == "approved"
    return False

def approved_registration_request_ids(discord_id, user_doc=None, latest_registration=None):
    discord_id = safe_str(discord_id)
    approved_ids = set()
    if not discord_id: return approved_ids

    if latest_registration is None:
        latest_registration = get_latest_registration_request_for_user(discord_id)

    if latest_registration and safe_str(latest_registration.get("status")) == "approved":
        latest_public_id = registration_public_id(latest_registration)
        if latest_public_id: approved_ids.add(latest_public_id)
        if latest_registration.get("_id"): approved_ids.add(str(latest_registration.get("_id")))
        if latest_registration.get("request_id"): approved_ids.add(str(latest_registration.get("request_id")))
    elif user_doc and safe_str(user_doc.get("fahrer_registration_status")) == "approved":
        request_id = safe_str(user_doc.get("fahrer_registration_request_id"))
        if request_id: approved_ids.add(request_id)

    return approved_ids

def archive_token_documents_for_user(discord_id, reason=""):
    discord_id = safe_str(discord_id)
    if not discord_id: return

    now = now_utc()
    system_documents_collection.update_many(
        {
            "discord_id": discord_id,
            "$or": [
                {"contains_tracker_code": True},
                {"type": {"$in": list(TOKEN_DOCUMENT_TYPES)}},
                {"title": {"$regex": "token|tracker", "$options": "i"}}
            ]
        },
        {
            "$set": {
                "archived": True,
                "hidden": True,
                "archived_at": now,
                "archived_reason": safe_str(reason, "registration_reset")
            }
        }
    )

def reset_registration_state_for_recreated_user(discord_id):
    discord_id = safe_str(discord_id)
    if not discord_id: return

    now = now_utc()
    archive_token_documents_for_user(discord_id, reason="user_account_recreated")

    fahrer_registration_collection.update_many(
        {"discord_id": discord_id, "archived": {"$ne": True}},
        {
            "$set": {
                "archived": True,
                "status": "archived",
                "archived_at": now,
                "archived_reason": "User-Account wurde neu angelegt. Alte Fahrer-Freigaben wurden zurückgesetzt.",
                "updated_at": now
            }
        }
    )

    token_request_collection.update_many(
        {"discord_id": discord_id, "archived": {"$ne": True}},
        {
            "$set": {
                "archived": True,
                "status": "archived",
                "archived_at": now,
                "archived_reason": "User-Account wurde neu angelegt. Alte Token-Anfragen wurden zurückgesetzt.",
                "updated_at": now
            }
        }
    )


def dashboard_registration_context(user_doc, latest_request=None):
    user_doc = user_doc or {}
    latest_request = latest_request or get_latest_registration_request_for_user(user_doc.get("discord_id"))
    status = safe_str(user_doc.get("fahrer_registration_status"))

    if latest_request and latest_request.get("status"):
        status = safe_str(latest_request.get("status"))

    if not status: status = "none"

    handler = "Noch nicht zugewiesen"
    if latest_request:
        claimed_by = latest_request.get("claimed_by") or {}
        approved_by = latest_request.get("approved_by") or {}
        rejected_by = latest_request.get("rejected_by") or {}
        handler = (approved_by.get("display_name") or rejected_by.get("display_name") or claimed_by.get("display_name") or latest_request.get("handler_name") or handler)

    if user_doc.get("fahrer_registration_handler"): handler = user_doc.get("fahrer_registration_handler")

    requested_at = "-"
    deadline_display = "1-2 Stunden je nach Uhrzeit und Tag"
    note = ""
    name = user_doc.get("display_name") or user_doc.get("username") or user_doc.get("discord_username") or ""
    role = get_primary_role_name(user_doc.get("roles", []))

    if latest_request:
        name = latest_request.get("name") or name
        role = latest_request.get("role") or role
        requested_at = format_datetime_for_template(latest_request.get("created_at")) or "-"
        deadline_display = latest_request.get("deadline_display") or format_datetime_for_template(latest_request.get("deadline_at")) or deadline_display
        note = latest_request.get("note") or latest_request.get("reject_reason") or ""

    return {
        "fahrer_registration_status": status,
        "fahrer_registration_name": name,
        "fahrer_registration_role": role,
        "fahrer_registration_handler": handler,
        "fahrer_registration_deadline": deadline_display,
        "fahrer_registration_requested_at": requested_at,
        "fahrer_registration_note": note,
        "fahrer_token_value": "",
        "fahrer_token_created_at": format_datetime_for_template(user_doc.get("tracker_code_created_at")) or "Heute"
    }


def tracker_confirmation_document_content(name, role, handler_name, tracker_code, reason=None):
    reason_block = ""
    if reason:
        reason_block = f'<p class="mt-4"><strong>Grund / Hinweis:</strong><br>{reason}</p>'

    return f"""
        <p><strong>Bestätigung Fahrer Registrierung</strong></p>
        <p class="mt-4">
            Hiermit wird bestätigt, dass <strong>{name}</strong> mit der Rolle
            <strong>{role}</strong> durch die Personalabteilung genehmigt wurde.
        </p>
        <p class="mt-4">
            <strong>Sachbearbeiter:</strong> {handler_name}<br>
            <strong>Freigabe:</strong> {now_utc().strftime('%d.%m.%Y %H:%M')}
        </p>
        {reason_block}
        <div class="mt-5 rounded-2xl bg-black/50 border border-[var(--brand-green)]/25 p-4">
            <p class="text-[10px] font-orbitron text-[var(--brand-green)] uppercase tracking-widest mb-2">Persönlicher Tracker Token</p>
            <p class="text-lg font-orbitron font-bold text-white break-all">{tracker_code}</p>
        </div>
        <p class="mt-4 text-xs text-gray-400">
            Bewahre diesen Token sicher auf. Gib ihn nicht öffentlich weiter.
        </p>
    """

def rejection_document_content(title, reason, handler_name):
    reason = safe_str(reason, "Kein Grund angegeben.")
    return f"""
        <p><strong>{title}</strong></p>
        <p class="mt-4">
            Dein Antrag wurde durch die Personalabteilung abgelehnt.
        </p>
        <p class="mt-4"><strong>Sachbearbeiter:</strong> {handler_name}</p>
        <div class="mt-5 rounded-2xl bg-black/50 border border-[var(--danger)]/25 p-4">
            <p class="text-[10px] font-orbitron text-[var(--danger)] uppercase tracking-widest mb-2">Begründung</p>
            <p>{reason}</p>
        </div>
    """

def create_tracker_code_for_user_doc(user_doc, actor=None, allow_unapproved=False):
    if not user_doc: raise ValueError("User-Dokument fehlt.")

    actor = actor or current_staff_identity()
    discord_id = safe_str(user_doc.get("discord_id"))

    if not allow_unapproved and not user_registration_is_approved(discord_id, user_doc=user_doc):
        raise PermissionError("Tracker-Token darf erst erstellt werden, nachdem die Personalabteilung den Fahrer-Antrag angenommen hat.")

    tracker_code = generate_tracker_code()

    users_collection.update_one(
        {"_id": user_doc["_id"]},
        {
            "$set": {
                "tracker_code_hash": hash_secret(tracker_code),
                "tracker_code_created_at": now_utc(),
                "tracker_enabled": True,
                "tracker_code_created_by": actor
            },
            "$unset": {"tracker_code": ""}
        }
    )
    return tracker_code

def prepare_registration_request_for_personalabteilung(request_doc):
    item = dict(request_doc)
    item["id"] = str(item.get("_id") or item.get("request_id") or "")
    item["request_id"] = item.get("request_id") or item["id"]
    item["name"] = item.get("name") or item.get("display_name") or item.get("username") or "Unbekannter User"
    item["username"] = item.get("username") or item.get("discord_username") or item["name"]
    item["role"] = item.get("role") or "Fahrer"
    item["status"] = item.get("status") or "pending"
    item["created_at"] = format_datetime_for_template(item.get("created_at")) or "-"
    item["requested_at"] = item["created_at"]
    item["deadline_display"] = item.get("deadline_display") or format_datetime_for_template(item.get("deadline_at")) or "1-2 Stunden"
    item["deadline_iso"] = datetime_to_iso(item.get("deadline_at"))
    item["avatar_url"] = item.get("avatar_url") or ""

    claimed_by = item.get("claimed_by") or {}
    approved_by = item.get("approved_by") or {}
    rejected_by = item.get("rejected_by") or {}

    item["claimed_by_name"] = (approved_by.get("display_name") or rejected_by.get("display_name") or claimed_by.get("display_name") or "Noch nicht geclaimt")
    item["handler_name"] = item["claimed_by_name"]
    item["sachbearbeiter_name"] = item["claimed_by_name"]
    item["note"] = item.get("note") or item.get("reject_reason") or ""

    return item

def prepare_token_request_for_personalabteilung(request_doc):
    item = dict(request_doc)
    item["id"] = str(item.get("_id") or item.get("request_id") or "")
    item["request_id"] = item.get("request_id") or item["id"]
    item["name"] = item.get("name") or item.get("display_name") or item.get("username") or "Unbekannter User"
    item["username"] = item.get("username") or item.get("discord_username") or item["name"]
    item["role"] = item.get("role") or "Fahrer"
    item["status"] = item.get("status") or "pending"
    item["created_at"] = format_datetime_for_template(item.get("created_at")) or "-"
    item["requested_at"] = item["created_at"]
    item["reason"] = item.get("reason") or "Kein Grund angegeben"
    item["avatar_url"] = item.get("avatar_url") or ""
    return item

def find_user_for_request_doc(request_doc):
    discord_id = safe_str(request_doc.get("discord_id") or request_doc.get("user_id"))
    if discord_id:
        user_doc = users_collection.find_one({"discord_id": discord_id})
        if user_doc: return user_doc

    username = safe_str(request_doc.get("username"))
    if username: return find_user_by_username(username)
    return None

def get_activity_for_user(username):
    items = profile_activity_collection.find({"username_lc": username.lower()}, {"_id": 0}).sort("created_at", -1).limit(10)
    return list(items)

def get_gallery_for_user(username):
    items = profile_gallery_collection.find({"username_lc": username.lower()}, {"_id": 0}).sort("created_at", -1).limit(12)
    return list(items)

# ==========================================
# TRACKER CODE / TOKEN HILFSFUNKTIONEN
# ==========================================

def hash_secret(value):
    value = safe_str(value)
    if not value: return ""
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
    return safe_str(code).upper().replace(" ", "")

def get_client_token_from_request(data=None):
    data = data or {}
    authorization = safe_str(request.headers.get("Authorization"))
    if authorization.lower().startswith("bearer "): authorization = authorization[7:].strip()
    return (safe_str(data.get("clientToken")) or safe_str(request.headers.get("X-Tracker-Token")) or authorization or safe_str(request.args.get("clientToken")))

def find_tracker_user_by_client_token(client_token):
    client_token = safe_str(client_token)
    if not client_token: return None
    return users_collection.find_one({"tracker_client_token_hash": hash_secret(client_token)})

def user_has_tracker_access(user_doc):
    if not user_doc: return False
    if user_doc.get("tracker_enabled") is False: return False
    return user_registration_is_approved(user_doc.get("discord_id"), user_doc=user_doc)

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
            "jobs": stats.get("jobs"),
            "convoys": stats.get("convoys"),
            "rating": stats.get("rating"),
            "income": stats.get("income"),
            "revenue": stats.get("revenue")
        }
    }

def tracker_api_key_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not TRACKER_API_KEY:
            return jsonify({"success": False, "error": "TRACKER_API_KEY ist serverseitig nicht konfiguriert."}), 500

        provided_key = request.headers.get("X-Tracker-Api-Key") or request.args.get("api_key")
        if not secure_compare(provided_key, TRACKER_API_KEY):
            return jsonify({"success": False, "error": "Ungültiger API-Key."}), 401

        return func(*args, **kwargs)
    return wrapper


# ==========================================
# TRACKER LIVE STATE / COMPANY / LOGBOOK
# ==========================================

def normalize_telemetry_payload(raw):
    raw = raw or {}
    def n(*keys, fallback=0):
        for key in keys:
            if key in raw and raw.get(key) is not None: return parse_number(raw.get(key), fallback)
        return fallback
    def s(*keys, fallback="-"):
        for key in keys:
            value = safe_str(raw.get(key))
            if value: return value
        return fallback
    def b(*keys, fallback=False):
        for key in keys:
            if key in raw:
                value = raw.get(key)
                if isinstance(value, bool): return value
                if isinstance(value, str): return value.lower() in {"true", "1", "yes", "ja"}
                return bool(value)
        return fallback

    clean = {
        "isConnected": b("isConnected", "telemetryConnected", fallback=False),
        "gameProcessDetected": b("gameProcessDetected", fallback=False),
        "telemetryConnected": b("telemetryConnected", "isConnected", fallback=False),
        "statusText": s("statusText", fallback=""),
        "game": s("game", fallback="ETS2/ATS"),
        "truck": s("truck", "driverTruckModel", fallback="-"),
        "sourceCity": s("sourceCity", "routeOrigin", fallback="-"),
        "destinationCity": s("destinationCity", "routeDestination", "activeDestination", fallback="-"),
        "cargo": s("cargo", "cargoName", fallback="-"),
        "speedKmh": n("speedKmh", "speed", fallback=0),
        "rpm": n("rpm", "engineRpm", "engineRPM", fallback=0),
        "fuelPercent": n("fuelPercent", "fuel", fallback=0),
        "damagePercent": n("damagePercent", "damage", fallback=0),
        "tripDistanceKm": n("tripDistanceKm", "driverKm", fallback=0),
        "remainingDistanceKm": n("remainingDistanceKm", "routeRemainingDistance", fallback=0),
        "plannedDistanceKm": n("plannedDistanceKm", fallback=0),
        "routeProgressPercent": n("routeProgressPercent", fallback=0),
        "engineEnabled": b("engineEnabled", fallback=False),
        "parkingBrake": b("parkingBrake", fallback=False),
        "driverName": s("driverName", fallback=""),
        "timestampUtc": now_utc().isoformat() + "Z"
    }

    if clean["destinationCity"] == "Freie Fahrt": clean["destinationCity"] = "-"
    return clean

def current_job_from_live(live):
    live = live or {}
    destination = live.get("destinationCity") or "-"
    source = live.get("sourceCity") or "-"
    cargo = live.get("cargo") or "-"

    if destination == "-" and source == "-" and cargo == "-": return None

    return {
        "sourceCity": source,
        "destinationCity": destination,
        "cargo": cargo,
        "distanceKm": parse_number(live.get("plannedDistanceKm"), 0),
        "remainingDistanceKm": parse_number(live.get("remainingDistanceKm"), 0),
        "income": round(parse_number(live.get("tripDistanceKm"), 0) * 3.2),
        "status": "Aktiv" if live.get("telemetryConnected") else "Warte"
    }

def get_user_job_entries(user_doc):
    result = []
    possible_fields = ["job_history", "jobs", "deliveries", "logbook", "tracker_logbook"]
    for field in possible_fields:
        items = user_doc.get(field)
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict): result.append(item)
    return result

def normalize_logbook_entry(entry, user_doc=None):
    user_doc = user_doc or {}
    source = safe_str(entry.get("sourceCity") or entry.get("source") or entry.get("from") or entry.get("routeOrigin"), "-")
    destination = safe_str(entry.get("destinationCity") or entry.get("destination") or entry.get("to") or entry.get("routeDestination"), "-")
    route = safe_str(entry.get("route"))
    if not route: route = f"{source} → {destination}"

    distance = parse_number(entry.get("distanceKm") or entry.get("distance") or entry.get("tripDistanceKm"), 0)
    income = parse_number(entry.get("income") or entry.get("revenue") or entry.get("money"), 0)

    created_at = entry.get("createdAt") or entry.get("created_at") or entry.get("finishedAt") or entry.get("timestamp") or ""
    if isinstance(created_at, datetime):
        created_at_text = created_at.isoformat() + "Z"
        sort_date = created_at
    else:
        created_at_text = safe_str(created_at)
        sort_date = datetime.min

    return {
        "status": safe_str(entry.get("status"), "Fertig"),
        "route": route,
        "sourceCity": source,
        "destinationCity": destination,
        "cargo": safe_str(entry.get("cargo") or entry.get("cargoName"), "-"),
        "distanceKm": distance,
        "income": income,
        "driverName": (user_doc.get("display_name") or user_doc.get("username") or user_doc.get("discord_username") or "EifelLog Fahrer"),
        "createdAt": created_at_text,
        "_sortDate": sort_date
    }

def build_active_driver_payload(user_doc):
    live = user_doc.get("tracker_live") or {}
    display_name = (user_doc.get("display_name") or user_doc.get("username") or user_doc.get("discord_username") or "EifelLog Fahrer")

    return {
        "driverName": display_name,
        "displayName": display_name,
        "username": user_doc.get("username"),
        "discordId": user_doc.get("discord_id"),
        "avatarUrl": make_external_url(get_discord_avatar_url(user_doc)),
        "game": live.get("game") or "ETS2/ATS",
        "truck": live.get("truck") or "-",
        "destinationCity": live.get("destinationCity") or "-",
        "cargo": live.get("cargo") or "-",
        "speedKmh": parse_number(live.get("speedKmh"), 0),
        "isOnline": bool(user_doc.get("tracker_online", False)),
        "lastSeen": datetime_to_iso(user_doc.get("tracker_live_updated_at"))
    }

def get_active_drivers():
    since = now_utc() - timedelta(minutes=2)
    users = users_collection.find({
        "tracker_online": True,
        "tracker_live_updated_at": {"$gte": since}
    }).sort("tracker_live_updated_at", DESCENDING)
    return [build_active_driver_payload(user) for user in users]

def build_logbook_payload(limit=30):
    entries = []
    for user_doc in users_collection.find({}):
        for raw_entry in get_user_job_entries(user_doc):
            entries.append(normalize_logbook_entry(raw_entry, user_doc))

        live = user_doc.get("tracker_live") or {}
        updated_at = user_doc.get("tracker_live_updated_at")

        if user_doc.get("tracker_online") and isinstance(updated_at, datetime):
            if updated_at >= now_utc() - timedelta(minutes=2):
                current_job = current_job_from_live(live)
                if current_job:
                    entries.append({
                        "status": "Aktiv",
                        "route": f"{current_job.get('sourceCity', '-')} → {current_job.get('destinationCity', '-')}",
                        "sourceCity": current_job.get("sourceCity", "-"),
                        "destinationCity": current_job.get("destinationCity", "-"),
                        "cargo": current_job.get("cargo", "-"),
                        "distanceKm": parse_number(live.get("tripDistanceKm"), 0),
                        "income": round(parse_number(live.get("tripDistanceKm"), 0) * 3.2),
                        "driverName": (user_doc.get("display_name") or user_doc.get("username") or user_doc.get("discord_username") or "EifelLog Fahrer"),
                        "createdAt": datetime_to_iso(updated_at),
                        "_sortDate": updated_at
                    })

    entries.sort(key=lambda item: item.get("_sortDate") or datetime.min, reverse=True)
    clean_entries = []
    for entry in entries[:limit]:
        entry.pop("_sortDate", None)
        clean_entries.append(entry)
    return clean_entries

def build_company_stats_payload():
    users = list(users_collection.find({}))
    company_income = 0.0
    company_km = 0.0
    jobs_all_time = 0
    deliveries = 0

    monthly_kilometers = [0, 0, 0, 0, 0, 0]
    income_series = [0, 0, 0, 0, 0, 0]

    for user_doc in users:
        stats = get_profile_stats(user_doc)
        user_km = parse_number(stats.get("km"), 0)
        user_income = parse_number(stats.get("income") or stats.get("revenue"), 0)
        user_deliveries = parse_int(stats.get("deliveries"), 0)
        user_jobs = parse_int(stats.get("jobs"), user_deliveries)

        live = user_doc.get("tracker_live") or {}
        live_km = parse_number(live.get("tripDistanceKm"), 0)
        live_income = round(live_km * 3.2)

        company_km += user_km + live_km
        company_income += user_income + live_income
        jobs_all_time += user_jobs
        deliveries += user_deliveries

        job_entries = get_user_job_entries(user_doc)
        if job_entries:
            for job in job_entries:
                distance = parse_number(job.get("distanceKm") or job.get("distance") or job.get("tripDistanceKm"), 0)
                income = parse_number(job.get("income") or job.get("revenue") or job.get("money"), 0)
                monthly_kilometers[-1] += distance
                income_series[-1] += income
        else:
            monthly_kilometers[-1] += user_km + live_km
            income_series[-1] += user_income + live_income

    active_driver_count = len(get_active_drivers())

    return {
        "companyIncome": round(company_income),
        "income": round(company_income),
        "revenue": round(company_income),
        "allTimeKilometers": round(company_km, 1),
        "allTimeKm": round(company_km, 1),
        "kilometers": round(company_km, 1),
        "jobsAllTime": jobs_all_time,
        "jobs": jobs_all_time,
        "totalJobs": jobs_all_time,
        "deliveries": deliveries,
        "totalDeliveries": deliveries,
        "activeDrivers": active_driver_count,
        "monthlyKilometers": monthly_kilometers,
        "incomeSeries": income_series
    }

def tracker_state_payload(user_doc):
    active_drivers = get_active_drivers()
    company_stats = build_company_stats_payload()
    logbook = build_logbook_payload(limit=30)
    live = user_doc.get("tracker_live") or {}
    current_job = current_job_from_live(live)

    return {
        "success": True,
        "profile": tracker_profile_payload(user_doc),
        "company": company_stats,
        "companyStats": company_stats,
        "currentJob": current_job,
        "logbook": logbook,
        "lastDeliveries": logbook,
        "activeDrivers": active_drivers
    }

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
        f"{OAUTH_URL}?client_id={DISCORD_CLIENT_ID}&redirect_uri={DISCORD_REDIRECT_URI}&response_type=code&scope=identify%20guilds%20guilds.members.read"
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

    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    token_response = requests.post(TOKEN_URL, data=token_payload, headers=headers)

    if token_response.status_code != 200:
        flash("Fehler bei der Discord-Kommunikation. Bitte Client ID/Secret prüfen.", "error")
        return redirect(url_for("home"))

    token = token_response.json().get("access_token")
    if not token:
        flash("Discord hat kein gültiges Access Token zurückgegeben.", "error")
        return redirect(url_for("home"))

    auth_headers = {"Authorization": f"Bearer {token}"}
    user_response = requests.get(f"{API_BASE_URL}/users/@me", headers=auth_headers)

    if user_response.status_code != 200:
        flash("Discord-Benutzerdaten konnten nicht geladen werden.", "error")
        return redirect(url_for("home"))

    user_data = user_response.json()
    member_response = requests.get(f"{API_BASE_URL}/users/@me/guilds/{DISCORD_GUILD_ID}/member", headers=auth_headers)

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

    if not existing_user:
        reset_registration_state_for_recreated_user(discord_id)

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
                "profile_rating": "0.0",
                "profile_income": "0",
                "aktenzeichen": generate_aktenzeichen() # Aktenzeichen bei Erstellung!
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
# TRACKER API
# ==========================================

@app.route("/api/tracker/login", methods=["GET", "POST", "OPTIONS"])
def tracker_login():
    if request.method == "OPTIONS": return jsonify({"success": True})
    if request.method == "GET": return jsonify({"success": False, "message": "Method not allowed"}), 200

    data = request.get_json(silent=True) or {}
    driver_name = safe_str(data.get("driverName"))
    tracker_code = normalize_tracker_code(data.get("trackerCode") or data.get("accessCode"))
    remember = bool(data.get("remember", True))

    if not driver_name or not tracker_code: return jsonify({"success": False, "error": "Fehlende Daten."}), 400

    user_doc = find_user_for_tracker_name(driver_name)
    if not user_doc: return jsonify({"success": False, "error": "Fahrer wurde nicht gefunden."}), 404
    if not user_has_tracker_access(user_doc): return jsonify({"success": False, "error": "Zugriff deaktiviert."}), 403

    incoming_code_hash = hash_secret(tracker_code)
    stored_hash = user_doc.get("tracker_code_hash", "")
    legacy_plain_code = normalize_tracker_code(user_doc.get("tracker_code"))

    valid_code = False
    if stored_hash and secure_compare(incoming_code_hash, stored_hash): valid_code = True
    if legacy_plain_code and secure_compare(tracker_code, legacy_plain_code):
        valid_code = True
        users_collection.update_one({"_id": user_doc["_id"]}, {"$set": {"tracker_code_hash": incoming_code_hash, "tracker_code_migrated_at": now_utc()}, "$unset": {"tracker_code": ""}})

    if not valid_code: return jsonify({"success": False, "error": "Code ist ungültig."}), 401

    client_token = generate_client_token()
    client_token_hash = hash_secret(client_token)

    users_collection.update_one(
        {"_id": user_doc["_id"]},
        {
            "$set": {
                "tracker_client_token_hash": client_token_hash,
                "tracker_last_login": now_utc(),
                "tracker_last_driver_name": driver_name,
                "tracker_enabled": True,
                "tracker_online": True
            },
            "$inc": {"tracker_login_count": 1}
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
    if request.method == "OPTIONS": return jsonify({"success": True})
    if request.method == "GET": return jsonify({"success": False, "message": "Method not allowed"}), 200

    data = request.get_json(silent=True) or {}
    client_token = get_client_token_from_request(data)
    if not client_token: return jsonify({"success": False, "error": "Fehlt"}), 401

    user_doc = find_tracker_user_by_client_token(client_token)
    if not user_doc: return jsonify({"success": False, "error": "Ungültig"}), 401
    if not user_has_tracker_access(user_doc): return jsonify({"success": False, "error": "Deaktiviert"}), 403

    users_collection.update_one({"_id": user_doc["_id"]}, {"$set": {"tracker_last_session_login": now_utc(), "tracker_online": True}})
    fresh_user = users_collection.find_one({"_id": user_doc["_id"]})

    return jsonify({"success": True, "message": "Tracker-Sitzung gültig.", "profile": tracker_profile_payload(fresh_user)})

@app.route("/api/tracker/profile", methods=["GET", "POST", "OPTIONS"])
def tracker_profile():
    if request.method == "OPTIONS": return jsonify({"success": True})
    data = request.get_json(silent=True) or {}
    client_token = get_client_token_from_request(data)
    if not client_token: return jsonify({"success": False, "error": "Fehlt"}), 401

    user_doc = find_tracker_user_by_client_token(client_token)
    if not user_doc: return jsonify({"success": False, "error": "Ungültig"}), 401
    if not user_has_tracker_access(user_doc): return jsonify({"success": False, "error": "Deaktiviert"}), 403

    return jsonify({"success": True, "profile": tracker_profile_payload(user_doc)})

@app.route("/api/tracker/state", methods=["GET", "POST", "OPTIONS"])
def tracker_state():
    if request.method == "OPTIONS": return jsonify({"success": True})
    data = request.get_json(silent=True) or {}
    client_token = get_client_token_from_request(data)
    if not client_token: return jsonify({"success": False, "error": "Fehlt"}), 401

    user_doc = find_tracker_user_by_client_token(client_token)
    if not user_doc: return jsonify({"success": False, "error": "Ungültig"}), 401
    if not user_has_tracker_access(user_doc): return jsonify({"success": False, "error": "Deaktiviert"}), 403

    users_collection.update_one({"_id": user_doc["_id"]}, {"$set": {"tracker_state_requested_at": now_utc()}})
    fresh_user = users_collection.find_one({"_id": user_doc["_id"]})

    return jsonify(tracker_state_payload(fresh_user))

@app.route("/api/tracker/telemetry/live", methods=["GET", "POST", "OPTIONS"])
def tracker_telemetry_live():
    if request.method == "OPTIONS": return jsonify({"success": True})
    if request.method == "GET": return jsonify({"success": False, "message": "Method not allowed"}), 200

    data = request.get_json(silent=True) or {}
    client_token = get_client_token_from_request(data)
    if not client_token: return jsonify({"success": False, "error": "Fehlt"}), 401

    user_doc = find_tracker_user_by_client_token(client_token)
    if not user_doc: return jsonify({"success": False, "error": "Ungültig"}), 401
    if not user_has_tracker_access(user_doc): return jsonify({"success": False, "error": "Deaktiviert"}), 403

    raw_telemetry = data.get("telemetry") or data.get("snapshot") or {}
    telemetry = normalize_telemetry_payload(raw_telemetry)

    is_online = bool(telemetry.get("isConnected") or telemetry.get("gameProcessDetected") or telemetry.get("telemetryConnected"))

    update_payload = {
        "tracker_live": telemetry,
        "tracker_live_updated_at": now_utc(),
        "tracker_online": is_online,
        "tracker_last_game": telemetry.get("game"),
        "tracker_last_truck": telemetry.get("truck"),
        "tracker_last_destination": telemetry.get("destinationCity"),
        "tracker_last_cargo": telemetry.get("cargo"),
        "tracker_last_speed_kmh": telemetry.get("speedKmh"),
        "tracker_last_fuel_percent": telemetry.get("fuelPercent"),
        "tracker_last_damage_percent": telemetry.get("damagePercent"),
        "tracker_last_trip_distance_km": telemetry.get("tripDistanceKm")
    }

    current_job = current_job_from_live(telemetry)
    if current_job: update_payload["tracker_current_job"] = current_job

    users_collection.update_one({"_id": user_doc["_id"]}, {"$set": update_payload})
    fresh_user = users_collection.find_one({"_id": user_doc["_id"]})

    return jsonify(tracker_state_payload(fresh_user))

@app.route("/api/tracker/logout", methods=["GET", "POST", "OPTIONS"])
def tracker_logout():
    if request.method == "OPTIONS": return jsonify({"success": True})
    if request.method == "GET": return jsonify({"success": False, "message": "Method not allowed"}), 200

    data = request.get_json(silent=True) or {}
    client_token = get_client_token_from_request(data)

    if client_token:
        users_collection.update_one(
            {"tracker_client_token_hash": hash_secret(client_token)},
            {"$unset": {"tracker_client_token_hash": ""}, "$set": {"tracker_logged_out_at": now_utc(), "tracker_online": False}}
        )

    return jsonify({"success": True, "message": "Tracker lokal abgemeldet."})

@app.route("/api/tracker/code/create", methods=["GET", "POST", "OPTIONS"])
@tracker_api_key_required
def tracker_create_code_admin():
    if request.method == "OPTIONS": return jsonify({"success": True})
    if request.method == "GET": return jsonify({"success": False, "message": "Method not allowed"}), 200

    data = request.get_json(silent=True) or {}
    driver_name = safe_str(data.get("driverName"))
    discord_id = safe_str(data.get("discordId"))
    force_new = bool(data.get("forceNew", False))

    if not driver_name and not discord_id: return jsonify({"success": False, "error": "driverName oder discordId fehlt."}), 400

    if discord_id: user_doc = users_collection.find_one({"discord_id": discord_id})
    else: user_doc = find_user_for_tracker_name(driver_name)

    if not user_doc: return jsonify({"success": False, "error": "Fahrer wurde nicht gefunden."}), 404
    if not user_registration_is_approved(user_doc.get("discord_id"), user_doc=user_doc):
        return jsonify({"success": False, "error": "Tracker-Code darf erst nach angenommener Fahrer-Registrierung erstellt werden."}), 403

    existing_hash = user_doc.get("tracker_code_hash")
    if existing_hash and not force_new:
        return jsonify({"success": True, "message": "Code existiert bereits.", "trackerCode": None, "driver": tracker_profile_payload(user_doc)})

    tracker_code = generate_tracker_code()

    users_collection.update_one(
        {"_id": user_doc["_id"]},
        {"$set": {"tracker_code_hash": hash_secret(tracker_code), "tracker_code_created_at": now_utc(), "tracker_enabled": True}, "$unset": {"tracker_code": ""}}
    )

    fresh_user = users_collection.find_one({"_id": user_doc["_id"]})
    return jsonify({"success": True, "message": "Tracker-Code erstellt.", "trackerCode": tracker_code, "driver": tracker_profile_payload(fresh_user)})

@app.route("/api/tracker/code/my", methods=["GET", "POST", "OPTIONS"])
def tracker_create_code_for_logged_in_user():
    if request.method == "OPTIONS": return jsonify({"success": True})
    return jsonify({"success": False, "message": "Tokens werden nicht automatisch erstellt. Bitte Personalabteilung kontaktieren."}), 403


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
    if not profile_user: abort(404)

    current_user = get_current_user()
    is_own_profile = (current_user is not None and str(current_user.get("discord_id")) == str(profile_user.get("discord_id")))

    if request.method == "POST":
        if not is_own_profile: abort(403)

        old_username = profile_user.get("username")
        new_username = normalize_username(request.form.get("username", old_username), fallback=old_username)

        if username_exists(new_username, exclude_discord_id=profile_user.get("discord_id")):
            flash("Dieser Benutzername ist bereits vergeben.", "error")
            return redirect(url_for("profile", username=old_username))

        uploaded_avatar = save_profile_image("avatar_file")
        uploaded_banner = save_profile_image("banner_file")

        avatar_url = uploaded_avatar or request.form.get("avatar_url", "").strip() or profile_user.get("avatar_url", "")
        banner_url = uploaded_banner or request.form.get("banner_url", "").strip() or profile_user.get("banner_url", "")

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
                    "username": new_username, "username_lc": new_username.lower(),
                    "display_name": display_name, "avatar_url": avatar_url, "banner_url": banner_url,
                    "rank": rank, "status": status, "bio": bio, "location": location, "discord": discord,
                    "truckersmp_id": truckersmp_id, "steam": steam, "website": website, "favorite_truck": favorite_truck,
                    "show_email": show_email, "show_discord": show_discord, "show_stats": show_stats,
                    "show_activity": show_activity, "public_profile": public_profile,
                    "updated_at": now, "last_seen": now.strftime("%d.%m.%Y %H:%M")
                }
            }
        )

        if new_username != old_username:
            profile_activity_collection.update_many({"username_lc": old_username.lower()}, {"$set": {"username": new_username, "username_lc": new_username.lower()}})
            profile_gallery_collection.update_many({"username_lc": old_username.lower()}, {"$set": {"username": new_username, "username_lc": new_username.lower()}})

        if isinstance(session.get("user"), dict):
            session["user"]["username"] = new_username
            session.modified = True

        flash("Profil wurde erfolgreich gespeichert.", "success")
        return redirect(url_for("profile", username=new_username))

    profile_data = prepare_profile_data(profile_user)
    stats = get_profile_stats(profile_user)
    activity = get_activity_for_user(profile_data["username"])
    gallery = get_gallery_for_user(profile_data["username"])

    return render_template("profile.html", profile=profile_data, is_own_profile=is_own_profile, stats=stats, activity=activity, gallery=gallery)


# ==========================================
# DRIVER HUB & DASHBOARD
# ==========================================

@app.route("/hub")
def hub():
    if "user" in session: return redirect(url_for("dashboard"))
    return render_template("hub.html")

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
        db_user = {
            "discord_id": str(user["id"]),
            "username": user.get("username"),
            "discord_username": user.get("discord_username"),
            "display_name": user.get("username"),
            "avatar": user.get("avatar"),
            "roles": user_roles
        }

    primary_role_name = get_primary_role_name(user_roles)
    news_items = load_json_file("news.json")

    user_documents = []
    all_documents = load_json_file("documents.json")
    user_id_str = str(user["id"])
    latest_registration = get_latest_registration_request_for_user(user_id_str)

    if not user_registration_is_approved(user_id_str, user_doc=db_user, latest_registration=latest_registration):
        archive_token_documents_for_user(user_id_str, reason="dashboard_non_approved_cleanup")

    for document in all_documents:
        if str(document.get("discord_id")) == user_id_str:
            user_documents.append(document)

    user_documents.extend(get_system_documents_for_user(user_id_str, user_doc=db_user, latest_registration=latest_registration))
    registration_context = dashboard_registration_context(db_user, latest_registration)

    return render_template("dashboard.html", current_user=user, needs_signature=needs_signature, primary_role_name=primary_role_name, news_items=news_items, user_documents=user_documents, **registration_context)


@app.route("/api/fahrer_registration", methods=["POST"])
def api_fahrer_registration():
    if "user" not in session: return jsonify({"success": False, "message": "Bitte zuerst einloggen."}), 401

    session_user = session.get("user") or {}
    discord_id = safe_str(session_user.get("id"))

    if not discord_id: return jsonify({"success": False, "message": "Session ist ungültig."}), 401

    db_user = users_collection.find_one({"discord_id": discord_id})
    if not db_user: return jsonify({"success": False, "message": "User wurde in der Datenbank nicht gefunden."}), 404

    data = request.get_json(silent=True) or {}
    name = safe_str(data.get("name"), db_user.get("display_name") or db_user.get("username") or "")[:80]
    role = safe_str(data.get("role"), get_primary_role_name(db_user.get("roles", [])))[:80]

    if len(name) < 2 or len(role) < 2: return jsonify({"success": False, "message": "Name und Rolle müssen ausgefüllt sein."}), 400

    existing_open = fahrer_registration_collection.find_one({"discord_id": discord_id, "archived": {"$ne": True}, "status": {"$in": ["pending", "open", "claimed"]}})
    if existing_open: return jsonify({"success": True, "message": "Du hast bereits eine offene Fahrer-Registrierung.", "requestId": str(existing_open.get("_id")), "status": existing_open.get("status", "pending")})

    now = now_utc()
    deadline_at, deadline_label = calculate_registration_deadline(now)
    request_id = uuid.uuid4().hex

    request_doc = {
        "request_id": request_id,
        "discord_id": discord_id,
        "user_id": discord_id,
        "username": db_user.get("username") or session_user.get("username"),
        "discord_username": db_user.get("discord_username") or session_user.get("discord_username"),
        "display_name": db_user.get("display_name") or db_user.get("username") or session_user.get("username"),
        "avatar_url": make_external_url(get_discord_avatar_url(db_user)),
        "name": name,
        "role": role,
        "status": "pending",
        "created_at": now,
        "updated_at": now,
        "deadline_at": deadline_at,
        "deadline_display": f"bis {deadline_at.strftime('%d.%m.%Y %H:%M')} ({deadline_label})",
        "source": "dashboard_quick_action",
        "note": "Antrag wurde über das Web Dashboard gestellt."
    }

    archive_token_documents_for_user(discord_id, reason="new_driver_registration_started")
    token_request_collection.update_many({"discord_id": discord_id, "status": {"$in": ["pending", "open", "claimed"]}}, {"$set": {"status": "rejected", "reject_reason": "Neue Fahrer-Registrierung gestartet.", "updated_at": now}})

    fahrer_registration_collection.insert_one(request_doc)
    users_collection.update_one({"discord_id": discord_id}, {"$set": {"fahrer_registration_status": "pending", "fahrer_registration_requested_at": now, "fahrer_registration_deadline_at": deadline_at, "fahrer_registration_name": name, "fahrer_registration_role": role, "fahrer_registration_request_id": request_id, "fahrer_registration_handler": "Noch nicht zugewiesen"}})

    # Automatische Aufgabe für Personalabteilung erstellen
    task_doc = {
        "title": f"Neue Registrierung: {name}",
        "type": "Onboarding",
        "priority": "high",
        "description": f"User {name} (@{request_doc['username']}) hat sich neu als {role} registriert. Bitte prüfen.",
        "status": "open",
        "created_at": now,
        "assignee": None
    }
    tasks_collection.insert_one(task_doc)

    return jsonify({"success": True, "message": "Deine Fahrer-Registrierung wurde an die Personalabteilung gesendet.", "requestId": request_id, "status": "pending", "deadline": request_doc["deadline_display"]})

@app.route("/api/new_token_request", methods=["POST"])
def api_new_token_request():
    if "user" not in session: return jsonify({"success": False, "message": "Bitte zuerst einloggen."}), 401
    session_user = session.get("user") or {}
    discord_id = safe_str(session_user.get("id"))
    if not discord_id: return jsonify({"success": False, "message": "Session ist ungültig."}), 401

    db_user = users_collection.find_one({"discord_id": discord_id})
    if not db_user: return jsonify({"success": False, "message": "User nicht gefunden."}), 404

    latest_registration = get_latest_registration_request_for_user(discord_id)
    is_approved = user_registration_is_approved(discord_id, user_doc=db_user, latest_registration=latest_registration)

    if not is_approved: return jsonify({"success": False, "message": "Du bist noch nicht als Fahrer genehmigt."}), 403

    existing_open = token_request_collection.find_one({"discord_id": discord_id, "archived": {"$ne": True}, "status": {"$in": ["pending", "open", "claimed"]}})
    if existing_open: return jsonify({"success": True, "message": "Du hast bereits eine offene Token-Anfrage.", "requestId": str(existing_open.get("_id")), "status": existing_open.get("status", "pending")})

    data = request.get_json(silent=True) or {}
    reason = safe_str(data.get("reason"), "Neuer Token wurde über das Dashboard angefordert.")[:400]
    now = now_utc()
    request_id = uuid.uuid4().hex

    approved_registration_id = registration_public_id(latest_registration) if latest_registration else safe_str(db_user.get("fahrer_registration_request_id"))

    request_doc = {
        "request_id": request_id,
        "registration_request_id": approved_registration_id,
        "discord_id": discord_id,
        "user_id": discord_id,
        "username": db_user.get("username") or session_user.get("username"),
        "discord_username": db_user.get("discord_username") or session_user.get("discord_username"),
        "display_name": db_user.get("display_name") or db_user.get("username") or session_user.get("username"),
        "avatar_url": make_external_url(get_discord_avatar_url(db_user)),
        "name": db_user.get("display_name") or db_user.get("username") or session_user.get("username"),
        "role": db_user.get("fahrer_registration_role") or get_primary_role_name(db_user.get("roles", [])),
        "reason": reason or "Kein Grund angegeben",
        "status": "pending",
        "created_at": now,
        "updated_at": now,
        "source": "dashboard_new_token"
    }

    token_request_collection.insert_one(request_doc)
    
    # Automatische Aufgabe für Personalabteilung erstellen
    task_doc = {
        "title": f"Neuer Token angefordert: {request_doc['name']}",
        "type": "Allgemein",
        "priority": "medium",
        "description": f"User {request_doc['name']} benötigt einen neuen Token. Grund: {reason}",
        "status": "open",
        "created_at": now,
        "assignee": None
    }
    tasks_collection.insert_one(task_doc)

    return jsonify({"success": True, "message": "Deine neue Token-Anfrage wurde an die Personalabteilung gesendet.", "requestId": request_id, "status": "pending"})


# ==========================================
# PERSONALABTEILUNG / BUCHHALTUNG / TASKS
# ==========================================

def has_personalabteilung_permission(user_roles):
    clean_user_roles = {str(role).strip() for role in user_roles if role}
    return bool(clean_user_roles.intersection(PERSONALABTEILUNG_ALLOWED_ROLES))

def require_personalabteilung_permission():
    if "user" not in session:
        flash("Bitte logge dich zuerst ein.", "error")
        return redirect(url_for("hub"))
    user_roles = session.get("user", {}).get("roles", [])
    if not has_personalabteilung_permission(user_roles):
        flash("Zugriff verweigert. Du benötigst Personalabteilung, Geschäftsführung oder Projektleitung.", "error")
        return redirect(url_for("dashboard"))
    return None

def require_personalabteilung_api_permission():
    if "user" not in session: return jsonify({"success": False, "message": "Bitte zuerst einloggen."}), 401
    user_roles = session.get("user", {}).get("roles", [])
    if not has_personalabteilung_permission(user_roles): return jsonify({"success": False, "message": "Nicht berechtigt."}), 403
    return None

def get_role_name_for_driver(user_doc):
    roles = {str(role).strip() for role in user_doc.get("roles", []) if role}
    if ROLE_GESCHAEFTSFUEHRUNG_ID in roles: return "Geschäftsführung"
    if ROLE_PROJEKTLEITUNG_ID in roles: return "Projektleitung"
    if ROLE_PERSONALABTEILUNG_ID in roles: return "Personalabteilung"
    return get_primary_role_name(user_doc.get("roles", []))

def prepare_driver_for_personalabteilung(user_doc):
    driver = dict(user_doc)
    driver["_id"] = str(driver.get("_id"))
    driver["display_name"] = (driver.get("display_name") or driver.get("username") or driver.get("discord_username") or "EifelLog Fahrer")
    driver["username"] = driver.get("username") or "driver"
    driver["username_lc"] = driver.get("username_lc") or str(driver["username"]).lower()
    driver["avatar_url"] = make_external_url(get_discord_avatar_url(driver))
    driver["banner_url"] = make_external_url(driver.get("banner_url"))
    driver["primary_role_name"] = get_role_name_for_driver(driver)
    driver["tracker_enabled"] = driver.get("tracker_enabled", True)
    driver["last_login"] = format_datetime_for_template(driver.get("last_login"))
    driver["tracker_last_login"] = format_datetime_for_template(driver.get("tracker_last_login"))
    driver["tracker_code_created_at"] = format_datetime_for_template(driver.get("tracker_code_created_at"))
    driver["aktenzeichen"] = driver.get("aktenzeichen", "Nicht vergeben")
    return driver


@app.route("/personalabteilung", methods=["GET"])
def personalabteilung():
    if "user" not in session:
        flash("Bitte logge dich zuerst ein.", "error")
        return redirect(url_for("hub"))
        
    user_roles = session.get("user", {}).get("roles", [])
    
    # Abfangen, ob es sich "nur" um Buchhaltung handelt (und nicht gleichzeitig PA/GF/PL)
    if ROLE_BUCHHALTUNG_ID in user_roles and not has_personalabteilung_permission(user_roles):
        return render_template("buchhaltung_form.html") # Ein eigenes einfaches Formular für Buchhaltung rendern.

    permission_response = require_personalabteilung_permission()
    if permission_response: return permission_response

    drivers_cursor = users_collection.find({}).sort([("display_name", ASCENDING), ("username", ASCENDING)])
    drivers = [prepare_driver_for_personalabteilung(d) for d in drivers_cursor]

    registration_requests_cursor = fahrer_registration_collection.find({"archived": {"$ne": True}}).sort([("created_at", DESCENDING)]).limit(250)
    registration_requests = [prepare_registration_request_for_personalabteilung(item) for item in registration_requests_cursor]

    token_requests_cursor = token_request_collection.find({"archived": {"$ne": True}}).sort([("created_at", DESCENDING)]).limit(250)
    token_requests = [prepare_token_request_for_personalabteilung(item) for item in token_requests_cursor]

    # Tasks abrufen
    tasks_cursor = tasks_collection.find({}).sort([("created_at", DESCENDING)]).limit(100)
    tasks = []
    for t in tasks_cursor:
        t["id"] = str(t["_id"])
        t["created_at"] = format_datetime_for_template(t.get("created_at"))
        tasks.append(t)

    return render_template(
        "Personalabteilung.html",
        drivers=drivers,
        fahrer_registration_requests=registration_requests,
        registration_requests=registration_requests,
        token_requests=token_requests,
        tasks=tasks
    )

# ==========================================
# BUCHHALTUNG / PERSONALABTEILUNG DOKUMENTE
# ==========================================

BUCHHALTUNG_ALLOWED_ROLES = {
    ROLE_BUCHHALTUNG_ID,
    ROLE_BUCHHALTUNG,
    ROLE_GESCHAEFTSFUEHRUNG_ID,
    ROLE_PROJEKTLEITUNG_ID,
    ROLE_GESCHAEFTSLEITUNG,
    ROLE_PROJEKTLEITUNG
}


def role_set(user_roles):
    return {str(role).strip() for role in (user_roles or []) if role and str(role).strip()}


def has_buchhaltung_permission(user_roles):
    return bool(role_set(user_roles).intersection(role_set(BUCHHALTUNG_ALLOWED_ROLES)))


def require_buchhaltung_permission():
    if "user" not in session:
        flash("Bitte logge dich zuerst ein.", "error")
        return redirect(url_for("hub"))

    user_roles = session.get("user", {}).get("roles", [])
    if not has_buchhaltung_permission(user_roles):
        flash("Zugriff verweigert. Du benötigst Buchhaltung, Geschäftsführung oder Projektleitung.", "error")
        return redirect(url_for("dashboard"))

    return None


def require_buchhaltung_api_permission():
    if "user" not in session:
        return jsonify({"success": False, "message": "Bitte zuerst einloggen."}), 401

    user_roles = session.get("user", {}).get("roles", [])
    if not has_buchhaltung_permission(user_roles):
        return jsonify({"success": False, "message": "Nicht berechtigt."}), 403

    return None


def current_account_identity():
    session_user = session.get("user") or {}
    discord_id = safe_str(session_user.get("id"))
    username = safe_str(session_user.get("username") or session_user.get("discord_username"), "User")

    db_user = None
    if discord_id:
        db_user = users_collection.find_one({"discord_id": discord_id})

    display_name = username
    if db_user:
        display_name = (
            db_user.get("display_name")
            or db_user.get("username")
            or db_user.get("discord_username")
            or username
        )

    return {
        "discord_id": discord_id,
        "username": username,
        "display_name": display_name,
        "roles": session_user.get("roles", []),
        "at": now_utc()
    }


def get_all_drivers_for_select():
    drivers_cursor = users_collection.find(
        {},
        {
            "_id": 1,
            "discord_id": 1,
            "username": 1,
            "username_lc": 1,
            "display_name": 1,
            "discord_username": 1,
            "avatar": 1,
            "avatar_url": 1,
            "roles": 1,
            "aktenzeichen": 1
        }
    ).sort([("display_name", ASCENDING), ("username", ASCENDING)])

    drivers = []
    for driver in drivers_cursor:
        drivers.append({
            "id": str(driver.get("_id")),
            "discord_id": driver.get("discord_id"),
            "username": driver.get("username") or driver.get("discord_username") or "Unbekannt",
            "display_name": driver.get("display_name") or driver.get("username") or driver.get("discord_username") or "Unbekannt",
            "discord_username": driver.get("discord_username") or "",
            "avatar_url": make_external_url(get_discord_avatar_url(driver)),
            "role": get_primary_role_name(driver.get("roles", [])),
            "aktenzeichen": driver.get("aktenzeichen") or "Nicht vergeben"
        })

    return drivers


@app.route("/buchhaltung", methods=["GET"])
def buchhaltung():
    permission_response = require_buchhaltung_permission()
    if permission_response:
        return permission_response

    actor = current_account_identity()

    return render_template(
        "buchhaltung.html",
        current_user=session.get("user"),
        display_name=actor.get("username") or actor.get("display_name"),
        staff_name=actor.get("display_name"),
        buchhaltung_requests=[],
        requests=[],
        transactions=[],
        buchhaltung_transactions=[],
        buchhaltung_stats={
            "open_requests": 0,
            "done_requests": 0,
            "open_transactions": 0,
            "paid_transactions": 0,
            "total_amount": 0
        }
    )


@app.route("/api/buchhaltung/request", methods=["GET", "POST", "OPTIONS"])
def api_buchhaltung_request():
    if request.method == "OPTIONS":
        return jsonify({"success": True})

    permission_response = require_buchhaltung_api_permission()
    if permission_response:
        return permission_response

    if request.method == "GET":
        items = list(
            buchhaltung_requests_collection.find(
                {"archived": {"$ne": True}},
                {"_id": 0}
            ).sort("created_at", DESCENDING).limit(100)
        )
        return jsonify({"success": True, "requests": items})

    data = request.get_json(silent=True) or {}

    category = safe_str(data.get("category") or data.get("type"), "Allgemeine Rückfrage")[:120]
    title = safe_str(data.get("title") or data.get("subject"), "Buchhaltungs-Anfrage")[:160]
    message = safe_str(data.get("message") or data.get("description") or data.get("content"))[:2000]
    amount = parse_number(data.get("amount"), 0)
    priority = safe_str(data.get("priority"), "normal")[:40]

    if not message:
        return jsonify({
            "success": False,
            "message": "Bitte eine Nachricht eingeben."
        }), 400

    actor = current_account_identity()
    now = now_utc()
    request_id = uuid.uuid4().hex

    request_doc = {
        "request_id": request_id,
        "category": category,
        "type": category,
        "title": title,
        "description": message,
        "message": message,
        "amount": amount,
        "currency": "EUR",
        "priority": priority,
        "status": "open",
        "archived": False,
        "created_at": now,
        "updated_at": now,
        "created_by": actor,
        "created_by_name": actor.get("display_name"),
        "sender_discord_id": actor.get("discord_id"),
        "sender_username": actor.get("username"),
        "source": "buchhaltung"
    }

    insert_result = buchhaltung_requests_collection.insert_one(request_doc)

    task_doc = {
        "title": f"Buchhaltung: {title}",
        "type": "Buchhaltung",
        "priority": priority,
        "description": message,
        "status": "open",
        "created_at": now,
        "updated_at": now,
        "assignee": None,
        "source": "buchhaltung",
        "buchhaltung_request_id": str(insert_result.inserted_id),
        "request_id": request_id,
        "created_by": actor
    }

    tasks_collection.insert_one(task_doc)

    return jsonify({
        "success": True,
        "message": "Buchhaltungs-Anfrage wurde gespeichert.",
        "requestId": request_id
    })


@app.route("/personalabteilung/dokumente", methods=["GET", "POST"])
def personalabteilung_dokumente():
    permission_response = require_personalabteilung_permission()
    if permission_response:
        return permission_response

    drivers = get_all_drivers_for_select()
    actor = current_account_identity()

    if request.method == "POST":
        discord_id = safe_str(request.form.get("discord_id"))
        title = safe_str(request.form.get("title"), "Dokument der Personalabteilung")
        sender = safe_str(request.form.get("sender"), "Personalabteilung")
        content = safe_str(request.form.get("content"))
        doc_type = safe_str(request.form.get("type"), "personalabteilung")
        needs_signature = request.form.get("needs_signature") in ["1", "true", "on", "yes"]
        important = request.form.get("important") in ["1", "true", "on", "yes"]

        if not discord_id:
            flash("Bitte wähle einen Fahrer aus.", "error")
            return render_template(
                "buchhaltung_form.html",
                current_user=session.get("user"),
                display_name=actor.get("username") or actor.get("display_name"),
                staff_name=actor.get("display_name"),
                drivers=drivers,
                fahrer=drivers
            )

        if not title or not content:
            flash("Titel und Inhalt müssen ausgefüllt sein.", "error")
            return render_template(
                "buchhaltung_form.html",
                current_user=session.get("user"),
                display_name=actor.get("username") or actor.get("display_name"),
                staff_name=actor.get("display_name"),
                drivers=drivers,
                fahrer=drivers
            )

        target_user = users_collection.find_one({"discord_id": discord_id})
        if not target_user:
            flash("Der ausgewählte Fahrer wurde nicht gefunden.", "error")
            return render_template(
                "buchhaltung_form.html",
                current_user=session.get("user"),
                display_name=actor.get("username") or actor.get("display_name"),
                staff_name=actor.get("display_name"),
                drivers=drivers,
                fahrer=drivers
            )

        create_system_document_for_user(
            discord_id=discord_id,
            title=title,
            sender=sender,
            content=content,
            doc_type=doc_type,
            needs_signature=needs_signature,
            extra={
                "important": important,
                "created_by": actor,
                "created_for_username": target_user.get("username") or target_user.get("discord_username"),
                "created_for_display_name": target_user.get("display_name") or target_user.get("username"),
                "source": "personalabteilung_dokumente"
            }
        )

        flash("Dokument wurde erfolgreich an den Fahrer gesendet.", "success")
        return redirect(url_for("personalabteilung_dokumente"))

    return render_template(
        "buchhaltung_form.html",
        current_user=session.get("user"),
        display_name=actor.get("username") or actor.get("display_name"),
        staff_name=actor.get("display_name"),
        drivers=drivers,
        fahrer=drivers
    )


@app.route("/api/personalabteilung/driver/document/send", methods=["POST"])
def api_personalabteilung_send_document():
    permission_response = require_personalabteilung_api_permission()
    if permission_response: return permission_response
    
    data = request.get_json(silent=True) or {}
    driver_id = safe_str(data.get("driverId"))
    title = safe_str(data.get("title"))
    message = safe_str(data.get("message"))
    
    if not driver_id or not title: return jsonify({"success": False, "message": "Fahrer-ID oder Titel fehlt."}), 400
    
    user_doc = users_collection.find_one({"discord_id": driver_id})
    if not user_doc: return jsonify({"success": False, "message": "Fahrer nicht gefunden."}), 404
    
    actor = current_staff_identity()
    handler_name = actor.get("display_name") or "Personalabteilung"
    aktenzeichen = user_doc.get("aktenzeichen") or generate_aktenzeichen()
    
    # Sicherstellen, dass der Fahrer ein Aktenzeichen hat
    if not user_doc.get("aktenzeichen"):
        users_collection.update_one({"discord_id": driver_id}, {"$set": {"aktenzeichen": aktenzeichen}})
    
    content = f"""
        <p><strong>{title}</strong></p>
        <p class="mt-4">Dieses Dokument wurde direkt von der Personalabteilung an dich ausgestellt.</p>
        <p class="mt-4"><strong>Sachbearbeiter:</strong> {handler_name}<br><strong>Aktenzeichen:</strong> {aktenzeichen}</p>
        <div class="mt-5 rounded-2xl bg-black/50 border border-[var(--brand-blue)]/25 p-4">
            <p class="text-[10px] font-orbitron text-[var(--brand-blue)] uppercase tracking-widest mb-2">Nachricht / Inhalt</p>
            <p>{message}</p>
        </div>
    """
    
    create_system_document_for_user(
        driver_id,
        title,
        handler_name,
        content,
        doc_type="direct_document",
        needs_signature=False,
        extra={"important": True}  # Landet im System Alert als wichtig
    )
    
    return jsonify({"success": True, "message": "Wichtiges Dokument ausgestellt."})

# [Hier folgen die bestehenden Approve/Reject API Methoden für die Personalabteilung in gekürzter Wiederholung...]

@app.route("/api/personalabteilung/fahrer_registration/claim", methods=["POST"])
def api_personalabteilung_claim_registration():
    permission_response = require_personalabteilung_api_permission()
    if permission_response: return permission_response
    data = request.get_json(silent=True) or {}
    request_id = safe_str(data.get("requestId") or data.get("id"))
    if not request_id: return jsonify({"success": False, "message": "Request-ID fehlt."}), 400

    request_doc = fahrer_registration_collection.find_one(request_lookup_query(request_id))
    if not request_doc: return jsonify({"success": False, "message": "Antrag wurde nicht gefunden."}), 404

    current_status = safe_str(request_doc.get("status"), "pending")
    if current_status in {"approved", "rejected"}: return jsonify({"success": False, "message": "Dieser Antrag ist bereits abgeschlossen."}), 409

    actor = current_staff_identity()
    now = now_utc()

    if current_status == "claimed":
        if request_is_claimed_by_actor(request_doc, actor):
            return jsonify({"success": True, "message": "Du hast diesen Antrag bereits geclaimt.", "handlerName": actor.get("display_name"), "status": "claimed"})
        claimed_by = request_doc.get("claimed_by") or {}
        claimed_name = claimed_by.get("display_name") or claimed_by.get("username") or "einem anderen Sachbearbeiter"
        return jsonify({"success": False, "message": f"Dieser Antrag ist bereits von {claimed_name} geclaimt."}), 409

    if current_status not in {"pending", "open"}: return jsonify({"success": False, "message": f"Dieser Antrag kann im Status '{current_status}' nicht geclaimt werden."}), 409

    fahrer_registration_collection.update_one({"_id": request_doc["_id"]}, {"$set": {"status": "claimed", "claimed_by": actor, "claimed_at": now, "updated_at": now}})
    users_collection.update_one({"discord_id": str(request_doc.get("discord_id"))}, {"$set": {"fahrer_registration_status": "claimed", "fahrer_registration_handler": actor.get("display_name"), "fahrer_registration_claimed_at": now}})
    return jsonify({"success": True, "message": "Antrag wurde geclaimt. Du kannst ihn jetzt annehmen oder ablehnen.", "handlerName": actor.get("display_name"), "status": "claimed"})

@app.route("/api/personalabteilung/fahrer_registration/approve", methods=["POST"])
def api_personalabteilung_approve_registration():
    permission_response = require_personalabteilung_api_permission()
    if permission_response: return permission_response

    data = request.get_json(silent=True) or {}
    request_id = safe_str(data.get("requestId") or data.get("id"))
    if not request_id: return jsonify({"success": False, "message": "Request-ID fehlt."}), 400

    request_doc = fahrer_registration_collection.find_one(request_lookup_query(request_id))
    if not request_doc: return jsonify({"success": False, "message": "Antrag wurde nicht gefunden."}), 404

    if request_doc.get("status") == "approved": return jsonify({"success": False, "message": "Dieser Antrag ist bereits genehmigt."}), 409
    if request_doc.get("status") == "rejected": return jsonify({"success": False, "message": "Ein abgelehnter Antrag kann nicht genehmigt werden."}), 409

    user_doc = find_user_for_request_doc(request_doc)
    if not user_doc: return jsonify({"success": False, "message": "Der User zum Antrag wurde nicht gefunden."}), 404

    actor = current_staff_identity()
    claim_error = require_request_claimed_by_actor(request_doc, actor)
    if claim_error: return claim_error

    now = now_utc()
    tracker_code = create_tracker_code_for_user_doc(user_doc, actor, allow_unapproved=True)

    # AKTENZEICHEN PRÜFEN UND SETZEN BEI APPROVE
    aktenzeichen = user_doc.get("aktenzeichen")
    if not aktenzeichen:
        aktenzeichen = generate_aktenzeichen()

    approved_name = request_doc.get("name") or user_doc.get("display_name") or user_doc.get("username") or "EifelLog Fahrer"
    approved_role = request_doc.get("role") or get_primary_role_name(user_doc.get("roles", []))
    handler_name = actor.get("display_name") or "Personalabteilung"

    document_content = tracker_confirmation_document_content(
        approved_name,
        approved_role,
        handler_name,
        tracker_code,
        reason=f"Fahrer-Registrierung wurde genehmigt.<br>Dein offizielles Aktenzeichen: <strong>{aktenzeichen}</strong>"
    )

    create_system_document_for_user(
        user_doc.get("discord_id"),
        "Fahrer Token Bestätigung",
        handler_name,
        document_content,
        doc_type="driver_registration_approval",
        needs_signature=False,
        extra={"request_id": str(request_doc.get("request_id") or request_doc.get("_id")), "token_created_at": now, "contains_tracker_code": True}
    )

    fahrer_registration_collection.update_one({"_id": request_doc["_id"]}, {"$set": {"status": "approved", "approved_by": actor, "approved_at": now, "updated_at": now, "generated_token_at": now}})
    users_collection.update_one(
        {"_id": user_doc["_id"]}, 
        {"$set": {
            "fahrer_registration_status": "approved", "fahrer_registration_approved_at": now,
            "fahrer_registration_handler": handler_name, "fahrer_registration_name": approved_name,
            "fahrer_registration_role": approved_role, "fahrer_registration_request_id": str(request_doc.get("request_id") or request_doc.get("_id")),
            "tracker_enabled": True, "aktenzeichen": aktenzeichen
        }}
    )

    return jsonify({"success": True, "message": "Fahrer wurde genehmigt. Token und Aktenzeichen ins System-Postfach gesendet.", "status": "approved", "handlerName": handler_name, "trackerCode": tracker_code})

@app.route("/api/personalabteilung/fahrer_registration/reject", methods=["POST"])
def api_personalabteilung_reject_registration():
    permission_response = require_personalabteilung_api_permission()
    if permission_response: return permission_response
    data = request.get_json(silent=True) or {}
    request_id = safe_str(data.get("requestId") or data.get("id"))
    reason = safe_str(data.get("reason"), "Kein Grund angegeben.")[:600]
    if not request_id: return jsonify({"success": False, "message": "Request-ID fehlt."}), 400

    request_doc = fahrer_registration_collection.find_one(request_lookup_query(request_id))
    if not request_doc: return jsonify({"success": False, "message": "Antrag wurde nicht gefunden."}), 404
    if request_doc.get("status") in {"approved", "rejected"}: return jsonify({"success": False, "message": "Dieser Antrag ist bereits abgeschlossen."}), 409

    user_doc = find_user_for_request_doc(request_doc)
    actor = current_staff_identity()
    claim_error = require_request_claimed_by_actor(request_doc, actor)
    if claim_error: return claim_error

    now = now_utc()
    handler_name = actor.get("display_name") or "Personalabteilung"

    fahrer_registration_collection.update_one({"_id": request_doc["_id"]}, {"$set": {"status": "rejected", "rejected_by": actor, "rejected_at": now, "reject_reason": reason, "updated_at": now}})
    if user_doc:
        users_collection.update_one({"_id": user_doc["_id"]}, {"$set": {"fahrer_registration_status": "rejected", "fahrer_registration_rejected_at": now, "fahrer_registration_reject_reason": reason, "fahrer_registration_handler": handler_name}})
        create_system_document_for_user(user_doc.get("discord_id"), "Fahrer Registrierung abgelehnt", handler_name, rejection_document_content("Fahrer Registrierung abgelehnt", reason, handler_name), doc_type="driver_registration_rejection", needs_signature=False, extra={"request_id": str(request_doc.get("request_id") or request_doc.get("_id"))})

    return jsonify({"success": True, "message": "Fahrer-Registrierung wurde abgelehnt.", "status": "rejected", "handlerName": handler_name})

@app.route("/api/personalabteilung/token_request/approve", methods=["POST"])
def api_personalabteilung_approve_token_request():
    permission_response = require_personalabteilung_api_permission()
    if permission_response: return permission_response
    data = request.get_json(silent=True) or {}
    request_id = safe_str(data.get("requestId") or data.get("id"))
    if not request_id: return jsonify({"success": False, "message": "Request-ID fehlt."}), 400

    request_doc = token_request_collection.find_one(request_lookup_query(request_id))
    if not request_doc: return jsonify({"success": False, "message": "Token-Anfrage wurde nicht gefunden."}), 404
    if request_doc.get("status") in {"approved", "rejected"}: return jsonify({"success": False, "message": "Diese Token-Anfrage ist bereits abgeschlossen."}), 409

    user_doc = find_user_for_request_doc(request_doc)
    if not user_doc: return jsonify({"success": False, "message": "Der User zur Token-Anfrage wurde nicht gefunden."}), 404
    if not user_registration_is_approved(user_doc.get("discord_id"), user_doc=user_doc): return jsonify({"success": False, "message": "Für diesen User darf kein neuer Token erstellt werden."}), 403

    actor = current_staff_identity()
    now = now_utc()
    handler_name = actor.get("display_name") or "Personalabteilung"
    tracker_code = create_tracker_code_for_user_doc(user_doc, actor)

    name = request_doc.get("name") or user_doc.get("display_name") or user_doc.get("username") or "EifelLog Fahrer"
    role = request_doc.get("role") or user_doc.get("fahrer_registration_role") or get_primary_role_name(user_doc.get("roles", []))
    reason = request_doc.get("reason") or "Neuer Token wurde genehmigt."

    document_content = tracker_confirmation_document_content(name, role, handler_name, tracker_code, reason=reason)
    create_system_document_for_user(user_doc.get("discord_id"), "Neuer Fahrer Token", handler_name, document_content, doc_type="new_token_approval", needs_signature=False, extra={"request_id": str(request_doc.get("request_id") or request_doc.get("_id")), "registration_request_id": safe_str(request_doc.get("registration_request_id") or user_doc.get("fahrer_registration_request_id")), "token_created_at": now, "contains_tracker_code": True})

    token_request_collection.update_one({"_id": request_doc["_id"]}, {"$set": {"status": "approved", "approved_by": actor, "approved_at": now, "updated_at": now, "generated_token_at": now}})
    users_collection.update_one({"_id": user_doc["_id"]}, {"$set": {"fahrer_registration_status": "approved", "fahrer_registration_handler": handler_name, "last_token_request_approved_at": now, "tracker_enabled": True}})

    return jsonify({"success": True, "message": "Neuer Token wurde erstellt und ins System-Postfach gesendet.", "status": "approved", "handlerName": handler_name, "trackerCode": tracker_code})

@app.route("/api/personalabteilung/token_request/reject", methods=["POST"])
def api_personalabteilung_reject_token_request():
    permission_response = require_personalabteilung_api_permission()
    if permission_response: return permission_response
    data = request.get_json(silent=True) or {}
    request_id = safe_str(data.get("requestId") or data.get("id"))
    reason = safe_str(data.get("reason"), "Kein Grund angegeben.")[:600]
    if not request_id: return jsonify({"success": False, "message": "Request-ID fehlt."}), 400

    request_doc = token_request_collection.find_one(request_lookup_query(request_id))
    if not request_doc: return jsonify({"success": False, "message": "Token-Anfrage wurde nicht gefunden."}), 404
    if request_doc.get("status") in {"approved", "rejected"}: return jsonify({"success": False, "message": "Diese Token-Anfrage ist bereits abgeschlossen."}), 409

    user_doc = find_user_for_request_doc(request_doc)
    actor = current_staff_identity()
    now = now_utc()
    handler_name = actor.get("display_name") or "Personalabteilung"

    token_request_collection.update_one({"_id": request_doc["_id"]}, {"$set": {"status": "rejected", "rejected_by": actor, "rejected_at": now, "reject_reason": reason, "updated_at": now}})
    if user_doc: create_system_document_for_user(user_doc.get("discord_id"), "Token Anfrage abgelehnt", handler_name, rejection_document_content("Token Anfrage abgelehnt", reason, handler_name), doc_type="new_token_rejection", needs_signature=False, extra={"request_id": str(request_doc.get("request_id") or request_doc.get("_id"))})

    return jsonify({"success": True, "message": "Token-Anfrage wurde abgelehnt.", "status": "rejected", "handlerName": handler_name})

@app.route("/personalabteilung/tracker-code/create", methods=["POST"])
def personalabteilung_create_tracker_code():
    permission_response = require_personalabteilung_api_permission()
    if permission_response: return permission_response
    data = request.get_json(silent=True) or {}
    driver_name = safe_str(data.get("driverName"))
    discord_id = safe_str(data.get("discordId"))
    force_new = bool(data.get("forceNew", True))

    if not driver_name and not discord_id: return jsonify({"success": False, "error": "driverName oder discordId fehlt."}), 400

    if discord_id: user_doc = users_collection.find_one({"discord_id": discord_id})
    else: user_doc = find_user_for_tracker_name(driver_name)

    if not user_doc: return jsonify({"success": False, "error": "Fahrer wurde nicht gefunden."}), 404
    if not user_registration_is_approved(user_doc.get("discord_id"), user_doc=user_doc): return jsonify({"success": False, "error": "Dieser User ist noch nicht als Fahrer angenommen."}), 403

    existing_hash = user_doc.get("tracker_code_hash")
    if existing_hash and not force_new: return jsonify({"success": True, "message": "Für diesen Fahrer existiert bereits ein Tracker-Code.", "trackerCode": None, "driver": tracker_profile_payload(user_doc)})

    actor = current_staff_identity()
    tracker_code = create_tracker_code_for_user_doc(user_doc, actor)

    fresh_user = users_collection.find_one({"_id": user_doc["_id"]})
    latest_registration = get_latest_registration_request_for_user(fresh_user.get("discord_id"))
    latest_request_id = registration_public_id(latest_registration) if latest_registration else safe_str(fresh_user.get("fahrer_registration_request_id"))

    create_system_document_for_user(
        fresh_user.get("discord_id"),
        "Fahrer Token Bestätigung",
        actor.get("display_name") or "Personalabteilung",
        tracker_confirmation_document_content(
            fresh_user.get("display_name") or fresh_user.get("username") or "EifelLog Fahrer",
            get_primary_role_name(fresh_user.get("roles", [])),
            actor.get("display_name") or "Personalabteilung",
            tracker_code,
            reason="Tracker-Code wurde durch die Personalabteilung erstellt."
        ),
        doc_type="manual_token_create",
        needs_signature=False,
        extra={"request_id": latest_request_id, "token_created_at": now_utc(), "contains_tracker_code": True}
    )

    return jsonify({"success": True, "message": "Tracker-Code wurde erstellt und als System-Dokument gesendet.", "trackerCode": tracker_code, "driver": tracker_profile_payload(fresh_user)})


# ==========================================
# STANDARD ROUTEN
# ==========================================

@app.route("/downloads")
def downloads():
    if "user" not in session: return redirect(url_for("login"))
    return render_template("download.html")

@app.route("/fuhrpark")
def fuhrpark():
    return render_template("fuhrpark.html")


# ==========================================
# API ROUTEN
# ==========================================

@app.route("/api/sign_policy", methods=["POST"])
def sign_policy():
    if "user" not in session: return jsonify({"success": False, "error": "Not logged in"}), 401
    data = request.get_json() or {}
    signature = data.get("signature")
    if not signature: return jsonify({"success": False, "error": "No signature provided"}), 400

    users_collection.update_one({"discord_id": str(session["user"]["id"])}, {"$set": {"policy_signed": True, "policy_signature": signature, "policy_signed_at": datetime.utcnow()}})
    return jsonify({"success": True})

@app.route("/api/health")
def health_check():
    return jsonify({
        "success": True,
        "service": "EifelLog",
        "database": MONGO_DB_NAME,
        "time": now_utc().isoformat() + "Z",
        "trackerRoutes": [
            "/api/tracker/login", "/api/tracker/session", "/api/tracker/profile",
            "/api/tracker/state", "/api/tracker/telemetry/live", "/api/tracker/logout"
        ]
    })


# ==========================================
# SERVER START
# ==========================================

if __name__ == "__main__":
    print(f"Starte Eifel LOG Server mit MongoDB DB '{MONGO_DB_NAME}' und Eventlet auf Port 5005...")
    eventlet.wsgi.server(eventlet.listen(("0.0.0.0", 5005)), app)