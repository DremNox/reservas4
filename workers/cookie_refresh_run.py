import os
from datetime import datetime, timezone, timedelta
from app.db import fetch_all, fetch_one
from app.ptp import selenium_login_and_store_cookies
from app.utils.crypto import decrypt_str

def due_accounts():
    # Buscar cookies "vigentes" que vencen en <= 24h por AccountId
    rows = fetch_all("""
    SELECT DISTINCT a.AccountId, a.EmailPTP, c.PasswordEnc
    FROM dbo.CuentasPTP a
    JOIN dbo.CredencialesPTP c ON c.AccountId=a.AccountId
    LEFT JOIN dbo.CookiesPTP k ON k.AccountId=a.AccountId AND k.IsCurrent=1 AND k.Name=N'auth_token'
    WHERE (k.ExpiryUtc IS NULL OR k.ExpiryUtc <= DATEADD(hour, 24, SYSUTCDATETIME()))
    """)
    return rows

def main():
    for r in due_accounts():
        pwd = decrypt_str(r["PasswordEnc"])
        print(f"[cookie-refresh] Renovando AccountId={r['AccountId']} ({r['EmailPTP']})...")
        total, ok = selenium_login_and_store_cookies(r["AccountId"], r["EmailPTP"], pwd)
        print(f"[cookie-refresh] Guardadas={total} auth_token={'OK' if ok else 'NO'}")

if __name__ == "__main__":
    main()
