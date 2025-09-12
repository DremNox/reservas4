import logging, json, os
from datetime import datetime, timezone
from .db import execute
import logging as stdlog


class DBHandler(logging.Handler):
    def emit(self, record):
        try:
            msg = self.format(record)
            user_id = getattr(record, "user_id", None)
            path = getattr(record, "path", None)
            extra_json = None
            if record.args and isinstance(record.args, dict):
                try:
                    extra_json = json.dumps(record.args, ensure_ascii=False)
                except Exception:
                    pass
            execute("""
                INSERT INTO dbo.LogsApp(Level, Module, Message, UserId, RequestPath, ExtraJson)
                VALUES (:lvl, :mod, :msg, :uid, :path, :extra)
            """,
            lvl=record.levelname,
            mod=record.name,
            msg=msg,
            uid=user_id,
            path=path,
            extra=extra_json)
        except Exception as e:
            # fallback a archivo local
            fallback = "/opt/reservas4/logs/app.log"
            os.makedirs(os.path.dirname(fallback), exist_ok=True)
            with open(fallback, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now(timezone.utc).isoformat()}] {record.levelname} {record.name}: {record.getMessage()}\n")

def setup_logging(app):
    handler = DBHandler()
    handler.setLevel(stdlog.INFO)
    formatter = stdlog.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handler.setFormatter(formatter)
    app.logger.addHandler(handler)
    app.logger.setLevel(stdlog.INFO)
