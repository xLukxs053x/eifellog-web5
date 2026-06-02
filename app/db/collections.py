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

mongo_client = MongoClient(MONGO_URI)
db = mongo_client[MONGO_DB_NAME]

users_collection = db["users"]
profile_activity_collection = db["profile_activity"]
profile_gallery_collection = db["profile_gallery"]
fahrer_registration_collection = db["fahrer_registration_requests"]
token_request_collection = db["token_requests"]
system_documents_collection = db["system_documents"]
instruction_acknowledgements_collection = db["instruction_acknowledgements"]
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

servicecenter_bildungen_requests_collection = db["servicecenter_bildungen_requests"]

tracker_driver_cards_collection = db["tracker_driver_cards"]
tracker_work_sessions_collection = db["tracker_work_sessions"]
tracker_job_starts_collection = db["tracker_job_starts"]
driver_logs_collection = db["driver_logs"]
tracker_shift_logs_collection = db["tracker_shift_logs"]

# HR Controlling
hr_personalakten_collection = db["hr_personalakten"]
hr_process_plan_collection = db["hr_process_plan"]
hr_checklist_collection = db["hr_checklist"]
hr_sheet_builder_collection = db["hr_sheet_builder"]

# Live Workspace / Tabellen-Builder
workspace_accounts_collection = db["workspace_accounts"]
workspace_workspaces_collection = db["workspace_workspaces"]
workspace_members_collection = db["workspace_members"]
workspace_folders_collection = db["workspace_folders"]
workspace_project_maps_collection = db["workspace_project_maps"]
workspace_sheets_collection = db["workspace_sheets"]
workspace_invites_collection = db["workspace_invites"]
workspace_events_collection = db["workspace_events"]

# LOA / Urlaubs-Dashboard
loa_mongo_client = mongo_client if LOA_MONGO_URI == MONGO_URI else MongoClient(LOA_MONGO_URI)
loa_db = loa_mongo_client[LOA_DB_NAME]
loa_collection = loa_db[LOA_COLLECTION_NAME]
