"""Blueprint-Routen für den EifelLog-Bereich: public."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from typing import Any

from flask import Blueprint, Response, current_app, jsonify, request, session

from app import legacy as _legacy


public_bp = Blueprint("public", __name__)


# ==========================================
# EIFEL LOG CAPTCHA: KONFIGURATION
# ==========================================
#
# Das Frontend in base.html verwendet automatisch diese Endpunkte:
#   GET  /api/captcha/challenge
#   POST /api/captcha/verify
#
# Ein Formular wird im Template mit folgendem Attribut aktiviert:
#   <form method="post" data-eifel-captcha="true">
#
# In der zugehörigen POST-Route muss vor der eigentlichen Verarbeitung
# consume_eifel_captcha() aufgerufen werden.
#
# Wichtig:
# - SECRET_KEY muss in der Flask-App sicher gesetzt sein.
# - Ein eigenes Captcha ersetzt weder CSRF-Schutz noch Rate-Limiting.
# - Für besonders sensible Formulare zusätzlich serverseitig begrenzen,
#   wie oft eine Route pro IP-Adresse / Nutzer aufgerufen werden darf.

CAPTCHA_CHALLENGE_TTL_SECONDS = 180
CAPTCHA_PASS_TTL_SECONDS = 300
CAPTCHA_MAX_ATTEMPTS = 3

CAPTCHA_CHALLENGE_SESSION_KEY = "eifel_captcha_challenge"
CAPTCHA_PASS_SESSION_KEY = "eifel_captcha_pass"


def _unix_time() -> int:
    """Liefert den aktuellen Unix-Zeitstempel als Ganzzahl."""
    return int(time.time())


def _secret_key_bytes() -> bytes:
    """Liefert den Flask-SECRET_KEY als Bytes für HMAC-Prüfwerte."""
    secret_key = current_app.config.get("SECRET_KEY")

    if not secret_key:
        raise RuntimeError(
            "Flask SECRET_KEY fehlt. Setze einen sicheren SECRET_KEY, "
            "bevor das Eifel-LOG-Captcha verwendet wird."
        )

    if isinstance(secret_key, bytes):
        return secret_key

    return str(secret_key).encode("utf-8")


def _hmac_digest(namespace: str, value: str) -> str:
    """Erzeugt einen serverseitigen HMAC-Prüfwert."""
    message = f"{namespace}:{value}".encode("utf-8")
    return hmac.new(_secret_key_bytes(), message, hashlib.sha256).hexdigest()


def _json_no_store(payload: dict[str, Any], status: int = 200) -> Response:
    """Erzeugt eine JSON-Antwort, die nicht zwischengespeichert werden darf."""
    response = jsonify(payload)
    response.status_code = status
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


def _build_manifest_question() -> tuple[str, str]:
    """Erzeugt eine zufällige Kontrollfrage im Eifel-LOG-Frachtbrief-Stil."""
    task_type = secrets.choice(("pallets", "crates", "remaining", "trailers"))

    if task_type == "pallets":
        trucks = secrets.randbelow(7) + 3
        pallets_per_truck = secrets.randbelow(8) + 4
        prompt = (
            f"{trucks} Trucks laden jeweils {pallets_per_truck} Paletten. "
            "Wie viele Paletten werden insgesamt transportiert?"
        )
        answer = trucks * pallets_per_truck

    elif task_type == "crates":
        pallets = secrets.randbelow(7) + 4
        crates_per_pallet = secrets.randbelow(8) + 3
        prompt = (
            f"Auf {pallets} Paletten stehen jeweils {crates_per_pallet} Kisten. "
            "Wie viele Kisten stehen auf dem Frachtbrief?"
        )
        answer = pallets * crates_per_pallet

    elif task_type == "remaining":
        loaded = secrets.randbelow(45) + 35
        delivered = secrets.randbelow(loaded - 15) + 8
        prompt = (
            f"Ein Trailer startet mit {loaded} Paketen. "
            f"{delivered} Pakete wurden zugestellt. "
            "Wie viele Pakete verbleiben im Trailer?"
        )
        answer = loaded - delivered

    else:
        first_trailer = secrets.randbelow(25) + 18
        second_trailer = secrets.randbelow(25) + 18
        prompt = (
            f"Trailer A meldet {first_trailer} Sendungen und Trailer B "
            f"{second_trailer} Sendungen. Wie viele Sendungen sind es zusammen?"
        )
        answer = first_trailer + second_trailer

    return prompt, str(answer)


def clear_eifel_captcha() -> None:
    """Entfernt eine offene Challenge und eine bestehende Captcha-Freigabe."""
    session.pop(CAPTCHA_CHALLENGE_SESSION_KEY, None)
    session.pop(CAPTCHA_PASS_SESSION_KEY, None)


def consume_eifel_captcha() -> bool:
    """
    Verbraucht einen zuvor ausgestellten Captcha-Einmal-Token.

    Diese Funktion muss am Anfang jeder geschützten POST-Route aufgerufen
    werden. Die Freigabe wird unabhängig vom Ergebnis aus der Session entfernt
    und kann daher nicht mehrfach verwendet werden.

    Beispiel:
        if request.method == "POST":
            if not consume_eifel_captcha():
                flash("Sicherheitsprüfung fehlgeschlagen.", "error")
                return redirect(url_for("public.home"))
    """
    submitted_token = request.form.get("eifel_captcha_token", "").strip()
    grant = session.pop(CAPTCHA_PASS_SESSION_KEY, None)

    if not submitted_token or not isinstance(grant, dict):
        return False

    if int(grant.get("expires_at", 0)) < _unix_time():
        return False

    expected_digest = str(grant.get("token_digest", ""))
    submitted_digest = _hmac_digest("captcha-pass", submitted_token)

    return bool(expected_digest) and hmac.compare_digest(
        expected_digest,
        submitted_digest,
    )


# ==========================================
# ÖFFENTLICHE SEITEN
# ==========================================

@public_bp.route("/")
@public_bp.route("/index.html")
def home(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.home()."""
    return _legacy.home(*args, **kwargs)


@public_bp.route("/about")
@public_bp.route("/about.html")
def about(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.about()."""
    return _legacy.about(*args, **kwargs)


@public_bp.route("/changelog")
@public_bp.route("/changelog.html")
def changelog(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.changelog()."""
    return _legacy.changelog(*args, **kwargs)


@public_bp.route("/tutorial")
def tutorial(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.tutorial()."""
    return _legacy.tutorial(*args, **kwargs)


@public_bp.route("/downloads")
@public_bp.route("/tracker/downloads")
def downloads(*args, **kwargs):
    """
    Delegiert kompatibel an app.legacy.downloads().

    Die zusätzliche Route /tracker/downloads wird vom Tracker-Update-CDN
    als optionale Download-Seite erwartet.
    """
    return _legacy.downloads(*args, **kwargs)


@public_bp.route("/events")
@public_bp.route("/events.html")
def events(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.events()."""
    return _legacy.events(*args, **kwargs)


@public_bp.route("/fuhrpark")
@public_bp.route("/fuhrpark.html")
def fuhrpark(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.fuhrpark()."""
    return _legacy.fuhrpark(*args, **kwargs)


@public_bp.route("/datenschutz")
@public_bp.route("/datenschutz.html")
def datenschutz(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.datenschutz()."""
    return _legacy.datenschutz(*args, **kwargs)


@public_bp.route("/nutzungsbedingungen")
@public_bp.route("/nutzungsbedingungen.html")
def nutzungsbedingungen(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.nutzungsbedingungen()."""
    return _legacy.nutzungsbedingungen(*args, **kwargs)


@public_bp.route("/impressum")
def impressum(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.impressum()."""
    return _legacy.impressum(*args, **kwargs)


@public_bp.route("/team")
@public_bp.route("/team.html")
def team(*args, **kwargs):
    """Delegiert kompatibel an app.legacy.team()."""
    return _legacy.team(*args, **kwargs)


# ==========================================
# EIFEL LOG CAPTCHA: ÖFFENTLICHE API
# ==========================================

@public_bp.route("/api/captcha/challenge", methods=["GET"])
def eifel_captcha_challenge() -> Response:
    """Erstellt eine kurzlebige Sicherheitsfracht für das Captcha-Modal."""
    prompt, answer = _build_manifest_question()
    challenge_id = secrets.token_urlsafe(24)

    # Die Klartext-Lösung wird absichtlich nicht in der Session gespeichert.
    # Normale Flask-Sessions sind signiert, aber nicht verschlüsselt.
    session[CAPTCHA_CHALLENGE_SESSION_KEY] = {
        "challenge_id": challenge_id,
        "answer_digest": _hmac_digest(
            "captcha-answer",
            f"{challenge_id}:{answer}",
        ),
        "expires_at": _unix_time() + CAPTCHA_CHALLENGE_TTL_SECONDS,
        "attempts": 0,
    }

    # Eine eventuell ältere Freigabe wird beim Laden einer neuen Aufgabe
    # ungültig. Dadurch bleibt der Ablauf eindeutig.
    session.pop(CAPTCHA_PASS_SESSION_KEY, None)

    return _json_no_store(
        {
            "challenge_id": challenge_id,
            "prompt": prompt,
            "expires_in": CAPTCHA_CHALLENGE_TTL_SECONDS,
        }
    )


@public_bp.route("/api/captcha/verify", methods=["POST"])
def eifel_captcha_verify() -> Response:
    """Prüft die Lösung und erstellt bei Erfolg einen Einmal-Token."""
    payload = request.get_json(silent=True) or {}
    challenge_id = str(payload.get("challenge_id", "")).strip()
    submitted_answer = str(payload.get("answer", "")).strip()
    challenge = session.get(CAPTCHA_CHALLENGE_SESSION_KEY)

    if not isinstance(challenge, dict) or not challenge_id or not submitted_answer:
        return _json_no_store(
            {
                "success": False,
                "error": "Bitte lade eine neue Sicherheitsfracht.",
            },
            400,
        )

    if int(challenge.get("expires_at", 0)) < _unix_time():
        clear_eifel_captcha()
        return _json_no_store(
            {
                "success": False,
                "error": "Der Frachtbrief ist abgelaufen. Bitte lade eine neue Fracht.",
            },
            410,
        )

    stored_challenge_id = str(challenge.get("challenge_id", ""))

    if not hmac.compare_digest(stored_challenge_id, challenge_id):
        clear_eifel_captcha()
        return _json_no_store(
            {
                "success": False,
                "error": "Ungültiger Frachtbrief. Bitte lade eine neue Fracht.",
            },
            400,
        )

    # Alle aktuell erzeugten Aufgaben haben ganzzahlige Lösungen.
    if not submitted_answer.isdigit() or len(submitted_answer) > 4:
        return _register_failed_captcha_attempt(challenge)

    expected_digest = str(challenge.get("answer_digest", ""))
    submitted_digest = _hmac_digest(
        "captcha-answer",
        f"{challenge_id}:{submitted_answer}",
    )

    if not expected_digest or not hmac.compare_digest(
        expected_digest,
        submitted_digest,
    ):
        return _register_failed_captcha_attempt(challenge)

    session.pop(CAPTCHA_CHALLENGE_SESSION_KEY, None)

    pass_token = secrets.token_urlsafe(32)
    session[CAPTCHA_PASS_SESSION_KEY] = {
        "token_digest": _hmac_digest("captcha-pass", pass_token),
        "expires_at": _unix_time() + CAPTCHA_PASS_TTL_SECONDS,
    }

    return _json_no_store(
        {
            "success": True,
            "token": pass_token,
            "expires_in": CAPTCHA_PASS_TTL_SECONDS,
        }
    )


def _register_failed_captcha_attempt(challenge: dict[str, Any]) -> Response:
    """Registriert einen Fehlversuch und sperrt die verbrauchte Challenge."""
    attempts = int(challenge.get("attempts", 0)) + 1

    if attempts >= CAPTCHA_MAX_ATTEMPTS:
        clear_eifel_captcha()
        return _json_no_store(
            {
                "success": False,
                "error": "Zu viele Fehlversuche. Bitte lade eine neue Fracht.",
            },
            429,
        )

    challenge["attempts"] = attempts
    session[CAPTCHA_CHALLENGE_SESSION_KEY] = challenge

    remaining_attempts = CAPTCHA_MAX_ATTEMPTS - attempts
    return _json_no_store(
        {
            "success": False,
            "error": f"Lösung nicht korrekt. Noch {remaining_attempts} Versuch(e).",
        },
        400,
    )


# ==========================================
# ÖFFENTLICHE DISCORD-PLUGIN-API
# ==========================================

@public_bp.route("/api/discord/events", methods=["GET"])
def api_discord_events(*args, **kwargs):
    """Liefert die öffentliche Event-Vorschau aus eifellog_db.events."""
    return _legacy.api_discord_events(*args, **kwargs)


@public_bp.route("/api/discord/birthdays", methods=["GET"])
def api_discord_birthdays(*args, **kwargs):
    """Liefert die öffentliche Geburtstagsvorschau aus EifelLog.Birthdays."""
    return _legacy.api_discord_birthdays(*args, **kwargs)