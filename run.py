"""Batch processing entry point.

Single-owner CLI: all writes from this run go under one owner_id. Pick the
owner with --owner-name (or rely on auto-select when only one account
exists). See agent/config/owner.py for resolution rules.
"""

import argparse
import sys
import uuid
from datetime import datetime, timedelta, timezone

from agent.config import load_config
from agent.config.owner import resolve_owner
from agent.perceive import perceive
from agent.storage import (
    get_db_connection, parse_turns,
    save_raw_conversation, save_conversation_turn,
)
from agent.utils.time_context import set_current_time
from psycopg2.extras import RealDictCursor


SOURCES = ["chatgpt", "claude", "gemini"]


def load_source(source: str, count: int = 0) -> list:
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if count > 0:
                cur.execute(
                    f"SELECT id, content, conversation_time FROM {source} "
                    f"WHERE status = 'pending' "
                    f"ORDER BY conversation_time ASC LIMIT %s",
                    (count,)
                )
            else:
                cur.execute(
                    f"SELECT id, content, conversation_time FROM {source} "
                    f"WHERE status = 'pending' "
                    f"ORDER BY conversation_time ASC"
                )
            rows = cur.fetchall()
            for r in rows:
                r["source"] = source
            return rows
    finally:
        conn.close()


def load_all(count: int = 0) -> list:
    conn = get_db_connection()
    all_rows = []
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            for source in SOURCES:
                cur.execute(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                    "WHERE table_name = %s)", (source,)
                )
                if not cur.fetchone()["exists"]:
                    continue
                cur.execute(
                    f"SELECT id, content, conversation_time FROM {source} "
                    f"WHERE status = 'pending' "
                    f"ORDER BY conversation_time ASC"
                )
                rows = cur.fetchall()
                for r in rows:
                    r["source"] = source
                all_rows.extend(rows)
    finally:
        conn.close()

    def _sort_key(r):
        t = r["conversation_time"]
        if t is None:
            return datetime.min.replace(tzinfo=timezone.utc)
        if t.tzinfo is None:
            return t.replace(tzinfo=timezone.utc)
        return t

    all_rows.sort(key=_sort_key)

    if count > 0:
        all_rows = all_rows[:count]

    return all_rows


def mark_processed(source: str, row_id: int):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE {source} SET status = 'processed' WHERE id = %s",
                (row_id,)
            )
        conn.commit()
    finally:
        conn.close()


def process_one(row: dict, config: dict, idx: int, total: int, owner_id: int = 1):
    source = row["source"]
    llm_config = config.get("llm", {})

    print(f"\n{'='*60}")
    print(f"[{idx}/{total}] source={source} id={row['id']} time={row['conversation_time']}")
    print(f"{'='*60}")

    turns = parse_turns(row)
    print(f"Parsed {len(turns)} turns")

    if not turns:
        print("No valid turns, skipping")
        return

    session_id = str(uuid.uuid4())[:8] + f"-{source}-{row['id']}"
    session_created_at = row["conversation_time"]

    for i, turn in enumerate(turns, 1):
        user_input = turn["user_input"]
        assistant_reply = turn["assistant_reply"]
        timestamp = (turn["timestamp"] or session_created_at or datetime.now(timezone.utc)) + timedelta(minutes=(i - 1) * 5)

        print(f"  Turn {i}/{len(turns)}: {user_input[:60]}{'...' if len(user_input) > 60 else ''}")

        perception = perceive(user_input, llm_config, config.get("language", "zh"))
        print(f"    category={perception['category']} intent={perception['intent'][:40]}")

        save_raw_conversation(
            session_id=session_id,
            session_created_at=session_created_at,
            user_input=user_input,
            user_input_at=timestamp,
            assistant_reply=assistant_reply,
            assistant_reply_at=timestamp,
            owner_id=owner_id,
        )

        save_conversation_turn({
            "owner_id": owner_id,
            "session_id": session_id,
            "session_created_at": session_created_at,
            "user_input": user_input,
            "user_input_at": timestamp,
            "assistant_reply": assistant_reply,
            "assistant_reply_at": timestamp,
            "intent": perception["intent"],
            "need_memory": perception["need_memory"],
            "memory_type": perception["memory_type"],
            "ai_summary": perception["ai_summary"],
            "perception_at": timestamp,
            "memories_used": [],
            "memories_used_at": None,
            "completed_at": timestamp,
            "has_new_info": perception["category"] == "personal",
        })

    print(f"  -> Done: session_id={session_id}, {len(turns)} turns")


def main():
    valid_sources = SOURCES + ["demo", "all"]
    p = argparse.ArgumentParser(
        description="Process historical chats and run sleep extraction. "
                    "All output (observations, profile facts, memory snapshots) "
                    "is scoped to the chosen owner.",
        epilog=(
            "Examples:\n"
            "  python run.py chatgpt 50                  # 50 oldest, auto-pick owner\n"
            "  python run.py claude max --owner-name jk  # all, write under jk\n"
            "  python run.py all 200 --owner-name wife   # mixed, write under wife\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("source", choices=valid_sources,
                   help="chatgpt | claude | gemini | demo | all")
    p.add_argument("count", nargs="?", default="max",
                   help="number or 'max' (default: max)")
    p.add_argument("--owner-name", dest="owner_name", default=None,
                   help="Which family member to write data under. "
                        "Omit if only one account exists in the DB.")
    args = p.parse_args()

    source = args.source.lower()
    count = 0 if str(args.count).lower() == "max" else int(args.count)

    config = load_config()
    owner_id = resolve_owner(args.owner_name)
    print(f"\n[owner] writing under owner_id={owner_id} ({args.owner_name or '<auto>'})")

    # Check LLM reachability
    import requests
    llm = config.get("llm", {})
    api_base = llm.get("api_base", "")
    if api_base:
        try:
            requests.get(api_base, timeout=5)
        except Exception:
            provider = config.get("llm_provider", "local")
            if provider == "local":
                print(f"⚠ Cannot reach Ollama at {api_base}")
                print("  Please run 'ollama start' first, then try again.")
            else:
                print(f"⚠ Cannot reach LLM API at {api_base}")

    start_time = datetime.now(timezone.utc)
    print(f"\n=== Batch Processing ===")
    print(f"Source: {source}, Count: {'all' if count == 0 else count}")
    print(f"LLM: {config['llm'].get('model', '?')}")

    if source == "all":
        rows = load_all(count)
    else:
        rows = load_source(source, count)

    print(f"Loaded {len(rows)} pending records (oldest first)")

    if not rows:
        print("No pending data to process.")
        return

    # Import core processing module
    try:
        from agent.sleep import run as run_sleep
    except ImportError:
        print("Error: agent/core/sleep module not found.")
        print("Please download the correct .so file for your platform from Releases")
        print("and place it in agent/core/")
        return

    for idx, row in enumerate(rows, 1):
        process_one(row, config, idx, len(rows), owner_id=owner_id)

        print(f"\n  --- Sleep processing ({idx}/{len(rows)}) ---")
        # Anchor "now" to the conversation's time so decay/expiry math reflects
        # the historical moment, not the actual clock — same behaviour as the
        # old run_sleep(fallback_time=...) API that no longer exists.
        if row["conversation_time"]:
            set_current_time(row["conversation_time"])
        try:
            run_sleep(owner_id=owner_id)
        finally:
            set_current_time(None)
        print(f"  --- Done ---")

        mark_processed(row["source"], row["id"])

    elapsed = datetime.now(timezone.utc) - start_time
    print(f"\n{'='*60}")
    print(f"Completed: {len(rows)} conversations in {elapsed}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
