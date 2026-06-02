"""Produktions-Entrypoint für den Eifel LOG Server.

Wichtig:
- Eventlet wird gepatcht, bevor Flask, PyMongo oder Requests importiert werden.
- Die Flask-App wird ausschließlich über app.create_app() erzeugt.
- Beim Start wird geprüft, ob die zentralen Tracker-Routen korrekt registriert
  wurden. Dadurch fällt eine fehlerhafte Blueprint-Registrierung sofort auf,
  statt erst später als HTTP 405 im Desktop-Tracker sichtbar zu werden.
"""

from __future__ import annotations

from typing import Iterable

import eventlet

# Muss zwingend vor dem Import der Flask-App und ihrer Abhängigkeiten laufen.
eventlet.monkey_patch()

import eventlet.wsgi
from flask import Flask

from app import create_app
from app.config import MONGO_DB_NAME, SERVER_HOST, SERVER_PORT


def _normalize_methods(methods: Iterable[str]) -> set[str]:
    """Normalisiert Flask-Methodenmengen für robuste Startprüfungen."""
    return {str(method).strip().upper() for method in methods if str(method).strip()}


def _registered_methods(flask_app: Flask, route_path: str) -> set[str]:
    """Liefert alle für einen konkreten Pfad registrierten HTTP-Methoden."""
    methods: set[str] = set()

    for rule in flask_app.url_map.iter_rules():
        if rule.rule == route_path:
            methods.update(_normalize_methods(rule.methods or set()))

    return methods


def validate_tracker_routes(flask_app: Flask) -> None:
    """Prüft die für den Desktop-Tracker zwingend benötigten Blueprint-Routen.

    Ein fehlender oder unvollständig registrierter Tracker-Blueprint würde bei
    schreibenden Requests typischerweise zu ``405 Method Not Allowed`` führen.
    Der Server bricht deshalb beim Start mit einer klaren Fehlermeldung ab.
    """
    required_routes: dict[str, set[str]] = {
        "/api/tracker/ping": {"GET"},
        "/api/tracker/driver-card": {"GET", "POST"},
        "/api/tracker/driver-card/pin/verify": {"POST"},
        "/api/tracker/work-session": {"GET", "POST"},
        "/api/tracker/state": {"GET"},
    }

    errors: list[str] = []

    for route_path, required_methods in required_routes.items():
        registered_methods = _registered_methods(flask_app, route_path)

        if not registered_methods:
            errors.append(f"{route_path}: Route fehlt vollständig")
            continue

        missing_methods = sorted(required_methods - registered_methods)

        if missing_methods:
            errors.append(
                f"{route_path}: fehlende Methode(n) {', '.join(missing_methods)}; "
                f"registriert: {', '.join(sorted(registered_methods))}"
            )

    if errors:
        details = "\n - ".join(errors)
        raise RuntimeError(
            "Tracker-Blueprint ist nicht vollständig registriert. "
            "Serverstart wurde abgebrochen.\n"
            f" - {details}"
        )


def create_server_app() -> Flask:
    """Erzeugt die Flask-App und validiert die Tracker-Routen."""
    flask_app = create_app()
    validate_tracker_routes(flask_app)
    return flask_app


app = create_server_app()


if __name__ == "__main__":
    host = str(SERVER_HOST)
    port = int(SERVER_PORT)

    print(
        f"Starte Eifel LOG Server mit MongoDB DB '{MONGO_DB_NAME}' "
        f"und Eventlet auf {host}:{port}..."
    )

    listener = eventlet.listen((host, port))
    eventlet.wsgi.server(listener, app)
