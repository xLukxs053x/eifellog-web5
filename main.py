import os
import requests
import eventlet
from datetime import datetime
from flask import Flask, render_template, redirect, request, session, url_for, flash, jsonify
from dotenv import load_dotenv
from pymongo import MongoClient

# Wichtig für Eventlet: Optimiert die Hintergrundprozesse
eventlet.monkey_patch()

# Lade Umgebungsvariablen aus der .env Datei
load_dotenv()

app = Flask(__name__)
# Lädt den Secret Key aus der .env oder generiert einen zufälligen als Fallback
app.secret_key = os.getenv("FLASK_SECRET_KEY", os.urandom(24)) 

# ==========================================
# DISCORD OAUTH2 KONFIGURATION (aus .env)
# ==========================================
DISCORD_CLIENT_ID = os.getenv('DISCORD_CLIENT_ID')
DISCORD_CLIENT_SECRET = os.getenv('DISCORD_CLIENT_SECRET')
DISCORD_REDIRECT_URI = os.getenv('DISCORD_REDIRECT_URI')
DISCORD_GUILD_ID = os.getenv('DISCORD_GUILD_ID')

# Discord API Endpunkte
OAUTH_URL = 'https://discord.com/api/oauth2/authorize'
TOKEN_URL = 'https://discord.com/api/oauth2/token'
API_BASE_URL = 'https://discord.com/api/v10'

# ==========================================
# MONGODB KONFIGURATION (aus .env)
# ==========================================
MONGO_URI = os.getenv('MONGO_URI')
# Verbindung zur Datenbank herstellen
mongo_client = MongoClient(MONGO_URI)
# Wir erstellen/nutzen eine Datenbank namens "eifellog_db"
db = mongo_client['eifellog_db']
# Tabelle (Collection) für die Benutzer
users_collection = db['users']

# ==========================================
# EIFEL LOG ROLLEN IDs (aus .env)
# ==========================================
ROLE_FAHRER = os.getenv('ROLE_FAHRER')
ROLE_GESCHAEFTSLEITUNG = os.getenv('ROLE_GESCHAEFTSLEITUNG')
ROLE_PROJEKTLEITUNG = os.getenv('ROLE_PROJEKTLEITUNG')
ROLE_FUHRPARKMANAGEMENT = os.getenv('ROLE_FUHRPARKMANAGEMENT')
ROLE_BUCHHALTUNG = os.getenv('ROLE_BUCHHALTUNG')
ROLE_HR_CONTROLLING = os.getenv('ROLE_HR_CONTROLLING')
ROLE_DISPOSITION = os.getenv('ROLE_DISPOSITION')
ROLE_PERSONALMANAGEMENT = os.getenv('ROLE_PERSONALMANAGEMENT')

# Alle Rollen, die das Dashboard betreten dürfen
ALLOWED_HUB_ROLES = [
    ROLE_FAHRER, 
    ROLE_GESCHAEFTSLEITUNG, 
    ROLE_PROJEKTLEITUNG, 
    ROLE_FUHRPARKMANAGEMENT, 
    ROLE_BUCHHALTUNG,
    ROLE_HR_CONTROLLING,
    ROLE_DISPOSITION,
    ROLE_PERSONALMANAGEMENT
]


# ==========================================
# ROUTES - ÖFFENTLICH
# ==========================================

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/about')
def about():
    return render_template('about.html')


# --- AUTHENTIFIZIERUNG ---

@app.route('/login')
def login():
    # Leitet den Nutzer zu Discord weiter. Wir fragen Profil ('identify') und Serverliste ('guilds') ab.
    auth_url = f"{OAUTH_URL}?client_id={DISCORD_CLIENT_ID}&redirect_uri={DISCORD_REDIRECT_URI}&response_type=code&scope=identify%20guilds"
    return redirect(auth_url)

@app.route('/callback')
def callback():
    code = request.args.get('code')
    if not code:
        flash("Login abgebrochen.", "error")
        return redirect(url_for('home'))

    # Code gegen ein Access Token eintauschen
    data = {
        'client_id': DISCORD_CLIENT_ID,
        'client_secret': DISCORD_CLIENT_SECRET,
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': DISCORD_REDIRECT_URI
    }
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    r = requests.post(TOKEN_URL, data=data, headers=headers)
    
    if r.status_code != 200:
        flash("Fehler bei der Discord-Kommunikation. Bitte Client ID/Secret prüfen.", "error")
        return redirect(url_for('home'))
        
    token = r.json()['access_token']
    auth_headers = {'Authorization': f'Bearer {token}'}

    # 1. Basis-Benutzerdaten holen (ID, Name, Profilbild)
    user_r = requests.get(f"{API_BASE_URL}/users/@me", headers=auth_headers)
    user_data = user_r.json()

    # 2. Server-spezifische Daten holen (Rollen des Nutzers auf dem Eifel LOG Server)
    member_r = requests.get(f"{API_BASE_URL}/users/@me/guilds/{DISCORD_GUILD_ID}/member", headers=auth_headers)
    
    if member_r.status_code == 404:
        flash("Du musst Mitglied auf dem Eifel LOG Discord Server sein!", "error")
        return redirect(url_for('home'))
        
    member_data = member_r.json()
    user_roles = member_data.get('roles', [])

    # 3. Datenbasis für MongoDB vorbereiten
    discord_id = user_data['id']
    username = user_data['username']
    avatar = user_data.get('avatar')

    # Dokument für die Datenbank erstellen
    db_user_data = {
        'discord_id': discord_id,
        'username': username,
        'avatar': avatar,
        'roles': user_roles,
        'last_login': datetime.utcnow()
    }

    # In MongoDB speichern oder aktualisieren (upsert=True)
    users_collection.update_one(
        {'discord_id': discord_id},
        {'$set': db_user_data},
        upsert=True
    )

    # 4. Session für den Browser speichern
    session['user'] = {
        'id': discord_id,
        'username': username,
        'avatar': avatar,
        'roles': user_roles
    }

    flash("Erfolgreich eingeloggt!", "success")
    # Nach Login direkt aufs Dashboard leiten
    return redirect(url_for('dashboard'))

@app.route('/logout')
def logout():
    session.pop('user', None)
    flash("Erfolgreich abgemeldet.", "success")
    return redirect(url_for('home'))


# --- DRIVER HUB (LOGIN PORTAL) ---

@app.route('/hub')
def hub():
    # Wenn der User schon eingeloggt ist, direkt zum Dashboard
    if 'user' in session:
        return redirect(url_for('dashboard'))
        
    # Ansonsten die Login-Seite anzeigen
    return render_template('hub.html')


# --- DASHBOARD (GESCHÜTZTER BEREICH) ---

@app.route('/dashboard')
def dashboard():
    # 1. Prüfen ob eingeloggt
    if 'user' not in session:
        flash("Bitte logge dich zuerst ein.", "error")
        return redirect(url_for('hub'))
        
    user = session['user']
    user_roles = user.get('roles', [])
    
    # --- SICHERHEITS-FIX: Rollen bereinigen (verhindert Fehler durch Leerzeichen in der .env) ---
    clean_user_roles = [str(r).strip() for r in user_roles]
    clean_allowed_roles = [str(r).strip() for r in ALLOWED_HUB_ROLES if r]
    
    # 2. Prüfen ob der Nutzer eine der erlaubten Rollen hat
    has_permission = any(role in clean_user_roles for role in clean_allowed_roles)
    
    # --- DEBUGGING-AUSGABE IN DER KONSOLE ---
    print("\n=== LOGIN DEBUG INFO ===")
    print(f"User: {user['username']}")
    print(f"User Rollen (Discord): {clean_user_roles}")
    print(f"Erlaubte Rollen (.env): {clean_allowed_roles}")
    print(f"Zugriff gewährt: {has_permission}")
    print("========================\n")
    
    if not has_permission:
        flash("Zugriff verweigert! Du benötigst eine anerkannte Rolle (z.B. Fahrer), um das Dashboard zu betreten.", "error")
        return redirect(url_for('home'))

    # 3. User aus Datenbank laden (für Policy Signatur Check)
    db_user = users_collection.find_one({'discord_id': user['id']})
    
    # Checken ob "policy_signed" fehlt oder False ist
    if db_user:
        needs_signature = not db_user.get('policy_signed', False)
    else:
        needs_signature = True
        
    # 4. Höchste/Wichtigste Rolle für das Dokumenten-Modal ermitteln (Hierarchisch absteigend)
    primary_role_name = "Fahrer"
    if str(ROLE_GESCHAEFTSLEITUNG).strip() in clean_user_roles:
        primary_role_name = "Geschäftsleitung"
    elif str(ROLE_PROJEKTLEITUNG).strip() in clean_user_roles:
        primary_role_name = "Projektleitung"
    elif str(ROLE_PERSONALMANAGEMENT).strip() in clean_user_roles:
        primary_role_name = "Personalmanagement"
    elif str(ROLE_HR_CONTROLLING).strip() in clean_user_roles:
        primary_role_name = "HR Controlling"
    elif str(ROLE_BUCHHALTUNG).strip() in clean_user_roles:
        primary_role_name = "Buchhaltung"
    elif str(ROLE_DISPOSITION).strip() in clean_user_roles:
        primary_role_name = "Disposition"
    elif str(ROLE_FUHRPARKMANAGEMENT).strip() in clean_user_roles:
        primary_role_name = "Fuhrparkmanagement"

    return render_template('dashboard.html', 
                           current_user=user, 
                           needs_signature=needs_signature,
                           primary_role_name=primary_role_name)


# --- API ROUTEN ---

@app.route('/api/sign_policy', methods=['POST'])
def sign_policy():
    if 'user' not in session:
        return jsonify({"success": False, "error": "Not logged in"}), 401
        
    data = request.get_json()
    signature = data.get('signature')
    
    if not signature:
        return jsonify({"success": False, "error": "No signature provided"}), 400

    # In der Datenbank updaten
    users_collection.update_one(
        {'discord_id': session['user']['id']},
        {'$set': {
            'policy_signed': True,
            'policy_signature': signature,
            'policy_signed_at': datetime.utcnow()
        }}
    )
    
    return jsonify({"success": True})


if __name__ == '__main__':
    print("Starte Eifel LOG Server mit MongoDB und Eventlet auf Port 5005...")
    eventlet.wsgi.server(eventlet.listen(('0.0.0.0', 5005)), app)