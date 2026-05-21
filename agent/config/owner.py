"""Owner (account) resolution for RiverHistory CLI tools.

RiverHistory shares the Riverse database with JKRiver, which now namespaces
every business row by `owner_id` (see JKRiver migrations 005-012). For
RiverHistory's single-owner-at-a-time batch tools (run.py, import_data.py),
this module looks up `accounts` and resolves a human-friendly --owner-name
into the integer id used by all storage writes.

Resolution order:
  1. --owner-name <name>  → look up by accounts.name (case-insensitive)
                            also matches accounts.display_name
  2. no flag, 1 account in DB  → auto-select that one
  3. no flag, multiple accounts → list them and exit with usage message

Always validates the schema first: if the `accounts` table is missing the
user is told to apply the JKRiver migrations before continuing.
"""

import sys
from psycopg2.extras import RealDictCursor
from agent.storage import get_db_connection


def _accounts_table_exists() -> bool:
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_name = 'accounts')"
            )
            return bool(cur.fetchone()[0])
    finally:
        conn.close()


def list_accounts() -> list[dict]:
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id, name, display_name FROM accounts "
                "WHERE is_active IS NOT FALSE ORDER BY id"
            )
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def _exit_with_account_list(accounts: list[dict]):
    print("Multiple accounts found in the database — please specify which one")
    print("to process via --owner-name <name>. Available accounts:")
    print()
    for a in accounts:
        display = a["display_name"] or a["name"]
        print(f"  --owner-name {a['name']:<12s}  (id={a['id']}, {display})")
    print()
    sys.exit(2)


def resolve_owner(name: str | None = None) -> int:
    """Resolve a CLI --owner-name into an integer owner_id.

    Exits with a helpful message if the schema isn't ready or the name
    doesn't match any account.
    """
    if not _accounts_table_exists():
        print("ERROR: the `accounts` table is missing. RiverHistory needs the")
        print("JKRiver family-multi-owner migrations (005-012) applied first.")
        print("Run: python3 setup_db.py")
        sys.exit(2)

    accounts = list_accounts()
    if not accounts:
        print("ERROR: no accounts in DB. Run setup_db.py to seed the default.")
        sys.exit(2)

    if name:
        n = name.lower().strip()
        for a in accounts:
            if a["name"].lower() == n or (a["display_name"] or "").lower() == n:
                return a["id"]
        print(f"ERROR: no account matching --owner-name '{name}'.")
        _exit_with_account_list(accounts)

    if len(accounts) == 1:
        return accounts[0]["id"]

    _exit_with_account_list(accounts)
