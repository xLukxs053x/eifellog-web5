"""Tracker-Endpunkte der EifelLog-Anwendung."""

from __future__ import annotations

from flask import Blueprint, jsonify

from app import legacy as _legacy
from app.core.utils import now_utc


tracker_bp = Blueprint("tracker", __name__)


@tracker_bp.route("/api/tracker/ping", methods=["GET"])
def tracker_ping():
    """Prüft, ob der Tracker-Blueprint korrekt registriert wurde."""
    return jsonify(
        {
            "success": True,
            "service": "EifelLog Tracker",
            "time": now_utc().isoformat() + "Z",
        }
    )


@tracker_bp.route('/webhook', methods=['GET', 'POST', 'OPTIONS'])
@tracker_bp.route('/api/tracker/webhook', methods=['GET', 'POST', 'OPTIONS'])
@tracker_bp.route('/api/tracker/discord/webhook', methods=['GET', 'POST', 'OPTIONS'])
def tracker_local_webhook(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.tracker_local_webhook()."""
    return _legacy.tracker_local_webhook(*args, **kwargs)

@tracker_bp.route('/api/tracker/feierabend', methods=['POST', 'OPTIONS'])
def tracker_feierabend(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.tracker_feierabend()."""
    return _legacy.tracker_feierabend(*args, **kwargs)

@tracker_bp.route('/api/tracker/login', methods=['GET', 'POST', 'OPTIONS'])
def tracker_login(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.tracker_login()."""
    return _legacy.tracker_login(*args, **kwargs)

@tracker_bp.route('/api/tracker/session', methods=['GET', 'POST', 'OPTIONS'])
def tracker_session_login(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.tracker_session_login()."""
    return _legacy.tracker_session_login(*args, **kwargs)

@tracker_bp.route('/api/tracker/profile', methods=['GET', 'POST', 'OPTIONS'])
def tracker_profile(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.tracker_profile()."""
    return _legacy.tracker_profile(*args, **kwargs)

@tracker_bp.route('/api/tracker/state', methods=['GET', 'POST', 'OPTIONS'])
def tracker_state(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.tracker_state()."""
    return _legacy.tracker_state(*args, **kwargs)

@tracker_bp.route('/api/tracker/company/stats', methods=['GET', 'POST', 'OPTIONS'])
@tracker_bp.route('/api/tracker/company/state', methods=['GET', 'POST', 'OPTIONS'])
@tracker_bp.route('/api/company/stats', methods=['GET', 'POST', 'OPTIONS'])
@tracker_bp.route('/api/dashboard/company/stats', methods=['GET', 'POST', 'OPTIONS'])
def api_company_stats(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_company_stats()."""
    return _legacy.api_company_stats(*args, **kwargs)

@tracker_bp.route('/api/tracker/company/reset', methods=['POST', 'OPTIONS'])
@tracker_bp.route('/api/company/reset', methods=['POST', 'OPTIONS'])
def api_reset_company_stats(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_reset_company_stats()."""
    return _legacy.api_reset_company_stats(*args, **kwargs)

@tracker_bp.route('/api/tracker/telemetry/live', methods=['GET', 'POST', 'OPTIONS'])
def tracker_telemetry_live(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.tracker_telemetry_live()."""
    return _legacy.tracker_telemetry_live(*args, **kwargs)

@tracker_bp.route('/api/tracker/driver-card', methods=['GET', 'POST', 'OPTIONS'])
def tracker_driver_card(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.tracker_driver_card()."""
    return _legacy.tracker_driver_card(*args, **kwargs)

@tracker_bp.route('/api/tracker/driver-card/pin/verify', methods=['POST', 'OPTIONS'])
@tracker_bp.route('/api/tracker/fahrerkarte/pin/verify', methods=['POST', 'OPTIONS'])
def tracker_driver_card_pin_verify(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.tracker_driver_card_pin_verify()."""
    return _legacy.tracker_driver_card_pin_verify(*args, **kwargs)

@tracker_bp.route('/api/tracker/driver-card/upload', methods=['POST', 'OPTIONS'])
@tracker_bp.route('/api/tracker/fahrerkarte/upload', methods=['POST', 'OPTIONS'])
@tracker_bp.route('/api/tracker/driver-card/pdf/upload', methods=['POST', 'OPTIONS'])
@tracker_bp.route('/api/tracker/driver-card/file', methods=['POST', 'OPTIONS'])
def tracker_driver_card_upload(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.tracker_driver_card_upload()."""
    return _legacy.tracker_driver_card_upload(*args, **kwargs)

@tracker_bp.route('/api/tracker/driver-card/pdf', methods=['GET', 'POST', 'OPTIONS'])
@tracker_bp.route('/api/tracker/driver-card/pdf/<card_id>', methods=['GET', 'POST', 'OPTIONS'])
@tracker_bp.route('/api/tracker/driver-card/download', methods=['GET', 'POST', 'OPTIONS'])
@tracker_bp.route('/api/tracker/driver-card/download/<card_id>', methods=['GET', 'POST', 'OPTIONS'])
@tracker_bp.route('/api/tracker/fahrerkarte/pdf', methods=['GET', 'POST', 'OPTIONS'])
@tracker_bp.route('/api/tracker/fahrerkarte/pdf/<card_id>', methods=['GET', 'POST', 'OPTIONS'])
def tracker_driver_card_pdf_download(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.tracker_driver_card_pdf_download()."""
    return _legacy.tracker_driver_card_pdf_download(*args, **kwargs)

@tracker_bp.route('/api/tracker/driver-card/extract/pdf', methods=['GET', 'POST', 'OPTIONS'])
@tracker_bp.route('/api/tracker/driver-card/extract/pdf/<selector>', methods=['GET', 'POST', 'OPTIONS'])
@tracker_bp.route('/api/tracker/fahrerkarte/auszug/pdf', methods=['GET', 'POST', 'OPTIONS'])
@tracker_bp.route('/api/tracker/fahrerkarte/auszug/pdf/<selector>', methods=['GET', 'POST', 'OPTIONS'])
@tracker_bp.route('/api/tracker/shift/pdf', methods=['GET', 'POST', 'OPTIONS'])
@tracker_bp.route('/api/tracker/shift/pdf/<selector>', methods=['GET', 'POST', 'OPTIONS'])
def tracker_driver_card_extract_pdf_download(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.tracker_driver_card_extract_pdf_download()."""
    return _legacy.tracker_driver_card_extract_pdf_download(*args, **kwargs)

@tracker_bp.route('/api/tracker/work-session', methods=['GET', 'POST', 'OPTIONS'])
@tracker_bp.route('/api/tracker/worksession', methods=['GET', 'POST', 'OPTIONS'])
@tracker_bp.route('/api/tracker/arbeitszeit', methods=['GET', 'POST', 'OPTIONS'])
def tracker_work_session(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.tracker_work_session()."""
    return _legacy.tracker_work_session(*args, **kwargs)

@tracker_bp.route('/api/tracker/jobs/start', methods=['GET', 'POST', 'OPTIONS'])
@tracker_bp.route('/api/tracker/job/start', methods=['GET', 'POST', 'OPTIONS'])
@tracker_bp.route('/api/tracker/jobs/started', methods=['GET', 'POST', 'OPTIONS'])
@tracker_bp.route('/api/tracker/job/started', methods=['GET', 'POST', 'OPTIONS'])
@tracker_bp.route('/api/tracker/start-job', methods=['GET', 'POST', 'OPTIONS'])
@tracker_bp.route('/api/tracker/tour/start', methods=['GET', 'POST', 'OPTIONS'])
@tracker_bp.route('/api/tracker/tour/started', methods=['GET', 'POST', 'OPTIONS'])
def tracker_jobs_start(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.tracker_jobs_start()."""
    return _legacy.tracker_jobs_start(*args, **kwargs)

@tracker_bp.route('/api/tracker/tour/submit', methods=['GET', 'POST', 'OPTIONS'])
@tracker_bp.route('/api/tracker/tour/complete', methods=['GET', 'POST', 'OPTIONS'])
@tracker_bp.route('/api/tracker/tour/completed', methods=['GET', 'POST', 'OPTIONS'])
def tracker_tour_submit(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.tracker_tour_submit()."""
    return _legacy.tracker_tour_submit(*args, **kwargs)

@tracker_bp.route('/api/tracker/job/complete', methods=['GET', 'POST', 'OPTIONS'])
@tracker_bp.route('/api/tracker/jobs/complete', methods=['GET', 'POST', 'OPTIONS'])
@tracker_bp.route('/api/tracker/job/finish', methods=['GET', 'POST', 'OPTIONS'])
@tracker_bp.route('/api/tracker/jobs/finish', methods=['GET', 'POST', 'OPTIONS'])
@tracker_bp.route('/api/tracker/job/completed', methods=['GET', 'POST', 'OPTIONS'])
@tracker_bp.route('/api/tracker/jobs/completed', methods=['GET', 'POST', 'OPTIONS'])
@tracker_bp.route('/api/tracker/complete-job', methods=['GET', 'POST', 'OPTIONS'])
def tracker_job_complete(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.tracker_job_complete()."""
    return _legacy.tracker_job_complete(*args, **kwargs)

@tracker_bp.route('/api/tracker/logout', methods=['GET', 'POST', 'OPTIONS'])
def tracker_logout(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.tracker_logout()."""
    return _legacy.tracker_logout(*args, **kwargs)

@tracker_bp.route('/api/tracker/code/create', methods=['GET', 'POST', 'OPTIONS'])
def tracker_create_code_admin(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.tracker_create_code_admin()."""
    return _legacy.tracker_create_code_admin(*args, **kwargs)

@tracker_bp.route('/api/tracker/code/my', methods=['GET', 'POST', 'OPTIONS'])
def tracker_create_code_for_logged_in_user(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.tracker_create_code_for_logged_in_user()."""
    return _legacy.tracker_create_code_for_logged_in_user(*args, **kwargs)

@tracker_bp.route('/api/tracker/activity-state', methods=['POST', 'OPTIONS'])
@tracker_bp.route('/api/tracker/driver-activity', methods=['POST', 'OPTIONS'])
@tracker_bp.route('/api/tracker/fahrerkarte/state', methods=['POST', 'OPTIONS'])
@tracker_bp.route('/api/tracker/state/update', methods=['POST', 'OPTIONS'])
def update_driver_state(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.update_driver_state()."""
    return _legacy.update_driver_state(*args, **kwargs)
