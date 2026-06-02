"""Blueprint-Routen für den EifelLog-Bereich: management."""

from __future__ import annotations

from flask import Blueprint

from app import legacy as _legacy


management_bp = Blueprint("management", __name__)


@management_bp.route('/admin', methods=['GET'])
@management_bp.route('/admin.html', methods=['GET'])
def admin(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.admin()."""
    return _legacy.admin(*args, **kwargs)


@management_bp.route('/management', methods=['GET'])
@management_bp.route('/geschaeftsfuehrung.html', methods=['GET'])
@management_bp.route('/geschaeftsfuehrung', methods=['GET'])
@management_bp.route('/geschaeftsleitung.html', methods=['GET'])
@management_bp.route('/geschaeftsleitung/dokumente', methods=['GET'])
@management_bp.route('/geschaeftsleitung', methods=['GET'])
def geschaeftsleitung(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.geschaeftsleitung()."""
    return _legacy.geschaeftsleitung(*args, **kwargs)


@management_bp.route('/geschaeftsleitung/dispo-documents/approve', methods=['POST'])
def geschaeftsleitung_approve_dispo_document(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.geschaeftsleitung_approve_dispo_document()."""
    return _legacy.geschaeftsleitung_approve_dispo_document(*args, **kwargs)


@management_bp.route('/geschaeftsleitung/dispo-documents/return', methods=['POST'])
def geschaeftsleitung_return_dispo_document(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.geschaeftsleitung_return_dispo_document()."""
    return _legacy.geschaeftsleitung_return_dispo_document(*args, **kwargs)


@management_bp.route('/personalabteilung', methods=['GET'])
def personalabteilung(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.personalabteilung()."""
    return _legacy.personalabteilung(*args, **kwargs)


@management_bp.route('/api/personalabteilung/fahrerkarte/data/query', methods=['POST', 'OPTIONS'])
def api_personalabteilung_fahrerkarte_data_query(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_personalabteilung_fahrerkarte_data_query()."""
    return _legacy.api_personalabteilung_fahrerkarte_data_query(*args, **kwargs)


@management_bp.route('/api/personalabteilung/fahrerkarte/daily-times', methods=['GET', 'POST', 'OPTIONS'])
@management_bp.route('/api/personalabteilung/fahrerkarte/times', methods=['GET', 'POST', 'OPTIONS'])
@management_bp.route('/api/personalabteilung/fahrerkarte/day', methods=['GET', 'POST', 'OPTIONS'])
def api_personalabteilung_fahrerkarte_daily_times(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_personalabteilung_fahrerkarte_daily_times()."""
    return _legacy.api_personalabteilung_fahrerkarte_daily_times(*args, **kwargs)


@management_bp.route('/api/personalabteilung/fahrerkarte/pdf/create', methods=['POST', 'OPTIONS'])
def api_personalabteilung_fahrerkarte_pdf_create(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_personalabteilung_fahrerkarte_pdf_create()."""
    return _legacy.api_personalabteilung_fahrerkarte_pdf_create(*args, **kwargs)


@management_bp.route('/api/personalabteilung/fahrerkarte/pdf/send', methods=['POST', 'OPTIONS'])
def api_personalabteilung_fahrerkarte_pdf_send(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_personalabteilung_fahrerkarte_pdf_send()."""
    return _legacy.api_personalabteilung_fahrerkarte_pdf_send(*args, **kwargs)


@management_bp.route('/api/personalabteilung/fahrerkarte/lenk-ruhe/pdf', methods=['POST', 'OPTIONS'])
def api_personalabteilung_fahrerkarte_lenk_ruhe_pdf(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_personalabteilung_fahrerkarte_lenk_ruhe_pdf()."""
    return _legacy.api_personalabteilung_fahrerkarte_lenk_ruhe_pdf(*args, **kwargs)


@management_bp.route('/personalabteilung/servicecenter/fahrerkarte', methods=['GET'])
@management_bp.route('/servicecenter/admin/fahrerkarte', methods=['GET'])
def personalabteilung_servicecenter_fahrerkarte_web(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.personalabteilung_servicecenter_fahrerkarte_web()."""
    return _legacy.personalabteilung_servicecenter_fahrerkarte_web(*args, **kwargs)


@management_bp.route('/personalabteilung/servicecenter/fahrerkarte/weiterbildungen', methods=['GET'])
@management_bp.route('/servicecenter/admin/fahrerkarte/weiterbildungen', methods=['GET'])
def personalabteilung_servicecenter_fahrerkarte_weiterbildungen_web(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.personalabteilung_servicecenter_fahrerkarte_weiterbildungen_web()."""
    return _legacy.personalabteilung_servicecenter_fahrerkarte_weiterbildungen_web(*args, **kwargs)


@management_bp.route('/api/personalabteilung/servicecenter/fahrerkarte/weiterbildungen', methods=['GET'])
def api_personalabteilung_servicecenter_fahrerkarte_weiterbildungen_list(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_personalabteilung_servicecenter_fahrerkarte_weiterbildungen_list()."""
    return _legacy.api_personalabteilung_servicecenter_fahrerkarte_weiterbildungen_list(*args, **kwargs)


@management_bp.route('/api/personalabteilung/servicecenter/fahrerkarte/weiterbildungen/claim', methods=['POST'])
def api_personalabteilung_servicecenter_fahrerkarte_weiterbildungen_claim(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_personalabteilung_servicecenter_fahrerkarte_weiterbildungen_claim()."""
    return _legacy.api_personalabteilung_servicecenter_fahrerkarte_weiterbildungen_claim(*args, **kwargs)


@management_bp.route('/api/personalabteilung/servicecenter/fahrerkarte/weiterbildungen/update', methods=['POST'])
def api_personalabteilung_servicecenter_fahrerkarte_weiterbildungen_update(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_personalabteilung_servicecenter_fahrerkarte_weiterbildungen_update()."""
    return _legacy.api_personalabteilung_servicecenter_fahrerkarte_weiterbildungen_update(*args, **kwargs)


@management_bp.route('/api/personalabteilung/servicecenter/fahrerkarte/weiterbildungen/appointment-proposal', methods=['POST'])
def api_personalabteilung_servicecenter_fahrerkarte_weiterbildungen_appointment_proposal(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_personalabteilung_servicecenter_fahrerkarte_weiterbildungen_appointment_proposal()."""
    return _legacy.api_personalabteilung_servicecenter_fahrerkarte_weiterbildungen_appointment_proposal(*args, **kwargs)


@management_bp.route('/api/personalabteilung/servicecenter/fahrerkarte/weiterbildungen/<request_id>/chat', methods=['GET', 'POST'])
def api_personalabteilung_servicecenter_fahrerkarte_weiterbildungen_chat(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_personalabteilung_servicecenter_fahrerkarte_weiterbildungen_chat()."""
    return _legacy.api_personalabteilung_servicecenter_fahrerkarte_weiterbildungen_chat(*args, **kwargs)


@management_bp.route('/api/personalabteilung/servicecenter/fahrerkarte/weiterbildungen/archive', methods=['POST'])
def api_personalabteilung_servicecenter_fahrerkarte_weiterbildungen_archive(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_personalabteilung_servicecenter_fahrerkarte_weiterbildungen_archive()."""
    return _legacy.api_personalabteilung_servicecenter_fahrerkarte_weiterbildungen_archive(*args, **kwargs)


@management_bp.route('/personalabteilung/dokumente', methods=['GET', 'POST'])
def personalabteilung_dokumente(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.personalabteilung_dokumente()."""
    return _legacy.personalabteilung_dokumente(*args, **kwargs)


@management_bp.route('/api/personalabteilung/driver/document/send', methods=['POST'])
def api_personalabteilung_send_document(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_personalabteilung_send_document()."""
    return _legacy.api_personalabteilung_send_document(*args, **kwargs)


@management_bp.route('/api/personalabteilung/driver/document/issue-fahrerkarte', methods=['POST'])
@management_bp.route('/api/personalabteilung/driver/fahrerkarte/ausstellen', methods=['POST'])
def api_personalabteilung_issue_driver_fahrerkarte(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_personalabteilung_issue_driver_fahrerkarte()."""
    return _legacy.api_personalabteilung_issue_driver_fahrerkarte(*args, **kwargs)


@management_bp.route('/api/personalabteilung/servicecenter/fahrerkarte', methods=['GET'])
def api_personalabteilung_servicecenter_fahrerkarte_list(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_personalabteilung_servicecenter_fahrerkarte_list()."""
    return _legacy.api_personalabteilung_servicecenter_fahrerkarte_list(*args, **kwargs)


@management_bp.route('/api/personalabteilung/servicecenter/fahrerkarte/claim', methods=['POST'])
def api_personalabteilung_servicecenter_fahrerkarte_claim(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_personalabteilung_servicecenter_fahrerkarte_claim()."""
    return _legacy.api_personalabteilung_servicecenter_fahrerkarte_claim(*args, **kwargs)


@management_bp.route('/api/personalabteilung/servicecenter/fahrerkarte/approve', methods=['POST'])
def api_personalabteilung_servicecenter_fahrerkarte_approve(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_personalabteilung_servicecenter_fahrerkarte_approve()."""
    return _legacy.api_personalabteilung_servicecenter_fahrerkarte_approve(*args, **kwargs)


@management_bp.route('/api/personalabteilung/servicecenter/fahrerkarte/issue', methods=['POST'])
def api_personalabteilung_servicecenter_fahrerkarte_issue(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_personalabteilung_servicecenter_fahrerkarte_issue()."""
    return _legacy.api_personalabteilung_servicecenter_fahrerkarte_issue(*args, **kwargs)


@management_bp.route('/api/personalabteilung/servicecenter/fahrerkarte/pin/reissue', methods=['POST'])
def api_personalabteilung_servicecenter_fahrerkarte_pin_reissue(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_personalabteilung_servicecenter_fahrerkarte_pin_reissue()."""
    return _legacy.api_personalabteilung_servicecenter_fahrerkarte_pin_reissue(*args, **kwargs)


@management_bp.route('/api/personalabteilung/servicecenter/fahrerkarte/reject', methods=['POST'])
def api_personalabteilung_servicecenter_fahrerkarte_reject(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_personalabteilung_servicecenter_fahrerkarte_reject()."""
    return _legacy.api_personalabteilung_servicecenter_fahrerkarte_reject(*args, **kwargs)


@management_bp.route('/api/personalabteilung/servicecenter/fahrerkarte/postpone', methods=['POST'])
def api_personalabteilung_servicecenter_fahrerkarte_postpone(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_personalabteilung_servicecenter_fahrerkarte_postpone()."""
    return _legacy.api_personalabteilung_servicecenter_fahrerkarte_postpone(*args, **kwargs)


@management_bp.route('/api/personalabteilung/servicecenter/fahrerkarte/discord-sync', methods=['POST'])
def api_personalabteilung_servicecenter_fahrerkarte_discord_sync(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_personalabteilung_servicecenter_fahrerkarte_discord_sync()."""
    return _legacy.api_personalabteilung_servicecenter_fahrerkarte_discord_sync(*args, **kwargs)


@management_bp.route('/api/personalabteilung/fahrer_registration/claim', methods=['POST'])
def api_personalabteilung_claim_registration(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_personalabteilung_claim_registration()."""
    return _legacy.api_personalabteilung_claim_registration(*args, **kwargs)


@management_bp.route('/api/personalabteilung/fahrer_registration/approve', methods=['POST'])
def api_personalabteilung_approve_registration(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_personalabteilung_approve_registration()."""
    return _legacy.api_personalabteilung_approve_registration(*args, **kwargs)


@management_bp.route('/api/personalabteilung/fahrer_registration/reject', methods=['POST'])
def api_personalabteilung_reject_registration(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_personalabteilung_reject_registration()."""
    return _legacy.api_personalabteilung_reject_registration(*args, **kwargs)


@management_bp.route('/api/personalabteilung/token_request/approve', methods=['POST'])
def api_personalabteilung_approve_token_request(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_personalabteilung_approve_token_request()."""
    return _legacy.api_personalabteilung_approve_token_request(*args, **kwargs)


@management_bp.route('/api/personalabteilung/token_request/reject', methods=['POST'])
def api_personalabteilung_reject_token_request(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_personalabteilung_reject_token_request()."""
    return _legacy.api_personalabteilung_reject_token_request(*args, **kwargs)


@management_bp.route('/personalabteilung/tracker-code/create', methods=['POST'])
def personalabteilung_create_tracker_code(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.personalabteilung_create_tracker_code()."""
    return _legacy.personalabteilung_create_tracker_code(*args, **kwargs)
