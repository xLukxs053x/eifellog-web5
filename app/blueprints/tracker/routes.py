"""Tracker-Endpunkte der EifelLog-Anwendung."""

from __future__ import annotations

from flask import Blueprint, jsonify

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