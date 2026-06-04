"""MongoDB-Verbindungen und Collections für EifelLog.

Die Collection-Namen bleiben standardmäßig vollständig kompatibel zur
bestehenden Anwendung. Über optionale Umgebungsvariablen können einzelne Namen
bei Bedarf angepasst werden, ohne die Business-Logik zu ändern.

Für den Tracker sind insbesondere diese Collections maßgeblich:
- ``tracker_job_starts``: persistenter, deduplizierter Tourstart-Zustand
- ``tour_receipts``: reservierte und abgeschlossene Tourbelege inklusive
  PDF-/Discord-Metadaten
- ``company_stats``: persistente All-Time- und Monatsstatistiken

Die eigentlichen PDF-Dateien werden nicht in MongoDB gespeichert. MongoDB hält
nur die fachlichen Belegdaten und die Metadaten des von Python erzeugten PDFs.
"""

from __future__ import annotations

from typing import Final

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

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


def _collection_name(*environment_keys: str, default: str) -> str:
    """Liest und validiert einen MongoDB-Collection-Namen.

    Standardmäßig werden die bisherigen Collection-Namen verwendet. Dadurch
    entstehen bei einem Update keine versehentlichen Parallel-Collections.
    """
    name = str(env_first(*environment_keys, default=default) or default).strip()

    if not name:
        raise RuntimeError(
            f"MongoDB-Collection-Name fehlt. Erwarteter Standardwert: {default!r}."
        )

    if "\x00" in name or name.startswith("system.") or "$" in name:
        raise RuntimeError(f"Ungültiger MongoDB-Collection-Name: {name!r}")

    return name


def _main_collection(*environment_keys: str, default: str) -> Collection:
    """Liefert eine Collection aus der zentralen EifelLog-Datenbank."""
    return db[_collection_name(*environment_keys, default=default)]


# ---------------------------------------------------------------------------
# Hauptverbindung
# ---------------------------------------------------------------------------

MONGO_APP_NAME: Final[str] = str(
    env_first("MONGO_APP_NAME", default="EifelLog") or "EifelLog"
).strip()

mongo_client = MongoClient(
    MONGO_URI,
    appname=MONGO_APP_NAME,
)

db: Database = mongo_client[MONGO_DB_NAME]


# ---------------------------------------------------------------------------
# Allgemeine Collections
# ---------------------------------------------------------------------------

users_collection = _main_collection(
    "USERS_COLLECTION_NAME",
    default="users",
)
profile_activity_collection = _main_collection(
    "PROFILE_ACTIVITY_COLLECTION_NAME",
    default="profile_activity",
)
profile_gallery_collection = _main_collection(
    "PROFILE_GALLERY_COLLECTION_NAME",
    default="profile_gallery",
)

fahrer_registration_collection = _main_collection(
    "FAHRER_REGISTRATION_COLLECTION_NAME",
    default="fahrer_registration_requests",
)
token_request_collection = _main_collection(
    "TOKEN_REQUEST_COLLECTION_NAME",
    default="token_requests",
)

system_documents_collection = _main_collection(
    "SYSTEM_DOCUMENTS_COLLECTION_NAME",
    default="system_documents",
)
instruction_acknowledgements_collection = _main_collection(
    "INSTRUCTION_ACKNOWLEDGEMENTS_COLLECTION_NAME",
    default="instruction_acknowledgements",
)

tasks_collection = _main_collection(
    "TASKS_COLLECTION_NAME",
    default="tasks",
)


# ---------------------------------------------------------------------------
# Buchhaltung / Tourbelege / Company-Statistiken
# ---------------------------------------------------------------------------

buchhaltung_requests_collection = _main_collection(
    "BUCHHALTUNG_REQUESTS_COLLECTION_NAME",
    default="buchhaltung_requests",
)
buchhaltung_entries_collection = _main_collection(
    "BUCHHALTUNG_ENTRIES_COLLECTION_NAME",
    default="buchhaltung_entries",
)

# Zentraler, deduplizierter Belegbestand für abgeschlossene Tracker-Touren.
# Darin werden auch die PDF- und Discord-Metadaten gespeichert. Die PDF-Datei
# selbst bleibt im konfigurierten Receipt-Ordner des Python-Backends.
tour_receipts_collection = _main_collection(
    "TOUR_RECEIPTS_COLLECTION_NAME",
    "TRACKER_TOUR_RECEIPTS_COLLECTION_NAME",
    default="tour_receipts",
)

# Persistente Company-All-Time- und Monatswerte. Die Business-Logik nutzt darin
# das Dokument ``company_all_time`` und verhindert Doppelzählungen über
# ``processed_receipt_keys``.
company_stats_collection = _main_collection(
    "COMPANY_STATS_COLLECTION_NAME",
    "TRACKER_COMPANY_STATS_COLLECTION_NAME",
    default="company_stats",
)


# ---------------------------------------------------------------------------
# Disposition
# ---------------------------------------------------------------------------

dispo_tours_collection = _main_collection(
    "DISPO_TOURS_COLLECTION_NAME",
    default="dispo_tours",
)
dispo_notes_collection = _main_collection(
    "DISPO_NOTES_COLLECTION_NAME",
    default="dispo_notes",
)
dispo_messages_collection = _main_collection(
    "DISPO_MESSAGES_COLLECTION_NAME",
    default="dispo_messages",
)
dispo_form_entries_collection = _main_collection(
    "DISPO_FORM_ENTRIES_COLLECTION_NAME",
    default="dispo_form_entries",
)


# ---------------------------------------------------------------------------
# ServiceCenter / Fahrerkarte
# ---------------------------------------------------------------------------

fahrerkarte_requests_collection = _main_collection(
    "FAHRERKARTE_REQUESTS_COLLECTION_NAME",
    default="fahrerkarte_requests",
)

fahrerkarte_beantragungen_collection = _main_collection(
    "SERVICECENTER_COLLECTION_NAME",
    "FAHRERKARTE_BEANTRAGUNGEN_COLLECTION",
    default="FahrerkarteBeantragungen",
)

servicecenter_bildungen_requests_collection = _main_collection(
    "SERVICECENTER_BILDUNGEN_REQUESTS_COLLECTION_NAME",
    default="servicecenter_bildungen_requests",
)


# ---------------------------------------------------------------------------
# Tracker
# ---------------------------------------------------------------------------

tracker_driver_cards_collection = _main_collection(
    "TRACKER_DRIVER_CARDS_COLLECTION_NAME",
    default="tracker_driver_cards",
)
tracker_work_sessions_collection = _main_collection(
    "TRACKER_WORK_SESSIONS_COLLECTION_NAME",
    default="tracker_work_sessions",
)

# Persistiert Tourstarts und dient als Deduplizierungsbasis für Start-Embeds.
# Deshalb bewusst keine neue Parallel-Collection für Discord-Startmeldungen
# anlegen: Der Startzustand und dessen Versandstatus gehören zusammen.
tracker_job_starts_collection = _main_collection(
    "TRACKER_JOB_STARTS_COLLECTION_NAME",
    default="tracker_job_starts",
)

driver_logs_collection = _main_collection(
    "DRIVER_LOGS_COLLECTION_NAME",
    default="driver_logs",
)
tracker_shift_logs_collection = _main_collection(
    "TRACKER_SHIFT_LOGS_COLLECTION_NAME",
    default="tracker_shift_logs",
)


# ---------------------------------------------------------------------------
# HR-Controlling
# ---------------------------------------------------------------------------

hr_personalakten_collection = _main_collection(
    "HR_PERSONALAKTEN_COLLECTION_NAME",
    default="hr_personalakten",
)
hr_process_plan_collection = _main_collection(
    "HR_PROCESS_PLAN_COLLECTION_NAME",
    default="hr_process_plan",
)
hr_checklist_collection = _main_collection(
    "HR_CHECKLIST_COLLECTION_NAME",
    default="hr_checklist",
)
hr_sheet_builder_collection = _main_collection(
    "HR_SHEET_BUILDER_COLLECTION_NAME",
    default="hr_sheet_builder",
)


# ---------------------------------------------------------------------------
# Live Workspace / Tabellen-Builder
# ---------------------------------------------------------------------------

workspace_accounts_collection = _main_collection(
    "WORKSPACE_ACCOUNTS_COLLECTION_NAME",
    default="workspace_accounts",
)
workspace_workspaces_collection = _main_collection(
    "WORKSPACE_WORKSPACES_COLLECTION_NAME",
    default="workspace_workspaces",
)
workspace_members_collection = _main_collection(
    "WORKSPACE_MEMBERS_COLLECTION_NAME",
    default="workspace_members",
)
workspace_folders_collection = _main_collection(
    "WORKSPACE_FOLDERS_COLLECTION_NAME",
    default="workspace_folders",
)
workspace_project_maps_collection = _main_collection(
    "WORKSPACE_PROJECT_MAPS_COLLECTION_NAME",
    default="workspace_project_maps",
)
workspace_sheets_collection = _main_collection(
    "WORKSPACE_SHEETS_COLLECTION_NAME",
    default="workspace_sheets",
)
workspace_invites_collection = _main_collection(
    "WORKSPACE_INVITES_COLLECTION_NAME",
    default="workspace_invites",
)
workspace_events_collection = _main_collection(
    "WORKSPACE_EVENTS_COLLECTION_NAME",
    default="workspace_events",
)


# ---------------------------------------------------------------------------
# Öffentliche Event-API
#
# Standardwerte:
#   EVENT_DB_NAME=eifellog_db
#   EVENT_COLLECTION_NAME=events
# ---------------------------------------------------------------------------

EVENT_DB_NAME: Final[str] = str(
    env_first("EVENT_DB_NAME", default="eifellog_db") or "eifellog_db"
).strip()
EVENT_COLLECTION_NAME: Final[str] = _collection_name(
    "EVENT_COLLECTION_NAME",
    default="events",
)

event_db: Database = mongo_client[EVENT_DB_NAME]
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

BIRTHDAY_DB_NAME: Final[str] = str(
    env_first("BIRTHDAY_DB_NAME", default="EifelLog") or "EifelLog"
).strip()
BIRTHDAY_COLLECTION_NAME: Final[str] = _collection_name(
    "BIRTHDAY_COLLECTION_NAME",
    default="Birthdays",
)

birthday_db: Database = mongo_client[BIRTHDAY_DB_NAME]
birthdays_collection = birthday_db[BIRTHDAY_COLLECTION_NAME]

# Kompatibilitäts-Aliase für bestehende Imports
birthday_collection = birthdays_collection
public_birthdays_collection = birthdays_collection
public_birthday_collection = birthdays_collection


# ---------------------------------------------------------------------------
# Tracker-Kompatibilitäts-Aliase
#
# Neue Services dürfen die fachlich präziseren Namen verwenden. Bestehende
# Legacy-Imports behalten weiterhin die oben definierten Originalnamen.
# ---------------------------------------------------------------------------

tracker_tour_receipts_collection = tour_receipts_collection
tracker_receipts_collection = tour_receipts_collection
tracker_company_stats_collection = company_stats_collection
tracker_job_start_collection = tracker_job_starts_collection


# ---------------------------------------------------------------------------
# Getter für bestehende und schrittweise migrierte Module
#
# Wichtig:
#   Getter immer mit Klammern aufrufen:
#       get_events_collection()
#
#   Nicht korrekt:
#       get_events_collection["events"]
# ---------------------------------------------------------------------------

def get_events_collection() -> Collection:
    """Liefert die MongoDB-Collection der öffentlichen Events."""
    return events_collection


def get_event_collection() -> Collection:
    """Kompatibilitäts-Getter für die öffentliche Event-Collection."""
    return events_collection


def get_birthdays_collection() -> Collection:
    """Liefert die MongoDB-Collection der öffentlichen Geburtstage."""
    return birthdays_collection


def get_birthday_collection() -> Collection:
    """Kompatibilitäts-Getter für die öffentliche Birthday-Collection."""
    return birthdays_collection


def get_tracker_job_starts_collection() -> Collection:
    """Liefert die persistente Deduplizierungsbasis der Tourstart-Embeds."""
    return tracker_job_starts_collection


def get_tour_receipts_collection() -> Collection:
    """Liefert die Collection der reservierten und abgeschlossenen Tourbelege."""
    return tour_receipts_collection


def get_company_stats_collection() -> Collection:
    """Liefert die persistente Company-Statistik-Collection."""
    return company_stats_collection


# ---------------------------------------------------------------------------
# LOA / Urlaubs-Dashboard
# ---------------------------------------------------------------------------

loa_mongo_client = (
    mongo_client
    if not LOA_MONGO_URI or LOA_MONGO_URI == MONGO_URI
    else MongoClient(
        LOA_MONGO_URI,
        appname=f"{MONGO_APP_NAME}-LOA",
    )
)

loa_db: Database = loa_mongo_client[LOA_DB_NAME]
loa_collection = loa_db[LOA_COLLECTION_NAME]
