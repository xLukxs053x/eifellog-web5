"""Zentrale Flask-App-Fabrik für EifelLog.

Während der kontrollierten Migration bleibt die bestehende Anwendung zunächst
unter app.legacy aktiv. Neue Bereiche werden Schritt für Schritt als
Blueprints ausgelagert und hier zentral registriert.
"""

from __future__ import annotations

from importlib import import_module
from typing import Final

from flask import Flask


BLUEPRINTS: Final[tuple[tuple[str, str], ...]] = (
    ("app.blueprints.api.routes", "api_bp"),
    ("app.blueprints.auth.routes", "auth_bp"),
    ("app.blueprints.public.routes", "public_bp"),
    ("app.blueprints.dashboard.routes", "dashboard_bp"),
    ("app.blueprints.tracker.routes", "tracker_bp"),
    ("app.blueprints.servicecenter.routes", "servicecenter_bp"),
    ("app.blueprints.dispo.routes", "dispo_bp"),
    ("app.blueprints.management.routes", "management_bp"),
    ("app.blueprints.hr.routes", "hr_bp"),
    ("app.blueprints.accounting.routes", "accounting_bp"),
    ("app.blueprints.workspace.routes", "workspace_bp"),
)


def register_blueprints(app: Flask) -> None:
    """Registriert vorhandene EifelLog-Blueprints genau einmal."""
    if app.extensions.get("eifellog_blueprints_registered"):
        return

    for module_path, blueprint_name in BLUEPRINTS:
        try:
            module = import_module(module_path)
        except ModuleNotFoundError as error:
            # Noch nicht angelegte Blueprints werden während der Migration
            # übersprungen. Interne Importfehler vorhandener Module bleiben
            # dagegen sichtbar.
            if error.name == module_path or module_path.startswith(f"{error.name}."):
                continue
            raise

        blueprint = getattr(module, blueprint_name, None)
        if blueprint is None:
            raise RuntimeError(
                f"Blueprint '{blueprint_name}' fehlt in '{module_path}'."
            )

        app.register_blueprint(blueprint)

    app.extensions["eifellog_blueprints_registered"] = True


def create_app() -> Flask:
    from app.legacy import app

    register_blueprints(app)
    return app
