"""Observation storage."""

from ._db import get_db_connection, _as_dicts
from psycopg2.extras import RealDictCursor


def save_observation(session_id: str, observation_type: str, content: str,
                     subject: str | None = None, context: str | None = None,
                     source_turn_id: int | None = None,
                     reference_time=None) -> int | None:
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            if reference_time:
                cur.execute(
                    "INSERT INTO observations "
                    "(session_id, observation_type, content, subject, context, source_turn_id, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                    (session_id, observation_type, content, subject, context, source_turn_id, reference_time),
                )
            else:
                cur.execute(
                    "INSERT INTO observations "
                    "(session_id, observation_type, content, subject, context, source_turn_id) "
                    "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                    (session_id, observation_type, content, subject, context, source_turn_id),
                )
            row = cur.fetchone()
            obs_id = row[0] if row else None
        conn.commit()
        return obs_id
    finally:
        conn.close()


def update_observation_classification(obs_id: int, classification: str):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE observations SET classification = %s WHERE id = %s",
                (classification, obs_id),
            )
        conn.commit()
    finally:
        conn.close()


def load_observations(session_id: str | None = None, subject: str | None = None,
                      limit: int = 50) -> list[dict]:
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            conditions = []
            params: list = []
            if session_id:
                conditions.append("session_id = %s")
                params.append(session_id)
            if subject:
                conditions.append("subject = %s")
                params.append(subject)
            where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
            params.append(limit)
            cur.execute(
                f"SELECT id, session_id, observation_type, content, subject, context, created_at "
                f"FROM observations {where} "
                f"ORDER BY created_at DESC LIMIT %s",
                params,
            )
            return _as_dicts(cur.fetchall())
    finally:
        conn.close()


def load_observations_by_time_range(pivot_time, keywords: set | None = None,
                                     limit: int = 200) -> dict:
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id, session_id, observation_type, content, subject, "
                "context, created_at "
                "FROM observations "
                "ORDER BY created_at ASC LIMIT %s",
                (limit,),
            )
            all_obs = _as_dicts(cur.fetchall())
    finally:
        conn.close()

    if keywords:
        filtered = []
        for o in all_obs:
            text = (o.get("content", "") + " " + (o.get("subject", "") or "")).lower()
            if any(kw.lower() in text for kw in keywords if kw and len(kw) >= 2):
                filtered.append(o)
    else:
        filtered = all_obs

    before = []
    after = []
    for o in filtered:
        obs_time = o.get("created_at")
        if not obs_time:
            before.append(o)
            continue
        obs_naive = obs_time.replace(tzinfo=None) if hasattr(obs_time, 'tzinfo') and obs_time.tzinfo else obs_time
        pivot_naive = pivot_time.replace(tzinfo=None) if hasattr(pivot_time, 'tzinfo') and pivot_time.tzinfo else pivot_time
        if obs_naive < pivot_naive:
            before.append(o)
        else:
            after.append(o)

    return {"before": before, "after": after}
