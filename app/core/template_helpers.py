"""Globale Jinja-Template-Helfer für EifelLog."""

from __future__ import annotations

import secrets

from flask import session


def register_template_helpers(app) -> None:
    """Registriert Template-Helfer genau einmal."""
    if app.extensions.get("eifellog_template_helpers_registered"):
        return

    @app.context_processor
    def inject_template_helpers():
        def csrf_token():
            token = session.get("_csrf_token")
            if not token:
                token = secrets.token_hex(16)
                session["_csrf_token"] = token
            return token

        return {"csrf_token": csrf_token}

    app.extensions["eifellog_template_helpers_registered"] = True
