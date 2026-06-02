"""Blueprint-Routen für den EifelLog-Bereich: public."""

from __future__ import annotations

from flask import Blueprint

from app import legacy as _legacy


public_bp = Blueprint("public", __name__)


@public_bp.route('/')
@public_bp.route('/index.html')
def home(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.home()."""
    return _legacy.home(*args, **kwargs)


@public_bp.route('/about')
@public_bp.route('/about.html')
def about(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.about()."""
    return _legacy.about(*args, **kwargs)


@public_bp.route('/changelog')
@public_bp.route('/changelog.html')
def changelog(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.changelog()."""
    return _legacy.changelog(*args, **kwargs)


@public_bp.route('/tutorial')
def tutorial(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.tutorial()."""
    return _legacy.tutorial(*args, **kwargs)


@public_bp.route('/downloads')
def downloads(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.downloads()."""
    return _legacy.downloads(*args, **kwargs)


@public_bp.route('/fuhrpark')
@public_bp.route('/fuhrpark.html')
def fuhrpark(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.fuhrpark()."""
    return _legacy.fuhrpark(*args, **kwargs)


@public_bp.route('/impressum')
def impressum(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.impressum()."""
    return _legacy.impressum(*args, **kwargs)


@public_bp.route('/team')
@public_bp.route('/team.html')
def team(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.team()."""
    return _legacy.team(*args, **kwargs)
