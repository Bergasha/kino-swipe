from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

def create_app():
    app = Flask(__name__,
                template_folder='templates',
                static_folder='static',
                static_url_path='/static')

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)

    from app.database import init_db
    init_db()

    from app import config
    app.secret_key = config.flask_secret()
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

    if config.env_value('KINO_RESET_SETUP'):
        config.delete(
            'PLEX_URL', 'PLEX_TOKEN', 'PLEX_SERVER_NAME', 'PLEX_MACHINE_ID',
            'JELLYFIN_URL', 'JELLYFIN_API_KEY', 'JELLYFIN_SERVER_NAME',
        )
        print("[setup] KINO_RESET_SETUP is set: saved Plex and Jellyfin connections were cleared. "
              "Remove that variable and restart once you have set Kino-Swipe up again.", flush=True)

    from app.routes import main_bp
    from app.setup import setup_bp
    app.register_blueprint(main_bp)
    app.register_blueprint(setup_bp)

    from app.services import is_plex_ready, is_jellyfin_ready
    if not (is_plex_ready() or is_jellyfin_ready()):
        print("[setup] Kino-Swipe isn't set up yet. Open it in your browser to finish setup.", flush=True)

    return app
