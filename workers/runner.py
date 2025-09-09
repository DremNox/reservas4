import os, time, json
from datetime import datetime, timezone
from app.db import fetch_all

INTERVAL = int(os.getenv("WORKER_INTERVAL_SEC", "60"))

def main():
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
                    continue
                # Aquí haremos: leer items del set, scrape de estados, y si hay toma libre -> reservar.
                print(f"[worker] {datetime.now(timezone.utc).isoformat()} watch SetId={set_id} (stub)")
        except Exception as e:
            print("[worker] error:", e)
        time.sleep(INTERVAL)

if __name__ == "__main__":
    main()
