"""Memory: conversation summaries, observation-subject lookups, snapshots."""

from ._db import get_db_connection, _as_dict, _as_dicts
from ._synonyms import _get_subject_synonyms
from psycopg2.extras import RealDictCursor


def load_conversation_summaries_around(pivot_time, limit_before=30, limit_after=50) -> dict:
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT ai_summary, intent, user_input_at, session_id "
                "FROM conversation_turns "
                "WHERE user_input_at < %s AND ai_summary IS NOT NULL "
                "ORDER BY user_input_at DESC LIMIT %s",
                (pivot_time, limit_before),
            )
            before = list(reversed(_as_dicts(cur.fetchall())))

            cur.execute(
                "SELECT ai_summary, intent, user_input_at, session_id "
                "FROM conversation_turns "
                "WHERE user_input_at >= %s AND ai_summary IS NOT NULL "
                "ORDER BY user_input_at ASC LIMIT %s",
                (pivot_time, limit_after),
            )
            after = _as_dicts(cur.fetchall())

        return {"before": before, "after": after}
    finally:
        conn.close()


def load_summaries_by_observation_subject(subject: str, pivot_time=None) -> dict:
    subject_syns = list(_get_subject_synonyms(subject))

    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT DISTINCT session_id FROM observations "
                "WHERE subject = ANY(%s) "
                "   OR subject ILIKE '%%' || %s || '%%' "
                "   OR %s ILIKE '%%' || subject || '%%'",
                (subject_syns, subject, subject),
            )
            session_ids = [r["session_id"] for r in cur.fetchall()]

            if not session_ids:
                return {"before": [], "after": []}

            cur.execute(
                "SELECT ai_summary, intent, user_input_at, session_id "
                "FROM conversation_turns "
                "WHERE session_id = ANY(%s) AND ai_summary IS NOT NULL "
                "ORDER BY user_input_at ASC",
                (session_ids,),
            )
            all_summaries = _as_dicts(cur.fetchall())
    finally:
        conn.close()

    if not pivot_time:
        return {"before": all_summaries, "after": []}

    before, after = [], []
    for s in all_summaries:
        s_time = s.get("user_input_at")
        if not s_time:
            before.append(s)
            continue
        s_naive = s_time.replace(tzinfo=None) if hasattr(s_time, "tzinfo") and s_time.tzinfo else s_time
        p_naive = pivot_time.replace(tzinfo=None) if hasattr(pivot_time, "tzinfo") and pivot_time.tzinfo else pivot_time
        if s_naive < p_naive:
            before.append(s)
        else:
            after.append(s)
    return {"before": before, "after": after}


def save_memory_snapshot(text: str, profile_count: int = 0):
    """保存预编译的记忆快照"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "CREATE TABLE IF NOT EXISTS memory_snapshot ("
                "  id SERIAL PRIMARY KEY,"
                "  snapshot_text TEXT NOT NULL,"
                "  profile_count INTEGER DEFAULT 0,"
                "  created_at TIMESTAMPTZ DEFAULT NOW()"
                ")"
            )
            cur.execute(
                "INSERT INTO memory_snapshot (snapshot_text, profile_count) "
                "VALUES (%s, %s)",
                (text, profile_count),
            )
        conn.commit()
    finally:
        conn.close()


def load_memory_snapshot() -> dict | None:
    """加载最新快照"""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT snapshot_text, profile_count, created_at "
                "FROM memory_snapshot ORDER BY id DESC LIMIT 1"
            )
            row = cur.fetchone()
            return _as_dict(row)
    except Exception:
        return None
    finally:
        conn.close()
