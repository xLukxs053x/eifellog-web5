"""Blueprint-Routen für den EifelLog-Bereich: hr."""

from __future__ import annotations

from flask import Blueprint

from app import legacy as _legacy


hr_bp = Blueprint("hr", __name__)


@hr_bp.route('/api/hr/driver-card/pdf/<user_id>/<date_str>')
def generate_driver_card_pdf(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.generate_driver_card_pdf()."""
    return _legacy.generate_driver_card_pdf(*args, **kwargs)


@hr_bp.route('/api/hr/driver_card_log/<discord_id>/<date_str>', methods=['GET'])
def hr_get_driver_card_log(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.hr_get_driver_card_log()."""
    return _legacy.hr_get_driver_card_log(*args, **kwargs)


@hr_bp.route('/api/hr/download_shift_pdf/<shift_id>', methods=['GET'])
def hr_download_shift_pdf(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.hr_download_shift_pdf()."""
    return _legacy.hr_download_shift_pdf(*args, **kwargs)


@hr_bp.route('/api/hr-controlling/system/status', methods=['GET', 'OPTIONS'])
def api_hr_controlling_system_status(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_hr_controlling_system_status()."""
    return _legacy.api_hr_controlling_system_status(*args, **kwargs)


@hr_bp.route('/api/hr-controlling/personalakten', methods=['GET', 'POST', 'OPTIONS'])
def api_hr_controlling_personalakten(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_hr_controlling_personalakten()."""
    return _legacy.api_hr_controlling_personalakten(*args, **kwargs)


@hr_bp.route('/api/hr-controlling/personalakten/<employee_id>', methods=['GET', 'PATCH', 'DELETE', 'OPTIONS'])
def api_hr_controlling_personalakte_detail(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_hr_controlling_personalakte_detail()."""
    return _legacy.api_hr_controlling_personalakte_detail(*args, **kwargs)


@hr_bp.route('/api/hr-controlling/checkliste', methods=['GET', 'POST', 'OPTIONS'])
def api_hr_controlling_checkliste(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_hr_controlling_checkliste()."""
    return _legacy.api_hr_controlling_checkliste(*args, **kwargs)


@hr_bp.route('/api/hr-controlling/checkliste/<item_id>', methods=['GET', 'PATCH', 'DELETE', 'OPTIONS'])
def api_hr_controlling_checkliste_detail(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_hr_controlling_checkliste_detail()."""
    return _legacy.api_hr_controlling_checkliste_detail(*args, **kwargs)


@hr_bp.route('/api/hr-controlling/prozessplan', methods=['GET', 'POST', 'OPTIONS'])
def api_hr_controlling_prozessplan(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_hr_controlling_prozessplan()."""
    return _legacy.api_hr_controlling_prozessplan(*args, **kwargs)


@hr_bp.route('/controlling', methods=['GET'])
def hr_controlling(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.hr_controlling()."""
    return _legacy.hr_controlling(*args, **kwargs)


@hr_bp.route('/api/hr-controlling/tabellen-builder', methods=['GET', 'POST', 'OPTIONS'])
def api_hr_controlling_tabellen_builder(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_hr_controlling_tabellen_builder()."""
    return _legacy.api_hr_controlling_tabellen_builder(*args, **kwargs)


@hr_bp.route('/api/hr-controlling/tabellen-builder/live', methods=['GET'])
def api_hr_controlling_tabellen_builder_live(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_hr_controlling_tabellen_builder_live()."""
    return _legacy.api_hr_controlling_tabellen_builder_live(*args, **kwargs)
