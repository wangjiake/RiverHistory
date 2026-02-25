"""Batch processing entry point."""

import sys
import uuid
from datetime import datetime, timedelta

from agent.config import load_config
from agent.perceive import perceive
from agent.storage import (
    configure_db, get_db_connection, parse_turns,
    save_raw_conversation, save_conversation_turn,
)
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

    all_rows.sort(key=lambda r: r["conversation_time"] or datetime.min)

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


def process_one(row: dict, config: dict, idx: int, total: int):
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
        timestamp = turn["timestamp"] + timedelta(minutes=(i - 1) * 5)

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
        )

        save_conversation_turn({
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
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("Usage: python run.py <source> <count>")
        print()
        print("  source:  chatgpt | claude | gemini | demo | all")
        print("  count:   number or 'max' (process all)")
        print()
        print("Examples:")
        print("  python run.py chatgpt 50    # ChatGPT oldest 50")
        print("  python run.py claude max    # Claude all")
        print("  python run.py gemini 100    # Gemini oldest 100")
        print("  python run.py demo max      # Demo test data")
        print("  python run.py all max       # All sources mixed by time")
        print("  python run.py all 200       # All sources mixed, oldest 200")
        return

    source = sys.argv[1].lower()
    count_arg = sys.argv[2] if len(sys.argv) > 2 else "max"
    count = 0 if count_arg.lower() == "max" else int(count_arg)

    valid_sources = SOURCES + ["demo", "all"]
    if source not in valid_sources:
        print(f"Error: unknown source '{source}'. Use: chatgpt | claude | gemini | demo | all")
        return

    config = load_config()
    configure_db(config["db_name"], config["db_user"], config["db_host"])

    start_time = datetime.now()
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
        from agent.core.sleep import run as run_sleep
    except ImportError:
        print("Error: agent/core/sleep module not found.")
        print("Please download the correct .so file for your platform from Releases")
        print("and place it in agent/core/")
        return

    for idx, row in enumerate(rows, 1):
        process_one(row, config, idx, len(rows))

        print(f"\n  --- Sleep processing ({idx}/{len(rows)}) ---")
        run_sleep(fallback_time=row["conversation_time"])
        print(f"  --- Done ---")

        mark_processed(row["source"], row["id"])

    elapsed = datetime.now() - start_time
    print(f"\n{'='*60}")
    print(f"Completed: {len(rows)} conversations in {elapsed}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
