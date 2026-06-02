"""Allgemeine, wiederverwendbare Hilfsfunktionen für EifelLog."""

from __future__ import annotations

import json
import math
import os
import re
from datetime import datetime

__all__ = [
    "now_utc",
    "mongo_upsert_set_preserve_created_at",
    "safe_str",
    "clean_roles",
    "normalize_username",
    "format_datetime_for_template",
    "datetime_to_iso",
    "parse_number",
    "first_present_value",
    "first_present_number",
    "parse_int",
    "load_json_file",
]

def now_utc():
    return datetime.utcnow()

def mongo_upsert_set_preserve_created_at(document):
    """
    Baut ein sicheres MongoDB-Upsert-Update.

    Hintergrund:
    MongoDB verbietet denselben Feldpfad gleichzeitig in $set und $setOnInsert.
    Wenn ein Dokument also created_at enthält, darf created_at nicht zusätzlich
    in $setOnInsert stehen, solange das komplette Dokument per $set gesetzt wird.

    Diese Funktion entfernt created_at aus $set und setzt es nur beim Insert.
    Dadurch bleibt created_at bei bestehenden Datensätzen stabil und bei neuen
    Datensätzen trotzdem vorhanden.
    """
    set_fields = dict(document or {})
    created_at_value = set_fields.pop("created_at", None)

    update_doc = {"$set": set_fields}
    if created_at_value is not None:
        update_doc["$setOnInsert"] = {"created_at": created_at_value}

    return update_doc

def safe_str(value, fallback=""):
    if value is None:
        return fallback
    return str(value).strip()

def clean_roles(roles):
    return [str(role).strip() for role in (roles or []) if role]

def normalize_username(username, fallback="driver"):
    username = str(username or "").strip()
    username = username.replace(" ", "-")
    username = re.sub(r"[^A-Za-z0-9_.-]", "", username)
    username = username[:32].strip(".-_")

    if not username:
        username = fallback
    return username

def format_datetime_for_template(value):
    if isinstance(value, datetime):
        return value.strftime("%d.%m.%Y %H:%M")
    if value:
        return str(value)
    return ""

def datetime_to_iso(value):
    if isinstance(value, datetime):
        return value.isoformat() + "Z"
    if value:
        return str(value)
    return ""

def parse_number(value, fallback=0.0):
    """Parst JSON-, MongoDB- und deutsch formatierte Zahlen ohne Dezimalstellen zu verlieren.

    Beispiele: 123.45, "123.45", "123,45" und "1.234,56 €".
    """
    if value is None:
        return fallback
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else fallback

    text = str(value).strip()
    if not text:
        return fallback

    text = text.replace("\u00a0", " ").replace("€", "").replace("%", "")
    text = re.sub(r"(?i)km", "", text)
    text = text.replace(" ", "").replace("'", "")
    text = re.sub(r"[^0-9,.+\-]", "", text)

    if text in {"", "+", "-", ".", ",", "+.", "-.", "+,", "-,"}:
        return fallback

    if "," in text and "." in text:
        # Das zuletzt vorkommende Trennzeichen ist die Dezimalstelle.
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        parts = text.split(",")
        if len(parts) > 2:
            text = "".join(parts[:-1]) + "." + parts[-1] if len(parts[-1]) in {1, 2} else "".join(parts)
        else:
            text = text.replace(",", ".")
    elif text.count(".") > 1:
        parts = text.split(".")
        text = "".join(parts[:-1]) + "." + parts[-1] if len(parts[-1]) in {1, 2} else "".join(parts)

    try:
        number = float(text)
        return number if math.isfinite(number) else fallback
    except Exception:
        return fallback

def first_present_value(source, *keys, fallback=None):
    """Liest den ersten gesetzten Wert. Anders als `or` bleiben 0 und False erhalten."""
    source = source or {}
    for key in keys:
        if key in source and source.get(key) not in [None, ""]:
            return source.get(key)
    return fallback

def first_present_number(source, *keys, fallback=0.0):
    return parse_number(first_present_value(source, *keys, fallback=fallback), fallback)

def parse_int(value, fallback=0):
    try:
        return int(round(parse_number(value, fallback)))
    except Exception:
        return fallback

def load_json_file(path):
    if not os.path.exists(path): return []
    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception as error:
        print(f"Fehler beim Laden von {path}: {error}")
        return []
