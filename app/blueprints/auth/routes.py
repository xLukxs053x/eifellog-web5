"""Blueprint-Routen für den EifelLog-Bereich: auth."""

from __future__ import annotations

from flask import Blueprint

from app import legacy as _legacy


auth_bp = Blueprint("auth", __name__)


@auth_bp.route('/login')
def login(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.login()."""
    return _legacy.login(*args, **kwargs)


@auth_bp.route('/callback')
def callback(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.callback()."""
    return _legacy.callback(*args, **kwargs)


@auth_bp.route('/logout')
def logout(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.logout()."""
    return _legacy.logout(*args, **kwargs)
