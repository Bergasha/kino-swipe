import os
from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

def create_app():
    app = Flask(__name__, 
                template_folder='templates', 
                static_folder='static',
                static_url_path='/static')
    
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)
    app.secret_key = os.environ.get("FLASK_SECRET")

    if not os.environ.get('FLASK_SECRET'):
        raise RuntimeError("Missing env var: FLASK_SECRET")
    if not os.environ.get('TMDB_API_KEY'):
        raise RuntimeError("Missing env var: TMDB_API_KEY")

 
    from app.database import init_db
    init_db()

   
    from app.routes import main_bp
    app.register_blueprint(main_bp)

    return app