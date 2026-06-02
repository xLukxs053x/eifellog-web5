"""Rollen-IDs und Berechtigungsprüfungen für EifelLog."""

from __future__ import annotations

import os

from app.config import env_first
from app.core.utils import clean_roles

ROLE_FAHRER = os.getenv("ROLE_FAHRER")
ROLE_GESCHAEFTSLEITUNG = os.getenv("ROLE_GESCHAEFTSLEITUNG")
ROLE_PROJEKTLEITUNG = os.getenv("ROLE_PROJEKTLEITUNG")
ROLE_STELLVERTRETENDE_PROJEKTLEITUNG = os.getenv("ROLE_STELLVERTRETENDE_PROJEKTLEITUNG")
ROLE_FUHRPARKMANAGEMENT = os.getenv("ROLE_FUHRPARKMANAGEMENT")
ROLE_BUCHHALTUNG = os.getenv("ROLE_BUCHHALTUNG")
ROLE_HR_CONTROLLING = env_first("ROLE_HR_CONTROLLING", "HR_CONTROLLING_ROLE_ID", default="1473726292963885188")
ROLE_DISPOSITION = os.getenv("ROLE_DISPOSITION")
ROLE_PERSONALMANAGEMENT = os.getenv("ROLE_PERSONALMANAGEMENT")
ROLE_PROBEFAHRER = os.getenv("ROLE_PROBEFAHRER")

# Hardcoded Rollen IDs basierend auf Vorgaben
ROLE_PERSONALABTEILUNG_ID = "1473725287505072174"
ROLE_GESCHAEFTSFUEHRUNG_ID = "1473721587122438322"
ROLE_PROJEKTLEITUNG_ID = "1473721587122438321"
ROLE_STELLVERTRETENDE_PROJEKTLEITUNG_ID = "1473721587122438320"
ROLE_BUCHHALTUNG_ID = "1473730533593845951"
ROLE_FAHRER_ID = env_first("ROLE_FAHRER_ID", "FAHRER_ROLE_ID", default=ROLE_FAHRER or "1473721587101339681")
ROLE_PROBEFAHRER_ID = env_first("ROLE_PROBEFAHRER_ID", "PROBEFAHRER_ROLE_ID", default=ROLE_PROBEFAHRER or "1508193258214265003")
ROLE_FUHRPARKMANAGEMENT_ID = env_first("ROLE_FUHRPARKMANAGEMENT_ID", "FUHRPARKMANAGEMENT_ROLE_ID", "FUHRPARK_ROLE_ID", default=ROLE_FUHRPARKMANAGEMENT or "")
ROLE_HR_CONTROLLING_ID = env_first("ROLE_HR_CONTROLLING_ID", "HR_CONTROLLING_ROLE_ID", default=ROLE_HR_CONTROLLING or "1473726292963885188")
ROLE_DISPOSITION_ID = env_first("ROLE_DISPOSITION_ID", "DISPOSITION_ROLE_ID", default=ROLE_DISPOSITION or "")

# Admin-Area: Zugriff ausschließlich fuer die von dir vorgegebenen Discord-Rollen.
ADMIN_AREA_PERSONALABTEILUNG_ROLE_ID = "1473721587122438321"
ADMIN_AREA_GESCHAEFTSLEITUNG_ROLE_ID = "1473721587122438322"
ADMIN_AREA_ALLOWED_ROLE_IDS = {
    ADMIN_AREA_PERSONALABTEILUNG_ROLE_ID,
    ADMIN_AREA_GESCHAEFTSLEITUNG_ROLE_ID,
}

ALLOWED_HUB_ROLES = [
    ROLE_FAHRER,
    ROLE_FAHRER_ID,
    ROLE_PROBEFAHRER,
    ROLE_PROBEFAHRER_ID,
    ROLE_GESCHAEFTSLEITUNG,
    ROLE_GESCHAEFTSFUEHRUNG_ID,
    ROLE_PROJEKTLEITUNG,
    ROLE_PROJEKTLEITUNG_ID,
    ROLE_STELLVERTRETENDE_PROJEKTLEITUNG,
    ROLE_STELLVERTRETENDE_PROJEKTLEITUNG_ID,
    ROLE_FUHRPARKMANAGEMENT,
    ROLE_FUHRPARKMANAGEMENT_ID,
    ROLE_BUCHHALTUNG,
    ROLE_BUCHHALTUNG_ID,
    ROLE_HR_CONTROLLING,
    ROLE_HR_CONTROLLING_ID,
    ROLE_DISPOSITION,
    ROLE_DISPOSITION_ID,
    ROLE_PERSONALMANAGEMENT,
    ROLE_PERSONALABTEILUNG_ID
]

PERSONALABTEILUNG_ALLOWED_ROLES = {
    ROLE_PERSONALABTEILUNG_ID,
    ROLE_GESCHAEFTSFUEHRUNG_ID,
    ROLE_PROJEKTLEITUNG_ID,
    ROLE_HR_CONTROLLING,
    ROLE_HR_CONTROLLING_ID,
    "1473726292963885188",
    "HR-Controlling",
    "HR Controlling",
    "hr-controlling",
    "hr controlling"
}

DISPOSITION_ALLOWED_ROLES = {
    ROLE_DISPOSITION,
    ROLE_DISPOSITION_ID,
    ROLE_GESCHAEFTSLEITUNG,
    ROLE_GESCHAEFTSFUEHRUNG_ID,
    ROLE_PROJEKTLEITUNG,
    ROLE_PROJEKTLEITUNG_ID,
    "Disposition",
    "Disponent",
    "disposition",
    "disponent",
    "dispo",
    "Geschäftsleitung",
    "Geschaeftsleitung",
    "Geschäftsführung",
    "Geschaeftsfuehrung",
    "Projektleitung",
    "projektleitung"
}

GESCHAEFTSLEITUNG_ALLOWED_ROLES = {
    ROLE_GESCHAEFTSLEITUNG,
    ROLE_GESCHAEFTSFUEHRUNG_ID,
    ROLE_PROJEKTLEITUNG,
    ROLE_PROJEKTLEITUNG_ID,
    "Geschäftsleitung",
    "Geschaeftsleitung",
    "Geschäftsführung",
    "Geschaeftsfuehrung",
    "geschäftsleitung",
    "geschaeftsleitung",
    "geschäftsführung",
    "geschaeftsfuehrung",
    "Projektleitung",
    "projektleitung"
}

# Rollen, die die Dispo-Formularseite öffnen und Belege einreichen dürfen.
# Der Zugriff auf /dispo/form ist bewusst breit, die Einsicht in eingereichte Dokumente bleibt getrennt.
DISPO_FORM_ACCESS_ROLES = {
    ROLE_FAHRER,
    ROLE_FAHRER_ID,
    ROLE_BUCHHALTUNG,
    ROLE_BUCHHALTUNG_ID,
    ROLE_HR_CONTROLLING,
    ROLE_HR_CONTROLLING_ID,
    ROLE_FUHRPARKMANAGEMENT,
    ROLE_FUHRPARKMANAGEMENT_ID,
    ROLE_PERSONALMANAGEMENT,
    ROLE_PERSONALABTEILUNG_ID,
    ROLE_DISPOSITION,
    ROLE_DISPOSITION_ID,
    ROLE_GESCHAEFTSLEITUNG,
    ROLE_GESCHAEFTSFUEHRUNG_ID,
    ROLE_PROJEKTLEITUNG,
    ROLE_PROJEKTLEITUNG_ID,
    ROLE_STELLVERTRETENDE_PROJEKTLEITUNG,
    ROLE_STELLVERTRETENDE_PROJEKTLEITUNG_ID,
    "Fahrer",
    "fahrer",
    "Buchhaltung",
    "buchhaltung",
    "HR-Controlling",
    "HR Controlling",
    "hr-controlling",
    "hr controlling",
    "Fuhrparkmanagement",
    "fuhrparkmanagement",
    "Personalmanagement",
    "Personalabteilung",
    "personalmanagement",
    "personalabteilung",
    "Disposition",
    "Disponent",
    "disposition",
    "disponent",
    "dispo",
    "Geschäftsleitung",
    "Geschaeftsleitung",
    "Geschäftsführung",
    "Geschaeftsfuehrung",
    "Projektleitung",
    "projektleitung",
    "Stellvertretende Projektleitung",
    "stellvertretende projektleitung"
}

# Nur diese Rolle sieht auf /dispo/form die Disponenten-Ansicht / Sektion „Eingereichte Dokumente“.
DISPO_SUBMITTED_DOCUMENTS_ALLOWED_ROLES = {
    ROLE_DISPOSITION,
    ROLE_DISPOSITION_ID,
    "Disposition",
    "Disponent",
    "disposition",
    "disponent",
    "dispo"
}

# Diese Rollen sollen die Sektion „Eingereichte Dokumente“ ausdrücklich nicht sehen.
DISPO_SUBMITTED_DOCUMENTS_BLOCKED_ROLES = {
    ROLE_HR_CONTROLLING,
    ROLE_HR_CONTROLLING_ID,
    ROLE_FAHRER,
    ROLE_FAHRER_ID,
    ROLE_BUCHHALTUNG,
    ROLE_BUCHHALTUNG_ID,
    ROLE_PERSONALMANAGEMENT,
    ROLE_PERSONALABTEILUNG_ID,
    ROLE_FUHRPARKMANAGEMENT,
    ROLE_FUHRPARKMANAGEMENT_ID,
    "HR-Controlling",
    "HR Controlling",
    "hr-controlling",
    "hr controlling",
    "Fahrer",
    "fahrer",
    "Buchhaltung",
    "buchhaltung",
    "Personalmanagement",
    "Personalabteilung",
    "personalmanagement",
    "personalabteilung",
    "Fuhrparkmanagement",
    "fuhrparkmanagement"
}

def has_dashboard_permission(user_roles):
    clean_user_roles = clean_roles(user_roles)
    clean_allowed_roles = clean_roles(ALLOWED_HUB_ROLES)
    return any(role in clean_user_roles for role in clean_allowed_roles)

def has_disposition_permission(user_roles):
    clean_user_roles = set(clean_roles(user_roles))
    clean_allowed_roles = set(clean_roles(DISPOSITION_ALLOWED_ROLES))
    if clean_user_roles.intersection(clean_allowed_roles):
        return True

    primary_role_name = get_primary_role_name(user_roles)
    return primary_role_name in {"Disposition", "Projektleitung", "Geschäftsleitung"}

def has_geschaeftsleitung_permission(user_roles):
    clean_user_roles = set(clean_roles(user_roles))
    clean_allowed_roles = set(clean_roles(GESCHAEFTSLEITUNG_ALLOWED_ROLES))
    if clean_user_roles.intersection(clean_allowed_roles):
        return True

    primary_role_name = get_primary_role_name(user_roles)
    return primary_role_name in {"Geschäftsleitung", "Geschäftsführung", "Projektleitung"}

def has_admin_area_permission(user_roles):
    """Admin-Area nur fuer die explizit erlaubten Discord-Rollen-IDs freigeben."""
    clean_user_roles = set(clean_roles(user_roles))
    clean_allowed_roles = set(clean_roles(ADMIN_AREA_ALLOWED_ROLE_IDS))
    return bool(clean_user_roles.intersection(clean_allowed_roles))

def has_dispo_form_access(user_roles):
    clean_user_roles = set(clean_roles(user_roles))
    clean_allowed_roles = set(clean_roles(DISPO_FORM_ACCESS_ROLES))
    if clean_user_roles.intersection(clean_allowed_roles):
        return True

    # Fallback: Jeder eingeloggte Discord-Nutzer aus der App darf das Formular betreten.
    return True

def has_dispo_submitted_documents_permission(user_roles):
    clean_user_roles = set(clean_roles(user_roles))
    clean_allowed_roles = set(clean_roles(DISPO_SUBMITTED_DOCUMENTS_ALLOWED_ROLES))

    # Disposition überschreibt Basisrollen wie Fahrer, falls ein Disponent mehrere Discord-Rollen besitzt.
    if clean_user_roles.intersection(clean_allowed_roles):
        return True

    primary_role_name = get_primary_role_name(user_roles)
    return primary_role_name in {"Disposition"}

def has_dispo_blocked_documents_role(user_roles):
    clean_user_roles = set(clean_roles(user_roles))
    clean_blocked_roles = set(clean_roles(DISPO_SUBMITTED_DOCUMENTS_BLOCKED_ROLES))
    return bool(clean_user_roles.intersection(clean_blocked_roles))

def get_primary_role_name(user_roles):
    clean_user_roles = clean_roles(user_roles)

    if str(ROLE_GESCHAEFTSLEITUNG).strip() in clean_user_roles or str(ROLE_GESCHAEFTSFUEHRUNG_ID).strip() in clean_user_roles: return "Geschäftsleitung"
    if str(ROLE_PROJEKTLEITUNG).strip() in clean_user_roles or str(ROLE_PROJEKTLEITUNG_ID).strip() in clean_user_roles: return "Projektleitung"
    if str(ROLE_STELLVERTRETENDE_PROJEKTLEITUNG).strip() in clean_user_roles or str(ROLE_STELLVERTRETENDE_PROJEKTLEITUNG_ID).strip() in clean_user_roles: return "Stellvertretende Projektleitung"
    if str(ROLE_DISPOSITION).strip() in clean_user_roles or str(ROLE_DISPOSITION_ID).strip() in clean_user_roles or "Disposition" in clean_user_roles or "Disponent" in clean_user_roles: return "Disposition"
    if str(ROLE_PERSONALMANAGEMENT).strip() in clean_user_roles or str(ROLE_PERSONALABTEILUNG_ID).strip() in clean_user_roles: return "Personalmanagement"
    if str(ROLE_HR_CONTROLLING).strip() in clean_user_roles or str(ROLE_HR_CONTROLLING_ID).strip() in clean_user_roles: return "HR-Controlling"
    if "HR-Controlling" in clean_user_roles or "HR Controlling" in clean_user_roles: return "HR-Controlling"
    if str(ROLE_BUCHHALTUNG).strip() in clean_user_roles or str(ROLE_BUCHHALTUNG_ID).strip() in clean_user_roles: return "Buchhaltung"
    if str(ROLE_FUHRPARKMANAGEMENT).strip() in clean_user_roles or str(ROLE_FUHRPARKMANAGEMENT_ID).strip() in clean_user_roles: return "Fuhrparkmanagement"
    if str(ROLE_PROBEFAHRER).strip() in clean_user_roles or str(ROLE_PROBEFAHRER_ID).strip() in clean_user_roles or "Probefahrer" in clean_user_roles or "probefahrer" in clean_user_roles: return "Probefahrer"
    if str(ROLE_FAHRER).strip() in clean_user_roles or str(ROLE_FAHRER_ID).strip() in clean_user_roles: return "Fahrer"

    return "Fahrer"
