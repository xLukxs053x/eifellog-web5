"""Blueprint-Routen für den EifelLog-Bereich: servicecenter."""

from __future__ import annotations

from flask import Blueprint

from app import legacy as _legacy


servicecenter_bp = Blueprint("servicecenter", __name__)


@servicecenter_bp.route('/bildungen', methods=['GET'])
@servicecenter_bp.route('/bildungen.html', methods=['GET'])
@servicecenter_bp.route('/servicecenter/bildungen', methods=['GET'])
def bildungen(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.bildungen()."""
    return _legacy.bildungen(*args, **kwargs)


@servicecenter_bp.route('/servicecenter/bildungen/anmelden', methods=['POST'])
def bildungen_anmelden(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.bildungen_anmelden()."""
    return _legacy.bildungen_anmelden(*args, **kwargs)


@servicecenter_bp.route('/api/servicecenter/bildungen/<request_id>', methods=['GET'])
def api_servicecenter_bildungen_request_detail(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_servicecenter_bildungen_request_detail()."""
    return _legacy.api_servicecenter_bildungen_request_detail(*args, **kwargs)


@servicecenter_bp.route('/api/servicecenter/bildungen/<request_id>/chat', methods=['POST'])
def api_servicecenter_bildungen_user_chat_send(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_servicecenter_bildungen_user_chat_send()."""
    return _legacy.api_servicecenter_bildungen_user_chat_send(*args, **kwargs)


@servicecenter_bp.route('/api/servicecenter/bildungen/<request_id>/withdraw', methods=['POST'])
def api_servicecenter_bildungen_withdraw(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_servicecenter_bildungen_withdraw()."""
    return _legacy.api_servicecenter_bildungen_withdraw(*args, **kwargs)


@servicecenter_bp.route('/api/servicecenter/bildungen/<request_id>/appointment/confirm', methods=['POST'])
def api_servicecenter_bildungen_appointment_confirm(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_servicecenter_bildungen_appointment_confirm()."""
    return _legacy.api_servicecenter_bildungen_appointment_confirm(*args, **kwargs)


@servicecenter_bp.route('/api/servicecenter/bildungen/<request_id>/appointment/decline', methods=['POST'])
def api_servicecenter_bildungen_appointment_decline(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_servicecenter_bildungen_appointment_decline()."""
    return _legacy.api_servicecenter_bildungen_appointment_decline(*args, **kwargs)


@servicecenter_bp.route('/servicecenter', methods=['GET'])
@servicecenter_bp.route('/EifellogServiceCenter', methods=['GET'])
@servicecenter_bp.route('/EifellogServiceCenter.html', methods=['GET'])
def servicecenter(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.servicecenter()."""
    return _legacy.servicecenter(*args, **kwargs)


@servicecenter_bp.route('/servicecenter/fahrerkarte', methods=['GET'])
def servicecenter_fahrerkarte(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.servicecenter_fahrerkarte()."""
    return _legacy.servicecenter_fahrerkarte(*args, **kwargs)


@servicecenter_bp.route('/servicecenter/fahrerkarte/pin/<request_id>', methods=['GET'])
def servicecenter_fahrerkarte_pin_reveal(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.servicecenter_fahrerkarte_pin_reveal()."""
    return _legacy.servicecenter_fahrerkarte_pin_reveal(*args, **kwargs)


@servicecenter_bp.route('/servicecenter/fahrerkarte/beantragen', methods=['POST'])
def servicecenter_fahrerkarte_beantragen(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.servicecenter_fahrerkarte_beantragen()."""
    return _legacy.servicecenter_fahrerkarte_beantragen(*args, **kwargs)


@servicecenter_bp.route('/api/fahrer_registration', methods=['POST'])
def api_fahrer_registration(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_fahrer_registration()."""
    return _legacy.api_fahrer_registration(*args, **kwargs)


@servicecenter_bp.route('/api/new_token_request', methods=['POST'])
def api_new_token_request(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_new_token_request()."""
    return _legacy.api_new_token_request(*args, **kwargs)


@servicecenter_bp.route('/servicecenter/fahrerkarte/download/<request_id>', methods=['GET'])
def servicecenter_fahrerkarte_download(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.servicecenter_fahrerkarte_download()."""
    return _legacy.servicecenter_fahrerkarte_download(*args, **kwargs)
