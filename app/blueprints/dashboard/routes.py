"""Blueprint-Routen für den EifelLog-Bereich: dashboard."""

from __future__ import annotations

from flask import Blueprint

from app import legacy as _legacy


dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route('/api/dashboard/state', methods=['GET', 'OPTIONS'])
@dashboard_bp.route('/api/dashboard/data', methods=['GET', 'OPTIONS'])
def dashboard_state_api(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.dashboard_state_api()."""
    return _legacy.dashboard_state_api(*args, **kwargs)


@dashboard_bp.route('/user')
def my_profile_redirect(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.my_profile_redirect()."""
    return _legacy.my_profile_redirect(*args, **kwargs)


@dashboard_bp.route('/user/<username>', methods=['GET', 'POST'])
def profile(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.profile()."""
    return _legacy.profile(*args, **kwargs)


@dashboard_bp.route('/hub')
def hub(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.hub()."""
    return _legacy.hub(*args, **kwargs)


@dashboard_bp.route('/leaderboard', methods=['GET'])
@dashboard_bp.route('/leaderboard.html', methods=['GET'])
def leaderboard(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.leaderboard()."""
    return _legacy.leaderboard(*args, **kwargs)


@dashboard_bp.route('/dashboard')
def dashboard(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.dashboard()."""
    return _legacy.dashboard(*args, **kwargs)


@dashboard_bp.route('/api/dashboard/instructions/update-wipe-info', methods=['GET', 'OPTIONS'])
def api_dashboard_update_wipe_info_status(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_dashboard_update_wipe_info_status()."""
    return _legacy.api_dashboard_update_wipe_info_status(*args, **kwargs)


@dashboard_bp.route('/api/dashboard/instructions/update-wipe-info/acknowledge', methods=['POST', 'OPTIONS'])
def api_dashboard_acknowledge_update_wipe_info(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_dashboard_acknowledge_update_wipe_info()."""
    return _legacy.api_dashboard_acknowledge_update_wipe_info(*args, **kwargs)


@dashboard_bp.route('/api/dashboard/loa/upcoming')
def api_dashboard_loa_upcoming(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_dashboard_loa_upcoming()."""
    return _legacy.api_dashboard_loa_upcoming(*args, **kwargs)


@dashboard_bp.route('/api/dashboard/loa/<record_id>')
def api_dashboard_loa_detail(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.api_dashboard_loa_detail()."""
    return _legacy.api_dashboard_loa_detail(*args, **kwargs)


@dashboard_bp.route('/dashboard/detail', methods=['GET'])
@dashboard_bp.route('/dashboard/detail.html', methods=['GET'])
def dashboard_detail(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.dashboard_detail()."""
    return _legacy.dashboard_detail(*args, **kwargs)


@dashboard_bp.route('/dashboard/gefahrene-km', methods=['GET'])
@dashboard_bp.route('/dashboard/gefahrene-km/details', methods=['GET'])
@dashboard_bp.route('/dashboard/gefahrene-km-details', methods=['GET'])
@dashboard_bp.route('/dashboard/gefahrene_km_details.html', methods=['GET'])
def dashboard_gefahrene_km_details(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.dashboard_gefahrene_km_details()."""
    return _legacy.dashboard_gefahrene_km_details(*args, **kwargs)


@dashboard_bp.route('/dashboard/kontostand', methods=['GET'])
@dashboard_bp.route('/dashboard/kontostand/details', methods=['GET'])
@dashboard_bp.route('/dashboard/kontostand-details', methods=['GET'])
@dashboard_bp.route('/dashboard/kontostand_details.html', methods=['GET'])
def dashboard_kontostand_details(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.dashboard_kontostand_details()."""
    return _legacy.dashboard_kontostand_details(*args, **kwargs)


@dashboard_bp.route('/dashboard/fahrer-level', methods=['GET'])
@dashboard_bp.route('/dashboard/fahrer-level/details', methods=['GET'])
@dashboard_bp.route('/dashboard/fahrer-level-details', methods=['GET'])
@dashboard_bp.route('/dashboard/fahrer_level_details.html', methods=['GET'])
def dashboard_fahrer_level_details(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.dashboard_fahrer_level_details()."""
    return _legacy.dashboard_fahrer_level_details(*args, **kwargs)


@dashboard_bp.route('/dashboard/abgeschlossen', methods=['GET'])
@dashboard_bp.route('/dashboard/abgeschlossene-touren', methods=['GET'])
@dashboard_bp.route('/dashboard/abgeschlossene-touren/details', methods=['GET'])
@dashboard_bp.route('/dashboard/abgeschlossene-touren-details', methods=['GET'])
@dashboard_bp.route('/dashboard/abgeschlossene_touren_details.html', methods=['GET'])
def dashboard_abgeschlossene_touren_details(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.dashboard_abgeschlossene_touren_details()."""
    return _legacy.dashboard_abgeschlossene_touren_details(*args, **kwargs)
