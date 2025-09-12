import logging, json, os
from datetime import datetime, timezone

# Evitamos import circular: importamos dentro de los métodos
# from .db import execute
# from flask import has_request_context, request, session

class RequestContextFilter(logging.Filter):
    """Inyecta user_id y path si hay request activo."""
    def filter(self, record):
        try:
            from flask import has_request_context, request, session
            if has_request_context():
                record.user_id = session.get("uid")
                record.path = getattr(request, "path", None)
            else:
                # fuera de Flask (workers, scripts)
                if not hasattr(record, "user_id"):
                    record.user_id = None
                if not hasattr(record, "path"):
                    record.path = None
        except Exception:
            if not hasattr(record, "user_id"):
                record.user_id = None
            if not hasattr(record, "path"):
                record.path = None
        return True

class DBHandler(logging.Handler):
    """Intenta escribir en dbo.LogsApp; si falla, usa archivo local."""
    def emit(self, record):
        try:
            msg = record.getMessage()
            level = record.levelname
            module = record.name
            user_id = getattr(record, "user_id", None)
            path = getattr(record, "path", None)

            extra_json = None
            # Si se pasó un dict por 'extra={"data": ...}' lo serializamos
            if hasattr(record, "extra_dict"):
                try:
                    extra_json = json.dumps(record.extra_dict, ensure_ascii=False)
                except Exception:
                    extra_json = None

            from .db import execute
            execute("""
                INSERT INTO dbo.LogsApp(Level, Module, Message, UserId, RequestPath, ExtraJson)
                VALUES (:lvl, :mod, :msg, :uid, :path, :extra)
            """, lvl=level, mod=module, msg=msg, uid=user_id, path=path, extra=extra_json)

        except Exception:
            try:
                # Fallback local
                fallback = "/opt/reservas4/logs/app.log"
                os.makedirs(os.path.dirname(fallback), exist_ok=True)
                with open(fallback, "a", encoding="utf-8") as f:
                    ts = datetime.now(timezone.utc).isoformat()
                    f.write(f"[{ts}] {record.levelname} {record.name} uid={getattr(record,'user_id',None)} path={getattr(record,'path',None)}: {record.getMessage()}\n")
            except Exception:
                # último recurso: ignorar
                pass

def setup_logging(app):
    """Adjunta handler de BD con filtro de contexto a app.logger"""
    handler = DBHandler()
    handler.setLevel(logging.INFO)
    handler.addFilter(RequestContextFilter())
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handler.setFormatter(fmt)

    app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)

    # Log de acceso mínimo
    @app.after_request
    def _after(resp):
        # Evita llenar la tabla con /healthz
        if getattr(resp, "status_code", 200) >= 400:
            app.logger.warning("HTTP %s en %s", resp.status_code, getattr(resp, "direct_passthrough", False), extra={"extra_dict":{"status": resp.status_code}})
        return resp
