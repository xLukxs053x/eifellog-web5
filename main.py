# WICHTIG: Eventlet muss als allererstes importiert und gepatcht werden!
import eventlet
eventlet.monkey_patch()
import eventlet.wsgi

# Erst danach darf Flask importiert werden
from flask import Flask, render_template

app = Flask(__name__)

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/hub')
def hub():
    return render_template('hub.html')

if __name__ == '__main__':
    print("Starte Eifel LOG Server mit Eventlet auf Port 5005...")
    eventlet.wsgi.server(eventlet.listen(('0.0.0.0', 5005)), app)