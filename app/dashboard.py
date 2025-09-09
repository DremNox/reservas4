from flask import Blueprint, render_template, session, abort

bp = Blueprint("dash", __name__)

def _require_login():
    if not session.get("uid"):
        abort(401)

@bp.get("/dashboard/estado")
def estado():
    _require_login()
    return render_template("dashboard/estado.html")

@bp.get("/dashboard/precios-cs")
def precios_cs():
    _require_login()
    return render_template("dashboard/precios_cs.html")

@bp.get("/dashboard/precios-ciudad")
def precios_ciudad():
    _require_login()
    return render_template("dashboard/precios_ciudad.html")
