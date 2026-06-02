"""Globale HTTP-Hooks und JSON-Fehlerbehandlung für EifelLog."""

from __future__ import annotations

from flask import jsonify, request
from werkzeug.exceptions import HTTPException

from app.core.utils import safe_str


def is_api_like_request_path() -> bool:
    path = safe_str(request.path)
    return path.startswith("/api/") or path in {
        "/webhook",
        "/api/tracker/webhook",
        "/api/tracker/discord/webhook",
    }


def register_http_handlers(app) -> None:
    """Registriert CORS, OPTIONS und API-Fehlerhandler genau einmal."""
    if app.extensions.get("eifellog_http_handlers_registered"):
        return

    @app.after_request
    def add_tracker_headers(response):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Headers"] = (
            "Content-Type, Accept, Origin, Authorization, X-Tracker-Token, "
            "X-Tracker-Code, X-Tracker-Client-Token, X-Client-Token, "
            "X-Tracker-Api-Key, X-Tracker-Pdf-Ticket, X-Requested-With"
        )
        response.headers["Access-Control-Allow-Methods"] = (
            "GET, POST, PUT, PATCH, DELETE, OPTIONS"
        )
        response.headers["Access-Control-Max-Age"] = "86400"
        response.headers["Access-Control-Allow-Private-Network"] = "true"
        response.headers["Access-Control-Expose-Headers"] = (
            "Content-Type, Content-Disposition, Content-Length, ETag, "
            "Last-Modified, X-EifelLog-Pdf-Type, X-EifelLog-Shift-Id, "
            "X-EifelLog-Driver-Card-Id"
        )
        return response

    @app.route("/api/<path:any_path>", methods=["OPTIONS"])
    def api_options(any_path):
        return jsonify({"success": True})

    @app.errorhandler(HTTPException)
    def handle_http_exception_json(error):
        if is_api_like_request_path():
            status_code = int(getattr(error, "code", 500) or 500)
            return jsonify(
                {
                    "success": False,
                    "error": safe_str(
                        getattr(error, "description", ""),
                        "HTTP-Fehler",
                    ),
                    "statusCode": status_code,
                    "path": request.path,
                }
            ), status_code
        return error

    @app.errorhandler(Exception)
    def handle_unexpected_api_exception(error):
        if is_api_like_request_path():
            app.logger.exception("Unerwarteter API-/Tracker-Fehler")
            return jsonify(
                {
                    "success": False,
                    "error": "Interner Serverfehler im Tracker-Backend.",
                    "details": safe_str(error),
                    "path": request.path,
                }
            ), 500
        raise error

    app.extensions["eifellog_http_handlers_registered"] = True
