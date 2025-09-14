# app/admin.py
from flask import Blueprint, render_template, session, abort

bp = Blueprint("admin", __name__)

def _require_admin():
    if not session.get("uid") or session.get("role") != "admin":
        abort(403)

@bp.get("/admin")
def admin_home():
    _require_admin()
    return render_template("admin/index.html")
