"""MongoDB-Indizes für EifelLog."""

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
        system_documents_collection.create_index([("expires_at", ASCENDING)], unique=False)
        system_documents_collection.create_index([("fixed", ASCENDING)], unique=False)

        instruction_acknowledgements_collection.create_index(
            [("discord_id", ASCENDING), ("instruction_id", ASCENDING)],
            unique=True,
        )
        instruction_acknowledgements_collection.create_index([("instruction_id", ASCENDING)], unique=False)
        instruction_acknowledgements_collection.create_index([("acknowledged_at", DESCENDING)], unique=False)
        
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
        buchhaltung_entries_collection.create_index([("job_status", ASCENDING)], unique=False)
        buchhaltung_entries_collection.create_index([("pdf_archive_id", ASCENDING)], unique=False)
        buchhaltung_entries_collection.create_index([("pdf.sha256", ASCENDING)], unique=False)
        buchhaltung_entries_collection.create_index([("pdf.uploaded_at", DESCENDING)], unique=False)
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
        fahrerkarte_requests_collection.create_index([("discord_id", ASCENDING), ("card_id", ASCENDING), ("status", ASCENDING), ("archived", ASCENDING)], unique=False)
        fahrerkarte_requests_collection.create_index([("pdf_relative_path", ASCENDING)], unique=False)
        fahrerkarte_requests_collection.create_index([("fahrerkarte_pin_issued_at", DESCENDING)], unique=False)
        fahrerkarte_requests_collection.create_index([("fahrerkarte_pin_locked_until", ASCENDING)], unique=False)
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

        servicecenter_bildungen_requests_collection.create_index([("request_id", ASCENDING)], unique=True)
        servicecenter_bildungen_requests_collection.create_index([("discord_id", ASCENDING)], unique=False)
        servicecenter_bildungen_requests_collection.create_index([("category", ASCENDING)], unique=False)
        servicecenter_bildungen_requests_collection.create_index([("offer_id", ASCENDING)], unique=False)
        servicecenter_bildungen_requests_collection.create_index([("status", ASCENDING)], unique=False)
        servicecenter_bildungen_requests_collection.create_index([("created_at", DESCENDING)], unique=False)
        servicecenter_bildungen_requests_collection.create_index([("updated_at", DESCENDING)], unique=False)
        servicecenter_bildungen_requests_collection.create_index([("appointment_at", ASCENDING)], unique=False)
        servicecenter_bildungen_requests_collection.create_index([("appointment_confirmation_status", ASCENDING)], unique=False)
        servicecenter_bildungen_requests_collection.create_index([("claimed_by.discord_id", ASCENDING)], unique=False)
        servicecenter_bildungen_requests_collection.create_index([("archived", ASCENDING)], unique=False)

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
        tracker_job_starts_collection.create_index([("job_start_key", ASCENDING)], unique=False)
        tracker_job_starts_collection.create_index([("status", ASCENDING)], unique=False)
        tracker_job_starts_collection.create_index([("created_at", DESCENDING)], unique=False)
        tracker_job_starts_collection.create_index([("tour_start_discord_sent_at", DESCENDING)], unique=False)
        tracker_job_starts_collection.create_index([("completed_at", DESCENDING)], unique=False)
        tracker_job_starts_collection.create_index([("discord_id", ASCENDING), ("job_start_key", ASCENDING), ("status", ASCENDING)], unique=False)

        driver_logs_collection.create_index([("discord_id", ASCENDING)], unique=False)
        driver_logs_collection.create_index([("user_id", ASCENDING)], unique=False)
        driver_logs_collection.create_index([("date_str", ASCENDING)], unique=False)
        driver_logs_collection.create_index([("date_display", ASCENDING)], unique=False)
        driver_logs_collection.create_index([("start_time", ASCENDING)], unique=False)
        driver_logs_collection.create_index([("end_time", ASCENDING)], unique=False)
        driver_logs_collection.create_index([("state_key", ASCENDING)], unique=False)
        driver_logs_collection.create_index([("discord_id", ASCENDING), ("date_str", ASCENDING), ("start_time", ASCENDING)], unique=False)

        tracker_shift_logs_collection.create_index([("shift_id", ASCENDING)], unique=False)
        tracker_shift_logs_collection.create_index([("discord_id", ASCENDING)], unique=False)
        tracker_shift_logs_collection.create_index([("shift_date", ASCENDING)], unique=False)
        tracker_shift_logs_collection.create_index([("date_str", ASCENDING)], unique=False)
        tracker_shift_logs_collection.create_index([("created_at", DESCENDING)], unique=False)
        tracker_shift_logs_collection.create_index([("updated_at", DESCENDING)], unique=False)
        tracker_shift_logs_collection.create_index([("discord_id", ASCENDING), ("date_str", ASCENDING)], unique=False)

        hr_personalakten_collection.create_index([("employee_id", ASCENDING)], unique=False)
        hr_personalakten_collection.create_index([("id", ASCENDING)], unique=False)
        hr_personalakten_collection.create_index([("name_lc", ASCENDING)], unique=False)
        hr_personalakten_collection.create_index([("email_lc", ASCENDING)], unique=False)
        hr_personalakten_collection.create_index([("status", ASCENDING)], unique=False)
        hr_personalakten_collection.create_index([("process", ASCENDING)], unique=False)
        hr_personalakten_collection.create_index([("archived", ASCENDING)], unique=False)
        hr_personalakten_collection.create_index([("created_at", DESCENDING)], unique=False)
        hr_personalakten_collection.create_index([("updated_at", DESCENDING)], unique=False)

        hr_process_plan_collection.create_index([("process_id", ASCENDING)], unique=False)
        hr_process_plan_collection.create_index([("sort_order", ASCENDING)], unique=False)
        hr_process_plan_collection.create_index([("phase", ASCENDING)], unique=False)
        hr_process_plan_collection.create_index([("archived", ASCENDING)], unique=False)
        hr_process_plan_collection.create_index([("created_at", DESCENDING)], unique=False)
        hr_process_plan_collection.create_index([("updated_at", DESCENDING)], unique=False)

        hr_checklist_collection.create_index([("item_id", ASCENDING)], unique=False)
        hr_checklist_collection.create_index([("process", ASCENDING)], unique=False)
        hr_checklist_collection.create_index([("done", ASCENDING)], unique=False)
        hr_checklist_collection.create_index([("archived", ASCENDING)], unique=False)
        hr_checklist_collection.create_index([("created_at", DESCENDING)], unique=False)
        hr_checklist_collection.create_index([("updated_at", DESCENDING)], unique=False)

        hr_sheet_builder_collection.create_index([("scope", ASCENDING)], unique=False)
        hr_sheet_builder_collection.create_index([("sheet_id", ASCENDING)], unique=False)
        hr_sheet_builder_collection.create_index([("updated_at", DESCENDING)], unique=False)
        hr_sheet_builder_collection.create_index([("archived", ASCENDING)], unique=False)

        workspace_accounts_collection.create_index([("email_lc", ASCENDING)], unique=True)
        workspace_accounts_collection.create_index([("discord_id", ASCENDING)], unique=False)
        workspace_accounts_collection.create_index([("role_id", DESCENDING)], unique=False)
        workspace_accounts_collection.create_index([("created_at", DESCENDING)], unique=False)

        workspace_workspaces_collection.create_index([("id", ASCENDING)], unique=True)
        workspace_workspaces_collection.create_index([("owner_id", ASCENDING)], unique=False)
        workspace_workspaces_collection.create_index([("min_role_id", ASCENDING)], unique=False)
        workspace_workspaces_collection.create_index([("archived", ASCENDING)], unique=False)
        workspace_workspaces_collection.create_index([("updated_at", DESCENDING)], unique=False)

        workspace_members_collection.create_index([("workspace_id", ASCENDING), ("user_id", ASCENDING)], unique=True)
        workspace_members_collection.create_index([("user_id", ASCENDING)], unique=False)
        workspace_members_collection.create_index([("access", ASCENDING)], unique=False)

        workspace_folders_collection.create_index([("id", ASCENDING)], unique=True)
        workspace_folders_collection.create_index([("workspace_id", ASCENDING)], unique=False)
        workspace_folders_collection.create_index([("parent_id", ASCENDING)], unique=False)
        workspace_folders_collection.create_index([("archived", ASCENDING)], unique=False)

        workspace_project_maps_collection.create_index([("id", ASCENDING)], unique=True)
        workspace_project_maps_collection.create_index([("workspace_id", ASCENDING)], unique=False)
        workspace_project_maps_collection.create_index([("folder_id", ASCENDING)], unique=False)
        workspace_project_maps_collection.create_index([("archived", ASCENDING)], unique=False)

        workspace_sheets_collection.create_index([("id", ASCENDING)], unique=True)
        workspace_sheets_collection.create_index([("workspace_id", ASCENDING)], unique=False)
        workspace_sheets_collection.create_index([("project_id", ASCENDING)], unique=False)
        workspace_sheets_collection.create_index([("updated_at", DESCENDING)], unique=False)
        workspace_sheets_collection.create_index([("archived", ASCENDING)], unique=False)

        workspace_invites_collection.create_index([("code", ASCENDING)], unique=True)
        workspace_invites_collection.create_index([("workspace_id", ASCENDING)], unique=False)
        workspace_invites_collection.create_index([("email_lc", ASCENDING)], unique=False)
        workspace_invites_collection.create_index([("claimed_by", ASCENDING)], unique=False)
        workspace_invites_collection.create_index([("created_at", DESCENDING)], unique=False)

        workspace_events_collection.create_index([("workspace_id", ASCENDING), ("created_at", DESCENDING)], unique=False)
        workspace_events_collection.create_index([("event_id", ASCENDING)], unique=True)
        workspace_events_collection.create_index([("user_id", ASCENDING)], unique=False)

        loa_collection.create_index([("status", ASCENDING)], unique=False)
        loa_collection.create_index([("start_date", ASCENDING)], unique=False)
        loa_collection.create_index([("end_date", ASCENDING)], unique=False)
        loa_collection.create_index([("user_id", ASCENDING)], unique=False)
        loa_collection.create_index([("timestamp_raw", DESCENDING)], unique=False)
    except Exception as error:
        print(f"MongoDB Index-Erstellung fehlgeschlagen: {error}")

