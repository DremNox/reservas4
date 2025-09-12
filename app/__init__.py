import os
from flask import Flask, render_template  # <-- añadido
from dotenv import load_dotenv
from .auth import bp as auth_bp
from .ptp import bp as ptp_bp
from .dashboard import bp as dash_bp
from .reservar import bp as resv_bp
from .admin import bp as admin_bp

def create_app():
    load_dotenv()

    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret")
    app.config["TZ"] = os.getenv("TZ", "Europe/Madrid")

    # Blueprints
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(ptp_bp,  url_prefix="/account")
    app.register_blueprint(dash_bp)
    app.register_blueprint(resv_bp)
    app.register_blueprint(admin_bp)

    @app.get("/")
    def index():
        # Evita 500 si no tienes index.html todavía
        try:
            return render_template("base_login.html", titulo="Inicio")
        except Exception:
            return "Reservas 4.0 – Home (pendiente index.html)", 200

    @app.get("/healthz")
    def health():
        return "ok", 200, {"Content-Type": "text/plain; charset=utf-8"}

    @app.errorhandler(404)
    def not_found(e):
        try:
            return render_template("errors/404.html"), 404
        except Exception:
            return "404 Not Found", 404

    @app.errorhandler(500)
    def internal_error(e):
        try:
            return render_template("errors/500.html"), 500
        except Exception:
            return "500 Internal Server Error", 500

    return app
