# app/reservas.py
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, abort,current_app
from .db import fetch_all, fetch_one, execute

bp = Blueprint("resv", __name__)

def _require_login():
    if not session.get("uid"):
        abort(401)

@bp.get("/dashboard/reservar")
def reservar_get():
    _require_login()
    current_app.logger.info("Vista reservar (sets) abierta")
    sets = fetch_all("""
        SELECT s.SetId, s.Nombre, s.TomaPreferida, s.VentanaCambioMin, s.Activo,
               (SELECT COUNT(1) FROM dbo.ConjuntoItems i WHERE i.SetId = s.SetId) AS NumItems
        FROM dbo.ConjuntosVigilancia s
        WHERE s.UserId = :uid
        ORDER BY s.SetId DESC
    """, uid=session["uid"])
    return render_template("dashboard/reservar.html", sets=sets)

@bp.post("/dashboard/reservar/set/create")
def reservar_set_create():
    _require_login()
    nombre = (request.form.get("nombre") or "").strip()
    toma = (request.form.get("toma") or "A").strip().upper()
    ventana = int(request.form.get("ventana") or 5)
    activo = 1 if (request.form.get("activo") == "1") else 0
    if toma not in ("A","B"):
        toma = "A"
    if not nombre:
        flash("El nombre del conjunto es obligatorio", "error")
        return redirect(url_for("resv.reservar_get"))
    execute("""
        INSERT INTO dbo.ConjuntosVigilancia (UserId, Nombre, TomaPreferida, VentanaCambioMin, Activo)
        VALUES (:uid, :n, :t, :v, :a)
    """, uid=session["uid"], n=nombre, t=toma, v=ventana, a=activo)
    current_app.logger.info("Set creado: nombre=%s toma=%s ventana=%s activo=%s", nombre, toma, ventana, activo,
                            extra={"extra_dict":{"action":"set_create"}})
    flash("Conjunto creado.", "success")
    return redirect(url_for("resv.reservar_get"))

@bp.get("/dashboard/reservar/set/<int:setid>")
def reservar_set_detail(setid: int):
    _require_login()
    s = fetch_one("""
        SELECT SetId, Nombre, TomaPreferida, VentanaCambioMin, Activo
        FROM dbo.ConjuntosVigilancia WHERE SetId=:id AND UserId=:uid
    """, id=setid, uid=session["uid"])
    if not s:
        current_app.logger.warning("Set detail 404: setid=%s", setid)
        abort(404)
    current_app.logger.info("Set abierto: setid=%s", setid)
    items = fetch_all("""
        SELECT SetItemId, ExternalIdPTP, Prioridad, PreferredSocket, Notas
        FROM dbo.ConjuntoItems WHERE SetId=:id ORDER BY Prioridad ASC, SetItemId ASC
    """, id=setid)
    return render_template("dashboard/reservar_set.html", s=s, items=items)

@bp.post("/dashboard/reservar/set/<int:setid>/item/add")
def reservar_set_item_add(setid: int):
    _require_login()
    s = fetch_one("SELECT SetId FROM dbo.ConjuntosVigilancia WHERE SetId=:id AND UserId=:uid",
                  id=setid, uid=session["uid"])
    if not s: abort(404)
    slug_or_url = (request.form.get("slug") or "").strip()
    prio = int(request.form.get("prioridad") or 1)
    psock = (request.form.get("socket") or "").strip().upper() or None
    notas = (request.form.get("notas") or "").strip() or None
    # Normalización simple: si es URL, quédate con el último segmento como slug
    ext = slug_or_url
    if "placetoplug.com" in ext:
        parts = [p for p in ext.split("/") if p]
        ext = parts[-1]
    execute("""
        INSERT INTO dbo.ConjuntoItems (SetId, ExternalIdPTP, Prioridad, PreferredSocket, Notas)
        VALUES (:sid, :ext, :prio, :ps, :n)
    """, sid=setid, ext=ext, prio=prio, ps=psock, n=notas)
    current_app.logger.info("Item añadido: setid=%s ext=%s prio=%s socket=%s", setid, ext, prio, psock,
                            extra={"extra_dict":{"action":"item_add"}})
    flash("Punto añadido al conjunto.", "success")
    return redirect(url_for("resv.reservar_set_detail", setid=setid))

@bp.post("/dashboard/reservar/set/<int:setid>/toggle")
def reservar_set_toggle(setid: int):
    _require_login()
    s = fetch_one("SELECT SetId, Activo FROM dbo.ConjuntosVigilancia WHERE SetId=:id AND UserId=:uid",
                  id=setid, uid=session["uid"])
    if not s: 
        current_app.logger.warning("Toggle 404: setid=%s", setid)
        abort(404)
    new = 0 if s["Activo"] else 1
    execute("UPDATE dbo.ConjuntosVigilancia SET Activo=:a WHERE SetId=:id", a=new, id=setid)
    # Upsert de Job watch
    if new:
        execute("""
            MERGE dbo.JobsProgramados AS t
            USING (SELECT :uid AS UserId, :sid AS SetId) AS s
            ON t.Tipo=N'watch' AND JSON_VALUE(t.PayloadJson,'$.SetId') = CAST(s.SetId AS NVARCHAR(20))
            WHEN MATCHED THEN UPDATE SET Activo=1
            WHEN NOT MATCHED THEN
                INSERT (UserId, Tipo, CronExpr, PayloadJson, Activo)
                VALUES (s.UserId, N'watch', N'@every 60s', JSON_OBJECT('SetId': s.SetId), 1);
        """, uid=session["uid"], sid=setid)
        current_app.logger.info("Set activado: setid=%s", setid, extra={"extra_dict":{"action":"set_enable"}})
    else:
        execute("""
            UPDATE dbo.JobsProgramados
            SET Activo=0
            WHERE Tipo=N'watch' AND JSON_VALUE(PayloadJson,'$.SetId') = CAST(:sid AS NVARCHAR(20))
        """, sid=setid)
        current_app.logger.info("Set desactivado: setid=%s", setid, extra={"extra_dict":{"action":"set_disable"}})
    flash("Conjunto " + ("activado" if new else "desactivado") + ".", "success")
    return redirect(url_for("resv.reservar_set_detail", setid=setid))
