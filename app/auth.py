from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from passlib.hash import pbkdf2_sha256 as hasher
from .db import fetch_one

bp = Blueprint("auth", __name__, template_folder="../templates/auth")

@bp.get("/login")
def login_get():
    return render_template("auth/login.html")

@bp.post("/login")
def login_post():
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""

    row = fetch_one("""
        SELECT UserId, Username, PasswordHash, Role, IsActive
        FROM dbo.Usuarios
        WHERE Username = :u
    """, u=username)

    if not row or not row["IsActive"] or not hasher.verify(password, row["PasswordHash"]):
        flash("Usuario o contraseña no válidos", "error")
        return redirect(url_for("auth.login_get"))

    # Sesión muy simple (sin Flask-Login para mantenerlo mínimo)
    session["uid"] = int(row["UserId"])
    session["uname"] = row["Username"]
    session["role"] = row["Role"]

    return redirect(url_for("dash.estado"))

@bp.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login_get"))
