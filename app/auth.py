from flask import Blueprint, render_template, request, redirect, url_for, flash, session,current_app
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
        current_app.logger.warning("Login fallido para '%s'", username, extra={"extra_dict":{"reason":"invalid_credentials"}})
        flash("Usuario o contraseña no válidos", "error")
        return redirect(url_for("auth.login_get"))

    # Sesión muy simple
    session["uid"] = int(row["UserId"])
    session["uname"] = row["Username"]
    session["role"] = row["Role"]

    # 👇 Aquí añadimos soporte para ?next= o hidden input
    current_app.logger.info("Login OK de '%s' (uid=%s, role=%s)", row["Username"], row["UserId"], row["Role"])

    next_url = request.args.get("next") or request.form.get("next") or url_for("dash.estado")
    return redirect(next_url)


@bp.get("/logout")
def logout():
    session.clear()
    current_app.logger.info("Logout de uid=%s uname=%s", uid, uname)
    return redirect(url_for("auth.login_get"))
