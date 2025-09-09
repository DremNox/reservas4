# app/ptp.py
import os
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, current_app
from flask import abort

from .db import fetch_one, fetch_all, execute
from .utils.crypto import encrypt_str, decrypt_str

# --- Selenium ---
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    ElementNotInteractableException,
)

bp = Blueprint("ptp", __name__)  # usamos la carpeta global "templates/"

# ------------------- CONFIG / CONSTANTES -------------------
HEADLESS = os.getenv("SELENIUM_HEADLESS", "1") == "1"
PAGELOAD_TIMEOUT = int(os.getenv("SELENIUM_PAGELOAD_TIMEOUT", "60"))
EXPLICIT_WAIT = int(os.getenv("SELENIUM_WAIT_TIMEOUT", "30"))
IMPLICIT_WAIT = int(os.getenv("SELENIUM_IMPLICIT_WAIT", "5"))

PTP_LOGIN_URL = "https://account.placetoplug.com/es/entrar?from=placetoplug.com%2Fes"

# XPaths que nos pasaste
X_EMAIL = "//input[@placeholder='Email']"
X_BTN_SIGUIENTE_EMAIL = "//div[@class='outlet']//div[1]//div[2]//button[1]"
X_PASSWORD = "//input[@placeholder='Contraseña']"
X_BTN_SIGUIENTE_PASS = "//body//app-root//div[2]//div[2]//button[1]"

# Rutas útiles para dumps/screenshot de depuración
LOGS_DIR = Path("/opt/reservas4/logs")
LOGS_DIR.mkdir(parents=True, exist_ok=True)
COOKIES_JSON_PATH = LOGS_DIR / "ptp_cookies_dump.json"


# ------------------- HELPERS WEB -------------------
def _require_login():
    if not session.get("uid"):
        abort(401)


# ------------------- UTILIDADES SELENIUM -------------------
def create_driver(headless: bool = HEADLESS) -> webdriver.Chrome:
    """Crea un driver de Chrome con/ sin interfaz usando selenium-manager."""
    chrome_options = ChromeOptions()
    if headless:
        chrome_options.add_argument("--headless=new")  # headless moderno
    # Recomendados en servidores
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    # Ventana razonable para evitar layouts móviles / overlays
    chrome_options.add_argument("--window-size=1200,900")

    driver = webdriver.Chrome(service=ChromeService(), options=chrome_options)
    driver.set_page_load_timeout(PAGELOAD_TIMEOUT)
    driver.implicitly_wait(IMPLICIT_WAIT)
    return driver


def wait_clickable(driver, xpath: str, timeout: int = EXPLICIT_WAIT):
    return WebDriverWait(driver, timeout).until(EC.element_to_be_clickable((By.XPATH, xpath)))


def wait_visible(driver, xpath: str, timeout: int = EXPLICIT_WAIT):
    return WebDriverWait(driver, timeout).until(EC.visibility_of_element_located((By.XPATH, xpath)))


def dump_cookies(driver) -> List[Dict[str, Any]]:
    """Convierte cookies Selenium -> lista JSON serializable (estándar)."""
    raw = driver.get_cookies()
    cookies: List[Dict[str, Any]] = []
    for c in raw:
        cookies.append({
            "name": c.get("name"),
            "value": c.get("value"),
            "domain": c.get("domain"),
            "path": c.get("path"),
            "expiry": c.get("expiry"),        # epoch segs o None
            "secure": bool(c.get("secure", False)),
            "httpOnly": bool(c.get("httpOnly", False)),
            "sameSite": c.get("sameSite"),    # Lax/Strict/None o None
        })
    return cookies


def save_json(cookies: List[Dict[str, Any]], path: Path) -> None:
    path.write_text(json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8")


def maybe_accept_cookies_banner(driver):
    """Intenta aceptar banners de cookies comunes; ignora si no hay."""
    candidates = [
        "//button[contains(., 'Aceptar')]",
        "//button[contains(., 'Aceptar todas')]",
        "//button[contains(., 'Acepto')]",
        "//button[contains(., 'Consentir')]",
        "//*[@id='onetrust-accept-btn-handler']",
    ]
    for xp in candidates:
        try:
            btns = driver.find_elements(By.XPATH, xp)
            if btns:
                try:
                    btns[0].click()
                    time.sleep(0.5)
                    break
                except Exception:
                    pass
        except Exception:
            pass


# ------------------- FLUJO DE LOGIN PTP -------------------
def login_and_collect_cookies(email: str, password: str) -> List[Dict[str, Any]]:
    driver = create_driver(HEADLESS)
    try:
        # 1) Cargar página de login
        driver.get(PTP_LOGIN_URL)
        maybe_accept_cookies_banner(driver)

        # 2) Email
        email_box = wait_visible(driver, X_EMAIL)
        try:
            email_box.clear()
        except Exception:
            email_box.send_keys(Keys.CONTROL, "a")
            email_box.send_keys(Keys.DELETE)
        email_box.send_keys(email)

        btn_siguiente_email = wait_clickable(driver, X_BTN_SIGUIENTE_EMAIL)
        btn_siguiente_email.click()

        # 3) Password (tras “siguiente” del email)
        password_box = wait_visible(driver, X_PASSWORD)
        try:
            password_box.clear()
        except Exception:
            password_box.send_keys(Keys.CONTROL, "a")
            password_box.send_keys(Keys.DELETE)
        password_box.send_keys(password)

        btn_siguiente_pass = wait_clickable(driver, X_BTN_SIGUIENTE_PASS)
        btn_siguiente_pass.click()

        # 4) Esperar a “login hecho”: cookies de sesión o cambio de URL
        WebDriverWait(driver, EXPLICIT_WAIT).until(
            lambda d: ("session" in "".join([c["name"].lower() for c in d.get_cookies()]))
                      or d.current_url != PTP_LOGIN_URL
        )
        time.sleep(2)  # por si hay redirecciones extra

        # 5) Volcado de cookies
        cookies = dump_cookies(driver)
        # Debug opcional
        # save_json(cookies, COOKIES_JSON_PATH)
        return cookies

    except (TimeoutException, NoSuchElementException, ElementNotInteractableException) as e:
        ts = int(time.time())
        try:
            driver.save_screenshot(str(LOGS_DIR / f"login_error_{ts}.png"))
        except Exception:
            pass
        raise RuntimeError(f"Error durante login PTP: {e}") from e
    finally:
        driver.quit()


# ------------------- VISTAS -------------------
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
    try:
        enc = encrypt_str(password)  # VARBINARY(MAX)
    except Exception as e:
        current_app.logger.error("Error cifrando PTP: %s", e)
        flash("No se pudo cifrar la contraseña PTP. Revisa FERNET_KEY en .env.", "error")
        return redirect(url_for("ptp.ptp_get"))

    execute("""
        MERGE dbo.CredencialesPTP AS t
        USING (SELECT :acc AS AccountId) AS s
        ON t.AccountId = s.AccountId
        WHEN MATCHED THEN UPDATE SET PasswordEnc=:p, Algorithm=N'fernet-v1', UpdatedAt=SYSUTCDATETIME()
        WHEN NOT MATCHED THEN INSERT (AccountId, PasswordEnc, Algorithm)
             VALUES (s.AccountId, :p, N'fernet-v1');
    """, acc=acc["AccountId"], p=enc)

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

    try:
        cookies = login_and_collect_cookies(email, password)
    except Exception as e:
        current_app.logger.error("Selenium login error: %s", e)
        flash("Fallo al iniciar sesión en PlaceToPlug (ver logs).", "error")
        return redirect(url_for("ptp.ptp_get"))

    # Guardar cookies en BD: invalidar vigentes por (AccountId, Name, Domain, Path) y crear nuevas
    total_saved = 0
    has_auth = False
    for c in cookies:
        name = c.get("name")
        value = c.get("value")
        domain = c.get("domain") or "placetoplug.com"
        path = c.get("path") or "/"
        expiry = c.get("expiry")
        httpOnly = 1 if c.get("httpOnly") else 0
        secure = 1 if c.get("secure") else 0
        sameSite = c.get("sameSite")

        # Convertir expiry (epoch) -> datetime
        exp_dt = None
        if isinstance(expiry, (int, float)):
            exp_dt = datetime.fromtimestamp(int(expiry), tz=timezone.utc)

        # invalidar anteriores "vigentes"
        execute("""
            UPDATE dbo.CookiesPTP
            SET IsCurrent = 0, IsValid = 0
            WHERE AccountId=:aid AND Name=:n AND Domain=:d AND Path=:p AND IsCurrent=1
        """, aid=account["AccountId"], n=name, d=domain, p=path)

        # insertar nueva vigente
        execute("""
            INSERT INTO dbo.CookiesPTP
            (AccountId, Name, Value, Domain, Path, ExpiryUtc, Secure, HttpOnly, SameSite,
             LastLoginUtc, LastRefreshUtc, IsValid, IsCurrent)
            VALUES
            (:aid, :n, :v, :d, :p, :exp, :sec, :httponly, :ss, SYSUTCDATETIME(), SYSUTCDATETIME(), 1, 1)
        """, aid=account["AccountId"], n=name, v=value, d=domain, p=path, exp=exp_dt,
             sec=secure, httponly=httpOnly, ss=sameSite)

        total_saved += 1
        if name and name.lower() == "auth_token" and value:
            has_auth = True

    flash(f"Cookies guardadas: {total_saved}. auth_token={'OK' if has_auth else 'NO'}", "success")
    return redirect(url_for("ptp.ptp_get"))
