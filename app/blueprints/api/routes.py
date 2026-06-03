"""Allgemeine API-Endpunkte der EifelLog-Anwendung."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from bson import ObjectId
from flask import Blueprint, current_app, jsonify, request, session
from pymongo.errors import PyMongoError

from app import legacy as _legacy
from app.config import MONGO_DB_NAME, TRACKER_JOB_START_PUBLIC_URL
from app.core.utils import now_utc, safe_str
from app.db.collections import (
    birthdays_collection,
    events_collection,
    users_collection,
)


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


def serialize_mongo_value(value: Any) -> Any:
    """
    Wandelt MongoDB-Werte rekursiv in JSON-kompatible Werte um.

    Dadurch können unter anderem ObjectId- und Datumswerte sicher über
    Flask jsonify() ausgegeben werden.
    """
    if isinstance(value, ObjectId):
        return str(value)

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if isinstance(value, dict):
        return {
            key: serialize_mongo_value(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple)):
        return [
            serialize_mongo_value(item)
            for item in value
        ]

    return value


def get_logged_in_discord_id() -> str:
    """Liest die Discord-ID robust aus der bestehenden Flask-Session."""
    user_session = session.get("user")

    if isinstance(user_session, dict):
        return safe_str(
            user_session.get("id")
            or user_session.get("discord_id")
        )

    if isinstance(user_session, str):
        username = safe_str(user_session).lower()
        if not username:
            return ""

        user_doc = users_collection.find_one({"username_lc": username})
        return safe_str((user_doc or {}).get("discord_id"))

    return ""


# ---------------------------------------------------------------------------
# Öffentliche Event-API
#
# Verfügbare URLs:
#   GET /api/events
#   GET /api/public/events
#
# MongoDB:
#   Datenbank:  EVENT_DB_NAME
#   Collection: EVENT_COLLECTION_NAME
# ---------------------------------------------------------------------------

@api_bp.route("/api/events", methods=["GET"])
@api_bp.route("/api/public/events", methods=["GET"])
def public_events():
    """Liefert die öffentlichen Event-Einträge aus MongoDB."""
    try:
        events = list(events_collection.find({}))

        return jsonify(
            [
                serialize_mongo_value(event)
                for event in events
            ]
        )

    except PyMongoError:
        current_app.logger.exception(
            "Öffentliche Event-API konnte nicht geladen werden."
        )

        return jsonify(
            {
                "success": False,
                "error": "Events konnten nicht geladen werden.",
            }
        ), 500


# ---------------------------------------------------------------------------
# Öffentliche Birthday-API
#
# Verfügbare URLs:
#   GET /api/birthdays
#   GET /api/public/birthdays
#
# MongoDB:
#   Datenbank:  BIRTHDAY_DB_NAME
#   Collection: BIRTHDAY_COLLECTION_NAME
# ---------------------------------------------------------------------------

@api_bp.route("/api/birthdays", methods=["GET"])
@api_bp.route("/api/public/birthdays", methods=["GET"])
def public_birthdays():
    """Liefert die öffentlichen Geburtstagseinträge aus MongoDB."""
    try:
        birthdays = list(birthdays_collection.find({}))

        return jsonify(
            [
                serialize_mongo_value(birthday)
                for birthday in birthdays
            ]
        )

    except PyMongoError:
        current_app.logger.exception(
            "Öffentliche Birthday-API konnte nicht geladen werden."
        )

        return jsonify(
            {
                "success": False,
                "error": "Geburtstage konnten nicht geladen werden.",
            }
        ), 500


# ---------------------------------------------------------------------------
# Richtlinien-Unterschrift
# ---------------------------------------------------------------------------

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
        {"discord_id": discord_id},
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

    return jsonify({"success": True})


# ---------------------------------------------------------------------------
# Health-Check
# ---------------------------------------------------------------------------

@api_bp.route("/api/health", methods=["GET"])
def health_check():
    """Liefert einen Statuscheck für Server, Datenbank und Tracker-Routen."""
    tracker_routes = list(TRACKER_ROUTES)

    if (
        TRACKER_JOB_START_PUBLIC_URL
        and TRACKER_JOB_START_PUBLIC_URL not in tracker_routes
    ):
        tracker_routes.insert(
            tracker_routes.index("/api/tracker/tour/start"),
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


# ---------------------------------------------------------------------------
# Legacy-Kompatibilität
# ---------------------------------------------------------------------------

@api_bp.route("/api/wartungsarbeiten", methods=["GET", "POST"])
@api_bp.route(
    "/api/wartungsarbeiten/<state>",
    methods=["GET", "POST"],
)
def api_wartungsarbeiten(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_wartungsarbeiten()."""
    return _legacy.api_wartungsarbeiten(*args, **kwargs)