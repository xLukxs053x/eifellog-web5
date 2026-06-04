"""Produktions-Entrypoint für den Eifel LOG Server.

Wichtig:
- Eventlet wird gepatcht, bevor Flask, PyMongo oder Requests importiert werden.
- Die Flask-App wird ausschließlich über app.create_app() erzeugt.
- Tourstart-Embeds und Abschluss-PDF-Belege werden ausschließlich von der
  Python-Seite verarbeitet.
- Der Discord-Zielchannel für Tourstart und Tourabschluss ist zentral auf
  1473756766478270517 festgelegt.
- Beim Start wird geprüft, ob die zentralen Tracker-Routen korrekt registriert
  wurden. Dadurch fällt eine fehlerhafte Blueprint-Registrierung sofort auf,
  statt erst später als HTTP 404/405 im Desktop-Tracker sichtbar zu werden.
- Zusätzlich werden die öffentlichen CDN-Routen für Tracker-Updates geprüft.
  Die Update-Dateien liegen standardmäßig unter <BASE_DIR>/tracker_updates.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable

import eventlet

# Muss zwingend vor dem Import der Flask-App und ihrer Abhängigkeiten laufen.
eventlet.monkey_patch()

# Dieser Channel wird bewusst zentral und verbindlich gesetzt. Dadurch landen
# sowohl das Tourstart-Embed als auch das Abschluss-Embed mit PDF-Beleg immer im
# selben Discord-Channel. Die Tracker-Routen bzw. Discord-Services können einen
# der Alias-Namen verwenden, ohne dass unterschiedliche Konfigurationen entstehen.
TOUR_DISCORD_CHANNEL_ID = "1473756766478270517"
os.environ["TOUR_DISCORD_CHANNEL_ID"] = TOUR_DISCORD_CHANNEL_ID
os.environ["TOUR_RECEIPT_DISCORD_CHANNEL_ID"] = TOUR_DISCORD_CHANNEL_ID
os.environ["TRACKER_DISCORD_CHANNEL_ID"] = TOUR_DISCORD_CHANNEL_ID

import eventlet.wsgi
from flask import Flask

from app import create_app
from app.config import BASE_DIR, MONGO_DB_NAME, SERVER_HOST, SERVER_PORT


# ==========================================
# TRACKER-UPDATE-CDN
# ==========================================
TRACKER_UPDATE_CDN_PUBLIC_PATH = "/tracker/updates"
TRACKER_UPDATE_CDN_CHANNELS = ("stable", "beta", "developer")
TRACKER_UPDATE_CDN_ROOT = Path(
    os.getenv("TRACKER_UPDATE_CDN_ROOT")
    or os.path.join(BASE_DIR, "tracker_updates")
).expanduser().resolve()
TRACKER_UPDATE_CDN_FILES_ROOT = TRACKER_UPDATE_CDN_ROOT / "files"
TRACKER_UPDATE_CDN_STRICT_STARTUP = str(
    os.getenv("TRACKER_UPDATE_CDN_STRICT_STARTUP", "false")
).strip().lower() in {"1", "true", "yes", "ja", "on", "enabled", "aktiv"}


# ==========================================
# ALLGEMEINE ROUTEN-PRÜFUNGEN
# ==========================================
def _normalize_methods(methods: Iterable[str]) -> set[str]:
    """Normalisiert Flask-Methodenmengen für robuste Startprüfungen."""
    return {
        str(method).strip().upper()
        for method in methods
        if str(method).strip()
    }


def _registered_methods(flask_app: Flask, route_path: str) -> set[str]:
    """Liefert alle für einen konkreten Flask-Regelpfad registrierten Methoden.

    Für dynamische Regeln muss exakt die Flask-Syntax verwendet werden, z. B.::

        /tracker/updates/<channel>/manifest.json
        /tracker/updates/files/<path:filename>
    """
    methods: set[str] = set()

    for rule in flask_app.url_map.iter_rules():
        if rule.rule == route_path:
            methods.update(_normalize_methods(rule.methods or set()))

    return methods


def _validate_required_routes(
    flask_app: Flask,
    required_routes: dict[str, set[str]],
    *,
    subsystem_name: str,
) -> None:
    """Prüft zwingend benötigte Flask-Routen und bricht bei Fehlern klar ab."""
    errors: list[str] = []

    for route_path, required_methods in required_routes.items():
        normalized_required_methods = _normalize_methods(required_methods)
        registered_methods = _registered_methods(flask_app, route_path)

        if not registered_methods:
            errors.append(f"{route_path}: Route fehlt vollständig")
            continue

        missing_methods = sorted(normalized_required_methods - registered_methods)

        if missing_methods:
            errors.append(
                f"{route_path}: fehlende Methode(n) {', '.join(missing_methods)}; "
                f"registriert: {', '.join(sorted(registered_methods))}"
            )

    if errors:
        details = "\n - ".join(errors)
        raise RuntimeError(
            f"{subsystem_name} ist nicht vollständig registriert. "
            "Serverstart wurde abgebrochen.\n"
            f" - {details}"
        )


# ==========================================
# TOUR-/TRACKER-PRÜFUNGEN
# ==========================================
def _validate_fixed_tour_channel(flask_app: Flask) -> None:
    """Stellt den zentralen Discord-Channel auch in Flask bereit.

    Die eigentliche Discord-Nachricht wird nicht in diesem Entrypoint erzeugt.
    Zuständig sind die Python-Tracker-Routen bzw. deren Discord-Service.
    """
    flask_app.config["TOUR_DISCORD_CHANNEL_ID"] = TOUR_DISCORD_CHANNEL_ID
    flask_app.config["TOUR_RECEIPT_DISCORD_CHANNEL_ID"] = TOUR_DISCORD_CHANNEL_ID
    flask_app.config["TRACKER_DISCORD_CHANNEL_ID"] = TOUR_DISCORD_CHANNEL_ID

    if not TOUR_DISCORD_CHANNEL_ID.isdigit():
        raise RuntimeError(
            "TOUR_DISCORD_CHANNEL_ID muss eine numerische Discord-ID sein."
        )


def validate_tracker_routes(flask_app: Flask) -> None:
    """Prüft die für den Desktop-Tracker zwingend benötigten Blueprint-Routen.

    Ein fehlender oder unvollständig registrierter Tracker-Blueprint würde bei
    schreibenden Requests typischerweise zu ``404 Not Found`` oder
    ``405 Method Not Allowed`` führen. Der Server bricht deshalb beim Start mit
    einer klaren Fehlermeldung ab.

    Die beiden Job-Routen sind für die Python-seitige Verarbeitung verbindlich:
    - ``POST /api/tracker/jobs/start`` erzeugt das Tourstart-Embed.
    - ``POST /api/tracker/jobs/complete`` erzeugt Abschluss-Embed, PDF-Beleg,
      Discord-Versand und die nachgelagerten Datenbank-/Statistikupdates.
    """
    required_routes: dict[str, set[str]] = {
        "/api/tracker/ping": {"GET"},
        "/api/tracker/driver-card": {"GET", "POST"},
        "/api/tracker/driver-card/pin/verify": {"POST"},
        "/api/tracker/work-session": {"GET", "POST"},
        "/api/tracker/state": {"GET"},
        "/api/tracker/jobs/start": {"POST"},
        "/api/tracker/jobs/complete": {"POST"},
    }

    _validate_required_routes(
        flask_app,
        required_routes,
        subsystem_name="Tracker-Blueprint",
    )


# ==========================================
# CDN-PRÜFUNGEN
# ==========================================
def _set_update_cdn_config(flask_app: Flask) -> None:
    """Spiegelt die Update-CDN-Konfiguration für Diagnosezwecke in Flask."""
    flask_app.config["TRACKER_UPDATE_CDN_PUBLIC_PATH"] = TRACKER_UPDATE_CDN_PUBLIC_PATH
    flask_app.config["TRACKER_UPDATE_CDN_ROOT"] = str(TRACKER_UPDATE_CDN_ROOT)
    flask_app.config["TRACKER_UPDATE_CDN_FILES_ROOT"] = str(TRACKER_UPDATE_CDN_FILES_ROOT)
    flask_app.config["TRACKER_UPDATE_CDN_CHANNELS"] = TRACKER_UPDATE_CDN_CHANNELS
    flask_app.config["TRACKER_UPDATE_CDN_STRICT_STARTUP"] = TRACKER_UPDATE_CDN_STRICT_STARTUP


def validate_update_cdn_routes(flask_app: Flask) -> None:
    """Prüft die öffentlichen CDN-Routen für den Windows-Updater.

    Die Manifeste und Pakete werden von ``legacy.py`` ausgeliefert. Der
    Desktop-Tracker erwartet exakt diese Pfade unter ``www.eifellog.de``.
    """
    required_routes: dict[str, set[str]] = {
        f"{TRACKER_UPDATE_CDN_PUBLIC_PATH}/health.json": {"GET", "HEAD", "OPTIONS"},
        f"{TRACKER_UPDATE_CDN_PUBLIC_PATH}/<channel>/manifest.json": {"GET", "HEAD", "OPTIONS"},
        f"{TRACKER_UPDATE_CDN_PUBLIC_PATH}/files/<path:filename>": {"GET", "HEAD", "OPTIONS"},
    }

    _validate_required_routes(
        flask_app,
        required_routes,
        subsystem_name="Tracker-Update-CDN",
    )


def _manifest_storage_errors() -> list[str]:
    """Prüft die erwartete CDN-Dateistruktur ohne interne Pfade öffentlich zu machen."""
    errors: list[str] = []

    if not TRACKER_UPDATE_CDN_ROOT.is_dir():
        return [
            "Update-CDN-Wurzelordner fehlt: "
            f"{TRACKER_UPDATE_CDN_ROOT}"
        ]

    if not TRACKER_UPDATE_CDN_FILES_ROOT.is_dir():
        errors.append(
            "Update-CDN-Dateiordner fehlt: "
            f"{TRACKER_UPDATE_CDN_FILES_ROOT}"
        )

    for channel in TRACKER_UPDATE_CDN_CHANNELS:
        manifest_path = TRACKER_UPDATE_CDN_ROOT / channel / "manifest.json"

        if not manifest_path.is_file():
            errors.append(
                f"{channel}: manifest.json fehlt unter {manifest_path}"
            )
            continue

        try:
            with manifest_path.open("r", encoding="utf-8-sig") as file:
                manifest = json.load(file)
        except json.JSONDecodeError as error:
            errors.append(
                f"{channel}: manifest.json enthält ungültiges JSON "
                f"(Zeile {error.lineno}, Spalte {error.colno})"
            )
            continue
        except OSError as error:
            errors.append(f"{channel}: manifest.json ist nicht lesbar: {error}")
            continue

        if not isinstance(manifest, dict):
            errors.append(f"{channel}: manifest.json muss ein JSON-Objekt enthalten")
            continue

        releases = manifest.get("releases")
        if not isinstance(releases, list) or not releases:
            errors.append(f"{channel}: manifest.json enthält keine Releases")

    return errors


def validate_update_cdn_storage() -> None:
    """Prüft Upload-Ordner und Manifeste mit optional strengem Startverhalten.

    Standardmäßig startet der Webserver trotz noch nicht hochgeladener Dateien,
    damit ein frisches Deployment administrierbar bleibt. In produktiven
    Releases kann mit ``TRACKER_UPDATE_CDN_STRICT_STARTUP=true`` ein harter
    Startabbruch aktiviert werden.
    """
    errors = _manifest_storage_errors()

    if not errors:
        print(
            "Tracker-Update-CDN: Ordnerstruktur und Channel-Manifeste sind vorhanden."
        )
        return

    details = "\n - ".join(errors)
    message = (
        "Tracker-Update-CDN ist noch nicht vollständig veröffentlicht.\n"
        f" - {details}"
    )

    if TRACKER_UPDATE_CDN_STRICT_STARTUP:
        raise RuntimeError(
            message
            + "\nTRACKER_UPDATE_CDN_STRICT_STARTUP=true verhindert den Serverstart."
        )

    print("WARNUNG: " + message)
    print(
        "Hinweis: Für einen harten Produktionscheck "
        "TRACKER_UPDATE_CDN_STRICT_STARTUP=true setzen."
    )


def report_optional_downloads_page(flask_app: Flask) -> None:
    """Meldet, ob eine optionale HTML-Downloadseite bereits registriert ist.

    Die Desktop-Updatefunktion benötigt diese Seite nicht. Sie ist lediglich die
    geplante Discord-ähnliche Weboberfläche für manuelle Downloads.
    """
    downloads_path = "/tracker/downloads"
    methods = _registered_methods(flask_app, downloads_path)

    if "GET" in methods:
        print(f"Tracker-Downloads-Seite registriert: {downloads_path}")
    else:
        print(
            "HINWEIS: Optionale Tracker-Downloads-Seite ist noch nicht registriert: "
            f"{downloads_path}"
        )


# ==========================================
# APP-ERZEUGUNG
# ==========================================
def create_server_app() -> Flask:
    """Erzeugt die Flask-App und validiert Tracker, Channel sowie CDN-Routen."""
    flask_app = create_app()

    _validate_fixed_tour_channel(flask_app)
    _set_update_cdn_config(flask_app)

    validate_tracker_routes(flask_app)
    validate_update_cdn_routes(flask_app)
    validate_update_cdn_storage()
    report_optional_downloads_page(flask_app)

    return flask_app


app = create_server_app()


if __name__ == "__main__":
    host = str(SERVER_HOST)
    port = int(SERVER_PORT)

    print(
        f"Starte Eifel LOG Server mit MongoDB DB '{MONGO_DB_NAME}', "
        f"Eventlet auf {host}:{port}, Tour-Discord-Channel "
        f"{TOUR_DISCORD_CHANNEL_ID} und Tracker-Update-CDN unter "
        f"{TRACKER_UPDATE_CDN_PUBLIC_PATH} ..."
    )

    listener = eventlet.listen((host, port))
    eventlet.wsgi.server(listener, app)
