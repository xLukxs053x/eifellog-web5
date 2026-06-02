"""Tracker-Endpunkte der EifelLog-Anwendung.

Diese Datei bildet die HTTP-Routing-Schicht für den Tracker ab.
Die eigentliche Business-Logik bleibt während der schrittweisen Migration
vorübergehend in ``app.legacy`` und wird von den Blueprint-Routen delegiert.

Die Methodensets sind bewusst zentral definiert:
- Lese-Endpunkte akzeptieren GET, HEAD und OPTIONS.
- Tracker-Kompatibilitätsendpunkte akzeptieren zusätzlich POST, PUT und PATCH.
- Schreibende Aktionen bleiben auf POST, PUT, PATCH und OPTIONS beschränkt.
"""

from __future__ import annotations

from flask import Blueprint, jsonify

from app import legacy as _legacy
from app.core.utils import now_utc


tracker_bp = Blueprint("tracker", __name__)


READ_METHODS = ["GET", "HEAD", "OPTIONS"]
READ_WRITE_METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "OPTIONS"]
WRITE_METHODS = ["POST", "PUT", "PATCH", "OPTIONS"]
DOWNLOAD_METHODS = ["GET", "HEAD", "POST", "OPTIONS"]


@tracker_bp.route("/api/tracker/ping", methods=READ_METHODS)
def tracker_ping():
    """Prüft, ob der Tracker-Blueprint korrekt registriert wurde."""
    return jsonify(
        {
            "success": True,
            "service": "EifelLog Tracker",
            "time": now_utc().isoformat() + "Z",
        }
    )


@tracker_bp.route("/webhook", methods=READ_WRITE_METHODS)
@tracker_bp.route("/api/tracker/webhook", methods=READ_WRITE_METHODS)
@tracker_bp.route("/api/tracker/discord/webhook", methods=READ_WRITE_METHODS)
def tracker_local_webhook(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.tracker_local_webhook()."""
    return _legacy.tracker_local_webhook(*args, **kwargs)


@tracker_bp.route("/api/tracker/feierabend", methods=WRITE_METHODS)
def tracker_feierabend(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.tracker_feierabend()."""
    return _legacy.tracker_feierabend(*args, **kwargs)


@tracker_bp.route("/api/tracker/login", methods=READ_WRITE_METHODS)
def tracker_login(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.tracker_login()."""
    return _legacy.tracker_login(*args, **kwargs)


@tracker_bp.route("/api/tracker/session", methods=READ_WRITE_METHODS)
def tracker_session_login(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.tracker_session_login()."""
    return _legacy.tracker_session_login(*args, **kwargs)


@tracker_bp.route("/api/tracker/profile", methods=READ_WRITE_METHODS)
def tracker_profile(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.tracker_profile()."""
    return _legacy.tracker_profile(*args, **kwargs)


@tracker_bp.route("/api/tracker/state", methods=READ_WRITE_METHODS)
def tracker_state(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.tracker_state()."""
    return _legacy.tracker_state(*args, **kwargs)


@tracker_bp.route("/api/tracker/company/stats", methods=READ_WRITE_METHODS)
@tracker_bp.route("/api/tracker/company/state", methods=READ_WRITE_METHODS)
@tracker_bp.route("/api/company/stats", methods=READ_WRITE_METHODS)
@tracker_bp.route("/api/dashboard/company/stats", methods=READ_WRITE_METHODS)
def api_company_stats(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_company_stats()."""
    return _legacy.api_company_stats(*args, **kwargs)


@tracker_bp.route("/api/tracker/company/reset", methods=WRITE_METHODS)
@tracker_bp.route("/api/company/reset", methods=WRITE_METHODS)
def api_reset_company_stats(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_reset_company_stats()."""
    return _legacy.api_reset_company_stats(*args, **kwargs)


@tracker_bp.route("/api/tracker/telemetry/live", methods=READ_WRITE_METHODS)
def tracker_telemetry_live(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.tracker_telemetry_live()."""
    return _legacy.tracker_telemetry_live(*args, **kwargs)


@tracker_bp.route("/api/tracker/driver-card", methods=READ_WRITE_METHODS)
def tracker_driver_card(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.tracker_driver_card()."""
    return _legacy.tracker_driver_card(*args, **kwargs)


@tracker_bp.route("/api/tracker/driver-card/pin/verify", methods=WRITE_METHODS)
@tracker_bp.route("/api/tracker/fahrerkarte/pin/verify", methods=WRITE_METHODS)
def tracker_driver_card_pin_verify(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.tracker_driver_card_pin_verify()."""
    return _legacy.tracker_driver_card_pin_verify(*args, **kwargs)


@tracker_bp.route("/api/tracker/driver-card/upload", methods=WRITE_METHODS)
@tracker_bp.route("/api/tracker/fahrerkarte/upload", methods=WRITE_METHODS)
@tracker_bp.route("/api/tracker/driver-card/pdf/upload", methods=WRITE_METHODS)
@tracker_bp.route("/api/tracker/driver-card/file", methods=WRITE_METHODS)
def tracker_driver_card_upload(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.tracker_driver_card_upload()."""
    return _legacy.tracker_driver_card_upload(*args, **kwargs)


@tracker_bp.route("/api/tracker/driver-card/pdf", methods=DOWNLOAD_METHODS)
@tracker_bp.route("/api/tracker/driver-card/pdf/<card_id>", methods=DOWNLOAD_METHODS)
@tracker_bp.route("/api/tracker/driver-card/download", methods=DOWNLOAD_METHODS)
@tracker_bp.route("/api/tracker/driver-card/download/<card_id>", methods=DOWNLOAD_METHODS)
@tracker_bp.route("/api/tracker/fahrerkarte/pdf", methods=DOWNLOAD_METHODS)
@tracker_bp.route("/api/tracker/fahrerkarte/pdf/<card_id>", methods=DOWNLOAD_METHODS)
def tracker_driver_card_pdf_download(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.tracker_driver_card_pdf_download()."""
    return _legacy.tracker_driver_card_pdf_download(*args, **kwargs)


@tracker_bp.route("/api/tracker/driver-card/extract/pdf", methods=DOWNLOAD_METHODS)
@tracker_bp.route("/api/tracker/driver-card/extract/pdf/<selector>", methods=DOWNLOAD_METHODS)
@tracker_bp.route("/api/tracker/fahrerkarte/auszug/pdf", methods=DOWNLOAD_METHODS)
@tracker_bp.route("/api/tracker/fahrerkarte/auszug/pdf/<selector>", methods=DOWNLOAD_METHODS)
@tracker_bp.route("/api/tracker/shift/pdf", methods=DOWNLOAD_METHODS)
@tracker_bp.route("/api/tracker/shift/pdf/<selector>", methods=DOWNLOAD_METHODS)
def tracker_driver_card_extract_pdf_download(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.tracker_driver_card_extract_pdf_download()."""
    return _legacy.tracker_driver_card_extract_pdf_download(*args, **kwargs)


@tracker_bp.route("/api/tracker/work-session", methods=READ_WRITE_METHODS)
@tracker_bp.route("/api/tracker/worksession", methods=READ_WRITE_METHODS)
@tracker_bp.route("/api/tracker/arbeitszeit", methods=READ_WRITE_METHODS)
def tracker_work_session(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.tracker_work_session()."""
    return _legacy.tracker_work_session(*args, **kwargs)


@tracker_bp.route("/api/tracker/jobs/start", methods=READ_WRITE_METHODS)
@tracker_bp.route("/api/tracker/job/start", methods=READ_WRITE_METHODS)
@tracker_bp.route("/api/tracker/jobs/started", methods=READ_WRITE_METHODS)
@tracker_bp.route("/api/tracker/job/started", methods=READ_WRITE_METHODS)
@tracker_bp.route("/api/tracker/start-job", methods=READ_WRITE_METHODS)
@tracker_bp.route("/api/tracker/tour/start", methods=READ_WRITE_METHODS)
@tracker_bp.route("/api/tracker/tour/started", methods=READ_WRITE_METHODS)
def tracker_jobs_start(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.tracker_jobs_start()."""
    return _legacy.tracker_jobs_start(*args, **kwargs)


@tracker_bp.route("/api/tracker/tour/submit", methods=READ_WRITE_METHODS)
@tracker_bp.route("/api/tracker/tour/complete", methods=READ_WRITE_METHODS)
@tracker_bp.route("/api/tracker/tour/completed", methods=READ_WRITE_METHODS)
def tracker_tour_submit(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.tracker_tour_submit()."""
    return _legacy.tracker_tour_submit(*args, **kwargs)


@tracker_bp.route("/api/tracker/job/complete", methods=READ_WRITE_METHODS)
@tracker_bp.route("/api/tracker/jobs/complete", methods=READ_WRITE_METHODS)
@tracker_bp.route("/api/tracker/job/finish", methods=READ_WRITE_METHODS)
@tracker_bp.route("/api/tracker/jobs/finish", methods=READ_WRITE_METHODS)
@tracker_bp.route("/api/tracker/job/completed", methods=READ_WRITE_METHODS)
@tracker_bp.route("/api/tracker/jobs/completed", methods=READ_WRITE_METHODS)
@tracker_bp.route("/api/tracker/complete-job", methods=READ_WRITE_METHODS)
def tracker_job_complete(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.tracker_job_complete()."""
    return _legacy.tracker_job_complete(*args, **kwargs)


@tracker_bp.route("/api/tracker/logout", methods=READ_WRITE_METHODS)
def tracker_logout(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.tracker_logout()."""
    return _legacy.tracker_logout(*args, **kwargs)


@tracker_bp.route("/api/tracker/code/create", methods=READ_WRITE_METHODS)
def tracker_create_code_admin(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.tracker_create_code_admin()."""
    return _legacy.tracker_create_code_admin(*args, **kwargs)


@tracker_bp.route("/api/tracker/code/my", methods=READ_WRITE_METHODS)
def tracker_create_code_for_logged_in_user(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.tracker_create_code_for_logged_in_user()."""
    return _legacy.tracker_create_code_for_logged_in_user(*args, **kwargs)


@tracker_bp.route("/api/tracker/activity-state", methods=READ_WRITE_METHODS)
@tracker_bp.route("/api/tracker/driver-activity", methods=READ_WRITE_METHODS)
@tracker_bp.route("/api/tracker/fahrerkarte/state", methods=READ_WRITE_METHODS)
@tracker_bp.route("/api/tracker/state/update", methods=READ_WRITE_METHODS)
def update_driver_state(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.update_driver_state()."""
    return _legacy.update_driver_state(*args, **kwargs)
