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
from io import BytesIO
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, render_template, render_template_string, redirect, request, session, url_for, flash, jsonify, abort, send_file
from dotenv import load_dotenv
from pymongo import MongoClient, ASCENDING, DESCENDING
from bson.objectid import ObjectId
from werkzeug.utils import secure_filename

try:
    from PIL import Image, ImageOps
    PIL_AVAILABLE = True
except Exception:
    Image = None
    ImageOps = None
    PIL_AVAILABLE = False


# ==========================================
# GRUNDKONFIGURATION
# ==========================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, ".env")

load_dotenv(dotenv_path=ENV_PATH, override=True)

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", os.urandom(24))
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024


@app.context_processor
def inject_template_helpers():
    """Stellt Template-Helfer bereit, damit reine Flask-Templates mit csrf_token() sauber rendern."""
    def csrf_token():
        token = session.get("_csrf_token")
        if not token:
            token = secrets.token_hex(16)
            session["_csrf_token"] = token
        return token

    return {"csrf_token": csrf_token}

PROFILE_UPLOAD_FOLDER = os.path.join("static", "uploads", "profiles")
ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}

TRACKER_API_KEY = os.getenv("TRACKER_API_KEY", "").strip()

# Discord Webhook für Job-Abschluss-Meldungen vom Tracker.
# Wichtig: Webhook-URLs bitte nur über .env setzen, nicht fest im Code speichern.
DISCORD_JOB_COMPLETE_WEBHOOK_URL = os.getenv("DISCORD_JOB_COMPLETE_WEBHOOK_URL", "").strip()


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
TOUR_CHANNEL_ID = env_first(
    "TOUR_CHANNEL_ID",
    "DISCORD_TOUR_CHANNEL_ID",
    "TOUREN_CHANNEL_ID",
    "DISCORD_TOUREN_CHANNEL_ID",
    default="1473756766478270517"
)
TOUR_RECEIPT_CHANNEL_ID = env_first(
    "TOUR_RECEIPT_CHANNEL_ID",
    "DISCORD_TOUR_RECEIPT_CHANNEL_ID",
    "DISCORD_ABRECHNUNG_CHANNEL_ID",
    "ABRECHNUNG_CHANNEL_ID",
    default=TOUR_CHANNEL_ID
)
DISCORD_TOUR_WEBHOOK_URL = env_first(
    "DISCORD_TOUR_WEBHOOK_URL",
    "TOUR_CHANNEL_WEBHOOK_URL",
    "DISCORD_TOUREN_WEBHOOK_URL",
    "TOUREN_WEBHOOK_URL",
    default=DISCORD_JOB_COMPLETE_WEBHOOK_URL
)
TOUR_START_DISCORD_ENABLED = env_bool("TOUR_START_DISCORD_ENABLED", "DISCORD_TOUR_START_ENABLED", default=True)
TOUR_RECEIPT_ENABLED = env_bool("TOUR_RECEIPT_ENABLED", default=True)
TOUR_RECEIPT_DISCORD_ENABLED = env_bool("TOUR_RECEIPT_DISCORD_ENABLED", default=True)
TOUR_RECEIPT_FOLDER = env_first(
    "TOUR_RECEIPT_FOLDER",
    "RECEIPT_FOLDER",
    default=os.path.join("static", "downloads", "tour_receipts")
)
SERVICECENTER_FAHRERKARTE_FOLDER = env_first(
    "SERVICECENTER_FAHRERKARTE_FOLDER",
    "FAHRERKARTE_DOWNLOAD_FOLDER",
    default=os.path.join("static", "downloads", "servicecenter", "fahrerkarten")
)
DISPO_FORM_UPLOAD_FOLDER = env_first(
    "DISPO_FORM_UPLOAD_FOLDER",
    "DISPO_BELEG_UPLOAD_FOLDER",
    default=os.path.join("static", "uploads", "dispo_form")
)
ALLOWED_DISPO_FORM_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "webp"}
TRACKER_DRIVER_CARD_UPLOAD_FOLDER = env_first(
    "TRACKER_DRIVER_CARD_UPLOAD_FOLDER",
    "FAHRERKARTE_TRACKER_UPLOAD_FOLDER",
    default=os.path.join("static", "uploads", "tracker_driver_cards")
)
ALLOWED_TRACKER_DRIVER_CARD_EXTENSIONS = {"pdf"}
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
company_stats_collection = db["company_stats"]
dispo_tours_collection = db["dispo_tours"]
dispo_notes_collection = db["dispo_notes"]
dispo_messages_collection = db["dispo_messages"]
dispo_form_entries_collection = db["dispo_form_entries"]
fahrerkarte_requests_collection = db["fahrerkarte_requests"]
fahrerkarte_beantragungen_collection = db[env_first(
    "SERVICECENTER_COLLECTION_NAME",
    "FAHRERKARTE_BEANTRAGUNGEN_COLLECTION",
    default="FahrerkarteBeantragungen"
)]

tracker_driver_cards_collection = db["tracker_driver_cards"]
tracker_work_sessions_collection = db["tracker_work_sessions"]
tracker_job_starts_collection = db["tracker_job_starts"]


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

        company_stats_collection.create_index([("kind", ASCENDING)], unique=False)
        company_stats_collection.create_index([("updated_at", DESCENDING)], unique=False)

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

        dispo_form_entries_collection.create_index([("entry_id", ASCENDING)], unique=False)
        dispo_form_entries_collection.create_index([("entry_source", ASCENDING)], unique=False)
        dispo_form_entries_collection.create_index([("entry_type", ASCENDING)], unique=False)
        dispo_form_entries_collection.create_index([("document_type", ASCENDING)], unique=False)
        dispo_form_entries_collection.create_index([("status", ASCENDING)], unique=False)
        dispo_form_entries_collection.create_index([("submitted_by.discord_id", ASCENDING)], unique=False)
        dispo_form_entries_collection.create_index([("submitted_by.username", ASCENDING)], unique=False)
        dispo_form_entries_collection.create_index([("reference", ASCENDING)], unique=False)
        dispo_form_entries_collection.create_index([("created_at", DESCENDING)], unique=False)
        dispo_form_entries_collection.create_index([("archived", ASCENDING)], unique=False)

        fahrerkarte_requests_collection.create_index([("request_id", ASCENDING)], unique=False)
        fahrerkarte_requests_collection.create_index([("discord_id", ASCENDING)], unique=False)
        fahrerkarte_requests_collection.create_index([("status", ASCENDING)], unique=False)
        fahrerkarte_requests_collection.create_index([("created_at", DESCENDING)], unique=False)
        fahrerkarte_requests_collection.create_index([("issued_at", DESCENDING)], unique=False)
        fahrerkarte_requests_collection.create_index([("claimed_by.discord_id", ASCENDING)], unique=False)
        fahrerkarte_requests_collection.create_index([("card_id", ASCENDING)], unique=False)
        fahrerkarte_requests_collection.create_index([("pdf_relative_path", ASCENDING)], unique=False)
        fahrerkarte_requests_collection.create_index([("archived", ASCENDING)], unique=False)

        fahrerkarte_beantragungen_collection.create_index([("request_id", ASCENDING)], unique=False)
        fahrerkarte_beantragungen_collection.create_index([("fahrerkarte_request_id", ASCENDING)], unique=False)
        fahrerkarte_beantragungen_collection.create_index([("discord_id", ASCENDING)], unique=False)
        fahrerkarte_beantragungen_collection.create_index([("user_id", ASCENDING)], unique=False)
        fahrerkarte_beantragungen_collection.create_index([("status", ASCENDING)], unique=False)
        fahrerkarte_beantragungen_collection.create_index([("fahrerkarte_status", ASCENDING)], unique=False)
        fahrerkarte_beantragungen_collection.create_index([("personalisierte_fahrerkarte_status", ASCENDING)], unique=False)
        fahrerkarte_beantragungen_collection.create_index([("source_user_mongo_id", ASCENDING)], unique=False)
        fahrerkarte_beantragungen_collection.create_index([("created_at", DESCENDING)], unique=False)
        fahrerkarte_beantragungen_collection.create_index([("updated_at", DESCENDING)], unique=False)

        tracker_driver_cards_collection.create_index([("discord_id", ASCENDING)], unique=False)
        tracker_driver_cards_collection.create_index([("user_id", ASCENDING)], unique=False)
        tracker_driver_cards_collection.create_index([("card_id", ASCENDING)], unique=False)
        tracker_driver_cards_collection.create_index([("created_at", DESCENDING)], unique=False)
        tracker_driver_cards_collection.create_index([("updated_at", DESCENDING)], unique=False)
        tracker_driver_cards_collection.create_index([("archived", ASCENDING)], unique=False)

        tracker_work_sessions_collection.create_index([("discord_id", ASCENDING)], unique=False)
        tracker_work_sessions_collection.create_index([("status", ASCENDING)], unique=False)
        tracker_work_sessions_collection.create_index([("updated_at", DESCENDING)], unique=False)

        tracker_job_starts_collection.create_index([("discord_id", ASCENDING)], unique=False)
        tracker_job_starts_collection.create_index([("job_id", ASCENDING)], unique=False)
        tracker_job_starts_collection.create_index([("status", ASCENDING)], unique=False)
        tracker_job_starts_collection.create_index([("created_at", DESCENDING)], unique=False)
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
ROLE_FAHRER_ID = env_first("ROLE_FAHRER_ID", "FAHRER_ROLE_ID", default=ROLE_FAHRER or "1473721587101339681")
ROLE_FUHRPARKMANAGEMENT_ID = env_first("ROLE_FUHRPARKMANAGEMENT_ID", "FUHRPARKMANAGEMENT_ROLE_ID", "FUHRPARK_ROLE_ID", default=ROLE_FUHRPARKMANAGEMENT or "")
ROLE_HR_CONTROLLING_ID = env_first("ROLE_HR_CONTROLLING_ID", "HR_CONTROLLING_ROLE_ID", default=ROLE_HR_CONTROLLING or "1473726292963885188")
ROLE_DISPOSITION_ID = env_first("ROLE_DISPOSITION_ID", "DISPOSITION_ROLE_ID", default=ROLE_DISPOSITION or "")

# ==========================================
# SERVICECENTER / WEB-ONLY FAHRERKARTE
# ==========================================
# Die Fahrerkarte-Bearbeitung laeuft vollstaendig im Web-ServiceCenter.
# Es werden keine Discord-Threads, Discord-Plugin-Mirrors oder Discord-PDF-Fallbacks mehr benoetigt.
SERVICECENTER_DISCORD_ENABLED = False
SERVICECENTER_DISCORD_CHANNEL_ID = env_first(
    "SERVICECENTER_DISCORD_CHANNEL_ID",
    "SERVICECENTER_CHANNEL_ID",
    default="1505988896952156350"
)
SERVICECENTER_DISCORD_CREATE_THREAD = env_bool("SERVICECENTER_DISCORD_CREATE_THREAD", default=True)
SERVICECENTER_DISCORD_ATTACH_PDF_ON_ISSUE = env_bool("SERVICECENTER_DISCORD_ATTACH_PDF_ON_ISSUE", default=True)
SERVICECENTER_DISCORD_THREAD_AUTO_ARCHIVE_DURATION = int(env_float(
    "SERVICECENTER_DISCORD_THREAD_AUTO_ARCHIVE_DURATION",
    default=10080
))
SERVICECENTER_PUBLIC_BASE_URL = env_first(
    "SERVICECENTER_PUBLIC_BASE_URL",
    "PUBLIC_BASE_URL",
    "TOUR_RECEIPT_PUBLIC_BASE_URL",
    default=""
).rstrip("/")
SERVICECENTER_DISCORD_REVIEW_ROLE_IDS_RAW = env_first(
    "SERVICECENTER_DISCORD_REVIEW_ROLE_IDS",
    "SERVICECENTER_REVIEW_ROLE_IDS",
    default=""
)

ALLOWED_HUB_ROLES = [
    ROLE_FAHRER,
    ROLE_FAHRER_ID,
    ROLE_GESCHAEFTSLEITUNG,
    ROLE_GESCHAEFTSFUEHRUNG_ID,
    ROLE_PROJEKTLEITUNG,
    ROLE_PROJEKTLEITUNG_ID,
    ROLE_STELLVERTRETENDE_PROJEKTLEITUNG,
    ROLE_STELLVERTRETENDE_PROJEKTLEITUNG_ID,
    ROLE_FUHRPARKMANAGEMENT,
    ROLE_FUHRPARKMANAGEMENT_ID,
    ROLE_BUCHHALTUNG,
    ROLE_BUCHHALTUNG_ID,
    ROLE_HR_CONTROLLING,
    ROLE_HR_CONTROLLING_ID,
    ROLE_DISPOSITION,
    ROLE_DISPOSITION_ID,
    ROLE_PERSONALMANAGEMENT,
    ROLE_PERSONALABTEILUNG_ID
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
    "Disponent",
    "disposition",
    "disponent",
    "dispo",
    "Geschäftsleitung",
    "Geschaeftsleitung",
    "Geschäftsführung",
    "Geschaeftsfuehrung",
    "Projektleitung",
    "projektleitung"
}

GESCHAEFTSLEITUNG_ALLOWED_ROLES = {
    ROLE_GESCHAEFTSLEITUNG,
    ROLE_GESCHAEFTSFUEHRUNG_ID,
    ROLE_PROJEKTLEITUNG,
    ROLE_PROJEKTLEITUNG_ID,
    "Geschäftsleitung",
    "Geschaeftsleitung",
    "Geschäftsführung",
    "Geschaeftsfuehrung",
    "geschäftsleitung",
    "geschaeftsleitung",
    "geschäftsführung",
    "geschaeftsfuehrung",
    "Projektleitung",
    "projektleitung"
}

# Rollen, die die Dispo-Formularseite öffnen und Belege einreichen dürfen.
# Der Zugriff auf /dispo/form ist bewusst breit, die Einsicht in eingereichte Dokumente bleibt getrennt.
DISPO_FORM_ACCESS_ROLES = {
    ROLE_FAHRER,
    ROLE_FAHRER_ID,
    ROLE_BUCHHALTUNG,
    ROLE_BUCHHALTUNG_ID,
    ROLE_HR_CONTROLLING,
    ROLE_HR_CONTROLLING_ID,
    ROLE_FUHRPARKMANAGEMENT,
    ROLE_FUHRPARKMANAGEMENT_ID,
    ROLE_PERSONALMANAGEMENT,
    ROLE_PERSONALABTEILUNG_ID,
    ROLE_DISPOSITION,
    ROLE_DISPOSITION_ID,
    ROLE_GESCHAEFTSLEITUNG,
    ROLE_GESCHAEFTSFUEHRUNG_ID,
    ROLE_PROJEKTLEITUNG,
    ROLE_PROJEKTLEITUNG_ID,
    ROLE_STELLVERTRETENDE_PROJEKTLEITUNG,
    ROLE_STELLVERTRETENDE_PROJEKTLEITUNG_ID,
    "Fahrer",
    "fahrer",
    "Buchhaltung",
    "buchhaltung",
    "HR-Controlling",
    "HR Controlling",
    "hr-controlling",
    "hr controlling",
    "Fuhrparkmanagement",
    "fuhrparkmanagement",
    "Personalmanagement",
    "Personalabteilung",
    "personalmanagement",
    "personalabteilung",
    "Disposition",
    "Disponent",
    "disposition",
    "disponent",
    "dispo",
    "Geschäftsleitung",
    "Geschaeftsleitung",
    "Geschäftsführung",
    "Geschaeftsfuehrung",
    "Projektleitung",
    "projektleitung",
    "Stellvertretende Projektleitung",
    "stellvertretende projektleitung"
}

# Nur diese Rolle sieht auf /dispo/form die Disponenten-Ansicht / Sektion „Eingereichte Dokumente“.
DISPO_SUBMITTED_DOCUMENTS_ALLOWED_ROLES = {
    ROLE_DISPOSITION,
    ROLE_DISPOSITION_ID,
    "Disposition",
    "Disponent",
    "disposition",
    "disponent",
    "dispo"
}

# Diese Rollen sollen die Sektion „Eingereichte Dokumente“ ausdrücklich nicht sehen.
DISPO_SUBMITTED_DOCUMENTS_BLOCKED_ROLES = {
    ROLE_HR_CONTROLLING,
    ROLE_HR_CONTROLLING_ID,
    ROLE_FAHRER,
    ROLE_FAHRER_ID,
    ROLE_BUCHHALTUNG,
    ROLE_BUCHHALTUNG_ID,
    ROLE_PERSONALMANAGEMENT,
    ROLE_PERSONALABTEILUNG_ID,
    ROLE_FUHRPARKMANAGEMENT,
    ROLE_FUHRPARKMANAGEMENT_ID,
    "HR-Controlling",
    "HR Controlling",
    "hr-controlling",
    "hr controlling",
    "Fahrer",
    "fahrer",
    "Buchhaltung",
    "buchhaltung",
    "Personalmanagement",
    "Personalabteilung",
    "personalmanagement",
    "personalabteilung",
    "Fuhrparkmanagement",
    "fuhrparkmanagement"
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


def has_geschaeftsleitung_permission(user_roles):
    clean_user_roles = set(clean_roles(user_roles))
    clean_allowed_roles = set(clean_roles(GESCHAEFTSLEITUNG_ALLOWED_ROLES))
    if clean_user_roles.intersection(clean_allowed_roles):
        return True

    primary_role_name = get_primary_role_name(user_roles)
    return primary_role_name in {"Geschäftsleitung", "Geschäftsführung", "Projektleitung"}


def has_dispo_form_access(user_roles):
    clean_user_roles = set(clean_roles(user_roles))
    clean_allowed_roles = set(clean_roles(DISPO_FORM_ACCESS_ROLES))
    if clean_user_roles.intersection(clean_allowed_roles):
        return True

    # Fallback: Jeder eingeloggte Discord-Nutzer aus der App darf das Formular betreten.
    return True


def has_dispo_submitted_documents_permission(user_roles):
    clean_user_roles = set(clean_roles(user_roles))
    clean_allowed_roles = set(clean_roles(DISPO_SUBMITTED_DOCUMENTS_ALLOWED_ROLES))

    # Disposition überschreibt Basisrollen wie Fahrer, falls ein Disponent mehrere Discord-Rollen besitzt.
    if clean_user_roles.intersection(clean_allowed_roles):
        return True

    primary_role_name = get_primary_role_name(user_roles)
    return primary_role_name in {"Disposition"}


def has_dispo_blocked_documents_role(user_roles):
    clean_user_roles = set(clean_roles(user_roles))
    clean_blocked_roles = set(clean_roles(DISPO_SUBMITTED_DOCUMENTS_BLOCKED_ROLES))
    return bool(clean_user_roles.intersection(clean_blocked_roles))


def get_primary_role_name(user_roles):
    clean_user_roles = clean_roles(user_roles)

    if str(ROLE_GESCHAEFTSLEITUNG).strip() in clean_user_roles or str(ROLE_GESCHAEFTSFUEHRUNG_ID).strip() in clean_user_roles: return "Geschäftsleitung"
    if str(ROLE_PROJEKTLEITUNG).strip() in clean_user_roles or str(ROLE_PROJEKTLEITUNG_ID).strip() in clean_user_roles: return "Projektleitung"
    if str(ROLE_STELLVERTRETENDE_PROJEKTLEITUNG).strip() in clean_user_roles or str(ROLE_STELLVERTRETENDE_PROJEKTLEITUNG_ID).strip() in clean_user_roles: return "Stellvertretende Projektleitung"
    if str(ROLE_DISPOSITION).strip() in clean_user_roles or str(ROLE_DISPOSITION_ID).strip() in clean_user_roles or "Disposition" in clean_user_roles or "Disponent" in clean_user_roles: return "Disposition"
    if str(ROLE_PERSONALMANAGEMENT).strip() in clean_user_roles or str(ROLE_PERSONALABTEILUNG_ID).strip() in clean_user_roles: return "Personalmanagement"
    if str(ROLE_HR_CONTROLLING).strip() in clean_user_roles or str(ROLE_HR_CONTROLLING_ID).strip() in clean_user_roles: return "HR-Controlling"
    if "HR-Controlling" in clean_user_roles or "HR Controlling" in clean_user_roles: return "HR-Controlling"
    if str(ROLE_BUCHHALTUNG).strip() in clean_user_roles or str(ROLE_BUCHHALTUNG_ID).strip() in clean_user_roles: return "Buchhaltung"
    if str(ROLE_FUHRPARKMANAGEMENT).strip() in clean_user_roles or str(ROLE_FUHRPARKMANAGEMENT_ID).strip() in clean_user_roles: return "Fuhrparkmanagement"
    if str(ROLE_FAHRER).strip() in clean_user_roles or str(ROLE_FAHRER_ID).strip() in clean_user_roles: return "Fahrer"

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


# ==========================================
# PERSISTENTE ALL-TIME-KILOMETER / COMPANY STATS
# ==========================================

COMPANY_STATS_DOCUMENT_ID = "company_all_time"


def positive_number(value, fallback=0.0):
    number = parse_number(value, fallback)
    if number < 0:
        return 0.0
    return number


def first_number_from_dict(source, *keys, fallback=0.0):
    source = source or {}
    for key in keys:
        if key in source and source.get(key) is not None:
            value = parse_number(source.get(key), fallback)
            if value > 0:
                return value
    return fallback


def get_user_all_time_km(user_doc):
    user_doc = user_doc or {}
    return positive_number(
        user_doc.get("tracker_all_time_km")
        or user_doc.get("profile_all_time_km")
        or user_doc.get("all_time_km")
        or user_doc.get("profile_km"),
        0.0
    )


def get_user_all_time_income(user_doc):
    user_doc = user_doc or {}
    return positive_number(
        user_doc.get("tracker_all_time_income")
        or user_doc.get("profile_all_time_income")
        or user_doc.get("all_time_income")
        or user_doc.get("profile_income")
        or user_doc.get("profile_revenue"),
        0.0
    )


def get_receipt_distance_km(receipt_doc):
    receipt_doc = receipt_doc or {}
    tour = receipt_doc.get("tour") or {}

    return positive_number(
        tour.get("driven_distance_km")
        or receipt_doc.get("completedDistanceKm")
        or receipt_doc.get("completed_distance_km")
        or receipt_doc.get("drivenDistanceKm")
        or receipt_doc.get("distanceKm")
        or receipt_doc.get("distance_km"),
        0.0
    )


def get_receipt_income(receipt_doc):
    receipt_doc = receipt_doc or {}
    billing = receipt_doc.get("billing") or {}

    return positive_number(
        billing.get("total_amount")
        or receipt_doc.get("income")
        or receipt_doc.get("revenue")
        or receipt_doc.get("money"),
        0.0
    )


def receipt_counts_as_completed(receipt_doc):
    receipt_doc = receipt_doc or {}
    status = safe_str(receipt_doc.get("status")).lower()

    return (
        receipt_doc.get("completed") is True
        or receipt_doc.get("submitted") is True
        or receipt_doc.get("billing_relevant") is True
        or status in {"submitted", "completed", "complete", "delivered", "done", "fertig"}
    )


def build_company_stats_doc_from_receipts():
    all_time_km = 0.0
    all_time_income = 0.0
    jobs_all_time = 0
    deliveries_all_time = 0
    latest_receipt_at = None

    query = {"archived": {"$ne": True}}
    for receipt_doc in tour_receipts_collection.find(query):
        if not receipt_counts_as_completed(receipt_doc):
            continue

        distance = get_receipt_distance_km(receipt_doc)
        income = get_receipt_income(receipt_doc)

        all_time_km += distance
        all_time_income += income
        jobs_all_time += 1
        deliveries_all_time += 1

        submitted_at = receipt_doc.get("submitted_at") or receipt_doc.get("created_at")
        if isinstance(submitted_at, datetime) and (latest_receipt_at is None or submitted_at > latest_receipt_at):
            latest_receipt_at = submitted_at

    now = now_utc()
    all_time_km = round(all_time_km, 1)
    all_time_income = round(all_time_income, 2)

    return {
        "_id": COMPANY_STATS_DOCUMENT_ID,
        "kind": "global",
        "all_time_km": all_time_km,
        "allTimeKilometers": all_time_km,
        "all_time_income": all_time_income,
        "companyIncome": all_time_income,
        "jobs_all_time": jobs_all_time,
        "deliveries_all_time": deliveries_all_time,
        "latest_receipt_at": latest_receipt_at,
        "updated_at": now,
        "source": "tour_receipts",
        "all_time_initialized": True
    }


def refresh_company_all_time_stats_from_receipts():
    stats_doc = build_company_stats_doc_from_receipts()
    company_stats_collection.replace_one(
        {"_id": COMPANY_STATS_DOCUMENT_ID},
        stats_doc,
        upsert=True
    )
    return stats_doc


def get_company_all_time_stats():
    stats_doc = company_stats_collection.find_one({"_id": COMPANY_STATS_DOCUMENT_ID})

    if not stats_doc or not stats_doc.get("all_time_initialized"):
        stats_doc = refresh_company_all_time_stats_from_receipts()

    return stats_doc or {
        "all_time_km": 0.0,
        "all_time_income": 0.0,
        "jobs_all_time": 0,
        "deliveries_all_time": 0
    }


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
    user_doc = user_doc or {}

    # Wichtig: "km" ist der persistente All-Time-Wert aus MongoDB.
    # Live-/Last-Trip-Werte werden hier bewusst nicht genutzt, damit die Statistik
    # nicht bei einem neuen Auftrag von vorne beginnt.
    km_value = (
        user_doc.get("profile_all_time_km")
        if user_doc.get("profile_all_time_km") not in [None, ""]
        else user_doc.get("tracker_all_time_km")
    )
    if km_value in [None, ""]:
        km_value = user_doc.get("all_time_km")
    if km_value in [None, ""]:
        km_value = user_doc.get("profile_km", "0")

    income_value = (
        user_doc.get("profile_all_time_income")
        if user_doc.get("profile_all_time_income") not in [None, ""]
        else user_doc.get("tracker_all_time_income")
    )
    if income_value in [None, ""]:
        income_value = user_doc.get("profile_income", user_doc.get("profile_revenue", "0"))

    deliveries_value = (
        user_doc.get("profile_all_time_deliveries")
        if user_doc.get("profile_all_time_deliveries") not in [None, ""]
        else user_doc.get("tracker_all_time_deliveries")
    )
    if deliveries_value in [None, ""]:
        deliveries_value = user_doc.get("profile_deliveries", "0")

    jobs_value = (
        user_doc.get("profile_all_time_jobs")
        if user_doc.get("profile_all_time_jobs") not in [None, ""]
        else user_doc.get("tracker_all_time_jobs")
    )
    if jobs_value in [None, ""]:
        jobs_value = user_doc.get("profile_jobs", deliveries_value)

    return {
        "km": km_value,
        "all_time_km": km_value,
        "allTimeKilometers": km_value,
        "deliveries": deliveries_value,
        "jobs": jobs_value,
        "convoys": user_doc.get("profile_convoys", "0"),
        "rating": user_doc.get("profile_rating", "0.0"),
        "income": income_value,
        "revenue": user_doc.get("profile_revenue", income_value)
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
        "document_id": document.get("document_id") or "",
        "request_id": document.get("request_id") or document.get("fahrerkarte_request_id") or "",
        "title": document.get("title") or "System Dokument",
        "sender": document.get("sender") or "System",
        "date": document.get("date") or format_datetime_for_template(document.get("created_at")) or "Heute",
        "content": document.get("content") or "",
        "description": document.get("description") or "",
        "needs_signature": bool(document.get("needs_signature", False)),
        "type": document.get("type") or "system",
        "is_alert": document.get("is_alert", False),
        "download_url": document.get("download_url") or "",
        "download_label": document.get("download_label") or "Download",
        "download_filename": document.get("download_filename") or document.get("file_name") or "",
        "file_type": document.get("file_type") or "",
        "file_path": document.get("file_path") or document.get("pdf_relative_path") or "",
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


# ==========================================
# SERVICECENTER / PERSONALISIERTE FAHRERKARTE
# ==========================================

def get_latest_fahrerkarte_request_for_user(discord_id):
    discord_id = safe_str(discord_id)
    if not discord_id:
        return None

    user_doc = users_collection.find_one({"discord_id": discord_id})
    if user_doc:
        sync_fahrerkarte_request_from_user_doc(user_doc)

    return fahrerkarte_requests_collection.find_one(
        {"discord_id": discord_id, "archived": {"$ne": True}},
        sort=[("created_at", DESCENDING)]
    )


def generate_fahrerkarte_card_id(discord_id, request_id=""):
    discord_id = safe_str(discord_id, "user")
    request_id = safe_str(request_id)
    raw = f"{discord_id}|{request_id}|{now_utc().isoformat()}|{secrets.token_hex(4)}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8].upper()
    return f"EL-FK-{now_utc().strftime('%Y%m%d')}-{digest}"


def normalize_fahrerkarte_status(status):
    status = safe_str(status, "none").lower()
    if status == "open":
        return "pending"
    if status in {"none", "pending", "claimed", "approved", "issued", "rejected", "postponed", "archived"}:
        return status
    return "none"


FAHRERKARTE_ACTIVE_STATUSES = {"pending", "claimed", "approved", "issued", "rejected", "postponed"}


def coerce_fahrerkarte_datetime(value, fallback=None):
    if isinstance(value, datetime):
        return value
    value = safe_str(value)
    if not value:
        return fallback
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return fallback


def user_doc_has_fahrerkarte_request(user_doc):
    user_doc = user_doc or {}
    if safe_str(user_doc.get("fahrerkarte_request_id") or user_doc.get("personalisierte_fahrerkarte_request_id")):
        return True
    status = normalize_fahrerkarte_status(
        user_doc.get("personalisierte_fahrerkarte_status")
        or user_doc.get("fahrerkarte_status")
    )
    return status in FAHRERKARTE_ACTIVE_STATUSES


def build_fahrerkarte_request_from_user_doc(user_doc):
    user_doc = user_doc or {}
    if not user_doc_has_fahrerkarte_request(user_doc):
        return None

    now = now_utc()
    user_mongo_id = safe_str(user_doc.get("_id"))
    discord_id = safe_str(user_doc.get("discord_id") or user_doc.get("user_id") or user_doc.get("id"))
    if not discord_id:
        return None

    request_id = safe_str(
        user_doc.get("fahrerkarte_request_id")
        or user_doc.get("personalisierte_fahrerkarte_request_id")
    )
    if not request_id:
        request_id = uuid.uuid4().hex

    status = normalize_fahrerkarte_status(
        user_doc.get("personalisierte_fahrerkarte_status")
        or user_doc.get("fahrerkarte_status")
        or "pending"
    )

    created_at = coerce_fahrerkarte_datetime(
        user_doc.get("fahrerkarte_requested_at")
        or user_doc.get("personalisierte_fahrerkarte_requested_at")
        or user_doc.get("created_at"),
        fallback=now,
    )
    updated_at = coerce_fahrerkarte_datetime(
        user_doc.get("fahrerkarte_updated_at")
        or user_doc.get("updated_at"),
        fallback=now,
    )

    display_name = safe_str(
        user_doc.get("fahrerkarte_name")
        or user_doc.get("display_name")
        or user_doc.get("username")
        or user_doc.get("discord_username"),
        "EifelLog Fahrer",
    )
    role_name = safe_str(
        user_doc.get("fahrerkarte_role")
        or user_doc.get("role_name")
        or user_doc.get("rank")
        or get_primary_role_name(user_doc.get("roles", [])),
        "Fahrer",
    )

    request_doc = {
        "request_id": request_id,
        "discord_id": discord_id,
        "user_id": discord_id,
        "username": user_doc.get("username") or user_doc.get("discord_username"),
        "discord_username": user_doc.get("discord_username") or user_doc.get("username"),
        "avatar_url": make_external_url(get_discord_avatar_url(user_doc)),
        "name": display_name,
        "full_name": display_name,
        "display_name": display_name,
        "role": role_name,
        "role_name": role_name,
        "system_id": discord_id,
        "driver_number": user_doc.get("driver_number") or user_doc.get("fahrernummer") or "",
        "priority": safe_str(user_doc.get("fahrerkarte_priority"), "normal"),
        "reason": safe_str(user_doc.get("fahrerkarte_reason"), "new_issue"),
        "delivery_method": safe_str(user_doc.get("fahrerkarte_delivery_method"), "servicecenter"),
        "notes": safe_str(user_doc.get("fahrerkarte_note") or user_doc.get("fahrerkarte_notes"), ""),
        "status": status,
        "created_at": created_at,
        "requested_at": created_at,
        "updated_at": updated_at,
        "source": "users_fahrerkarte_sync",
        "source_collection": "users",
        "source_user_mongo_id": user_mongo_id,
        "user_mongo_id": user_mongo_id,
        "verified_user_mongo_id": user_mongo_id,
        "card_id": safe_str(user_doc.get("fahrerkarte_card_id") or user_doc.get("card_id")),
        "handler_name": safe_str(user_doc.get("fahrerkarte_handler"), "Noch nicht zugewiesen"),
        "tracker_upload_ready": bool(user_doc.get("tracker_upload_ready") or status == "issued"),
    }

    optional_map = {
        "approved_at": "fahrerkarte_approved_at",
        "issued_at": "fahrerkarte_issued_at",
        "rejected_at": "fahrerkarte_rejected_at",
        "postponed_at": "fahrerkarte_postponed_at",
        "reject_reason": "fahrerkarte_reject_reason",
        "postpone_reason": "fahrerkarte_postpone_reason",
        "issue_note": "fahrerkarte_issue_note",
        "approval_note": "fahrerkarte_approval_note",
        "pdf_relative_path": "fahrerkarte_pdf_relative_path",
        "pdf_filename": "fahrerkarte_pdf_filename",
        "download_url": "fahrerkarte_download_url",
    }
    for target_key, user_key in optional_map.items():
        value = user_doc.get(user_key)
        if target_key.endswith("_at"):
            value = coerce_fahrerkarte_datetime(value)
        if value not in (None, ""):
            request_doc[target_key] = value

    if request_doc.get("pdf_relative_path"):
        request_doc["pdf_path"] = request_doc.get("pdf_relative_path")

    return request_doc


def mirror_fahrerkarte_request_for_discord_plugin(request_doc, user_doc=None):
    request_doc = request_doc or {}
    request_id = safe_str(request_doc.get("request_id") or request_doc.get("_id"))
    discord_id = safe_str(request_doc.get("discord_id") or request_doc.get("user_id"))
    if not request_id or not discord_id:
        return None

    user_doc = user_doc or users_collection.find_one({"discord_id": discord_id}) or {}
    status = normalize_fahrerkarte_status(
        request_doc.get("status")
        or user_doc.get("personalisierte_fahrerkarte_status")
        or user_doc.get("fahrerkarte_status")
        or "pending"
    )
    user_mongo_id = safe_str(
        request_doc.get("source_user_mongo_id")
        or request_doc.get("user_mongo_id")
        or user_doc.get("_id")
    )
    created_at = coerce_fahrerkarte_datetime(
        request_doc.get("created_at")
        or request_doc.get("requested_at")
        or user_doc.get("fahrerkarte_requested_at"),
        fallback=now_utc(),
    )
    updated_at = coerce_fahrerkarte_datetime(
        request_doc.get("updated_at")
        or user_doc.get("fahrerkarte_updated_at"),
        fallback=now_utc(),
    )

    mirror_doc = {
        "request_id": request_id,
        "fahrerkarte_request_id": request_id,
        "discord_id": discord_id,
        "user_id": discord_id,
        "username": request_doc.get("username") or user_doc.get("username") or user_doc.get("discord_username"),
        "discord_username": request_doc.get("discord_username") or user_doc.get("discord_username") or user_doc.get("username"),
        "display_name": request_doc.get("display_name") or request_doc.get("full_name") or request_doc.get("name") or user_doc.get("display_name"),
        "name": request_doc.get("name") or request_doc.get("display_name") or user_doc.get("display_name") or user_doc.get("username"),
        "role": request_doc.get("role") or request_doc.get("role_name") or user_doc.get("fahrerkarte_role") or user_doc.get("rank"),
        "role_name": request_doc.get("role_name") or request_doc.get("role") or user_doc.get("fahrerkarte_role") or user_doc.get("rank"),
        "status": status,
        "fahrerkarte_status": status,
        "personalisierte_fahrerkarte_status": status,
        "handler_name": request_doc.get("handler_name") or user_doc.get("fahrerkarte_handler") or "Noch nicht zugewiesen",
        "fahrerkarte_handler": request_doc.get("handler_name") or user_doc.get("fahrerkarte_handler") or "Noch nicht zugewiesen",
        "requested_at": created_at,
        "fahrerkarte_requested_at": created_at,
        "created_at": created_at,
        "updated_at": updated_at,
        "source": "web_main_servicecenter_sync",
        "source_collection": "fahrerkarte_requests",
        "source_request_mongo_id": safe_str(request_doc.get("_id")),
        "source_user_mongo_id": user_mongo_id,
        "verified_user_mongo_id": user_mongo_id,
        "user_check_status": "verified" if user_mongo_id else "not_checked",
        "card_id": request_doc.get("card_id") or user_doc.get("fahrerkarte_card_id") or "",
        "fahrerkarte_card_id": request_doc.get("card_id") or user_doc.get("fahrerkarte_card_id") or "",
        "note": request_doc.get("issue_note") or request_doc.get("approval_note") or request_doc.get("notes") or request_doc.get("reject_reason") or "",
        "fahrerkarte_note": request_doc.get("issue_note") or request_doc.get("approval_note") or request_doc.get("notes") or request_doc.get("reject_reason") or "",
        "priority": request_doc.get("priority") or "normal",
        "reason": request_doc.get("reason") or "new_issue",
        "delivery_method": request_doc.get("delivery_method") or "servicecenter",
        "download_url": request_doc.get("download_url") or user_doc.get("fahrerkarte_download_url") or "",
        "pdf_relative_path": request_doc.get("pdf_relative_path") or user_doc.get("fahrerkarte_pdf_relative_path") or "",
        "pdf_filename": request_doc.get("pdf_filename") or user_doc.get("fahrerkarte_pdf_filename") or "",
    }

    if request_doc.get("issued_at") or user_doc.get("fahrerkarte_issued_at"):
        mirror_doc["issued_at"] = coerce_fahrerkarte_datetime(request_doc.get("issued_at") or user_doc.get("fahrerkarte_issued_at"))
        mirror_doc["fahrerkarte_issued_at"] = mirror_doc["issued_at"]

    if request_doc.get("discord_thread_id") or request_doc.get("thread_id"):
        mirror_doc["thread_id"] = safe_str(request_doc.get("discord_thread_id") or request_doc.get("thread_id"))
    if request_doc.get("discord_parent_channel_id"):
        mirror_doc["thread_parent_channel_id"] = safe_str(request_doc.get("discord_parent_channel_id"))
    if request_doc.get("discord_parent_message_id"):
        mirror_doc["thread_parent_message_id"] = safe_str(request_doc.get("discord_parent_message_id"))
    if request_doc.get("discord_admin_message_id"):
        mirror_doc["admin_message_id"] = safe_str(request_doc.get("discord_admin_message_id"))
    if request_doc.get("discord_history_message_id"):
        mirror_doc["history_message_id"] = safe_str(request_doc.get("discord_history_message_id"))

    lookup_items = [{"request_id": request_id}, {"fahrerkarte_request_id": request_id}]
    if user_mongo_id:
        lookup_items.append({"source_user_mongo_id": user_mongo_id})
    if ObjectId.is_valid(request_id):
        lookup_items.append({"_id": ObjectId(request_id)})

    # MongoDB erlaubt denselben Feldpfad nicht gleichzeitig in $set und $setOnInsert.
    # created_at wird bereits ueber mirror_doc gesetzt und ist dadurch auch bei Upserts vorhanden.
    fahrerkarte_beantragungen_collection.update_one(
        {"$or": lookup_items},
        {
            "$set": mirror_doc,
            "$setOnInsert": {
                "imported_at": now_utc(),
            },
        },
        upsert=True,
    )
    return fahrerkarte_beantragungen_collection.find_one({"request_id": request_id})


def sync_fahrerkarte_request_from_user_doc(user_doc, force=False):
    request_doc = build_fahrerkarte_request_from_user_doc(user_doc)
    if not request_doc:
        return None

    request_id = safe_str(request_doc.get("request_id"))
    user_mongo_id = safe_str(request_doc.get("source_user_mongo_id"))
    lookup_items = [{"request_id": request_id}]
    if user_mongo_id:
        lookup_items.append({"source_user_mongo_id": user_mongo_id})
        lookup_items.append({"user_mongo_id": user_mongo_id})
    existing = fahrerkarte_requests_collection.find_one({"$or": lookup_items})

    set_fields = dict(request_doc)
    if existing and not force:
        # Nicht leere, im ServiceCenter erzeugte Felder behalten.
        for key in [
            "discord_thread_id", "thread_id", "discord_channel_id", "discord_parent_channel_id",
            "discord_parent_message_id", "discord_message_id", "discord_admin_message_id",
            "discord_history_message_id", "discord_message_url", "discord_thread_url",
            "pdf_path", "pdf_relative_path", "pdf_filename", "download_url",
            "card_id", "claimed_by", "approved_by", "issued_by", "rejected_by", "postponed_by",
            "claimed_at", "approved_at", "issued_at", "rejected_at", "postponed_at",
        ]:
            if existing.get(key) not in (None, "") and set_fields.get(key) in (None, ""):
                set_fields[key] = existing.get(key)

    if existing:
        fahrerkarte_requests_collection.update_one(
            {"_id": existing["_id"]},
            {"$set": set_fields}
        )
        fresh_request = fahrerkarte_requests_collection.find_one({"_id": existing["_id"]})
    else:
        insert_result = fahrerkarte_requests_collection.insert_one(set_fields)
        fresh_request = fahrerkarte_requests_collection.find_one({"_id": insert_result.inserted_id})

    mirror_fahrerkarte_request_for_discord_plugin(fresh_request, user_doc=user_doc)

    # Falls die User-Collection nur den Status hatte, die erzeugte Request-ID sauber zurückschreiben.
    if user_doc and request_id and safe_str(user_doc.get("fahrerkarte_request_id")) != request_id:
        users_collection.update_one(
            {"_id": user_doc["_id"]},
            {"$set": {
                "fahrerkarte_request_id": request_id,
                "personalisierte_fahrerkarte_status": fresh_request.get("status", "pending"),
                "fahrerkarte_status": fresh_request.get("status", "pending"),
                "fahrerkarte_updated_at": now_utc(),
            }}
        )

    return fresh_request


def sync_fahrerkarte_requests_from_users(limit=500):
    query = {
        "$or": [
            {"fahrerkarte_request_id": {"$exists": True, "$nin": ["", None]}},
            {"personalisierte_fahrerkarte_status": {"$in": list(FAHRERKARTE_ACTIVE_STATUSES)}},
            {"fahrerkarte_status": {"$in": list(FAHRERKARTE_ACTIVE_STATUSES)}},
        ]
    }
    checked = 0
    imported = 0
    updated = 0
    failed = 0

    cursor = users_collection.find(query).sort([("updated_at", DESCENDING), ("created_at", DESCENDING)]).limit(int(limit or 500))
    for user_doc in cursor:
        checked += 1
        before = None
        request_id = safe_str(user_doc.get("fahrerkarte_request_id") or user_doc.get("personalisierte_fahrerkarte_request_id"))
        if request_id:
            before = fahrerkarte_requests_collection.find_one({"request_id": request_id})
        try:
            synced = sync_fahrerkarte_request_from_user_doc(user_doc)
            if synced:
                if before:
                    updated += 1
                else:
                    imported += 1
        except Exception as error:
            failed += 1
            print(f"Fahrerkarte-User-Sync fehlgeschlagen fuer User {user_doc.get('_id')}: {error}")

    return {"checked": checked, "imported": imported, "updated": updated, "failed": failed}


def prepare_fahrerkarte_context(user_doc, latest_request=None):
    user_doc = user_doc or {}
    discord_id = safe_str(user_doc.get("discord_id"))
    latest_request = latest_request or get_latest_fahrerkarte_request_for_user(discord_id)

    status = normalize_fahrerkarte_status(user_doc.get("personalisierte_fahrerkarte_status") or user_doc.get("fahrerkarte_status"))
    if latest_request and latest_request.get("status"):
        status = normalize_fahrerkarte_status(latest_request.get("status"))

    name = (
        user_doc.get("display_name")
        or user_doc.get("username")
        or user_doc.get("discord_username")
        or ""
    )
    role = get_primary_role_name(user_doc.get("roles", []))
    handler = "Noch nicht zugewiesen"
    requested_at = "-"
    issued_at = "-"
    note = ""
    card_id = safe_str(user_doc.get("fahrerkarte_card_id"), "Wird nach Ausstellung erzeugt")
    pdf_download_url = ""
    pdf_filename = ""

    if latest_request:
        name = latest_request.get("display_name") or latest_request.get("full_name") or latest_request.get("name") or name
        role = latest_request.get("role") or latest_request.get("role_name") or role
        requested_at = format_datetime_for_template(latest_request.get("created_at")) or "-"
        issued_at = format_datetime_for_template(latest_request.get("issued_at")) or "-"
        note = latest_request.get("note") or latest_request.get("notes") or latest_request.get("reject_reason") or ""
        card_id = latest_request.get("card_id") or card_id
        if latest_request.get("pdf_relative_path") or latest_request.get("pdf_path"):
            pdf_download_url = f"/servicecenter/fahrerkarte/download/{latest_request.get('request_id') or latest_request.get('_id')}"
            pdf_filename = latest_request.get("pdf_filename") or latest_request.get("file_name") or "Fahrerkarte.pdf"

        claimed_by = latest_request.get("claimed_by") or {}
        approved_by = latest_request.get("approved_by") or {}
        issued_by = latest_request.get("issued_by") or {}
        rejected_by = latest_request.get("rejected_by") or {}
        handler = (
            issued_by.get("display_name")
            or approved_by.get("display_name")
            or rejected_by.get("display_name")
            or claimed_by.get("display_name")
            or latest_request.get("handler_name")
            or handler
        )

    if not card_id:
        card_id = "Wird nach Ausstellung erzeugt"

    return {
        "personalisierte_fahrerkarte_status": status,
        "fahrerkarte_name": name,
        "fahrerkarte_role": role,
        "fahrerkarte_handler": handler,
        "fahrerkarte_requested_at": requested_at,
        "fahrerkarte_issued_at": issued_at,
        "fahrerkarte_card_id": card_id,
        "fahrerkarte_note": note,
        "fahrerkarte_pdf_download_url": pdf_download_url,
        "fahrerkarte_pdf_filename": pdf_filename,
    }


def get_servicecenter_messages_for_user(discord_id, limit=12):
    discord_id = safe_str(discord_id)
    if not discord_id:
        return []

    documents = system_documents_collection.find(
        {
            "discord_id": discord_id,
            "archived": {"$ne": True},
            "hidden": {"$ne": True},
            "$or": [
                {"type": {"$in": ["driver_card_application", "driver_card_approval", "driver_card_issued", "driver_card_rejection", "driver_card_postponed", "driver_card_pdf"]}},
                {"title": {"$regex": "fahrerkarte|servicecenter", "$options": "i"}},
            ],
        },
        {"_id": 0}
    ).sort("created_at", DESCENDING).limit(limit)

    return [prepare_system_document_for_dashboard(document) for document in documents]


def fahrerkarte_application_document_content(name, role, request_id, priority, reason, delivery_method, notes=""):
    reason_label = {
        "new_issue": "Erstausstellung",
        "update": "Datenänderung / Aktualisierung",
        "replacement": "Ersatzkarte",
        "role_change": "Rollenwechsel",
    }.get(safe_str(reason), safe_str(reason, "Nicht angegeben"))

    priority_label = {
        "normal": "Normal - reguläre Bearbeitung",
        "high": "Hoch - Einsatz / Tour steht bevor",
        "low": "Niedrig - keine Eile",
    }.get(safe_str(priority), safe_str(priority, "Normal"))

    delivery_label = {
        "servicecenter": "ServiceCenter / Postfach",
        "profile": "Im Profil hinterlegen",
        "manual": "Manuelle Übergabe durch Personalabteilung",
    }.get(safe_str(delivery_method), safe_str(delivery_method, "ServiceCenter"))

    notes = safe_str(notes, "Keine Hinweise angegeben.")

    return f"""
        <p><strong>Beantragung personalisierte Fahrerkarte</strong></p>
        <p class="mt-4">
            Deine Beantragung wurde im EifelLog ServiceCenter eingereicht und wartet auf Prüfung.
        </p>
        <div class="mt-5 rounded-2xl bg-black/50 border border-[var(--brand-green)]/25 p-4">
            <p class="text-[10px] font-orbitron text-[var(--brand-green)] uppercase tracking-widest mb-2">Antragsdaten</p>
            <p><strong>Name:</strong> {name}</p>
            <p><strong>Rolle:</strong> {role}</p>
            <p><strong>Antrags-ID:</strong> {request_id}</p>
            <p><strong>Priorität:</strong> {priority_label}</p>
            <p><strong>Antragsgrund:</strong> {reason_label}</p>
            <p><strong>Bereitstellung:</strong> {delivery_label}</p>
        </div>
        <p class="mt-4"><strong>Hinweise:</strong><br>{notes}</p>
    """


def fahrerkarte_reason_label(reason):
    return {
        "new_issue": "Erstausstellung",
        "update": "Datenänderung / Aktualisierung",
        "replacement": "Ersatzkarte",
        "role_change": "Rollenwechsel",
    }.get(safe_str(reason), safe_str(reason, "Nicht angegeben"))


def fahrerkarte_priority_label(priority):
    return {
        "normal": "Normal",
        "high": "Hoch",
        "low": "Niedrig",
    }.get(safe_str(priority), safe_str(priority, "Normal"))


def fahrerkarte_delivery_label(delivery_method):
    return {
        "servicecenter": "ServiceCenter / Postfach",
        "profile": "Im Profil hinterlegen",
        "manual": "Manuelle Übergabe durch Personalabteilung",
    }.get(safe_str(delivery_method), safe_str(delivery_method, "ServiceCenter"))


def fahrerkarte_status_label(status):
    return {
        "pending": "Offen",
        "open": "Offen",
        "claimed": "Geclaimt",
        "approved": "Genehmigt",
        "issued": "Ausgestellt",
        "rejected": "Abgelehnt",
        "postponed": "Zurückgestellt",
        "archived": "Archiviert",
        "none": "Nicht beantragt",
    }.get(safe_str(status).lower(), safe_str(status, "Unbekannt"))


def servicecenter_fahrerkarte_download_url(request_id):
    request_id = safe_str(request_id)
    if not request_id:
        return ""
    return f"/servicecenter/fahrerkarte/download/{request_id}"


def resolve_servicecenter_fahrerkarte_folder():
    folder = SERVICECENTER_FAHRERKARTE_FOLDER
    if not os.path.isabs(folder):
        folder = os.path.join(BASE_DIR, folder)
    return folder


def resolve_fahrerkarte_pdf_path(pdf_path):
    pdf_path = safe_str(pdf_path)
    if not pdf_path:
        return ""
    if os.path.isabs(pdf_path):
        return pdf_path
    return os.path.join(BASE_DIR, pdf_path)



def resolve_local_avatar_path(source):
    source = safe_str(source)
    if not source:
        return ""

    if source.startswith("file://"):
        source = source[7:]

    if source.startswith("/static/"):
        return os.path.join(BASE_DIR, source.lstrip("/"))
    if source.startswith("static/"):
        return os.path.join(BASE_DIR, source)

    try:
        host_prefix = request.host_url.rstrip("/") if request else ""
    except Exception:
        host_prefix = ""

    if host_prefix and source.startswith(host_prefix):
        rel_path = source[len(host_prefix):].lstrip("/")
        if rel_path.startswith("static/"):
            return os.path.join(BASE_DIR, rel_path)

    if os.path.isabs(source) and os.path.exists(source):
        return source
    possible = os.path.join(BASE_DIR, source.lstrip("/"))
    if os.path.exists(possible):
        return possible
    return ""


def load_fahrerkarte_avatar_jpeg(request_doc, user_doc=None, size=180):
    """Laedt den User-Avatar und wandelt ihn als JPEG fuer das PDF-XObject um.
    Wenn kein Avatar erreichbar ist, wird im PDF ein neutraler Platzhalter verwendet.
    """
    if not PIL_AVAILABLE:
        return None

    user_doc = user_doc or {}
    sources = [
        request_doc.get("avatar_url") if request_doc else "",
        user_doc.get("avatar_url"),
        get_discord_avatar_url(user_doc) if user_doc else "",
    ]

    for source in sources:
        source = safe_str(source)
        if not source:
            continue
        raw = None
        local_path = resolve_local_avatar_path(source)
        try:
            if local_path and os.path.exists(local_path):
                with open(local_path, "rb") as image_file:
                    raw = image_file.read()
            elif source.startswith("http://") or source.startswith("https://"):
                response = requests.get(source, timeout=5)
                if response.ok and response.content:
                    raw = response.content
        except Exception as error:
            print(f"Fahrerkarte-Avatar konnte nicht geladen werden ({source}): {error}")
            raw = None

        if not raw:
            continue

        try:
            image = Image.open(BytesIO(raw))
            image = ImageOps.exif_transpose(image).convert("RGB")
            image = ImageOps.fit(image, (int(size), int(size)), method=Image.LANCZOS, centering=(0.5, 0.5))
            output = BytesIO()
            image.save(output, format="JPEG", quality=88, optimize=True)
            return {"name": "Avatar1", "width": int(size), "height": int(size), "data": output.getvalue()}
        except Exception as error:
            print(f"Fahrerkarte-Avatar konnte nicht verarbeitet werden ({source}): {error}")
    return None


def pdf_stream_image(stream, image_name, x, y, width, height):
    image_name = safe_str(image_name)
    if not image_name:
        return
    stream.extend(
        f"q\n{float(width):.2f} 0 0 {float(height):.2f} {float(x):.2f} {float(y):.2f} cm\n/{image_name} Do\nQ\n".encode("ascii")
    )


def normalize_signature_value(value):
    return re.sub(r"[^a-z0-9]+", "", safe_str(value).lower())


def create_fahrerkarte_signature_payload(request_doc, actor, signature_name, signed_at=None):
    signed_at = signed_at or now_utc()
    request_id = safe_str(request_doc.get("request_id") or request_doc.get("_id"))
    discord_id = safe_str(request_doc.get("discord_id") or request_doc.get("user_id"))
    actor_id = safe_str(actor.get("discord_id") or actor.get("id") or actor.get("username"))
    payload = f"{request_id}|{discord_id}|{actor_id}|{safe_str(signature_name)}|{signed_at.isoformat()}"
    key = str(app.secret_key).encode("utf-8", errors="ignore")
    signature_hash = hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest().upper()
    return {
        "digital_signature": {
            "name": safe_str(signature_name),
            "signed_at": signed_at,
            "actor": actor,
            "hash": signature_hash,
            "method": "web_servicecenter_staff_signature",
            "valid": True,
        },
        "signature_name": safe_str(signature_name),
        "signature_hash": signature_hash,
        "signature_valid": True,
        "signature_method": "web_servicecenter_staff_signature",
        "signed_by": actor,
        "signed_at": signed_at,
    }


def validate_fahrerkarte_issue_signature(data, actor, request_doc):
    data = data or {}
    actor = actor or {}
    signature_name = safe_str(
        data.get("signature")
        or data.get("signedBy")
        or data.get("signatureName")
        or data.get("sachbearbeiterSignature")
        or data.get("digitalSignature")
    )
    confirmed = bool_from_payload(
        data.get("signatureConfirmed")
        or data.get("confirmSignature")
        or data.get("signed")
        or data.get("signature_confirmed"),
        fallback=False,
    )

    if len(signature_name) < 3:
        return False, "Digitale Signatur fehlt. Bitte den eigenen Sachbearbeiter-Namen eintragen."
    if not confirmed:
        return False, "Bitte die digitale Signatur aktiv bestätigen."

    allowed_names = {
        normalize_signature_value(actor.get("display_name")),
        normalize_signature_value(actor.get("username")),
    }
    given_name = normalize_signature_value(signature_name)
    if given_name not in {name for name in allowed_names if name}:
        return False, "Die Signatur muss exakt dem eingeloggten Sachbearbeiter entsprechen."

    return True, create_fahrerkarte_signature_payload(request_doc, actor, signature_name)


def build_eifellog_servicecenter_pdf(title, subtitle, sections, footer_text="EifelLog ServiceCenter"):
    page_width = 595
    page_height = 842
    margin_left = 42
    y_start = 792
    y_min = 62
    line_height = 15

    all_lines = []

    def add_line(text, size=10, bold=False, gap_after=0, color=(0.08, 0.10, 0.09)):
        all_lines.append({
            "text": safe_str(text),
            "size": int(size),
            "bold": bool(bold),
            "gap_after": int(gap_after or 0),
            "color": color,
        })

    add_line("EIFELLOG SERVICECENTER", size=9, bold=True, gap_after=2, color=(0.16, 0.78, 0.35))
    add_line(title, size=18, bold=True, gap_after=3, color=(1, 1, 1))
    add_line(subtitle, size=10, bold=False, gap_after=26, color=(0.78, 0.82, 0.79))
    add_line(f"Erstellt am {now_utc().strftime('%d.%m.%Y %H:%M')} UTC", size=9, bold=False, gap_after=14, color=(0.38, 0.43, 0.40))

    for section_title, rows in sections:
        add_line(section_title, size=13, bold=True, gap_after=5, color=(0.10, 0.55, 0.24))
        for label, value in rows:
            for wrapped in wrap_pdf_line(label, value, max_chars=92):
                add_line(wrapped, size=10, bold=False, gap_after=1, color=(0.07, 0.08, 0.08))
        add_line("", size=6, gap_after=8, color=(0.07, 0.08, 0.08))

    pages = []
    current = []
    current_y = y_start
    for line in all_lines:
        effective_height = line_height + int(line.get("gap_after") or 0)
        if current and current_y - effective_height < y_min:
            pages.append(current)
            current = []
            current_y = y_start
        current.append(line)
        current_y -= effective_height
    if current:
        pages.append(current)

    objects = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")

    page_object_numbers = []

    for page_index, page_lines in enumerate(pages, start=1):
        y = y_start
        stream = bytearray()
        stream.extend(b"q\n")
        stream.extend(b"0.97 0.98 0.97 rg 0 0 595 842 re f\n")
        stream.extend(b"0.03 0.05 0.04 rg 0 716 595 126 re f\n")
        stream.extend(b"0.14 0.84 0.36 rg 0 710 595 6 re f\n")
        stream.extend(b"0.90 0.94 0.91 rg 36 56 523 636 re f\n")
        stream.extend(b"0.14 0.84 0.36 RG 1.2 w 36 56 523 636 re S\n")

        for item in page_lines:
            text_value = item["text"]
            size = int(item["size"])
            font = "F2" if item["bold"] else "F1"
            r, g, b = item.get("color") or (0, 0, 0)
            stream.extend(b"BT\n")
            stream.extend(f"/{font} {size} Tf\n".encode("ascii"))
            stream.extend(f"{r:.3f} {g:.3f} {b:.3f} rg\n".encode("ascii"))
            stream.extend(f"1 0 0 1 {margin_left} {y} Tm\n".encode("ascii"))
            stream.extend(b"(" + pdf_text_bytes(text_value) + b") Tj\n")
            stream.extend(b"ET\n")
            y -= line_height + int(item.get("gap_after") or 0)

        stream.extend(b"0.03 0.05 0.04 rg 0 0 595 42 re f\n")
        stream.extend(b"BT\n/F1 8 Tf\n0.78 0.82 0.79 rg\n")
        stream.extend(f"1 0 0 1 {margin_left} 24 Tm\n".encode("ascii"))
        stream.extend(b"(" + pdf_text_bytes(f"{footer_text} / Seite {page_index} von {len(pages)}") + b") Tj\nET\n")
        stream.extend(b"Q\n")

        content_object_number = len(objects) + 1
        objects.append(f"<< /Length {len(stream)} >>\nstream\n".encode("ascii") + bytes(stream) + b"\nendstream")
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



def pdf_stream_rect(stream, x, y, width, height, fill_rgb=None, stroke_rgb=None, line_width=1):
    if fill_rgb:
        r, g, b = fill_rgb
        stream.extend(f"{r:.3f} {g:.3f} {b:.3f} rg {x:.2f} {y:.2f} {width:.2f} {height:.2f} re f\n".encode("ascii"))
    if stroke_rgb:
        r, g, b = stroke_rgb
        stream.extend(f"{r:.3f} {g:.3f} {b:.3f} RG {float(line_width):.2f} w {x:.2f} {y:.2f} {width:.2f} {height:.2f} re S\n".encode("ascii"))


def pdf_stream_line(stream, x1, y1, x2, y2, stroke_rgb=(0, 0, 0), line_width=1):
    r, g, b = stroke_rgb
    stream.extend(f"{r:.3f} {g:.3f} {b:.3f} RG {float(line_width):.2f} w {x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S\n".encode("ascii"))


def pdf_stream_text(stream, x, y, text, size=10, bold=False, color=(0, 0, 0), max_chars=None, line_gap=3):
    text = safe_str(text, "-")
    if max_chars:
        lines = []
        for raw_line in text.splitlines() or [""]:
            lines.extend(wrap_pdf_line("", raw_line, max_chars=max_chars))
    else:
        lines = text.splitlines() or [text]

    cursor_y = y
    font = "F2" if bold else "F1"
    r, g, b = color
    for line in lines:
        stream.extend(b"BT\n")
        stream.extend(f"/{font} {int(size)} Tf\n".encode("ascii"))
        stream.extend(f"{r:.3f} {g:.3f} {b:.3f} rg\n".encode("ascii"))
        stream.extend(f"1 0 0 1 {float(x):.2f} {float(cursor_y):.2f} Tm\n".encode("ascii"))
        stream.extend(b"(" + pdf_text_bytes(line) + b") Tj\n")
        stream.extend(b"ET\n")
        cursor_y -= int(size) + int(line_gap)
    return cursor_y


def build_pdf_single_page(stream, page_width=595, page_height=842, images=None):
    images = images or []
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"",  # Pages object wird gesetzt, sobald die Page-Objektnummer bekannt ist.
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
    ]

    content = bytes(stream)
    content_obj_num = len(objects) + 1
    objects.append(f"<< /Length {len(content)} >>\nstream\n".encode("ascii") + content + b"\nendstream")

    xobject_entries = []
    for index, image in enumerate(images, start=1):
        image_name = safe_str(image.get("name") or f"Im{index}")
        image_data = image.get("data") or b""
        image_width = int(image.get("width") or 1)
        image_height = int(image.get("height") or 1)
        if not image_name or not image_data:
            continue
        object_number = len(objects) + 1
        xobject_entries.append(f"/{image_name} {object_number} 0 R")
        objects.append(
            (
                f"<< /Type /XObject /Subtype /Image /Width {image_width} /Height {image_height} "
                f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length {len(image_data)} >>\nstream\n"
            ).encode("ascii") + image_data + b"\nendstream"
        )

    page_obj_num = len(objects) + 1
    xobject_resource = ""
    if xobject_entries:
        xobject_resource = " /XObject << " + " ".join(xobject_entries) + " >>"

    page_obj = (
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_width} {page_height}] "
        f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >>{xobject_resource} >> "
        f"/Contents {content_obj_num} 0 R >>"
    ).encode("ascii")
    objects.append(page_obj)
    objects[1] = f"<< /Type /Pages /Kids [{page_obj_num} 0 R] /Count 1 >>".encode("ascii")

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


def fahrerkarte_pdf_value(request_doc, user_doc, *keys, fallback="-"):
    for key in keys:
        if request_doc and request_doc.get(key):
            return request_doc.get(key)
        if user_doc and user_doc.get(key):
            return user_doc.get(key)
    return fallback


def build_personalisierte_fahrerkarte_pdf(request_doc, user_doc=None, actor=None):
    user_doc = user_doc or {}
    actor = actor or {}

    card_id = safe_str(request_doc.get("card_id")) or generate_fahrerkarte_card_id(request_doc.get("discord_id"), request_doc.get("request_id"))
    request_id = safe_str(request_doc.get("request_id") or request_doc.get("_id"))
    name = safe_str(
        request_doc.get("display_name")
        or request_doc.get("full_name")
        or request_doc.get("name")
        or user_doc.get("display_name")
        or user_doc.get("username")
        or "EifelLog Fahrer"
    )
    username = safe_str(request_doc.get("username") or user_doc.get("username") or user_doc.get("discord_username") or "-")
    role = safe_str(request_doc.get("role") or request_doc.get("role_name") or get_primary_role_name(user_doc.get("roles", [])))
    discord_id = safe_str(request_doc.get("discord_id") or user_doc.get("discord_id") or "-")
    driver_number = safe_str(request_doc.get("driver_number") or user_doc.get("driver_number") or "Nicht angegeben")
    system_id = safe_str(request_doc.get("system_id") or discord_id or "-")
    issued_at = request_doc.get("issued_at") or now_utc()
    if not isinstance(issued_at, datetime):
        issued_at = now_utc()
    valid_until = issued_at + timedelta(days=365)
    handler = (
        actor.get("display_name")
        or actor.get("username")
        or (request_doc.get("issued_by") or {}).get("display_name")
        or (request_doc.get("approved_by") or {}).get("display_name")
        or "Personalabteilung"
    )
    digital_signature = request_doc.get("digital_signature") or {}
    signature_name = safe_str(request_doc.get("signature_name") or digital_signature.get("name") or handler)
    signature_hash = safe_str(request_doc.get("signature_hash") or digital_signature.get("hash"))
    if not signature_hash:
        signature_hash = hashlib.sha256(f"{card_id}|{discord_id}|{request_id}|{signature_name}".encode("utf-8")).hexdigest().upper()
    short_signature_hash = signature_hash[:32]
    note = safe_str(request_doc.get("issue_note") or request_doc.get("approval_note") or request_doc.get("notes") or "Fahrerkarte wurde im EifelLog ServiceCenter ausgestellt.")

    avatar_image = load_fahrerkarte_avatar_jpeg(request_doc, user_doc=user_doc, size=180)
    pdf_images = [avatar_image] if avatar_image else []

    stream = bytearray()
    stream.extend(b"q\n")

    # Seite bewusst als interne ServiceCenter-Karte, nicht als amtliches Dokument.
    pdf_stream_rect(stream, 0, 0, 595, 842, fill_rgb=(0.940, 0.965, 0.980))
    pdf_stream_rect(stream, 0, 790, 595, 52, fill_rgb=(0.120, 0.250, 0.460))
    pdf_stream_text(stream, 42, 814, "EIFELLOG SERVICECENTER", size=10, bold=True, color=(1, 1, 1))
    pdf_stream_text(stream, 42, 796, "Digitale Fahrerkarte / Web-Ausstellung", size=18, bold=True, color=(1, 1, 1))
    pdf_stream_text(stream, 390, 812, f"Ausgestellt: {issued_at.strftime('%d.%m.%Y')}", size=9, bold=False, color=(0.890, 0.940, 1.000))

    # Kartenkörper nach hellblauem Fahrerkarte-Layout, klar als interne EifelLog-Karte markiert.
    card_x, card_y, card_w, card_h = 34, 493, 527, 262
    pdf_stream_rect(stream, card_x + 5, card_y - 7, card_w, card_h, fill_rgb=(0.640, 0.720, 0.780))
    pdf_stream_rect(stream, card_x, card_y, card_w, card_h, fill_rgb=(0.820, 0.910, 0.965), stroke_rgb=(0.260, 0.410, 0.620), line_width=1.5)
    pdf_stream_rect(stream, card_x, card_y + card_h - 38, card_w, 38, fill_rgb=(0.650, 0.780, 0.900))
    pdf_stream_rect(stream, card_x + 10, card_y + card_h - 34, 54, 30, fill_rgb=(0.060, 0.190, 0.510), stroke_rgb=(1, 1, 1), line_width=0.8)
    pdf_stream_text(stream, card_x + 20, card_y + card_h - 23, "EL", size=13, bold=True, color=(1, 1, 1))
    pdf_stream_text(stream, card_x + 78, card_y + card_h - 18, "FAHRERKARTE", size=17, bold=True, color=(0.090, 0.180, 0.330))
    pdf_stream_text(stream, card_x + 250, card_y + card_h - 15, "EifelLog Web-ServiceCenter", size=9, bold=True, color=(0.090, 0.180, 0.330))
    pdf_stream_text(stream, card_x + 395, card_y + card_h - 29, "KEIN AMTLICHES DOKUMENT", size=8, bold=True, color=(0.580, 0.060, 0.060))

    # Avatar des Users
    avatar_x, avatar_y, avatar_w, avatar_h = card_x + 24, card_y + 69, 108, 126
    pdf_stream_rect(stream, avatar_x - 2, avatar_y - 2, avatar_w + 4, avatar_h + 4, fill_rgb=(0.920, 0.955, 0.980), stroke_rgb=(0.260, 0.410, 0.620), line_width=0.8)
    if avatar_image:
        pdf_stream_image(stream, "Avatar1", avatar_x, avatar_y + 9, avatar_w, avatar_w)
    else:
        pdf_stream_rect(stream, avatar_x, avatar_y + 9, avatar_w, avatar_w, fill_rgb=(0.730, 0.820, 0.880), stroke_rgb=(0.260, 0.410, 0.620), line_width=0.5)
        initials = "".join([part[:1] for part in name.split()[:2]]).upper() or "EL"
        pdf_stream_text(stream, avatar_x + 31, avatar_y + 65, initials[:3], size=24, bold=True, color=(0.120, 0.250, 0.460))
    pdf_stream_text(stream, avatar_x + 14, avatar_y + 7, "USER AVATAR", size=7, bold=True, color=(0.190, 0.300, 0.430))

    # Datenfelder im Stil der Referenz, aber mit internen Feldern.
    data_x = card_x + 154
    line_y = card_y + 184
    pdf_stream_text(stream, data_x, line_y, f"1. {name[:46]}", size=15, bold=True, color=(0.050, 0.080, 0.120), max_chars=58)
    pdf_stream_text(stream, data_x, line_y - 26, f"2. {role[:50]}", size=11, bold=True, color=(0.050, 0.080, 0.120), max_chars=62)
    pdf_stream_text(stream, data_x, line_y - 49, f"3. {issued_at.strftime('%d.%m.%Y')}", size=10, bold=False, color=(0.050, 0.080, 0.120))
    pdf_stream_text(stream, data_x + 138, line_y - 49, f"4a {issued_at.strftime('%d.%m.%Y')}", size=10, bold=False, color=(0.050, 0.080, 0.120))
    pdf_stream_text(stream, data_x + 272, line_y - 49, f"4b {valid_until.strftime('%d.%m.%Y')}", size=10, bold=False, color=(0.050, 0.080, 0.120))
    pdf_stream_text(stream, data_x, line_y - 72, "4c EifelLog ServiceCenter", size=10, bold=False, color=(0.050, 0.080, 0.120), max_chars=60)
    pdf_stream_text(stream, data_x, line_y - 95, f"5a {system_id}", size=10, bold=False, color=(0.050, 0.080, 0.120), max_chars=64)
    pdf_stream_text(stream, data_x, line_y - 118, f"5b {card_id}", size=10, bold=True, color=(0.050, 0.080, 0.120), max_chars=64)
    pdf_stream_text(stream, data_x, line_y - 141, f"User: {username}  |  Fahrer-Nr.: {driver_number}", size=8, bold=False, color=(0.220, 0.310, 0.420), max_chars=76)

    # Interner Checkcode
    qr_x, qr_y, cell = card_x + card_w - 90, card_y + 55, 4
    pdf_stream_rect(stream, qr_x - 6, qr_y - 6, 68, 68, fill_rgb=(1, 1, 1), stroke_rgb=(0.260, 0.410, 0.620), line_width=0.5)
    digest = hashlib.sha256(f"{card_id}|{request_id}".encode("utf-8")).digest()
    for row in range(14):
        for col in range(14):
            byte = digest[(row * 14 + col) % len(digest)]
            should_fill = ((byte >> (col % 8)) & 1) or row in {0, 13} or col in {0, 13}
            if should_fill:
                pdf_stream_rect(stream, qr_x + col * cell, qr_y + row * cell, cell - 1, cell - 1, fill_rgb=(0.040, 0.080, 0.150))
    pdf_stream_text(stream, qr_x - 1, qr_y - 20, "CHECKCODE", size=7, bold=True, color=(0.090, 0.180, 0.330))

    # Signaturzeile auf Karte
    pdf_stream_line(stream, card_x + 155, card_y + 23, card_x + 375, card_y + 23, stroke_rgb=(0.090, 0.180, 0.330), line_width=0.6)
    pdf_stream_text(stream, card_x + 155, card_y + 9, f"Signiert: {signature_name[:36]}", size=8, bold=False, color=(0.050, 0.080, 0.120), max_chars=54)
    pdf_stream_text(stream, card_x + 405, card_y + 9, "INTERN / WEB", size=8, bold=True, color=(0.580, 0.060, 0.060))

    # Detailbereiche unterhalb der Karte
    box_y = 250
    pdf_stream_rect(stream, 48, box_y, 499, 188, fill_rgb=(1, 1, 1), stroke_rgb=(0.260, 0.410, 0.620), line_width=1)
    pdf_stream_text(stream, 66, box_y + 158, "Postfach & Download", size=13, bold=True, color=(0.090, 0.180, 0.330))
    pdf_stream_text(stream, 66, box_y + 133, f"Antrags-ID: {request_id}", size=9, bold=False, color=(0.050, 0.070, 0.090), max_chars=82)
    pdf_stream_text(stream, 66, box_y + 116, f"Karten-ID: {card_id}", size=9, bold=False, color=(0.050, 0.070, 0.090), max_chars=82)
    pdf_stream_text(stream, 66, box_y + 99, f"Status: {fahrerkarte_status_label(request_doc.get('status') or 'issued')}", size=9, bold=False, color=(0.050, 0.070, 0.090), max_chars=82)
    pdf_stream_text(stream, 66, box_y + 82, "Bereitstellung: Postfach im ServiceCenter + PDF-Download", size=9, bold=True, color=(0.090, 0.180, 0.330), max_chars=82)
    pdf_stream_text(stream, 66, box_y + 58, f"Hinweis: {note}", size=9, bold=False, color=(0.050, 0.070, 0.090), max_chars=62)

    pdf_stream_text(stream, 315, box_y + 158, "Digitale Signatur", size=13, bold=True, color=(0.090, 0.180, 0.330))
    pdf_stream_text(stream, 315, box_y + 133, f"Sachbearbeiter: {handler}", size=9, bold=False, color=(0.050, 0.070, 0.090), max_chars=42)
    pdf_stream_text(stream, 315, box_y + 116, f"Signatur: {signature_name}", size=9, bold=False, color=(0.050, 0.070, 0.090), max_chars=42)
    pdf_stream_text(stream, 315, box_y + 99, f"Zeitpunkt: {issued_at.strftime('%d.%m.%Y %H:%M')} UTC", size=9, bold=False, color=(0.050, 0.070, 0.090), max_chars=42)
    pdf_stream_text(stream, 315, box_y + 82, f"Hash: {short_signature_hash}", size=8, bold=False, color=(0.050, 0.070, 0.090), max_chars=42)
    pdf_stream_text(stream, 315, box_y + 58, "Verifikation: Web-ServiceCenter / MongoDB-Antrag", size=8, bold=True, color=(0.090, 0.180, 0.330), max_chars=42)

    pdf_stream_rect(stream, 48, 116, 499, 88, fill_rgb=(0.120, 0.250, 0.460), stroke_rgb=(0.260, 0.410, 0.620), line_width=0.9)
    pdf_stream_text(stream, 66, 175, "Interne Fahrerkarte", size=12, bold=True, color=(1, 1, 1))
    pdf_stream_text(stream, 66, 154, "Dieses Dokument ist eine interne EifelLog-ServiceCenter-Karte und ersetzt keine amtliche Fahrerkarte.", size=8, bold=False, color=(0.890, 0.940, 1.000), max_chars=92)
    verify_hash = hashlib.sha256(f"{card_id}|{discord_id}|{request_id}".encode("utf-8")).hexdigest()[:24].upper()
    pdf_stream_text(stream, 66, 136, f"Pruefhash: {verify_hash}", size=8, bold=False, color=(0.890, 0.940, 1.000), max_chars=80)
    pdf_stream_text(stream, 66, 120, "Download: ServiceCenter / Postfach / Fahrerkarte", size=8, bold=True, color=(1, 1, 1), max_chars=80)

    pdf_stream_text(stream, 42, 62, f"{TOUR_RECEIPT_COMPANY_NAME} - webbasierte Fahrerkarte-Ausstellung", size=8, bold=False, color=(0.220, 0.310, 0.420))
    pdf_stream_text(stream, 42, 48, "Bei falschen Daten bitte die Personalabteilung kontaktieren.", size=8, bold=False, color=(0.220, 0.310, 0.420))
    stream.extend(b"Q\n")
    return build_pdf_single_page(stream, images=pdf_images)


def build_fahrerkarte_pdf_sections(request_doc, user_doc=None, actor=None):
    user_doc = user_doc or {}
    actor = actor or {}
    created_at = request_doc.get("created_at")
    issued_at = request_doc.get("issued_at") or now_utc()
    approved_at = request_doc.get("approved_at")

    sections = []
    sections.append(("Dokument", [
        ("Dokumenttyp", "Personalisierte Fahrerkarte"),
        ("Antrags-ID", request_doc.get("request_id") or str(request_doc.get("_id"))),
        ("Karten-ID", request_doc.get("card_id") or "Wird erzeugt"),
        ("Status", fahrerkarte_status_label(request_doc.get("status") or "issued")),
        ("Beantragt am", format_datetime_for_template(created_at) or "-"),
        ("Genehmigt am", format_datetime_for_template(approved_at) or "-"),
        ("Ausgestellt am", format_datetime_for_template(issued_at) or now_utc().strftime("%d.%m.%Y %H:%M")),
    ]))

    sections.append(("Fahrer", [
        ("Name", request_doc.get("display_name") or request_doc.get("full_name") or request_doc.get("name") or user_doc.get("display_name") or "EifelLog Fahrer"),
        ("Username", request_doc.get("username") or user_doc.get("username") or "-"),
        ("Discord-ID", request_doc.get("discord_id") or user_doc.get("discord_id") or "-"),
        ("Rolle", request_doc.get("role") or request_doc.get("role_name") or get_primary_role_name(user_doc.get("roles", []))),
        ("System-ID", request_doc.get("system_id") or request_doc.get("discord_id") or "-"),
        ("Fahrernummer", request_doc.get("driver_number") or "Nicht angegeben"),
    ]))

    sections.append(("Beantragung", [
        ("Priorität", fahrerkarte_priority_label(request_doc.get("priority"))),
        ("Antragsgrund", fahrerkarte_reason_label(request_doc.get("reason"))),
        ("Bereitstellung", fahrerkarte_delivery_label(request_doc.get("delivery_method"))),
        ("Hinweise", request_doc.get("notes") or "Keine Hinweise angegeben."),
    ]))

    handler = actor.get("display_name") or actor.get("username")
    if not handler:
        issued_by = request_doc.get("issued_by") or {}
        approved_by = request_doc.get("approved_by") or {}
        handler = issued_by.get("display_name") or approved_by.get("display_name") or "Personalabteilung"

    sections.append(("Personalabteilung", [
        ("Sachbearbeiter", handler),
        ("Ausstellungsvermerk", request_doc.get("issue_note") or request_doc.get("approval_note") or "Fahrerkarte wurde im EifelLog ServiceCenter ausgestellt."),
        ("Tracker Upload", "Dieses PDF ist für den späteren Upload im Tracker vorgesehen."),
    ]))
    return sections


def save_fahrerkarte_pdf(request_doc, user_doc=None, actor=None, force=False):
    if not request_doc:
        raise ValueError("Fahrerkarte-Antrag fehlt.")

    existing_path = safe_str(request_doc.get("pdf_path") or request_doc.get("pdf_relative_path"))
    if existing_path and not force:
        resolved = resolve_fahrerkarte_pdf_path(existing_path)
        if os.path.exists(resolved):
            return resolved, safe_str(request_doc.get("pdf_relative_path") or existing_path), safe_str(request_doc.get("pdf_filename") or os.path.basename(resolved)), b""

    issue_time = request_doc.get("issued_at") or now_utc()
    if not isinstance(issue_time, datetime):
        issue_time = now_utc()

    month_folder = issue_time.strftime("%Y-%m")
    target_folder = os.path.join(resolve_servicecenter_fahrerkarte_folder(), month_folder)
    os.makedirs(target_folder, exist_ok=True)

    request_id = safe_str(request_doc.get("request_id") or request_doc.get("_id"), uuid.uuid4().hex)
    card_id = safe_str(request_doc.get("card_id")) or generate_fahrerkarte_card_id(request_doc.get("discord_id"), request_id)
    driver_name = request_doc.get("display_name") or request_doc.get("full_name") or request_doc.get("name") or "fahrer"
    safe_driver = re.sub(r"[^A-Za-z0-9_.-]+", "_", safe_str(driver_name, "fahrer"))[:60].strip("_") or "fahrer"
    safe_card_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", card_id)[:80]
    filename = f"EifelLog_ServiceCenter_Fahrerkarte_{safe_card_id}_{safe_driver}_{request_id[:8]}.pdf"
    file_path = os.path.join(target_folder, filename)

    pdf_doc = dict(request_doc)
    pdf_doc["card_id"] = card_id
    pdf_doc["issued_at"] = issue_time
    pdf_doc["status"] = "issued"

    # Das Fahrerkarte-PDF wird komplett in main.py generiert.
    # Kein Template und keine externe PDF-Bibliothek nötig.
    pdf_bytes = build_personalisierte_fahrerkarte_pdf(pdf_doc, user_doc=user_doc, actor=actor)

    with open(file_path, "wb") as file:
        file.write(pdf_bytes)

    try:
        relative_path = os.path.relpath(file_path, BASE_DIR).replace(os.sep, "/")
    except Exception:
        relative_path = file_path

    return file_path, relative_path, filename, pdf_bytes


def fahrerkarte_pdf_document_content(request_doc, download_url, description=""):
    request_id = safe_str(request_doc.get("request_id") or request_doc.get("_id"))
    card_id = safe_str(request_doc.get("card_id"), "Wird erzeugt")
    name = request_doc.get("display_name") or request_doc.get("full_name") or request_doc.get("name") or "EifelLog Fahrer"
    username = request_doc.get("username") or request_doc.get("discord_username") or "-"
    role = request_doc.get("role") or request_doc.get("role_name") or "Fahrer"
    issued_at = format_datetime_for_template(request_doc.get("issued_at")) or now_utc().strftime("%d.%m.%Y %H:%M")
    description = safe_str(description, "Deine personalisierte Fahrerkarte wurde als PDF im EifelLog ServiceCenter bereitgestellt.")
    return f"""
        <p><strong>Personalisierte Fahrerkarte ausgestellt</strong></p>
        <p class="mt-4">{description}</p>

        <div class="mt-5 rounded-3xl bg-gradient-to-br from-black via-[#07120b] to-black border border-[var(--brand-green)]/40 p-5 shadow-2xl">
            <div class="flex items-start justify-between gap-4">
                <div>
                    <p class="text-[10px] font-orbitron text-[var(--brand-green)] uppercase tracking-[0.25em]">EifelLog Fahrerkarte</p>
                    <h3 class="mt-2 text-xl font-orbitron font-black text-white">{name}</h3>
                    <p class="mt-1 text-sm text-gray-300">{role}</p>
                </div>
                <div class="rounded-xl border border-[var(--brand-green)]/50 px-3 py-2 text-right">
                    <p class="text-[9px] uppercase tracking-widest text-gray-400">Status</p>
                    <p class="font-orbitron font-bold text-[var(--brand-green)]">AKTIV</p>
                </div>
            </div>

            <div class="mt-5 grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
                <p><span class="text-gray-400">Karten-ID:</span><br><strong class="text-white break-all">{card_id}</strong></p>
                <p><span class="text-gray-400">Username:</span><br><strong class="text-white">{username}</strong></p>
                <p><span class="text-gray-400">Antrags-ID:</span><br><strong class="text-white break-all">{request_id}</strong></p>
                <p><span class="text-gray-400">Ausgestellt am:</span><br><strong class="text-white">{issued_at}</strong></p>
            </div>

            <p class="mt-5 text-xs text-gray-400">
                Das PDF wurde automatisch generiert und ist als Download für Dashboard, ServiceCenter und späteren Tracker-Upload bereit.
            </p>

            <a href="{download_url}" class="inline-flex items-center justify-center mt-5 px-5 py-3 rounded-xl bg-[var(--brand-green)] text-black font-orbitron font-bold uppercase tracking-widest hover:opacity-90" download>
                PDF herunterladen
            </a>
        </div>
    """

def create_fahrerkarte_pdf_dashboard_document(request_doc, actor=None, description=""):
    discord_id = safe_str(request_doc.get("discord_id") or request_doc.get("user_id"))
    request_id = safe_str(request_doc.get("request_id") or request_doc.get("_id"))
    if not discord_id or not request_id:
        return None

    actor = actor or current_staff_identity()
    handler_name = actor.get("display_name") or actor.get("username") or "EifelLog ServiceCenter"
    download_url = servicecenter_fahrerkarte_download_url(request_id)
    pdf_filename = request_doc.get("pdf_filename") or request_doc.get("file_name") or "EifelLog_Fahrerkarte.pdf"
    document_description = safe_str(description, "Deine personalisierte Fahrerkarte wurde als PDF ausgestellt und ist bereit für den Tracker-Upload.")

    return create_system_document_for_user(
        discord_id,
        "Personalisierte Fahrerkarte PDF",
        handler_name,
        fahrerkarte_pdf_document_content(request_doc, download_url, document_description),
        doc_type="driver_card_pdf",
        needs_signature=False,
        extra={
            "important": True,
            "request_id": request_id,
            "fahrerkarte_request_id": request_id,
            "contains_driver_card": True,
            "download_url": download_url,
            "download_label": "PDF herunterladen",
            "download_filename": pdf_filename,
            "file_name": pdf_filename,
            "file_type": "pdf",
            "file_path": request_doc.get("pdf_relative_path") or request_doc.get("pdf_path") or "",
            "pdf_relative_path": request_doc.get("pdf_relative_path") or "",
            "description": document_description,
            "tracker_upload_ready": True,
        },
    )


def get_active_fahrerkarte_request_for_issue(discord_id):
    discord_id = safe_str(discord_id)
    if not discord_id:
        return None
    return fahrerkarte_requests_collection.find_one(
        {
            "discord_id": discord_id,
            "archived": {"$ne": True},
            "status": {"$in": ["pending", "open", "postponed", "claimed", "approved"]},
        },
        sort=[("created_at", DESCENDING)]
    )


def create_direct_fahrerkarte_request_for_user(user_doc, actor=None, issue_note=""):
    if not user_doc:
        raise ValueError("Fahrer wurde nicht gefunden.")

    actor = actor or current_staff_identity()
    now = now_utc()
    discord_id = safe_str(user_doc.get("discord_id"))
    display_name = safe_str(user_doc.get("display_name") or user_doc.get("username") or user_doc.get("discord_username"), "EifelLog Fahrer")
    role_name = get_primary_role_name(user_doc.get("roles", []))
    request_id = uuid.uuid4().hex

    request_doc = {
        "request_id": request_id,
        "discord_id": discord_id,
        "user_id": discord_id,
        "username": user_doc.get("username") or user_doc.get("discord_username"),
        "discord_username": user_doc.get("discord_username") or user_doc.get("username"),
        "avatar_url": make_external_url(get_discord_avatar_url(user_doc)),
        "name": display_name,
        "full_name": display_name,
        "display_name": display_name,
        "role": role_name,
        "role_name": role_name,
        "system_id": discord_id,
        "driver_number": user_doc.get("driver_number") or user_doc.get("fahrernummer") or "",
        "priority": "normal",
        "reason": "new_issue",
        "delivery_method": "servicecenter",
        "notes": safe_str(issue_note, "Direkte Ausstellung über Dokument / Ausstellen."),
        "status": "claimed",
        "claimed_by": actor,
        "claimed_at": now,
        "approved_by": actor,
        "approved_at": now,
        "approval_note": safe_str(issue_note, "Direkte Ausstellung durch Personalabteilung."),
        "handler_name": actor.get("display_name") or actor.get("username") or "Personalabteilung",
        "created_at": now,
        "updated_at": now,
        "source": "personalabteilung_dokument_ausstellen",
        "card_id": "",
    }
    inserted = fahrerkarte_requests_collection.insert_one(request_doc)
    return fahrerkarte_requests_collection.find_one({"_id": inserted.inserted_id})


def ensure_fahrerkarte_dashboard_document_once(request_doc, actor=None, description=""):
    discord_id = safe_str(request_doc.get("discord_id") or request_doc.get("user_id"))
    request_id = safe_str(request_doc.get("request_id") or request_doc.get("_id"))
    if not discord_id or not request_id:
        return None

    existing = system_documents_collection.find_one({
        "discord_id": discord_id,
        "type": "driver_card_pdf",
        "request_id": request_id,
        "archived": {"$ne": True},
        "hidden": {"$ne": True},
    })
    if existing:
        return existing

    return create_fahrerkarte_pdf_dashboard_document(request_doc, actor=actor, description=description)


def auto_issue_fahrerkarte_for_user(user_doc, actor=None, issue_note="", request_doc=None, force_pdf=True):
    if not user_doc:
        raise ValueError("Fahrer wurde nicht gefunden.")

    actor = actor or current_staff_identity()
    handler_name = actor.get("display_name") or actor.get("username") or "Personalabteilung"
    issue_note = safe_str(issue_note, "Fahrerkarte wurde über Dokument / Ausstellen automatisch ausgestellt.")[:1000]
    discord_id = safe_str(user_doc.get("discord_id"))

    if not request_doc:
        request_doc = get_active_fahrerkarte_request_for_issue(discord_id)

    if not request_doc:
        request_doc = create_direct_fahrerkarte_request_for_user(user_doc, actor=actor, issue_note=issue_note)

    current_status = normalize_fahrerkarte_status(request_doc.get("status"))
    if current_status in {"rejected", "archived"}:
        raise PermissionError("Abgelehnte oder archivierte Fahrerkarte-Anträge können nicht ausgestellt werden.")

    if current_status == "issued":
        pdf_path = request_doc.get("pdf_path") or request_doc.get("pdf_relative_path")
        resolved_path = resolve_fahrerkarte_pdf_path(pdf_path)
        if not resolved_path or not os.path.exists(resolved_path):
            file_path, relative_path, filename, _pdf_bytes = save_fahrerkarte_pdf(request_doc, user_doc=user_doc, actor=actor, force=True)
            fahrerkarte_requests_collection.update_one(
                {"_id": request_doc["_id"]},
                {"$set": {"pdf_path": file_path, "pdf_relative_path": relative_path, "pdf_filename": filename, "updated_at": now_utc()}}
            )
            request_doc = fahrerkarte_requests_collection.find_one({"_id": request_doc["_id"]})
        ensure_fahrerkarte_dashboard_document_once(request_doc, actor=actor, description=issue_note)
        return {
            "request": request_doc,
            "download_url": servicecenter_fahrerkarte_download_url(request_doc.get("request_id") or request_doc.get("_id")),
            "pdf_filename": request_doc.get("pdf_filename") or "EifelLog_Fahrerkarte.pdf",
            "card_id": request_doc.get("card_id"),
            "already_issued": True,
        }

    claimed_by = request_doc.get("claimed_by") or {}
    claimed_discord_id = safe_str(claimed_by.get("discord_id"))
    actor_discord_id = safe_str(actor.get("discord_id"))
    if current_status in {"claimed", "approved"} and claimed_discord_id and actor_discord_id and claimed_discord_id != actor_discord_id:
        claimed_name = claimed_by.get("display_name") or claimed_by.get("username") or "einem anderen Sachbearbeiter"
        raise PermissionError(f"Dieser Fahrerkarte-Antrag ist bereits von {claimed_name} geclaimt.")

    now = now_utc()
    card_id = safe_str(request_doc.get("card_id")) or generate_fahrerkarte_card_id(discord_id, request_doc.get("request_id"))

    pre_update = {
        "status": "issued",
        "card_id": card_id,
        "claimed_by": request_doc.get("claimed_by") or actor,
        "claimed_at": request_doc.get("claimed_at") or now,
        "approved_by": request_doc.get("approved_by") or actor,
        "approved_at": request_doc.get("approved_at") or now,
        "issued_by": actor,
        "issued_at": now,
        "issue_note": issue_note,
        "handler_name": handler_name,
        "tracker_upload_ready": True,
        "updated_at": now,
    }

    temp_doc = dict(request_doc)
    temp_doc.update(pre_update)
    file_path, relative_path, filename, _pdf_bytes = save_fahrerkarte_pdf(temp_doc, user_doc=user_doc, actor=actor, force=force_pdf)

    final_update = dict(pre_update)
    final_update.update({
        "pdf_path": file_path,
        "pdf_relative_path": relative_path,
        "pdf_filename": filename,
        "download_url": servicecenter_fahrerkarte_download_url(request_doc.get("request_id") or request_doc.get("_id")),
    })

    fahrerkarte_requests_collection.update_one({"_id": request_doc["_id"]}, {"$set": final_update})
    fresh_request = fahrerkarte_requests_collection.find_one({"_id": request_doc["_id"]})

    update_user_fahrerkarte_state(user_doc, fresh_request, "issued", actor, extra_set={
        "fahrerkarte_issued_at": now,
        "fahrerkarte_pdf_relative_path": relative_path,
        "fahrerkarte_pdf_filename": filename,
        "fahrerkarte_download_url": servicecenter_fahrerkarte_download_url(fresh_request.get("request_id")),
    })

    ensure_fahrerkarte_dashboard_document_once(fresh_request, actor=actor, description=issue_note)
    tasks_collection.update_many(
        {"source": "servicecenter_fahrerkarte", "request_id": fresh_request.get("request_id")},
        {"$set": {"status": "done", "completed_at": now, "updated_at": now}}
    )

    return {
        "request": fresh_request,
        "download_url": servicecenter_fahrerkarte_download_url(fresh_request.get("request_id")),
        "pdf_filename": filename,
        "card_id": card_id,
        "already_issued": False,
    }


def should_issue_fahrerkarte_from_document_payload(data, title="", message=""):
    doc_type = safe_str(data.get("type") or data.get("documentType") or data.get("docType")).lower()
    action = safe_str(data.get("action") or data.get("documentAction")).lower()
    combined = f"{title} {message} {doc_type} {action}".lower()
    explicit = bool_from_payload(
        data.get("issueFahrerkarte")
        or data.get("issue_fahrerkarte")
        or data.get("issueDriverCard")
        or data.get("ausstellen"),
        fallback=False
    )
    if explicit:
        return True
    if doc_type in {"fahrerkarte", "driver_card", "driver-card", "driver_card_pdf", "driver-card-pdf"}:
        return True
    if action in {"fahrerkarte_ausstellen", "issue_fahrerkarte", "issue-driver-card", "driver_card_issue"}:
        return True
    return "fahrerkarte" in combined and ("ausstellen" in combined or "austellen" in combined or "pdf" in combined)


def prepare_fahrerkarte_request_for_personalabteilung(request_doc):
    item = dict(request_doc)
    mongo_id = item.get("_id")
    mongo_id_str = str(mongo_id) if mongo_id else ""
    item["_id"] = mongo_id_str
    item["id"] = safe_str(item.get("request_id") or item.get("id") or mongo_id_str)
    item["request_id"] = safe_str(item.get("request_id") or item["id"])
    item["name"] = item.get("display_name") or item.get("full_name") or item.get("name") or "Unbekannter User"
    item["display_name"] = item.get("display_name") or item["name"]
    item["username"] = item.get("username") or item.get("discord_username") or item["name"]
    item["role"] = item.get("role") or item.get("role_name") or "Fahrer"
    item["role_name"] = item.get("role_name") or item["role"]
    item["status"] = normalize_fahrerkarte_status(item.get("status") or "pending")
    item["status_label"] = fahrerkarte_status_label(item["status"])
    item["created_at"] = format_datetime_for_template(item.get("created_at")) or "-"
    item["requested_at"] = item["created_at"]
    item["updated_at"] = format_datetime_for_template(item.get("updated_at")) or item["created_at"]
    item["claimed_at"] = format_datetime_for_template(item.get("claimed_at")) or ""
    item["approved_at"] = format_datetime_for_template(item.get("approved_at")) or ""
    item["issued_at"] = format_datetime_for_template(item.get("issued_at")) or ""
    item["postponed_until"] = format_datetime_for_template(item.get("postponed_until")) or ""
    item["priority"] = item.get("priority") or "normal"
    item["priority_label"] = fahrerkarte_priority_label(item.get("priority"))
    item["reason"] = item.get("reason") or "Nicht angegeben"
    item["reason_label"] = fahrerkarte_reason_label(item.get("reason"))
    item["delivery_method"] = item.get("delivery_method") or "servicecenter"
    item["delivery_label"] = fahrerkarte_delivery_label(item.get("delivery_method"))
    item["notes"] = item.get("notes") or item.get("note") or ""
    item["system_id"] = item.get("system_id") or item.get("discord_id") or "-"
    item["driver_number"] = item.get("driver_number") or ""
    item["card_id"] = item.get("card_id") or ""
    item["pdf_filename"] = item.get("pdf_filename") or item.get("file_name") or ""
    item["pdf_relative_path"] = item.get("pdf_relative_path") or item.get("pdf_path") or ""
    item["download_url"] = servicecenter_fahrerkarte_download_url(item["request_id"]) if item["pdf_relative_path"] else ""
    item["tracker_upload_ready"] = bool(item.get("tracker_upload_ready") or item.get("status") == "issued")
    item["avatar_url"] = item.get("avatar_url") or ""
    item["source_user_mongo_id"] = item.get("source_user_mongo_id") or item.get("user_mongo_id") or ""
    item["user_mongo_id"] = item["source_user_mongo_id"]
    item["source_collection"] = item.get("source_collection") or item.get("source") or "fahrerkarte_requests"

    claimed_by = item.get("claimed_by") or {}
    approved_by = item.get("approved_by") or {}
    issued_by = item.get("issued_by") or {}
    rejected_by = item.get("rejected_by") or {}
    postponed_by = item.get("postponed_by") or {}
    item["claimed_by_name"] = (
        issued_by.get("display_name")
        or approved_by.get("display_name")
        or rejected_by.get("display_name")
        or postponed_by.get("display_name")
        or claimed_by.get("display_name")
        or item.get("handler_name")
        or "Noch nicht geclaimt"
    )
    item["handler_name"] = item["claimed_by_name"]
    item["sachbearbeiter_name"] = item["claimed_by_name"]
    item["reject_reason"] = item.get("reject_reason") or ""
    item["postpone_reason"] = item.get("postpone_reason") or ""
    item["issue_note"] = item.get("issue_note") or ""
    digital_signature = item.get("digital_signature") or {}
    item["signature_required"] = item["status"] in {"approved", "claimed"}
    item["issue_requires_signature"] = True
    item["signature_name"] = item.get("signature_name") or digital_signature.get("name") or ""
    item["signature_hash"] = item.get("signature_hash") or digital_signature.get("hash") or ""
    item["signature_valid"] = bool(item.get("signature_valid") or digital_signature.get("valid"))

    # Frontend-Hilfe für die Spalte/Button "Dokument":
    # - vor Ausstellung: Button "AUSSTELLEN" kann die Issue-Route aufrufen
    # - nach Ausstellung: Button kann direkt die PDF herunterladen
    if item["status"] == "issued" and item["download_url"]:
        item["document_action"] = "download"
        item["document_button_label"] = "PDF DOWNLOAD"
        item["document_download_url"] = item["download_url"]
        item["document_issue_url"] = ""
    else:
        item["document_action"] = "issue_fahrerkarte"
        item["document_button_label"] = "AUSSTELLEN"
        item["document_download_url"] = ""
        item["document_issue_url"] = "/api/personalabteilung/servicecenter/fahrerkarte/issue"
    item["auto_download_after_issue"] = True
    return item


def find_fahrerkarte_request(request_id):
    request_id = safe_str(request_id)
    if not request_id:
        return None

    request_doc = fahrerkarte_requests_collection.find_one(request_lookup_query(request_id))
    if request_doc:
        mirror_fahrerkarte_request_for_discord_plugin(request_doc)
        return request_doc

    user_lookup_items = [
        {"fahrerkarte_request_id": request_id},
        {"personalisierte_fahrerkarte_request_id": request_id},
        {"discord_id": request_id},
        {"user_id": request_id},
    ]
    object_id = object_id_or_none(request_id)
    if object_id:
        user_lookup_items.append({"_id": object_id})

    user_doc = users_collection.find_one({"$or": user_lookup_items})
    if user_doc and user_doc_has_fahrerkarte_request(user_doc):
        return sync_fahrerkarte_request_from_user_doc(user_doc)

    mirror_doc = fahrerkarte_beantragungen_collection.find_one({
        "$or": [
            {"request_id": request_id},
            {"fahrerkarte_request_id": request_id},
            {"source_user_mongo_id": request_id},
        ]
    })
    if mirror_doc:
        mirror_request_id = safe_str(mirror_doc.get("request_id") or mirror_doc.get("fahrerkarte_request_id"))
        if mirror_request_id and mirror_request_id != request_id:
            return find_fahrerkarte_request(mirror_request_id)

    return None


def update_user_fahrerkarte_state(user_doc, request_doc, status, actor=None, extra_set=None):
    if not user_doc and request_doc:
        user_doc = find_user_for_request_doc(request_doc)
    if not user_doc:
        return

    actor = actor or {}
    handler_name = actor.get("display_name") or actor.get("username") or request_doc.get("handler_name") or "Personalabteilung"
    now = now_utc()
    update_fields = {
        "personalisierte_fahrerkarte_status": status,
        "fahrerkarte_status": status,
        "fahrerkarte_handler": handler_name,
        "fahrerkarte_request_id": safe_str(request_doc.get("request_id") or request_doc.get("_id")),
        "fahrerkarte_name": request_doc.get("display_name") or request_doc.get("full_name") or request_doc.get("name"),
        "fahrerkarte_role": request_doc.get("role") or request_doc.get("role_name"),
        "fahrerkarte_updated_at": now,
    }
    if request_doc.get("card_id"):
        update_fields["fahrerkarte_card_id"] = request_doc.get("card_id")
    if request_doc.get("issued_at"):
        update_fields["fahrerkarte_issued_at"] = request_doc.get("issued_at")
    if request_doc.get("pdf_relative_path"):
        update_fields["fahrerkarte_pdf_relative_path"] = request_doc.get("pdf_relative_path")
        update_fields["fahrerkarte_pdf_filename"] = request_doc.get("pdf_filename") or request_doc.get("file_name")
    if extra_set:
        update_fields.update(extra_set)


    users_collection.update_one({"_id": user_doc["_id"]}, {"$set": update_fields})
    mirror_fahrerkarte_request_for_discord_plugin(request_doc, user_doc=user_doc)


# ==========================================
# SERVICECENTER / DISCORD CHANNEL + THREAD SYNC
# ==========================================

def servicecenter_discord_role_ids():
    role_ids = []
    raw_items = []

    if SERVICECENTER_DISCORD_REVIEW_ROLE_IDS_RAW:
        raw_items.extend(re.split(r"[,;\s]+", SERVICECENTER_DISCORD_REVIEW_ROLE_IDS_RAW))

    raw_items.extend([
        ROLE_PERSONALABTEILUNG_ID,
        ROLE_HR_CONTROLLING_ID,
        ROLE_GESCHAEFTSFUEHRUNG_ID,
        ROLE_PROJEKTLEITUNG_ID,
    ])

    for role_id in raw_items:
        role_id = safe_str(role_id)
        if role_id.isdigit() and role_id not in role_ids:
            role_ids.append(role_id)
    return role_ids


def servicecenter_discord_mentions(include_roles=True):
    if not include_roles:
        return ""
    role_ids = servicecenter_discord_role_ids()
    return " ".join(f"<@&{role_id}>" for role_id in role_ids)


def discord_api_request(method, endpoint, json_payload=None, data=None, files=None, timeout=12):
    if not DISCORD_BOT_TOKEN:
        return False, {"error": "DISCORD_BOT_TOKEN fehlt."}, 0

    endpoint = safe_str(endpoint)
    if not endpoint.startswith("/"):
        endpoint = f"/{endpoint}"

    headers = {"Authorization": f"Bot {DISCORD_BOT_TOKEN}"}
    if not files:
        headers["Content-Type"] = "application/json"

    try:
        response = requests.request(
            method.upper(),
            f"{API_BASE_URL}{endpoint}",
            headers=headers,
            json=json_payload if not files else None,
            data=data,
            files=files,
            timeout=timeout,
        )
    except Exception as error:
        return False, {"error": str(error)}, 0

    payload = None
    try:
        payload = response.json()
    except Exception:
        payload = {"text": response.text}

    if 200 <= response.status_code < 300:
        return True, payload or {}, response.status_code

    return False, payload or {}, response.status_code


def discord_truncate(value, limit=1024, fallback="-"):
    value = safe_str(value, fallback)
    if not value:
        value = fallback
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)] + "..."


def servicecenter_discord_absolute_url(path):
    path = safe_str(path)
    if not path:
        return ""
    if path.startswith("http://") or path.startswith("https://"):
        return path

    base = SERVICECENTER_PUBLIC_BASE_URL or safe_str(TOUR_RECEIPT_PUBLIC_BASE_URL).rstrip("/")
    if base:
        return f"{base}/{path.lstrip('/')}"

    try:
        return request.host_url.rstrip("/") + (path if path.startswith("/") else f"/{path}")
    except Exception:
        return path


def servicecenter_discord_message_link(channel_id, message_id, guild_id=None):
    guild_id = safe_str(guild_id or DISCORD_GUILD_ID)
    channel_id = safe_str(channel_id)
    message_id = safe_str(message_id)
    if guild_id and channel_id and message_id:
        return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"
    return ""


def servicecenter_discord_thread_link(thread_id):
    guild_id = safe_str(DISCORD_GUILD_ID)
    thread_id = safe_str(thread_id)
    if guild_id and thread_id:
        return f"https://discord.com/channels/{guild_id}/{thread_id}"
    return ""


def servicecenter_discord_status_color(status):
    status = normalize_fahrerkarte_status(status)
    return {
        "pending": 0xFAA61A,
        "open": 0xFAA61A,
        "claimed": 0x5865F2,
        "approved": 0x2BA044,
        "issued": 0x2BA044,
        "rejected": 0xD83C3E,
        "postponed": 0x6E8096,
        "archived": 0x2F3136,
    }.get(status, 0x2BA044)


def servicecenter_discord_event_title(event, request_doc):
    status = normalize_fahrerkarte_status(request_doc.get("status") or "pending")
    if event == "created":
        return "🪪 Neue Fahrerkarte-Beantragung"
    if event == "existing":
        return "🪪 Vorhandene Fahrerkarte-Beantragung"
    if event == "claimed":
        return "👤 Fahrerkarte-Beantragung übernommen"
    if event == "approved":
        return "✅ Fahrerkarte-Beantragung genehmigt"
    if event == "issued":
        return "🟢 Fahrerkarte ausgestellt"
    if event == "rejected":
        return "❌ Fahrerkarte-Beantragung abgelehnt"
    if event == "postponed":
        return "⏸️ Fahrerkarte-Beantragung zurückgestellt"
    return f"🪪 Fahrerkarte-Beantragung: {fahrerkarte_status_label(status)}"


def servicecenter_discord_thread_name(request_doc):
    request_id = safe_str(request_doc.get("request_id") or request_doc.get("_id"))
    user_name = safe_str(request_doc.get("display_name") or request_doc.get("full_name") or request_doc.get("name") or request_doc.get("username"), "user")
    user_slug = normalize_username(user_name, fallback="user").lower()
    suffix = request_id[-6:] if request_id else secrets.token_hex(3)
    name = f"fahrerkarte-{user_slug}-{suffix}"
    return discord_truncate(name, 95, fallback="fahrerkarte-antrag")


def servicecenter_discord_components(request_doc):
    request_id = safe_str(request_doc.get("request_id") or request_doc.get("_id"))
    buttons = []

    personal_url = servicecenter_discord_absolute_url("/personalabteilung")
    if personal_url.startswith("http"):
        buttons.append({"type": 2, "style": 5, "label": "Personalabteilung öffnen", "url": personal_url})

    service_url = servicecenter_discord_absolute_url("/servicecenter")
    if service_url.startswith("http"):
        buttons.append({"type": 2, "style": 5, "label": "ServiceCenter", "url": service_url})

    if request_doc.get("pdf_relative_path") or request_doc.get("pdf_path") or normalize_fahrerkarte_status(request_doc.get("status")) == "issued":
        download_url = servicecenter_discord_absolute_url(servicecenter_fahrerkarte_download_url(request_id))
        if download_url.startswith("http"):
            buttons.append({"type": 2, "style": 5, "label": "PDF Download", "url": download_url})

    return [{"type": 1, "components": buttons[:5]}] if buttons else []


def servicecenter_discord_allowed_mentions(request_doc, include_roles=True):
    roles = servicecenter_discord_role_ids() if include_roles else []
    users = []
    discord_id = safe_str(request_doc.get("discord_id") or request_doc.get("user_id"))
    if discord_id.isdigit():
        users.append(discord_id)
    return {"parse": [], "roles": roles, "users": users}


def servicecenter_discord_request_embed(request_doc, event="updated", actor=None):
    actor = actor or {}
    request_id = safe_str(request_doc.get("request_id") or request_doc.get("_id"))
    discord_id = safe_str(request_doc.get("discord_id") or request_doc.get("user_id"))
    status = normalize_fahrerkarte_status(request_doc.get("status") or "pending")
    display_name = safe_str(request_doc.get("display_name") or request_doc.get("full_name") or request_doc.get("name") or request_doc.get("username"), "Unbekannter User")
    role_name = safe_str(request_doc.get("role") or request_doc.get("role_name"), "-")
    handler = safe_str(
        request_doc.get("handler_name")
        or (request_doc.get("issued_by") or {}).get("display_name")
        or (request_doc.get("approved_by") or {}).get("display_name")
        or (request_doc.get("claimed_by") or {}).get("display_name")
        or (actor or {}).get("display_name"),
        "Noch nicht zugewiesen"
    )

    description = (
        f"**{display_name}** hat eine personalisierte Fahrerkarte im ServiceCenter beantragt.\n"
        f"Status: **{fahrerkarte_status_label(status)}**"
    )
    if event == "issued":
        description = f"Die personalisierte Fahrerkarte fuer **{display_name}** wurde ausgestellt."
    elif event == "rejected":
        description = f"Die Fahrerkarte-Beantragung von **{display_name}** wurde abgelehnt."
    elif event == "postponed":
        description = f"Die Fahrerkarte-Beantragung von **{display_name}** wurde zurueckgestellt."

    fields = [
        {"name": "👤 Antragsteller", "value": discord_truncate(f"<@{discord_id}>\n`{discord_id}`" if discord_id else display_name), "inline": True},
        {"name": "🏷️ Rolle", "value": discord_truncate(role_name), "inline": True},
        {"name": "📌 Status", "value": discord_truncate(fahrerkarte_status_label(status)), "inline": True},
        {"name": "🆔 Antrag-ID", "value": discord_truncate(f"`{request_id}`"), "inline": False},
        {"name": "🗄️ User-DB-ID", "value": discord_truncate(f"`{safe_str(request_doc.get('source_user_mongo_id') or request_doc.get('user_mongo_id') or '-')}`"), "inline": True},
        {"name": "📚 Quelle", "value": discord_truncate(safe_str(request_doc.get("source_collection") or request_doc.get("source") or "fahrerkarte_requests")), "inline": True},
        {"name": "⚡ Priorität", "value": discord_truncate(fahrerkarte_priority_label(request_doc.get("priority"))), "inline": True},
        {"name": "📝 Grund", "value": discord_truncate(fahrerkarte_reason_label(request_doc.get("reason"))), "inline": True},
        {"name": "📦 Bereitstellung", "value": discord_truncate(fahrerkarte_delivery_label(request_doc.get("delivery_method"))), "inline": True},
        {"name": "👮 Sachbearbeiter", "value": discord_truncate(handler), "inline": True},
        {"name": "🕒 Eingang", "value": discord_truncate(format_datetime_for_template(request_doc.get("created_at")) or "-"), "inline": True},
    ]

    if request_doc.get("driver_number"):
        fields.append({"name": "🚛 Fahrer-/Personalnummer", "value": discord_truncate(request_doc.get("driver_number")), "inline": True})
    if request_doc.get("card_id"):
        fields.append({"name": "💳 Karten-ID", "value": discord_truncate(f"`{request_doc.get('card_id')}`"), "inline": False})
    if request_doc.get("notes"):
        fields.append({"name": "📄 Hinweise", "value": discord_truncate(request_doc.get("notes"), 900), "inline": False})
    if request_doc.get("approval_note"):
        fields.append({"name": "✅ Freigabe-Hinweis", "value": discord_truncate(request_doc.get("approval_note"), 900), "inline": False})
    if request_doc.get("issue_note"):
        fields.append({"name": "🟢 Ausstellungs-Hinweis", "value": discord_truncate(request_doc.get("issue_note"), 900), "inline": False})
    if request_doc.get("reject_reason"):
        fields.append({"name": "❌ Ablehnungsgrund", "value": discord_truncate(request_doc.get("reject_reason"), 900), "inline": False})
    if request_doc.get("postpone_reason"):
        fields.append({"name": "⏸️ Zurückgestellt", "value": discord_truncate(request_doc.get("postpone_reason"), 900), "inline": False})

    embed = {
        "title": servicecenter_discord_event_title(event, request_doc),
        "description": discord_truncate(description, 3900),
        "color": servicecenter_discord_status_color(status),
        "fields": fields[:25],
        "footer": {"text": "EifelLog ServiceCenter • Fahrerkarte"},
        "timestamp": now_utc().isoformat() + "Z",
    }

    avatar_url = safe_str(request_doc.get("avatar_url"))
    if avatar_url.startswith("http://") or avatar_url.startswith("https://"):
        embed["thumbnail"] = {"url": avatar_url}

    return embed


def servicecenter_discord_history_embed(discord_id, current_request_id=""):
    discord_id = safe_str(discord_id)
    current_request_id = safe_str(current_request_id)
    if not discord_id:
        return None

    records = list(fahrerkarte_requests_collection.find(
        {"discord_id": discord_id, "archived": {"$ne": True}}
    ).sort([("created_at", DESCENDING)]).limit(10))

    if not records:
        description = "Keine bisherigen Fahrerkarte-Beantragungen gefunden."
    else:
        lines = []
        for item in records:
            item_request_id = safe_str(item.get("request_id") or item.get("_id"))
            marker = "➡️" if item_request_id == current_request_id else "•"
            date_text = format_datetime_for_template(item.get("created_at")) or "-"
            status_text = fahrerkarte_status_label(item.get("status"))
            reason_text = fahrerkarte_reason_label(item.get("reason"))
            card_id = safe_str(item.get("card_id"))
            card_text = f" / `{card_id}`" if card_id else ""
            lines.append(f"{marker} `{date_text}` **{status_text}** — {reason_text}{card_text}")
        description = "\n".join(lines)

    return {
        "title": "🗂️ Vorhandene Beantragungen dieses Users",
        "description": discord_truncate(description, 3900),
        "color": 0x2BA044,
        "footer": {"text": "EifelLog ServiceCenter • Historie"},
        "timestamp": now_utc().isoformat() + "Z",
    }


def servicecenter_discord_send_message(channel_id, payload):
    channel_id = safe_str(channel_id)
    if not channel_id:
        return False, {"error": "Channel-ID fehlt."}, 0
    return discord_api_request("POST", f"/channels/{channel_id}/messages", json_payload=payload)


def servicecenter_discord_patch_message(channel_id, message_id, payload):
    channel_id = safe_str(channel_id)
    message_id = safe_str(message_id)
    if not channel_id or not message_id:
        return False, {"error": "Channel-ID oder Message-ID fehlt."}, 0
    return discord_api_request("PATCH", f"/channels/{channel_id}/messages/{message_id}", json_payload=payload)


def servicecenter_discord_upsert_message(channel_id, message_id, payload):
    if message_id:
        ok, result, status_code = servicecenter_discord_patch_message(channel_id, message_id, payload)
        if ok:
            return True, result, status_code
    return servicecenter_discord_send_message(channel_id, payload)


def servicecenter_discord_create_thread_from_message(parent_channel_id, parent_message_id, thread_name):
    if not SERVICECENTER_DISCORD_CREATE_THREAD:
        return False, {"error": "Thread-Erstellung ist deaktiviert."}, 0

    payload = {
        "name": thread_name,
        "auto_archive_duration": SERVICECENTER_DISCORD_THREAD_AUTO_ARCHIVE_DURATION,
    }
    return discord_api_request(
        "POST",
        f"/channels/{parent_channel_id}/messages/{parent_message_id}/threads",
        json_payload=payload,
    )


def servicecenter_discord_create_forum_thread(parent_channel_id, request_doc, event="created"):
    if not SERVICECENTER_DISCORD_CREATE_THREAD:
        return False, {"error": "Thread-Erstellung ist deaktiviert."}, 0

    content = servicecenter_discord_mentions(include_roles=True)
    if content:
        content += "\n"
    content += "Neue ServiceCenter-Beantragung. Bitte im Thread prüfen."

    payload = {
        "name": servicecenter_discord_thread_name(request_doc),
        "auto_archive_duration": SERVICECENTER_DISCORD_THREAD_AUTO_ARCHIVE_DURATION,
        "message": {
            "content": content,
            "embeds": [servicecenter_discord_request_embed(request_doc, event=event)],
            "components": servicecenter_discord_components(request_doc),
            "allowed_mentions": servicecenter_discord_allowed_mentions(request_doc, include_roles=True),
        },
    }
    return discord_api_request("POST", f"/channels/{parent_channel_id}/threads", json_payload=payload)


def ensure_servicecenter_discord_thread(request_doc, event="created"):
    parent_channel_id = safe_str(SERVICECENTER_DISCORD_CHANNEL_ID)
    if not parent_channel_id:
        return {"ok": False, "error": "SERVICECENTER_DISCORD_CHANNEL_ID fehlt."}

    existing_thread_id = safe_str(request_doc.get("discord_thread_id") or request_doc.get("thread_id"))
    existing_parent_message_id = safe_str(request_doc.get("discord_parent_message_id") or request_doc.get("discord_message_id"))
    if existing_thread_id:
        return {
            "ok": True,
            "thread_id": existing_thread_id,
            "parent_channel_id": safe_str(request_doc.get("discord_parent_channel_id") or parent_channel_id),
            "parent_message_id": existing_parent_message_id,
            "created": False,
        }

    thread_name = servicecenter_discord_thread_name(request_doc)
    parent_payload = {
        "content": f"{servicecenter_discord_mentions(include_roles=True)}\n🪪 **Neue Fahrerkarte-Beantragung** von <@{safe_str(request_doc.get('discord_id') or request_doc.get('user_id'))}>".strip(),
        "embeds": [servicecenter_discord_request_embed(request_doc, event=event)],
        "components": servicecenter_discord_components(request_doc),
        "allowed_mentions": servicecenter_discord_allowed_mentions(request_doc, include_roles=True),
    }

    parent_ok, parent_message, parent_status = servicecenter_discord_send_message(parent_channel_id, parent_payload)
    if parent_ok and parent_message.get("id"):
        parent_message_id = safe_str(parent_message.get("id"))
        if SERVICECENTER_DISCORD_CREATE_THREAD:
            thread_ok, thread_payload, thread_status = servicecenter_discord_create_thread_from_message(parent_channel_id, parent_message_id, thread_name)
            if thread_ok and thread_payload.get("id"):
                return {
                    "ok": True,
                    "thread_id": safe_str(thread_payload.get("id")),
                    "parent_channel_id": parent_channel_id,
                    "parent_message_id": parent_message_id,
                    "created": True,
                }

            return {
                "ok": True,
                "thread_id": "",
                "parent_channel_id": parent_channel_id,
                "parent_message_id": parent_message_id,
                "created": False,
                "warning": f"Message erstellt, Thread konnte nicht erstellt werden: {thread_payload}",
            }

        return {
            "ok": True,
            "thread_id": "",
            "parent_channel_id": parent_channel_id,
            "parent_message_id": parent_message_id,
            "created": False,
        }

    # Fallback fuer Forum-/Media-Channels: dort wird direkt ein Thread mit Startnachricht erstellt.
    forum_ok, forum_thread, forum_status = servicecenter_discord_create_forum_thread(parent_channel_id, request_doc, event=event)
    if forum_ok and forum_thread.get("id"):
        return {
            "ok": True,
            "thread_id": safe_str(forum_thread.get("id")),
            "parent_channel_id": parent_channel_id,
            "parent_message_id": "",
            "created": True,
        }

    return {
        "ok": False,
        "error": f"Discord Message/Thread konnte nicht erstellt werden. MessageStatus={parent_status}, Message={parent_message}, ForumStatus={forum_status}, Forum={forum_thread}",
    }


def servicecenter_discord_sync_fahrerkarte_request(request_doc, event="updated", actor=None):
    if not SERVICECENTER_DISCORD_ENABLED:
        return {"ok": False, "skipped": True, "error": "SERVICECENTER_DISCORD_ENABLED ist deaktiviert."}
    if not request_doc:
        return {"ok": False, "error": "Request-Dokument fehlt."}
    if not DISCORD_BOT_TOKEN:
        return {"ok": False, "error": "DISCORD_BOT_TOKEN fehlt."}

    request_id = safe_str(request_doc.get("request_id") or request_doc.get("_id"))
    if not request_id:
        return {"ok": False, "error": "Request-ID fehlt."}

    mirror_fahrerkarte_request_for_discord_plugin(request_doc)

    thread_info = ensure_servicecenter_discord_thread(request_doc, event=event)
    if not thread_info.get("ok"):
        fahrerkarte_requests_collection.update_one(
            request_lookup_query(request_id),
            {"$set": {
                "discord_sync_status": "failed",
                "discord_sync_error": safe_str(thread_info.get("error"))[:1800],
                "discord_synced_at": now_utc(),
            }}
        )
        return thread_info

    target_channel_id = safe_str(thread_info.get("thread_id") or thread_info.get("parent_channel_id"))
    parent_channel_id = safe_str(thread_info.get("parent_channel_id") or SERVICECENTER_DISCORD_CHANNEL_ID)
    parent_message_id = safe_str(thread_info.get("parent_message_id"))

    # Datenbank zuerst aktualisieren, damit Folgesyncs den Thread wiederverwenden.
    set_fields = {
        "discord_sync_status": "synced",
        "discord_sync_error": "",
        "discord_synced_at": now_utc(),
        "discord_parent_channel_id": parent_channel_id,
        "discord_parent_message_id": parent_message_id,
        "discord_channel_id": target_channel_id,
    }
    if thread_info.get("thread_id"):
        set_fields["discord_thread_id"] = safe_str(thread_info.get("thread_id"))
        set_fields["thread_id"] = safe_str(thread_info.get("thread_id"))
    if parent_message_id:
        set_fields["discord_message_id"] = parent_message_id
        set_fields["discord_message_url"] = servicecenter_discord_message_link(parent_channel_id, parent_message_id)
    if target_channel_id:
        set_fields["discord_thread_url"] = servicecenter_discord_thread_link(target_channel_id)

    fahrerkarte_requests_collection.update_one(request_lookup_query(request_id), {"$set": set_fields})
    fresh_request = fahrerkarte_requests_collection.find_one(request_lookup_query(request_id)) or request_doc

    admin_payload = {
        "content": "🪪 **ServiceCenter Fahrerkarte – Bearbeitung**",
        "embeds": [servicecenter_discord_request_embed(fresh_request, event=event, actor=actor)],
        "components": servicecenter_discord_components(fresh_request),
        "allowed_mentions": {"parse": []},
    }
    admin_message_id = safe_str(fresh_request.get("discord_admin_message_id"))
    admin_ok, admin_msg, admin_status = servicecenter_discord_upsert_message(target_channel_id, admin_message_id, admin_payload)

    if admin_ok and admin_msg.get("id"):
        fahrerkarte_requests_collection.update_one(request_lookup_query(request_id), {"$set": {
            "discord_admin_message_id": safe_str(admin_msg.get("id")),
            "discord_admin_message_url": servicecenter_discord_message_link(target_channel_id, admin_msg.get("id")),
            "discord_synced_at": now_utc(),
        }})

    history_embed = servicecenter_discord_history_embed(
        safe_str(fresh_request.get("discord_id") or fresh_request.get("user_id")),
        current_request_id=request_id,
    )
    history_ok = False
    history_msg = {}
    if history_embed:
        history_payload = {
            "content": "📚 **Historie dieses Users**",
            "embeds": [history_embed],
            "allowed_mentions": {"parse": []},
        }
        history_message_id = safe_str(fresh_request.get("discord_history_message_id"))
        history_ok, history_msg, _history_status = servicecenter_discord_upsert_message(target_channel_id, history_message_id, history_payload)
        if history_ok and history_msg.get("id"):
            fahrerkarte_requests_collection.update_one(request_lookup_query(request_id), {"$set": {
                "discord_history_message_id": safe_str(history_msg.get("id")),
                "discord_history_message_url": servicecenter_discord_message_link(target_channel_id, history_msg.get("id")),
                "discord_synced_at": now_utc(),
            }})

    if not admin_ok:
        fahrerkarte_requests_collection.update_one(request_lookup_query(request_id), {"$set": {
            "discord_sync_status": "partial",
            "discord_sync_error": safe_str(admin_msg)[:1800],
            "discord_synced_at": now_utc(),
        }})

    final_request = fahrerkarte_requests_collection.find_one(request_lookup_query(request_id)) or fresh_request
    mirror_fahrerkarte_request_for_discord_plugin(final_request)

    return {
        "ok": bool(admin_ok),
        "thread_id": target_channel_id,
        "parent_message_id": parent_message_id,
        "admin_message_id": safe_str(admin_msg.get("id")) if isinstance(admin_msg, dict) else "",
        "history_message_id": safe_str(history_msg.get("id")) if isinstance(history_msg, dict) else "",
        "history_ok": bool(history_ok),
        "created": bool(thread_info.get("created")),
        "warning": thread_info.get("warning", ""),
        "status": admin_status,
    }


def servicecenter_discord_send_pdf_fallback(request_doc, file_path, actor=None, reason="PDF-Fallback"):
    if not SERVICECENTER_DISCORD_ENABLED or not SERVICECENTER_DISCORD_ATTACH_PDF_ON_ISSUE:
        return {"ok": False, "skipped": True}
    if not DISCORD_BOT_TOKEN:
        return {"ok": False, "error": "DISCORD_BOT_TOKEN fehlt."}

    request_id = safe_str(request_doc.get("request_id") or request_doc.get("_id"))
    thread_id = safe_str(request_doc.get("discord_thread_id") or request_doc.get("thread_id") or request_doc.get("discord_channel_id"))
    if not thread_id:
        sync_result = servicecenter_discord_sync_fahrerkarte_request(request_doc, event="issued", actor=actor)
        thread_id = safe_str(sync_result.get("thread_id"))

    if not thread_id:
        return {"ok": False, "error": "Kein Discord-Thread/Channel fuer PDF-Fallback vorhanden."}

    resolved_path = resolve_fahrerkarte_pdf_path(file_path)
    if not resolved_path or not os.path.exists(resolved_path):
        return {"ok": False, "error": "PDF-Datei wurde nicht gefunden."}

    filename = safe_str(request_doc.get("pdf_filename") or os.path.basename(resolved_path), "Fahrerkarte.pdf")
    payload = {
        "content": (
            f"📎 **{reason}**\n"
            f"Falls der Web-Download nicht funktioniert, liegt die ausgestellte Fahrerkarte hier direkt als PDF im Thread.\n"
            f"Antrag-ID: `{request_id}`"
        ),
        "allowed_mentions": {"parse": []},
    }

    try:
        with open(resolved_path, "rb") as pdf_file:
            files = {"files[0]": (filename, pdf_file, "application/pdf")}
            data = {"payload_json": json.dumps(payload)}
            ok, result, status_code = discord_api_request(
                "POST",
                f"/channels/{thread_id}/messages",
                data=data,
                files=files,
                timeout=20,
            )
    except Exception as error:
        return {"ok": False, "error": str(error)}

    if ok and isinstance(result, dict):
        fahrerkarte_requests_collection.update_one(request_lookup_query(request_id), {"$set": {
            "discord_pdf_message_id": safe_str(result.get("id")),
            "discord_pdf_message_url": servicecenter_discord_message_link(thread_id, result.get("id")),
            "discord_pdf_uploaded_at": now_utc(),
        }})

    return {"ok": ok, "result": result, "status": status_code}



# ==========================================
# WEB-ONLY OVERRIDES FUER SERVICECENTER-FAHRERKARTEN
# ==========================================
# Die folgenden Namen bleiben aus Kompatibilitaetsgruenden bestehen, fuehren aber keinerlei
# Discord-API-Requests mehr aus. Alte Templates/JS koennen dadurch weiter laufen, die Bearbeitung
# findet trotzdem nur im Web-ServiceCenter statt.

def mirror_fahrerkarte_request_for_discord_plugin(request_doc, user_doc=None):
    return request_doc


def servicecenter_discord_sync_fahrerkarte_request(request_doc, event="updated", actor=None):
    if request_doc:
        request_id = safe_str(request_doc.get("request_id") or request_doc.get("_id"))
        if request_id:
            fahrerkarte_requests_collection.update_one(
                request_lookup_query(request_id),
                {"$set": {
                    "web_sync_status": "web_only",
                    "web_synced_at": now_utc(),
                    "discord_sync_status": "disabled_web_only",
                    "discord_sync_error": "Discord-Plugin entfernt: ServiceCenter Fahrerkarte laeuft vollstaendig ueber Web.",
                }}
            )
    return {"ok": True, "web_only": True, "skipped_discord": True, "event": safe_str(event)}


def servicecenter_discord_send_pdf_fallback(request_doc, file_path, actor=None, reason="PDF-Fallback"):
    return {"ok": True, "web_only": True, "skipped_discord": True}


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

def tracker_auth_user_from_payload(data=None):
    data = data or {}
    client_token = get_client_token_from_request(data)
    if not client_token:
        return None, None, (jsonify({"success": False, "error": "Tracker-Token fehlt."}), 401)

    user_doc = find_tracker_user_by_client_token(client_token)
    if not user_doc:
        return None, client_token, (jsonify({"success": False, "error": "Tracker-Token ist ungültig."}), 401)

    if not user_has_tracker_access(user_doc):
        return None, client_token, (jsonify({"success": False, "error": "Tracker-Zugriff ist deaktiviert oder Fahrer-Registrierung ist nicht freigegeben."}), 403)

    return user_doc, client_token, None


def tracker_allowed_driver_card_file(filename):
    filename = safe_str(filename).lower()
    return "." in filename and filename.rsplit(".", 1)[1] in ALLOWED_TRACKER_DRIVER_CARD_EXTENSIONS


def tracker_driver_card_upload_relative_path(filename):
    filename = safe_str(filename)
    return os.path.join(TRACKER_DRIVER_CARD_UPLOAD_FOLDER, filename).replace("\\", "/")


def tracker_public_file_url(relative_path):
    relative_path = safe_str(relative_path).replace("\\", "/")
    if not relative_path:
        return ""
    if relative_path.startswith("http://") or relative_path.startswith("https://"):
        return relative_path
    return make_external_url(relative_path)


def tracker_first_user_value(user_doc, *keys, fallback=""):
    user_doc = user_doc or {}
    for key in keys:
        value = safe_str(user_doc.get(key))
        if value:
            return value
    return fallback


def tracker_latest_issued_fahrerkarte_request(user_doc):
    user_doc = user_doc or {}
    discord_id = safe_str(user_doc.get("discord_id"))
    if not discord_id:
        return None

    request_doc = get_latest_fahrerkarte_request_for_user(discord_id)
    if not request_doc:
        return None

    status = normalize_fahrerkarte_status(request_doc.get("status"))
    if status not in {"approved", "issued"}:
        return None

    return request_doc


def tracker_build_driver_card_doc(user_doc, source_request=None, source="tracker_upload", extra=None):
    user_doc = user_doc or {}
    source_request = source_request or {}
    extra = extra or {}

    now = now_utc()
    discord_id = safe_str(user_doc.get("discord_id") or user_doc.get("user_id") or user_doc.get("id"))
    display_name = (
        safe_str(extra.get("driverName"))
        or safe_str(source_request.get("display_name") or source_request.get("full_name") or source_request.get("name"))
        or safe_str(user_doc.get("display_name") or user_doc.get("username") or user_doc.get("discord_username"))
        or "EifelLog Fahrer"
    )
    role_name = (
        safe_str(extra.get("role"))
        or safe_str(source_request.get("role") or source_request.get("role_name"))
        or get_primary_role_name(user_doc.get("roles", []))
        or "Fahrer"
    )
    personal_number = (
        safe_str(extra.get("personalNumber"))
        or safe_str(source_request.get("driver_number") or source_request.get("system_id"))
        or tracker_first_user_value(user_doc, "driver_number", "fahrernummer", "employee_number", "personal_number", "discord_id", fallback="-")
    )
    birth_date = (
        safe_str(extra.get("birthDate"))
        or tracker_first_user_value(user_doc, "birth_date", "birthDate", "date_of_birth", "dob", fallback="")
    )
    if not birth_date:
        created_at = user_doc.get("created_at")
        birth_date = created_at.strftime("%d.%m.%Y") if isinstance(created_at, datetime) else now.strftime("%d.%m.%Y")

    card_id = (
        safe_str(extra.get("cardId") or extra.get("card_id"))
        or safe_str(source_request.get("card_id") or source_request.get("fahrerkarte_card_id"))
        or tracker_first_user_value(user_doc, "fahrerkarte_card_id", "personalisierte_fahrerkarte_card_id", "driver_card_id", "card_id", fallback="")
    )
    if not card_id:
        card_id = generate_fahrerkarte_card_id(discord_id, safe_str(source_request.get("request_id")))

    file_relative_path = safe_str(
        extra.get("fileRelativePath")
        or extra.get("file_relative_path")
        or source_request.get("pdf_relative_path")
        or source_request.get("pdf_path")
    )
    file_name = safe_str(
        extra.get("fileName")
        or extra.get("filename")
        or source_request.get("pdf_filename")
        or "fahrerkarte.pdf"
    )
    download_url = (
        safe_str(extra.get("downloadUrl") or extra.get("download_url"))
        or (servicecenter_fahrerkarte_download_url(source_request.get("request_id")) if source_request.get("request_id") else "")
        or tracker_public_file_url(file_relative_path)
    )

    request_id = safe_str(source_request.get("request_id") or source_request.get("_id"))
    doc = {
        "card_id": card_id,
        "discord_id": discord_id,
        "user_id": discord_id,
        "user_mongo_id": safe_str(user_doc.get("_id")),
        "username": user_doc.get("username") or user_doc.get("discord_username"),
        "discord_username": user_doc.get("discord_username") or user_doc.get("username"),
        "driver_name": display_name,
        "display_name": display_name,
        "name": display_name,
        "role": role_name,
        "role_name": role_name,
        "personal_number": personal_number,
        "driver_number": personal_number,
        "birth_date": birth_date,
        "department": safe_str(extra.get("department") or source_request.get("department"), "Web-ServiceCenter"),
        "status": safe_str(extra.get("status") or source_request.get("status"), "Aktiv"),
        "state": "Aktiv",
        "card_number": card_id,
        "card_type": safe_str(extra.get("cardType") or extra.get("type"), "Digitale Ausgabe"),
        "signature": safe_str(extra.get("signature") or display_name),
        "tag": safe_str(extra.get("tag"), "INTERN"),
        "file_name": file_name,
        "original_filename": safe_str(extra.get("originalFilename") or file_name),
        "file_relative_path": file_relative_path,
        "pdf_relative_path": file_relative_path,
        "download_url": download_url,
        "source": source,
        "source_request_id": request_id,
        "synced": True,
        "active": True,
        "archived": False,
        "uploaded_at": extra.get("uploadedAt") if isinstance(extra.get("uploadedAt"), datetime) else now,
        "created_at": extra.get("createdAt") if isinstance(extra.get("createdAt"), datetime) else now,
        "updated_at": now,
    }

    return doc


def tracker_prepare_driver_card_payload(card_doc=None, user_doc=None):
    if not card_doc:
        return None

    card_id = safe_str(card_doc.get("card_id") or card_doc.get("cardId") or card_doc.get("card_number"))
    driver_name = safe_str(card_doc.get("driver_name") or card_doc.get("display_name") or card_doc.get("name"), "EifelLog Fahrer")
    file_relative_path = safe_str(card_doc.get("file_relative_path") or card_doc.get("pdf_relative_path") or card_doc.get("pdf_path"))
    download_url = safe_str(card_doc.get("download_url")) or tracker_public_file_url(file_relative_path)
    created_at = card_doc.get("created_at") or card_doc.get("uploaded_at")
    updated_at = card_doc.get("updated_at") or created_at

    return {
        "id": safe_str(card_doc.get("_id")) or card_id,
        "_id": safe_str(card_doc.get("_id")) or card_id,
        "cardId": card_id,
        "card_id": card_id,
        "driverCardId": card_id,
        "driverName": driver_name,
        "name": driver_name,
        "displayName": driver_name,
        "username": card_doc.get("username") or (user_doc or {}).get("username"),
        "role": safe_str(card_doc.get("role") or card_doc.get("role_name"), "Fahrer"),
        "position": safe_str(card_doc.get("role") or card_doc.get("role_name"), "Fahrer"),
        "personalNumber": safe_str(card_doc.get("personal_number") or card_doc.get("driver_number"), "-"),
        "driverNumber": safe_str(card_doc.get("driver_number") or card_doc.get("personal_number"), "-"),
        "employeeNumber": safe_str(card_doc.get("personal_number") or card_doc.get("driver_number"), "-"),
        "birthDate": safe_str(card_doc.get("birth_date"), "-"),
        "dateOfBirth": safe_str(card_doc.get("birth_date"), "-"),
        "department": safe_str(card_doc.get("department"), "Web-ServiceCenter"),
        "issueDepartment": safe_str(card_doc.get("department"), "Web-ServiceCenter"),
        "status": "Aktiv" if safe_str(card_doc.get("status")).lower() in {"issued", "approved", "aktiv", "active"} else safe_str(card_doc.get("status"), "Aktiv"),
        "state": "Aktiv",
        "cardNumber": safe_str(card_doc.get("card_number") or card_id, card_id),
        "licenseNumber": safe_str(card_doc.get("card_number") or card_id, card_id),
        "driverCardNumber": safe_str(card_doc.get("card_number") or card_id, card_id),
        "cardType": safe_str(card_doc.get("card_type"), "Digitale Ausgabe"),
        "type": safe_str(card_doc.get("card_type"), "Digitale Ausgabe"),
        "signature": safe_str(card_doc.get("signature"), driver_name),
        "tag": safe_str(card_doc.get("tag"), "INTERN"),
        "fileName": safe_str(card_doc.get("file_name") or card_doc.get("original_filename"), "fahrerkarte.pdf"),
        "filename": safe_str(card_doc.get("file_name") or card_doc.get("original_filename"), "fahrerkarte.pdf"),
        "downloadUrl": download_url,
        "download_url": download_url,
        "uploadedAt": datetime_to_iso(card_doc.get("uploaded_at") or created_at),
        "createdAt": datetime_to_iso(created_at),
        "updatedAt": datetime_to_iso(updated_at),
        "synced": True,
    }


def tracker_get_latest_driver_card_doc(user_doc, create_from_servicecenter=True):
    user_doc = user_doc or {}
    discord_id = safe_str(user_doc.get("discord_id"))
    if not discord_id:
        return None

    card_doc = tracker_driver_cards_collection.find_one(
        {"discord_id": discord_id, "archived": {"$ne": True}},
        sort=[("updated_at", DESCENDING), ("created_at", DESCENDING)]
    )
    if card_doc:
        return card_doc

    if not create_from_servicecenter:
        return None

    source_request = tracker_latest_issued_fahrerkarte_request(user_doc)
    if not source_request:
        return None

    card_doc = tracker_build_driver_card_doc(user_doc, source_request=source_request, source="servicecenter_issue")
    tracker_driver_cards_collection.update_one(
        {"discord_id": discord_id, "card_id": card_doc["card_id"]},
        {"$set": card_doc, "$setOnInsert": {"created_at": card_doc["created_at"]}},
        upsert=True
    )
    return tracker_driver_cards_collection.find_one({"discord_id": discord_id, "card_id": card_doc["card_id"]})


def tracker_default_work_session():
    now_ms = int(now_utc().timestamp() * 1000)
    return {
        "status": "offDuty",
        "workMs": 0,
        "driveMs": 0,
        "breakMs": 0,
        "restMs": 11 * 60 * 60 * 1000,
        "weeklyRestMs": 45 * 60 * 60 * 1000,
        "continuousDriveMs": 0,
        "currentBreakMs": 0,
        "splitBreakFirstMs": 0,
        "reducedDailyRestUsed": 0,
        "weeklyRestDue": False,
        "shiftStartedAt": None,
        "lastShiftEndedAt": now_ms,
        "updatedAt": now_ms,
    }


def tracker_ms(value, fallback=0):
    try:
        number = float(value)
        if number < 0:
            return fallback
        return int(number)
    except Exception:
        return fallback


def tracker_normalize_work_session(raw=None, previous=None):
    previous = previous or tracker_default_work_session()
    raw = raw or {}

    status = safe_str(raw.get("status") or previous.get("status"), "offDuty")
    if status not in {"working", "pause", "offDuty"}:
        status = "offDuty"

    normalized = dict(previous)
    normalized.update({
        "status": status,
        "workMs": tracker_ms(raw.get("workMs"), tracker_ms(previous.get("workMs"), 0)),
        "driveMs": tracker_ms(raw.get("driveMs"), tracker_ms(previous.get("driveMs"), 0)),
        "breakMs": tracker_ms(raw.get("breakMs"), tracker_ms(previous.get("breakMs"), 0)),
        "restMs": tracker_ms(raw.get("restMs"), tracker_ms(previous.get("restMs"), 0)),
        "weeklyRestMs": tracker_ms(raw.get("weeklyRestMs"), tracker_ms(previous.get("weeklyRestMs"), 0)),
        "continuousDriveMs": tracker_ms(raw.get("continuousDriveMs"), tracker_ms(previous.get("continuousDriveMs"), 0)),
        "currentBreakMs": tracker_ms(raw.get("currentBreakMs"), tracker_ms(previous.get("currentBreakMs"), 0)),
        "splitBreakFirstMs": tracker_ms(raw.get("splitBreakFirstMs"), tracker_ms(previous.get("splitBreakFirstMs"), 0)),
        "reducedDailyRestUsed": tracker_ms(raw.get("reducedDailyRestUsed"), tracker_ms(previous.get("reducedDailyRestUsed"), 0)),
        "weeklyRestDue": bool_from_payload(raw.get("weeklyRestDue"), fallback=bool(previous.get("weeklyRestDue", False))),
        "shiftStartedAt": raw.get("shiftStartedAt") if raw.get("shiftStartedAt") not in ["", None] else previous.get("shiftStartedAt"),
        "lastShiftEndedAt": raw.get("lastShiftEndedAt") if raw.get("lastShiftEndedAt") not in ["", None] else previous.get("lastShiftEndedAt"),
        "updatedAt": tracker_ms(raw.get("updatedAt"), int(now_utc().timestamp() * 1000)),
    })

    return normalized


def tracker_get_latest_work_session_doc(user_doc):
    user_doc = user_doc or {}
    discord_id = safe_str(user_doc.get("discord_id"))
    if not discord_id:
        return None
    return tracker_work_sessions_collection.find_one(
        {"discord_id": discord_id},
        sort=[("updated_at", DESCENDING), ("created_at", DESCENDING)]
    )


def tracker_prepare_work_session_payload(session_doc_or_raw=None):
    if not session_doc_or_raw:
        return tracker_default_work_session()
    if "work_session" in session_doc_or_raw:
        return tracker_normalize_work_session(session_doc_or_raw.get("work_session") or {})
    return tracker_normalize_work_session(session_doc_or_raw)


def tracker_save_work_session(user_doc, raw_session, driver_card_id=""):
    user_doc = user_doc or {}
    discord_id = safe_str(user_doc.get("discord_id"))
    previous_doc = tracker_get_latest_work_session_doc(user_doc)
    previous_session = tracker_prepare_work_session_payload(previous_doc) if previous_doc else tracker_default_work_session()
    work_session = tracker_normalize_work_session(raw_session, previous_session)
    now = now_utc()

    doc = {
        "discord_id": discord_id,
        "user_id": discord_id,
        "user_mongo_id": safe_str(user_doc.get("_id")),
        "username": user_doc.get("username") or user_doc.get("discord_username"),
        "display_name": user_doc.get("display_name") or user_doc.get("username") or user_doc.get("discord_username"),
        "driver_card_id": safe_str(driver_card_id),
        "status": work_session.get("status"),
        "work_session": work_session,
        "updated_at": now,
    }

    tracker_work_sessions_collection.update_one(
        {"discord_id": discord_id},
        {"$set": doc, "$setOnInsert": {"created_at": now}},
        upsert=True
    )

    users_collection.update_one(
        {"_id": user_doc["_id"]},
        {"$set": {
            "tracker_work_session": work_session,
            "tracker_work_session_updated_at": now,
            "tracker_work_status": work_session.get("status"),
        }}
    )

    return tracker_work_sessions_collection.find_one({"discord_id": discord_id})


def tracker_effective_break_ms(work_session):
    work_session = work_session or {}
    current_break = tracker_ms(work_session.get("currentBreakMs"), 0) if work_session.get("status") == "pause" else 0
    split_first = tracker_ms(work_session.get("splitBreakFirstMs"), 0)

    if current_break >= 45 * 60 * 1000:
        return current_break

    if split_first >= 15 * 60 * 1000 and current_break >= 30 * 60 * 1000:
        return split_first + current_break

    return max(current_break, split_first)


def tracker_validate_job_requirements(user_doc, driver_card_doc, work_session):
    work_session = tracker_normalize_work_session(work_session)
    issues = []

    daily_drive_limit_ms = 8 * 60 * 60 * 1000
    continuous_drive_limit_ms = int(4.5 * 60 * 60 * 1000)
    daily_rest_ms = 11 * 60 * 60 * 1000
    reduced_daily_rest_ms = 9 * 60 * 60 * 1000
    weekly_rest_ms = 45 * 60 * 60 * 1000
    effective_break_ms = tracker_effective_break_ms(work_session)

    if not driver_card_doc:
        issues.append("Fahrerkarte fehlt oder wurde nicht aus der Datenbank geladen.")
    elif not bool(driver_card_doc.get("active", True)) or safe_str(driver_card_doc.get("status")).lower() in {"inactive", "gesperrt", "blocked", "archived"}:
        issues.append("Fahrerkarte ist nicht aktiv.")

    if work_session.get("status") != "working":
        issues.append("Arbeitszeit ist nicht aktiv.")

    if tracker_ms(work_session.get("driveMs"), 0) >= daily_drive_limit_ms:
        issues.append("8 Stunden Lenkzeit sind erreicht.")

    if tracker_ms(work_session.get("continuousDriveMs"), 0) >= continuous_drive_limit_ms and effective_break_ms < 45 * 60 * 1000:
        issues.append("Nach 4,5 Stunden Lenkzeit muss eine Pause von mindestens 45 Minuten eingelegt werden. Diese kann in 15 + 30 Minuten aufgeteilt werden.")

    if tracker_ms(work_session.get("restMs"), 0) < daily_rest_ms:
        reduced_ok = (
            tracker_ms(work_session.get("restMs"), 0) >= reduced_daily_rest_ms
            and tracker_ms(work_session.get("reducedDailyRestUsed"), 0) < 3
        )
        new_shift_after_rest = bool(work_session.get("lastShiftEndedAt")) and work_session.get("status") == "working" and tracker_ms(work_session.get("workMs"), 0) < 60000
        if not reduced_ok and new_shift_after_rest:
            issues.append("Tägliche Ruhezeit von mindestens 11 Stunden ist nicht erfüllt. Dreimal pro Woche sind 9 Stunden zulässig.")

    if bool(work_session.get("weeklyRestDue", False)) and tracker_ms(work_session.get("weeklyRestMs"), 0) < weekly_rest_ms:
        issues.append("Wöchentliche Ruhezeit von regulär 45 Stunden ist fällig und nicht erfüllt.")

    return {
        "allowed": len(issues) == 0,
        "issues": issues,
        "remainingDriveMs": max(0, daily_drive_limit_ms - tracker_ms(work_session.get("driveMs"), 0)),
        "nextBreakInMs": max(0, continuous_drive_limit_ms - tracker_ms(work_session.get("continuousDriveMs"), 0)),
        "effectiveBreakMs": effective_break_ms,
        "limits": {
            "dailyDriveMs": daily_drive_limit_ms,
            "continuousDriveMs": continuous_drive_limit_ms,
            "dailyRestMs": daily_rest_ms,
            "reducedDailyRestMs": reduced_daily_rest_ms,
            "weeklyRestMs": weekly_rest_ms,
        },
    }


def tracker_job_id_from_payload(payload, telemetry=None):
    payload = payload or {}
    telemetry = telemetry or {}
    job_id = (
        safe_str(payload.get("jobId") or payload.get("job_id"))
        or safe_str(telemetry.get("jobId") or telemetry.get("job_id") or telemetry.get("deliveryId") or telemetry.get("delivery_id"))
    )
    if not job_id:
        seed = f"{safe_str(telemetry.get('sourceCity'))}|{safe_str(telemetry.get('destinationCity'))}|{safe_str(telemetry.get('cargo'))}|{now_utc().isoformat()}|{uuid.uuid4().hex}"
        job_id = "EL-JOB-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12].upper()
    return job_id


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
        "cargo": s("cargo", "cargoName", "freight", "jobCargo", fallback="-"),
        "jobId": s("jobId", "job_id", "id", "deliveryId", "delivery_id", fallback=""),
        "eta": s("eta", "etaText", "eta_text", "remainingTime", "navigationTime", fallback="-"),
        "speedKmh": n("speedKmh", "speed", fallback=0),
        "rpm": n("rpm", "engineRpm", "engineRPM", fallback=0),
        "fuelPercent": n("fuelPercent", "fuel", "tankPercent", "fuel_percent", fallback=0),
        "fuelLiters": n("fuelLiters", "fuel_liters", "fuelUsed", fallback=-1),
        "damagePercent": n("damagePercent", "damage", fallback=0),
        "completedDistanceKm": n("completedDistanceKm", "drivenDistanceKm", "distanceKm", "routeDistanceKm", fallback=0),
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
        "jobId": safe_str(live.get("jobId")),
        "sourceCity": source,
        "destinationCity": destination,
        "cargo": cargo,
        "truck": live.get("truck") or "-",
        "fuelPercent": parse_number(live.get("fuelPercent"), 0),
        "fuelLiters": parse_number(live.get("fuelLiters"), -1),
        "eta": live.get("eta") or "-",
        "rpm": parse_number(live.get("rpm"), 0),
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
    # Company-All-Time kommt aus einem eigenen MongoDB-Eintrag
    # und nicht aus tracker_live / tracker_last_trip_distance_km.
    users = list(users_collection.find({}))
    persistent_stats = get_company_all_time_stats()

    company_km = positive_number(persistent_stats.get("all_time_km") or persistent_stats.get("allTimeKilometers"), 0.0)
    company_income = positive_number(persistent_stats.get("all_time_income") or persistent_stats.get("companyIncome"), 0.0)
    jobs_all_time = parse_int(persistent_stats.get("jobs_all_time"), 0)
    deliveries = parse_int(persistent_stats.get("deliveries_all_time"), 0)

    # Fallback für alte Datenbanken ohne tour_receipts/company_stats.
    # Auch hier werden nur gespeicherte All-Time-Felder gelesen, keine Live-Trip-Werte.
    if company_km <= 0 and company_income <= 0 and jobs_all_time <= 0 and deliveries <= 0:
        for user_doc in users:
            stats = get_profile_stats(user_doc)
            company_km += positive_number(stats.get("km"), 0.0)
            company_income += positive_number(stats.get("income") or stats.get("revenue"), 0.0)
            deliveries += parse_int(stats.get("deliveries"), 0)
            jobs_all_time += parse_int(stats.get("jobs"), parse_int(stats.get("deliveries"), 0))

    monthly_kilometers = [0, 0, 0, 0, 0, 0]
    income_series = [0, 0, 0, 0, 0, 0]

    for user_doc in users:
        job_entries = get_user_job_entries(user_doc)
        for job in job_entries:
            distance = positive_number(job.get("distanceKm") or job.get("distance") or job.get("tripDistanceKm"), 0)
            income = positive_number(job.get("income") or job.get("revenue") or job.get("money"), 0)
            monthly_kilometers[-1] += distance
            income_series[-1] += income

    active_driver_count = len(get_active_drivers())

    return {
        "companyIncome": round(company_income),
        "income": round(company_income),
        "revenue": round(company_income),
        "allTimeKilometers": round(company_km, 1),
        "allTimeKm": round(company_km, 1),
        "companyAllTimeKilometers": round(company_km, 1),
        "companyAllTimeKm": round(company_km, 1),
        "kilometers": round(company_km, 1),
        "jobsAllTime": jobs_all_time,
        "jobs": jobs_all_time,
        "totalJobs": jobs_all_time,
        "deliveries": deliveries,
        "totalDeliveries": deliveries,
        "activeDrivers": active_driver_count,
        "monthlyKilometers": [round(value, 1) for value in monthly_kilometers],
        "incomeSeries": [round(value, 2) for value in income_series],
        "databaseEntryId": COMPANY_STATS_DOCUMENT_ID,
        "updatedAt": datetime_to_iso(persistent_stats.get("updated_at"))
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



def dashboard_number(value, fallback=0.0):
    return parse_number(value, fallback)


def dashboard_int(value, fallback=0):
    return parse_int(value, fallback)


def calculate_driver_level(total_km=0, completed_trips=0, xp_value=None):
    if xp_value is None:
        xp_value = round(parse_number(total_km, 0) * 2 + parse_int(completed_trips, 0) * 50)

    xp = parse_int(xp_value, 0)
    level = max(1, (xp // 1000) + 1)
    progress = max(0, min(100, round((xp % 1000) / 10)))
    return level, xp, progress


def get_user_logbook_entries_for_dashboard(user_doc, limit=10):
    user_doc = user_doc or {}
    entries = []

    for raw_entry in get_user_job_entries(user_doc):
        if not isinstance(raw_entry, dict):
            continue

        normalized = normalize_logbook_entry(raw_entry, user_doc)
        created_at_raw = raw_entry.get("createdAt") or raw_entry.get("created_at") or raw_entry.get("finishedAt") or raw_entry.get("submitted_at") or raw_entry.get("timestamp")
        date_text = "-"

        if isinstance(created_at_raw, datetime):
            date_text = created_at_raw.strftime("%d.%m.%Y")
            sort_date = created_at_raw
        else:
            created_at_text = safe_str(created_at_raw)
            sort_date = normalized.get("_sortDate") or datetime.min
            if created_at_text:
                try:
                    iso_text = created_at_text.replace("Z", "+00:00")
                    parsed_date = datetime.fromisoformat(iso_text)
                    date_text = parsed_date.strftime("%d.%m.%Y")
                    sort_date = parsed_date.replace(tzinfo=None)
                except Exception:
                    date_text = created_at_text[:10] if len(created_at_text) >= 10 else created_at_text

        entries.append({
            "date": date_text,
            "route": normalized.get("route") or "-",
            "from_city": normalized.get("sourceCity") or "-",
            "to_city": normalized.get("destinationCity") or "-",
            "cargo": normalized.get("cargo") or "-",
            "distance": round(parse_number(normalized.get("distanceKm"), 0), 1),
            "earnings": round(parse_number(normalized.get("income"), 0), 2),
            "status": normalized.get("status") or "Abgeschlossen",
            "_sortDate": sort_date
        })

    entries.sort(key=lambda item: item.get("_sortDate") or datetime.min, reverse=True)

    cleaned = []
    for entry in entries[:limit]:
        entry.pop("_sortDate", None)
        cleaned.append(entry)
    return cleaned


def get_driver_current_trip_for_dashboard(user_doc):
    user_doc = user_doc or {}
    live = user_doc.get("tracker_live") or {}
    current_job = user_doc.get("tracker_current_job") or current_job_from_live(live)

    if not current_job:
        return {}

    source = safe_str(current_job.get("sourceCity") or live.get("sourceCity"), "-")
    destination = safe_str(current_job.get("destinationCity") or live.get("destinationCity"), "-")
    cargo = safe_str(current_job.get("cargo") or live.get("cargo"), "-")

    if source == "-" and destination == "-" and cargo == "-":
        return {}

    progress = parse_number(live.get("routeProgressPercent"), 0)
    if progress <= 0:
        planned = parse_number(live.get("plannedDistanceKm") or current_job.get("distanceKm"), 0)
        remaining = parse_number(live.get("remainingDistanceKm") or current_job.get("remainingDistanceKm"), 0)
        if planned > 0:
            progress = max(0, min(100, round(((planned - remaining) / planned) * 100)))

    trip_distance = parse_number(live.get("tripDistanceKm") or user_doc.get("tracker_last_trip_distance_km"), 0)
    expected_earnings = parse_number(current_job.get("income"), 0)
    if expected_earnings <= 0:
        expected_earnings = round(trip_distance * TOUR_RECEIPT_RATE_PER_KM, 2)

    updated_at = user_doc.get("tracker_live_updated_at")
    departure = "-"
    if isinstance(updated_at, datetime):
        departure = updated_at.strftime("%H:%M")

    return {
        "from_city": source,
        "to_city": destination,
        "departure": departure,
        "progress": round(max(0, min(100, progress))),
        "cargo": cargo,
        "distance": round(trip_distance, 1),
        "remaining_distance": round(parse_number(live.get("remainingDistanceKm"), 0), 1),
        "expected_earnings": round(expected_earnings, 2),
        "status": safe_str(current_job.get("status"), "Aktiv" if user_doc.get("tracker_online") else "Warte")
    }


def prepare_driver_dashboard_context(user_doc):
    user_doc = user_doc or {}
    stats = get_profile_stats(user_doc)
    fahrtenbuch_entries = get_user_logbook_entries_for_dashboard(user_doc, limit=12)

    completed_km = parse_number(stats.get("km"), 0)
    completed_income = parse_number(stats.get("income") or stats.get("revenue"), 0)
    completed_trips = parse_int(stats.get("deliveries"), 0)
    if completed_trips <= 0:
        completed_trips = len(fahrtenbuch_entries)

    live = user_doc.get("tracker_live") or {}
    live_updated_at = user_doc.get("tracker_live_updated_at")
    live_is_fresh = isinstance(live_updated_at, datetime) and live_updated_at >= now_utc() - timedelta(minutes=5)
    live_distance = parse_number(live.get("tripDistanceKm") or user_doc.get("tracker_last_trip_distance_km"), 0) if live_is_fresh else 0

    total_km = completed_km + live_distance

    balance = parse_number(
        user_doc.get("balance")
        or user_doc.get("konto_stand")
        or user_doc.get("kontostand")
        or user_doc.get("account_balance")
        or user_doc.get("profile_balance")
        or completed_income,
        completed_income
    )

    stored_xp = user_doc.get("driver_xp") or user_doc.get("fahrer_xp") or user_doc.get("xp")
    stored_level = user_doc.get("driver_level") or user_doc.get("fahrer_level") or user_doc.get("level")
    calculated_level, xp, level_progress = calculate_driver_level(total_km, completed_trips, stored_xp)

    driver_level = stored_level if stored_level not in [None, ""] else calculated_level

    driver_stats = {
        "total_km": round(total_km, 1),
        "completed_km": round(completed_km, 1),
        "last_trip_distance": round(parse_number(user_doc.get("tracker_last_trip_distance_km") or live.get("tripDistanceKm"), 0), 1),
        "balance": round(balance, 2),
        "completed_trips": completed_trips,
        "level": driver_level,
        "xp": xp,
        "level_progress": level_progress,
        "online": bool(user_doc.get("tracker_online", False) and live_is_fresh),
        "last_update": format_datetime_for_template(live_updated_at)
    }

    return {
        "driver_stats": driver_stats,
        "fahrtenbuch_entries": fahrtenbuch_entries,
        "driver_current_trip": get_driver_current_trip_for_dashboard(user_doc)
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


def payload_lookup_value(payload, *keys, fallback=""):
    payload = payload or {}
    for key in keys:
        value = payload.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return fallback


def format_fuel_display_from_payload(payload):
    payload = payload or {}
    fuel_liters = parse_number(
        payload.get("fuelLiters")
        or payload.get("fuel_liters")
        or payload.get("fuelUsed"),
        -1
    )
    fuel_percent = parse_number(
        payload.get("fuelPercent")
        or payload.get("fuel_percent")
        or payload.get("tankPercent")
        or payload.get("fuel"),
        -1
    )

    if fuel_liters >= 0:
        return format_liters(fuel_liters)
    if fuel_percent >= 0:
        return format_percent(fuel_percent)
    return "-"


def resolve_driver_card_id(user_doc=None, payload=None):
    payload = payload or {}
    for key in (
        "fahrerkarteId", "fahrerkarte_id", "fahrerkarteID",
        "driverCardId", "driver_card_id", "cardId", "card_id",
        "tachographCardId", "tachograph_card_id"
    ):
        value = safe_str(payload.get(key))
        if value:
            return value

    user_doc = user_doc or {}
    for key in (
        "fahrerkarte_card_id", "personalisierte_fahrerkarte_card_id",
        "driver_card_id", "card_id", "fahrerkarte_id"
    ):
        value = safe_str(user_doc.get(key))
        if value:
            return value

    discord_id = safe_str(user_doc.get("discord_id") or user_doc.get("user_id") or user_doc.get("id"))
    if discord_id:
        try:
            latest_request = fahrerkarte_requests_collection.find_one(
                {"discord_id": discord_id, "archived": {"$ne": True}},
                sort=[("created_at", DESCENDING)]
            ) or {}
            for key in ("card_id", "fahrerkarte_card_id", "driver_card_id"):
                value = safe_str(latest_request.get(key))
                if value:
                    return value
        except Exception as error:
            print(f"Fahrerkarte-ID konnte nicht aufgeloest werden: {error}")

    return "-"


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
        ("Fahrerkarte-ID", driver.get("fahrerkarte_id")),
    ]))

    tour = receipt_doc.get("tour") or {}
    sections.append(("Tourdaten", [
        ("Spiel", tour.get("game")),
        ("Truck", tour.get("truck")),
        ("Start", tour.get("source_city")),
        ("Ziel", tour.get("destination_city")),
        ("Fracht", tour.get("cargo")),
        ("Kraftstoff", format_fuel_display_from_payload(tour)),
        ("ETA", tour.get("eta")),
        ("RPM", str(parse_int(tour.get("rpm"), 0))),
        ("Geplante Distanz", format_km(tour.get("planned_distance_km"))),
        ("Gefahrene Distanz", format_km(tour.get("driven_distance_km"))),
        ("Restdistanz", format_km(tour.get("remaining_distance_km"))),
        ("Fortschritt", format_percent(tour.get("route_progress_percent"))),
        ("Schaden", format_percent(tour.get("damage_percent"))),
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


def discord_payload_for_bot(payload):
    payload = dict(payload or {})
    # username/avatar_url sind Webhook-Felder und werden von Bot-Channel-Messages nicht akzeptiert.
    payload.pop("username", None)
    payload.pop("avatar_url", None)
    return payload


def discord_wait_url(url):
    url = safe_str(url)
    if not url:
        return ""
    if "?" not in url:
        return url + "?wait=true"
    if "wait=" not in url:
        return url + "&wait=true"
    return url


def post_discord_json_to_tour_channel(discord_payload, channel_id=None, webhook_url=None):
    channel_id = safe_str(channel_id or TOUR_CHANNEL_ID or TOUR_RECEIPT_CHANNEL_ID)
    webhook_url = safe_str(webhook_url or DISCORD_TOUR_WEBHOOK_URL or DISCORD_JOB_COMPLETE_WEBHOOK_URL)

    if DISCORD_BOT_TOKEN and channel_id:
        try:
            response = requests.post(
                f"https://discord.com/api/v10/channels/{channel_id}/messages",
                headers={"Authorization": f"Bot {DISCORD_BOT_TOKEN}", "Content-Type": "application/json"},
                json=discord_payload_for_bot(discord_payload),
                timeout=20
            )
        except Exception as error:
            return {"sent": False, "method": "bot", "channel_id": channel_id, "error": str(error)}

        if response.status_code not in range(200, 300):
            return {
                "sent": False,
                "method": "bot",
                "channel_id": channel_id,
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

    if webhook_url:
        try:
            response = requests.post(discord_wait_url(webhook_url), json=discord_payload, timeout=20)
        except Exception as error:
            return {"sent": False, "method": "webhook", "error": str(error)}

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
            "channel_id": message.get("channel_id") or channel_id,
            "message_id": message.get("id"),
            "raw": message
        }

    return {"sent": False, "reason": "Kein DISCORD_BOT_TOKEN/TOUR_CHANNEL_ID oder DISCORD_TOUR_WEBHOOK_URL konfiguriert."}


def post_discord_file_to_tour_channel(discord_payload, file_tuple, channel_id=None, webhook_url=None):
    channel_id = safe_str(channel_id or TOUR_RECEIPT_CHANNEL_ID or TOUR_CHANNEL_ID)
    webhook_url = safe_str(webhook_url or DISCORD_TOUR_WEBHOOK_URL or DISCORD_JOB_COMPLETE_WEBHOOK_URL)
    filename, file_bytes, content_type = file_tuple

    if DISCORD_BOT_TOKEN and channel_id:
        try:
            response = requests.post(
                f"https://discord.com/api/v10/channels/{channel_id}/messages",
                headers={"Authorization": f"Bot {DISCORD_BOT_TOKEN}"},
                data={"payload_json": json.dumps(discord_payload_for_bot(discord_payload), ensure_ascii=False)},
                files={"files[0]": (filename, file_bytes, content_type)},
                timeout=25
            )
        except Exception as error:
            return {"sent": False, "method": "bot", "channel_id": channel_id, "error": str(error)}

        if response.status_code not in range(200, 300):
            return {
                "sent": False,
                "method": "bot",
                "channel_id": channel_id,
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

    if webhook_url:
        try:
            response = requests.post(
                discord_wait_url(webhook_url),
                data={"payload_json": json.dumps(discord_payload, ensure_ascii=False)},
                files={"files[0]": (filename, file_bytes, content_type)},
                timeout=25
            )
        except Exception as error:
            return {"sent": False, "method": "webhook", "error": str(error)}

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
            "channel_id": message.get("channel_id") or channel_id,
            "message_id": message.get("id"),
            "raw": message
        }

    return {"sent": False, "reason": "Kein DISCORD_BOT_TOKEN/TOUR_CHANNEL_ID oder DISCORD_TOUR_WEBHOOK_URL konfiguriert."}


def send_receipt_to_discord(receipt_doc, pdf_bytes, filename):
    if not TOUR_RECEIPT_DISCORD_ENABLED:
        return {"sent": False, "reason": "TOUR_RECEIPT_DISCORD_ENABLED=false"}

    driver = receipt_doc.get("driver") or {}
    tour = receipt_doc.get("tour") or {}
    billing = receipt_doc.get("billing") or {}

    payload = {
        "username": "EifelLog Tracker",
        "allowed_mentions": {"parse": []},
        "embeds": [
            {
                "title": "🧾 Tour-Beleg eingereicht",
                "description": "Der Job wurde abgeschlossen. Der PDF-Beleg ist angehängt und für die Buchhaltung relevant.",
                "color": 5763719,
                "fields": [
                    {"name": "👤 Fahrer", "value": safe_str(driver.get("name"), "-"), "inline": True},
                    {"name": "🪪 Fahrerkarte-ID", "value": safe_str(driver.get("fahrerkarte_id"), "-"), "inline": True},
                    {"name": "🧾 Job-ID", "value": f"`{safe_str(receipt_doc.get('job_id'), '-')}`", "inline": True},

                    {"name": "🚛 LKW", "value": safe_str(tour.get("truck"), "-"), "inline": True},
                    {"name": "📦 Fracht", "value": safe_str(tour.get("cargo"), "-"), "inline": True},
                    {"name": "⛽ Kraftstoff", "value": format_fuel_display_from_payload(tour), "inline": True},

                    {"name": "📍 Von", "value": safe_str(tour.get("source_city"), "-"), "inline": True},
                    {"name": "🏁 Nach", "value": safe_str(tour.get("destination_city"), "-"), "inline": True},
                    {"name": "⚙️ RPM", "value": str(parse_int(tour.get("rpm"), 0)), "inline": True},

                    {"name": "🕒 ETA", "value": safe_str(tour.get("eta"), "-"), "inline": True},
                    {"name": "📊 Strecke", "value": format_km(tour.get("driven_distance_km")), "inline": True},
                    {"name": "💶 Abrechnung", "value": format_money(billing.get("total_amount"), billing.get("currency")), "inline": True},

                    {"name": "📄 Belegnummer", "value": f"`{safe_str(receipt_doc.get('receipt_number'), '-')}`", "inline": True},
                    {"name": "🏦 Buchhaltung", "value": "Ja – abrechnungsrelevant", "inline": True}
                ],
                "footer": {"text": f"{TOUR_RECEIPT_COMPANY_NAME} • Touren-Channel"},
                "timestamp": now_utc().isoformat() + "Z"
            }
        ],
        "attachments": [
            {
                "id": 0,
                "filename": filename,
                "description": f"Tour-Beleg {receipt_doc.get('receipt_number')}"
            }
        ]
    }

    return post_discord_file_to_tour_channel(
        payload,
        (filename, pdf_bytes, "application/pdf"),
        channel_id=TOUR_RECEIPT_CHANNEL_ID,
        webhook_url=DISCORD_TOUR_WEBHOOK_URL or DISCORD_JOB_COMPLETE_WEBHOOK_URL
    )

def build_tour_receipt_doc(user_doc, payload, telemetry=None):
    telemetry = telemetry or {}
    submitted_at = now_utc()

    job_id = (
        safe_str(payload.get("jobId"))
        or safe_str(payload.get("job_id"))
        or safe_str(payload.get("id"))
        or safe_str(payload.get("deliveryId"))
        or safe_str(payload.get("delivery_id"))
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
    cargo = safe_str(
        payload.get("cargo")
        or payload.get("freight")
        or payload.get("cargoName")
        or payload.get("jobCargo")
        or telemetry.get("cargo"),
        "-"
    )
    game = safe_str(payload.get("game") or telemetry.get("game"), "ETS2/ATS")
    truck = safe_str(
        payload.get("truck")
        or payload.get("truckName")
        or payload.get("truckModel")
        or payload.get("truck_model")
        or telemetry.get("truck"),
        "-"
    )
    eta = safe_str(payload.get("eta") or payload.get("etaText") or payload.get("eta_text") or telemetry.get("eta"), "-")
    driver_card_id = resolve_driver_card_id(user_doc, payload) or resolve_driver_card_id(user_doc, telemetry)

    planned_distance = parse_number(
        payload.get("plannedDistanceKm")
        or payload.get("planned_distance_km")
        or payload.get("routeDistanceKm")
        or payload.get("route_distance_km")
        or payload.get("completedDistanceKm")
        or payload.get("completed_distance_km")
        or payload.get("distanceKm")
        or telemetry.get("plannedDistanceKm"),
        0
    )
    driven_distance = parse_number(
        payload.get("completedDistanceKm")
        or payload.get("completed_distance_km")
        or payload.get("drivenDistanceKm")
        or payload.get("driven_distance_km")
        or payload.get("distanceKm")
        or payload.get("distance")
        or payload.get("routeDistanceKm")
        or payload.get("route_distance_km")
        or payload.get("tripDistanceKm")
        or telemetry.get("completedDistanceKm")
        or telemetry.get("drivenDistanceKm")
        or telemetry.get("distanceKm")
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
            "planned_distance_km", "completedDistanceKm", "completed_distance_km", "drivenDistanceKm",
            "driven_distance_km", "routeDistanceKm", "route_distance_km", "distanceKm", "distance",
            "remainingDistanceKm", "ratePerKm", "rate_per_km", "income", "baseAmount", "base_amount", "bonus", "penalty",
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
        "distanceKm": driven_distance,
        "completedDistanceKm": driven_distance,
        "completed_distance_km": driven_distance,
        "income": total_amount,
        "submitted_at": submitted_at,
        "created_at": submitted_at,
        "driver": {
            "name": display_name,
            "username": user_doc.get("username"),
            "discord_id": user_doc.get("discord_id"),
            "role": get_primary_role_name(user_doc.get("roles", [])),
            "fahrerkarte_id": driver_card_id
        },
        "tour": {
            "game": game,
            "truck": truck,
            "source_city": source_city,
            "destination_city": destination_city,
            "cargo": cargo,
            "eta": eta,
            "planned_distance_km": planned_distance,
            "driven_distance_km": driven_distance,
            "remaining_distance_km": remaining_distance,
            "route_progress_percent": parse_number(payload.get("routeProgressPercent") or telemetry.get("routeProgressPercent"), 100),
            "damage_percent": parse_number(payload.get("damagePercent") or telemetry.get("damagePercent"), 0),
            "fuel_percent": parse_number(payload.get("fuelPercent") or telemetry.get("fuelPercent"), 0),
            "fuel_liters": parse_number(payload.get("fuelLiters") or payload.get("fuel_liters") or telemetry.get("fuelLiters"), -1),
            "speed_kmh": parse_number(payload.get("speedKmh") or telemetry.get("speedKmh"), 0),
            "rpm": parse_number(payload.get("rpm") or payload.get("engineRpm") or telemetry.get("rpm"), 0)
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

    distance = get_receipt_distance_km(receipt_doc)
    income = get_receipt_income(receipt_doc)

    new_km = round(get_user_all_time_km(user_doc) + distance, 1)
    new_income = round(get_user_all_time_income(user_doc) + income, 2)

    stats = get_profile_stats(user_doc)
    new_deliveries = parse_int(stats.get("deliveries"), 0) + 1
    new_jobs = parse_int(stats.get("jobs"), new_deliveries - 1) + 1
    now = now_utc()

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
        "completedDistanceKm": distance,
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
                # Kompatible Profil-Felder
                "profile_km": str(new_km),
                "profile_income": str(new_income),
                "profile_revenue": str(new_income),
                "profile_deliveries": str(new_deliveries),
                "profile_jobs": str(new_jobs),

                # Neue persistente All-Time-Felder als echte Zahlen in MongoDB
                "all_time_km": new_km,
                "all_time_income": new_income,
                "all_time_deliveries": new_deliveries,
                "all_time_jobs": new_jobs,
                "profile_all_time_km": new_km,
                "profile_all_time_income": new_income,
                "profile_all_time_deliveries": new_deliveries,
                "profile_all_time_jobs": new_jobs,
                "tracker_all_time_km": new_km,
                "tracker_all_time_income": new_income,
                "tracker_all_time_deliveries": new_deliveries,
                "tracker_all_time_jobs": new_jobs,
                "tracker_all_time_updated_at": now,

                # Last-Trip bleibt separat und überschreibt nicht mehr All-Time
                "tracker_last_completed_distance_km": distance,
                "tracker_last_trip_distance_km": distance,
                "tracker_online": False,
                "tracker_current_job": None,
                "tracker_last_receipt_id": receipt_doc.get("receipt_id"),
                "tracker_last_receipt_number": receipt_doc.get("receipt_number"),
                "tracker_last_job_completed_at": now
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

    # Eigener Company-All-Time-Datenbankeintrag: company_stats/company_all_time
    # wird nach jeder abgeschlossenen Tour aus allen gespeicherten Belegen neu aufgebaut.
    refresh_company_all_time_stats_from_receipts()


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

    fresh_user = users_collection.find_one({"_id": user_doc["_id"]})
    company_all_time = get_company_all_time_stats()

    return jsonify({
        "success": True,
        "message": "Tour wurde vollständig abgegeben, als Job abgeschlossen und als Abrechnung erfasst.",
        "submitted": True,
        "completed": True,
        "billingRelevant": True,
        "allTimeKilometers": round(positive_number(company_all_time.get("all_time_km"), 0), 1),
        "companyAllTimeKilometers": round(positive_number(company_all_time.get("all_time_km"), 0), 1),
        "driverAllTimeKilometers": round(get_user_all_time_km(fresh_user), 1),
        "databaseEntryId": COMPANY_STATS_DOCUMENT_ID,
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
        "state": tracker_state_payload(fresh_user)
    })


# ==========================================
# LOCAL TRACKER WEBHOOK -> DISCORD
# ==========================================

TRACKER_WEBHOOK_DEDUPE_TTL_SECONDS = int(env_float("TRACKER_WEBHOOK_DEDUPE_TTL_SECONDS", default=30))
_tracker_webhook_recent_keys = {}


def first_payload_value(payload, *keys, fallback="-"):
    payload = payload or {}
    for key in keys:
        value = payload.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return fallback


def first_payload_number(payload, *keys, fallback=0.0):
    payload = payload or {}
    for key in keys:
        if key in payload and payload.get(key) is not None:
            return parse_number(payload.get(key), fallback)
    return fallback


def discord_text(value, fallback="-", max_length=1024):
    value = safe_str(value, fallback)
    if not value:
        value = fallback
    value = value.replace("\x00", "").strip()
    if len(value) > max_length:
        value = value[: max_length - 1] + "…"
    return value


def discord_field(name, value, inline=True):
    return {
        "name": discord_text(name, "-", 256),
        "value": discord_text(value, "-", 1024),
        "inline": bool(inline)
    }


def tracker_current_job_key(payload, user_doc=None):
    payload = payload or {}
    job_id = payload_lookup_value(payload, "jobId", "job_id", "id", "deliveryId", "delivery_id", fallback="")
    if job_id:
        return f"job:{job_id}"

    driver_id = safe_str((user_doc or {}).get("discord_id"))
    driver_name = payload_lookup_value(payload, "driverName", "displayName", "username", "driver", fallback=driver_id)
    source = payload_lookup_value(payload, "sourceCity", "source_city", "source", "from", "routeOrigin", fallback="-")
    destination = payload_lookup_value(payload, "destinationCity", "destination_city", "destination", "to", "routeDestination", fallback="-")
    cargo = payload_lookup_value(payload, "cargo", "freight", "cargoName", "jobCargo", fallback="-")
    truck = payload_lookup_value(payload, "truck", "truckName", "truckModel", "truck_model", fallback="-")

    raw_key = "|".join([driver_id or driver_name, source, destination, cargo, truck])
    if raw_key.replace("|", "").replace("-", "").strip() == "":
        return ""
    return "tour:" + hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:24]


def build_tour_start_discord_payload(user_doc, telemetry):
    telemetry = telemetry or {}
    display_name = (
        (user_doc or {}).get("display_name")
        or (user_doc or {}).get("username")
        or (user_doc or {}).get("discord_username")
        or payload_lookup_value(telemetry, "driverName", "displayName", "username", "driver", fallback="EifelLog Fahrer")
    )
    truck = payload_lookup_value(telemetry, "truck", "truckName", "truckModel", "truck_model", fallback="-")
    source = payload_lookup_value(telemetry, "sourceCity", "source_city", "source", "from", "routeOrigin", fallback="-")
    destination = payload_lookup_value(telemetry, "destinationCity", "destination_city", "destination", "to", "routeDestination", fallback="-")
    cargo = payload_lookup_value(telemetry, "cargo", "freight", "cargoName", "jobCargo", fallback="-")
    eta = payload_lookup_value(telemetry, "eta", "etaText", "eta_text", "remainingTime", "navigationTime", fallback="-")
    rpm = first_payload_number(telemetry, "rpm", "engineRpm", "engineRPM", fallback=0)
    job_id = payload_lookup_value(telemetry, "jobId", "job_id", "id", "deliveryId", "delivery_id", fallback="-")
    driver_card_id = resolve_driver_card_id(user_doc, telemetry)

    return {
        "username": "EifelLog Tracker",
        "allowed_mentions": {"parse": []},
        "embeds": [
            {
                "title": "🚚 Tour gestartet",
                "description": f"**{discord_text(display_name, 'EifelLog Fahrer', 120)}** hat eine Tour gestartet.",
                "color": 5763719,
                "fields": [
                    discord_field("👤 Fahrer", display_name, True),
                    discord_field("🪪 Fahrerkarte-ID", driver_card_id, True),
                    discord_field("🚛 LKW", truck, True),

                    discord_field("📦 Fracht", cargo, True),
                    discord_field("⛽ Kraftstoff", format_fuel_display_from_payload(telemetry), True),
                    discord_field("🕒 ETA", eta, True),

                    discord_field("⚙️ RPM", str(parse_int(rpm, 0)), True),
                    discord_field("📍 Von", source, True),
                    discord_field("🏁 Nach", destination, True),

                    discord_field("🧾 Job-ID", f"`{discord_text(job_id, '-', 120)}`", False)
                ],
                "footer": {"text": f"{TOUR_RECEIPT_COMPANY_NAME} • Touren-Channel"},
                "timestamp": now_utc().isoformat() + "Z"
            }
        ]
    }


def send_tour_start_to_discord(user_doc, telemetry):
    if not TOUR_START_DISCORD_ENABLED:
        return {"sent": False, "reason": "TOUR_START_DISCORD_ENABLED=false"}
    return post_discord_json_to_tour_channel(
        build_tour_start_discord_payload(user_doc, telemetry),
        channel_id=TOUR_CHANNEL_ID,
        webhook_url=DISCORD_TOUR_WEBHOOK_URL or DISCORD_JOB_COMPLETE_WEBHOOK_URL
    )


def unwrap_tracker_webhook_payload(data):
    data = data or {}
    if isinstance(data, dict) and isinstance(data.get("payload"), dict):
        payload = data.get("payload") or {}
    else:
        payload = data
    return payload if isinstance(payload, dict) else {}


def tracker_webhook_dedupe_key(payload):
    payload = payload or {}

    job_id = first_payload_value(payload, "jobId", "job_id", "id", "deliveryId", "delivery_id", fallback="")
    if job_id:
        return f"job:{job_id}"

    driver = first_payload_value(payload, "driverName", "displayName", "username", "driver", fallback="")
    source = first_payload_value(payload, "sourceCity", "source_city", "source", "from", fallback="")
    destination = first_payload_value(payload, "destinationCity", "destination_city", "destination", "to", fallback="")
    cargo = first_payload_value(payload, "cargo", "freight", "cargoName", "jobCargo", fallback="")
    truck = first_payload_value(payload, "truck", "truckName", "truckModel", fallback="")
    distance = str(round(first_payload_number(
        payload,
        "completedDistanceKm", "completed_distance_km", "drivenDistanceKm", "driven_distance_km",
        "distanceKm", "distance", "routeDistanceKm", "route_distance_km", "plannedDistanceKm",
        "tripDistanceKm",
        fallback=0.0
    ), 1))

    raw_key = "|".join([driver, source, destination, cargo, truck, distance])
    return "payload:" + hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:24]


def tracker_webhook_is_duplicate(payload):
    if TRACKER_WEBHOOK_DEDUPE_TTL_SECONDS <= 0:
        return False

    now = now_utc()
    ttl = timedelta(seconds=TRACKER_WEBHOOK_DEDUPE_TTL_SECONDS)
    dedupe_key = tracker_webhook_dedupe_key(payload)

    expired_keys = [
        key for key, seen_at in _tracker_webhook_recent_keys.items()
        if not isinstance(seen_at, datetime) or now - seen_at > ttl
    ]
    for key in expired_keys:
        _tracker_webhook_recent_keys.pop(key, None)

    last_seen = _tracker_webhook_recent_keys.get(dedupe_key)
    if isinstance(last_seen, datetime) and now - last_seen <= ttl:
        return True

    _tracker_webhook_recent_keys[dedupe_key] = now
    return False


def build_tracker_webhook_discord_payload(payload):
    payload = payload or {}

    driver = first_payload_value(payload, "driverName", "displayName", "username", "driver", fallback="Unbekannter Fahrer")
    truck = first_payload_value(payload, "truck", "truckName", "truckModel", "truck_model", fallback="-")
    source = first_payload_value(payload, "sourceCity", "source_city", "source", "from", "jobSourceCity", fallback="-")
    destination = first_payload_value(payload, "destinationCity", "destination_city", "destination", "to", "targetCity", "jobDestinationCity", fallback="-")
    cargo = first_payload_value(payload, "cargo", "freight", "cargoName", "cargo_name", "jobCargo", fallback="-")
    game = first_payload_value(payload, "game", "gameCode", "gameName", fallback="ETS2/ATS")
    status = first_payload_value(payload, "status", "jobStatus", fallback="completed")

    distance = first_payload_number(
        payload,
        "completedDistanceKm", "completed_distance_km", "drivenDistanceKm", "driven_distance_km",
        "distanceKm", "distance", "routeDistanceKm", "route_distance_km", "plannedDistanceKm",
        "tripDistanceKm",
        fallback=0.0
    )
    damage = first_payload_number(payload, "damagePercent", "truckDamagePercent", "trailerDamagePercent", "damage", fallback=0.0)
    rpm = first_payload_number(payload, "rpm", "engineRpm", "engineRPM", fallback=0.0)
    fuel_display = format_fuel_display_from_payload(payload)

    eta = first_payload_value(payload, "eta", "etaText", "eta_text", fallback="-")
    job_id = first_payload_value(payload, "jobId", "job_id", "id", "deliveryId", "delivery_id", fallback="-")
    driver_card_id = resolve_driver_card_id(None, payload)

    return {
        "username": "EifelLog Tracker",
        "allowed_mentions": {"parse": []},
        "embeds": [
            {
                "title": "🚚 Auftrag erfolgreich abgeschlossen!",
                "description": f"Der Tracker hat einen abgeschlossenen Auftrag gemeldet. Status: `{discord_text(status, 'completed', 80)}`",
                "color": 3447003,
                "fields": [
                    discord_field("👤 Fahrer", driver, True),
                    discord_field("🪪 Fahrerkarte-ID", driver_card_id, True),
                    discord_field("🚛 LKW", truck, True),

                    discord_field("📍 Von", source, True),
                    discord_field("🏁 Nach", destination, True),
                    discord_field("📦 Fracht", cargo, True),

                    discord_field("🛣️ Strecke", f"{round(distance, 1)} km", True),
                    discord_field("🔧 Schaden", f"{round(damage, 1)}%", True),
                    discord_field("⛽ Kraftstoff", fuel_display, True),

                    discord_field("⚙️ RPM", str(parse_int(rpm, 0)), True),
                    discord_field("🕒 ETA", eta, True),
                    discord_field("🧾 Job-ID", job_id, False)
                ],
                "footer": {"text": "EifelLog Telemetry Webhook"},
                "timestamp": now_utc().isoformat() + "Z"
            }
        ]
    }


def post_json_to_discord_webhook(discord_payload):
    return post_discord_json_to_tour_channel(
        discord_payload,
        channel_id=TOUR_CHANNEL_ID,
        webhook_url=DISCORD_TOUR_WEBHOOK_URL or DISCORD_JOB_COMPLETE_WEBHOOK_URL
    )

def payload_bool(payload, *keys, fallback=False):
    payload = payload or {}
    for key in keys:
        if key not in payload:
            continue
        value = payload.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "ja", "on", "completed", "delivered"}
    return fallback


def tracker_webhook_payload_is_completed(payload):
    payload = payload or {}
    status = first_payload_value(payload, "status", "jobStatus", "job_status", fallback="").lower()

    return (
        payload_bool(payload, "jobFinished", "jobDelivered", "jobCompleted", "completed", "delivered", fallback=False)
        or status in {"finished", "completed", "complete", "delivered", "done", "fertig", "submitted"}
    )


def tracker_webhook_completed_distance(payload):
    return first_payload_number(
        payload,
        "completedDistanceKm", "completed_distance_km", "drivenDistanceKm", "driven_distance_km",
        "distanceKm", "distance", "routeDistanceKm", "route_distance_km", "plannedDistanceKm",
        "tripDistanceKm",
        fallback=0.0
    )


def resolve_tracker_webhook_user(payload):
    payload = payload or {}

    client_token = first_payload_value(
        payload,
        "clientToken", "trackerClientToken", "tracker_token", "token",
        fallback=""
    )
    if client_token:
        user_doc = find_tracker_user_by_client_token(client_token)
        if user_doc:
            return user_doc

    for key in ("discordId", "discord_id", "driverDiscordId", "driver_discord_id"):
        discord_id = safe_str(payload.get(key))
        if discord_id:
            user_doc = users_collection.find_one({"discord_id": discord_id})
            if user_doc:
                return user_doc

    driver_name = first_payload_value(payload, "driverName", "displayName", "username", "driver", fallback="")
    if driver_name:
        return find_user_for_tracker_name(driver_name)

    return None


def stable_webhook_job_id(payload):
    job_id = first_payload_value(payload, "jobId", "job_id", "id", "deliveryId", "delivery_id", fallback="")
    if job_id:
        return job_id

    return "webhook-" + tracker_webhook_dedupe_key(payload).split(":", 1)[-1]


def store_tracker_webhook_completed_job(payload):
    payload = payload or {}

    if not tracker_webhook_payload_is_completed(payload):
        return {"stored": False, "reason": "Payload ist kein abgeschlossener Auftrag."}

    distance = tracker_webhook_completed_distance(payload)
    if distance <= 0:
        return {"stored": False, "reason": "Keine abgeschlossene Distanz im Payload gefunden."}

    user_doc = resolve_tracker_webhook_user(payload)
    if not user_doc:
        return {"stored": False, "reason": "Kein Fahrer/User zum Webhook-Payload gefunden."}

    payload_for_db = dict(payload)
    payload_for_db["jobId"] = stable_webhook_job_id(payload_for_db)
    payload_for_db["completedDistanceKm"] = distance
    payload_for_db["distanceKm"] = distance

    receipt_doc = build_tour_receipt_doc(user_doc, payload_for_db, telemetry=payload_for_db)
    receipt_doc["source"] = "tracker_webhook"
    receipt_doc["status"] = "completed"
    receipt_doc["completed"] = True
    receipt_doc["submitted"] = True
    receipt_doc["billing_relevant"] = True
    receipt_doc["pdf"] = receipt_doc.get("pdf") or {}
    receipt_doc["discord"] = receipt_doc.get("discord") or {}

    existing = tour_receipts_collection.find_one({
        "job_id": receipt_doc["job_id"],
        "driver.discord_id": safe_str(user_doc.get("discord_id")),
        "archived": {"$ne": True}
    })
    if existing:
        refresh_company_all_time_stats_from_receipts()
        company_stats = get_company_all_time_stats()
        return {
            "stored": False,
            "alreadyStored": True,
            "reason": "Dieser Auftrag ist bereits in der Datenbank gespeichert.",
            "jobId": existing.get("job_id"),
            "allTimeKilometers": round(positive_number(company_stats.get("all_time_km"), 0), 1)
        }

    try:
        file_path, filename, pdf_bytes = save_tour_receipt_pdf(receipt_doc)
        receipt_doc["pdf"] = {
            "file_path": file_path,
            "file_name": filename,
            "public_url": build_receipt_public_url(file_path),
            "size_bytes": len(pdf_bytes),
            "content_type": "application/pdf"
        }
        receipt_doc["discord"] = send_receipt_to_discord(receipt_doc, pdf_bytes, filename)
    except Exception as error:
        receipt_doc["discord"] = {"sent": False, "error": str(error)}

    tour_receipts_collection.insert_one(receipt_doc)
    write_receipt_into_user_stats(user_doc, receipt_doc)

    fresh_user = users_collection.find_one({"_id": user_doc["_id"]}) or user_doc
    company_stats = get_company_all_time_stats()

    return {
        "stored": True,
        "jobId": receipt_doc.get("job_id"),
        "receiptId": receipt_doc.get("receipt_id"),
        "driverName": receipt_doc.get("driver", {}).get("name"),
        "distanceKm": round(distance, 1),
        "driverAllTimeKilometers": round(get_user_all_time_km(fresh_user), 1),
        "allTimeKilometers": round(positive_number(company_stats.get("all_time_km"), 0), 1),
        "databaseEntryId": COMPANY_STATS_DOCUMENT_ID,
        "pdf": receipt_doc.get("pdf"),
        "discord": receipt_doc.get("discord")
    }


@app.route("/webhook", methods=["GET", "POST", "OPTIONS"])
@app.route("/api/tracker/webhook", methods=["GET", "POST", "OPTIONS"])
@app.route("/api/tracker/discord/webhook", methods=["GET", "POST", "OPTIONS"])
def tracker_local_webhook():
    if request.method == "OPTIONS":
        return jsonify({"success": True})

    if request.method == "GET":
        return jsonify({
            "success": True,
            "message": "Tracker Webhook ist aktiv. Bitte per POST JSON senden.",
            "routes": ["/webhook", "/api/tracker/webhook", "/api/tracker/discord/webhook"]
        })

    data = request.get_json(silent=True) or {}
    payload = unwrap_tracker_webhook_payload(data)

    if not payload:
        return jsonify({"success": False, "error": "Webhook Payload fehlt oder ist kein JSON-Objekt."}), 400

    if tracker_webhook_is_duplicate(payload):
        return jsonify({
            "success": True,
            "duplicate": True,
            "message": "Webhook wurde als Duplikat erkannt und nicht erneut verarbeitet."
        })

    database_result = store_tracker_webhook_completed_job(payload)

    discord_result = database_result.get("discord") or {}
    if not discord_result:
        if isinstance(data, dict) and ("embeds" in data or "content" in data):
            discord_payload = data
        else:
            discord_payload = build_tracker_webhook_discord_payload(payload)

        discord_result = post_json_to_discord_webhook(discord_payload)

    success = bool(discord_result.get("sent")) or bool(database_result.get("stored")) or bool(database_result.get("alreadyStored"))
    status_code = 200 if success else 502

    return jsonify({
        "success": success,
        "message": "Webhook empfangen. All-Time-KM wurden gespeichert und Discord wurde informiert." if success else "Webhook empfangen, aber Datenbank/Discord-Verarbeitung fehlgeschlagen.",
        "database": database_result,
        "discord": discord_result
    }), status_code


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
    previous_job_key = safe_str(user_doc.get("tracker_current_job_key"))

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
    if current_job:
        current_job_key = tracker_current_job_key(telemetry, user_doc)
        update_payload["tracker_current_job"] = current_job
        update_payload["tracker_current_job_key"] = current_job_key

        if is_online and current_job_key and current_job_key != previous_job_key:
            start_discord_result = send_tour_start_to_discord(user_doc, telemetry)
            update_payload["tracker_tour_started_at"] = now_utc()
            update_payload["tracker_tour_started_discord"] = start_discord_result
            update_payload["tracker_tour_started_discord_message_id"] = start_discord_result.get("message_id")
            update_payload["tracker_tour_started_discord_channel_id"] = start_discord_result.get("channel_id") or TOUR_CHANNEL_ID
    else:
        update_payload["tracker_current_job"] = None
        update_payload["tracker_current_job_key"] = ""

    users_collection.update_one({"_id": user_doc["_id"]}, {"$set": update_payload})
    fresh_user = users_collection.find_one({"_id": user_doc["_id"]})

    return jsonify(tracker_state_payload(fresh_user))

@app.route("/api/tracker/driver-card", methods=["GET", "POST", "OPTIONS"])
def tracker_driver_card():
    if request.method == "OPTIONS":
        return jsonify({"success": True})

    data = request.get_json(silent=True) or {}
    user_doc, client_token, error_response = tracker_auth_user_from_payload(data)
    if error_response:
        return error_response

    if request.method == "POST":
        incoming = data.get("driverCard") or data.get("driver_card") or data.get("card") or {}
        latest_request = tracker_latest_issued_fahrerkarte_request(user_doc)
        card_doc = tracker_build_driver_card_doc(user_doc, source_request=latest_request or {}, source="tracker_manual_sync", extra=incoming)
        tracker_driver_cards_collection.update_one(
            {"discord_id": user_doc.get("discord_id"), "card_id": card_doc["card_id"]},
            {"$set": card_doc, "$setOnInsert": {"created_at": card_doc["created_at"]}},
            upsert=True
        )
        card_doc = tracker_driver_cards_collection.find_one({"discord_id": user_doc.get("discord_id"), "card_id": card_doc["card_id"]})
    else:
        card_doc = tracker_get_latest_driver_card_doc(user_doc, create_from_servicecenter=True)

    if not card_doc:
        return jsonify({
            "success": False,
            "error": "Keine Fahrerkarte in der Datenbank gefunden. Bitte zuerst eine Fahrerkarte-PDF hochladen.",
            "driverCard": None,
            "profile": tracker_profile_payload(user_doc),
        }), 404

    driver_card_payload = tracker_prepare_driver_card_payload(card_doc, user_doc=user_doc)
    return jsonify({
        "success": True,
        "driverCard": driver_card_payload,
        "driver_card": driver_card_payload,
        "digitalDriverCard": driver_card_payload,
        "fahrerkarte": driver_card_payload,
        "profile": tracker_profile_payload(user_doc),
    })


@app.route("/api/tracker/driver-card/upload", methods=["POST", "OPTIONS"])
def tracker_driver_card_upload():
    if request.method == "OPTIONS":
        return jsonify({"success": True})

    form_payload = request.form or {}
    user_doc, client_token, error_response = tracker_auth_user_from_payload(form_payload)
    if error_response:
        return error_response

    upload = request.files.get("file") or request.files.get("pdf") or request.files.get("driverCardPdf")
    if not upload or not upload.filename:
        return jsonify({"success": False, "error": "Keine PDF-Datei erhalten."}), 400

    if not tracker_allowed_driver_card_file(upload.filename):
        return jsonify({"success": False, "error": "Nur PDF-Dateien sind als Fahrerkarte erlaubt."}), 400

    os.makedirs(TRACKER_DRIVER_CARD_UPLOAD_FOLDER, exist_ok=True)

    original_filename = secure_filename(upload.filename) or "fahrerkarte.pdf"
    extension = original_filename.rsplit(".", 1)[1].lower()
    discord_id = safe_str(user_doc.get("discord_id"))
    unique_filename = f"{discord_id or 'driver'}_{now_utc().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:10]}.{extension}"
    relative_path = tracker_driver_card_upload_relative_path(unique_filename)
    absolute_path = os.path.join(BASE_DIR, relative_path)
    os.makedirs(os.path.dirname(absolute_path), exist_ok=True)
    upload.save(absolute_path)

    latest_request = tracker_latest_issued_fahrerkarte_request(user_doc)
    extra = {
        "fileName": unique_filename,
        "originalFilename": original_filename,
        "fileRelativePath": relative_path,
        "downloadUrl": tracker_public_file_url(relative_path),
        "uploadedAt": now_utc(),
        "status": "Aktiv",
    }
    card_doc = tracker_build_driver_card_doc(user_doc, source_request=latest_request or {}, source="tracker_pdf_upload", extra=extra)

    tracker_driver_cards_collection.update_many(
        {"discord_id": discord_id, "archived": {"$ne": True}},
        {"$set": {"archived": True, "archived_at": now_utc(), "active": False}}
    )
    tracker_driver_cards_collection.update_one(
        {"discord_id": discord_id, "card_id": card_doc["card_id"], "file_relative_path": relative_path},
        {"$set": card_doc, "$setOnInsert": {"created_at": card_doc["created_at"]}},
        upsert=True
    )

    users_collection.update_one(
        {"_id": user_doc["_id"]},
        {"$set": {
            "fahrerkarte_card_id": card_doc["card_id"],
            "personalisierte_fahrerkarte_card_id": card_doc["card_id"],
            "driver_card_id": card_doc["card_id"],
            "fahrerkarte_pdf_relative_path": relative_path,
            "fahrerkarte_pdf_filename": unique_filename,
            "fahrerkarte_download_url": card_doc.get("download_url"),
            "tracker_driver_card_uploaded_at": now_utc(),
            "tracker_driver_card_active": True,
        }}
    )

    fresh_user = users_collection.find_one({"_id": user_doc["_id"]})
    fresh_card = tracker_driver_cards_collection.find_one(
        {"discord_id": discord_id, "card_id": card_doc["card_id"], "archived": {"$ne": True}},
        sort=[("updated_at", DESCENDING)]
    ) or tracker_driver_cards_collection.find_one({"discord_id": discord_id, "card_id": card_doc["card_id"]})
    driver_card_payload = tracker_prepare_driver_card_payload(fresh_card, user_doc=fresh_user)

    return jsonify({
        "success": True,
        "message": "Fahrerkarte-PDF wurde gespeichert und als digitale Fahrerkarte in der Datenbank hinterlegt.",
        "driverCard": driver_card_payload,
        "driver_card": driver_card_payload,
        "digitalDriverCard": driver_card_payload,
        "fahrerkarte": driver_card_payload,
        "profile": tracker_profile_payload(fresh_user),
    })


@app.route("/api/tracker/work-session", methods=["GET", "POST", "OPTIONS"])
def tracker_work_session():
    if request.method == "OPTIONS":
        return jsonify({"success": True})

    data = request.get_json(silent=True) or {}
    user_doc, client_token, error_response = tracker_auth_user_from_payload(data)
    if error_response:
        return error_response

    if request.method == "POST":
        incoming_session = data.get("workSession") or data.get("work_session") or data.get("driverWorkSession") or data.get("tachograph") or {}
        driver_card_id = safe_str(data.get("driverCardId") or data.get("driver_card_id"))
        session_doc = tracker_save_work_session(user_doc, incoming_session, driver_card_id=driver_card_id)
    else:
        session_doc = tracker_get_latest_work_session_doc(user_doc)

    work_session = tracker_prepare_work_session_payload(session_doc)
    driver_card_doc = tracker_get_latest_driver_card_doc(user_doc, create_from_servicecenter=True)
    eligibility = tracker_validate_job_requirements(user_doc, driver_card_doc, work_session)

    return jsonify({
        "success": True,
        "workSession": work_session,
        "work_session": work_session,
        "eligibility": eligibility,
        "driverCard": tracker_prepare_driver_card_payload(driver_card_doc, user_doc=user_doc) if driver_card_doc else None,
        "profile": tracker_profile_payload(user_doc),
    })


@app.route("/api/tracker/jobs/start", methods=["POST", "OPTIONS"])
def tracker_jobs_start():
    if request.method == "OPTIONS":
        return jsonify({"success": True})

    data = request.get_json(silent=True) or {}
    user_doc, client_token, error_response = tracker_auth_user_from_payload(data)
    if error_response:
        return error_response

    driver_card_doc = tracker_get_latest_driver_card_doc(user_doc, create_from_servicecenter=True)
    incoming_session = data.get("workSession") or data.get("work_session") or {}
    if incoming_session:
        session_doc = tracker_save_work_session(
            user_doc,
            incoming_session,
            driver_card_id=(driver_card_doc or {}).get("card_id") or safe_str(data.get("driverCardId"))
        )
    else:
        session_doc = tracker_get_latest_work_session_doc(user_doc)

    work_session = tracker_prepare_work_session_payload(session_doc)
    eligibility = tracker_validate_job_requirements(user_doc, driver_card_doc, work_session)

    if not eligibility.get("allowed"):
        return jsonify({
            "success": False,
            "error": "Auftrag kann nicht gestartet werden: " + " ".join(eligibility.get("issues") or []),
            "issues": eligibility.get("issues") or [],
            "eligibility": eligibility,
            "workSession": work_session,
            "driverCard": tracker_prepare_driver_card_payload(driver_card_doc, user_doc=user_doc) if driver_card_doc else None,
        }), 409

    telemetry_raw = data.get("telemetry") or data.get("snapshot") or user_doc.get("tracker_live") or {}
    telemetry = normalize_telemetry_payload(telemetry_raw) if telemetry_raw else {}
    job_id = tracker_job_id_from_payload(data, telemetry)
    current_job = current_job_from_live(telemetry) if telemetry else None
    now = now_utc()

    job_doc = {
        "job_id": job_id,
        "discord_id": safe_str(user_doc.get("discord_id")),
        "user_id": safe_str(user_doc.get("discord_id")),
        "user_mongo_id": safe_str(user_doc.get("_id")),
        "username": user_doc.get("username") or user_doc.get("discord_username"),
        "display_name": user_doc.get("display_name") or user_doc.get("username") or user_doc.get("discord_username"),
        "driver_card_id": (driver_card_doc or {}).get("card_id"),
        "driver_card": tracker_prepare_driver_card_payload(driver_card_doc, user_doc=user_doc),
        "work_session": work_session,
        "eligibility": eligibility,
        "telemetry": telemetry,
        "current_job": current_job,
        "status": "started",
        "checked_at": safe_str(data.get("checkedAt")),
        "created_at": now,
        "updated_at": now,
    }
    tracker_job_starts_collection.insert_one(job_doc)

    set_payload = {
        "tracker_last_job_start_id": job_id,
        "tracker_last_job_started_at": now,
        "tracker_current_driver_card_id": (driver_card_doc or {}).get("card_id"),
        "tracker_work_session": work_session,
        "tracker_work_session_updated_at": now,
    }
    if telemetry:
        set_payload.update({
            "tracker_live": telemetry,
            "tracker_live_updated_at": now,
            "tracker_online": bool(telemetry.get("isConnected") or telemetry.get("gameProcessDetected") or telemetry.get("telemetryConnected")),
        })
    if current_job:
        set_payload["tracker_current_job"] = current_job
        set_payload["tracker_current_job_key"] = tracker_current_job_key(telemetry, user_doc)

    users_collection.update_one({"_id": user_doc["_id"]}, {"$set": set_payload})
    fresh_user = users_collection.find_one({"_id": user_doc["_id"]})

    response_payload = tracker_state_payload(fresh_user)
    response_payload.update({
        "message": "Auftrag gestartet. Voraussetzungen wurden serverseitig geprüft.",
        "jobStart": {
            "jobId": job_id,
            "status": "started",
            "startedAt": datetime_to_iso(now),
        },
        "eligibility": eligibility,
        "workSession": work_session,
        "driverCard": tracker_prepare_driver_card_payload(driver_card_doc, user_doc=fresh_user),
    })
    return jsonify(response_payload)



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
    driver_dashboard_context = prepare_driver_dashboard_context(db_user)

    return render_template(
        "dashboard.html",
        current_user=user,
        needs_signature=needs_signature,
        primary_role_name=primary_role_name,
        news_items=news_items,
        user_documents=user_documents,
        **registration_context,
        **driver_dashboard_context
    )


@app.route("/servicecenter", methods=["GET"])
@app.route("/EifellogServiceCenter", methods=["GET"])
@app.route("/EifellogServiceCenter.html", methods=["GET"])
def servicecenter():
    if "user" not in session:
        flash("Bitte logge dich zuerst ein.", "error")
        return redirect(url_for("hub"))

    user = session["user"]
    user_roles = user.get("roles", [])

    if not has_dashboard_permission(user_roles):
        flash("Zugriff verweigert! Du benötigst eine anerkannte Rolle, um das ServiceCenter zu betreten.", "error")
        return redirect(url_for("home"))

    discord_id = safe_str(user.get("id"))
    db_user = users_collection.find_one({"discord_id": discord_id})

    if not db_user:
        db_user = {
            "discord_id": discord_id,
            "username": user.get("username"),
            "discord_username": user.get("discord_username"),
            "display_name": user.get("username"),
            "avatar": user.get("avatar"),
            "roles": user_roles,
        }

    primary_role_name = get_primary_role_name(user_roles)
    latest_fahrerkarte_request = get_latest_fahrerkarte_request_for_user(discord_id)
    fahrerkarte_context = prepare_fahrerkarte_context(db_user, latest_fahrerkarte_request)
    servicecenter_messages = get_servicecenter_messages_for_user(discord_id)

    return render_template(
        "EifellogServiceCenter.html",
        current_user=user,
        primary_role_name=primary_role_name,
        servicecenter_messages=servicecenter_messages,
        fahrerkarte_submit_url=url_for("servicecenter_fahrerkarte_beantragen"),
        fahrerkarte_download_url=fahrerkarte_context.get("fahrerkarte_pdf_download_url") or url_for("servicecenter_fahrerkarte"),
        **fahrerkarte_context,
    )


@app.route("/servicecenter/fahrerkarte", methods=["GET"])
def servicecenter_fahrerkarte():
    return servicecenter()


@app.route("/servicecenter/fahrerkarte/beantragen", methods=["POST"])
def servicecenter_fahrerkarte_beantragen():
    if "user" not in session:
        flash("Bitte logge dich zuerst ein.", "error")
        return redirect(url_for("hub"))

    user = session.get("user") or {}
    user_roles = user.get("roles", [])

    if not has_dashboard_permission(user_roles):
        flash("Zugriff verweigert! Du benötigst eine anerkannte Rolle, um eine Fahrerkarte zu beantragen.", "error")
        return redirect(url_for("home"))

    discord_id = safe_str(user.get("id"))
    if not discord_id:
        flash("Session ist ungültig. Bitte logge dich erneut ein.", "error")
        return redirect(url_for("hub"))

    db_user = users_collection.find_one({"discord_id": discord_id})
    if not db_user:
        flash("User wurde in der Datenbank nicht gefunden.", "error")
        return redirect(url_for("dashboard"))

    data = request.form if request.form else (request.get_json(silent=True) or {})

    full_name = safe_str(data.get("full_name"), db_user.get("display_name") or db_user.get("username") or user.get("username"))[:100]
    display_name = safe_str(data.get("display_name"), full_name)[:100]
    role_name = safe_str(data.get("role_name"), get_primary_role_name(db_user.get("roles", [])))[:100]
    system_id = safe_str(data.get("system_id"), discord_id)[:80]
    driver_number = safe_str(data.get("driver_number"))[:80]
    priority = safe_str(data.get("priority"), "normal")[:40]
    reason = safe_str(data.get("reason"))[:80]
    delivery_method = safe_str(data.get("delivery_method"), "servicecenter")[:80]
    notes = safe_str(data.get("notes"))[:600]
    confirm_correct = safe_str(data.get("confirm_correct")) in {"1", "true", "on", "yes", "ja"}

    if len(full_name) < 2 or len(display_name) < 2 or len(role_name) < 2 or len(system_id) < 2:
        flash("Bitte fülle alle Pflichtfelder für die Fahrerkarte aus.", "error")
        return redirect(url_for("servicecenter"))

    if not reason:
        flash("Bitte wähle einen Antragsgrund aus.", "error")
        return redirect(url_for("servicecenter"))

    if not confirm_correct:
        flash("Bitte bestätige, dass deine Angaben korrekt sind.", "error")
        return redirect(url_for("servicecenter"))

    # Wichtig: Falls der Antrag bereits nur im users-Dokument steht, zuerst vollständig in die Request-Collection spiegeln.
    sync_fahrerkarte_request_from_user_doc(db_user)

    existing_open = fahrerkarte_requests_collection.find_one({
        "discord_id": discord_id,
        "archived": {"$ne": True},
        "status": {"$in": ["pending", "open", "claimed", "approved", "postponed"]},
    })
    if existing_open:
        flash("Du hast bereits eine offene Beantragung für eine personalisierte Fahrerkarte. Sie liegt im Web-ServiceCenter der Personalabteilung bereit.", "info")
        return redirect(url_for("servicecenter"))

    now = now_utc()
    request_id = uuid.uuid4().hex

    request_doc = {
        "request_id": request_id,
        "discord_id": discord_id,
        "user_id": discord_id,
        "username": db_user.get("username") or user.get("username"),
        "discord_username": db_user.get("discord_username") or user.get("discord_username"),
        "avatar_url": make_external_url(get_discord_avatar_url(db_user)),
        "name": full_name,
        "full_name": full_name,
        "display_name": display_name,
        "role": role_name,
        "role_name": role_name,
        "system_id": system_id,
        "driver_number": driver_number,
        "priority": priority,
        "reason": reason,
        "delivery_method": delivery_method,
        "notes": notes,
        "status": "pending",
        "created_at": now,
        "updated_at": now,
        "source": "servicecenter_fahrerkarte",
        "card_id": "",
    }

    insert_result = fahrerkarte_requests_collection.insert_one(request_doc)
    request_doc["_id"] = insert_result.inserted_id
    mirror_fahrerkarte_request_for_discord_plugin(request_doc, user_doc=db_user)

    users_collection.update_one(
        {"discord_id": discord_id},
        {
            "$set": {
                "personalisierte_fahrerkarte_status": "pending",
                "fahrerkarte_status": "pending",
                "fahrerkarte_requested_at": now,
                "fahrerkarte_request_id": request_id,
                "fahrerkarte_name": display_name,
                "fahrerkarte_role": role_name,
                "fahrerkarte_handler": "Noch nicht zugewiesen",
            }
        }
    )

    create_system_document_for_user(
        discord_id,
        "Fahrerkarte beantragt",
        "EifelLog ServiceCenter",
        fahrerkarte_application_document_content(display_name, role_name, request_id, priority, reason, delivery_method, notes),
        doc_type="driver_card_application",
        needs_signature=False,
        extra={
            "important": True,
            "request_id": request_id,
            "fahrerkarte_request_id": request_id,
            "contains_driver_card": True,
        },
    )

    tasks_collection.insert_one({
        "title": f"Fahrerkarte beantragen: {display_name}",
        "type": "ServiceCenter",
        "priority": "high" if priority == "high" else "medium",
        "description": f"{display_name} ({role_name}) hat eine personalisierte Fahrerkarte beantragt. Grund: {reason}",
        "status": "open",
        "created_at": now,
        "assignee": None,
        "source": "servicecenter_fahrerkarte",
        "request_id": request_id,
    })

    servicecenter_discord_sync_fahrerkarte_request(request_doc, event="created")
    flash("Deine personalisierte Fahrerkarte wurde beantragt. Die Personalabteilung kann sie jetzt im Web-ServiceCenter claimen, signieren und ausstellen.", "success")
    return redirect(url_for("servicecenter"))


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
        flash("Du wurdest zum Dispo-Formular weitergeleitet.", "info")
        return redirect(url_for("dispo_form"))

    return None


def require_geschaeftsleitung_permission():
    if "user" not in session:
        flash("Bitte logge dich zuerst ein.", "error")
        return redirect(url_for("hub"))

    user_roles = session.get("user", {}).get("roles", [])
    if not has_geschaeftsleitung_permission(user_roles):
        flash("Zugriff verweigert. Diese Dokumentprüfung ist nur für Geschäftsleitung/Geschäftsführung freigegeben.", "error")
        return redirect(url_for("dashboard"))

    return None


def require_dispo_form_access():
    if "user" not in session:
        flash("Bitte logge dich zuerst ein.", "error")
        return redirect(url_for("hub"))

    user_roles = session.get("user", {}).get("roles", [])
    if not has_dispo_form_access(user_roles):
        flash("Zugriff verweigert. Du darfst das Dispo-Formular nicht öffnen.", "error")
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


@app.route("/disposition.html", methods=["GET"])
@app.route("/disposition", methods=["GET"])
@app.route("/dispo.html", methods=["GET"])
@app.route("/dispo", methods=["GET"])
def dispo():
    if "user" not in session:
        flash("Bitte logge dich zuerst ein.", "error")
        return redirect(url_for("hub"))

    user = session.get("user") or {}
    user_roles = user.get("roles", [])
    primary_role_name = get_primary_role_name(user_roles)

    if not has_disposition_permission(user_roles):
        # Alle Nicht-Dispo-Rollen landen beim Klick oder Direkteingabe von /dispo direkt im Formular.
        return redirect(url_for("dispo_form"))

    if isinstance(session.get("user"), dict):
        session["user"]["is_disposition"] = True
        session["user"]["can_access_dispo_form"] = True
        session["user"]["can_view_dispo_submitted_documents"] = has_dispo_submitted_documents_permission(user_roles)
        permissions = set(item for item in session["user"].get("permissions", []) if item)
        permissions.add("disposition.view")
        permissions.add("disposition.manage")
        permissions.add("disposition.form")
        if has_dispo_submitted_documents_permission(user_roles):
            permissions.add("disposition.documents")
        else:
            permissions.discard("disposition.documents")
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
# DISPOSITION FORMULAR / ABSCHLUSSBELEGE
# ==========================================

def resolve_dispo_form_upload_folder():
    folder = safe_str(DISPO_FORM_UPLOAD_FOLDER, os.path.join("static", "uploads", "dispo_form"))
    if not os.path.isabs(folder):
        folder = os.path.join(BASE_DIR, folder)
    return folder


def allowed_dispo_form_document(filename):
    filename = safe_str(filename)
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_DISPO_FORM_EXTENSIONS


def dispo_form_entry_lookup_query(entry_id):
    entry_id = safe_str(entry_id)
    query_items = [{"entry_id": entry_id}, {"id": entry_id}]
    object_id = object_id_or_none(entry_id)
    if object_id:
        query_items.append({"_id": object_id})
    return {"$or": query_items}


def normalize_dispo_form_status(status):
    status = safe_str(status, "pending").lower()
    if status in {"verified", "geprueft", "geprüft", "checked", "reviewed"}:
        return "verified"
    if status in {"signed", "signiert", "digitally_signed", "digital_signed"}:
        return "signed"
    if status in {"management_pending", "forwarded_to_management", "forwarded", "zur_entscheidung"}:
        return "management_pending"
    if status in {"returned_incomplete", "needs_fix", "need_fix", "incomplete", "unvollstaendig", "unvollständig", "zurueckgegeben", "zurückgegeben"}:
        return "returned_incomplete"
    if status in {"approved", "freigegeben", "accepted", "ok"}:
        return "approved"
    if status in {"rejected", "abgelehnt", "declined", "denied"}:
        return "rejected"
    if status in {"completed", "done", "abgeschlossen", "finished"}:
        return "completed"
    return "pending"


def normalize_dispo_form_entry_type(entry_type):
    entry_type = safe_str(entry_type, "income").lower()
    if entry_type in {"damage", "schaden", "loss"}:
        return "damage"
    return "income"


def dispo_form_document_type_label(document_type):
    return {
        "freight_papers": "Frachtpapiere",
        "abschlussbeleg": "Abschlussbeleg",
        "delivery_note": "Lieferschein",
        "invoice": "Rechnung",
        "damage_receipt": "Schadenbeleg",
        "manual_income": "Manuelle Einnahme",
        "manual_damage": "Manueller Schaden",
        "other": "Sonstiges",
    }.get(safe_str(document_type).lower(), safe_str(document_type, "Beleg"))


def dispo_form_tax_mode_label(tax_mode):
    return {
        "eifellog_internal": "EifelLog intern",
        "external_receipt": "Externer Beleg",
        "no_tax": "Keine Steuer",
    }.get(safe_str(tax_mode).lower(), safe_str(tax_mode, "EifelLog intern"))


def calculate_dispo_form_tax(amount_net, tax_rate, tax_mode="eifellog_internal"):
    net = round(max(parse_number(amount_net, 0), 0), 2)
    rate = round(max(parse_number(tax_rate, 19), 0), 2)
    mode = safe_str(tax_mode, "eifellog_internal")

    if mode == "no_tax":
        rate = 0.0

    tax_amount = round(net * (rate / 100), 2)
    gross = round(net + tax_amount, 2)
    return net, rate, tax_amount, gross


def current_dispo_form_submitter():
    actor = current_disposition_identity()
    return {
        "discord_id": safe_str(actor.get("discord_id")),
        "username": safe_str(actor.get("username"), "Disposition"),
        "display_name": safe_str(actor.get("display_name") or actor.get("username"), "Disposition"),
        "roles": actor.get("roles", []),
    }


def prepare_dispo_form_entry_for_template(entry_doc):
    item = dict(entry_doc or {})
    mongo_id = str(item.get("_id")) if item.get("_id") else ""
    submitted_by = item.get("submitted_by") or {}
    files = item.get("files") or []
    first_file = files[0] if files else {}

    entry_source = safe_str(item.get("entry_source"), "manual")
    entry_type = normalize_dispo_form_entry_type(item.get("entry_type"))
    document_type = safe_str(item.get("document_type"))

    if entry_source == "manual" and not document_type:
        document_type = "manual_damage" if entry_type == "damage" else "manual_income"

    entry_id = safe_str(item.get("entry_id") or item.get("id") or mongo_id)

    return {
        "id": entry_id,
        "entry_id": entry_id,
        "entry_source": entry_source,
        "entry_type": entry_type,
        "type": "Schaden" if entry_type == "damage" else "Einnahme",
        "document_type": dispo_form_document_type_label(document_type),
        "document_type_raw": document_type,
        "reference": safe_str(item.get("reference"), "-"),
        "title": safe_str(item.get("title") or item.get("note") or dispo_form_document_type_label(document_type), "Beleg"),
        "description": safe_str(item.get("description") or item.get("note"), ""),
        "note": safe_str(item.get("note") or item.get("description"), ""),
        "amount_net": format_money(item.get("amount_net"), "EUR"),
        "amount_gross": format_money(item.get("amount_gross"), "EUR"),
        "tax_rate": int(parse_number(item.get("tax_rate"), 19)) if parse_number(item.get("tax_rate"), 19).is_integer() else parse_number(item.get("tax_rate"), 19),
        "tax_amount": format_money(item.get("tax_amount"), "EUR"),
        "tax_mode": dispo_form_tax_mode_label(item.get("tax_mode")),
        "status": normalize_dispo_form_status(item.get("status")),
        "submitted_by": safe_str(submitted_by.get("display_name") or submitted_by.get("username") or item.get("submitted_by_name"), "Unbekannt"),
        "submitted_by_id": safe_str(submitted_by.get("discord_id") or item.get("submitted_by_id"), "-"),
        "author": safe_str(submitted_by.get("display_name") or submitted_by.get("username") or item.get("author"), "Unbekannt"),
        "created_at": format_datetime_for_template(item.get("created_at")) or "-",
        "updated_at": format_datetime_for_template(item.get("updated_at")) or "-",
        "file_url": url_for("dispo_form_file_download", entry_id=entry_id, filename=first_file.get("stored_filename")) if first_file.get("stored_filename") else "",
        "file_name": first_file.get("original_filename") or first_file.get("stored_filename") or "",
        "files": files,
        "signature": safe_str(item.get("signature") or item.get("dispo_signature") or item.get("signature_text") or item.get("signed_by_name") or item.get("signed_by"), ""),
        "signed_by": safe_str(item.get("signed_by_name") or item.get("signature") or item.get("signed_by"), ""),
        "dispo_note": safe_str(item.get("dispo_note") or item.get("review_note") or item.get("review_comment"), ""),
        "review_note": safe_str(item.get("review_note") or item.get("dispo_note") or item.get("review_comment"), ""),
        "management_note": safe_str(item.get("management_note") or item.get("forward_note") or item.get("approval_note"), ""),
    }


def normalize_management_document_status(entry_doc):
    entry_doc = entry_doc or {}
    management_status = safe_str(entry_doc.get("management_status")).lower()

    if management_status in {"approved", "freigegeben", "accepted", "ok"}:
        return "approved"
    if management_status in {"returned_incomplete", "incomplete", "unvollstaendig", "unvollständig", "zurueckgegeben", "zurückgegeben"}:
        return "returned_incomplete"
    if management_status in {"rejected", "abgelehnt", "declined", "denied"}:
        return "rejected"
    if management_status in {"management_pending", "pending", "forwarded", "forwarded_to_management", "zur_entscheidung"}:
        return "management_pending"

    raw_status = safe_str(entry_doc.get("status"), "pending").lower()
    if raw_status in {"returned_incomplete", "incomplete", "unvollstaendig", "unvollständig", "zurueckgegeben", "zurückgegeben"}:
        return "returned_incomplete"
    if raw_status in {"rejected", "abgelehnt", "declined", "denied"}:
        return "rejected"
    if raw_status in {"management_pending", "forwarded", "forwarded_to_management", "zur_entscheidung"}:
        return "management_pending"

    # Ein von der Disposition freigegebener Beleg ist für die Geschäftsleitung zuerst "zur Entscheidung".
    if raw_status in {"approved", "freigegeben", "accepted", "ok"}:
        return "management_pending"

    return "management_pending"


def prepare_geschaeftsleitung_document_for_template(entry_doc):
    item = prepare_dispo_form_entry_for_template(entry_doc)
    item["status"] = normalize_management_document_status(entry_doc)

    reviewed_by = (entry_doc or {}).get("reviewed_by") or {}
    management_reviewed_by = (entry_doc or {}).get("management_reviewed_by") or {}
    approved_by_management = (entry_doc or {}).get("approved_by_management") or {}
    returned_by_management = (entry_doc or {}).get("returned_by_management") or {}

    forwarded_at = (
        (entry_doc or {}).get("forwarded_at")
        or (entry_doc or {}).get("dispo_forwarded_at")
        or (entry_doc or {}).get("reviewed_at")
        or (entry_doc or {}).get("updated_at")
        or (entry_doc or {}).get("created_at")
    )

    signature = (
        (entry_doc or {}).get("signature")
        or (entry_doc or {}).get("dispo_signature")
        or (entry_doc or {}).get("signed_by")
        or reviewed_by.get("display_name")
        or reviewed_by.get("username")
        or "Disposition"
    )

    item.update({
        "document_id": item.get("entry_id"),
        "forwarded_at": format_datetime_for_template(forwarded_at) or item.get("updated_at") or item.get("created_at"),
        "dispo_forwarded_at": format_datetime_for_template((entry_doc or {}).get("dispo_forwarded_at")) or "",
        "signature": signature,
        "signed_by": signature,
        "dispo_note": safe_str((entry_doc or {}).get("dispo_note") or (entry_doc or {}).get("review_note") or (entry_doc or {}).get("description")),
        "review_note": safe_str((entry_doc or {}).get("review_note") or (entry_doc or {}).get("dispo_note")),
        "management_note": safe_str((entry_doc or {}).get("management_note") or (entry_doc or {}).get("approval_note")),
        "return_note": safe_str((entry_doc or {}).get("return_note") or (entry_doc or {}).get("return_reason")),
        "management_reviewed_by": (
            management_reviewed_by.get("display_name")
            or approved_by_management.get("display_name")
            or returned_by_management.get("display_name")
            or ""
        ),
    })

    return item


def get_geschaeftsleitung_documents(limit=300):
    query = {
        "archived": {"$ne": True},
        "$or": [
            {"management_status": {"$exists": True}},
            {"forwarded_to_management": True},
            {"status": {"$in": [
                "approved",
                "management_pending",
                "forwarded_to_management",
                "forwarded",
                "returned_incomplete",
                "rejected"
            ]}},
        ]
    }

    cursor = dispo_form_entries_collection.find(query).sort([
        ("management_reviewed_at", DESCENDING),
        ("reviewed_at", DESCENDING),
        ("updated_at", DESCENDING),
        ("created_at", DESCENDING),
    ]).limit(limit)

    return [prepare_geschaeftsleitung_document_for_template(entry) for entry in cursor]


def count_geschaeftsleitung_documents(documents):
    return {
        "pending": len([item for item in documents if item.get("status") == "management_pending"]),
        "approved": len([item for item in documents if item.get("status") == "approved"]),
        "returned": len([item for item in documents if item.get("status") == "returned_incomplete"]),
    }


def save_dispo_form_uploaded_files(entry_id, uploaded_files):
    saved_files = []
    upload_root = resolve_dispo_form_upload_folder()
    dated_folder = os.path.join(now_utc().strftime("%Y"), now_utc().strftime("%m"), safe_str(entry_id))
    target_folder = os.path.join(upload_root, dated_folder)
    os.makedirs(target_folder, exist_ok=True)

    for uploaded_file in uploaded_files:
        if not uploaded_file or not uploaded_file.filename:
            continue

        if not allowed_dispo_form_document(uploaded_file.filename):
            raise ValueError("Nur PDF, PNG, JPG, JPEG oder WEBP Dateien sind erlaubt.")

        original_filename = secure_filename(uploaded_file.filename)
        extension = original_filename.rsplit(".", 1)[1].lower()
        stored_filename = f"{uuid.uuid4().hex}.{extension}"
        absolute_path = os.path.join(target_folder, stored_filename)
        uploaded_file.save(absolute_path)

        relative_path = os.path.relpath(absolute_path, BASE_DIR)
        saved_files.append({
            "original_filename": original_filename,
            "stored_filename": stored_filename,
            "extension": extension,
            "relative_path": relative_path.replace(os.sep, "/"),
            "size_bytes": os.path.getsize(absolute_path),
            "uploaded_at": now_utc(),
        })

    return saved_files


def get_dispo_form_stats(entries):
    pending_count = 0
    total_documents = 0
    income_sum = 0.0
    damage_sum = 0.0

    for entry in entries:
        if normalize_dispo_form_status(entry.get("status")) == "pending":
            pending_count += 1

        if safe_str(entry.get("entry_source")) == "document":
            total_documents += max(len(entry.get("files") or []), 1)

        amount = parse_number(entry.get("amount_net"), 0)
        entry_type = normalize_dispo_form_entry_type(entry.get("entry_type"))
        document_type = safe_str(entry.get("document_type")).lower()

        if entry_type == "damage" or document_type == "damage_receipt":
            damage_sum += amount
        elif amount > 0:
            income_sum += amount

    return {
        "pending_count": pending_count,
        "total_documents": total_documents,
        "income_sum": income_sum,
        "damage_sum": damage_sum,
    }



def dispo_user_public_payload(user_doc):
    user_doc = user_doc or {}
    mongo_id = str(user_doc.get("_id")) if user_doc.get("_id") else ""
    discord_id = safe_str(user_doc.get("discord_id") or user_doc.get("id") or user_doc.get("user_id") or mongo_id)
    username = safe_str(user_doc.get("username") or user_doc.get("discord_username") or user_doc.get("name") or discord_id, discord_id)
    display_name = safe_str(user_doc.get("display_name") or user_doc.get("global_name") or user_doc.get("nick") or username, username)

    return {
        "id": discord_id or mongo_id,
        "_id": mongo_id,
        "discord_id": discord_id,
        "user_id": discord_id or mongo_id,
        "username": username,
        "name": display_name,
        "display_name": display_name,
        "roles": user_doc.get("roles", []),
        "avatar": safe_str(user_doc.get("avatar") or user_doc.get("avatar_hash")),
    }


def get_eifellog_user_collections():
    """Unterstützt beide Varianten: eifellog_db.user und eifellog_db.users."""
    collections = []
    seen_names = set()

    for name in ("user", "users"):
        if name in seen_names:
            continue
        try:
            collections.append(db[name])
            seen_names.add(name)
        except Exception:
            continue

    return collections or [users_collection]


def get_dispo_assignable_users(limit=500):
    users = []
    seen_keys = set()
    query = {
        "$and": [
            {"archived": {"$ne": True}},
            {"disabled": {"$ne": True}},
            {"deleted": {"$ne": True}},
        ]
    }
    projection = {
        "discord_id": 1,
        "id": 1,
        "user_id": 1,
        "username": 1,
        "discord_username": 1,
        "display_name": 1,
        "global_name": 1,
        "nick": 1,
        "name": 1,
        "roles": 1,
        "avatar": 1,
        "avatar_hash": 1,
    }

    for collection in get_eifellog_user_collections():
        try:
            cursor = collection.find(query, projection).sort([
                ("display_name", ASCENDING),
                ("username", ASCENDING),
                ("discord_id", ASCENDING),
            ]).limit(limit)
        except Exception:
            try:
                cursor = collection.find({}, projection).limit(limit)
            except Exception:
                continue

        for user_doc in cursor:
            payload = dispo_user_public_payload(user_doc)
            key = safe_str(payload.get("discord_id") or payload.get("_id") or payload.get("username")).lower()
            if not key or key in seen_keys:
                continue
            seen_keys.add(key)
            users.append(payload)

    users.sort(key=lambda item: (safe_str(item.get("display_name") or item.get("username")).lower(), safe_str(item.get("discord_id"))))
    return users[:limit]


def find_dispo_assignable_user(user_id):
    user_id = safe_str(user_id)
    if not user_id:
        return None

    query_items = []
    object_id = object_id_or_none(user_id)
    if object_id:
        query_items.append({"_id": object_id})

    query_items.extend([
        {"discord_id": user_id},
        {"id": user_id},
        {"user_id": user_id},
        {"username": user_id},
        {"username_lc": user_id.lower()},
        {"display_name": {"$regex": f"^{re.escape(user_id)}$", "$options": "i"}},
    ])

    for collection in get_eifellog_user_collections():
        try:
            user_doc = collection.find_one({"$or": query_items})
        except Exception:
            user_doc = None
        if user_doc:
            return user_doc

    return None


def require_dispo_document_management_permission():
    permission_response = require_dispo_form_access()
    if permission_response:
        return permission_response

    user_roles = session.get("user", {}).get("roles", [])
    if not has_dispo_submitted_documents_permission(user_roles):
        if request.is_json:
            return jsonify({"success": False, "message": "Nur die Disposition darf eingereichte Dokumente bearbeiten."}), 403
        flash("Nur die Disposition darf eingereichte Dokumente bearbeiten.", "error")
        return redirect(url_for("dispo_form"))

    return None


def load_active_dispo_form_entry(document_id):
    document_id = safe_str(document_id)
    if not document_id:
        return None
    return dispo_form_entries_collection.find_one({
        **dispo_form_entry_lookup_query(document_id),
        "archived": {"$ne": True},
    })


@app.route("/dispo/form", methods=["GET"])
@app.route("/dispo_form.html", methods=["GET"])
def dispo_form():
    permission_response = require_dispo_form_access()
    if permission_response:
        return permission_response

    user = session.get("user") or {}
    user_roles = user.get("roles", [])
    primary_role_name = get_primary_role_name(user_roles)
    can_view_dispo_submitted_documents = has_dispo_submitted_documents_permission(user_roles)
    is_disposition_user = has_disposition_permission(user_roles)

    if isinstance(session.get("user"), dict):
        session["user"]["is_disposition"] = is_disposition_user
        session["user"]["can_access_dispo_form"] = True
        session["user"]["can_view_dispo_submitted_documents"] = can_view_dispo_submitted_documents
        permissions = set(item for item in session["user"].get("permissions", []) if item)
        permissions.add("disposition.form")
        if is_disposition_user:
            permissions.add("disposition.view")
        else:
            permissions.discard("disposition.view")
            permissions.discard("disposition.manage")
        if can_view_dispo_submitted_documents:
            permissions.add("disposition.documents")
        else:
            permissions.discard("disposition.documents")
        session["user"]["permissions"] = sorted(permissions)
        session.modified = True
        user = session.get("user") or user

    if can_view_dispo_submitted_documents:
        entries_cursor = dispo_form_entries_collection.find(
            {"archived": {"$ne": True}}
        ).sort([("created_at", DESCENDING)]).limit(300)

        raw_entries = list(entries_cursor)
        prepared_entries = [prepare_dispo_form_entry_for_template(entry) for entry in raw_entries]
        manual_entries = [entry for entry in prepared_entries if entry.get("entry_source") == "manual"][:80]
        stats = get_dispo_form_stats(raw_entries)
    else:
        raw_entries = []
        prepared_entries = []
        manual_entries = []
        stats = {
            "pending_count": 0,
            "total_documents": 0,
            "income_sum": 0.0,
            "damage_sum": 0.0,
        }

    return render_template(
        "dispo_form.html",
        current_user=user,
        primary_role_name=primary_role_name,
        can_access_dispo_form=True,
        can_view_dispo_submitted_documents=can_view_dispo_submitted_documents,
        show_dispo_submitted_documents=can_view_dispo_submitted_documents,
        show_submitted_documents=can_view_dispo_submitted_documents,
        is_disposition_viewer=can_view_dispo_submitted_documents,
        blocked_from_dispo_documents=has_dispo_blocked_documents_role(user_roles) and not can_view_dispo_submitted_documents,
        dispo_assignable_users=get_dispo_assignable_users() if can_view_dispo_submitted_documents else [],
        dispo_users=get_dispo_assignable_users() if can_view_dispo_submitted_documents else [],
        eifellog_users=get_dispo_assignable_users() if can_view_dispo_submitted_documents else [],
        users=get_dispo_assignable_users() if can_view_dispo_submitted_documents else [],
        dispo_form_submissions=prepared_entries,
        dispo_manual_entries=manual_entries,
        dispo_form_pending_count=stats["pending_count"],
        dispo_form_total_documents=stats["total_documents"],
        dispo_form_income_sum=format_money(stats["income_sum"], "EUR"),
        dispo_form_damage_sum=format_money(stats["damage_sum"], "EUR"),
        role_disposition_id=ROLE_DISPOSITION_ID,
        role_fahrer_id=ROLE_FAHRER_ID,
        role_hr_controlling_id=ROLE_HR_CONTROLLING_ID,
        role_buchhaltung_id=ROLE_BUCHHALTUNG_ID,
        role_personalmanagement_id=ROLE_PERSONALABTEILUNG_ID,
        role_fuhrparkmanagement_id=ROLE_FUHRPARKMANAGEMENT_ID,
    )


@app.route("/dispo/form/manual", methods=["POST"])
def dispo_form_manual_submit():
    permission_response = require_dispo_form_access()
    if permission_response:
        return permission_response

    submitter = current_dispo_form_submitter()
    entry_type = normalize_dispo_form_entry_type(request.form.get("entry_type"))
    reference = safe_str(request.form.get("reference"))[:160]
    title = safe_str(request.form.get("title"))[:180]
    description = safe_str(request.form.get("description"))[:2000]
    tax_mode = safe_str(request.form.get("tax_mode"), "eifellog_internal")[:80]
    amount_net, tax_rate, tax_amount, amount_gross = calculate_dispo_form_tax(
        request.form.get("amount_net"),
        request.form.get("tax_rate", 19),
        tax_mode,
    )

    if len(reference) < 2 or len(title) < 2:
        flash("Referenz und Titel müssen ausgefüllt sein.", "error")
        return redirect(url_for("dispo_form"))

    if amount_net <= 0:
        flash("Bitte einen gültigen Netto-Betrag eintragen.", "error")
        return redirect(url_for("dispo_form"))

    now = now_utc()
    entry_id = uuid.uuid4().hex
    entry_doc = {
        "entry_id": entry_id,
        "entry_source": "manual",
        "entry_type": entry_type,
        "document_type": "manual_damage" if entry_type == "damage" else "manual_income",
        "reference": reference,
        "title": title,
        "description": description,
        "amount_net": amount_net,
        "tax_rate": tax_rate,
        "tax_amount": tax_amount,
        "amount_gross": amount_gross,
        "tax_mode": tax_mode,
        "currency": "EUR",
        "status": "pending",
        "submitted_by": submitter,
        "archived": False,
        "created_at": now,
        "updated_at": now,
    }

    dispo_form_entries_collection.insert_one(entry_doc)
    dispo_messages_collection.insert_one({
        "message_id": uuid.uuid4().hex,
        "title": "Neue manuelle Dispo-Erfassung",
        "content": f"{submitter.get('display_name')} hat {title} für {reference} eingereicht.",
        "priority": "high" if entry_type == "damage" else "normal",
        "archived": False,
        "created_at": now,
        "created_by": submitter,
        "dispo_form_entry_id": entry_id,
    })

    flash("Erfassung wurde gespeichert und ist für die Disposition sichtbar.", "success")
    return redirect(url_for("dispo_form"))


@app.route("/dispo/form/documents/upload", methods=["POST"])
def dispo_form_documents_upload():
    permission_response = require_dispo_form_access()
    if permission_response:
        return permission_response

    submitter = current_dispo_form_submitter()
    document_type = safe_str(request.form.get("document_type"), "freight_papers")[:80]
    reference = safe_str(request.form.get("reference"))[:160]
    note = safe_str(request.form.get("note"))[:2000]
    status = normalize_dispo_form_status(request.form.get("status"))
    tax_mode = safe_str(request.form.get("tax_mode"), "eifellog_internal")[:80]
    amount_net, tax_rate, tax_amount, amount_gross = calculate_dispo_form_tax(
        request.form.get("amount_net"),
        request.form.get("tax_rate", 19),
        tax_mode,
    )

    if len(reference) < 2:
        flash("Bitte eine Referenz zur Tour oder zum Auftrag eintragen.", "error")
        return redirect(url_for("dispo_form"))

    uploaded_files = request.files.getlist("documents")
    uploaded_files = [file for file in uploaded_files if file and file.filename]

    if not uploaded_files:
        flash("Bitte mindestens einen Beleg oder ein Frachtpapier hochladen.", "error")
        return redirect(url_for("dispo_form"))

    entry_id = uuid.uuid4().hex

    try:
        saved_files = save_dispo_form_uploaded_files(entry_id, uploaded_files)
    except ValueError as error:
        flash(str(error), "error")
        return redirect(url_for("dispo_form"))
    except Exception as error:
        print(f"Dispo-Form Upload fehlgeschlagen: {error}")
        flash("Upload fehlgeschlagen. Bitte später erneut versuchen.", "error")
        return redirect(url_for("dispo_form"))

    if not saved_files:
        flash("Es konnte keine gültige Datei gespeichert werden.", "error")
        return redirect(url_for("dispo_form"))

    now = now_utc()
    entry_type = "damage" if document_type == "damage_receipt" else "income"
    entry_doc = {
        "entry_id": entry_id,
        "entry_source": "document",
        "entry_type": entry_type,
        "document_type": document_type,
        "reference": reference,
        "title": dispo_form_document_type_label(document_type),
        "note": note,
        "amount_net": amount_net,
        "tax_rate": tax_rate,
        "tax_amount": tax_amount,
        "amount_gross": amount_gross,
        "tax_mode": tax_mode,
        "currency": "EUR",
        "status": status,
        "files": saved_files,
        "submitted_by": submitter,
        "archived": False,
        "created_at": now,
        "updated_at": now,
    }

    dispo_form_entries_collection.insert_one(entry_doc)
    dispo_messages_collection.insert_one({
        "message_id": uuid.uuid4().hex,
        "title": "Neue Frachtpapiere eingereicht",
        "content": f"{submitter.get('display_name')} hat {len(saved_files)} Datei(en) für {reference} eingereicht.",
        "priority": "high" if document_type == "damage_receipt" else "normal",
        "archived": False,
        "created_at": now,
        "created_by": submitter,
        "dispo_form_entry_id": entry_id,
    })

    flash("Beleg wurde hochgeladen und ist für die Disposition sichtbar.", "success")
    return redirect(url_for("dispo_form"))


@app.route("/dispo/form/file/<entry_id>/<filename>", methods=["GET"])
def dispo_form_file_download(entry_id, filename):
    permission_response = require_dispo_form_access()
    if permission_response:
        return permission_response

    entry_doc = dispo_form_entries_collection.find_one(dispo_form_entry_lookup_query(entry_id))
    if not entry_doc or entry_doc.get("archived") is True:
        abort(404)

    user = session.get("user") or {}
    user_roles = user.get("roles", [])
    submitted_by = entry_doc.get("submitted_by") or {}
    current_discord_id = safe_str(user.get("id"))
    entry_submitter_id = safe_str(submitted_by.get("discord_id") or entry_doc.get("submitted_by_id"))

    can_open_file = (
        has_dispo_submitted_documents_permission(user_roles)
        or (current_discord_id and entry_submitter_id and current_discord_id == entry_submitter_id)
    )
    if not can_open_file:
        abort(403)

    filename = secure_filename(filename)
    matched_file = None
    for file_item in entry_doc.get("files") or []:
        if secure_filename(file_item.get("stored_filename")) == filename:
            matched_file = file_item
            break

    if not matched_file:
        abort(404)

    absolute_path = os.path.abspath(os.path.join(BASE_DIR, matched_file.get("relative_path", "")))
    upload_root = os.path.abspath(resolve_dispo_form_upload_folder())

    if not absolute_path.startswith(upload_root) or not os.path.exists(absolute_path):
        abort(404)

    return send_file(
        absolute_path,
        as_attachment=False,
        download_name=matched_file.get("original_filename") or filename,
    )


@app.route("/dispo/form/<entry_id>/status", methods=["POST"])
def dispo_form_update_status(entry_id):
    permission_response = require_dispo_form_access()
    if permission_response:
        return permission_response

    user_roles = session.get("user", {}).get("roles", [])
    if not has_dispo_submitted_documents_permission(user_roles):
        if request.is_json:
            return jsonify({"success": False, "message": "Nur die Disposition darf den Status eingereichter Dokumente ändern."}), 403
        flash("Nur die Disposition darf den Status eingereichter Dokumente ändern.", "error")
        return redirect(url_for("dispo_form"))

    data = request.get_json(silent=True) or request.form or {}
    new_status = normalize_dispo_form_status(data.get("status"))
    actor = current_dispo_form_submitter()

    result = dispo_form_entries_collection.update_one(
        {**dispo_form_entry_lookup_query(entry_id), "archived": {"$ne": True}},
        {
            "$set": {
                "status": new_status,
                "reviewed_by": actor,
                "reviewed_at": now_utc(),
                "updated_at": now_utc(),
            }
        }
    )

    if result.matched_count == 0:
        if request.is_json:
            return jsonify({"success": False, "message": "Eintrag wurde nicht gefunden."}), 404
        flash("Eintrag wurde nicht gefunden.", "error")
        return redirect(url_for("dispo_form"))

    if request.is_json:
        return jsonify({"success": True, "status": new_status})

    flash("Status wurde aktualisiert.", "success")
    return redirect(url_for("dispo_form"))


@app.route("/dispo/form/users", methods=["GET"])
def dispo_form_users_api():
    permission_response = require_dispo_document_management_permission()
    if permission_response:
        return permission_response

    users = get_dispo_assignable_users()
    return jsonify({
        "success": True,
        "users": users,
        "count": len(users),
        "source": "eifellog_db.user/eifellog_db.users",
    })


@app.route("/dispo/form/documents/edit", methods=["POST"])
def dispo_form_document_edit():
    permission_response = require_dispo_document_management_permission()
    if permission_response:
        return permission_response

    document_id = safe_str(request.form.get("document_id"))
    if not document_id:
        flash("Dokument-ID fehlt.", "error")
        return redirect(url_for("dispo_form"))

    entry_doc = load_active_dispo_form_entry(document_id)
    if not entry_doc:
        flash("Dokument wurde nicht gefunden.", "error")
        return redirect(url_for("dispo_form"))

    reference = safe_str(request.form.get("reference"))[:160]
    title = safe_str(request.form.get("title"))[:180]
    amount_net_raw = request.form.get("amount_net")
    tax_rate_raw = request.form.get("tax_rate")

    update_fields = {
        "updated_at": now_utc(),
        "updated_by": current_disposition_identity(),
    }

    if reference:
        update_fields["reference"] = reference
    if title:
        update_fields["title"] = title

    has_amount = amount_net_raw is not None and safe_str(amount_net_raw) != ""
    has_tax_rate = tax_rate_raw is not None and safe_str(tax_rate_raw) != ""
    if has_amount or has_tax_rate:
        amount_source = amount_net_raw if has_amount else entry_doc.get("amount_net")
        tax_rate_source = tax_rate_raw if has_tax_rate else entry_doc.get("tax_rate", 19)
        tax_mode = safe_str(entry_doc.get("tax_mode"), "eifellog_internal")
        amount_net, tax_rate, tax_amount, amount_gross = calculate_dispo_form_tax(amount_source, tax_rate_source, tax_mode)
        update_fields.update({
            "amount_net": amount_net,
            "tax_rate": tax_rate,
            "tax_amount": tax_amount,
            "amount_gross": amount_gross,
        })

    dispo_form_entries_collection.update_one(
        {"_id": entry_doc["_id"]},
        {"$set": update_fields}
    )

    dispo_messages_collection.insert_one({
        "message_id": uuid.uuid4().hex,
        "title": "Dispo-Dokument bearbeitet",
        "content": f"Dokument {document_id} wurde durch die Disposition bearbeitet.",
        "priority": "normal",
        "archived": False,
        "created_at": now_utc(),
        "created_by": update_fields["updated_by"],
        "dispo_form_entry_id": safe_str(entry_doc.get("entry_id") or document_id),
    })

    flash("Änderungen wurden gespeichert.", "success")
    return redirect(url_for("dispo_form"))


@app.route("/dispo/form/documents/assign-user", methods=["POST"])
def dispo_form_document_assign_user():
    permission_response = require_dispo_document_management_permission()
    if permission_response:
        return permission_response

    document_id = safe_str(request.form.get("document_id"))
    assigned_user_id = safe_str(request.form.get("assigned_user_id"))

    if not document_id or not assigned_user_id:
        flash("Bitte Dokument und User auswählen.", "error")
        return redirect(url_for("dispo_form"))

    entry_doc = load_active_dispo_form_entry(document_id)
    if not entry_doc:
        flash("Dokument wurde nicht gefunden.", "error")
        return redirect(url_for("dispo_form"))

    user_doc = find_dispo_assignable_user(assigned_user_id)
    if not user_doc:
        flash("User wurde in eifellog_db.user / users nicht gefunden.", "error")
        return redirect(url_for("dispo_form"))

    assigned_user = dispo_user_public_payload(user_doc)
    actor = current_disposition_identity()
    now = now_utc()

    submitted_by = {
        "discord_id": safe_str(assigned_user.get("discord_id") or assigned_user.get("id")),
        "username": safe_str(assigned_user.get("username")),
        "display_name": safe_str(assigned_user.get("display_name") or assigned_user.get("username")),
        "roles": assigned_user.get("roles", []),
    }

    dispo_form_entries_collection.update_one(
        {"_id": entry_doc["_id"]},
        {
            "$set": {
                "submitted_by": submitted_by,
                "submitted_by_id": submitted_by["discord_id"],
                "submitted_by_name": submitted_by["display_name"],
                "assigned_user": submitted_by,
                "assigned_user_id": submitted_by["discord_id"],
                "assigned_by": actor,
                "assigned_at": now,
                "updated_at": now,
            }
        }
    )

    dispo_messages_collection.insert_one({
        "message_id": uuid.uuid4().hex,
        "title": "Einreicher zugeordnet",
        "content": f"Dokument {document_id} wurde {submitted_by['display_name']} zugeordnet.",
        "priority": "normal",
        "archived": False,
        "created_at": now,
        "created_by": actor,
        "dispo_form_entry_id": safe_str(entry_doc.get("entry_id") or document_id),
    })

    flash("Einreicher wurde zugeordnet und gespeichert.", "success")
    return redirect(url_for("dispo_form"))


@app.route("/dispo/form/documents/review", methods=["POST"])
def dispo_form_document_review():
    permission_response = require_dispo_document_management_permission()
    if permission_response:
        return permission_response

    document_id = safe_str(request.form.get("document_id"))
    review_status_raw = safe_str(request.form.get("review_status"), "verified")
    review_note = safe_str(request.form.get("review_note"))[:2000]

    if not document_id:
        flash("Dokument-ID fehlt.", "error")
        return redirect(url_for("dispo_form"))

    entry_doc = load_active_dispo_form_entry(document_id)
    if not entry_doc:
        flash("Dokument wurde nicht gefunden.", "error")
        return redirect(url_for("dispo_form"))

    if review_status_raw == "needs_fix":
        new_status = "returned_incomplete"
    else:
        new_status = normalize_dispo_form_status(review_status_raw)

    actor = current_disposition_identity()
    now = now_utc()
    dispo_form_entries_collection.update_one(
        {"_id": entry_doc["_id"]},
        {
            "$set": {
                "status": new_status,
                "review_status": new_status,
                "review_note": review_note,
                "dispo_note": review_note,
                "reviewed_by": actor,
                "reviewed_at": now,
                "updated_at": now,
            }
        }
    )

    dispo_messages_collection.insert_one({
        "message_id": uuid.uuid4().hex,
        "title": "Dispo-Prüfung gespeichert",
        "content": f"Dokument {document_id} wurde mit Status {new_status} geprüft.",
        "priority": "high" if new_status in {"returned_incomplete", "rejected"} else "normal",
        "archived": False,
        "created_at": now,
        "created_by": actor,
        "dispo_form_entry_id": safe_str(entry_doc.get("entry_id") or document_id),
    })

    flash("Prüfung wurde gespeichert.", "success")
    return redirect(url_for("dispo_form"))


@app.route("/dispo/form/documents/sign", methods=["POST"])
def dispo_form_document_sign():
    permission_response = require_dispo_document_management_permission()
    if permission_response:
        return permission_response

    document_id = safe_str(request.form.get("document_id"))
    signer_name = safe_str(request.form.get("signer_name"))[:160]
    signature_text = safe_str(request.form.get("signature_text"))[:240]

    if not document_id or not signer_name or not signature_text:
        flash("Dokument-ID, Signatur-Name und Signatur müssen ausgefüllt sein.", "error")
        return redirect(url_for("dispo_form"))

    entry_doc = load_active_dispo_form_entry(document_id)
    if not entry_doc:
        flash("Dokument wurde nicht gefunden.", "error")
        return redirect(url_for("dispo_form"))

    actor = current_disposition_identity()
    now = now_utc()
    signature_record = {
        "name": signer_name,
        "text": signature_text,
        "signed_by": actor,
        "signed_at": now,
    }

    dispo_form_entries_collection.update_one(
        {"_id": entry_doc["_id"]},
        {
            "$set": {
                "status": "signed",
                "signature": signature_text,
                "signature_text": signature_text,
                "signed_by_name": signer_name,
                "signed_by": actor,
                "signed_at": now,
                "signature_record": signature_record,
                "updated_at": now,
            }
        }
    )

    dispo_messages_collection.insert_one({
        "message_id": uuid.uuid4().hex,
        "title": "Dispo-Dokument signiert",
        "content": f"Dokument {document_id} wurde von {signer_name} signiert.",
        "priority": "normal",
        "archived": False,
        "created_at": now,
        "created_by": actor,
        "dispo_form_entry_id": safe_str(entry_doc.get("entry_id") or document_id),
    })

    flash("Dokument wurde digital signiert.", "success")
    return redirect(url_for("dispo_form"))


@app.route("/dispo/form/documents/forward-management", methods=["POST"])
def dispo_form_document_forward_management():
    permission_response = require_dispo_document_management_permission()
    if permission_response:
        return permission_response

    document_id = safe_str(request.form.get("document_id"))
    management_note = safe_str(request.form.get("management_note"))[:2000]

    if not document_id:
        flash("Dokument-ID fehlt.", "error")
        return redirect(url_for("dispo_form"))

    entry_doc = load_active_dispo_form_entry(document_id)
    if not entry_doc:
        flash("Dokument wurde nicht gefunden.", "error")
        return redirect(url_for("dispo_form"))

    actor = current_disposition_identity()
    now = now_utc()
    dispo_form_entries_collection.update_one(
        {"_id": entry_doc["_id"]},
        {
            "$set": {
                "status": "management_pending",
                "management_status": "management_pending",
                "forwarded_to_management": True,
                "management_note": management_note,
                "forward_note": management_note,
                "forwarded_by": actor,
                "dispo_forwarded_by": actor,
                "forwarded_at": now,
                "dispo_forwarded_at": now,
                "updated_at": now,
            }
        }
    )

    submitted_by = entry_doc.get("submitted_by") or {}
    reference = safe_str(entry_doc.get("reference"), "-")
    user_name = safe_str(submitted_by.get("display_name") or submitted_by.get("username") or entry_doc.get("submitted_by_name"), "Unbekannt")

    dispo_messages_collection.insert_one({
        "message_id": uuid.uuid4().hex,
        "title": "Dokument an Geschäftsleitung weitergegeben",
        "content": f"Dokument {document_id} von {user_name} / {reference} wartet auf Entscheidung der Geschäftsleitung.",
        "priority": "high",
        "archived": False,
        "created_at": now,
        "created_by": actor,
        "dispo_form_entry_id": safe_str(entry_doc.get("entry_id") or document_id),
    })

    flash("Dokument wurde an die Geschäftsleitung weitergegeben.", "success")
    return redirect(url_for("dispo_form"))


# ==========================================
# GESCHÄFTSLEITUNG / DOKUMENTPRÜFUNG
# ==========================================

@app.route("/management", methods=["GET"])
@app.route("/geschaeftsfuehrung.html", methods=["GET"])
@app.route("/geschaeftsfuehrung", methods=["GET"])
@app.route("/geschaeftsleitung.html", methods=["GET"])
@app.route("/geschaeftsleitung/dokumente", methods=["GET"])
@app.route("/geschaeftsleitung", methods=["GET"])
def geschaeftsleitung():
    permission_response = require_geschaeftsleitung_permission()
    if permission_response:
        return permission_response

    user = session.get("user") or {}
    user_roles = user.get("roles", [])
    primary_role_name = get_primary_role_name(user_roles)

    if isinstance(session.get("user"), dict):
        permissions = set(item for item in session["user"].get("permissions", []) if item)
        permissions.add("management.documents")
        permissions.add("geschaeftsleitung.documents")
        session["user"]["can_view_geschaeftsleitung_documents"] = True
        session["user"]["can_view_management_documents"] = True
        session["user"]["permissions"] = sorted(permissions)
        session.modified = True
        user = session.get("user") or user

    documents = get_geschaeftsleitung_documents()
    counts = count_geschaeftsleitung_documents(documents)

    return render_template(
        "geschaeftsleitung.html",
        current_user=user,
        primary_role_name=primary_role_name,
        can_view_geschaeftsleitung_documents=True,
        can_view_management_documents=True,
        is_management_viewer=True,
        geschaeftsleitung_documents=documents,
        management_review_items=documents,
        dispo_forwarded_documents=documents,
        management_pending_count=counts["pending"],
        management_approved_count=counts["approved"],
        management_returned_count=counts["returned"],
        role_geschaeftsleitung_id=ROLE_GESCHAEFTSLEITUNG,
        role_geschaeftsfuehrung_id=ROLE_GESCHAEFTSFUEHRUNG_ID,
    )


@app.route("/geschaeftsleitung/dispo-documents/approve", methods=["POST"])
def geschaeftsleitung_approve_dispo_document():
    permission_response = require_geschaeftsleitung_permission()
    if permission_response:
        return permission_response

    document_id = safe_str(request.form.get("document_id"))
    approval_note = safe_str(request.form.get("approval_note"))[:2000]

    if not document_id:
        flash("Dokument-ID fehlt.", "error")
        return redirect(url_for("geschaeftsleitung"))

    actor = current_disposition_identity()
    now = now_utc()
    result = dispo_form_entries_collection.update_one(
        {**dispo_form_entry_lookup_query(document_id), "archived": {"$ne": True}},
        {
            "$set": {
                "management_status": "approved",
                "management_note": approval_note,
                "approval_note": approval_note,
                "management_reviewed_by": actor,
                "approved_by_management": actor,
                "management_reviewed_at": now,
                "management_approved_at": now,
                "updated_at": now,
            }
        }
    )

    if result.matched_count == 0:
        flash("Dokument wurde nicht gefunden.", "error")
        return redirect(url_for("geschaeftsleitung"))

    dispo_messages_collection.insert_one({
        "message_id": uuid.uuid4().hex,
        "title": "Geschäftsleitung hat Dokument freigegeben",
        "content": f"Dokument {document_id} wurde final freigegeben.",
        "priority": "normal",
        "document_id": document_id,
        "archived": False,
        "created_at": now,
        "created_by": actor,
    })

    flash("Dokument wurde durch die Geschäftsleitung freigegeben.", "success")
    return redirect(url_for("geschaeftsleitung"))


@app.route("/geschaeftsleitung/dispo-documents/return", methods=["POST"])
def geschaeftsleitung_return_dispo_document():
    permission_response = require_geschaeftsleitung_permission()
    if permission_response:
        return permission_response

    document_id = safe_str(request.form.get("document_id"))
    return_reason = safe_str(request.form.get("return_reason"))[:2000]
    mark_incomplete = request.form.get("mark_incomplete") == "1"

    if not document_id:
        flash("Dokument-ID fehlt.", "error")
        return redirect(url_for("geschaeftsleitung"))

    if len(return_reason) < 2:
        flash("Bitte gib einen Grund für die Rückgabe an.", "error")
        return redirect(url_for("geschaeftsleitung"))

    actor = current_disposition_identity()
    now = now_utc()
    set_fields = {
        "management_status": "returned_incomplete",
        "return_note": return_reason,
        "return_reason": return_reason,
        "management_note": return_reason,
        "management_reviewed_by": actor,
        "returned_by_management": actor,
        "management_reviewed_at": now,
        "management_returned_at": now,
        "updated_at": now,
    }

    if mark_incomplete:
        set_fields["status"] = "returned_incomplete"

    result = dispo_form_entries_collection.update_one(
        {**dispo_form_entry_lookup_query(document_id), "archived": {"$ne": True}},
        {"$set": set_fields}
    )

    if result.matched_count == 0:
        flash("Dokument wurde nicht gefunden.", "error")
        return redirect(url_for("geschaeftsleitung"))

    dispo_messages_collection.insert_one({
        "message_id": uuid.uuid4().hex,
        "title": "Geschäftsleitung hat Dokument zurückgegeben",
        "content": f"Dokument {document_id} wurde zurück an die Disposition gegeben: {return_reason}",
        "priority": "critical",
        "document_id": document_id,
        "archived": False,
        "created_at": now,
        "created_by": actor,
    })

    flash("Dokument wurde als nicht vollständig markiert und an die Disposition zurückgegeben.", "success")
    return redirect(url_for("geschaeftsleitung"))


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

    sync_fahrerkarte_requests_from_users(limit=500)

    servicecenter_fahrerkarte_cursor = fahrerkarte_requests_collection.find(
        {"archived": {"$ne": True}}
    ).sort([("created_at", DESCENDING)]).limit(250)
    servicecenter_fahrerkarte_requests = [
        prepare_fahrerkarte_request_for_personalabteilung(item)
        for item in servicecenter_fahrerkarte_cursor
    ]

    servicecenter_fahrerkarte_actions = {
        "list": url_for("api_personalabteilung_servicecenter_fahrerkarte_list"),
        "claim": url_for("api_personalabteilung_servicecenter_fahrerkarte_claim"),
        "approve": url_for("api_personalabteilung_servicecenter_fahrerkarte_approve"),
        "issue": url_for("api_personalabteilung_servicecenter_fahrerkarte_issue"),
        "reject": url_for("api_personalabteilung_servicecenter_fahrerkarte_reject"),
        "postpone": url_for("api_personalabteilung_servicecenter_fahrerkarte_postpone"),
        "webPage": url_for("personalabteilung_servicecenter_fahrerkarte_web"),
    }

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
        servicecenter_fahrerkarte_requests=servicecenter_fahrerkarte_requests,
        fahrerkarte_requests=servicecenter_fahrerkarte_requests,
        servicecenter_requests=servicecenter_fahrerkarte_requests,
        servicecenter_fahrerkarte_actions=servicecenter_fahrerkarte_actions,
        servicecenter_fahrerkarte_web_url=url_for("personalabteilung_servicecenter_fahrerkarte_web"),
        tasks=tasks
    )


FAHRERKARTE_WEB_ADMIN_TEMPLATE = r"""
<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ServiceCenter Fahrerkarte</title>
  <style>
    :root { --blue:#17345f; --line:#9bb5cf; --bg:#eef5fb; --green:#27d263; --red:#b3261e; }
    * { box-sizing: border-box; }
    body { margin:0; font-family: Inter, Arial, sans-serif; background:linear-gradient(135deg,#eef5fb,#d9e9f6); color:#112; }
    header { background:#17345f; color:white; padding:24px 32px; display:flex; justify-content:space-between; gap:16px; align-items:center; }
    header h1 { margin:0; font-size:24px; letter-spacing:.08em; text-transform:uppercase; }
    header p { margin:6px 0 0; color:#d8e8f7; }
    main { max-width:1220px; margin:0 auto; padding:28px; }
    .toolbar { display:flex; flex-wrap:wrap; gap:12px; align-items:center; margin-bottom:22px; }
    button, select, input, textarea { border-radius:12px; border:1px solid #a8bfd7; padding:11px 13px; font:inherit; }
    button { cursor:pointer; background:#17345f; color:white; font-weight:800; text-transform:uppercase; letter-spacing:.06em; border-color:#17345f; }
    button.secondary { background:white; color:#17345f; }
    button.success { background:#146c2e; border-color:#146c2e; }
    button.danger { background:#9f1d17; border-color:#9f1d17; }
    button:disabled { opacity:.55; cursor:not-allowed; }
    .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(360px,1fr)); gap:18px; }
    .case { background:rgba(255,255,255,.92); border:1px solid #b5c9dd; border-radius:22px; overflow:hidden; box-shadow:0 18px 38px rgba(23,52,95,.12); }
    .card { margin:16px; border-radius:18px; border:1px solid #668bb2; background:#dcecf8; overflow:hidden; position:relative; }
    .card-head { height:44px; background:#bcd5eb; display:flex; align-items:center; gap:12px; padding:0 14px; color:#17345f; font-weight:900; letter-spacing:.08em; }
    .eu { width:54px; height:30px; background:#17345f; color:white; display:grid; place-items:center; border-radius:4px; font-weight:900; }
    .not-official { margin-left:auto; color:#a32017; font-size:10px; }
    .card-body { display:grid; grid-template-columns:112px 1fr; gap:16px; padding:16px; }
    .avatar { width:108px; height:126px; border:1px solid #668bb2; background:white; object-fit:cover; }
    .fields p { margin:0 0 9px; font-size:13px; }
    .fields strong { font-size:18px; }
    .meta { padding:0 16px 16px; display:grid; grid-template-columns:1fr 1fr; gap:8px; font-size:12px; color:#26394c; }
    .status { display:inline-flex; padding:4px 9px; border-radius:999px; font-size:11px; font-weight:900; background:#e9f9ee; color:#146c2e; border:1px solid #9edbb0; }
    .actions { border-top:1px solid #dde8f1; padding:16px; display:grid; gap:10px; }
    .signature { display:grid; gap:8px; background:#f5f9fc; border:1px dashed #9bb5cf; padding:12px; border-radius:16px; }
    .row { display:flex; gap:8px; flex-wrap:wrap; }
    .msg { margin:0 0 14px; min-height:20px; font-weight:700; }
    .small { font-size:12px; color:#475b70; }
  </style>
</head>
<body>
<header>
  <div>
    <h1>ServiceCenter Fahrerkarte</h1>
    <p>Web-only: claimen, genehmigen, signieren, ausstellen und PDF im User-Postfach bereitstellen.</p>
  </div>
  <a href="{{ personal_url }}" style="color:white;font-weight:800">Zur Personalabteilung</a>
</header>
<main>
  <div class="toolbar">
    <select id="status">
      <option value="">Alle Status</option>
      <option value="pending">Offen</option>
      <option value="claimed">Geclaimt</option>
      <option value="approved">Genehmigt</option>
      <option value="issued">Ausgestellt</option>
      <option value="postponed">Zurückgestellt</option>
      <option value="rejected">Abgelehnt</option>
    </select>
    <button onclick="loadCases()">Aktualisieren</button>
    <span class="small">Sachbearbeiter-Signatur: exakt dein eingeloggter Anzeigename/Username.</span>
  </div>
  <p id="msg" class="msg"></p>
  <section id="cases" class="grid"></section>
</main>
<script>
const actions = {{ actions_json | safe }};
const staffName = {{ staff_name_json | safe }};
const casesEl = document.getElementById('cases');
const msgEl = document.getElementById('msg');
function setMsg(text, error=false){ msgEl.textContent = text || ''; msgEl.style.color = error ? '#9f1d17' : '#146c2e'; }
function esc(v){ return String(v ?? '').replace(/[&<>"']/g, s => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[s])); }
async function api(url, payload){
  const res = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload || {})});
  const data = await res.json().catch(()=>({success:false,message:'Ungültige Serverantwort'}));
  if(!res.ok || data.success === false) throw new Error(data.message || 'Aktion fehlgeschlagen');
  return data;
}
async function loadCases(){
  const status = document.getElementById('status').value;
  const url = actions.list + (status ? ('?status=' + encodeURIComponent(status)) : '');
  const res = await fetch(url);
  const data = await res.json();
  const items = data.requests || data.items || [];
  casesEl.innerHTML = items.map(renderCase).join('') || '<p>Keine Fahrerkarte-Anträge gefunden.</p>';
  setMsg(items.length + ' Antrag/Anträge geladen.');
}
function renderCase(item){
  const id = esc(item.request_id || item.id);
  const avatar = esc(item.avatar_url || '/static/eifellog.jpg');
  const canClaim = ['pending','open','postponed','approved'].includes(item.status);
  const canApprove = item.status === 'claimed';
  const canIssue = ['claimed','approved'].includes(item.status);
  const download = item.download_url ? `<a href="${esc(item.download_url)}" download><button class="success" type="button">PDF herunterladen</button></a>` : '';
  return `
  <article class="case" id="case-${id}">
    <div class="card">
      <div class="card-head"><span class="eu">EL</span><span>FAHRERKARTE</span><span class="not-official">KEIN AMTLICHES DOKUMENT</span></div>
      <div class="card-body">
        <img class="avatar" src="${avatar}" alt="Avatar" onerror="this.src='/static/eifellog.jpg'">
        <div class="fields">
          <p><strong>${esc(item.display_name || item.name)}</strong></p>
          <p>2. ${esc(item.role || item.role_name)}</p>
          <p>3. Beantragt: ${esc(item.created_at || item.requested_at)}</p>
          <p>4a Status: <span class="status">${esc(item.status_label || item.status)}</span></p>
          <p>5a System-ID: ${esc(item.system_id)}</p>
          <p>5b Karten-ID: ${esc(item.card_id || 'Wird bei Ausstellung erzeugt')}</p>
        </div>
      </div>
      <div class="meta"><span>Grund: ${esc(item.reason_label)}</span><span>Sachbearbeiter: ${esc(item.sachbearbeiter_name)}</span></div>
    </div>
    <div class="actions">
      <div class="row">
        <button ${canClaim?'':'disabled'} onclick="claimCase('${id}')">Claim</button>
        <button class="secondary" ${canApprove?'':'disabled'} onclick="approveCase('${id}')">Genehmigen</button>
        ${download}
      </div>
      <div class="signature">
        <label>Digitale Signatur des Sachbearbeiters</label>
        <input id="sig-${id}" value="${esc(staffName)}" placeholder="${esc(staffName)}">
        <textarea id="note-${id}" rows="2" placeholder="Ausstellungsvermerk">Fahrerkarte wurde im EifelLog Web-ServiceCenter ausgestellt.</textarea>
        <label class="small"><input id="confirm-${id}" type="checkbox"> Ich bestätige die korrekte Web-Signatur und Ausstellung.</label>
        <button class="success" ${canIssue?'':'disabled'} onclick="issueCase('${id}')">Signieren & ausstellen</button>
      </div>
      <div class="row">
        <button class="danger" onclick="rejectCase('${id}')">Ablehnen</button>
        <button class="secondary" onclick="postponeCase('${id}')">Zurückstellen</button>
      </div>
    </div>
  </article>`;
}
async function claimCase(id){ try{ const d=await api(actions.claim,{requestId:id}); setMsg(d.message); await loadCases(); }catch(e){ setMsg(e.message,true); } }
async function approveCase(id){ try{ const note=prompt('Genehmigungsvermerk','Fahrerkarte geprüft und genehmigt.')||''; const d=await api(actions.approve,{requestId:id,note}); setMsg(d.message); await loadCases(); }catch(e){ setMsg(e.message,true); } }
async function issueCase(id){
  try{
    const signature = document.getElementById('sig-'+id).value;
    const issueNote = document.getElementById('note-'+id).value;
    const signatureConfirmed = document.getElementById('confirm-'+id).checked;
    const d = await api(actions.issue,{requestId:id,signature,signatureConfirmed,issueNote,force:true});
    setMsg(d.message);
    if(d.downloadUrl) window.open(d.downloadUrl,'_blank');
    await loadCases();
  }catch(e){ setMsg(e.message,true); }
}
async function rejectCase(id){ try{ const reason=prompt('Ablehnungsgrund','')||'Kein Grund angegeben.'; const d=await api(actions.reject,{requestId:id,reason}); setMsg(d.message); await loadCases(); }catch(e){ setMsg(e.message,true); } }
async function postponeCase(id){ try{ const reason=prompt('Grund für Zurückstellung','Zur späteren Bearbeitung zurückgestellt.')||''; const d=await api(actions.postpone,{requestId:id,reason}); setMsg(d.message); await loadCases(); }catch(e){ setMsg(e.message,true); } }
loadCases();
</script>
</body>
</html>
"""


@app.route("/personalabteilung/servicecenter/fahrerkarte", methods=["GET"])
@app.route("/servicecenter/admin/fahrerkarte", methods=["GET"])
def personalabteilung_servicecenter_fahrerkarte_web():
    permission_response = require_personalabteilung_permission()
    if permission_response:
        return permission_response

    actor = current_staff_identity()
    actions = {
        "list": url_for("api_personalabteilung_servicecenter_fahrerkarte_list"),
        "claim": url_for("api_personalabteilung_servicecenter_fahrerkarte_claim"),
        "approve": url_for("api_personalabteilung_servicecenter_fahrerkarte_approve"),
        "issue": url_for("api_personalabteilung_servicecenter_fahrerkarte_issue"),
        "reject": url_for("api_personalabteilung_servicecenter_fahrerkarte_reject"),
        "postpone": url_for("api_personalabteilung_servicecenter_fahrerkarte_postpone"),
    }
    return render_template_string(
        FAHRERKARTE_WEB_ADMIN_TEMPLATE,
        actions_json=json.dumps(actions),
        staff_name_json=json.dumps(actor.get("display_name") or actor.get("username") or "Personalabteilung"),
        personal_url=url_for("personalabteilung"),
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
    driver_id = safe_str(data.get("driverId") or data.get("driver_id") or data.get("discordId") or data.get("discord_id") or data.get("userId"))
    title = safe_str(data.get("title") or data.get("subject"), "Dokument der Personalabteilung")
    message = safe_str(data.get("message") or data.get("content") or data.get("description"))
    doc_type = safe_str(data.get("type") or data.get("documentType") or data.get("docType"), "direct_document")
    needs_signature = bool_from_payload(data.get("needsSignature") or data.get("needs_signature"), fallback=False)
    important = bool_from_payload(data.get("important"), fallback=True)

    if not driver_id:
        return jsonify({"success": False, "message": "Fahrer-ID fehlt."}), 400

    user_doc = find_user_by_driver_identifier(driver_id)
    if not user_doc:
        return jsonify({"success": False, "message": "Fahrer nicht gefunden."}), 404

    actor = current_staff_identity()
    handler_name = actor.get("display_name") or "Personalabteilung"
    aktenzeichen = user_doc.get("aktenzeichen") or generate_aktenzeichen()

    # Sicherstellen, dass der Fahrer ein Aktenzeichen hat
    if not user_doc.get("aktenzeichen"):
        users_collection.update_one({"_id": user_doc["_id"]}, {"$set": {"aktenzeichen": aktenzeichen}})
        user_doc["aktenzeichen"] = aktenzeichen

    # Wenn im Dokument-Button "Ausstellen/Austellen" oder Fahrerkarte gesetzt ist:
    # PDF generieren, Fahrerkarte ausstellen und direkt als Download zurückgeben.
    if should_issue_fahrerkarte_from_document_payload(data, title=title, message=message):
        try:
            issue_result = auto_issue_fahrerkarte_for_user(
                user_doc,
                actor=actor,
                issue_note=message or "Fahrerkarte wurde über Dokument / Ausstellen ausgegeben.",
                force_pdf=True
            )
        except PermissionError as error:
            return jsonify({"success": False, "message": str(error)}), 403
        except Exception as error:
            return jsonify({"success": False, "message": f"Fahrerkarte konnte nicht ausgestellt werden: {error}"}), 500

        fresh_request = issue_result["request"]
        return jsonify({
            "success": True,
            "message": "Fahrerkarte wurde ausgestellt. Das PDF wurde erstellt, im Dokument hinterlegt und kann automatisch heruntergeladen werden.",
            "documentType": "driver_card_pdf",
            "status": "issued",
            "autoDownload": True,
            "downloadUrl": issue_result["download_url"],
            "downloadFilename": issue_result["pdf_filename"],
            "cardId": issue_result["card_id"],
            "requestId": fresh_request.get("request_id"),
            "request": prepare_fahrerkarte_request_for_personalabteilung(fresh_request),
        })

    if not title or not message:
        return jsonify({"success": False, "message": "Titel und Inhalt fehlen."}), 400

    content = f"""
        <p><strong>{title}</strong></p>
        <p class="mt-4">Dieses Dokument wurde direkt von der Personalabteilung an dich ausgestellt.</p>
        <p class="mt-4"><strong>Sachbearbeiter:</strong> {handler_name}<br><strong>Aktenzeichen:</strong> {aktenzeichen}</p>
        <div class="mt-5 rounded-2xl bg-black/50 border border-[var(--brand-blue)]/25 p-4">
            <p class="text-[10px] font-orbitron text-[var(--brand-blue)] uppercase tracking-widest mb-2">Nachricht / Inhalt</p>
            <p>{message}</p>
        </div>
    """

    document = create_system_document_for_user(
        user_doc.get("discord_id"),
        title,
        handler_name,
        content,
        doc_type=doc_type or "direct_document",
        needs_signature=needs_signature,
        extra={
            "important": important,
            "created_by": actor,
            "created_for_username": user_doc.get("username") or user_doc.get("discord_username"),
            "created_for_display_name": user_doc.get("display_name") or user_doc.get("username"),
            "source": "personalabteilung_driver_document_send",
        }
    )

    return jsonify({
        "success": True,
        "message": "Wichtiges Dokument ausgestellt.",
        "documentId": document.get("document_id"),
        "autoDownload": False,
    })


@app.route("/api/personalabteilung/driver/document/issue-fahrerkarte", methods=["POST"])
@app.route("/api/personalabteilung/driver/fahrerkarte/ausstellen", methods=["POST"])
def api_personalabteilung_issue_driver_fahrerkarte():
    permission_response = require_personalabteilung_api_permission()
    if permission_response: return permission_response

    data = request.get_json(silent=True) or {}
    request_id = safe_str(data.get("requestId") or data.get("request_id") or data.get("id"))
    driver_id = safe_str(data.get("driverId") or data.get("driver_id") or data.get("discordId") or data.get("discord_id") or data.get("userId"))
    issue_note = safe_str(data.get("note") or data.get("issueNote") or data.get("message") or data.get("description"), "Fahrerkarte wurde über Dokument / Ausstellen ausgestellt.")[:1000]

    actor = current_staff_identity()
    request_doc = None
    user_doc = None

    if request_id:
        request_doc = find_fahrerkarte_request(request_id)
        if not request_doc:
            return jsonify({"success": False, "message": "Fahrerkarte-Antrag wurde nicht gefunden."}), 404
        user_doc = find_user_for_request_doc(request_doc)
    elif driver_id:
        user_doc = find_user_by_driver_identifier(driver_id)
    else:
        return jsonify({"success": False, "message": "Fahrer-ID oder Request-ID fehlt."}), 400

    if not user_doc:
        return jsonify({"success": False, "message": "Fahrer nicht gefunden."}), 404

    try:
        issue_result = auto_issue_fahrerkarte_for_user(
            user_doc,
            actor=actor,
            issue_note=issue_note,
            request_doc=request_doc,
            force_pdf=bool_from_payload(data.get("force"), fallback=True)
        )
    except PermissionError as error:
        return jsonify({"success": False, "message": str(error)}), 403
    except Exception as error:
        return jsonify({"success": False, "message": f"Fahrerkarte konnte nicht ausgestellt werden: {error}"}), 500

    fresh_request = issue_result["request"]
    return jsonify({
        "success": True,
        "message": "Fahrerkarte wurde ausgestellt. PDF wurde erstellt und als Download bereitgestellt.",
        "status": "issued",
        "autoDownload": True,
        "downloadUrl": issue_result["download_url"],
        "downloadFilename": issue_result["pdf_filename"],
        "cardId": issue_result["card_id"],
        "requestId": fresh_request.get("request_id"),
        "request": prepare_fahrerkarte_request_for_personalabteilung(fresh_request),
    })


# ==========================================
# PERSONALABTEILUNG - SERVICECENTER FAHRERKARTE
# ==========================================

@app.route("/api/personalabteilung/servicecenter/fahrerkarte", methods=["GET"])
def api_personalabteilung_servicecenter_fahrerkarte_list():
    permission_response = require_personalabteilung_api_permission()
    if permission_response: return permission_response

    sync_fahrerkarte_requests_from_users(limit=500)

    status = safe_str(request.args.get("status"))
    query = {"archived": {"$ne": True}}
    if status:
        query["status"] = status

    items_cursor = fahrerkarte_requests_collection.find(query).sort([("created_at", DESCENDING)]).limit(250)
    items = [prepare_fahrerkarte_request_for_personalabteilung(item) for item in items_cursor]
    return jsonify({"success": True, "requests": items, "items": items})


@app.route("/api/personalabteilung/servicecenter/fahrerkarte/claim", methods=["POST"])
def api_personalabteilung_servicecenter_fahrerkarte_claim():
    permission_response = require_personalabteilung_api_permission()
    if permission_response: return permission_response

    data = request.get_json(silent=True) or {}
    request_id = safe_str(data.get("requestId") or data.get("id"))
    if not request_id:
        return jsonify({"success": False, "message": "Request-ID fehlt."}), 400

    request_doc = find_fahrerkarte_request(request_id)
    if not request_doc:
        return jsonify({"success": False, "message": "Fahrerkarte-Antrag wurde nicht gefunden."}), 404

    current_status = normalize_fahrerkarte_status(request_doc.get("status") or "pending")
    if current_status in {"issued", "rejected", "archived"}:
        return jsonify({"success": False, "message": "Dieser Fahrerkarte-Antrag ist bereits abgeschlossen."}), 409

    actor = current_staff_identity()
    now = now_utc()

    if current_status == "claimed":
        if request_is_claimed_by_actor(request_doc, actor):
            return jsonify({"success": True, "message": "Du hast diesen Fahrerkarte-Antrag bereits geclaimt.", "handlerName": actor.get("display_name"), "status": "claimed"})
        claimed_by = request_doc.get("claimed_by") or {}
        claimed_name = claimed_by.get("display_name") or claimed_by.get("username") or "einem anderen Sachbearbeiter"
        return jsonify({"success": False, "message": f"Dieser Fahrerkarte-Antrag ist bereits von {claimed_name} geclaimt."}), 409

    if current_status not in {"pending", "open", "postponed", "approved"}:
        return jsonify({"success": False, "message": f"Dieser Antrag kann im Status '{current_status}' nicht geclaimt werden."}), 409

    update = {
        "status": "claimed",
        "claimed_by": actor,
        "claimed_at": now,
        "handler_name": actor.get("display_name") or actor.get("username") or "Personalabteilung",
        "updated_at": now,
    }
    fahrerkarte_requests_collection.update_one({"_id": request_doc["_id"]}, {"$set": update})

    fresh_request = fahrerkarte_requests_collection.find_one({"_id": request_doc["_id"]})
    user_doc = find_user_for_request_doc(fresh_request)
    update_user_fahrerkarte_state(user_doc, fresh_request, "claimed", actor)
    servicecenter_discord_sync_fahrerkarte_request(fresh_request, event="claimed", actor=actor)

    return jsonify({
        "success": True,
        "message": "Fahrerkarte-Antrag wurde geclaimt. Du kannst ihn jetzt genehmigen, ausstellen, zurückstellen oder ablehnen.",
        "status": "claimed",
        "handlerName": actor.get("display_name"),
        "request": prepare_fahrerkarte_request_for_personalabteilung(fresh_request),
    })


@app.route("/api/personalabteilung/servicecenter/fahrerkarte/approve", methods=["POST"])
def api_personalabteilung_servicecenter_fahrerkarte_approve():
    permission_response = require_personalabteilung_api_permission()
    if permission_response: return permission_response

    data = request.get_json(silent=True) or {}
    request_id = safe_str(data.get("requestId") or data.get("id"))
    note = safe_str(data.get("note") or data.get("approvalNote") or data.get("reason"), "Fahrerkarte wurde genehmigt.")[:800]
    if not request_id:
        return jsonify({"success": False, "message": "Request-ID fehlt."}), 400

    request_doc = find_fahrerkarte_request(request_id)
    if not request_doc:
        return jsonify({"success": False, "message": "Fahrerkarte-Antrag wurde nicht gefunden."}), 404
    if normalize_fahrerkarte_status(request_doc.get("status")) in {"issued", "rejected", "archived"}:
        return jsonify({"success": False, "message": "Dieser Fahrerkarte-Antrag ist bereits abgeschlossen."}), 409

    user_doc = find_user_for_request_doc(request_doc)
    if not user_doc:
        return jsonify({"success": False, "message": "Der User zur Fahrerkarte wurde nicht gefunden."}), 404

    actor = current_staff_identity()
    claim_error = require_request_claimed_by_actor(request_doc, actor)
    if claim_error: return claim_error

    now = now_utc()
    handler_name = actor.get("display_name") or "Personalabteilung"

    update = {
        "status": "approved",
        "approved_by": actor,
        "approved_at": now,
        "approval_note": note,
        "handler_name": handler_name,
        "updated_at": now,
    }
    fahrerkarte_requests_collection.update_one({"_id": request_doc["_id"]}, {"$set": update})
    fresh_request = fahrerkarte_requests_collection.find_one({"_id": request_doc["_id"]})
    update_user_fahrerkarte_state(user_doc, fresh_request, "approved", actor, extra_set={"fahrerkarte_approved_at": now})

    create_system_document_for_user(
        user_doc.get("discord_id"),
        "Fahrerkarte genehmigt",
        handler_name,
        f'''
            <p><strong>Deine personalisierte Fahrerkarte wurde genehmigt.</strong></p>
            <p class="mt-4">Die Personalabteilung hat deinen Antrag geprüft und freigegeben. Die PDF-Ausstellung erfolgt im nächsten Schritt im ServiceCenter.</p>
            <div class="mt-5 rounded-2xl bg-black/50 border border-[var(--brand-green)]/25 p-4">
                <p class="text-[10px] font-orbitron text-[var(--brand-green)] uppercase tracking-widest mb-2">Bearbeitung</p>
                <p><strong>Sachbearbeiter:</strong> {handler_name}</p>
                <p><strong>Hinweis:</strong><br>{note}</p>
            </div>
        ''',
        doc_type="driver_card_approval",
        needs_signature=False,
        extra={"important": True, "request_id": fresh_request.get("request_id"), "fahrerkarte_request_id": fresh_request.get("request_id"), "contains_driver_card": True},
    )

    tasks_collection.update_many({"source": "servicecenter_fahrerkarte", "request_id": fresh_request.get("request_id")}, {"$set": {"status": "approved", "updated_at": now}})
    servicecenter_discord_sync_fahrerkarte_request(fresh_request, event="approved", actor=actor)

    return jsonify({
        "success": True,
        "message": "Fahrerkarte-Antrag wurde genehmigt. Er kann jetzt ausgestellt werden.",
        "status": "approved",
        "handlerName": handler_name,
        "request": prepare_fahrerkarte_request_for_personalabteilung(fresh_request),
    })


@app.route("/api/personalabteilung/servicecenter/fahrerkarte/issue", methods=["POST"])
def api_personalabteilung_servicecenter_fahrerkarte_issue():
    permission_response = require_personalabteilung_api_permission()
    if permission_response: return permission_response

    data = request.get_json(silent=True) or {}
    request_id = safe_str(data.get("requestId") or data.get("id"))
    issue_note = safe_str(data.get("note") or data.get("issueNote") or data.get("description"), "Fahrerkarte wurde im EifelLog ServiceCenter ausgestellt.")[:1000]
    force_pdf = bool_from_payload(data.get("force"), fallback=False)
    if not request_id:
        return jsonify({"success": False, "message": "Request-ID fehlt."}), 400

    request_doc = find_fahrerkarte_request(request_id)
    if not request_doc:
        return jsonify({"success": False, "message": "Fahrerkarte-Antrag wurde nicht gefunden."}), 404

    current_status = normalize_fahrerkarte_status(request_doc.get("status"))
    if current_status in {"rejected", "archived"}:
        return jsonify({"success": False, "message": "Abgelehnte oder archivierte Fahrerkarte-Anträge können nicht ausgestellt werden."}), 409

    user_doc = find_user_for_request_doc(request_doc)
    if not user_doc:
        return jsonify({"success": False, "message": "Der User zur Fahrerkarte wurde nicht gefunden."}), 404

    actor = current_staff_identity()
    if current_status == "claimed":
        claim_error = require_request_claimed_by_actor(request_doc, actor)
        if claim_error: return claim_error
    elif current_status == "approved":
        if not request_is_claimed_by_actor(request_doc, actor):
            claimed_by = request_doc.get("claimed_by") or {}
            claimed_name = claimed_by.get("display_name") or claimed_by.get("username") or "einem anderen Sachbearbeiter"
            return jsonify({"success": False, "message": f"Dieser Fahrerkarte-Antrag ist bereits von {claimed_name} geclaimt. Nur der zuständige Sachbearbeiter kann ihn ausstellen."}), 403
    else:
        return jsonify({"success": False, "message": "Dieser Fahrerkarte-Antrag muss zuerst geclaimt werden."}), 409

    signature_ok, signature_result = validate_fahrerkarte_issue_signature(data, actor, request_doc)
    if not signature_ok:
        return jsonify({"success": False, "message": signature_result}), 400
    signature_data = signature_result

    now = now_utc()
    handler_name = actor.get("display_name") or "Personalabteilung"
    card_id = safe_str(request_doc.get("card_id")) or generate_fahrerkarte_card_id(request_doc.get("discord_id"), request_doc.get("request_id"))

    pre_update = {
        "status": "issued",
        "card_id": card_id,
        "approved_by": request_doc.get("approved_by") or actor,
        "approved_at": request_doc.get("approved_at") or now,
        "issued_by": actor,
        "issued_at": now,
        "issue_note": issue_note,
        "handler_name": handler_name,
        "tracker_upload_ready": True,
        "updated_at": now,
    }
    pre_update.update(signature_data)

    temp_doc = dict(request_doc)
    temp_doc.update(pre_update)

    file_path, relative_path, filename, _pdf_bytes = save_fahrerkarte_pdf(temp_doc, user_doc=user_doc, actor=actor, force=force_pdf)

    final_update = dict(pre_update)
    final_update.update({
        "pdf_path": file_path,
        "pdf_relative_path": relative_path,
        "pdf_filename": filename,
        "download_url": servicecenter_fahrerkarte_download_url(request_doc.get("request_id") or request_doc.get("_id")),
    })
    fahrerkarte_requests_collection.update_one({"_id": request_doc["_id"]}, {"$set": final_update})
    fresh_request = fahrerkarte_requests_collection.find_one({"_id": request_doc["_id"]})

    update_user_fahrerkarte_state(user_doc, fresh_request, "issued", actor, extra_set={
        "fahrerkarte_issued_at": now,
        "fahrerkarte_pdf_relative_path": relative_path,
        "fahrerkarte_pdf_filename": filename,
        "fahrerkarte_download_url": servicecenter_fahrerkarte_download_url(fresh_request.get("request_id")),
    })

    create_fahrerkarte_pdf_dashboard_document(fresh_request, actor=actor, description=issue_note)

    tasks_collection.update_many({"source": "servicecenter_fahrerkarte", "request_id": fresh_request.get("request_id")}, {"$set": {"status": "done", "completed_at": now, "updated_at": now}})
    servicecenter_discord_sync_fahrerkarte_request(fresh_request, event="issued", actor=actor)
    servicecenter_discord_send_pdf_fallback(fresh_request, file_path, actor=actor, reason="Fahrerkarte ausgestellt / PDF-Fallback")

    return jsonify({
        "success": True,
        "message": "Fahrerkarte wurde ausgestellt. PDF wurde erstellt und dem User im Dashboard bereitgestellt.",
        "status": "issued",
        "handlerName": handler_name,
        "cardId": card_id,
        "downloadUrl": servicecenter_fahrerkarte_download_url(fresh_request.get("request_id")),
        "pdfPath": relative_path,
        "pdfFilename": filename,
        "request": prepare_fahrerkarte_request_for_personalabteilung(fresh_request),
    })


@app.route("/api/personalabteilung/servicecenter/fahrerkarte/reject", methods=["POST"])
def api_personalabteilung_servicecenter_fahrerkarte_reject():
    permission_response = require_personalabteilung_api_permission()
    if permission_response: return permission_response

    data = request.get_json(silent=True) or {}
    request_id = safe_str(data.get("requestId") or data.get("id"))
    reason = safe_str(data.get("reason"), "Kein Grund angegeben.")[:800]
    if not request_id:
        return jsonify({"success": False, "message": "Request-ID fehlt."}), 400

    request_doc = find_fahrerkarte_request(request_id)
    if not request_doc:
        return jsonify({"success": False, "message": "Fahrerkarte-Antrag wurde nicht gefunden."}), 404
    if normalize_fahrerkarte_status(request_doc.get("status")) in {"issued", "rejected", "archived"}:
        return jsonify({"success": False, "message": "Dieser Fahrerkarte-Antrag ist bereits abgeschlossen."}), 409

    user_doc = find_user_for_request_doc(request_doc)
    actor = current_staff_identity()
    claim_error = require_request_claimed_by_actor(request_doc, actor)
    if claim_error: return claim_error

    now = now_utc()
    handler_name = actor.get("display_name") or "Personalabteilung"

    fahrerkarte_requests_collection.update_one({"_id": request_doc["_id"]}, {"$set": {
        "status": "rejected",
        "rejected_by": actor,
        "rejected_at": now,
        "reject_reason": reason,
        "handler_name": handler_name,
        "updated_at": now,
    }})
    fresh_request = fahrerkarte_requests_collection.find_one({"_id": request_doc["_id"]})

    if user_doc:
        update_user_fahrerkarte_state(user_doc, fresh_request, "rejected", actor, extra_set={"fahrerkarte_rejected_at": now, "fahrerkarte_reject_reason": reason})
        create_system_document_for_user(
            user_doc.get("discord_id"),
            "Fahrerkarte abgelehnt",
            handler_name,
            rejection_document_content("Fahrerkarte abgelehnt", reason, handler_name),
            doc_type="driver_card_rejection",
            needs_signature=False,
            extra={"important": True, "request_id": fresh_request.get("request_id"), "fahrerkarte_request_id": fresh_request.get("request_id"), "contains_driver_card": True},
        )

    tasks_collection.update_many({"source": "servicecenter_fahrerkarte", "request_id": fresh_request.get("request_id")}, {"$set": {"status": "rejected", "updated_at": now}})
    servicecenter_discord_sync_fahrerkarte_request(fresh_request, event="rejected", actor=actor)

    return jsonify({
        "success": True,
        "message": "Fahrerkarte-Antrag wurde abgelehnt.",
        "status": "rejected",
        "handlerName": handler_name,
        "request": prepare_fahrerkarte_request_for_personalabteilung(fresh_request),
    })


@app.route("/api/personalabteilung/servicecenter/fahrerkarte/postpone", methods=["POST"])
def api_personalabteilung_servicecenter_fahrerkarte_postpone():
    permission_response = require_personalabteilung_api_permission()
    if permission_response: return permission_response

    data = request.get_json(silent=True) or {}
    request_id = safe_str(data.get("requestId") or data.get("id"))
    reason = safe_str(data.get("reason"), "Zur späteren Bearbeitung zurückgestellt.")[:800]
    postponed_until_raw = safe_str(data.get("postponedUntil") or data.get("until") or data.get("date"))
    if not request_id:
        return jsonify({"success": False, "message": "Request-ID fehlt."}), 400

    request_doc = find_fahrerkarte_request(request_id)
    if not request_doc:
        return jsonify({"success": False, "message": "Fahrerkarte-Antrag wurde nicht gefunden."}), 404

    current_status = normalize_fahrerkarte_status(request_doc.get("status"))
    if current_status in {"issued", "rejected", "archived"}:
        return jsonify({"success": False, "message": "Dieser Fahrerkarte-Antrag ist bereits abgeschlossen."}), 409

    actor = current_staff_identity()
    if current_status == "claimed" and not request_is_claimed_by_actor(request_doc, actor):
        claimed_by = request_doc.get("claimed_by") or {}
        claimed_name = claimed_by.get("display_name") or claimed_by.get("username") or "einem anderen Sachbearbeiter"
        return jsonify({"success": False, "message": f"Dieser Fahrerkarte-Antrag ist bereits von {claimed_name} geclaimt."}), 403

    postponed_until = None
    if postponed_until_raw:
        try:
            postponed_until = datetime.fromisoformat(postponed_until_raw.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            postponed_until = None

    now = now_utc()
    handler_name = actor.get("display_name") or "Personalabteilung"
    update = {
        "status": "postponed",
        "postponed_by": actor,
        "postponed_at": now,
        "postpone_reason": reason,
        "claimed_by": actor,
        "handler_name": handler_name,
        "updated_at": now,
    }
    if postponed_until:
        update["postponed_until"] = postponed_until

    fahrerkarte_requests_collection.update_one({"_id": request_doc["_id"]}, {"$set": update})
    fresh_request = fahrerkarte_requests_collection.find_one({"_id": request_doc["_id"]})
    user_doc = find_user_for_request_doc(fresh_request)

    if user_doc:
        update_user_fahrerkarte_state(user_doc, fresh_request, "postponed", actor, extra_set={"fahrerkarte_postpone_reason": reason, "fahrerkarte_postponed_at": now})
        create_system_document_for_user(
            user_doc.get("discord_id"),
            "Fahrerkarte zurückgestellt",
            handler_name,
            f'''
                <p><strong>Deine Fahrerkarte-Beantragung wurde zurückgestellt.</strong></p>
                <p class="mt-4">Die Personalabteilung benötigt noch Zeit oder weitere Prüfung.</p>
                <div class="mt-5 rounded-2xl bg-black/50 border border-[var(--brand-green)]/25 p-4">
                    <p class="text-[10px] font-orbitron text-[var(--brand-green)] uppercase tracking-widest mb-2">Wiedervorlage</p>
                    <p><strong>Sachbearbeiter:</strong> {handler_name}</p>
                    <p><strong>Grund:</strong><br>{reason}</p>
                    <p><strong>Bis:</strong> {format_datetime_for_template(postponed_until) if postponed_until else 'Noch offen'}</p>
                </div>
            ''',
            doc_type="driver_card_postponed",
            needs_signature=False,
            extra={"important": True, "request_id": fresh_request.get("request_id"), "fahrerkarte_request_id": fresh_request.get("request_id"), "contains_driver_card": True},
        )

    tasks_collection.update_many({"source": "servicecenter_fahrerkarte", "request_id": fresh_request.get("request_id")}, {"$set": {"status": "postponed", "updated_at": now}})
    servicecenter_discord_sync_fahrerkarte_request(fresh_request, event="postponed", actor=actor)

    return jsonify({
        "success": True,
        "message": "Fahrerkarte-Antrag wurde zurückgestellt.",
        "status": "postponed",
        "handlerName": handler_name,
        "request": prepare_fahrerkarte_request_for_personalabteilung(fresh_request),
    })


@app.route("/api/personalabteilung/servicecenter/fahrerkarte/discord-sync", methods=["POST"])
def api_personalabteilung_servicecenter_fahrerkarte_discord_sync():
    permission_response = require_personalabteilung_api_permission()
    if permission_response: return permission_response

    data = request.get_json(silent=True) or {}
    request_id = safe_str(data.get("requestId") or data.get("id"))
    if not request_id:
        return jsonify({"success": False, "message": "Request-ID fehlt."}), 400

    request_doc = find_fahrerkarte_request(request_id)
    if not request_doc:
        return jsonify({"success": False, "message": "Fahrerkarte-Antrag wurde nicht gefunden."}), 404

    result = servicecenter_discord_sync_fahrerkarte_request(request_doc, event="updated", actor=current_staff_identity())
    fresh_request = find_fahrerkarte_request(request_id) or request_doc
    return jsonify({
        "success": True,
        "message": "Web-only ServiceCenter geprüft. Discord-Sync ist deaktiviert und wird nicht mehr verwendet.",
        "result": result,
        "request": prepare_fahrerkarte_request_for_personalabteilung(fresh_request),
    })


@app.route("/servicecenter/fahrerkarte/download/<request_id>", methods=["GET"])
def servicecenter_fahrerkarte_download(request_id):
    if "user" not in session:
        flash("Bitte logge dich zuerst ein.", "error")
        return redirect(url_for("hub"))

    request_doc = find_fahrerkarte_request(request_id)
    if not request_doc:
        abort(404)

    session_user = session.get("user") or {}
    session_discord_id = safe_str(session_user.get("id"))
    user_roles = session_user.get("roles", [])
    is_owner = session_discord_id and session_discord_id == safe_str(request_doc.get("discord_id") or request_doc.get("user_id"))
    is_staff = has_personalabteilung_permission(user_roles)
    if not is_owner and not is_staff:
        abort(403)

    pdf_path = request_doc.get("pdf_path") or request_doc.get("pdf_relative_path")
    resolved_path = resolve_fahrerkarte_pdf_path(pdf_path)

    if not resolved_path or not os.path.exists(resolved_path):
        if normalize_fahrerkarte_status(request_doc.get("status")) == "issued":
            user_doc = find_user_for_request_doc(request_doc)
            file_path, relative_path, filename, _pdf_bytes = save_fahrerkarte_pdf(request_doc, user_doc=user_doc, actor=request_doc.get("issued_by") or {}, force=True)
            fahrerkarte_requests_collection.update_one({"_id": request_doc["_id"]}, {"$set": {"pdf_path": file_path, "pdf_relative_path": relative_path, "pdf_filename": filename, "updated_at": now_utc()}})
            resolved_path = file_path
            request_doc["pdf_filename"] = filename
        else:
            abort(404)

    download_name = request_doc.get("pdf_filename") or os.path.basename(resolved_path)
    return send_file(resolved_path, mimetype="application/pdf", as_attachment=True, download_name=download_name)

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
            "/api/tracker/driver-card", "/api/tracker/driver-card/upload",
            "/api/tracker/work-session", "/api/tracker/jobs/start",
            "/api/tracker/tour/submit", "/api/tracker/job/complete", "/api/tracker/logout",
            "/webhook", "/api/tracker/webhook", "/api/tracker/discord/webhook"
        ]
    })


# ==========================================
# SERVER START
# ==========================================

if __name__ == "__main__":
    print(f"Starte Eifel LOG Server mit MongoDB DB '{MONGO_DB_NAME}' und Eventlet auf {SERVER_HOST}:{SERVER_PORT}...")
    eventlet.wsgi.server(eventlet.listen((SERVER_HOST, SERVER_PORT)), app)