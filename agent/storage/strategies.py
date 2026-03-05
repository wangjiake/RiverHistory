"""Strategy storage."""

from datetime import datetime, timedelta
from ._db import get_db_connection


def save_strategy(hypothesis_category: str, hypothesis_subject: str,
                  strategy_type: str, description: str,
                  trigger_condition: str, approach: str,
                  priority: float = 0.5, expires_days: int = 30,
                  reference_time=None):
    now = reference_time if reference_time else datetime.now()
    expires_at = now + timedelta(days=expires_days) if expires_days > 0 else None
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM strategies "
                "WHERE hypothesis_category = %s AND hypothesis_subject = %s "
                "AND strategy_type = %s AND status = 'pending'",
                (hypothesis_category, hypothesis_subject, strategy_type),
            )
            if cur.fetchone():
                return False

            cur.execute("SELECT COUNT(*) FROM strategies WHERE status = 'pending'")
            if cur.fetchone()[0] >= 30:
                return False

            cur.execute(
                "INSERT INTO strategies "
                "(hypothesis_category, hypothesis_subject, strategy_type, description, "
                " trigger_condition, approach, priority, status, created_at, expires_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending', %s, %s)",
                (hypothesis_category, hypothesis_subject, strategy_type, description,
                 trigger_condition, approach, priority, now, expires_at),
            )
        conn.commit()
        return True
    finally:
        conn.close()
