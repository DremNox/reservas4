import os, time, json, logging
from datetime import datetime, timezone
from app.logging import DBHandler, RequestContextFilter  # reutilizamos
from app.db import fetch_all

INTERVAL = int(os.getenv("WORKER_INTERVAL_SEC", "60"))

logger = logging.getLogger("workers")
handler = DBHandler()
handler.setLevel(logging.INFO)
handler.addFilter(RequestContextFilter())   # inyecta user_id/path = None en workers
logger.addHandler(handler)
logger.setLevel(logging.INFO)

def main():
    logger.info("worker iniciado", extra={"extra_dict":{"interval_sec": INTERVAL}})
    print("[worker] iniciado, interval:", INTERVAL, "s")
    
    while True:
        try:
            jobs = fetch_all("""
                SELECT JobId, UserId, PayloadJson
                FROM dbo.JobsProgramados
                WHERE Tipo=N'watch' AND Activo=1
            """)
            for j in jobs:
                payload = j["PayloadJson"] or "{}"
                try:
                    data = json.loads(payload)
                except Exception:
                    data = {}
                set_id = data.get("SetId")
                if not set_id:
                    logger.warning("Job con payload inválido", extra={"extra_dict":{"job_id": j["JobId"]}})
                    continue
                logger.info("watch tick", extra={"extra_dict":{"set_id": set_id, "job_id": j["JobId"]}})
                # Aquí haremos: leer items del set, scrape de estados, y si hay toma libre -> reservar.
                print(f"[worker] {datetime.now(timezone.utc).isoformat()} watch SetId={set_id} (stub)")
        except Exception as e:
            logger.error("worker error: %s", e, exc_info=True)
            print("[worker] error:", e)
        time.sleep(INTERVAL)

if __name__ == "__main__":
    main()
