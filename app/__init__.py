import os
from flask import Flask
from dotenv import load_dotenv
from .auth import bp as auth_bp
from .ptp import bp as ptp_bp
from .dashboard import bp as dash_bp
from .reservar import bp as resv_bp
from .admin import bp as admin_bp

def create_app():
    load_dotenv()  # carga .env si existe

    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret")
    app.config["TZ"] = os.getenv("TZ", "Europe/Madrid")

    # Blueprints
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(ptp_bp,  url_prefix="/account")
    app.register_blueprint(dash_bp)      # /dashboard/*
    app.register_blueprint(resv_bp)      # /dashboard/reservar...
    app.register_blueprint(admin_bp)     # /admin

    # Home -> HTML
    @app.get("/")
    def index():
        return render_template("index.html", titulo="Inicio")

    # Healthcheck simple (texto)
    @app.get("/healthz")
    def health():
        return "ok", 200, {"Content-Type": "text/plain; charset=utf-8"}

    # (Opcional) manejo de errores a HTML
    @app.errorhandler(404)
    def not_found(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def internal_error(e):
        return render_template("errors/500.html"), 500
    return app