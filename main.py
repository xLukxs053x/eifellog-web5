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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, ".env")

load_dotenv(dotenv_path=ENV_PATH, override=True)

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", os.urandom(24))
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024

PROFILE_UPLOAD_FOLDER = os.path.join("static", "uploads", "profiles")
ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}

TRACKER_API_KEY = os.getenv("TRACKER_API_KEY", "").strip()

# Discord Webhook für Job-Abschluss-Meldungen vom Tracker
DISCORD_JOB_COMPLETE_WEBHOOK_URL = os.getenv(
    "DISCORD_JOB_COMPLETE_WEBHOOK_URL",
    "https://discord.com/api/webhooks/1505648390648762498/eDP1AtdUVWWgxkEnMGNtNmLx1JbPFhd_qV16ohpj6hiVXp7rJHmS_ScIj7XiRF46-kWf"
).strip()


# ==========================================
# TOUR-BELEG / PDF / ABRECHNUNG AUS .ENV
# ==========================================

def env_first(*names, default=""):
    for name in names:
        value = os.getenv(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return default


def env_bool(*names, default=False):
    value = env_first(*names, default="")
    if value == "":
        return bool(default)
    return value.lower() in {"1", "true", "yes", "ja", "on", "enabled"}


def env_float(*names, default=0.0):
    value = env_first(*names, default="")
    if value == "":
        return float(default)
    try:
        return float(str(value).replace(",", "."))
    except Exception:
        return float(default)


DISCORD_BOT_TOKEN = env_first("DISCORD_BOT_TOKEN", "BOT_TOKEN", "DISCORD_TOKEN", default="")
TOUR_RECEIPT_CHANNEL_ID = env_first(
    "TOUR_RECEIPT_CHANNEL_ID",
    "DISCORD_TOUR_RECEIPT_CHANNEL_ID",
    "DISCORD_ABRECHNUNG_CHANNEL_ID",
    "ABRECHNUNG_CHANNEL_ID",
    default="1473756766478270517"
)
TOUR_RECEIPT_ENABLED = env_bool("TOUR_RECEIPT_ENABLED", default=True)
TOUR_RECEIPT_DISCORD_ENABLED = env_bool("TOUR_RECEIPT_DISCORD_ENABLED", default=True)
TOUR_RECEIPT_FOLDER = env_first(
    "TOUR_RECEIPT_FOLDER",
    "RECEIPT_FOLDER",
    default=os.path.join("static", "downloads", "tour_receipts")
)
TOUR_RECEIPT_PUBLIC_BASE_URL = env_first("TOUR_RECEIPT_PUBLIC_BASE_URL", "PUBLIC_BASE_URL", default="")
TOUR_RECEIPT_COMPANY_NAME = env_first("TOUR_RECEIPT_COMPANY_NAME", "COMPANY_NAME", default="Eifel LOG")
TOUR_RECEIPT_CURRENCY = env_first("TOUR_RECEIPT_CURRENCY", "DEFAULT_CURRENCY", default="EUR")
TOUR_RECEIPT_RATE_PER_KM = env_float("TOUR_RECEIPT_RATE_PER_KM", "TRACKER_EURO_PER_KM", default=3.2)
SERVER_HOST = env_first("SERVER_HOST", "HOST", default="0.0.0.0")
SERVER_PORT = int(env_float("SERVER_PORT", "PORT", default=5005))


# ==========================================
# LOCAL TRACKER / WEBVIEW2 CORS
# ==========================================

@app.after_request
def add_tracker_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = (
        "Content-Type, Authorization, X-Tracker-Token, X-Tracker-Code, X-Tracker-Api-Key, X-Requested-With"
    )
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, DELETE, OPTIONS"
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
buchhaltung_entries_collection = db["buchhaltung_entries"]
tour_receipts_collection = db["tour_receipts"]
dispo_tours_collection = db["dispo_tours"]
dispo_notes_collection = db["dispo_notes"]
dispo_messages_collection = db["dispo_messages"]


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
        buchhaltung_requests_collection.create_index([("status", ASCENDING)], unique=False)
        buchhaltung_requests_collection.create_index([("archived", ASCENDING)], unique=False)

        buchhaltung_entries_collection.create_index([("entry_id", ASCENDING)], unique=False)
        buchhaltung_entries_collection.create_index([("created_at", DESCENDING)], unique=False)
        buchhaltung_entries_collection.create_index([("updated_at", DESCENDING)], unique=False)
        buchhaltung_entries_collection.create_index([("created_by.discord_id", ASCENDING)], unique=False)
        buchhaltung_entries_collection.create_index([("created_by.username", ASCENDING)], unique=False)
        buchhaltung_entries_collection.create_index([("date", DESCENDING)], unique=False)
        buchhaltung_entries_collection.create_index([("type", ASCENDING)], unique=False)
        buchhaltung_entries_collection.create_index([("payment_status", ASCENDING)], unique=False)
        buchhaltung_entries_collection.create_index([("receipt_status", ASCENDING)], unique=False)
        buchhaltung_entries_collection.create_index([("archived", ASCENDING)], unique=False)

        tour_receipts_collection.create_index([("receipt_id", ASCENDING)], unique=False)
        tour_receipts_collection.create_index([("job_id", ASCENDING)], unique=False)
        tour_receipts_collection.create_index([("driver.discord_id", ASCENDING)], unique=False)
        tour_receipts_collection.create_index([("submitted_at", DESCENDING)], unique=False)
        tour_receipts_collection.create_index([("billing_relevant", ASCENDING)], unique=False)

        dispo_tours_collection.create_index([("tour_id", ASCENDING)], unique=False)
        dispo_tours_collection.create_index([("status", ASCENDING)], unique=False)
        dispo_tours_collection.create_index([("priority", ASCENDING)], unique=False)
        dispo_tours_collection.create_index([("created_at", DESCENDING)], unique=False)
        dispo_tours_collection.create_index([("assigned_driver_id", ASCENDING)], unique=False)
        dispo_tours_collection.create_index([("assigned_driver.discord_id", ASCENDING)], unique=False)
        dispo_tours_collection.create_index([("archived", ASCENDING)], unique=False)

        dispo_notes_collection.create_index([("created_at", DESCENDING)], unique=False)
        dispo_notes_collection.create_index([("created_by.discord_id", ASCENDING)], unique=False)
        dispo_notes_collection.create_index([("archived", ASCENDING)], unique=False)

        dispo_messages_collection.create_index([("created_at", DESCENDING)], unique=False)
        dispo_messages_collection.create_index([("priority", ASCENDING)], unique=False)
        dispo_messages_collection.create_index([("archived", ASCENDING)], unique=False)
    except Exception as error:
        print(f"MongoDB Index-Erstellung fehlgeschlagen: {error}")


ensure_indexes()


# ==========================================
# EIFEL LOG ROLLEN IDS
# ==========================================

ROLE_FAHRER = os.getenv("ROLE_FAHRER")
ROLE_GESCHAEFTSLEITUNG = os.getenv("ROLE_GESCHAEFTSLEITUNG")
ROLE_PROJEKTLEITUNG = os.getenv("ROLE_PROJEKTLEITUNG")
ROLE_STELLVERTRETENDE_PROJEKTLEITUNG = os.getenv("ROLE_STELLVERTRETENDE_PROJEKTLEITUNG")
ROLE_FUHRPARKMANAGEMENT = os.getenv("ROLE_FUHRPARKMANAGEMENT")
ROLE_BUCHHALTUNG = os.getenv("ROLE_BUCHHALTUNG")
ROLE_HR_CONTROLLING = env_first("ROLE_HR_CONTROLLING", "HR_CONTROLLING_ROLE_ID", default="1473726292963885188")
ROLE_DISPOSITION = os.getenv("ROLE_DISPOSITION")
ROLE_PERSONALMANAGEMENT = os.getenv("ROLE_PERSONALMANAGEMENT")

# Hardcoded Rollen IDs basierend auf Vorgaben
ROLE_PERSONALABTEILUNG_ID = "1473725287505072174"
ROLE_GESCHAEFTSFUEHRUNG_ID = "1473721587122438322"
ROLE_PROJEKTLEITUNG_ID = "1473721587122438321"
ROLE_STELLVERTRETENDE_PROJEKTLEITUNG_ID = "1473721587122438320"
ROLE_BUCHHALTUNG_ID = "1473730533593845951"
ROLE_HR_CONTROLLING_ID = env_first("ROLE_HR_CONTROLLING_ID", "HR_CONTROLLING_ROLE_ID", default=ROLE_HR_CONTROLLING or "1473726292963885188")
ROLE_DISPOSITION_ID = env_first("ROLE_DISPOSITION_ID", "DISPOSITION_ROLE_ID", default=ROLE_DISPOSITION or "")

ALLOWED_HUB_ROLES = [
    ROLE_FAHRER,
    ROLE_GESCHAEFTSLEITUNG,
    ROLE_PROJEKTLEITUNG,
    ROLE_STELLVERTRETENDE_PROJEKTLEITUNG,
    ROLE_FUHRPARKMANAGEMENT,
    ROLE_BUCHHALTUNG,
    ROLE_HR_CONTROLLING,
    ROLE_HR_CONTROLLING_ID,
    ROLE_DISPOSITION,
    ROLE_DISPOSITION_ID,
    ROLE_PERSONALMANAGEMENT,
    ROLE_STELLVERTRETENDE_PROJEKTLEITUNG_ID
]

PERSONALABTEILUNG_ALLOWED_ROLES = {
    ROLE_PERSONALABTEILUNG_ID,
    ROLE_GESCHAEFTSFUEHRUNG_ID,
    ROLE_PROJEKTLEITUNG_ID,
    ROLE_HR_CONTROLLING,
    ROLE_HR_CONTROLLING_ID,
    "1473726292963885188",
    "HR-Controlling",
    "HR Controlling",
    "hr-controlling",
    "hr controlling"
}

DISPOSITION_ALLOWED_ROLES = {
    ROLE_DISPOSITION,
    ROLE_DISPOSITION_ID,
    ROLE_GESCHAEFTSLEITUNG,
    ROLE_GESCHAEFTSFUEHRUNG_ID,
    ROLE_PROJEKTLEITUNG,
    ROLE_PROJEKTLEITUNG_ID,
    "Disposition",
    "disposition",
    "dispo",
    "Geschäftsleitung",
    "Geschaeftsleitung",
    "Geschäftsführung",
    "Geschaeftsfuehrung",
    "Projektleitung",
    "projektleitung"
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


def has_disposition_permission(user_roles):
    clean_user_roles = set(clean_roles(user_roles))
    clean_allowed_roles = set(clean_roles(DISPOSITION_ALLOWED_ROLES))
    if clean_user_roles.intersection(clean_allowed_roles):
        return True

    primary_role_name = get_primary_role_name(user_roles)
    return primary_role_name in {"Disposition", "Projektleitung", "Geschäftsleitung"}


def get_primary_role_name(user_roles):
    clean_user_roles = clean_roles(user_roles)

    if str(ROLE_GESCHAEFTSLEITUNG).strip() in clean_user_roles or str(ROLE_GESCHAEFTSFUEHRUNG_ID).strip() in clean_user_roles: return "Geschäftsleitung"
    if str(ROLE_PROJEKTLEITUNG).strip() in clean_user_roles or str(ROLE_PROJEKTLEITUNG_ID).strip() in clean_user_roles: return "Projektleitung"
    if str(ROLE_STELLVERTRETENDE_PROJEKTLEITUNG).strip() in clean_user_roles or str(ROLE_STELLVERTRETENDE_PROJEKTLEITUNG_ID).strip() in clean_user_roles: return "Stellvertretende Projektleitung"
    if str(ROLE_PERSONALMANAGEMENT).strip() in clean_user_roles: return "Personalmanagement"
    if str(ROLE_HR_CONTROLLING).strip() in clean_user_roles or str(ROLE_HR_CONTROLLING_ID).strip() in clean_user_roles: return "HR-Controlling"
    if "HR-Controlling" in clean_user_roles or "HR Controlling" in clean_user_roles: return "HR-Controlling"
    if str(ROLE_BUCHHALTUNG).strip() in clean_user_roles: return "Buchhaltung"
    if str(ROLE_DISPOSITION).strip() in clean_user_roles or str(ROLE_DISPOSITION_ID).strip() in clean_user_roles: return "Disposition"
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

def normalize_buchhaltung_priority(priority):
    priority = safe_str(priority, "Normal")
    priority_lc = priority.lower()

    if priority_lc in {"dringend", "urgent", "high", "hoch"}:
        return "Dringend"
    if priority_lc in {"wichtig", "important", "medium", "mittel"}:
        return "Wichtig"
    if priority_lc in {"normal", "low", "niedrig"}:
        return "Normal"

    return priority[:40] if priority else "Normal"


def prepare_buchhaltung_request_for_personalabteilung(request_doc):
    item = dict(request_doc)
    mongo_id = item.get("_id")
    mongo_id_str = str(mongo_id) if mongo_id else ""

    item["_id"] = mongo_id_str
    item["id"] = safe_str(item.get("id") or item.get("request_id") or mongo_id_str)
    item["request_id"] = safe_str(item.get("request_id") or item["id"])

    item["category"] = safe_str(item.get("category") or item.get("type"), "Allgemeine Personalfrage")
    item["type"] = item.get("type") or item["category"]

    item["title"] = safe_str(item.get("title") or item.get("subject"), "Ohne Betreff")
    item["subject"] = safe_str(item.get("subject") or item.get("title"), item["title"])

    item["message"] = safe_str(item.get("message") or item.get("description") or item.get("text") or item.get("body"))
    item["description"] = item["message"]

    item["priority"] = normalize_buchhaltung_priority(item.get("priority"))
    item["status"] = safe_str(item.get("status"), "open").lower()

    item["reference"] = safe_str(item.get("reference") or item.get("ref") or item.get("bezug") or item.get("case_reference"))

    created_by = item.get("created_by") or {}
    sender_name = (
        item.get("sender_name")
        or item.get("requester_name")
        or item.get("created_by_name")
        or created_by.get("display_name")
        or item.get("user_name")
        or item.get("display_name")
        or item.get("name")
        or item.get("username")
        or "Buchhaltung"
    )

    sender_username = (
        item.get("sender_username")
        or created_by.get("username")
        or item.get("username")
        or item.get("discord_username")
        or sender_name
    )

    sender_discord_id = (
        item.get("sender_discord_id")
        or created_by.get("discord_id")
        or item.get("discord_id")
        or item.get("user_id")
        or "-"
    )

    item["sender_name"] = sender_name
    item["requester_name"] = sender_name
    item["created_by_name"] = item.get("created_by_name") or sender_name
    item["username"] = sender_username
    item["discord_username"] = item.get("discord_username") or sender_username
    item["discord_id"] = sender_discord_id
    item["user_id"] = sender_discord_id
    item["avatar_url"] = item.get("avatar_url") or ""

    item["created_at"] = format_datetime_for_template(item.get("created_at")) or "-"
    item["requested_at"] = item["created_at"]
    item["submitted_at"] = item["created_at"]
    item["updated_at"] = format_datetime_for_template(item.get("updated_at")) or item["created_at"]

    claimed_by = item.get("claimed_by") or {}
    item["claimed_by_name"] = (
        item.get("claimed_by_name")
        or item.get("handler_name")
        or item.get("sachbearbeiter_name")
        or claimed_by.get("display_name")
        or "Noch nicht zugewiesen"
    )
    item["handler_name"] = item["claimed_by_name"]
    item["sachbearbeiter_name"] = item["claimed_by_name"]

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
# TOUR-BELEG / PDF / ABRECHNUNG
# ==========================================

def bool_from_payload(value, fallback=False):
    if value is None:
        return fallback
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return safe_str(value).lower() in {"1", "true", "yes", "ja", "on", "aktiv", "active"}


def format_money(value, currency=None):
    currency = safe_str(currency, TOUR_RECEIPT_CURRENCY).upper()
    number = parse_number(value, 0)
    text = f"{number:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if currency == "EUR":
        return f"{text} €"
    return f"{text} {currency}"


def format_km(value):
    number = parse_number(value, 0)
    text = f"{number:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{text} km"


def format_percent(value):
    number = parse_number(value, 0)
    text = f"{number:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{text} %"


def format_liters(value):
    number = parse_number(value, 0)
    text = f"{number:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{text} l"


def pdf_safe_text(value):
    value = safe_str(value, "-")
    value = value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return value


def pdf_text_bytes(value):
    return pdf_safe_text(value).encode("cp1252", errors="replace")


def wrap_pdf_line(label, value, max_chars=96):
    label = safe_str(label)
    value = safe_str(value, "-")
    prefix = f"{label}: " if label else ""
    raw = prefix + value

    if len(raw) <= max_chars:
        return [raw]

    lines = []
    current = ""
    for word in raw.split():
        if len(current) + len(word) + 1 > max_chars:
            if current:
                lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)

    if not lines:
        return [raw[:max_chars]]
    return lines


def build_simple_pdf(title, sections):
    # Minimaler PDF-Generator ohne externe Bibliothek.
    # Nutzt Standard-Schrift Helvetica und erstellt bei Bedarf mehrere Seiten.
    page_width = 595
    page_height = 842
    margin_left = 42
    y_start = 800
    y_min = 55
    line_height = 15

    pages = []
    current_lines = []

    def add_page():
        nonlocal current_lines
        if current_lines:
            pages.append(current_lines)
        current_lines = []

    def add_line(text, size=10, bold=False, gap_after=0):
        nonlocal current_lines
        if len(current_lines) >= 46:
            add_page()
        current_lines.append({
            "text": safe_str(text),
            "size": size,
            "bold": bool(bold),
            "gap_after": gap_after
        })

    add_line(title, size=18, bold=True, gap_after=10)
    add_line(f"Erstellt am {now_utc().strftime('%d.%m.%Y %H:%M')} UTC", size=9, gap_after=10)

    for section_title, rows in sections:
        add_line(section_title, size=13, bold=True, gap_after=4)
        for label, value in rows:
            for wrapped in wrap_pdf_line(label, value):
                add_line(wrapped, size=10)
        add_line("", size=6, gap_after=3)

    add_page()

    objects = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")

    page_object_numbers = []

    for page_lines in pages:
        y = y_start
        stream = bytearray()
        stream.extend(b"q\n")
        stream.extend(b"0.08 w\n")
        stream.extend(f"{margin_left} 820 m {page_width - margin_left} 820 l S\n".encode("ascii"))

        for item in page_lines:
            text_value = item["text"]
            size = int(item["size"])
            font = "F2" if item["bold"] else "F1"

            if y < y_min:
                y = y_start

            stream.extend(b"BT\n")
            stream.extend(f"/{font} {size} Tf\n".encode("ascii"))
            stream.extend(f"1 0 0 1 {margin_left} {y} Tm\n".encode("ascii"))
            stream.extend(b"(" + pdf_text_bytes(text_value) + b") Tj\n")
            stream.extend(b"ET\n")

            y -= line_height + int(item.get("gap_after") or 0)

        stream.extend(f"{margin_left} 38 m {page_width - margin_left} 38 l S\n".encode("ascii"))
        stream.extend(b"BT\n/F1 8 Tf\n")
        stream.extend(f"1 0 0 1 {margin_left} 25 Tm\n".encode("ascii"))
        stream.extend(b"(Eifel LOG Tour-Beleg / Abrechnung) Tj\nET\n")
        stream.extend(b"Q\n")

        content_object_number = len(objects) + 1
        content_object = (
            f"<< /Length {len(stream)} >>\nstream\n".encode("ascii")
            + bytes(stream)
            + b"\nendstream"
        )
        objects.append(content_object)

        page_object_number = len(objects) + 1
        page_object_numbers.append(page_object_number)
        page_object = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_width} {page_height}] "
            f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> "
            f"/Contents {content_object_number} 0 R >>"
        ).encode("ascii")
        objects.append(page_object)

    kids = " ".join(f"{number} 0 R" for number in page_object_numbers)
    objects[1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_object_numbers)} >>".encode("ascii")

    pdf = bytearray()
    pdf.extend(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")

    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{index} 0 obj\n".encode("ascii"))
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")

    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))

    pdf.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    return bytes(pdf)


def generate_receipt_number(job_id, discord_id="", submitted_at=None):
    submitted_at = submitted_at or now_utc()
    raw = f"{job_id}|{discord_id}|{submitted_at.isoformat()}|{secrets.token_hex(4)}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8].upper()
    return f"EL-{submitted_at.strftime('%Y%m%d')}-{digest}"


def build_receipt_public_url(file_path):
    base = safe_str(TOUR_RECEIPT_PUBLIC_BASE_URL)
    if not base:
        return ""
    filename = os.path.basename(file_path)
    return base.rstrip("/") + "/" + filename


def save_tour_receipt_pdf(receipt_doc):
    submitted_at = receipt_doc.get("submitted_at") or now_utc()
    if not isinstance(submitted_at, datetime):
        submitted_at = now_utc()

    month_folder = submitted_at.strftime("%Y-%m")
    target_folder = os.path.join(TOUR_RECEIPT_FOLDER, month_folder)
    os.makedirs(target_folder, exist_ok=True)

    safe_driver = re.sub(r"[^A-Za-z0-9_.-]+", "_", safe_str(receipt_doc.get("driver", {}).get("name"), "fahrer"))[:60]
    safe_job = re.sub(r"[^A-Za-z0-9_.-]+", "_", safe_str(receipt_doc.get("job_id"), "job"))[:60]
    filename = f"EifelLog_Beleg_{receipt_doc['receipt_number']}_{safe_driver}_{safe_job}.pdf"
    file_path = os.path.join(target_folder, filename)

    sections = []

    sections.append(("Status", [
        ("Status", "Abgegeben / Abgeschlossen"),
        ("Abrechnung", "Ja, abrechnungsrelevant"),
        ("Belegnummer", receipt_doc.get("receipt_number")),
        ("Job-ID", receipt_doc.get("job_id")),
        ("Eingereicht UTC", submitted_at.isoformat() + "Z"),
    ]))

    driver = receipt_doc.get("driver") or {}
    sections.append(("Fahrer", [
        ("Name", driver.get("name")),
        ("Username", driver.get("username")),
        ("Discord-ID", driver.get("discord_id")),
        ("Rolle", driver.get("role")),
    ]))

    tour = receipt_doc.get("tour") or {}
    sections.append(("Tourdaten", [
        ("Spiel", tour.get("game")),
        ("Truck", tour.get("truck")),
        ("Start", tour.get("source_city")),
        ("Ziel", tour.get("destination_city")),
        ("Fracht", tour.get("cargo")),
        ("Geplante Distanz", format_km(tour.get("planned_distance_km"))),
        ("Gefahrene Distanz", format_km(tour.get("driven_distance_km"))),
        ("Restdistanz", format_km(tour.get("remaining_distance_km"))),
        ("Fortschritt", format_percent(tour.get("route_progress_percent"))),
        ("Schaden", format_percent(tour.get("damage_percent"))),
        ("Tank", format_percent(tour.get("fuel_percent"))),
        ("RPM", str(parse_int(tour.get("rpm"), 0))),
        ("Geschwindigkeit bei Abgabe", f"{parse_int(tour.get('speed_kmh'), 0)} km/h"),
    ]))

    billing = receipt_doc.get("billing") or {}
    sections.append(("Abrechnung", [
        ("Satz pro KM", format_money(billing.get("rate_per_km"), billing.get("currency"))),
        ("Grundbetrag", format_money(billing.get("base_amount"), billing.get("currency"))),
        ("Bonus", format_money(billing.get("bonus"), billing.get("currency"))),
        ("Abzug", format_money(billing.get("penalty"), billing.get("currency"))),
        ("Gesamtbetrag", format_money(billing.get("total_amount"), billing.get("currency"))),
        ("Währung", billing.get("currency")),
    ]))

    extra = receipt_doc.get("extra") or {}
    if extra:
        rows = []
        for key, value in sorted(extra.items()):
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)[:500]
            rows.append((key, value))
        sections.append(("Weitere Daten", rows))

    pdf_bytes = build_simple_pdf(
        f"{TOUR_RECEIPT_COMPANY_NAME} - Tour-Beleg / Abrechnung",
        sections
    )

    with open(file_path, "wb") as file:
        file.write(pdf_bytes)

    return file_path, filename, pdf_bytes


def send_receipt_to_discord(receipt_doc, pdf_bytes, filename):
    if not TOUR_RECEIPT_DISCORD_ENABLED:
        return {"sent": False, "reason": "TOUR_RECEIPT_DISCORD_ENABLED=false"}

    driver = receipt_doc.get("driver") or {}
    tour = receipt_doc.get("tour") or {}
    billing = receipt_doc.get("billing") or {}

    content = (
        "✅ **Job abgeschlossen**\n"
        "\n"
        f"**Fahrer:** {driver.get('name') or '-'}\n"
        f"**Job-ID:** `{receipt_doc.get('job_id')}`\n"
        f"**Route:** {tour.get('source_city') or '-'} → {tour.get('destination_city') or '-'}\n"
        f"**Fracht:** {tour.get('cargo') or '-'}\n"
        f"**Spiel:** {tour.get('game') or 'ETS2/ATS'}\n"
        f"**Gefahrene Distanz:** {format_km(tour.get('driven_distance_km'))}\n"
        f"**Schaden:** {format_percent(tour.get('damage_percent'))}\n"
        f"**Abrechnung:** {format_money(billing.get('total_amount'), billing.get('currency'))}\n"
        f"**Belegnummer:** `{receipt_doc.get('receipt_number')}`\n"
        "\n"
        "📄 Der Tour-Beleg wurde automatisch erstellt und angehängt."
    )

    payload = {
        "username": "EifelLog Tracker",
        "content": content,
        "allowed_mentions": {"parse": []},
        "attachments": [
            {
                "id": 0,
                "filename": filename,
                "description": f"Tour-Beleg {receipt_doc.get('receipt_number')}"
            }
        ]
    }

    webhook_url = safe_str(DISCORD_JOB_COMPLETE_WEBHOOK_URL)

    if webhook_url:
        webhook_post_url = webhook_url
        if "?" not in webhook_post_url:
            webhook_post_url += "?wait=true"
        elif "wait=" not in webhook_post_url:
            webhook_post_url += "&wait=true"

        response = requests.post(
            webhook_post_url,
            data={"payload_json": json.dumps(payload, ensure_ascii=False)},
            files={"files[0]": (filename, pdf_bytes, "application/pdf")},
            timeout=20
        )

        if response.status_code not in range(200, 300):
            return {
                "sent": False,
                "method": "webhook",
                "status_code": response.status_code,
                "error": response.text[:1000]
            }

        try:
            message = response.json()
        except Exception:
            message = {}

        return {
            "sent": True,
            "method": "webhook",
            "channel_id": message.get("channel_id"),
            "message_id": message.get("id"),
            "raw": message
        }

    if not DISCORD_BOT_TOKEN:
        return {"sent": False, "reason": "DISCORD_BOT_TOKEN fehlt und DISCORD_JOB_COMPLETE_WEBHOOK_URL fehlt"}

    channel_id = safe_str(TOUR_RECEIPT_CHANNEL_ID)
    if not channel_id:
        return {"sent": False, "reason": "TOUR_RECEIPT_CHANNEL_ID fehlt"}

    response = requests.post(
        f"https://discord.com/api/v10/channels/{channel_id}/messages",
        headers={"Authorization": f"Bot {DISCORD_BOT_TOKEN}"},
        data={"payload_json": json.dumps(payload, ensure_ascii=False)},
        files={"files[0]": (filename, pdf_bytes, "application/pdf")},
        timeout=20
    )

    if response.status_code not in range(200, 300):
        return {
            "sent": False,
            "method": "bot",
            "status_code": response.status_code,
            "error": response.text[:1000]
        }

    try:
        message = response.json()
    except Exception:
        message = {}

    return {
        "sent": True,
        "method": "bot",
        "channel_id": channel_id,
        "message_id": message.get("id"),
        "raw": message
    }

def build_tour_receipt_doc(user_doc, payload, telemetry=None):
    telemetry = telemetry or {}
    submitted_at = now_utc()

    job_id = (
        safe_str(payload.get("jobId"))
        or safe_str(payload.get("job_id"))
        or safe_str(payload.get("id"))
        or f"job-{submitted_at.strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3)}"
    )

    display_name = (
        user_doc.get("display_name")
        or user_doc.get("username")
        or user_doc.get("discord_username")
        or safe_str(payload.get("driverName"), "EifelLog Fahrer")
    )

    source_city = (
        safe_str(payload.get("sourceCity"))
        or safe_str(payload.get("source_city"))
        or safe_str(telemetry.get("sourceCity"))
        or "-"
    )
    destination_city = (
        safe_str(payload.get("destinationCity"))
        or safe_str(payload.get("destination_city"))
        or safe_str(telemetry.get("destinationCity"))
        or "-"
    )
    cargo = safe_str(payload.get("cargo") or telemetry.get("cargo"), "-")
    game = safe_str(payload.get("game") or telemetry.get("game"), "ETS2/ATS")
    truck = safe_str(payload.get("truck") or telemetry.get("truck"), "-")

    planned_distance = parse_number(
        payload.get("plannedDistanceKm")
        or payload.get("planned_distance_km")
        or telemetry.get("plannedDistanceKm"),
        0
    )
    driven_distance = parse_number(
        payload.get("drivenDistanceKm")
        or payload.get("distanceKm")
        or payload.get("distance")
        or telemetry.get("tripDistanceKm"),
        0
    )
    remaining_distance = parse_number(
        payload.get("remainingDistanceKm")
        or telemetry.get("remainingDistanceKm"),
        0
    )

    if driven_distance <= 0 and planned_distance > 0 and remaining_distance >= 0:
        driven_distance = max(planned_distance - remaining_distance, 0)

    rate_per_km = parse_number(payload.get("ratePerKm") or payload.get("rate_per_km"), TOUR_RECEIPT_RATE_PER_KM)
    base_amount = parse_number(payload.get("income") or payload.get("baseAmount") or payload.get("base_amount"), 0)
    if base_amount <= 0:
        base_amount = round(driven_distance * rate_per_km, 2)

    bonus = parse_number(payload.get("bonus"), 0)
    penalty = abs(parse_number(payload.get("penalty") or payload.get("deduction"), 0))
    total_amount = round(base_amount + bonus - penalty, 2)
    currency = safe_str(payload.get("currency"), TOUR_RECEIPT_CURRENCY).upper()

    receipt_number = generate_receipt_number(job_id, user_doc.get("discord_id"), submitted_at)

    extra = {}
    for key, value in payload.items():
        if key not in {
            "clientToken", "jobId", "job_id", "id", "driverName", "sourceCity", "source_city",
            "destinationCity", "destination_city", "cargo", "game", "truck", "plannedDistanceKm",
            "planned_distance_km", "drivenDistanceKm", "distanceKm", "distance", "remainingDistanceKm",
            "ratePerKm", "rate_per_km", "income", "baseAmount", "base_amount", "bonus", "penalty",
            "deduction", "currency", "telemetry", "snapshot"
        }:
            extra[key] = value

    return {
        "receipt_id": uuid.uuid4().hex,
        "receipt_number": receipt_number,
        "job_id": job_id,
        "status": "submitted",
        "submitted": True,
        "completed": True,
        "billing_relevant": True,
        "submitted_at": submitted_at,
        "created_at": submitted_at,
        "driver": {
            "name": display_name,
            "username": user_doc.get("username"),
            "discord_id": user_doc.get("discord_id"),
            "role": get_primary_role_name(user_doc.get("roles", []))
        },
        "tour": {
            "game": game,
            "truck": truck,
            "source_city": source_city,
            "destination_city": destination_city,
            "cargo": cargo,
            "planned_distance_km": planned_distance,
            "driven_distance_km": driven_distance,
            "remaining_distance_km": remaining_distance,
            "route_progress_percent": parse_number(payload.get("routeProgressPercent") or telemetry.get("routeProgressPercent"), 100),
            "damage_percent": parse_number(payload.get("damagePercent") or telemetry.get("damagePercent"), 0),
            "fuel_percent": parse_number(payload.get("fuelPercent") or telemetry.get("fuelPercent"), 0),
            "speed_kmh": parse_number(payload.get("speedKmh") or telemetry.get("speedKmh"), 0),
            "rpm": parse_number(payload.get("rpm") or telemetry.get("rpm"), 0)
        },
        "billing": {
            "rate_per_km": rate_per_km,
            "base_amount": base_amount,
            "bonus": bonus,
            "penalty": penalty,
            "total_amount": total_amount,
            "currency": currency
        },
        "extra": extra,
        "raw_telemetry": telemetry
    }


def write_receipt_into_user_stats(user_doc, receipt_doc):
    billing = receipt_doc.get("billing") or {}
    tour = receipt_doc.get("tour") or {}

    distance = parse_number(tour.get("driven_distance_km"), 0)
    income = parse_number(billing.get("total_amount"), 0)

    stats = get_profile_stats(user_doc)
    new_km = parse_number(stats.get("km"), 0) + distance
    new_income = parse_number(stats.get("income") or stats.get("revenue"), 0) + income
    new_deliveries = parse_int(stats.get("deliveries"), 0) + 1
    new_jobs = parse_int(stats.get("jobs"), new_deliveries - 1) + 1

    logbook_entry = {
        "status": "Fertig",
        "receiptId": receipt_doc.get("receipt_id"),
        "receiptNumber": receipt_doc.get("receipt_number"),
        "jobId": receipt_doc.get("job_id"),
        "route": f"{tour.get('source_city', '-')} → {tour.get('destination_city', '-')}",
        "sourceCity": tour.get("source_city", "-"),
        "destinationCity": tour.get("destination_city", "-"),
        "cargo": tour.get("cargo", "-"),
        "distanceKm": distance,
        "income": income,
        "incomeText": format_money(income, billing.get("currency")),
        "driverName": receipt_doc.get("driver", {}).get("name"),
        "createdAt": receipt_doc.get("submitted_at").isoformat() + "Z",
        "billingRelevant": True,
        "pdfFilePath": receipt_doc.get("pdf", {}).get("file_path"),
        "discordMessageId": receipt_doc.get("discord", {}).get("message_id")
    }

    users_collection.update_one(
        {"_id": user_doc["_id"]},
        {
            "$set": {
                "profile_km": str(round(new_km, 1)),
                "profile_income": str(round(new_income, 2)),
                "profile_revenue": str(round(new_income, 2)),
                "profile_deliveries": str(new_deliveries),
                "profile_jobs": str(new_jobs),
                "tracker_online": False,
                "tracker_current_job": None,
                "tracker_last_receipt_id": receipt_doc.get("receipt_id"),
                "tracker_last_receipt_number": receipt_doc.get("receipt_number"),
                "tracker_last_job_completed_at": now_utc()
            },
            "$push": {
                "job_history": {
                    "$each": [logbook_entry],
                    "$position": 0,
                    "$slice": 100
                }
            }
        }
    )


def complete_tracker_tour_from_request():
    if not TOUR_RECEIPT_ENABLED:
        return jsonify({"success": False, "error": "TOUR_RECEIPT_ENABLED ist deaktiviert."}), 503

    if request.method == "OPTIONS":
        return jsonify({"success": True})
    if request.method == "GET":
        return jsonify({"success": False, "message": "Method not allowed"}), 200

    data = request.get_json(silent=True) or {}
    client_token = get_client_token_from_request(data)
    if not client_token:
        return jsonify({"success": False, "error": "ClientToken fehlt."}), 401

    user_doc = find_tracker_user_by_client_token(client_token)
    if not user_doc:
        return jsonify({"success": False, "error": "Tracker-Sitzung ungültig."}), 401
    if not user_has_tracker_access(user_doc):
        return jsonify({"success": False, "error": "Tracker-Zugriff deaktiviert."}), 403

    telemetry = data.get("telemetry") or data.get("snapshot") or user_doc.get("tracker_live") or {}
    if telemetry:
        telemetry = normalize_telemetry_payload(telemetry)

    receipt_doc = build_tour_receipt_doc(user_doc, data, telemetry=telemetry)

    existing = tour_receipts_collection.find_one({
        "job_id": receipt_doc["job_id"],
        "driver.discord_id": safe_str(user_doc.get("discord_id")),
        "archived": {"$ne": True}
    })
    if existing:
        return jsonify({
            "success": True,
            "message": "Diese Tour wurde bereits abgegeben.",
            "alreadySubmitted": True,
            "receipt": {
                "receiptId": existing.get("receipt_id"),
                "receiptNumber": existing.get("receipt_number"),
                "jobId": existing.get("job_id"),
                "pdfFilePath": existing.get("pdf", {}).get("file_path"),
                "discordMessageId": existing.get("discord", {}).get("message_id"),
                "billingRelevant": bool(existing.get("billing_relevant", True)),
                "totalAmount": existing.get("billing", {}).get("total_amount"),
                "currency": existing.get("billing", {}).get("currency")
            }
        })

    file_path, filename, pdf_bytes = save_tour_receipt_pdf(receipt_doc)

    receipt_doc["pdf"] = {
        "file_path": file_path,
        "file_name": filename,
        "public_url": build_receipt_public_url(file_path),
        "size_bytes": len(pdf_bytes),
        "content_type": "application/pdf"
    }

    discord_result = send_receipt_to_discord(receipt_doc, pdf_bytes, filename)
    receipt_doc["discord"] = discord_result

    tour_receipts_collection.insert_one(receipt_doc)
    write_receipt_into_user_stats(user_doc, receipt_doc)

    return jsonify({
        "success": True,
        "message": "Tour wurde vollständig abgegeben, als Job abgeschlossen und als Abrechnung erfasst.",
        "submitted": True,
        "completed": True,
        "billingRelevant": True,
        "receipt": {
            "receiptId": receipt_doc.get("receipt_id"),
            "receiptNumber": receipt_doc.get("receipt_number"),
            "jobId": receipt_doc.get("job_id"),
            "driverName": receipt_doc.get("driver", {}).get("name"),
            "route": f"{receipt_doc.get('tour', {}).get('source_city', '-')} → {receipt_doc.get('tour', {}).get('destination_city', '-')}",
            "cargo": receipt_doc.get("tour", {}).get("cargo"),
            "pdfFilePath": file_path,
            "pdfFileName": filename,
            "pdfPublicUrl": receipt_doc.get("pdf", {}).get("public_url"),
            "discordSent": bool(discord_result.get("sent")),
            "discordChannelId": discord_result.get("channel_id") or TOUR_RECEIPT_CHANNEL_ID,
            "discordMessageId": discord_result.get("message_id"),
            "discordError": discord_result.get("error") or discord_result.get("reason"),
            "totalAmount": receipt_doc.get("billing", {}).get("total_amount"),
            "currency": receipt_doc.get("billing", {}).get("currency"),
            "submittedAt": receipt_doc.get("submitted_at").isoformat() + "Z"
        },
        "state": tracker_state_payload(users_collection.find_one({"_id": user_doc["_id"]}))
    })


# ==========================================
# ROUTES - ÖFFENTLICH
# ==========================================

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/about")
def about():
    return render_template("about.html")

@app.route('/changelog')
def changelog():
    # Pfad zur JSON-Datei (hier wird davon ausgegangen, dass sie im Hauptverzeichnis liegt)
    # Falls sie im static-Ordner liegt, nutze: os.path.join(app.root_path, 'static', 'changelog.json')
    json_path = os.path.join(app.root_path, 'changelog.json')
    
    changelog_data = []
    
    # Changelog JSON laden
    try:
        if os.path.exists(json_path):
            with open(json_path, 'r', encoding='utf-8') as f:
                changelog_data = json.load(f)
    except Exception as e:
        print(f"Fehler beim Laden der Changelog-Daten: {e}")

    # Roadmap-Daten (Könntest du später auch in eine roadmap.json auslagern)
    roadmap_data = [
        {
            "status": "in_progress",
            "title": "Economy System V2",
            "eta": "In Progress",
            "description": "Komplette Überarbeitung des Finanzsystems inklusive dynamischer Frachtpreise und Wartungskosten."
        },
        {
            "status": "planned",
            "title": "Speditions-Events",
            "eta": "Q3 2026",
            "description": "Wöchentliche Konvois mit Leaderboard und speziellen Belohnungen für aktive Fahrer."
        },
        {
            "status": "planned",
            "title": "API Integration",
            "eta": "Planned",
            "description": "Direkte Schnittstelle zu Telemetrie-Daten aus dem Spiel zur automatischen Fahrtenbuch-Eintragung."
        }
    ]

    return render_template('changelog.html', changelog=changelog_data, roadmap=roadmap_data)




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

@app.route("/api/tracker/tour/submit", methods=["GET", "POST", "OPTIONS"])
def tracker_tour_submit():
    return complete_tracker_tour_from_request()


@app.route("/api/tracker/job/complete", methods=["GET", "POST", "OPTIONS"])
def tracker_job_complete():
    return complete_tracker_tour_from_request()


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
# STANDARD ROUTEN
# ==========================================

@app.route("/tutorial")
def tutorial():
    if "user" not in session:
        flash("Bitte logge dich zuerst ein.", "error")
        return redirect(url_for("hub"))

    user = session["user"]
    user_roles = user.get("roles", [])

    if not has_dashboard_permission(user_roles):
        flash("Zugriff verweigert! Du benötigst eine anerkannte Rolle.", "error")
        return redirect(url_for("home"))

    role_name = get_primary_role_name(user_roles)

    # Je nach Rolle ein anderes Tutorial-Template ausspielen
    if role_name in ["Geschäftsleitung", "Projektleitung", "Stellvertretende Projektleitung"]:
        template_name = "tutorial_management.html"
    elif role_name in ["Personalmanagement", "HR Controlling", "HR-Controlling", "Personalabteilung"]:
        template_name = "tutorial_personal.html"
    elif role_name == "Buchhaltung":
        template_name = "tutorial_buchhaltung.html"
    elif role_name in ["Disposition", "Fuhrparkmanagement"]:
        template_name = "tutorial_orga.html"
    else:
        template_name = "tutorial_fahrer.html"

    # Hinweis: Stelle sicher, dass diese HTML-Dateien im `templates` Ordner existieren!
    # Wenn du nur eine Datei (tutorial.html) verwenden willst, passe hier den Namen an 
    # oder nutze Jinja-If-Abfragen in einer globalen tutorial.html.
    return render_template(template_name, current_user=user, primary_role_name=role_name)


@app.route("/downloads")
def downloads():
    if "user" not in session: return redirect(url_for("login"))
    return render_template("download.html")

@app.route("/fuhrpark")
def fuhrpark():
    return render_template("fuhrpark.html")


# ==========================================
# DISPOSITION
# ==========================================

def require_disposition_permission():
    if "user" not in session:
        flash("Bitte logge dich zuerst ein.", "error")
        return redirect(url_for("hub"))

    user_roles = session.get("user", {}).get("roles", [])
    if not has_disposition_permission(user_roles):
        flash("Zugriff verweigert. Du benötigst die Rolle Disposition oder mindestens Projektleitung.", "error")
        return redirect(url_for("dashboard"))

    return None


def current_disposition_identity():
    session_user = session.get("user") or {}
    discord_id = safe_str(session_user.get("id"))
    username = safe_str(session_user.get("username") or session_user.get("discord_username"), "Disposition")

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


def dispo_tour_lookup_query(tour_id):
    tour_id = safe_str(tour_id)
    query_items = [{"tour_id": tour_id}, {"id": tour_id}]
    object_id = object_id_or_none(tour_id)
    if object_id:
        query_items.append({"_id": object_id})
    return {"$or": query_items}


def normalize_dispo_priority(priority):
    priority = safe_str(priority, "normal").lower()
    if priority in {"critical", "kritisch", "urgent", "dringend"}:
        return "critical"
    if priority in {"high", "hoch", "wichtig"}:
        return "high"
    return "normal"


def normalize_dispo_status(status):
    status = safe_str(status, "open").lower()
    if status in {"assigned", "active", "in_progress", "unterwegs", "laufend"}:
        return "active"
    if status in {"done", "completed", "finished", "abgeschlossen"}:
        return "done"
    if status in {"cancelled", "canceled", "storniert"}:
        return "cancelled"
    return "open"


def prepare_dispo_tour_for_template(tour_doc):
    item = dict(tour_doc or {})
    mongo_id = str(item.get("_id")) if item.get("_id") else ""
    assigned_driver = item.get("assigned_driver") or {}

    item["id"] = safe_str(item.get("tour_id") or item.get("id") or mongo_id)
    item["tour_id"] = item["id"]
    item["route_from"] = safe_str(item.get("route_from") or item.get("from") or item.get("source") or item.get("sourceCity"), "-")
    item["route_to"] = safe_str(item.get("route_to") or item.get("to") or item.get("destination") or item.get("destinationCity"), "-")
    item["cargo"] = safe_str(item.get("cargo") or item.get("cargoName"), "-")
    item["payout"] = safe_str(item.get("payout") or item.get("reward") or item.get("income"), "-")
    item["priority"] = normalize_dispo_priority(item.get("priority"))
    item["status"] = normalize_dispo_status(item.get("status"))
    item["deadline"] = safe_str(item.get("deadline") or item.get("deadline_display"), "-")
    item["created_at"] = format_datetime_for_template(item.get("created_at")) or safe_str(item.get("created_at"), "-")
    item["updated_at"] = format_datetime_for_template(item.get("updated_at")) or safe_str(item.get("updated_at"), "-")
    item["assigned_driver"] = safe_str(
        item.get("assigned_driver_name")
        or assigned_driver.get("display_name")
        or assigned_driver.get("username")
        or item.get("driver")
        or item.get("assigned_to"),
        "Nicht gesetzt"
    )

    progress = parse_int(item.get("progress") or item.get("route_progress_percent") or item.get("progress_percent"), 0)
    item["progress"] = max(0, min(progress, 100))
    return item


def prepare_dispo_note_for_template(note_doc):
    item = dict(note_doc or {})
    created_by = item.get("created_by") or {}
    return {
        "id": safe_str(item.get("note_id") or item.get("id") or item.get("_id")),
        "content": safe_str(item.get("content") or item.get("note"), "-"),
        "note": safe_str(item.get("content") or item.get("note"), "-"),
        "author": safe_str(item.get("author") or created_by.get("display_name") or created_by.get("username"), "Disposition"),
        "created_at": format_datetime_for_template(item.get("created_at")) or "-"
    }


def prepare_dispo_message_for_template(message_doc):
    item = dict(message_doc or {})
    return {
        "id": safe_str(item.get("message_id") or item.get("id") or item.get("_id")),
        "title": safe_str(item.get("title"), "Meldung"),
        "content": safe_str(item.get("content") or item.get("message"), "-"),
        "message": safe_str(item.get("content") or item.get("message"), "-"),
        "priority": normalize_dispo_priority(item.get("priority")),
        "created_at": format_datetime_for_template(item.get("created_at")) or "-"
    }


def build_dispo_driver_for_template(user_doc):
    live = user_doc.get("tracker_live") or {}
    display_name = (
        user_doc.get("display_name")
        or user_doc.get("username")
        or user_doc.get("discord_username")
        or "EifelLog Fahrer"
    )

    source_city = safe_str(live.get("sourceCity"), "")
    destination_city = safe_str(live.get("destinationCity"), "")
    current_location = "Standort unbekannt"
    if source_city and destination_city and destination_city != "-":
        current_location = f"{source_city} → {destination_city}"
    elif source_city:
        current_location = source_city
    elif user_doc.get("tracker_online"):
        current_location = "Online"

    return {
        "id": str(user_doc.get("_id")),
        "discord_id": user_doc.get("discord_id"),
        "username": display_name,
        "name": display_name,
        "truck": safe_str(live.get("truck") or user_doc.get("favorite_truck"), "Kein Fahrzeug gesetzt"),
        "current_location": current_location,
        "avatar_url": make_external_url(get_discord_avatar_url(user_doc)),
        "online": bool(user_doc.get("tracker_online", False))
    }


def get_dispo_available_drivers(limit=100):
    clauses = [
        {"fahrer_registration_status": "approved"},
        {"tracker_enabled": True},
        {"tracker_online": True}
    ]

    fahrer_roles = clean_roles([ROLE_FAHRER])
    if fahrer_roles:
        clauses.append({"roles": {"$in": fahrer_roles}})

    active_tours = list(dispo_tours_collection.find(
        {"archived": {"$ne": True}, "status": {"$in": ["assigned", "active", "in_progress"]}},
        {"assigned_driver_id": 1, "assigned_driver.discord_id": 1}
    ))
    busy_driver_ids = {safe_str(tour.get("assigned_driver_id")) for tour in active_tours if safe_str(tour.get("assigned_driver_id"))}
    busy_discord_ids = {safe_str((tour.get("assigned_driver") or {}).get("discord_id")) for tour in active_tours if safe_str((tour.get("assigned_driver") or {}).get("discord_id"))}

    drivers_cursor = users_collection.find({"$or": clauses}).sort([("tracker_online", DESCENDING), ("display_name", ASCENDING), ("username", ASCENDING)]).limit(limit)

    drivers = []
    seen = set()
    for driver in drivers_cursor:
        driver_id = str(driver.get("_id"))
        discord_id = safe_str(driver.get("discord_id"))
        if driver_id in seen or discord_id in seen:
            continue
        if driver_id in busy_driver_ids or discord_id in busy_discord_ids:
            continue
        seen.add(driver_id)
        if discord_id:
            seen.add(discord_id)
        drivers.append(build_dispo_driver_for_template(driver))

    return drivers


@app.route("/dispo", methods=["GET"])
def dispo():
    permission_response = require_disposition_permission()
    if permission_response:
        return permission_response

    user = session.get("user") or {}
    user_roles = user.get("roles", [])
    primary_role_name = get_primary_role_name(user_roles)

    if isinstance(session.get("user"), dict):
        session["user"]["is_disposition"] = True
        permissions = set(item for item in session["user"].get("permissions", []) if item)
        permissions.add("disposition.view")
        permissions.add("disposition.manage")
        session["user"]["permissions"] = sorted(permissions)
        session.modified = True

    open_tours_cursor = dispo_tours_collection.find(
        {"archived": {"$ne": True}, "status": {"$in": ["open", "pending"]}}
    ).sort([("created_at", DESCENDING)]).limit(250)

    active_tours_cursor = dispo_tours_collection.find(
        {"archived": {"$ne": True}, "status": {"$in": ["assigned", "active", "in_progress"]}}
    ).sort([("updated_at", DESCENDING), ("created_at", DESCENDING)]).limit(250)

    messages_cursor = dispo_messages_collection.find(
        {"archived": {"$ne": True}}
    ).sort([("created_at", DESCENDING)]).limit(50)

    notes_cursor = dispo_notes_collection.find(
        {"archived": {"$ne": True}}
    ).sort([("created_at", DESCENDING)]).limit(50)

    dispo_open_tours = [prepare_dispo_tour_for_template(tour) for tour in open_tours_cursor]
    dispo_active_tours = [prepare_dispo_tour_for_template(tour) for tour in active_tours_cursor]
    dispo_available_drivers = get_dispo_available_drivers()
    dispo_messages = [prepare_dispo_message_for_template(message) for message in messages_cursor]
    dispo_notes = [prepare_dispo_note_for_template(note) for note in notes_cursor]

    return render_template(
        "dispo.html",
        current_user=user,
        primary_role_name=primary_role_name,
        dispo_open_tours=dispo_open_tours,
        dispo_active_tours=dispo_active_tours,
        dispo_available_drivers=dispo_available_drivers,
        dispo_messages=dispo_messages,
        dispo_notes=dispo_notes,
        dispo_recent_events=[],
        open_tours_count=len(dispo_open_tours),
        active_tours_count=len(dispo_active_tours),
        available_drivers_count=len(dispo_available_drivers),
        critical_messages_count=len([message for message in dispo_messages if message.get("priority") == "critical"])
    )


@app.route("/dispo/tour/create", methods=["POST"])
def dispo_create_tour():
    permission_response = require_disposition_permission()
    if permission_response:
        return permission_response

    actor = current_disposition_identity()
    route_from = safe_str(request.form.get("route_from"))[:120]
    route_to = safe_str(request.form.get("route_to"))[:120]
    cargo = safe_str(request.form.get("cargo"))[:160]
    payout = safe_str(request.form.get("payout"))[:80]
    priority = normalize_dispo_priority(request.form.get("priority"))
    deadline = safe_str(request.form.get("deadline"))[:120]
    notes = safe_str(request.form.get("notes"))[:1200]

    if len(route_from) < 2 or len(route_to) < 2 or len(cargo) < 2:
        flash("Startort, Zielort und Fracht müssen ausgefüllt sein.", "error")
        return redirect(url_for("dispo"))

    now = now_utc()
    tour_id = uuid.uuid4().hex
    tour_doc = {
        "tour_id": tour_id,
        "route_from": route_from,
        "route_to": route_to,
        "cargo": cargo,
        "payout": payout,
        "priority": priority,
        "deadline": deadline,
        "notes": notes,
        "status": "open",
        "progress": 0,
        "archived": False,
        "created_at": now,
        "updated_at": now,
        "created_by": {
            "discord_id": actor.get("discord_id"),
            "username": actor.get("username"),
            "display_name": actor.get("display_name")
        }
    }

    dispo_tours_collection.insert_one(tour_doc)
    dispo_messages_collection.insert_one({
        "message_id": uuid.uuid4().hex,
        "title": "Neue Tour angelegt",
        "content": f"{route_from} → {route_to} · {cargo}",
        "priority": priority,
        "tour_id": tour_id,
        "archived": False,
        "created_at": now,
        "created_by": actor
    })

    flash("Tour wurde erfolgreich für die Disposition angelegt.", "success")
    return redirect(url_for("dispo"))


@app.route("/dispo/note/create", methods=["POST"])
def dispo_create_note():
    permission_response = require_disposition_permission()
    if permission_response:
        return permission_response

    actor = current_disposition_identity()
    note = safe_str(request.form.get("note"))[:2000]

    if len(note) < 2:
        flash("Die Notiz darf nicht leer sein.", "error")
        return redirect(url_for("dispo"))

    dispo_notes_collection.insert_one({
        "note_id": uuid.uuid4().hex,
        "content": note,
        "author": actor.get("display_name") or actor.get("username") or "Disposition",
        "archived": False,
        "created_at": now_utc(),
        "created_by": {
            "discord_id": actor.get("discord_id"),
            "username": actor.get("username"),
            "display_name": actor.get("display_name")
        }
    })

    flash("Leitstellen-Notiz wurde gespeichert.", "success")
    return redirect(url_for("dispo"))


@app.route("/dispo/tour/assign", methods=["POST"])
@app.route("/dispo/tour/<tour_id>/assign", methods=["POST"])
def dispo_assign_tour(tour_id=None):
    permission_response = require_disposition_permission()
    if permission_response:
        return permission_response

    actor = current_disposition_identity()
    tour_id = safe_str(tour_id or request.form.get("tour_id"))
    driver_id = safe_str(request.form.get("driver_id"))
    assign_note = safe_str(request.form.get("assign_note"))[:1200]

    if not tour_id or not driver_id:
        flash("Bitte Tour und Fahrer auswählen.", "error")
        return redirect(url_for("dispo"))

    tour_doc = dispo_tours_collection.find_one(dispo_tour_lookup_query(tour_id))
    if not tour_doc:
        flash("Tour wurde nicht gefunden.", "error")
        return redirect(url_for("dispo"))

    driver_query_items = []
    driver_object_id = object_id_or_none(driver_id)
    if driver_object_id:
        driver_query_items.append({"_id": driver_object_id})
    driver_query_items.extend([
        {"discord_id": driver_id},
        {"username": driver_id},
        {"username_lc": driver_id.lower()}
    ])
    driver_doc = users_collection.find_one({"$or": driver_query_items})

    if not driver_doc:
        flash("Fahrer wurde nicht gefunden.", "error")
        return redirect(url_for("dispo"))

    now = now_utc()
    driver_name = (
        driver_doc.get("display_name")
        or driver_doc.get("username")
        or driver_doc.get("discord_username")
        or "EifelLog Fahrer"
    )

    assigned_driver = {
        "id": str(driver_doc.get("_id")),
        "discord_id": safe_str(driver_doc.get("discord_id")),
        "username": safe_str(driver_doc.get("username") or driver_doc.get("discord_username")),
        "display_name": driver_name
    }

    dispo_tours_collection.update_one(
        {"_id": tour_doc["_id"]},
        {
            "$set": {
                "status": "assigned",
                "assigned_driver": assigned_driver,
                "assigned_driver_id": assigned_driver["id"],
                "assigned_driver_name": driver_name,
                "assigned_note": assign_note,
                "assigned_at": now,
                "assigned_by": actor,
                "updated_at": now
            }
        }
    )

    route_from = safe_str(tour_doc.get("route_from"), "-")
    route_to = safe_str(tour_doc.get("route_to"), "-")
    cargo = safe_str(tour_doc.get("cargo"), "-")

    dispo_messages_collection.insert_one({
        "message_id": uuid.uuid4().hex,
        "title": "Tour zugewiesen",
        "content": f"{driver_name} wurde für {route_from} → {route_to} eingeteilt.",
        "priority": "normal",
        "tour_id": safe_str(tour_doc.get("tour_id") or tour_doc.get("_id")),
        "archived": False,
        "created_at": now,
        "created_by": actor
    })

    if assigned_driver.get("discord_id"):
        note_block = f'<p class="mt-4"><strong>Hinweis der Disposition:</strong><br>{assign_note}</p>' if assign_note else ""
        create_system_document_for_user(
            assigned_driver["discord_id"],
            "Neue Tour zugewiesen",
            "Disposition",
            f'''
                <p><strong>Dir wurde eine neue Tour zugewiesen.</strong></p>
                <p class="mt-4"><strong>Route:</strong> {route_from} → {route_to}<br>
                <strong>Fracht:</strong> {cargo}<br>
                <strong>Deadline:</strong> {safe_str(tour_doc.get("deadline"), "-")}</p>
                {note_block}
            ''',
            doc_type="disposition_tour_assignment",
            needs_signature=False,
            extra={"tour_id": safe_str(tour_doc.get("tour_id") or tour_doc.get("_id")), "important": True}
        )

    flash("Tour wurde erfolgreich zugewiesen.", "success")
    return redirect(url_for("dispo"))


# ==========================================
# PERSONALABTEILUNG / BUCHHALTUNG / TASKS
# ==========================================

def has_personalabteilung_permission(user_roles):
    clean_user_roles = {str(role).strip() for role in user_roles if role}
    clean_allowed_roles = {str(role).strip() for role in PERSONALABTEILUNG_ALLOWED_ROLES if role}
    return bool(clean_user_roles.intersection(clean_allowed_roles))

def require_personalabteilung_permission():
    if "user" not in session:
        flash("Bitte logge dich zuerst ein.", "error")
        return redirect(url_for("hub"))
    user_roles = session.get("user", {}).get("roles", [])
    if not has_personalabteilung_permission(user_roles):
        flash("Zugriff verweigert. Du benötigst Personalabteilung, HR-Controlling, Geschäftsführung oder Projektleitung.", "error")
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
    if ROLE_STELLVERTRETENDE_PROJEKTLEITUNG_ID in roles: return "Stellvertretende Projektleitung"
    if ROLE_PERSONALABTEILUNG_ID in roles: return "Personalabteilung"
    if ROLE_HR_CONTROLLING_ID in roles or ROLE_HR_CONTROLLING in roles: return "HR-Controlling"
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

    buchhaltung_requests_cursor = buchhaltung_requests_collection.find(
        {"archived": {"$ne": True}}
    ).sort([("created_at", DESCENDING)]).limit(250)
    buchhaltung_requests = [
        prepare_buchhaltung_request_for_personalabteilung(item)
        for item in buchhaltung_requests_cursor
    ]

    # Tasks abrufen: Buchhaltungsanfragen laufen ab jetzt nur noch über den eigenen Tab.
    tasks_cursor = tasks_collection.find({
        "source": {"$ne": "buchhaltung"},
        "type": {"$ne": "Buchhaltung"},
        "buchhaltung_request_id": {"$exists": False}
    }).sort([("created_at", DESCENDING)]).limit(100)
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
        buchhaltung_requests=buchhaltung_requests,
        accounting_requests=buchhaltung_requests,
        accounting_department_requests=buchhaltung_requests,
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

# Diese Rollen/Rechte dürfen alle Buchhaltungseinträge sehen und bearbeiten.
# Wichtig: Die Rechteprüfung passiert hier serverseitig. Frontend-Flags sind nur UI-Hinweise.
BUCHHALTUNG_VIEW_ALL_ROLES = {
    ROLE_BUCHHALTUNG_ID,
    ROLE_BUCHHALTUNG,
    ROLE_GESCHAEFTSFUEHRUNG_ID,
    ROLE_PROJEKTLEITUNG_ID,
    ROLE_GESCHAEFTSLEITUNG,
    ROLE_PROJEKTLEITUNG,
    "admin",
    "owner",
    "verwaltung",
    "buchhaltung",
    "accounting",
    "finance",
    "buchhaltung.view_all",
    "buchhaltung:all",
    "buchhaltung_all",
    "buchhaltung.view.all",
    "buchhaltung_admin",
    "finance_admin"
}


def role_set(user_roles):
    return {str(role).strip() for role in (user_roles or []) if role and str(role).strip()}


def has_buchhaltung_permission(user_roles):
    return bool(role_set(user_roles).intersection(role_set(BUCHHALTUNG_ALLOWED_ROLES)))


def has_buchhaltung_view_all_permission(user_roles):
    return bool(role_set(user_roles).intersection(role_set(BUCHHALTUNG_VIEW_ALL_ROLES)))


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


def actor_owns_buchhaltung_entry(entry_doc, actor):
    if not entry_doc or not actor:
        return False

    created_by = entry_doc.get("created_by") or {}
    actor_discord_id = safe_str(actor.get("discord_id"))
    actor_username = safe_str(actor.get("username")).lower()

    entry_discord_id = safe_str(
        entry_doc.get("created_by_discord_id")
        or entry_doc.get("discord_id")
        or created_by.get("discord_id")
    )
    entry_username = safe_str(
        entry_doc.get("created_by_username")
        or entry_doc.get("username")
        or created_by.get("username")
    ).lower()

    if actor_discord_id and entry_discord_id and actor_discord_id == entry_discord_id:
        return True
    if actor_username and entry_username and actor_username == entry_username:
        return True
    return False


def own_buchhaltung_query(actor):
    discord_id = safe_str(actor.get("discord_id"))
    username = safe_str(actor.get("username"))
    display_name = safe_str(actor.get("display_name"))

    clauses = []
    if discord_id:
        clauses.extend([
            {"created_by.discord_id": discord_id},
            {"created_by_discord_id": discord_id},
            {"discord_id": discord_id},
            {"user_id": discord_id},
            {"owner_id": discord_id}
        ])
    if username:
        clauses.extend([
            {"created_by.username": username},
            {"created_by_username": username},
            {"username": username},
            {"created_by": username}
        ])
    if display_name:
        clauses.extend([
            {"created_by.display_name": display_name},
            {"created_by_name": display_name},
            {"display_name": display_name}
        ])

    if not clauses:
        return {"_id": None}
    return {"$or": clauses}


def buchhaltung_entry_lookup_query(entry_id):
    entry_id = safe_str(entry_id)
    query_items = [{"entry_id": entry_id}, {"id": entry_id}, {"uuid": entry_id}]
    object_id = object_id_or_none(entry_id)
    if object_id:
        query_items.append({"_id": object_id})
    return {"$or": query_items}


def normalize_buchhaltung_type(value):
    value = safe_str(value, "income").lower()
    if value in {"expense", "ausgabe", "kosten", "cost"}:
        return "expense"
    return "income"


def normalize_buchhaltung_payment(value):
    value = safe_str(value, "Offen")[:60]
    value_lc = value.lower()
    if value_lc in {"bezahlt", "paid", "done", "erledigt"}:
        return "Bezahlt"
    if value_lc in {"teilzahlung", "partial", "teilweise"}:
        return "Teilzahlung"
    if value_lc in {"prüfen", "pruefen", "check"}:
        return "Prüfen"
    return "Offen"


def normalize_buchhaltung_receipt(value):
    value = safe_str(value, "Vorhanden")[:60]
    value_lc = value.lower()
    if value_lc in {"fehlt", "missing", "no", "nein"}:
        return "Fehlt"
    if value_lc in {"digital prüfen", "digital pruefen", "prüfen", "pruefen", "check"}:
        return "Digital prüfen"
    return "Vorhanden"


def normalize_buchhaltung_date(value):
    value = safe_str(value)
    if re.match(r"^\d{4}-\d{2}-\d{2}$", value):
        return value
    return now_utc().strftime("%Y-%m-%d")


def calculate_buchhaltung_vat(gross, vat_rate):
    gross = parse_number(gross, 0)
    vat_rate = parse_number(vat_rate, 0)
    if not vat_rate:
        return 0.0
    return round((gross - gross / (1 + vat_rate / 100)) * 100) / 100


def datetime_to_client_iso(value):
    if isinstance(value, datetime):
        return value.isoformat() + "Z"
    if value:
        return str(value)
    return ""


def prepare_buchhaltung_entry_for_api(entry_doc):
    item = dict(entry_doc or {})
    created_by = item.get("created_by") or {}
    updated_by = item.get("updated_by") or {}

    entry_id = safe_str(item.get("entry_id") or item.get("id") or item.get("uuid") or item.get("_id"))
    if item.get("_id"):
        mongo_id = str(item.get("_id"))
    else:
        mongo_id = ""

    entry_type = normalize_buchhaltung_type(item.get("type"))
    amount = round(parse_number(item.get("amount") or item.get("gross_amount") or item.get("brutto"), 0), 2)
    vat_rate = round(parse_number(item.get("vat_rate") or item.get("vatRate") or item.get("vat") or item.get("tax_rate"), 0), 2)
    vat_amount = round(parse_number(item.get("vat_amount") or item.get("vatAmount") or item.get("tax_amount"), calculate_buchhaltung_vat(amount, vat_rate)), 2)

    created_by_name = safe_str(
        item.get("created_by_name")
        or item.get("createdBy")
        or created_by.get("display_name")
        or created_by.get("username")
        or item.get("username"),
        "Unbekannt"
    )

    result = {
        "_id": mongo_id,
        "id": entry_id or mongo_id,
        "entry_id": entry_id or mongo_id,
        "createdAt": datetime_to_client_iso(item.get("created_at") or item.get("createdAt")),
        "created_at": datetime_to_client_iso(item.get("created_at") or item.get("createdAt")),
        "updatedAt": datetime_to_client_iso(item.get("updated_at") or item.get("updatedAt")),
        "updated_at": datetime_to_client_iso(item.get("updated_at") or item.get("updatedAt")),
        "createdBy": created_by_name,
        "created_by_name": created_by_name,
        "created_by": {
            "discord_id": safe_str(created_by.get("discord_id") or item.get("created_by_discord_id") or item.get("discord_id")),
            "username": safe_str(created_by.get("username") or item.get("created_by_username") or item.get("username")),
            "display_name": safe_str(created_by.get("display_name") or created_by_name)
        },
        "updated_by": {
            "discord_id": safe_str(updated_by.get("discord_id")),
            "username": safe_str(updated_by.get("username")),
            "display_name": safe_str(updated_by.get("display_name"))
        },
        "userId": safe_str(created_by.get("discord_id") or item.get("created_by_discord_id") or item.get("discord_id") or item.get("user_id")),
        "user_id": safe_str(created_by.get("discord_id") or item.get("created_by_discord_id") or item.get("discord_id") or item.get("user_id")),
        "date": normalize_buchhaltung_date(item.get("date")),
        "type": entry_type,
        "typeLabel": "Einnahme" if entry_type == "income" else "Ausgabe",
        "type_label": "Einnahme" if entry_type == "income" else "Ausgabe",
        "category": safe_str(item.get("category"), "Sonstiges")[:120],
        "amount": amount,
        "gross_amount": amount,
        "vatRate": vat_rate,
        "vat_rate": vat_rate,
        "vatAmount": vat_amount,
        "vat_amount": vat_amount,
        "documentNo": safe_str(item.get("document_no") or item.get("documentNo") or item.get("document") or item.get("invoice_no"))[:120],
        "document_no": safe_str(item.get("document_no") or item.get("documentNo") or item.get("document") or item.get("invoice_no"))[:120],
        "partner": safe_str(item.get("partner") or item.get("customer") or item.get("supplier") or item.get("driver"))[:120],
        "tour": safe_str(item.get("tour") or item.get("plate") or item.get("vehicle"))[:120],
        "receipt": normalize_buchhaltung_receipt(item.get("receipt_status") or item.get("receipt")),
        "receipt_status": normalize_buchhaltung_receipt(item.get("receipt_status") or item.get("receipt")),
        "payment": normalize_buchhaltung_payment(item.get("payment_status") or item.get("payment")),
        "payment_status": normalize_buchhaltung_payment(item.get("payment_status") or item.get("payment")),
        "note": safe_str(item.get("note") or item.get("notes"))[:1000],
        "source": safe_str(item.get("source"), "buchhaltung2")[:80]
    }
    return result


def build_buchhaltung_entry_doc(data, actor):
    data = data or {}
    amount = round(parse_number(data.get("amount") or data.get("gross_amount") or data.get("brutto"), 0), 2)
    vat_rate = round(parse_number(data.get("vat_rate") or data.get("vatRate") or data.get("vat") or data.get("tax_rate"), 0), 2)
    vat_amount = round(parse_number(data.get("vat_amount") or data.get("vatAmount") or data.get("tax_amount"), calculate_buchhaltung_vat(amount, vat_rate)), 2)
    entry_type = normalize_buchhaltung_type(data.get("type"))
    now = now_utc()

    return {
        "entry_id": uuid.uuid4().hex,
        "date": normalize_buchhaltung_date(data.get("date")),
        "type": entry_type,
        "type_label": "Einnahme" if entry_type == "income" else "Ausgabe",
        "category": safe_str(data.get("category"), "Sonstiges")[:120],
        "amount": amount,
        "gross_amount": amount,
        "currency": "EUR",
        "vat_rate": vat_rate,
        "vat_amount": vat_amount,
        "document_no": safe_str(data.get("document_no") or data.get("documentNo") or data.get("document") or data.get("invoice_no"))[:120],
        "partner": safe_str(data.get("partner") or data.get("customer") or data.get("supplier") or data.get("driver"))[:120],
        "tour": safe_str(data.get("tour") or data.get("plate") or data.get("vehicle"))[:120],
        "receipt_status": normalize_buchhaltung_receipt(data.get("receipt_status") or data.get("receipt")),
        "payment_status": normalize_buchhaltung_payment(data.get("payment_status") or data.get("payment")),
        "note": safe_str(data.get("note") or data.get("notes"))[:1000],
        "source": safe_str(data.get("source"), "buchhaltung2")[:80],
        "archived": False,
        "created_at": now,
        "updated_at": now,
        "created_by": {
            "discord_id": safe_str(actor.get("discord_id")),
            "username": safe_str(actor.get("username")),
            "display_name": safe_str(actor.get("display_name"))
        },
        "created_by_discord_id": safe_str(actor.get("discord_id")),
        "created_by_username": safe_str(actor.get("username")),
        "created_by_name": safe_str(actor.get("display_name") or actor.get("username"))
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
    user_roles = session.get("user", {}).get("roles", [])
    can_view_all_entries = has_buchhaltung_view_all_permission(user_roles)

    # Die neue buchhaltung2.html liest diese Flags direkt aus der Session.
    # Ohne diese Flags würden Rollen-IDs im Frontend nicht als "Buchhaltung" erkannt.
    if isinstance(session.get("user"), dict):
        session["user"]["buchhaltung_view_all"] = can_view_all_entries
        session["user"]["can_view_all_buchhaltung"] = can_view_all_entries
        session["user"]["is_buchhaltung"] = has_buchhaltung_permission(user_roles)
        permissions = set(to_string for to_string in session["user"].get("permissions", []) if to_string)
        if can_view_all_entries:
            permissions.add("buchhaltung.view_all")
        session["user"]["permissions"] = sorted(permissions)
        session.modified = True

    return render_template(
        "buchhaltung2.html",
        current_user=session.get("user"),
        display_name=actor.get("username") or actor.get("display_name"),
        staff_name=actor.get("display_name"),
        can_view_all_buchhaltung=can_view_all_entries,
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


@app.route("/api/buchhaltung/entries", methods=["GET", "POST", "OPTIONS"])
def api_buchhaltung_entries():
    if request.method == "OPTIONS":
        return jsonify({"success": True})

    permission_response = require_buchhaltung_api_permission()
    if permission_response:
        return permission_response

    actor = current_account_identity()
    user_roles = session.get("user", {}).get("roles", [])
    can_view_all_entries = has_buchhaltung_view_all_permission(user_roles)

    if request.method == "GET":
        requested_scope = safe_str(request.args.get("scope"), "own").lower()
        query = {"archived": {"$ne": True}}
        scope = "own"

        if requested_scope == "all":
            if not can_view_all_entries:
                return jsonify({
                    "success": False,
                    "message": "Nicht berechtigt, alle Buchhaltungseinträge zu sehen."
                }), 403
            scope = "all"
        else:
            query.update(own_buchhaltung_query(actor))

        limit = max(1, min(parse_int(request.args.get("limit"), 500), 1000))
        items_cursor = buchhaltung_entries_collection.find(query).sort(
            [("date", DESCENDING), ("created_at", DESCENDING)]
        ).limit(limit)
        entries = [prepare_buchhaltung_entry_for_api(item) for item in items_cursor]

        return jsonify({
            "success": True,
            "scope": scope,
            "can_view_all": can_view_all_entries,
            "entries": entries
        })

    data = request.get_json(silent=True) or {}
    amount = parse_number(data.get("amount") or data.get("gross_amount") or data.get("brutto"), 0)
    if amount <= 0:
        return jsonify({"success": False, "message": "Bitte einen gültigen Bruttobetrag eingeben."}), 400

    entry_doc = build_buchhaltung_entry_doc(data, actor)
    buchhaltung_entries_collection.insert_one(entry_doc)
    created = buchhaltung_entries_collection.find_one({"entry_id": entry_doc["entry_id"]})

    return jsonify({
        "success": True,
        "message": "Buchung wurde serverseitig gespeichert.",
        "entry": prepare_buchhaltung_entry_for_api(created)
    }), 201


@app.route("/api/buchhaltung/entries/<entry_id>", methods=["GET", "PATCH", "DELETE", "OPTIONS"])
def api_buchhaltung_entry_detail(entry_id):
    if request.method == "OPTIONS":
        return jsonify({"success": True})

    permission_response = require_buchhaltung_api_permission()
    if permission_response:
        return permission_response

    actor = current_account_identity()
    user_roles = session.get("user", {}).get("roles", [])
    can_view_all_entries = has_buchhaltung_view_all_permission(user_roles)

    lookup = buchhaltung_entry_lookup_query(entry_id)
    query = {"$and": [lookup, {"archived": {"$ne": True}}]}
    entry_doc = buchhaltung_entries_collection.find_one(query)

    if not entry_doc:
        return jsonify({"success": False, "message": "Buchung wurde nicht gefunden."}), 404

    if not can_view_all_entries and not actor_owns_buchhaltung_entry(entry_doc, actor):
        return jsonify({"success": False, "message": "Nicht berechtigt für diese Buchung."}), 403

    if request.method == "GET":
        return jsonify({"success": True, "entry": prepare_buchhaltung_entry_for_api(entry_doc)})

    now = now_utc()

    if request.method == "DELETE":
        buchhaltung_entries_collection.update_one(
            {"_id": entry_doc["_id"]},
            {
                "$set": {
                    "archived": True,
                    "archived_at": now,
                    "archived_by": actor,
                    "updated_at": now,
                    "updated_by": actor
                }
            }
        )
        return jsonify({"success": True, "message": "Buchung wurde gelöscht."})

    data = request.get_json(silent=True) or {}
    update_fields = {}

    if "date" in data:
        update_fields["date"] = normalize_buchhaltung_date(data.get("date"))
    if "type" in data:
        entry_type = normalize_buchhaltung_type(data.get("type"))
        update_fields["type"] = entry_type
        update_fields["type_label"] = "Einnahme" if entry_type == "income" else "Ausgabe"
    if "category" in data:
        update_fields["category"] = safe_str(data.get("category"), "Sonstiges")[:120]
    if "document_no" in data or "documentNo" in data or "document" in data or "invoice_no" in data:
        update_fields["document_no"] = safe_str(data.get("document_no") or data.get("documentNo") or data.get("document") or data.get("invoice_no"))[:120]
    if "partner" in data or "customer" in data or "supplier" in data or "driver" in data:
        update_fields["partner"] = safe_str(data.get("partner") or data.get("customer") or data.get("supplier") or data.get("driver"))[:120]
    if "tour" in data or "plate" in data or "vehicle" in data:
        update_fields["tour"] = safe_str(data.get("tour") or data.get("plate") or data.get("vehicle"))[:120]
    if "receipt_status" in data or "receipt" in data:
        update_fields["receipt_status"] = normalize_buchhaltung_receipt(data.get("receipt_status") or data.get("receipt"))
    if "payment_status" in data or "payment" in data:
        update_fields["payment_status"] = normalize_buchhaltung_payment(data.get("payment_status") or data.get("payment"))
    if "note" in data or "notes" in data:
        update_fields["note"] = safe_str(data.get("note") or data.get("notes"))[:1000]

    amount_changed = "amount" in data or "gross_amount" in data or "brutto" in data
    vat_rate_changed = "vat_rate" in data or "vatRate" in data or "vat" in data or "tax_rate" in data
    vat_amount_changed = "vat_amount" in data or "vatAmount" in data or "tax_amount" in data

    if amount_changed:
        amount = round(parse_number(data.get("amount") or data.get("gross_amount") or data.get("brutto"), 0), 2)
        if amount <= 0:
            return jsonify({"success": False, "message": "Bitte einen gültigen Bruttobetrag eingeben."}), 400
        update_fields["amount"] = amount
        update_fields["gross_amount"] = amount

    if vat_rate_changed:
        update_fields["vat_rate"] = round(parse_number(data.get("vat_rate") or data.get("vatRate") or data.get("vat") or data.get("tax_rate"), 0), 2)

    if vat_amount_changed:
        update_fields["vat_amount"] = round(parse_number(data.get("vat_amount") or data.get("vatAmount") or data.get("tax_amount"), 0), 2)
    elif amount_changed or vat_rate_changed:
        current_amount = update_fields.get("amount", parse_number(entry_doc.get("amount"), 0))
        current_vat_rate = update_fields.get("vat_rate", parse_number(entry_doc.get("vat_rate"), 0))
        update_fields["vat_amount"] = calculate_buchhaltung_vat(current_amount, current_vat_rate)

    if not update_fields:
        return jsonify({"success": True, "message": "Keine Änderung übergeben.", "entry": prepare_buchhaltung_entry_for_api(entry_doc)})

    update_fields["updated_at"] = now
    update_fields["updated_by"] = actor

    buchhaltung_entries_collection.update_one({"_id": entry_doc["_id"]}, {"$set": update_fields})
    updated = buchhaltung_entries_collection.find_one({"_id": entry_doc["_id"]})

    return jsonify({
        "success": True,
        "message": "Buchung wurde aktualisiert.",
        "entry": prepare_buchhaltung_entry_for_api(updated)
    })


@app.route("/api/buchhaltung/request", methods=["GET", "POST", "OPTIONS"])
def api_buchhaltung_request():
    if request.method == "OPTIONS":
        return jsonify({"success": True})

    permission_response = require_buchhaltung_api_permission()
    if permission_response:
        return permission_response

    if request.method == "GET":
        items_cursor = buchhaltung_requests_collection.find(
            {"archived": {"$ne": True}}
        ).sort("created_at", DESCENDING).limit(100)
        items = [
            prepare_buchhaltung_request_for_personalabteilung(item)
            for item in items_cursor
        ]
        return jsonify({"success": True, "requests": items})

    data = request.get_json(silent=True) or {}

    category = safe_str(data.get("category") or data.get("type"), "Allgemeine Rückfrage")[:120]
    title = safe_str(data.get("title") or data.get("subject"), "Buchhaltungs-Anfrage")[:160]
    message = safe_str(data.get("message") or data.get("description") or data.get("content"))[:2000]
    amount = parse_number(data.get("amount"), 0)
    priority = safe_str(data.get("priority"), "normal")[:40]
    entries_snapshot = data.get("entries") if isinstance(data.get("entries"), list) else []

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
        "subject": title,
        "description": message,
        "message": message,
        "reference": safe_str(data.get("reference") or data.get("ref") or data.get("bezug"))[:160],
        "target_department": safe_str(data.get("target_department"), "Personalabteilung")[:80],
        "amount": amount,
        "currency": "EUR",
        "priority": normalize_buchhaltung_priority(priority),
        "status": "open",
        "archived": False,
        "created_at": now,
        "updated_at": now,
        "created_by": actor,
        "created_by_name": actor.get("display_name"),
        "sender_name": actor.get("display_name"),
        "sender_discord_id": actor.get("discord_id"),
        "sender_username": actor.get("username"),
        "source": "buchhaltung",
        "scope": safe_str(data.get("scope"), "")[:40],
        "entries_snapshot": entries_snapshot[:500],
        "destination": "personalabteilung",
        "visible_in_personalabteilung_tab": True
    }

    buchhaltung_requests_collection.insert_one(request_doc)

    return jsonify({
        "success": True,
        "message": "Buchhaltungs-Anfrage wurde gespeichert und direkt an den Tab der Personalabteilung gesendet.",
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
            "/api/tracker/state", "/api/tracker/telemetry/live",
            "/api/tracker/tour/submit", "/api/tracker/job/complete", "/api/tracker/logout"
        ]
    })


# ==========================================
# SERVER START
# ==========================================

if __name__ == "__main__":
    print(f"Starte Eifel LOG Server mit MongoDB DB '{MONGO_DB_NAME}' und Eventlet auf {SERVER_HOST}:{SERVER_PORT}...")
    eventlet.wsgi.server(eventlet.listen((SERVER_HOST, SERVER_PORT)), app)