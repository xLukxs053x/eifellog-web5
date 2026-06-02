"""Zentrale EifelLog-Konfiguration.

Diese Datei enthält ausschließlich .env-Lesen und Konfigurationswerte.
Keine Flask-Routen und keine MongoDB-Abfragen gehören hier hinein.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
BASE_DIR = str(PROJECT_ROOT)
ENV_PATH = str(PROJECT_ROOT / ".env")

load_dotenv(dotenv_path=ENV_PATH, override=True)


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


def env_list(*names):
    """Liest kommagetrennte, semikolongetrennte oder mehrzeilige .env-Listen robust ein."""
    values = []
    for name in names:
        raw_value = os.getenv(name)
        if raw_value is None:
            continue
        for item in re.split(r"[,;\n\r]+", str(raw_value)):
            item = item.strip()
            if item and item not in values:
                values.append(item)
    return values


PROFILE_UPLOAD_FOLDER = os.path.join("static", "uploads", "profiles")
ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}

TRACKER_API_KEY = os.getenv("TRACKER_API_KEY", "").strip()

# Discord Webhook für Job-Abschluss-Meldungen vom Tracker.
# Webhook-URLs ausschließlich über .env setzen.
DISCORD_JOB_COMPLETE_WEBHOOK_URL = (
    os.getenv("DISCORD_JOB_COMPLETE_WEBHOOK_URL")
    or os.getenv("DISCORD_TOUR_WEBHOOK_URL")
    or os.getenv("TOUR_CHANNEL_WEBHOOK_URL")
    or os.getenv("DISCORD_TOUREN_WEBHOOK_URL")
    or os.getenv("TOUREN_WEBHOOK_URL")
    or os.getenv("DISCORD_WEBHOOK_URL")
    or os.getenv("DISCORD_WEBHOOK")
    or os.getenv("WEBHOOK_URL")
    or ""
).strip()

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
BUCHHALTUNG_PDF_UPLOAD_FOLDER = env_first(
    "BUCHHALTUNG_PDF_UPLOAD_FOLDER",
    "BUCHHALTUNG_ARCHIVE_UPLOAD_FOLDER",
    "ACCOUNTING_PDF_UPLOAD_FOLDER",
    default=os.path.join("static", "uploads", "buchhaltung_pdfs")
)
ALLOWED_BUCHHALTUNG_PDF_EXTENSIONS = {"pdf"}
BUCHHALTUNG_PDF_MAX_BYTES = int(env_float(
    "BUCHHALTUNG_PDF_MAX_MB",
    "ACCOUNTING_PDF_MAX_MB",
    default=8
) * 1024 * 1024)
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
TRACKER_JOB_START_PUBLIC_URL = env_first(
    "TRACKER_JOB_START_PUBLIC_URL",
    "TRACKER_JOBS_START_PUBLIC_URL",
    default="https://www.eifellog.de/api/tracker/jobs/start"
)

TRACKER_PDF_DOWNLOAD_TICKET_LIFETIME_SECONDS = max(60, min(3600, int(env_float(
    "TRACKER_PDF_DOWNLOAD_TICKET_LIFETIME_SECONDS",
    "FAHRERKARTE_AUSZUG_DOWNLOAD_TICKET_SECONDS",
    default=600,
))))
TRACKER_PDF_DOWNLOAD_SIGNING_KEY = env_first(
    "TRACKER_PDF_DOWNLOAD_SIGNING_KEY",
    "FLASK_SECRET_KEY",
    default="",
)

TRACKER_SHIFT_PDF_LAYOUT_VERSION = "eifellog-ticket-theme-v3"
SERVICECENTER_FAHRERKARTE_PDF_LAYOUT_VERSION = "eifellog-fahrerkarte-bestaetigung-v6-qr-bildungen"

TOUR_START_DUPLICATE_WINDOW_MINUTES = int(env_float(
    "TOUR_START_DUPLICATE_WINDOW_MINUTES",
    "JOB_START_WEBHOOK_DUPLICATE_WINDOW_MINUTES",
    default=2
))
TOUR_COMPLETED_BLOCKS_RESTART_MINUTES = int(env_float(
    "TOUR_COMPLETED_BLOCKS_RESTART_MINUTES",
    default=0
))
TOUR_START_AFTER_COMPLETION_SUPPRESS_SECONDS = int(env_float(
    "TOUR_START_AFTER_COMPLETION_SUPPRESS_SECONDS",
    "TRACKER_TOUR_RESTART_GRACE_SECONDS",
    default=180
))

# Discord OAuth2
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
DISCORD_REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI")
DISCORD_GUILD_ID = os.getenv("DISCORD_GUILD_ID")

OAUTH_URL = "https://discord.com/api/oauth2/authorize"
TOKEN_URL = "https://discord.com/api/oauth2/token"
API_BASE_URL = "https://discord.com/api/v10"

# MongoDB
MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "eifellog_db")

LOA_MONGO_URI = env_first("LOA_MONGO_URI", "MONGO_URI", default=MONGO_URI)
LOA_DB_NAME = env_first(
    "LOA_DB_NAME",
    "MONGO_LOA_DB_NAME",
    "EIFELLOG_LOA_DB_NAME",
    default="EifelLog"
)
LOA_COLLECTION_NAME = env_first(
    "LOA_COLLECTION_NAME",
    "MONGO_LOA_COLLECTION_NAME",
    "EIFELLOG_LOA_COLLECTION_NAME",
    default="LOA"
)
