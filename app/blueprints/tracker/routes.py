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

import json
from typing import Any, Callable

from flask import Blueprint, jsonify, make_response, request

from app import legacy as _legacy
from app.core.utils import now_utc


tracker_bp = Blueprint("tracker", __name__)


READ_METHODS = ["GET", "HEAD", "OPTIONS"]
READ_WRITE_METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "OPTIONS"]
WRITE_METHODS = ["POST", "PUT", "PATCH", "OPTIONS"]
DOWNLOAD_METHODS = ["GET", "HEAD", "POST", "OPTIONS"]


# Die Fahrerkarte läuft ohne PIN. Alte Desktop-Versionen und ältere WebAssets
# dürfen die bisherigen PIN-Endpunkte weiterhin ansprechen, erhalten dort aber
# sofort eine erfolgreiche Kompatibilitätsantwort. Dadurch bleibt kein Client
# dauerhaft im Zustand "Profil wird überprüft" hängen.
_PIN_REQUIRED_KEYS = {
    "pinrequired",
    "requirespin",
    "needspin",
    "pinneeded",
    "pinpending",
    "awaitingpin",
    "waitforpin",
}
_PIN_VERIFIED_KEYS = {
    "pinverified",
    "drivercardverified",
    "cardverified",
    "profileverified",
    "identityverified",
}
_PROFILE_CHECKING_KEYS = {
    "profilechecking",
    "profilepending",
    "verificationpending",
    "checkingprofile",
    "identitychecking",
}
_READY_KEYS = {
    "ready",
    "profileready",
    "cardready",
    "drivercardready",
    "identityloaded",
}
_STATUS_KEYS = {
    "status",
    "cardstatus",
    "drivercardstatus",
    "profilestatus",
    "verificationstatus",
}
_PENDING_STATUS_VALUES = {
    "checking",
    "verifying",
    "pending",
    "processing",
    "loading",
    "profile_checking",
    "profile-checking",
    "pin_required",
    "pin-required",
    "awaiting_pin",
    "awaiting-pin",
    "wait_for_pin",
    "wait-for-pin",
}
_DRIVER_CARD_BRANCH_KEYS = {
    "drivercard",
    "drivercardstate",
    "drivercardprofile",
    "card",
    "cardstate",
    "cardprofile",
    "fahrerkarte",
    "fahrerkartezustand",
    "fahrerkarteprofil",
    "profile",
    "identity",
}


def _compact_key(value: Any) -> str:
    """Normalisiert JSON-Schlüsselnamen für kompatible snake-/camel-case-Prüfungen."""
    return "".join(character for character in str(value).lower() if character.isalnum())


def _is_driver_card_branch_key(key: Any) -> bool:
    return _compact_key(key) in _DRIVER_CARD_BRANCH_KEYS


def _looks_like_pin_gate(value: Any) -> bool:
    """Erkennt ausschließlich alte Antworten, die den entfernten PIN-Schritt blockieren."""
    if isinstance(value, list):
        return any(_looks_like_pin_gate(item) for item in value)

    if not isinstance(value, dict):
        if isinstance(value, str):
            lowered = value.lower()
            return "pin" in lowered and any(
                marker in lowered
                for marker in (
                    "erforder",
                    "prüf",
                    "pruef",
                    "verify",
                    "verification",
                    "required",
                    "await",
                    "warte",
                    "fehl",
                )
            )
        return False

    for key, item in value.items():
        compact_key = _compact_key(key)

        if compact_key in _PIN_REQUIRED_KEYS and bool(item):
            return True

        if compact_key in _PIN_VERIFIED_KEYS and item is False:
            return True

        if _looks_like_pin_gate(item):
            return True

    return False


def _normalize_pinless_payload(value: Any, *, force_defaults: bool = False) -> Any:
    """Entfernt alte PIN-Wartezustände aus einer JSON-Antwort.

    Die eigentlichen Profildaten bleiben unverändert. Es werden nur die
    Kompatibilitätsfelder des abgeschafften PIN-Schritts korrigiert.
    """
    if isinstance(value, list):
        return [
            _normalize_pinless_payload(item, force_defaults=force_defaults)
            for item in value
        ]

    if not isinstance(value, dict):
        return value

    normalized: dict[str, Any] = {}

    for key, item in value.items():
        compact_key = _compact_key(key)
        child_force_defaults = _is_driver_card_branch_key(key)

        if compact_key in _PIN_REQUIRED_KEYS:
            normalized[key] = False
            continue

        if compact_key in _PIN_VERIFIED_KEYS:
            normalized[key] = True
            continue

        if compact_key in _PROFILE_CHECKING_KEYS:
            normalized[key] = False
            continue

        if compact_key in _READY_KEYS:
            normalized[key] = True
            continue

        if (
            compact_key in _STATUS_KEYS
            and force_defaults
            and isinstance(item, str)
            and item.strip().lower() in _PENDING_STATUS_VALUES
        ):
            normalized[key] = "ready"
            continue

        if isinstance(item, (dict, list)):
            normalized[key] = _normalize_pinless_payload(
                item,
                force_defaults=child_force_defaults,
            )
            continue

        normalized[key] = item

    if force_defaults:
        normalized.setdefault("pinRequired", False)
        normalized.setdefault("requiresPin", False)
        normalized.setdefault("pinVerified", True)
        normalized.setdefault("profileVerified", True)
        normalized.setdefault("profileChecking", False)
        normalized.setdefault("ready", True)

        status = normalized.get("status")
        if status is None or (
            isinstance(status, str)
            and status.strip().lower() in _PENDING_STATUS_VALUES
        ):
            normalized["status"] = "ready"

    return normalized


def _delegate_pinless_json(
    handler: Callable[..., Any],
    *args: Any,
    force_defaults: bool = False,
    **kwargs: Any,
):
    """Delegiert an legacy und korrigiert nur JSON-Antworten des alten PIN-Flows."""
    raw_response = handler(*args, **kwargs)
    response = make_response(raw_response)
    payload = response.get_json(silent=True)

    if payload is None:
        return response

    pin_gate = _looks_like_pin_gate(payload)

    # Normale Authentifizierungs- oder Validierungsfehler bleiben unverändert.
    # Nur ein alter PIN-Gate-Fehler wird als erfolgreicher No-PIN-Fallback
    # behandelt.
    if response.status_code >= 400 and not pin_gate:
        return response

    normalized_payload = _normalize_pinless_payload(
        payload,
        force_defaults=force_defaults or pin_gate,
    )

    if isinstance(normalized_payload, dict) and pin_gate:
        normalized_payload["success"] = True
        normalized_payload["ok"] = True
        normalized_payload["verified"] = True
        normalized_payload["pinVerified"] = True
        normalized_payload["profileVerified"] = True
        normalized_payload["profileChecking"] = False
        normalized_payload["pinRequired"] = False
        normalized_payload["requiresPin"] = False
        normalized_payload["ready"] = True
        normalized_payload["status"] = "ready"
        normalized_payload["message"] = "Fahrerkarte ist ohne PIN einsatzbereit."

    if pin_gate and response.status_code >= 400:
        response.status_code = 200

    response.set_data(
        json.dumps(
            normalized_payload,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    response.headers["Content-Type"] = "application/json; charset=utf-8"
    response.headers["Content-Length"] = str(len(response.get_data()))
    return response


def _pinless_driver_card_success_response():
    """Antwort für alte Clients, die den nicht mehr benötigten PIN-Call senden."""
    body = request.get_json(silent=True)
    card_id = ""

    if isinstance(body, dict):
        card_id = str(
            body.get("cardId")
            or body.get("card_id")
            or body.get("fahrerkarteId")
            or body.get("fahrerkarte_id")
            or ""
        ).strip()

    payload: dict[str, Any] = {
        "success": True,
        "ok": True,
        "verified": True,
        "pinVerified": True,
        "profileVerified": True,
        "profileChecking": False,
        "pinRequired": False,
        "requiresPin": False,
        "ready": True,
        "status": "ready",
        "message": "Fahrerkarte ist ohne PIN einsatzbereit.",
        "time": now_utc().isoformat() + "Z",
    }

    if card_id:
        payload["cardId"] = card_id

    return jsonify(payload)


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
    """Delegiert Login-Antworten und entfernt veraltete PIN-Wartezustände."""
    return _delegate_pinless_json(_legacy.tracker_login, *args, **kwargs)


@tracker_bp.route("/api/tracker/session", methods=READ_WRITE_METHODS)
def tracker_session_login(*args, **kwargs):
    """Delegiert Session-Antworten und entfernt veraltete PIN-Wartezustände."""
    return _delegate_pinless_json(_legacy.tracker_session_login, *args, **kwargs)


@tracker_bp.route("/api/tracker/profile", methods=READ_WRITE_METHODS)
def tracker_profile(*args, **kwargs):
    """Liefert das Profil ohne zusätzlichen PIN-Prüfschritt aus."""
    return _delegate_pinless_json(
        _legacy.tracker_profile,
        *args,
        force_defaults=True,
        **kwargs,
    )


@tracker_bp.route("/api/tracker/state", methods=READ_WRITE_METHODS)
def tracker_state(*args, **kwargs):
    """Liefert den Tracker-State ohne veraltete PIN-Wartezustände aus."""
    return _delegate_pinless_json(_legacy.tracker_state, *args, **kwargs)


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
@tracker_bp.route("/api/tracker/fahrerkarte", methods=READ_WRITE_METHODS)
def tracker_driver_card(*args, **kwargs):
    """Liefert die Fahrerkarte unmittelbar ohne PIN-Gate aus."""
    return _delegate_pinless_json(
        _legacy.tracker_driver_card,
        *args,
        force_defaults=True,
        **kwargs,
    )


@tracker_bp.route("/api/tracker/driver-card/pin/verify", methods=WRITE_METHODS)
@tracker_bp.route("/api/tracker/fahrerkarte/pin/verify", methods=WRITE_METHODS)
def tracker_driver_card_pin_verify(*args, **kwargs):
    """Kompatibilitätsroute: Die Fahrerkarte benötigt keine PIN mehr."""
    return _pinless_driver_card_success_response()


@tracker_bp.route("/api/tracker/driver-card/upload", methods=WRITE_METHODS)
@tracker_bp.route("/api/tracker/fahrerkarte/upload", methods=WRITE_METHODS)
@tracker_bp.route("/api/tracker/driver-card/pdf/upload", methods=WRITE_METHODS)
@tracker_bp.route("/api/tracker/driver-card/file", methods=WRITE_METHODS)
def tracker_driver_card_upload(*args, **kwargs):
    """Delegiert den Upload und entfernt veraltete PIN-Wartezustände."""
    return _delegate_pinless_json(
        _legacy.tracker_driver_card_upload,
        *args,
        force_defaults=True,
        **kwargs,
    )


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
    """Delegiert Arbeitszeit-Antworten und entfernt alte PIN-Wartezustände."""
    return _delegate_pinless_json(_legacy.tracker_work_session, *args, **kwargs)


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
    """Delegiert Fahrerstatus-Antworten und entfernt alte PIN-Wartezustände."""
    return _delegate_pinless_json(_legacy.update_driver_state, *args, **kwargs)
