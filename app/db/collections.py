"""MongoDB-Verbindungen und Collections für EifelLog."""

from pymongo import MongoClient

from app.config import (
    LOA_COLLECTION_NAME,
    LOA_DB_NAME,
    LOA_MONGO_URI,
    MONGO_DB_NAME,
    MONGO_URI,
    env_first,
)


if not MONGO_URI:
    raise RuntimeError("MONGO_URI fehlt. Bitte in deiner .env setzen.")


# ---------------------------------------------------------------------------
# Hauptverbindung
# ---------------------------------------------------------------------------

mongo_client = MongoClient(MONGO_URI)
db = mongo_client[MONGO_DB_NAME]


# ---------------------------------------------------------------------------
# Allgemeine Collections
# ---------------------------------------------------------------------------

users_collection = db["users"]
profile_activity_collection = db["profile_activity"]
profile_gallery_collection = db["profile_gallery"]

fahrer_registration_collection = db["fahrer_registration_requests"]
token_request_collection = db["token_requests"]

system_documents_collection = db["system_documents"]
instruction_acknowledgements_collection = db[
    "instruction_acknowledgements"
]

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

fahrerkarte_beantragungen_collection = db[
    env_first(
        "SERVICECENTER_COLLECTION_NAME",
        "FAHRERKARTE_BEANTRAGUNGEN_COLLECTION",
        default="FahrerkarteBeantragungen",
    )
]

servicecenter_bildungen_requests_collection = db[
    "servicecenter_bildungen_requests"
]


# ---------------------------------------------------------------------------
# Tracker
# ---------------------------------------------------------------------------

tracker_driver_cards_collection = db["tracker_driver_cards"]
tracker_work_sessions_collection = db["tracker_work_sessions"]
tracker_job_starts_collection = db["tracker_job_starts"]

driver_logs_collection = db["driver_logs"]
tracker_shift_logs_collection = db["tracker_shift_logs"]


# ---------------------------------------------------------------------------
# HR-Controlling
# ---------------------------------------------------------------------------

hr_personalakten_collection = db["hr_personalakten"]
hr_process_plan_collection = db["hr_process_plan"]
hr_checklist_collection = db["hr_checklist"]
hr_sheet_builder_collection = db["hr_sheet_builder"]


# ---------------------------------------------------------------------------
# Live Workspace / Tabellen-Builder
# ---------------------------------------------------------------------------

workspace_accounts_collection = db["workspace_accounts"]
workspace_workspaces_collection = db["workspace_workspaces"]
workspace_members_collection = db["workspace_members"]
workspace_folders_collection = db["workspace_folders"]
workspace_project_maps_collection = db["workspace_project_maps"]
workspace_sheets_collection = db["workspace_sheets"]
workspace_invites_collection = db["workspace_invites"]
workspace_events_collection = db["workspace_events"]


# ---------------------------------------------------------------------------
# Öffentliche Event-API
#
# Standardwerte:
#   EVENT_DB_NAME=eifellog_db
#   EVENT_COLLECTION_NAME=events
# ---------------------------------------------------------------------------

EVENT_DB_NAME = env_first(
    "EVENT_DB_NAME",
    default="eifellog_db",
)

EVENT_COLLECTION_NAME = env_first(
    "EVENT_COLLECTION_NAME",
    default="events",
)

event_db = mongo_client[EVENT_DB_NAME]
events_collection = event_db[EVENT_COLLECTION_NAME]

# Kompatibilitäts-Aliase für bestehende Imports
event_collection = events_collection
public_events_collection = events_collection
public_event_collection = events_collection


# ---------------------------------------------------------------------------
# Öffentliche Birthday-API
#
# Standardwerte:
#   BIRTHDAY_DB_NAME=EifelLog
#   BIRTHDAY_COLLECTION_NAME=Birthdays
# ---------------------------------------------------------------------------

BIRTHDAY_DB_NAME = env_first(
    "BIRTHDAY_DB_NAME",
    default="EifelLog",
)

BIRTHDAY_COLLECTION_NAME = env_first(
    "BIRTHDAY_COLLECTION_NAME",
    default="Birthdays",
)

birthday_db = mongo_client[BIRTHDAY_DB_NAME]
birthdays_collection = birthday_db[BIRTHDAY_COLLECTION_NAME]

# Kompatibilitäts-Aliase für bestehende Imports
birthday_collection = birthdays_collection
public_birthdays_collection = birthdays_collection
public_birthday_collection = birthdays_collection


# ---------------------------------------------------------------------------
# Optionale Getter für bestehende Module
#
# Wichtig:
#   Getter immer mit Klammern aufrufen:
#       get_events_collection()
#
#   Nicht korrekt:
#       get_events_collection["events"]
# ---------------------------------------------------------------------------

def get_events_collection():
    """Liefert die MongoDB-Collection der öffentlichen Events."""
    return events_collection


def get_event_collection():
    """Kompatibilitäts-Getter für die öffentliche Event-Collection."""
    return events_collection


def get_birthdays_collection():
    """Liefert die MongoDB-Collection der öffentlichen Geburtstage."""
    return birthdays_collection


def get_birthday_collection():
    """Kompatibilitäts-Getter für die öffentliche Birthday-Collection."""
    return birthdays_collection


# ---------------------------------------------------------------------------
# LOA / Urlaubs-Dashboard
# ---------------------------------------------------------------------------

loa_mongo_client = (
    mongo_client
    if not LOA_MONGO_URI or LOA_MONGO_URI == MONGO_URI
    else MongoClient(LOA_MONGO_URI)
)

loa_db = loa_mongo_client[LOA_DB_NAME]
loa_collection = loa_db[LOA_COLLECTION_NAME]