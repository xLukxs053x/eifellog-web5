"""Blueprint-Routen für den EifelLog-Bereich: accounting."""

from __future__ import annotations

from flask import Blueprint

from app import legacy as _legacy


accounting_bp = Blueprint("accounting", __name__)


@accounting_bp.route('/buchhaltung', methods=['GET'])
def buchhaltung(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.buchhaltung()."""
    return _legacy.buchhaltung(*args, **kwargs)


@accounting_bp.route('/api/buchhaltung/entries', methods=['GET', 'POST', 'OPTIONS'])
def api_buchhaltung_entries(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_buchhaltung_entries()."""
    return _legacy.api_buchhaltung_entries(*args, **kwargs)


@accounting_bp.route('/api/buchhaltung/entries/<entry_id>', methods=['GET', 'PATCH', 'DELETE', 'OPTIONS'])
def api_buchhaltung_entry_detail(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_buchhaltung_entry_detail()."""
    return _legacy.api_buchhaltung_entry_detail(*args, **kwargs)


@accounting_bp.route('/api/buchhaltung/entries/<entry_id>/pdf', methods=['GET', 'OPTIONS'])
def api_buchhaltung_entry_pdf(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_buchhaltung_entry_pdf()."""
    return _legacy.api_buchhaltung_entry_pdf(*args, **kwargs)


@accounting_bp.route('/api/buchhaltung/request', methods=['GET', 'POST', 'OPTIONS'])
def api_buchhaltung_request(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_buchhaltung_request()."""
    return _legacy.api_buchhaltung_request(*args, **kwargs)
