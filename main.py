import eventlet

# Eventlet-Patching muss vor dem Import der Flask-App stattfinden.
eventlet.monkey_patch()

from app import create_app
from app.config import MONGO_DB_NAME, SERVER_HOST, SERVER_PORT


app = create_app()


if __name__ == "__main__":
    print(
        f"Starte Eifel LOG Server mit MongoDB DB '{MONGO_DB_NAME}' "
        f"und Eventlet auf {SERVER_HOST}:{SERVER_PORT}..."
    )
    eventlet.wsgi.server(eventlet.listen((SERVER_HOST, SERVER_PORT)), app)