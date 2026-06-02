"""Blueprint-Routen für den EifelLog-Bereich: dispo."""

from __future__ import annotations

from flask import Blueprint

from app import legacy as _legacy


dispo_bp = Blueprint("dispo", __name__)


@dispo_bp.route('/disposition.html', methods=['GET'])
@dispo_bp.route('/disposition', methods=['GET'])
@dispo_bp.route('/dispo.html', methods=['GET'])
@dispo_bp.route('/dispo', methods=['GET'])
def dispo(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.dispo()."""
    return _legacy.dispo(*args, **kwargs)


@dispo_bp.route('/dispo/tour/create', methods=['POST'])
def dispo_create_tour(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.dispo_create_tour()."""
    return _legacy.dispo_create_tour(*args, **kwargs)


@dispo_bp.route('/dispo/note/create', methods=['POST'])
def dispo_create_note(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.dispo_create_note()."""
    return _legacy.dispo_create_note(*args, **kwargs)


@dispo_bp.route('/dispo/tour/assign', methods=['POST'])
@dispo_bp.route('/dispo/tour/<tour_id>/assign', methods=['POST'])
def dispo_assign_tour(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.dispo_assign_tour()."""
    return _legacy.dispo_assign_tour(*args, **kwargs)


@dispo_bp.route('/dispo/form', methods=['GET'])
@dispo_bp.route('/dispo_form.html', methods=['GET'])
def dispo_form(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.dispo_form()."""
    return _legacy.dispo_form(*args, **kwargs)


@dispo_bp.route('/dispo/form/manual', methods=['POST'])
def dispo_form_manual_submit(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.dispo_form_manual_submit()."""
    return _legacy.dispo_form_manual_submit(*args, **kwargs)


@dispo_bp.route('/dispo/form/documents/upload', methods=['POST'])
def dispo_form_documents_upload(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.dispo_form_documents_upload()."""
    return _legacy.dispo_form_documents_upload(*args, **kwargs)


@dispo_bp.route('/dispo/form/file/<entry_id>/<filename>', methods=['GET'])
def dispo_form_file_download(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.dispo_form_file_download()."""
    return _legacy.dispo_form_file_download(*args, **kwargs)


@dispo_bp.route('/dispo/form/<entry_id>/status', methods=['POST'])
def dispo_form_update_status(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.dispo_form_update_status()."""
    return _legacy.dispo_form_update_status(*args, **kwargs)


@dispo_bp.route('/dispo/form/users', methods=['GET'])
def dispo_form_users_api(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.dispo_form_users_api()."""
    return _legacy.dispo_form_users_api(*args, **kwargs)


@dispo_bp.route('/dispo/form/documents/edit', methods=['POST'])
def dispo_form_document_edit(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.dispo_form_document_edit()."""
    return _legacy.dispo_form_document_edit(*args, **kwargs)


@dispo_bp.route('/dispo/form/documents/assign-user', methods=['POST'])
def dispo_form_document_assign_user(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.dispo_form_document_assign_user()."""
    return _legacy.dispo_form_document_assign_user(*args, **kwargs)


@dispo_bp.route('/dispo/form/documents/review', methods=['POST'])
def dispo_form_document_review(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.dispo_form_document_review()."""
    return _legacy.dispo_form_document_review(*args, **kwargs)


@dispo_bp.route('/dispo/form/documents/sign', methods=['POST'])
def dispo_form_document_sign(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.dispo_form_document_sign()."""
    return _legacy.dispo_form_document_sign(*args, **kwargs)


@dispo_bp.route('/dispo/form/documents/forward-management', methods=['POST'])
def dispo_form_document_forward_management(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.dispo_form_document_forward_management()."""
    return _legacy.dispo_form_document_forward_management(*args, **kwargs)
