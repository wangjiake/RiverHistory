"""Reset profile tables."""

import argparse
import psycopg2


TABLES_TO_RESET = [
    "raw_conversations",
    "conversation_turns",
    "event_log",
    "session_tags",
    "observations",
    "user_profile",
    "hypotheses",
    "current_profile",
    "user_model",
    "strategies",
    "trajectory_summary",
    "relationships",
]


def reset_tables(db_name: str, db_user: str = "postgres", db_host: str = "localhost"):
    conn = psycopg2.connect(dbname=db_name, user=db_user, host=db_host)
    cur = conn.cursor()

    for table in TABLES_TO_RESET:
        cur.execute(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_name = %s)", (table,)
        )
        if cur.fetchone()[0]:
            cur.execute(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE")
            print(f"  Cleared: {table}")
        else:
            print(f"  Skipped (not found): {table}")

    conn.commit()
    cur.close()
    conn.close()


def main():
    from agent.config import load_config
    _cfg = load_config()
    _db = _cfg.get("database", {})

    parser = argparse.ArgumentParser(description="Reset profile tables")
    parser.add_argument("--db", default=_db.get("name", "Riverse"), help="database name")
    parser.add_argument("--user", default=_db.get("user", "postgres"), help="database user")
    parser.add_argument("--host", default=_db.get("host", "localhost"), help="database host")
    args = parser.parse_args()

    print(f"Database: {args.db}")
    print(f"Resetting all profile tables (source tables will NOT be touched)...")
    reset_tables(args.db, args.user, args.host)
    print("Done. Source tables (chatgpt/claude/gemini/demo) are untouched.")


if __name__ == "__main__":
    main()
