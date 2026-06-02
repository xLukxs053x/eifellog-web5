"""EifelLog Flask-App-Fabrik.

Während der kontrollierten Migration wird die bestehende Anwendung aus
app.legacy geladen. Neue Bereiche können anschließend schrittweise als
Blueprints ausgelagert werden.
"""


def create_app():
    from app.legacy import app
    return app