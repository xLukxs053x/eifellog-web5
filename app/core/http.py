"""Globale HTTP-Hooks und JSON-Fehlerbehandlung für EifelLog."""

from __future__ import annotations

from flask import jsonify, request
from werkzeug.exceptions import HTTPException, MethodNotAllowed

from app.core.utils import safe_str


def is_api_like_request_path() -> bool:
    """Erkennt API-, Tracker- und Webhook-Anfragen."""

    path = safe_str(request.path)

    return (
        path.startswith("/api/")
        or path in {
            "/webhook",
            "/api/tracker/webhook",
            "/api/tracker/discord/webhook",
        }
    )


def _allowed_methods_for_error(error) -> list[str]:
    """Liest die von Flask erlaubten HTTP-Methoden robust aus."""

    valid_methods = getattr(error, "valid_methods", None) or []

    return sorted(
        {
            safe_str(method).upper()
            for method in valid_methods
            if safe_str(method)
        }
    )


def register_http_handlers(app) -> None:
    """Registriert CORS, OPTIONS und API-Fehlerhandler genau einmal."""

    if app.extensions.get("eifellog_http_handlers_registered"):
        return

    @app.after_request
    def add_tracker_headers(response):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Headers"] = (
            "Content-Type, Accept, Origin, Authorization, "
            "X-Tracker-Token, X-Tracker-Code, X-Tracker-Client-Token, "
            "X-Client-Token, X-Tracker-Api-Key, X-Tracker-Pdf-Ticket, "
            "X-Requested-With"
        )
        response.headers["Access-Control-Allow-Methods"] = (
            "GET, HEAD, POST, PUT, PATCH, DELETE, OPTIONS"
        )
        response.headers["Access-Control-Max-Age"] = "86400"
        response.headers["Access-Control-Allow-Private-Network"] = "true"
        response.headers["Access-Control-Expose-Headers"] = (
            "Content-Type, Content-Disposition, Content-Length, "
            "ETag, Last-Modified, X-EifelLog-Pdf-Type, "
            "X-EifelLog-Shift-Id, X-EifelLog-Driver-Card-Id"
        )

        return response

    @app.route("/api/<path:any_path>", methods=["OPTIONS"])
    def api_options(any_path):
        return jsonify(
            {
                "success": True,
                "method": request.method,
                "path": request.path,
            }
        )

    @app.errorhandler(MethodNotAllowed)
    def handle_method_not_allowed(error):
        allowed_methods = _allowed_methods_for_error(error)
        allowed_text = ", ".join(allowed_methods) if allowed_methods else "unbekannt"

        message = (
            f"HTTP-Methode {request.method} ist für {request.path} nicht erlaubt. "
            f"Erlaubt: {allowed_text}"
        )

        app.logger.warning(
            "405 Method Not Allowed: method=%s path=%s endpoint=%s allowed=%s",
            request.method,
            request.path,
            request.endpoint,
            allowed_text,
        )

        if is_api_like_request_path():
            return jsonify(
                {
                    "success": False,
                    "error": message,
                    "message": message,
                    "statusCode": 405,
                    "method": request.method,
                    "path": request.path,
                    "endpoint": request.endpoint,
                    "allowedMethods": allowed_methods,
                }
            ), 405

        return error

    @app.errorhandler(HTTPException)
    def handle_http_exception_json(error):
        if is_api_like_request_path():
            status_code = int(getattr(error, "code", 500) or 500)

            message = safe_str(
                getattr(error, "description", ""),
                "HTTP-Fehler",
            )

            app.logger.warning(
                "HTTP-Fehler: status=%s method=%s path=%s endpoint=%s message=%s",
                status_code,
                request.method,
                request.path,
                request.endpoint,
                message,
            )

            return jsonify(
                {
                    "success": False,
                    "error": message,
                    "message": message,
                    "statusCode": status_code,
                    "method": request.method,
                    "path": request.path,
                    "endpoint": request.endpoint,
                }
            ), status_code

        return error

    @app.errorhandler(Exception)
    def handle_unexpected_api_exception(error):
        if is_api_like_request_path():
            app.logger.exception(
                "Unerwarteter API-/Tracker-Fehler: method=%s path=%s endpoint=%s",
                request.method,
                request.path,
                request.endpoint,
            )

            return jsonify(
                {
                    "success": False,
                    "error": "Interner Serverfehler im Tracker-Backend.",
                    "message": "Interner Serverfehler im Tracker-Backend.",
                    "details": safe_str(error),
                    "statusCode": 500,
                    "method": request.method,
                    "path": request.path,
                    "endpoint": request.endpoint,
                }
            ), 500

        raise error

    app.extensions["eifellog_http_handlers_registered"] = True