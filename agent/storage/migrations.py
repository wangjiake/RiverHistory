"""Simple file-based DB migration runner.

Tracks applied migrations in a `schema_version` table and runs unapplied
.sql files from the migrations/ directory in lexicographic order.

Usage:
    from agent.storage.migrations import migrate
    migrate()  # runs at startup
"""

import logging
import os

from ._db import get_db_connection

logger = logging.getLogger(__name__)

_MIGRATIONS_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "migrations",
)


def _ensure_schema_version_table(conn):
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                filename VARCHAR(255) PRIMARY KEY,
                applied_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
    conn.commit()


def _get_applied(conn) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT filename FROM schema_version")
        return {row[0] for row in cur.fetchall()}


def migrate():
    """Run all unapplied migrations from migrations/ directory."""
    migrations_dir = os.path.abspath(_MIGRATIONS_DIR)
    if not os.path.isdir(migrations_dir):
        logger.debug("No migrations directory at %s", migrations_dir)
        return

    sql_files = sorted(
        f for f in os.listdir(migrations_dir)
        if f.endswith(".sql")
    )
    if not sql_files:
        return

    conn = get_db_connection()
    try:
        _ensure_schema_version_table(conn)
        applied = _get_applied(conn)

        for filename in sql_files:
            if filename in applied:
                continue

            filepath = os.path.join(migrations_dir, filename)
            logger.info("Applying migration: %s", filename)
            with open(filepath, "r", encoding="utf-8") as f:
                sql = f.read()

            try:
                with conn.cursor() as cur:
                    cur.execute(sql)
                    cur.execute(
                        "INSERT INTO schema_version (filename) VALUES (%s)",
                        (filename,),
                    )
                conn.commit()
                logger.info("Migration applied: %s", filename)
            except Exception:
                conn.rollback()
                logger.error("Migration failed: %s", filename, exc_info=True)
                raise
    finally:
        conn.close()
