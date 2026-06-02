"""Allgemeine API-Endpunkte der EifelLog-Anwendung."""

from __future__ import annotations

from flask import Blueprint, jsonify, request, session

from app.config import MONGO_DB_NAME, TRACKER_JOB_START_PUBLIC_URL
from app.core.utils import now_utc, safe_str
from app.db.collections import users_collection


api_bp = Blueprint("api", __name__)


TRACKER_ROUTES = (
    "/api/tracker/ping",
    "/api/tracker/login",
    "/api/tracker/session",
    "/api/tracker/profile",
    "/api/tracker/state",
    "/api/tracker/telemetry/live",
    "/api/tracker/activity-state",
    "/api/tracker/driver-activity",
    "/api/tracker/fahrerkarte/state",
    "/api/tracker/state/update",
    "/api/tracker/driver-card",
    "/api/tracker/driver-card/upload",
    "/api/tracker/driver-card/extract/pdf/<shift_id>",
    "/api/tracker/fahrerkarte/auszug/pdf/<shift_id>",
    "/api/tracker/work-session",
    "/api/tracker/jobs/start",
    "/api/tracker/tour/start",
    "/api/tracker/tour/submit",
    "/api/tracker/tour/complete",
    "/api/tracker/job/complete",
    "/api/tracker/jobs/completed",
    "/api/tracker/logout",
    "/api/hr/driver_card_log/<discord_id>/<date_str>",
    "/api/hr/driver-card/pdf/<user_id>/<date_str>",
    "/webhook",
    "/api/tracker/webhook",
    "/api/tracker/discord/webhook",
)


def get_logged_in_discord_id() -> str:
    """Liest die Discord-ID robust aus der bestehenden Flask-Session."""

    user_session = session.get("user")

    if isinstance(user_session, dict):
        return safe_str(
            user_session.get("id")
            or user_session.get("discord_id")
        )

    # Legacy-Kompatibilität:
    # Ältere Sessions können nur einen Benutzernamen als String enthalten.
    if isinstance(user_session, str):
        username = safe_str(user_session).lower()
        if not username:
            return ""

        user_doc = users_collection.find_one(
            {
                "username_lc": username,
            }
        )

        return safe_str((user_doc or {}).get("discord_id"))

    return ""


@api_bp.route("/api/sign_policy", methods=["POST"])
def sign_policy():
    """Speichert die Richtlinien-Unterschrift eines eingeloggten Nutzers."""

    discord_id = get_logged_in_discord_id()
    if not discord_id:
        return jsonify(
            {
                "success": False,
                "error": "Not logged in",
            }
        ), 401

    data = request.get_json(silent=True) or {}
    signature = safe_str(data.get("signature"))

    if not signature:
        return jsonify(
            {
                "success": False,
                "error": "No signature provided",
            }
        ), 400

    update_result = users_collection.update_one(
        {
            "discord_id": discord_id,
        },
        {
            "$set": {
                "policy_signed": True,
                "policy_signature": signature,
                "policy_signed_at": now_utc(),
            }
        },
    )

    if update_result.matched_count == 0:
        return jsonify(
            {
                "success": False,
                "error": "User not found",
            }
        ), 404

    return jsonify(
        {
            "success": True,
        }
    )


@api_bp.route("/api/health", methods=["GET"])
def health_check():
    """Liefert einen Statuscheck für Server, Datenbank und Tracker-Routen."""

    tracker_routes = list(TRACKER_ROUTES)

    if (
        TRACKER_JOB_START_PUBLIC_URL
        and TRACKER_JOB_START_PUBLIC_URL not in tracker_routes
    ):
        insert_index = tracker_routes.index("/api/tracker/tour/start")

        tracker_routes.insert(
            insert_index,
            TRACKER_JOB_START_PUBLIC_URL,
        )

    return jsonify(
        {
            "success": True,
            "service": "EifelLog",
            "database": MONGO_DB_NAME,
            "time": now_utc().isoformat() + "Z",
            "trackerJobStartUrl": TRACKER_JOB_START_PUBLIC_URL,
            "trackerRoutes": tracker_routes,
        }
    )