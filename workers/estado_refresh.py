import os
from app.db import fetch_all
from app.estado import scrape_conector_estado
import logging
from app.logging import DBHandler, RequestContextFilter

logger = logging.getLogger("estado_refresh")
h = DBHandler(); h.addFilter(RequestContextFilter()); h.setLevel(logging.INFO)
logger.addHandler(h); logger.setLevel(logging.INFO)

def main():
    # recorre todos los usuarios con cuenta PTP
    users = fetch_all("""
      SELECT DISTINCT a.UserId, a.AccountId
      FROM dbo.CuentasPTP a
      JOIN dbo.CredencialesPTP c ON c.AccountId=a.AccountId
    """)
    for u in users:
        account_id = u["AccountId"]
        conns = fetch_all("""
          SELECT c.ConectorId, c.UrlConector
          FROM dbo.Conectores c
          JOIN dbo.Puntos p ON p.PuntoId=c.PuntoId
          WHERE p.UserId=:uid AND c.Activo=1
          ORDER BY p.PuntoId, c.Orden, c.ConectorId
        """, uid=u["UserId"])
        for c in conns:
            try:
                scrape_conector_estado(account_id, c["ConectorId"], c["UrlConector"])
            except Exception as e:
                logger.error("estado_refresh error conector_id=%s: %s", c["ConectorId"], e, exc_info=True)

if __name__ == "__main__":
    main()
