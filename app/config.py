"""Zentrale EifelLog-Konfiguration.

Diese Datei enthält ausschließlich das Lesen von Umgebungsvariablen und
zentrale Konfigurationswerte. Flask-Routen, MongoDB-Abfragen und fachliche
Business-Logik gehören nicht in dieses Modul.

Tracker-Architektur:
- Tourstart-Embeds und Abschluss-PDF-Belege werden serverseitig durch Python
  erzeugt und an Discord gesendet.
- Beide Nachrichtentypen landen verbindlich im selben Discord-Channel.
- Der feste Zielchannel kann absichtlich nicht durch Payloads oder abweichende
  .env-Werte überschrieben werden.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Final

from dotenv import load_dotenv


# ---------------------------------------------------------------------------
# Projektpfade / .env
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BASE_DIR = str(PROJECT_ROOT)
ENV_PATH = str(PROJECT_ROOT / ".env")

# Bestehendes Produktionsverhalten beibehalten: Werte aus der Projekt-.env
# haben Vorrang vor bereits gesetzten Prozesswerten.
load_dotenv(dotenv_path=ENV_PATH, override=True)


# ---------------------------------------------------------------------------
# Robuste .env-Helfer
# ---------------------------------------------------------------------------

def env_first(*names: str, default=""):
    """Liefert den ersten nicht-leeren Wert aus mehreren .env-Aliasen."""
    for name in names:
        value = os.getenv(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return default


def env_bool(*names: str, default: bool = False) -> bool:
    """Liest einen booleschen .env-Wert mit deutschen und englischen Aliasen."""
    value = env_first(*names, default="")
    if value == "":
        return bool(default)
    return str(value).strip().lower() in {
        "1",
        "true",
        "yes",
        "ja",
        "on",
        "enabled",
        "enable",
        "aktiv",
    }


def env_float(*names: str, default: float = 0.0) -> float:
    """Liest eine Gleitkommazahl; Komma und Punkt werden unterstützt."""
    value = env_first(*names, default="")
    if value == "":
        return float(default)
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return float(default)


def env_int(*names: str, default: int = 0) -> int:
    """Liest eine Ganzzahl robust; auch Werte wie ``2.0`` bleiben kompatibel."""
    return int(env_float(*names, default=float(default)))


def env_list(*names: str) -> list[str]:
    """Liest kommagetrennte, semikolongetrennte oder mehrzeilige .env-Listen."""
    values: list[str] = []
    for name in names:
        raw_value = os.getenv(name)
        if raw_value is None:
            continue
        for item in re.split(r"[,;\n\r]+", str(raw_value)):
            item = item.strip()
            if item and item not in values:
                values.append(item)
    return values


def _validated_discord_snowflake(value: str, *, setting_name: str) -> str:
    """Validiert eine Discord-ID ohne eine Discord-Netzwerkanfrage auszuführen."""
    normalized = str(value or "").strip()
    if not normalized.isdigit():
        raise RuntimeError(f"{setting_name} muss eine numerische Discord-ID sein.")
    return normalized


# ---------------------------------------------------------------------------
# Allgemeine Uploads
# ---------------------------------------------------------------------------

PROFILE_UPLOAD_FOLDER = os.path.join("static", "uploads", "profiles")
ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}

DISPO_FORM_UPLOAD_FOLDER = env_first(
    "DISPO_FORM_UPLOAD_FOLDER",
    "DISPO_BELEG_UPLOAD_FOLDER",
    default=os.path.join("static", "uploads", "dispo_form"),
)
ALLOWED_DISPO_FORM_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "webp"}

BUCHHALTUNG_PDF_UPLOAD_FOLDER = env_first(
    "BUCHHALTUNG_PDF_UPLOAD_FOLDER",
    "BUCHHALTUNG_ARCHIVE_UPLOAD_FOLDER",
    "ACCOUNTING_PDF_UPLOAD_FOLDER",
    default=os.path.join("static", "uploads", "buchhaltung_pdfs"),
)
ALLOWED_BUCHHALTUNG_PDF_EXTENSIONS = {"pdf"}
BUCHHALTUNG_PDF_MAX_BYTES = max(
    1,
    env_int("BUCHHALTUNG_PDF_MAX_MB", "ACCOUNTING_PDF_MAX_MB", default=8),
) * 1024 * 1024


# ---------------------------------------------------------------------------
# Tracker-Authentifizierung
# ---------------------------------------------------------------------------

TRACKER_API_KEY = env_first(
    "TRACKER_API_KEY",
    "EIFELLOG_TRACKER_API_KEY",
    default="",
)

# Optionaler Standard-Token für interne Clients. Nutzerbezogene Tracker-Tokens
# werden weiterhin fachlich über MongoDB validiert.
TRACKER_CLIENT_TOKEN = env_first(
    "TRACKER_CLIENT_TOKEN",
    "EIFELLOG_TRACKER_CLIENT_TOKEN",
    default="",
)


# ---------------------------------------------------------------------------
# Tracker / Discord: verbindlicher Channel für Start-Embed und Abschluss-PDF
# ---------------------------------------------------------------------------

# Fachliche Vorgabe: Tourstart-Embed und Abschluss-PDF-Beleg müssen immer in
# exakt diesem Channel landen. Der Wert ist bewusst kein .env-Schalter.
FORCED_TOUR_DISCORD_CHANNEL_ID: Final[str] = _validated_discord_snowflake(
    "1473756766478270517",
    setting_name="FORCED_TOUR_DISCORD_CHANNEL_ID",
)

# Kompatibilitätsaliase für bestehende und schrittweise ausgelagerte Services.
# Sämtliche Aliase zeigen absichtlich auf denselben unveränderlichen Wert.
TOUR_DISCORD_CHANNEL_ID = FORCED_TOUR_DISCORD_CHANNEL_ID
TRACKER_DISCORD_CHANNEL_ID = FORCED_TOUR_DISCORD_CHANNEL_ID
TOUR_CHANNEL_ID = FORCED_TOUR_DISCORD_CHANNEL_ID
TOUR_START_CHANNEL_ID = FORCED_TOUR_DISCORD_CHANNEL_ID
TOUR_START_DISCORD_CHANNEL_ID = FORCED_TOUR_DISCORD_CHANNEL_ID
TOUR_RECEIPT_CHANNEL_ID = FORCED_TOUR_DISCORD_CHANNEL_ID
TOUR_RECEIPT_DISCORD_CHANNEL_ID = FORCED_TOUR_DISCORD_CHANNEL_ID
DISCORD_TOUR_CHANNEL_ID = FORCED_TOUR_DISCORD_CHANNEL_ID
TOUREN_CHANNEL_ID = FORCED_TOUR_DISCORD_CHANNEL_ID
DISCORD_TOUREN_CHANNEL_ID = FORCED_TOUR_DISCORD_CHANNEL_ID
DISCORD_ABRECHNUNG_CHANNEL_ID = FORCED_TOUR_DISCORD_CHANNEL_ID
ABRECHNUNG_CHANNEL_ID = FORCED_TOUR_DISCORD_CHANNEL_ID

# Auch Module, die außerhalb von app.config direkt auf os.environ zugreifen,
# erhalten denselben verbindlichen Zielchannel. Abweichende .env-Werte werden
# absichtlich überschrieben.
for _channel_environment_name in (
    "TOUR_DISCORD_CHANNEL_ID",
    "TRACKER_DISCORD_CHANNEL_ID",
    "TOUR_CHANNEL_ID",
    "TOUR_START_CHANNEL_ID",
    "TOUR_START_DISCORD_CHANNEL_ID",
    "TOUR_RECEIPT_CHANNEL_ID",
    "TOUR_RECEIPT_DISCORD_CHANNEL_ID",
    "DISCORD_TOUR_CHANNEL_ID",
    "TOUREN_CHANNEL_ID",
    "DISCORD_TOUREN_CHANNEL_ID",
    "DISCORD_ABRECHNUNG_CHANNEL_ID",
    "ABRECHNUNG_CHANNEL_ID",
):
    os.environ[_channel_environment_name] = FORCED_TOUR_DISCORD_CHANNEL_ID

DISCORD_BOT_TOKEN = env_first(
    "DISCORD_BOT_TOKEN",
    "BOT_TOKEN",
    "DISCORD_TOKEN",
    default="",
)

# Webhook-URLs enthalten sensible Tokens und gehören ausschließlich in die
# .env. Die Business-Logik muss vor einem Webhook-Fallback zusätzlich per
# Discord-API prüfen, dass der Webhook wirklich zum festen Tour-Channel gehört.
DISCORD_JOB_COMPLETE_WEBHOOK_URL = env_first(
    "DISCORD_JOB_COMPLETE_WEBHOOK_URL",
    "DISCORD_TOUR_WEBHOOK_URL",
    "TOUR_CHANNEL_WEBHOOK_URL",
    "DISCORD_TOUREN_WEBHOOK_URL",
    "TOUREN_WEBHOOK_URL",
    "DISCORD_WEBHOOK_URL",
    "DISCORD_WEBHOOK",
    "WEBHOOK_URL",
    default="",
)
DISCORD_TOUR_WEBHOOK_URL = env_first(
    "DISCORD_TOUR_WEBHOOK_URL",
    "TOUR_CHANNEL_WEBHOOK_URL",
    "DISCORD_TOUREN_WEBHOOK_URL",
    "TOUREN_WEBHOOK_URL",
    default=DISCORD_JOB_COMPLETE_WEBHOOK_URL,
)
TOUR_CHANNEL_WEBHOOK_URL = DISCORD_TOUR_WEBHOOK_URL
TOUR_WEBHOOK_REQUIRE_FIXED_CHANNEL = True

TOUR_START_DISCORD_ENABLED = env_bool(
    "TOUR_START_DISCORD_ENABLED",
    "DISCORD_TOUR_START_ENABLED",
    default=True,
)
TOUR_RECEIPT_ENABLED = env_bool("TOUR_RECEIPT_ENABLED", default=True)
TOUR_RECEIPT_DISCORD_ENABLED = env_bool(
    "TOUR_RECEIPT_DISCORD_ENABLED",
    default=True,
)


# ---------------------------------------------------------------------------
# Tourbelege / Tracker-PDFs
# ---------------------------------------------------------------------------

TOUR_RECEIPT_FOLDER = env_first(
    "TOUR_RECEIPT_FOLDER",
    "RECEIPT_FOLDER",
    default=os.path.join("static", "downloads", "tour_receipts"),
)
TOUR_RECEIPT_PUBLIC_BASE_URL = env_first(
    "TOUR_RECEIPT_PUBLIC_BASE_URL",
    "PUBLIC_BASE_URL",
    default="",
).rstrip("/")
TOUR_RECEIPT_COMPANY_NAME = env_first(
    "TOUR_RECEIPT_COMPANY_NAME",
    "COMPANY_NAME",
    default="Eifel LOG",
)
TOUR_RECEIPT_CURRENCY = env_first(
    "TOUR_RECEIPT_CURRENCY",
    "DEFAULT_CURRENCY",
    default="EUR",
).upper()
TOUR_RECEIPT_RATE_PER_KM = env_float(
    "TOUR_RECEIPT_RATE_PER_KM",
    "TRACKER_EURO_PER_KM",
    default=3.2,
)

TRACKER_DRIVER_CARD_UPLOAD_FOLDER = env_first(
    "TRACKER_DRIVER_CARD_UPLOAD_FOLDER",
    "FAHRERKARTE_TRACKER_UPLOAD_FOLDER",
    default=os.path.join("static", "uploads", "tracker_driver_cards"),
)
ALLOWED_TRACKER_DRIVER_CARD_EXTENSIONS = {"pdf"}

TRACKER_PDF_DOWNLOAD_TICKET_LIFETIME_SECONDS = max(
    60,
    min(
        3600,
        env_int(
            "TRACKER_PDF_DOWNLOAD_TICKET_LIFETIME_SECONDS",
            "FAHRERKARTE_AUSZUG_DOWNLOAD_TICKET_SECONDS",
            default=600,
        ),
    ),
)
TRACKER_PDF_DOWNLOAD_SIGNING_KEY = env_first(
    "TRACKER_PDF_DOWNLOAD_SIGNING_KEY",
    "FLASK_SECRET_KEY",
    default="",
)

TRACKER_SHIFT_PDF_LAYOUT_VERSION = "eifellog-ticket-theme-v3"
SERVICECENTER_FAHRERKARTE_PDF_LAYOUT_VERSION = (
    "eifellog-fahrerkarte-bestaetigung-v6-qr-bildungen"
)


# ---------------------------------------------------------------------------
# Tracker-Endpunkte / Start- und Abschlusslogik
# ---------------------------------------------------------------------------

DEFAULT_PUBLIC_BASE_URL: Final[str] = "https://www.eifellog.de"
PUBLIC_BASE_URL = env_first("PUBLIC_BASE_URL", default=DEFAULT_PUBLIC_BASE_URL).rstrip("/")

TRACKER_JOB_START_PUBLIC_URL = env_first(
    "TRACKER_JOB_START_PUBLIC_URL",
    "TRACKER_JOBS_START_PUBLIC_URL",
    default=f"{PUBLIC_BASE_URL}/api/tracker/jobs/start",
)
TRACKER_JOB_COMPLETE_PUBLIC_URL = env_first(
    "TRACKER_JOB_COMPLETE_PUBLIC_URL",
    "TRACKER_JOBS_COMPLETE_PUBLIC_URL",
    "TOUR_RECEIPT_COMPLETE_URL",
    "TRACKER_JOB_COMPLETE_URL",
    "TRACKER_JOBS_COMPLETE_URL",
    default=f"{PUBLIC_BASE_URL}/api/tracker/jobs/complete",
)

# Aliase für Desktop-/C#-Konfigurationen und spätere Service-Migrationen.
TOUR_RECEIPT_COMPLETE_URL = TRACKER_JOB_COMPLETE_PUBLIC_URL
TRACKER_JOB_COMPLETE_URL = TRACKER_JOB_COMPLETE_PUBLIC_URL
TRACKER_JOBS_COMPLETE_URL = TRACKER_JOB_COMPLETE_PUBLIC_URL

TOUR_START_DUPLICATE_WINDOW_MINUTES = max(
    0,
    env_int(
        "TOUR_START_DUPLICATE_WINDOW_MINUTES",
        "JOB_START_WEBHOOK_DUPLICATE_WINDOW_MINUTES",
        default=2,
    ),
)
TOUR_COMPLETED_BLOCKS_RESTART_MINUTES = max(
    0,
    env_int("TOUR_COMPLETED_BLOCKS_RESTART_MINUTES", default=0),
)
TOUR_START_AFTER_COMPLETION_SUPPRESS_SECONDS = max(
    0,
    env_int(
        "TOUR_START_AFTER_COMPLETION_SUPPRESS_SECONDS",
        "TRACKER_TOUR_RESTART_GRACE_SECONDS",
        default=180,
    ),
)
TRACKER_WEBHOOK_DEDUPE_TTL_SECONDS = max(
    0,
    env_int("TRACKER_WEBHOOK_DEDUPE_TTL_SECONDS", default=30),
)

TOUR_DESTINATION_REACHED_MAX_DISTANCE_KM = max(
    0.0,
    env_float(
        "TOUR_DESTINATION_REACHED_MAX_DISTANCE_KM",
        "TRACKER_DESTINATION_REACHED_MAX_DISTANCE_KM",
        default=0.15,
    ),
)
TOUR_DESTINATION_REACHED_MIN_PROGRESS = max(
    0.0,
    min(
        100.0,
        env_float(
            "TOUR_DESTINATION_REACHED_MIN_PROGRESS",
            "TRACKER_DESTINATION_REACHED_MIN_PROGRESS",
            default=99.5,
        ),
    ),
)


# ---------------------------------------------------------------------------
# ServiceCenter / Fahrerkarte
# ---------------------------------------------------------------------------

SERVICECENTER_FAHRERKARTE_FOLDER = env_first(
    "SERVICECENTER_FAHRERKARTE_FOLDER",
    "FAHRERKARTE_DOWNLOAD_FOLDER",
    default=os.path.join("static", "downloads", "servicecenter", "fahrerkarten"),
)


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

SERVER_HOST = env_first("SERVER_HOST", "HOST", default="0.0.0.0")
SERVER_PORT = env_int("SERVER_PORT", "PORT", default=5005)


# ---------------------------------------------------------------------------
# Discord OAuth2
# ---------------------------------------------------------------------------

DISCORD_CLIENT_ID = env_first("DISCORD_CLIENT_ID", default="")
DISCORD_CLIENT_SECRET = env_first("DISCORD_CLIENT_SECRET", default="")
DISCORD_REDIRECT_URI = env_first("DISCORD_REDIRECT_URI", default="")
DISCORD_GUILD_ID = env_first("DISCORD_GUILD_ID", default="")

OAUTH_URL = "https://discord.com/api/oauth2/authorize"
TOKEN_URL = "https://discord.com/api/oauth2/token"
API_BASE_URL = "https://discord.com/api/v10"


# ---------------------------------------------------------------------------
# MongoDB
# ---------------------------------------------------------------------------

MONGO_URI = env_first("MONGO_URI", default="")
MONGO_DB_NAME = env_first("MONGO_DB_NAME", default="eifellog_db")
MONGO_APP_NAME = env_first("MONGO_APP_NAME", default="EifelLog")

# Konfigurierbare Collection-Namen. Die Standardwerte bleiben absichtlich
# identisch zu den bisherigen MongoDB-Collections, damit bei einem Update keine
# leeren Parallel-Collections entstehen.
TRACKER_JOB_STARTS_COLLECTION_NAME = env_first(
    "TRACKER_JOB_STARTS_COLLECTION_NAME",
    default="tracker_job_starts",
)
TOUR_RECEIPTS_COLLECTION_NAME = env_first(
    "TOUR_RECEIPTS_COLLECTION_NAME",
    "TRACKER_TOUR_RECEIPTS_COLLECTION_NAME",
    default="tour_receipts",
)
COMPANY_STATS_COLLECTION_NAME = env_first(
    "COMPANY_STATS_COLLECTION_NAME",
    "TRACKER_COMPANY_STATS_COLLECTION_NAME",
    default="company_stats",
)


# ---------------------------------------------------------------------------
# LOA / Urlaubs-Dashboard
# ---------------------------------------------------------------------------

LOA_MONGO_URI = env_first("LOA_MONGO_URI", "MONGO_URI", default=MONGO_URI)
LOA_DB_NAME = env_first(
    "LOA_DB_NAME",
    "MONGO_LOA_DB_NAME",
    "EIFELLOG_LOA_DB_NAME",
    default="EifelLog",
)
LOA_COLLECTION_NAME = env_first(
    "LOA_COLLECTION_NAME",
    "MONGO_LOA_COLLECTION_NAME",
    "EIFELLOG_LOA_COLLECTION_NAME",
    default="LOA",
)
