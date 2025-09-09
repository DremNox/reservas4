import os
from urllib.parse import quote_plus
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

_engine: Engine | None = None

def get_engine() -> Engine:
    global _engine
    if _engine is not None:
        return _engine

    driver = os.getenv("ODBC_DRIVER", "ODBC Driver 18 for SQL Server")
    host = os.getenv("SQLSERVER_HOST", "orion")
    db   = os.getenv("SQLSERVER_DATABASE", "reservas3")
    user = os.getenv("SQLSERVER_USER")
    pwd  = os.getenv("SQLSERVER_PASSWORD")

    encrypt = os.getenv("SQL_ENCRYPT", "yes")
    trust   = os.getenv("SQL_TRUST_CERT", "yes")

    assert user and pwd, "Faltan credenciales SQL en variables de entorno"

    conn_str = (
        f"mssql+pyodbc://{quote_plus(user)}:{quote_plus(pwd)}@{quote_plus(host)}/"
        f"{quote_plus(db)}"
        f"?driver={quote_plus(driver)}&Encrypt={encrypt}&TrustServerCertificate={trust}"
    )

    _engine = create_engine(conn_str, pool_pre_ping=True, fast_executemany=True)
    return _engine

def fetch_one(sql: str, **params):
    with get_engine().begin() as conn:
        return conn.execute(text(sql), params).mappings().first()

def fetch_all(sql: str, **params):
    with get_engine().begin() as conn:
        return conn.execute(text(sql), params).mappings().all()

def execute(sql: str, **params):
    with get_engine().begin() as conn:
        conn.execute(text(sql), params)
