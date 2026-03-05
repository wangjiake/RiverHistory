"""Conversation storage: raw conversations, turns, session tags."""

import json
from ._db import get_db_connection, _as_dicts
from psycopg2.extras import RealDictCursor


def save_raw_conversation(session_id: str, session_created_at,
                          user_input: str, user_input_at,
                          assistant_reply: str, assistant_reply_at):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO raw_conversations "
                "(session_id, session_created_at, user_input, user_input_at, "
                " assistant_reply, assistant_reply_at) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (session_id, session_created_at,
                 user_input, user_input_at,
                 assistant_reply, assistant_reply_at),
            )
        conn.commit()
    finally:
        conn.close()


def save_conversation_turn(turn: dict):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO conversation_turns "
                "(session_id, session_created_at, "
                " user_input, user_input_at, assistant_reply, assistant_reply_at, "
                " intent, need_memory, memory_type, ai_summary, perception_at, "
                " memories_used, memories_used_at, "
                " raw_response, raw_response_at, "
                " verification_result, verification_result_at, "
                " final_response, final_response_at, "
                " thinking_notes, thinking_notes_at, "
                " completed_at) "
                "VALUES ("
                " %s, %s, %s, %s, %s, %s, "
                " %s, %s, %s, %s, %s, "
                " %s, %s, "
                " %s, %s, "
                " %s, %s, "
                " %s, %s, "
                " %s, %s, "
                " %s)",
                (
                    turn["session_id"], turn["session_created_at"],
                    turn["user_input"], turn["user_input_at"],
                    turn["assistant_reply"], turn["assistant_reply_at"],
                    turn.get("intent"), turn.get("need_memory"),
                    turn.get("memory_type"), turn.get("ai_summary"),
                    turn.get("perception_at"),
                    json.dumps(turn.get("memories_used", []), ensure_ascii=False),
                    turn.get("memories_used_at"),
                    turn.get("raw_response"), turn.get("raw_response_at"),
                    turn.get("verification_result"), turn.get("verification_result_at"),
                    turn.get("final_response"), turn.get("final_response_at"),
                    turn.get("thinking_notes"), turn.get("thinking_notes_at"),
                    turn.get("completed_at"),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def save_session_tag(session_id: str, tag: str, summary: str = "",
                     reference_time=None):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            if reference_time:
                cur.execute(
                    "INSERT INTO session_tags (session_id, tag, summary, created_at) "
                    "VALUES (%s, %s, %s, %s)",
                    (session_id, tag, summary, reference_time),
                )
            else:
                cur.execute(
                    "INSERT INTO session_tags (session_id, tag, summary) "
                    "VALUES (%s, %s, %s)",
                    (session_id, tag, summary),
                )
        conn.commit()
    finally:
        conn.close()


def load_existing_tags(limit: int = 50) -> list[str]:
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT tag FROM session_tags "
                "ORDER BY tag LIMIT %s",
                (limit,),
            )
            return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()


def search_sessions_by_tag(tag_keyword: str, limit: int = 10) -> list[dict]:
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT session_id, tag, summary, created_at "
                "FROM session_tags "
                "WHERE tag LIKE %s "
                "ORDER BY created_at DESC LIMIT %s",
                (f"%{tag_keyword}%", limit),
            )
            return _as_dicts(cur.fetchall())
    finally:
        conn.close()
