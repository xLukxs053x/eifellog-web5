"""Zentrale Flask-App-Fabrik und Blueprint-Registrierung für EifelLog."""

from __future__ import annotations

from flask import Flask
from werkzeug.routing import Rule


def register_legacy_url_aliases(app: Flask) -> None:
    """Erhält bestehende url_for("name")-Aufrufe während der Migration.

    Blueprint-Endpunkte heißen intern zum Beispiel ``public.home``. Bestehende
    Templates verwenden teilweise weiterhin ``url_for("home")``. Dafür werden
    ausschließlich Build-Aliasse ergänzt; eingehende Requests laufen weiterhin
    über die Blueprints.
    """
    if app.extensions.get("eifellog_legacy_url_aliases_registered"):
        return

    original_rules = list(app.url_map.iter_rules())
    existing_endpoints = {rule.endpoint for rule in original_rules}

    grouped_rules: dict[str, list] = {}

    for rule in original_rules:
        if "." not in rule.endpoint:
            continue

        legacy_endpoint = rule.endpoint.rsplit(".", 1)[-1]
        grouped_rules.setdefault(legacy_endpoint, []).append(rule)

    for legacy_endpoint, rules in grouped_rules.items():
        if legacy_endpoint in existing_endpoints:
            continue

        for source_rule in rules:
            app.url_map.add(
                Rule(
                    source_rule.rule,
                    defaults=source_rule.defaults,
                    subdomain=source_rule.subdomain,
                    methods=source_rule.methods,
                    build_only=True,
                    endpoint=legacy_endpoint,
                )
            )

    app.extensions["eifellog_legacy_url_aliases_registered"] = True


def register_blueprints(app: Flask) -> None:
    """Registriert sämtliche fachlichen EifelLog-Blueprints genau einmal."""
    if app.extensions.get("eifellog_blueprints_registered"):
        return

    from app.blueprints.api.routes import api_bp
    from app.blueprints.auth.routes import auth_bp
    from app.blueprints.public.routes import public_bp
    from app.blueprints.dashboard.routes import dashboard_bp
    from app.blueprints.tracker.routes import tracker_bp
    from app.blueprints.servicecenter.routes import servicecenter_bp
    from app.blueprints.dispo.routes import dispo_bp
    from app.blueprints.management.routes import management_bp
    from app.blueprints.hr.routes import hr_bp
    from app.blueprints.accounting.routes import accounting_bp
    from app.blueprints.workspace.routes import workspace_bp

    blueprints = (
        api_bp,
        auth_bp,
        public_bp,
        dashboard_bp,
        tracker_bp,
        servicecenter_bp,
        dispo_bp,
        management_bp,
        hr_bp,
        accounting_bp,
        workspace_bp,
    )

    for blueprint in blueprints:
        app.register_blueprint(blueprint)

    register_legacy_url_aliases(app)
    app.extensions["eifellog_blueprints_registered"] = True


def create_app() -> Flask:
    """Lädt die bestehende App und registriert sämtliche Blueprints."""
    from app.legacy import app

    register_blueprints(app)
    return app
