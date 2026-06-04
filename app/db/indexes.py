"""MongoDB-Indizes für EifelLog.

Die Tracker-Indizes schützen insbesondere zwei kritische Abläufe:
- Ein Tourstart-Embed darf für eine offene Tour nur einmal reserviert werden.
- Ein Abschlussbeleg darf trotz paralleler Retrys nur einmal verarbeitet werden.

Alle Indizes werden fehlertolerant einzeln angelegt. Ein einzelner historischer
Datenkonflikt verhindert dadurch nicht mehr die Erstellung aller nachfolgenden
Indizes. Fehler bleiben im Server-Log sichtbar und können gezielt bereinigt
werden.
"""

from datetime import datetime

from pymongo import ASCENDING, DESCENDING

from app.db.collections import (
    buchhaltung_entries_collection,
    buchhaltung_requests_collection,
    company_stats_collection,
    dispo_form_entries_collection,
    dispo_messages_collection,
    dispo_notes_collection,
    dispo_tours_collection,
    driver_logs_collection,
    fahrer_registration_collection,
    fahrerkarte_beantragungen_collection,
    fahrerkarte_requests_collection,
    hr_checklist_collection,
    hr_personalakten_collection,
    hr_process_plan_collection,
    hr_sheet_builder_collection,
    instruction_acknowledgements_collection,
    loa_collection,
    profile_activity_collection,
    profile_gallery_collection,
    servicecenter_bildungen_requests_collection,
    system_documents_collection,
    tasks_collection,
    token_request_collection,
    tour_receipts_collection,
    tracker_driver_cards_collection,
    tracker_job_starts_collection,
    tracker_shift_logs_collection,
    tracker_work_sessions_collection,
    users_collection,
    workspace_accounts_collection,
    workspace_events_collection,
    workspace_folders_collection,
    workspace_invites_collection,
    workspace_members_collection,
    workspace_project_maps_collection,
    workspace_sheets_collection,
    workspace_workspaces_collection,
)


def _safe_create_index(collection, keys, **kwargs):
    """Legt genau einen Index an, ohne die komplette Startsequenz abzubrechen."""
    try:
        return collection.create_index(keys, **kwargs)
    except Exception as error:
        index_name = kwargs.get("name") or repr(keys)
        collection_name = getattr(collection, "full_name", None) or getattr(collection, "name", repr(collection))
        print(
            "MongoDB Index-Erstellung fehlgeschlagen: "
            f"{collection_name}.{index_name}: {error}"
        )
        return None


def _archive_duplicate_open_tracker_job_starts():
    """Bereinigt nur doppelte offene Tourstarts vor dem eindeutigen Index.

    Historische Abschlussbelege werden niemals automatisch gelöscht oder
    verändert. Bei offenen Tourstarts bleibt jeweils der zuletzt aktualisierte
    Datensatz aktiv; ältere doppelte Datensätze werden revisionssicher als
    ``superseded`` markiert.
    """
    now = datetime.utcnow()

    try:
        duplicate_groups = tracker_job_starts_collection.aggregate(
            [
                {
                    "$match": {
                        "status": "started",
                        "discord_id": {"$type": "string"},
                        "job_start_key": {"$type": "string"},
                    }
                },
                {"$sort": {"updated_at": -1, "created_at": -1}},
                {
                    "$group": {
                        "_id": {
                            "discord_id": "$discord_id",
                            "job_start_key": "$job_start_key",
                        },
                        "keep_id": {"$first": "$_id"},
                        "all_ids": {"$push": "$_id"},
                        "count": {"$sum": 1},
                    }
                },
                {"$match": {"count": {"$gt": 1}}},
            ]
        )

        for group in duplicate_groups:
            keep_id = group.get("keep_id")
            duplicate_ids = [
                document_id
                for document_id in group.get("all_ids", [])
                if document_id != keep_id
            ]
            if not duplicate_ids:
                continue

            tracker_job_starts_collection.update_many(
                {"_id": {"$in": duplicate_ids}},
                {
                    "$set": {
                        "status": "superseded",
                        "archived": True,
                        "superseded_reason": "duplicate_open_tracker_job_start_index_migration",
                        "superseded_at": now,
                        "updated_at": now,
                    }
                },
            )
    except Exception as error:
        print(
            "MongoDB Bereinigung doppelter offener Tracker-Tourstarts "
            f"fehlgeschlagen: {error}"
        )


def ensure_indexes():
    _archive_duplicate_open_tracker_job_starts()

    try:
        _safe_create_index(users_collection, [("discord_id", ASCENDING)], unique=False)
        _safe_create_index(users_collection, [("username_lc", ASCENDING)], unique=False)
        _safe_create_index(users_collection, [("tracker_code_hash", ASCENDING)], unique=False)
        _safe_create_index(users_collection, [("tracker_client_token_hash", ASCENDING)], unique=False)
        _safe_create_index(users_collection, [("tracker_live_updated_at", DESCENDING)], unique=False)
        _safe_create_index(users_collection, [("tracker_online", ASCENDING)], unique=False)

        _safe_create_index(profile_activity_collection, [("discord_id", ASCENDING)], unique=False)
        _safe_create_index(profile_activity_collection, [("created_at", DESCENDING)], unique=False)
        _safe_create_index(profile_activity_collection, [("archived", ASCENDING)], unique=False)

        _safe_create_index(profile_gallery_collection, [("discord_id", ASCENDING)], unique=False)
        _safe_create_index(profile_gallery_collection, [("created_at", DESCENDING)], unique=False)
        _safe_create_index(profile_gallery_collection, [("archived", ASCENDING)], unique=False)

        _safe_create_index(fahrer_registration_collection, [("discord_id", ASCENDING)], unique=False)
        _safe_create_index(fahrer_registration_collection, [("status", ASCENDING)], unique=False)
        _safe_create_index(fahrer_registration_collection, [("created_at", DESCENDING)], unique=False)
        _safe_create_index(fahrer_registration_collection, [("claimed_by.discord_id", ASCENDING)], unique=False)
        _safe_create_index(fahrer_registration_collection, [("deadline_at", ASCENDING)], unique=False)

        _safe_create_index(token_request_collection, [("discord_id", ASCENDING)], unique=False)
        _safe_create_index(token_request_collection, [("status", ASCENDING)], unique=False)
        _safe_create_index(token_request_collection, [("created_at", DESCENDING)], unique=False)

        _safe_create_index(system_documents_collection, [("discord_id", ASCENDING)], unique=False)
        _safe_create_index(system_documents_collection, [("created_at", DESCENDING)], unique=False)
        _safe_create_index(system_documents_collection, [("type", ASCENDING)], unique=False)
        _safe_create_index(system_documents_collection, [("expires_at", ASCENDING)], unique=False)
        _safe_create_index(system_documents_collection, [("fixed", ASCENDING)], unique=False)

        _safe_create_index(instruction_acknowledgements_collection, 
            [("discord_id", ASCENDING), ("instruction_id", ASCENDING)],
            unique=True,
        )
        _safe_create_index(instruction_acknowledgements_collection, [("instruction_id", ASCENDING)], unique=False)
        _safe_create_index(instruction_acknowledgements_collection, [("acknowledged_at", DESCENDING)], unique=False)
        
        _safe_create_index(tasks_collection, [("status", ASCENDING)], unique=False)
        _safe_create_index(tasks_collection, [("created_at", DESCENDING)], unique=False)
        
        _safe_create_index(buchhaltung_requests_collection, [("created_at", DESCENDING)], unique=False)
        _safe_create_index(buchhaltung_requests_collection, [("status", ASCENDING)], unique=False)
        _safe_create_index(buchhaltung_requests_collection, [("archived", ASCENDING)], unique=False)

        _safe_create_index(buchhaltung_entries_collection, [("entry_id", ASCENDING)], unique=False)
        _safe_create_index(buchhaltung_entries_collection, [("created_at", DESCENDING)], unique=False)
        _safe_create_index(buchhaltung_entries_collection, [("updated_at", DESCENDING)], unique=False)
        _safe_create_index(buchhaltung_entries_collection, [("created_by.discord_id", ASCENDING)], unique=False)
        _safe_create_index(buchhaltung_entries_collection, [("created_by.username", ASCENDING)], unique=False)
        _safe_create_index(buchhaltung_entries_collection, [("date", DESCENDING)], unique=False)
        _safe_create_index(buchhaltung_entries_collection, [("type", ASCENDING)], unique=False)
        _safe_create_index(buchhaltung_entries_collection, [("payment_status", ASCENDING)], unique=False)
        _safe_create_index(buchhaltung_entries_collection, [("receipt_status", ASCENDING)], unique=False)
        _safe_create_index(buchhaltung_entries_collection, [("job_status", ASCENDING)], unique=False)
        _safe_create_index(buchhaltung_entries_collection, [("pdf_archive_id", ASCENDING)], unique=False)
        _safe_create_index(buchhaltung_entries_collection, [("pdf.sha256", ASCENDING)], unique=False)
        _safe_create_index(buchhaltung_entries_collection, [("pdf.uploaded_at", DESCENDING)], unique=False)
        _safe_create_index(buchhaltung_entries_collection, [("archived", ASCENDING)], unique=False)

        _safe_create_index(tour_receipts_collection, [("receipt_id", ASCENDING)], unique=False)
        _safe_create_index(tour_receipts_collection, [("receipt_number", ASCENDING)], unique=False)
        _safe_create_index(tour_receipts_collection, [("receipt_dedupe_key", ASCENDING)], unique=False)
        _safe_create_index(tour_receipts_collection, [("job_id", ASCENDING)], unique=False)
        _safe_create_index(tour_receipts_collection, [("job_start_key", ASCENDING)], unique=False)
        _safe_create_index(tour_receipts_collection, [("driver.discord_id", ASCENDING)], unique=False)
        _safe_create_index(tour_receipts_collection, [("submitted_at", DESCENDING)], unique=False)
        _safe_create_index(tour_receipts_collection, [("billing_relevant", ASCENDING)], unique=False)
        _safe_create_index(tour_receipts_collection, [("processing_status", ASCENDING)], unique=False)
        _safe_create_index(tour_receipts_collection, [("discord.channel_id", ASCENDING)], unique=False)
        _safe_create_index(tour_receipts_collection, [("discord.sent", ASCENDING)], unique=False)
        _safe_create_index(
            tour_receipts_collection,
            [("receipt_dedupe_key", ASCENDING)],
            name="uq_tour_receipts_receipt_dedupe_key",
            unique=True,
            partialFilterExpression={"receipt_dedupe_key": {"$type": "string"}},
        )

        _safe_create_index(company_stats_collection, [("kind", ASCENDING)], unique=False)
        _safe_create_index(company_stats_collection, [("updated_at", DESCENDING)], unique=False)
        _safe_create_index(company_stats_collection, [("processed_receipt_keys", ASCENDING)], unique=False)

        _safe_create_index(dispo_tours_collection, [("tour_id", ASCENDING)], unique=False)
        _safe_create_index(dispo_tours_collection, [("status", ASCENDING)], unique=False)
        _safe_create_index(dispo_tours_collection, [("priority", ASCENDING)], unique=False)
        _safe_create_index(dispo_tours_collection, [("created_at", DESCENDING)], unique=False)
        _safe_create_index(dispo_tours_collection, [("assigned_driver_id", ASCENDING)], unique=False)
        _safe_create_index(dispo_tours_collection, [("assigned_driver.discord_id", ASCENDING)], unique=False)
        _safe_create_index(dispo_tours_collection, [("archived", ASCENDING)], unique=False)

        _safe_create_index(dispo_notes_collection, [("created_at", DESCENDING)], unique=False)
        _safe_create_index(dispo_notes_collection, [("created_by.discord_id", ASCENDING)], unique=False)
        _safe_create_index(dispo_notes_collection, [("archived", ASCENDING)], unique=False)

        _safe_create_index(dispo_messages_collection, [("created_at", DESCENDING)], unique=False)
        _safe_create_index(dispo_messages_collection, [("priority", ASCENDING)], unique=False)
        _safe_create_index(dispo_messages_collection, [("archived", ASCENDING)], unique=False)

        _safe_create_index(dispo_form_entries_collection, [("entry_id", ASCENDING)], unique=False)
        _safe_create_index(dispo_form_entries_collection, [("entry_source", ASCENDING)], unique=False)
        _safe_create_index(dispo_form_entries_collection, [("entry_type", ASCENDING)], unique=False)
        _safe_create_index(dispo_form_entries_collection, [("document_type", ASCENDING)], unique=False)
        _safe_create_index(dispo_form_entries_collection, [("status", ASCENDING)], unique=False)
        _safe_create_index(dispo_form_entries_collection, [("submitted_by.discord_id", ASCENDING)], unique=False)
        _safe_create_index(dispo_form_entries_collection, [("submitted_by.username", ASCENDING)], unique=False)
        _safe_create_index(dispo_form_entries_collection, [("reference", ASCENDING)], unique=False)
        _safe_create_index(dispo_form_entries_collection, [("created_at", DESCENDING)], unique=False)
        _safe_create_index(dispo_form_entries_collection, [("archived", ASCENDING)], unique=False)

        _safe_create_index(fahrerkarte_requests_collection, [("request_id", ASCENDING)], unique=False)
        _safe_create_index(fahrerkarte_requests_collection, [("discord_id", ASCENDING)], unique=False)
        _safe_create_index(fahrerkarte_requests_collection, [("status", ASCENDING)], unique=False)
        _safe_create_index(fahrerkarte_requests_collection, [("created_at", DESCENDING)], unique=False)
        _safe_create_index(fahrerkarte_requests_collection, [("issued_at", DESCENDING)], unique=False)
        _safe_create_index(fahrerkarte_requests_collection, [("claimed_by.discord_id", ASCENDING)], unique=False)
        _safe_create_index(fahrerkarte_requests_collection, [("card_id", ASCENDING)], unique=False)
        _safe_create_index(fahrerkarte_requests_collection, [("discord_id", ASCENDING), ("card_id", ASCENDING), ("status", ASCENDING), ("archived", ASCENDING)], unique=False)
        _safe_create_index(fahrerkarte_requests_collection, [("pdf_relative_path", ASCENDING)], unique=False)
        _safe_create_index(fahrerkarte_requests_collection, [("fahrerkarte_pin_issued_at", DESCENDING)], unique=False)
        _safe_create_index(fahrerkarte_requests_collection, [("fahrerkarte_pin_locked_until", ASCENDING)], unique=False)
        _safe_create_index(fahrerkarte_requests_collection, [("archived", ASCENDING)], unique=False)

        _safe_create_index(fahrerkarte_beantragungen_collection, [("request_id", ASCENDING)], unique=False)
        _safe_create_index(fahrerkarte_beantragungen_collection, [("fahrerkarte_request_id", ASCENDING)], unique=False)
        _safe_create_index(fahrerkarte_beantragungen_collection, [("discord_id", ASCENDING)], unique=False)
        _safe_create_index(fahrerkarte_beantragungen_collection, [("user_id", ASCENDING)], unique=False)
        _safe_create_index(fahrerkarte_beantragungen_collection, [("status", ASCENDING)], unique=False)
        _safe_create_index(fahrerkarte_beantragungen_collection, [("fahrerkarte_status", ASCENDING)], unique=False)
        _safe_create_index(fahrerkarte_beantragungen_collection, [("personalisierte_fahrerkarte_status", ASCENDING)], unique=False)
        _safe_create_index(fahrerkarte_beantragungen_collection, [("source_user_mongo_id", ASCENDING)], unique=False)
        _safe_create_index(fahrerkarte_beantragungen_collection, [("created_at", DESCENDING)], unique=False)
        _safe_create_index(fahrerkarte_beantragungen_collection, [("updated_at", DESCENDING)], unique=False)

        _safe_create_index(servicecenter_bildungen_requests_collection, [("request_id", ASCENDING)], unique=True)
        _safe_create_index(servicecenter_bildungen_requests_collection, [("discord_id", ASCENDING)], unique=False)
        _safe_create_index(servicecenter_bildungen_requests_collection, [("category", ASCENDING)], unique=False)
        _safe_create_index(servicecenter_bildungen_requests_collection, [("offer_id", ASCENDING)], unique=False)
        _safe_create_index(servicecenter_bildungen_requests_collection, [("status", ASCENDING)], unique=False)
        _safe_create_index(servicecenter_bildungen_requests_collection, [("created_at", DESCENDING)], unique=False)
        _safe_create_index(servicecenter_bildungen_requests_collection, [("updated_at", DESCENDING)], unique=False)
        _safe_create_index(servicecenter_bildungen_requests_collection, [("appointment_at", ASCENDING)], unique=False)
        _safe_create_index(servicecenter_bildungen_requests_collection, [("appointment_confirmation_status", ASCENDING)], unique=False)
        _safe_create_index(servicecenter_bildungen_requests_collection, [("claimed_by.discord_id", ASCENDING)], unique=False)
        _safe_create_index(servicecenter_bildungen_requests_collection, [("archived", ASCENDING)], unique=False)

        _safe_create_index(tracker_driver_cards_collection, [("discord_id", ASCENDING)], unique=False)
        _safe_create_index(tracker_driver_cards_collection, [("user_id", ASCENDING)], unique=False)
        _safe_create_index(tracker_driver_cards_collection, [("card_id", ASCENDING)], unique=False)
        _safe_create_index(tracker_driver_cards_collection, [("created_at", DESCENDING)], unique=False)
        _safe_create_index(tracker_driver_cards_collection, [("updated_at", DESCENDING)], unique=False)
        _safe_create_index(tracker_driver_cards_collection, [("archived", ASCENDING)], unique=False)

        _safe_create_index(tracker_work_sessions_collection, [("discord_id", ASCENDING)], unique=False)
        _safe_create_index(tracker_work_sessions_collection, [("status", ASCENDING)], unique=False)
        _safe_create_index(tracker_work_sessions_collection, [("updated_at", DESCENDING)], unique=False)

        _safe_create_index(tracker_job_starts_collection, [("discord_id", ASCENDING)], unique=False)
        _safe_create_index(tracker_job_starts_collection, [("job_id", ASCENDING)], unique=False)
        _safe_create_index(tracker_job_starts_collection, [("job_start_key", ASCENDING)], unique=False)
        _safe_create_index(tracker_job_starts_collection, [("status", ASCENDING)], unique=False)
        _safe_create_index(tracker_job_starts_collection, [("archived", ASCENDING)], unique=False)
        _safe_create_index(tracker_job_starts_collection, [("created_at", DESCENDING)], unique=False)
        _safe_create_index(tracker_job_starts_collection, [("updated_at", DESCENDING)], unique=False)
        _safe_create_index(tracker_job_starts_collection, [("tour_start_discord_claimed", ASCENDING)], unique=False)
        _safe_create_index(tracker_job_starts_collection, [("tour_start_discord_sent", ASCENDING)], unique=False)
        _safe_create_index(tracker_job_starts_collection, [("tour_start_discord_sent_at", DESCENDING)], unique=False)
        _safe_create_index(tracker_job_starts_collection, [("completed_at", DESCENDING)], unique=False)
        _safe_create_index(tracker_job_starts_collection, [("discord_id", ASCENDING), ("job_start_key", ASCENDING), ("status", ASCENDING)], unique=False)
        _safe_create_index(
            tracker_job_starts_collection,
            [("discord_id", ASCENDING), ("job_start_key", ASCENDING)],
            name="uq_tracker_job_starts_open_tour",
            unique=True,
            partialFilterExpression={
                "discord_id": {"$type": "string"},
                "job_start_key": {"$type": "string"},
                "status": "started",
            },
        )

        _safe_create_index(driver_logs_collection, [("discord_id", ASCENDING)], unique=False)
        _safe_create_index(driver_logs_collection, [("user_id", ASCENDING)], unique=False)
        _safe_create_index(driver_logs_collection, [("receipt_id", ASCENDING)], unique=False)
        _safe_create_index(driver_logs_collection, [("job_start_key", ASCENDING)], unique=False)
        _safe_create_index(driver_logs_collection, [("date_str", ASCENDING)], unique=False)
        _safe_create_index(driver_logs_collection, [("date_display", ASCENDING)], unique=False)
        _safe_create_index(driver_logs_collection, [("start_time", ASCENDING)], unique=False)
        _safe_create_index(driver_logs_collection, [("end_time", ASCENDING)], unique=False)
        _safe_create_index(driver_logs_collection, [("state_key", ASCENDING)], unique=False)
        _safe_create_index(driver_logs_collection, [("discord_id", ASCENDING), ("date_str", ASCENDING), ("start_time", ASCENDING)], unique=False)
        _safe_create_index(
            driver_logs_collection,
            [("discord_id", ASCENDING), ("receipt_id", ASCENDING)],
            name="uq_driver_logs_receipt_per_driver",
            unique=True,
            partialFilterExpression={
                "discord_id": {"$type": "string"},
                "receipt_id": {"$type": "string"},
                "archived": False,
            },
        )

        _safe_create_index(tracker_shift_logs_collection, [("shift_id", ASCENDING)], unique=False)
        _safe_create_index(tracker_shift_logs_collection, [("discord_id", ASCENDING)], unique=False)
        _safe_create_index(tracker_shift_logs_collection, [("shift_date", ASCENDING)], unique=False)
        _safe_create_index(tracker_shift_logs_collection, [("date_str", ASCENDING)], unique=False)
        _safe_create_index(tracker_shift_logs_collection, [("tour_receipt_ids", ASCENDING)], unique=False)
        _safe_create_index(tracker_shift_logs_collection, [("created_at", DESCENDING)], unique=False)
        _safe_create_index(tracker_shift_logs_collection, [("updated_at", DESCENDING)], unique=False)
        _safe_create_index(tracker_shift_logs_collection, [("discord_id", ASCENDING), ("date_str", ASCENDING)], unique=False)

        _safe_create_index(hr_personalakten_collection, [("employee_id", ASCENDING)], unique=False)
        _safe_create_index(hr_personalakten_collection, [("id", ASCENDING)], unique=False)
        _safe_create_index(hr_personalakten_collection, [("name_lc", ASCENDING)], unique=False)
        _safe_create_index(hr_personalakten_collection, [("email_lc", ASCENDING)], unique=False)
        _safe_create_index(hr_personalakten_collection, [("status", ASCENDING)], unique=False)
        _safe_create_index(hr_personalakten_collection, [("process", ASCENDING)], unique=False)
        _safe_create_index(hr_personalakten_collection, [("archived", ASCENDING)], unique=False)
        _safe_create_index(hr_personalakten_collection, [("created_at", DESCENDING)], unique=False)
        _safe_create_index(hr_personalakten_collection, [("updated_at", DESCENDING)], unique=False)

        _safe_create_index(hr_process_plan_collection, [("process_id", ASCENDING)], unique=False)
        _safe_create_index(hr_process_plan_collection, [("sort_order", ASCENDING)], unique=False)
        _safe_create_index(hr_process_plan_collection, [("phase", ASCENDING)], unique=False)
        _safe_create_index(hr_process_plan_collection, [("archived", ASCENDING)], unique=False)
        _safe_create_index(hr_process_plan_collection, [("created_at", DESCENDING)], unique=False)
        _safe_create_index(hr_process_plan_collection, [("updated_at", DESCENDING)], unique=False)

        _safe_create_index(hr_checklist_collection, [("item_id", ASCENDING)], unique=False)
        _safe_create_index(hr_checklist_collection, [("process", ASCENDING)], unique=False)
        _safe_create_index(hr_checklist_collection, [("done", ASCENDING)], unique=False)
        _safe_create_index(hr_checklist_collection, [("archived", ASCENDING)], unique=False)
        _safe_create_index(hr_checklist_collection, [("created_at", DESCENDING)], unique=False)
        _safe_create_index(hr_checklist_collection, [("updated_at", DESCENDING)], unique=False)

        _safe_create_index(hr_sheet_builder_collection, [("scope", ASCENDING)], unique=False)
        _safe_create_index(hr_sheet_builder_collection, [("sheet_id", ASCENDING)], unique=False)
        _safe_create_index(hr_sheet_builder_collection, [("updated_at", DESCENDING)], unique=False)
        _safe_create_index(hr_sheet_builder_collection, [("archived", ASCENDING)], unique=False)

        _safe_create_index(workspace_accounts_collection, [("email_lc", ASCENDING)], unique=True)
        _safe_create_index(workspace_accounts_collection, [("discord_id", ASCENDING)], unique=False)
        _safe_create_index(workspace_accounts_collection, [("role_id", DESCENDING)], unique=False)
        _safe_create_index(workspace_accounts_collection, [("created_at", DESCENDING)], unique=False)

        _safe_create_index(workspace_workspaces_collection, [("id", ASCENDING)], unique=True)
        _safe_create_index(workspace_workspaces_collection, [("owner_id", ASCENDING)], unique=False)
        _safe_create_index(workspace_workspaces_collection, [("min_role_id", ASCENDING)], unique=False)
        _safe_create_index(workspace_workspaces_collection, [("archived", ASCENDING)], unique=False)
        _safe_create_index(workspace_workspaces_collection, [("updated_at", DESCENDING)], unique=False)

        _safe_create_index(workspace_members_collection, [("workspace_id", ASCENDING), ("user_id", ASCENDING)], unique=True)
        _safe_create_index(workspace_members_collection, [("user_id", ASCENDING)], unique=False)
        _safe_create_index(workspace_members_collection, [("access", ASCENDING)], unique=False)

        _safe_create_index(workspace_folders_collection, [("id", ASCENDING)], unique=True)
        _safe_create_index(workspace_folders_collection, [("workspace_id", ASCENDING)], unique=False)
        _safe_create_index(workspace_folders_collection, [("parent_id", ASCENDING)], unique=False)
        _safe_create_index(workspace_folders_collection, [("archived", ASCENDING)], unique=False)

        _safe_create_index(workspace_project_maps_collection, [("id", ASCENDING)], unique=True)
        _safe_create_index(workspace_project_maps_collection, [("workspace_id", ASCENDING)], unique=False)
        _safe_create_index(workspace_project_maps_collection, [("folder_id", ASCENDING)], unique=False)
        _safe_create_index(workspace_project_maps_collection, [("archived", ASCENDING)], unique=False)

        _safe_create_index(workspace_sheets_collection, [("id", ASCENDING)], unique=True)
        _safe_create_index(workspace_sheets_collection, [("workspace_id", ASCENDING)], unique=False)
        _safe_create_index(workspace_sheets_collection, [("project_id", ASCENDING)], unique=False)
        _safe_create_index(workspace_sheets_collection, [("updated_at", DESCENDING)], unique=False)
        _safe_create_index(workspace_sheets_collection, [("archived", ASCENDING)], unique=False)

        _safe_create_index(workspace_invites_collection, [("code", ASCENDING)], unique=True)
        _safe_create_index(workspace_invites_collection, [("workspace_id", ASCENDING)], unique=False)
        _safe_create_index(workspace_invites_collection, [("email_lc", ASCENDING)], unique=False)
        _safe_create_index(workspace_invites_collection, [("claimed_by", ASCENDING)], unique=False)
        _safe_create_index(workspace_invites_collection, [("created_at", DESCENDING)], unique=False)

        _safe_create_index(workspace_events_collection, [("workspace_id", ASCENDING), ("created_at", DESCENDING)], unique=False)
        _safe_create_index(workspace_events_collection, [("event_id", ASCENDING)], unique=True)
        _safe_create_index(workspace_events_collection, [("user_id", ASCENDING)], unique=False)

        _safe_create_index(loa_collection, [("status", ASCENDING)], unique=False)
        _safe_create_index(loa_collection, [("start_date", ASCENDING)], unique=False)
        _safe_create_index(loa_collection, [("end_date", ASCENDING)], unique=False)
        _safe_create_index(loa_collection, [("user_id", ASCENDING)], unique=False)
        _safe_create_index(loa_collection, [("timestamp_raw", DESCENDING)], unique=False)
    except Exception as error:
        print(f"MongoDB Index-Erstellung fehlgeschlagen: {error}")

