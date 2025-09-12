# app/utils/ptp_cookies.py
from typing import List, Dict
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.webdriver import WebDriver
from selenium.webdriver.support.ui import WebDriverWait as W
from selenium.webdriver.support import expected_conditions as EC
from ..db import fetch_all

def get_current_cookies(account_id: int) -> List[Dict]:
    rows = fetch_all("""
      SELECT Name, Value, Domain, Path, ExpiryUtc, Secure, HttpOnly, SameSite
      FROM dbo.CookiesPTP
      WHERE AccountId=:aid AND IsCurrent=1 AND IsValid=1
    """, aid=account_id)
    cookies = []
    for r in rows:
        c = {
            "name": r["Name"], "value": r["Value"],
            "domain": r["Domain"] or "placetoplug.com",
            "path": r["Path"] or "/",
            "secure": bool(r["Secure"]), "httpOnly": bool(r["HttpOnly"])
        }
        cookies.append(c)
    return cookies

def prime_cookies(driver: WebDriver, cookies: List[Dict]):
    """Añade cookies para dominios relevantes."""
    domains = ["placetoplug.com", "account.placetoplug.com"]
    for dom in domains:
        driver.get(f"https://{dom}/")
        for c in cookies:
            cd = c.copy()
            # Selenium requiere que el dominio coincida con el host actual
            if cd.get("domain") and dom.endswith(cd["domain"].lstrip(".")):
                cd.pop("sameSite", None)
                cd.pop("httpOnly", None)  # Selenium usa 'httpOnly' internamente; si da problemas, se quita
                try:
                    driver.add_cookie(cd)
                except Exception:
                    pass
