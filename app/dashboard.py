from flask import Blueprint, render_template, session, abort, jsonify, current_app
from .db import fetch_all
from .estado import scrape_conector_estado

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
@bp.post("/dashboard/estado/refresh")
def estado_refresh():
    _require_login()
    # Busca el account PTP del usuario (usamos el primero)
    acc = fetch_all("""
      SELECT a.AccountId FROM dbo.CuentasPTP a
      JOIN dbo.CredencialesPTP c ON c.AccountId=a.AccountId
      WHERE a.UserId=:uid
    """, uid=session["uid"])
    if not acc:
        return jsonify({"ok": False, "error": "Configura tu cuenta PTP primero."}), 400

    account_id = acc[0]["AccountId"]

    conns = fetch_all("""
      SELECT c.ConectorId, c.UrlConector
      FROM dbo.Conectores c
      JOIN dbo.Puntos p ON p.PuntoId=c.PuntoId
      WHERE p.UserId=:uid AND c.Activo=1
      ORDER BY p.PuntoId, c.Orden
    """, uid=session["uid"])

    results = []
    for c in conns:
        try:
            estado, hint = scrape_conector_estado(account_id, c["ConectorId"], c["UrlConector"])
            results.append({"conector_id": c["ConectorId"], "estado": estado, "hint": hint})
        except Exception as e:
            current_app.logger.error("refresh estado conector_id=%s: %s", c["ConectorId"], e, exc_info=True)
            results.append({"conector_id": c["ConectorId"], "estado": "Error", "hint": str(e)})

    return jsonify({"ok": True, "results": results})