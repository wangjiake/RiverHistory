"""Database connection and helpers."""

import psycopg2
from agent.config import load_config as _load_config

_cfg = _load_config()
_db_cfg = _cfg.get("database", {})

DB_CONFIG = {
    "dbname": _db_cfg.get("name", "Riverse"),
    "user": _db_cfg.get("user", "postgres"),
    "host": _db_cfg.get("host", "localhost"),
    "options": "-c client_encoding=UTF8",
}
if _db_cfg.get("password"):
    DB_CONFIG["password"] = _db_cfg["password"]
if _db_cfg.get("port"):
    DB_CONFIG["port"] = _db_cfg["port"]


def configure_db(name: str, user: str = "postgres", host: str = "localhost"):
    DB_CONFIG["dbname"] = name
    DB_CONFIG["user"] = user
    DB_CONFIG["host"] = host


def get_db_connection():
    conn = psycopg2.connect(**DB_CONFIG)
    return conn


def _as_dict(row):
    return dict(row) if row else None


def _as_dicts(rows):
    return [dict(r) for r in rows]
