import os
import time
from datetime import datetime, timezone
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from .db import fetch_one, fetch_all, execute
from .utils.crypto import encrypt_str, decrypt_str

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

PTP_LOGIN_URL = "https://account.placetoplug.com/es/entrar?from=placetoplug.com%2Fes"
SEL_WAIT = int(os.getenv("SELENIUM_WAIT_TIMEOUT", "30"))
SEL_PAGELOAD = int(os.getenv("SELENIUM_PAGELOAD_TIMEOUT", "60"))

bp = Blueprint("ptp", __name__, template_folder="../templates/account")

def _require_login():
    if not session.get("uid"):
        from flask import abort
        abort(401)

@bp.get("/ptp")
def ptp_get():
    _require_login()
    account = fetch_one("""
        SELECT a.AccountId, a.EmailPTP, c.Algorithm, c.UpdatedAt
        FROM dbo.CuentasPTP a
        LEFT JOIN dbo.CredencialesPTP c ON c.AccountId = a.AccountId
        WHERE a.UserId = :uid
    """, uid=session["uid"])
    return render_template("account/ptp.html", account=account)

@bp.post("/ptp/save")
def ptp_save():
    _require_login()
    email = (request.form.get("email") or "").strip()
    password = request.form.get("password") or ""
    if not email or not password:
        flash("Email y contraseña PTP son obligatorios", "error")
        return redirect(url_for("ptp.ptp_get"))

    # Crear/obtener account
    acc = fetch_one("SELECT AccountId FROM dbo.CuentasPTP WHERE UserId=:uid AND EmailPTP=:e",
                    uid=session["uid"], e=email)
    if not acc:
        execute("""
            INSERT INTO dbo.CuentasPTP (UserId, EmailPTP)
            VALUES (:uid, :e)
        """, uid=session["uid"], e=email)
        acc = fetch_one("SELECT AccountId FROM dbo.CuentasPTP WHERE UserId=:uid AND EmailPTP=:e",
                        uid=session["uid"], e=email)

    # Guardar credencial cifrada
    execute("""
        MERGE dbo.CredencialesPTP AS t
        USING (SELECT :acc AS AccountId) AS s
        ON t.AccountId = s.AccountId
        WHEN MATCHED THEN UPDATE SET PasswordEnc=:p, Algorithm=N'fernet-v1', UpdatedAt=SYSUTCDATETIME()
        WHEN NOT MATCHED THEN INSERT (AccountId, PasswordEnc, Algorithm)
             VALUES (s.AccountId, :p, N'fernet-v1');
    """, acc=acc["AccountId"], p=encrypt_str(password))

    flash("Cuenta PTP guardada en BD (password cifrada).", "success")
    return redirect(url_for("ptp.ptp_get"))

@bp.post("/ptp/refresh-now")
def ptp_refresh_now():
    _require_login()
    account = fetch_one("""
        SELECT a.AccountId, a.EmailPTP, c.PasswordEnc
        FROM dbo.CuentasPTP a
        JOIN dbo.CredencialesPTP c ON c.AccountId = a.AccountId
        WHERE a.UserId=:uid
    """, uid=session["uid"])

    if not account:
        flash("Primero guarda tu cuenta PTP (email + password).", "error")
        return redirect(url_for("ptp.ptp_get"))

    email = account["EmailPTP"]
    password = decrypt_str(account["PasswordEnc"])

    total, auth_cookie = _selenium_login_and_store_cookies(account["AccountId"], email, password)
    if total > 0:
        flash(f"Cookies guardadas: {total}. auth_token={'OK' if auth_cookie else 'NO'}", "success")
    else:
        flash("No se guardaron cookies.", "error")

    return redirect(url_for("ptp.ptp_get"))

def _make_driver():
    browser = (os.getenv("SELENIUM_BROWSER") or "auto").lower()
    headless = os.getenv("SELENIUM_HEADLESS", "1") == "1"

    def try_chrome():
        from selenium.webdriver.chrome.options import Options as ChromeOptions
        opts = ChromeOptions()
        if headless:
            opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--window-size=1280,1024")
        return webdriver.Chrome(options=opts)

    def try_firefox():
        from selenium.webdriver.firefox.options import Options as FFOptions
        opts = FFOptions()
        if headless:
            opts.add_argument("-headless")
        return webdriver.Firefox(options=opts)

    if browser in ("auto", "chrome"):
        try:
            return try_chrome()
        except Exception:
            if browser == "chrome":
                raise
    # fallback
    return try_firefox()

def _selenium_login_and_store_cookies(account_id: int, email: str, password: str):
    """Hace login en PTP y almacena TODAS las cookies en dbo.CookiesPTP con IsCurrent=1."""
    driver = _make_driver()
    driver.set_page_load_timeout(SEL_PAGELOAD)
    wait = WebDriverWait(driver, SEL_WAIT)
    total_saved = 0
    has_auth = False
    try:
        driver.get(PTP_LOGIN_URL)
        # Email
        email_input = wait.until(EC.presence_of_element_located((By.XPATH, "//input[@placeholder='Email']")))
        email_input.clear()
        email_input.send_keys(email)

        # Botón siguiente (email)
        btn_next_email = driver.find_element(By.XPATH, "//div[@class='outlet']//div[1]//div[2]//button[1]")
        btn_next_email.click()

        # Password
        pwd_input = wait.until(EC.presence_of_element_located((By.XPATH, "//input[@placeholder='Contraseña']")))
        pwd_input.clear()
        pwd_input.send_keys(password)

        # Botón entrar (password)
        btn_next_pwd = wait.until(EC.element_to_be_clickable((By.XPATH, "//body//app-root//div[2]//div[2]//button[1]")))
        btn_next_pwd.click()

        # Espera a redirección/estado logueado
        # Tip: abrir placetoplug.com para asegurar que el dominio de cookies es correcto
        wait.until(lambda d: "account.placetoplug.com" in d.current_url or "placetoplug.com" in d.current_url)
        driver.get("https://placetoplug.com/es")
        time.sleep(2)

        # Recoger cookies
        cookies = driver.get_cookies()  # [{'name','value','domain','path','expiry','httpOnly','secure','sameSite'...}]
        for c in cookies:
            name = c.get("name")
            value = c.get("value")
            domain = c.get("domain") or "placetoplug.com"
            path = c.get("path") or "/"
            expiry = c.get("expiry")  # epoch seconds
            httpOnly = bool(c.get("httpOnly"))
            secure = bool(c.get("secure"))
            sameSite = c.get("sameSite")

            expiry_dt = None
            if isinstance(expiry, (int, float)):
                expiry_dt = datetime.fromtimestamp(int(expiry), tz=timezone.utc)

            # invalidar vigentes anteriores de la misma cookie
            execute("""
                UPDATE dbo.CookiesPTP
                SET IsCurrent = 0, IsValid = 0
                WHERE AccountId=:aid AND Name=:n AND Domain=:d AND Path=:p AND IsCurrent=1
            """, aid=account_id, n=name, d=domain, p=path)

            # insertar nueva vigente
            execute("""
                INSERT INTO dbo.CookiesPTP
                (AccountId, Name, Value, Domain, Path, ExpiryUtc, Secure, HttpOnly, SameSite,
                 LastLoginUtc, LastRefreshUtc, IsValid, IsCurrent)
                VALUES
                (:aid, :n, :v, :d, :p, :exp, :sec, :httponly, :ss, SYSUTCDATETIME(), SYSUTCDATETIME(), 1, 1)
            """, aid=account_id, n=name, v=value, d=domain, p=path, exp=expiry_dt,
                 sec=1 if secure else 0, httponly=1 if httpOnly else 0, ss=sameSite)

            total_saved += 1
            if name.lower() == "auth_token" and value:
                has_auth = True

        return total_saved, has_auth

    finally:
        driver.quit()
