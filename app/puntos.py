# app/puntos.py
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, abort, current_app
from .db import fetch_all, fetch_one, execute
from .estado import scrape_conector_estado
from flask import jsonify

bp = Blueprint("puntos", __name__, template_folder="../templates")

def _require_login():
    if not session.get("uid"):
        abort(401)

@bp.get("/dashboard/puntos")
def puntos_list():
    _require_login()
    puntos = fetch_all("""
        SELECT p.PuntoId, p.Nombre, p.Notas,
               (SELECT COUNT(*) FROM dbo.Conectores c WHERE c.PuntoId=p.PuntoId) AS NumConectores
        FROM dbo.Puntos p
        WHERE p.UserId=:uid
        ORDER BY p.PuntoId DESC
    """, uid=session["uid"])
    return render_template("dashboard/puntos.html", puntos=puntos)

@bp.post("/dashboard/puntos/add")
def puntos_add():
    _require_login()
    nombre = (request.form.get("nombre") or "").strip()
    notas  = (request.form.get("notas") or "").strip()
    if not nombre:
        flash("El nombre del punto es obligatorio", "error")
        return redirect(url_for("puntos.puntos_list"))
    execute("""
        INSERT INTO dbo.Puntos (UserId, Nombre, Notas) VALUES (:uid, :n, :no)
    """, uid=session["uid"], n=nombre, no=notas)
    current_app.logger.info("Punto creado: %s", nombre)
    flash("Punto creado.", "success")
    return redirect(url_for("puntos.puntos_list"))

@bp.get("/dashboard/puntos/<int:punto_id>")
def punto_detail(punto_id: int):
    _require_login()
    p = fetch_one("""
        SELECT PuntoId, Nombre, Notas
        FROM dbo.Puntos WHERE PuntoId=:id AND UserId=:uid
    """, id=punto_id, uid=session["uid"])
    if not p:
        abort(404)
    conectores = fetch_all("""
        SELECT ConectorId, Nombre, Tipo, UrlConector, Orden, Activo
        FROM dbo.Conectores
        WHERE PuntoId=:pid
        ORDER BY Orden, ConectorId
    """, pid=punto_id)
    # Estado actual (si ya tienes la vista creada)
    estados = fetch_all("""
        SELECT e.ConectorId, e.Estado, e.CapturedAtUtc
        FROM dbo.V_ConectorEstadoActual e
        WHERE e.ConectorId IN (SELECT ConectorId FROM dbo.Conectores WHERE PuntoId=:pid)
    """, pid=punto_id)
    estado_map = {e["ConectorId"]: e for e in estados}
    return render_template("dashboard/punto_detail.html", p=p, conectores=conectores, estado_map=estado_map)

@bp.post("/dashboard/puntos/<int:punto_id>/conectores/add")
def conector_add(punto_id: int):
    _require_login()
    # validar punto
    exists = fetch_one("SELECT 1 AS ok FROM dbo.Puntos WHERE PuntoId=:id AND UserId=:uid", id=punto_id, uid=session["uid"])
    if not exists:
        abort(404)

    nombre = (request.form.get("nombre") or "").strip()
    url    = (request.form.get("url") or "").strip()
    tipo   = (request.form.get("tipo") or "").strip() or None
    orden  = int(request.form.get("orden") or 1)

    if not nombre or not url:
        flash("Nombre y URL del conector son obligatorios", "error")
        return redirect(url_for("puntos.punto_detail", punto_id=punto_id))

    execute("""
        INSERT INTO dbo.Conectores (PuntoId, Nombre, Tipo, UrlConector, Orden, Activo)
        VALUES (:pid, :n, :t, :u, :o, 1)
    """, pid=punto_id, n=nombre, t=tipo, u=url, o=orden)

    current_app.logger.info("Conector añadido: punto_id=%s nombre=%s", punto_id, nombre)
    flash("Conector añadido.", "success")
    return redirect(url_for("puntos.punto_detail", punto_id=punto_id))

@bp.post("/dashboard/puntos/<int:punto_id>/conectores/<int:conector_id>/toggle")
def conector_toggle(punto_id: int, conector_id: int):
    _require_login()
    c = fetch_one("""
        SELECT c.ConectorId, c.Activo
        FROM dbo.Conectores c
        JOIN dbo.Puntos p ON p.PuntoId=c.PuntoId AND p.UserId=:uid
        WHERE c.ConectorId=:cid AND p.PuntoId=:pid
    """, cid=conector_id, pid=punto_id, uid=session["uid"])
    if not c:
        abort(404)
    new = 0 if c["Activo"] else 1
    execute("UPDATE dbo.Conectores SET Activo=:a WHERE ConectorId=:cid", a=new, cid=conector_id)
    flash("Conector " + ("activado" if new else "desactivado") + ".", "success")
    return redirect(url_for("puntos.punto_detail", punto_id=punto_id))

@bp.post("/dashboard/puntos/<int:punto_id>/refresh")
def punto_refresh(punto_id: int):
    _require_login()
    # validar punto del usuario
    p = fetch_one("SELECT PuntoId FROM dbo.Puntos WHERE PuntoId=:id AND UserId=:uid",
                  id=punto_id, uid=session["uid"])
    if not p: abort(404)

    acc = fetch_all("""
      SELECT a.AccountId
      FROM dbo.CuentasPTP a
      JOIN dbo.CredencialesPTP c ON c.AccountId=a.AccountId
      WHERE a.UserId=:uid
      ORDER BY a.AccountId ASC
    """, uid=session["uid"])
    if not acc:
      return jsonify({"ok": False, "error": "Configura tu cuenta PTP primero."}), 400
    account_id = acc[0]["AccountId"]

    conns = fetch_all("""
      SELECT ConectorId, UrlConector
      FROM dbo.Conectores
      WHERE PuntoId=:pid AND Activo=1
      ORDER BY Orden, ConectorId
    """, pid=punto_id)

    results = []
    for c in conns:
        try:
            estado, hint = scrape_conector_estado(account_id, c["ConectorId"], c["UrlConector"])
            results.append({"conector_id": c["ConectorId"], "estado": estado, "hint": hint})
        except Exception as e:
            results.append({"conector_id": c["ConectorId"], "estado": "Error", "hint": str(e)})

    return jsonify({ "ok": True, "count": len(results), "results": results })
