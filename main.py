import eventlet
from flask import Flask, render_template

# Wichtig für Eventlet: Optimiert die Hintergrundprozesse
eventlet.monkey_patch()

app = Flask(__name__)

# Route für die Startseite
@app.route('/')
def home():
    return render_template('index.html')

# Route für eine reine "Über uns" Seite
@app.route('/about')
def about():
    return render_template('about.html')

# Route für den Driver Hub
@app.route('/hub')
def hub():
    # Lädt jetzt ein richtiges Template für den Hub
    return render_template('hub.html')

if __name__ == '__main__':
    print("Starte Eifel LOG Server mit Eventlet auf Port 5005...")
    
    # '0.0.0.0' macht den Server nach außen hin sichtbar (public)
    # Port 5005 bleibt bestehen
    eventlet.wsgi.server(eventlet.listen(('0.0.0.0', 5005)), app)