import os
from flask import Flask, render_template, redirect, url_for, session, request
from dotenv import load_dotenv
from .auth import bp as auth_bp
from .ptp import bp as ptp_bp
from .dashboard import bp as dash_bp
from .reservar import bp as resv_bp
from .admin import bp as admin_bp
from .logging_setup  import setup_logging

LOGIN_REQUIRED_PREFIXES = ("/dashboard", "/account", "/admin")

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
    try:
        setup_logging(app)
    except Exception as e:
        import logging as stdlog
        sh = stdlog.StreamHandler()
        sh.setLevel(stdlog.INFO)
        sh.setFormatter(stdlog.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        app.logger.addHandler(sh)
        app.logger.error("Fallo configurando logging DB; usando StreamHandler. %s", e, exc_info=True)
 
    # Middleware: exigir login en rutas protegidas
    @app.before_request
    def _force_login_on_protected_routes():
        path = request.path or "/"
        if path.startswith("/static") or path.startswith("/healthz") or path.startswith("/auth"):
            return
        if path.startswith(LOGIN_REQUIRED_PREFIXES) and not session.get("uid"):
            # respeta ?next=
            return redirect(url_for("auth.login_get", next=path))

    # Home -> redirección por sesión
    @app.get("/")
    def index():
        if session.get("uid"):
            return redirect(url_for("dash.estado"))
        return redirect(url_for("auth.login_get"))

    # Alias /dashboard
    @app.get("/dashboard")
    def dashboard_home():
        return redirect(url_for("dash.estado"))

    # Healthcheck
    @app.get("/healthz")
    def health():
        return "ok", 200, {"Content-Type": "text/plain; charset=utf-8"}

    # Errores
    @app.errorhandler(404)
    def not_found(e):
        return render_template("errors/404.html", titulo="Página no encontrada"), 404

    @app.errorhandler(500)
    def internal_error(e):
        return render_template("errors/500.html", titulo="Error del servidor"), 500

    return app
