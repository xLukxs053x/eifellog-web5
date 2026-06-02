"""Blueprint-Routen für den EifelLog-Bereich: workspace."""

from __future__ import annotations

from flask import Blueprint

from app import legacy as _legacy


workspace_bp = Blueprint("workspace", __name__)


@workspace_bp.route('/api/workspace/system/status', methods=['GET', 'OPTIONS'])
def api_workspace_system_status(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_workspace_system_status()."""
    return _legacy.api_workspace_system_status(*args, **kwargs)


@workspace_bp.route('/api/workspace/auth/register', methods=['POST', 'OPTIONS'])
def api_workspace_auth_register(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_workspace_auth_register()."""
    return _legacy.api_workspace_auth_register(*args, **kwargs)


@workspace_bp.route('/api/workspace/auth/login', methods=['POST', 'OPTIONS'])
def api_workspace_auth_login(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_workspace_auth_login()."""
    return _legacy.api_workspace_auth_login(*args, **kwargs)


@workspace_bp.route('/api/workspace/auth/logout', methods=['POST', 'OPTIONS'])
def api_workspace_auth_logout(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_workspace_auth_logout()."""
    return _legacy.api_workspace_auth_logout(*args, **kwargs)


@workspace_bp.route('/api/workspace/me', methods=['GET', 'OPTIONS'])
@workspace_bp.route('/api/workspace/bootstrap', methods=['GET', 'OPTIONS'])
def api_workspace_bootstrap(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_workspace_bootstrap()."""
    return _legacy.api_workspace_bootstrap(*args, **kwargs)


@workspace_bp.route('/api/workspace/account', methods=['PATCH', 'OPTIONS'])
def api_workspace_account_update(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_workspace_account_update()."""
    return _legacy.api_workspace_account_update(*args, **kwargs)


@workspace_bp.route('/api/workspace/workspaces', methods=['GET', 'POST', 'OPTIONS'])
def api_workspace_workspaces(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_workspace_workspaces()."""
    return _legacy.api_workspace_workspaces(*args, **kwargs)


@workspace_bp.route('/api/workspace/workspaces/<workspace_id>', methods=['GET', 'PATCH', 'DELETE', 'OPTIONS'])
def api_workspace_workspace_detail(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_workspace_workspace_detail()."""
    return _legacy.api_workspace_workspace_detail(*args, **kwargs)


@workspace_bp.route('/api/workspace/workspaces/<workspace_id>/members', methods=['GET', 'POST', 'OPTIONS'])
def api_workspace_members(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_workspace_members()."""
    return _legacy.api_workspace_members(*args, **kwargs)


@workspace_bp.route('/api/workspace/workspaces/<workspace_id>/folders', methods=['GET', 'POST', 'OPTIONS'])
def api_workspace_folders(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_workspace_folders()."""
    return _legacy.api_workspace_folders(*args, **kwargs)


@workspace_bp.route('/api/workspace/folders/<folder_id>', methods=['PATCH', 'DELETE', 'OPTIONS'])
def api_workspace_folder_detail(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_workspace_folder_detail()."""
    return _legacy.api_workspace_folder_detail(*args, **kwargs)


@workspace_bp.route('/api/workspace/workspaces/<workspace_id>/project-maps', methods=['GET', 'POST', 'OPTIONS'])
def api_workspace_project_maps(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_workspace_project_maps()."""
    return _legacy.api_workspace_project_maps(*args, **kwargs)


@workspace_bp.route('/api/workspace/project-maps/<project_id>', methods=['PATCH', 'DELETE', 'OPTIONS'])
def api_workspace_project_map_detail(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_workspace_project_map_detail()."""
    return _legacy.api_workspace_project_map_detail(*args, **kwargs)


@workspace_bp.route('/api/workspace/workspaces/<workspace_id>/sheets', methods=['GET', 'POST', 'OPTIONS'])
def api_workspace_sheets(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_workspace_sheets()."""
    return _legacy.api_workspace_sheets(*args, **kwargs)


@workspace_bp.route('/api/workspace/sheets/<sheet_id>', methods=['GET', 'PATCH', 'DELETE', 'OPTIONS'])
def api_workspace_sheet_detail(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_workspace_sheet_detail()."""
    return _legacy.api_workspace_sheet_detail(*args, **kwargs)


@workspace_bp.route('/api/workspace/workspaces/<workspace_id>/share', methods=['POST', 'OPTIONS'])
def api_workspace_share(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_workspace_share()."""
    return _legacy.api_workspace_share(*args, **kwargs)


@workspace_bp.route('/api/workspace/share/accept', methods=['POST', 'OPTIONS'])
def api_workspace_share_accept(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_workspace_share_accept()."""
    return _legacy.api_workspace_share_accept(*args, **kwargs)


@workspace_bp.route('/api/workspace/events', methods=['GET', 'OPTIONS'])
def api_workspace_events(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_workspace_events()."""
    return _legacy.api_workspace_events(*args, **kwargs)


@workspace_bp.route('/api/workspace/live/<workspace_id>', methods=['GET'])
def api_workspace_live_stream(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_workspace_live_stream()."""
    return _legacy.api_workspace_live_stream(*args, **kwargs)
