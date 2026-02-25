"""Import conversation exports into database."""

import argparse
import json
import re
import hashlib
from html.parser import HTMLParser
from datetime import datetime, timezone, timedelta
import psycopg2



_GEMINI_DATE_RE = re.compile(
    r"(\d{4})年(\d{1,2})月(\d{1,2})日\s+"
    r"(\d{1,2}):(\d{2}):(\d{2})\s+"
    r"(GMT[+-]\d{2}:\d{2}|[A-Z]{2,5})"
)

_TZ_ABBREVS = {
    "JST": 9, "CST": 8, "KST": 9, "EST": -5, "PST": -8,
    "UTC": 0, "GMT": 0, "CET": 1, "EET": 2, "IST": 5,
}


def _parse_gemini_timestamp(ts_str: str) -> datetime | None:
    if not ts_str:
        return None
    m = _GEMINI_DATE_RE.search(ts_str.strip())
    if not m:
        return None
    year, month, day, hour, minute, second, tz_str = m.groups()

    if tz_str.startswith("GMT"):
        sign = 1 if tz_str[3] == "+" else -1
        parts = tz_str[4:].split(":")
        offset_hours = sign * int(parts[0])
        offset_mins = sign * int(parts[1]) if len(parts) > 1 else 0
    else:
        offset_hours = _TZ_ABBREVS.get(tz_str, 0)
        offset_mins = 0

    tz = timezone(timedelta(hours=offset_hours, minutes=offset_mins))
    return datetime(int(year), int(month), int(day),
                    int(hour), int(minute), int(second), tzinfo=tz)


class _GeminiHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.items = []
        self.in_body1 = False
        self.text_buf = ""

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        cls = d.get("class", "")
        if "outer-cell" in cls:
            pass  # reset per card
        if "mdl-typography--body-1" in cls and "text-right" not in cls:
            self.in_body1 = True
            self.text_buf = ""

    def handle_endtag(self, tag):
        if self.in_body1 and tag == "div":
            self.in_body1 = False
            text = self.text_buf.strip()
            if not text:
                return

            cleaned = re.sub(r"^Prompted[\s\xa0]*", "", text)

            m = _GEMINI_DATE_RE.search(cleaned)
            if m:
                prompt = cleaned[:m.start()].strip()
                ts = m.group(0)
                response = cleaned[m.end():].strip()
                conv_time = _parse_gemini_timestamp(ts)
            else:
                prompt = cleaned
                response = ""
                conv_time = None

            if prompt:
                self.items.append({
                    "prompt": prompt,
                    "response": response,
                    "timestamp": ts if m else "",
                    "conversation_time": conv_time,
                })

    def handle_data(self, data):
        if self.in_body1:
            self.text_buf += data


def _checksum_str(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def _checksum_dict(d: dict) -> str:
    raw = json.dumps(d, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()



def import_chatgpt(filepath: str, conn):
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        print(f"  ChatGPT: expected JSON array, got {type(data).__name__}")
        return 0

    cur = conn.cursor()
    count = 0
    skipped = 0
    for conv in data:
        cs = _checksum_dict(conv)
        cur.execute("SELECT 1 FROM chatgpt WHERE checksum = %s", (cs,))
        if cur.fetchone():
            skipped += 1
            continue

        create_time = conv.get("create_time")
        if create_time:
            conv_time = datetime.fromtimestamp(create_time, tz=timezone.utc)
        else:
            conv_time = None

        cur.execute(
            "INSERT INTO chatgpt (content, checksum, conversation_time) "
            "VALUES (%s, %s, %s)",
            (json.dumps(conv, ensure_ascii=False), cs, conv_time),
        )
        count += 1

    conn.commit()
    cur.close()
    print(f"  ChatGPT: imported {count}, skipped {skipped} duplicates")
    return count



def import_claude(filepath: str, conn):
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        print(f"  Claude: expected JSON array, got {type(data).__name__}")
        return 0

    cur = conn.cursor()
    count = 0
    skipped = 0
    for conv in data:
        cs = _checksum_dict(conv)
        cur.execute("SELECT 1 FROM claude WHERE checksum = %s", (cs,))
        if cur.fetchone():
            skipped += 1
            continue

        created_at = conv.get("created_at")
        if created_at:
            try:
                conv_time = datetime.fromisoformat(created_at)
            except Exception:
                conv_time = None
        else:
            conv_time = None

        cur.execute(
            "INSERT INTO claude (content, checksum, conversation_time) "
            "VALUES (%s, %s, %s)",
            (json.dumps(conv, ensure_ascii=False), cs, conv_time),
        )
        count += 1

    conn.commit()
    cur.close()
    print(f"  Claude: imported {count}, skipped {skipped} duplicates")
    return count



def _import_gemini_html(filepath: str, conn):
    with open(filepath, "r", encoding="utf-8") as f:
        html = f.read()

    parser = _GeminiHTMLParser()
    parser.feed(html)

    cur = conn.cursor()
    count = 0
    skipped = 0
    for item in parser.items:
        content = {
            "prompt": item["prompt"],
            "response": item["response"],
            "timestamp": item["timestamp"],
        }
        cs = _checksum_str(item["prompt"] + item["timestamp"])
        cur.execute("SELECT 1 FROM gemini WHERE checksum = %s", (cs,))
        if cur.fetchone():
            skipped += 1
            continue

        cur.execute(
            "INSERT INTO gemini (content, checksum, conversation_time) "
            "VALUES (%s, %s, %s)",
            (json.dumps(content, ensure_ascii=False), cs, item["conversation_time"]),
        )
        count += 1

    conn.commit()
    cur.close()
    print(f"  Gemini: imported {count}, skipped {skipped} duplicates (HTML)")
    return count


def _import_gemini_json(filepath: str, conn):
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict):
        data = [data]

    if not isinstance(data, list):
        print(f"  Gemini: expected JSON array, got {type(data).__name__}")
        return 0

    cur = conn.cursor()
    count = 0
    skipped = 0
    for conv in data:
        cs = _checksum_dict(conv)
        cur.execute("SELECT 1 FROM gemini WHERE checksum = %s", (cs,))
        if cur.fetchone():
            skipped += 1
            continue

        ts_str = conv.get("timestamp", "")
        conv_time = _parse_gemini_timestamp(ts_str)

        cur.execute(
            "INSERT INTO gemini (content, checksum, conversation_time) "
            "VALUES (%s, %s, %s)",
            (json.dumps(conv, ensure_ascii=False), cs, conv_time),
        )
        count += 1

    conn.commit()
    cur.close()
    print(f"  Gemini: imported {count}, skipped {skipped} duplicates (JSON)")
    return count


def import_gemini(filepath: str, conn):
    if filepath.lower().endswith(".html") or filepath.lower().endswith(".htm"):
        return _import_gemini_html(filepath, conn)
    else:
        return _import_gemini_json(filepath, conn)



def import_demo(filepath: str, conn):
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        print(f"  Demo: expected JSON array, got {type(data).__name__}")
        return 0

    cur = conn.cursor()
    count = 0
    skipped = 0
    for session in data:
        cs = _checksum_dict(session)
        cur.execute("SELECT 1 FROM demo WHERE checksum = %s", (cs,))
        if cur.fetchone():
            skipped += 1
            continue

        date_str = session.get("date", "")
        if date_str:
            conv_time = datetime.strptime(date_str, "%Y-%m-%d").replace(
                hour=20, minute=0, tzinfo=timezone.utc)
        else:
            conv_time = None

        cur.execute(
            "INSERT INTO demo (content, checksum, conversation_time) "
            "VALUES (%s, %s, %s)",
            (json.dumps(session, ensure_ascii=False), cs, conv_time),
        )
        count += 1

    conn.commit()
    cur.close()
    print(f"  Demo: imported {count} sessions, skipped {skipped} duplicates")
    return count



def main():
    from agent.config import load_config
    _cfg = load_config()
    _db = _cfg.get("database", {})

    parser = argparse.ArgumentParser(
        description="Import conversation exports",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python import_data.py --chatgpt data/conversations.json
  python import_data.py --claude data/claude/conversations.json
  python import_data.py --gemini "data/Gemini Apps/我的活动记录.html"
  python import_data.py --demo                                         # load demo test data
  python import_data.py --demo2                                        # load demo2 test data (clears demo table first)
  python import_data.py --demo3                                        # load demo3 test data (clears demo table first)
  python import_data.py --chatgpt data/chatgpt.json --gemini "data/Gemini Apps/我的活动记录.html"
""",
    )
    parser.add_argument("--db", default=_db.get("name", "Riverse"), help="database name")
    parser.add_argument("--user", default=_db.get("user", "postgres"), help="database user")
    parser.add_argument("--host", default=_db.get("host", "localhost"), help="database host")
    parser.add_argument("--chatgpt", help="ChatGPT conversations.json path")
    parser.add_argument("--claude", help="Claude export JSON path")
    parser.add_argument("--gemini", help="Gemini Takeout path (.html or .json, auto-detected)")
    parser.add_argument("--demo", action="store_true", help="Load demo test data (data/demo.json)")
    parser.add_argument("--demo2", action="store_true", help="Load demo2 test data (data/demo2.json, clears demo table first)")
    parser.add_argument("--demo3", action="store_true", help="Load demo3 test data (data/demo3.json, clears demo table first)")
    args = parser.parse_args()

    if not any([args.chatgpt, args.claude, args.gemini, args.demo, args.demo2, args.demo3]):
        parser.print_help()
        print("\nError: specify at least one source (--chatgpt / --claude / --gemini / --demo)")
        return

    conn = psycopg2.connect(dbname=args.db, user=args.user, host=args.host,
                            options="-c client_encoding=UTF8")

    print(f"Database: {args.db}")
    total = 0
    if args.chatgpt:
        total += import_chatgpt(args.chatgpt, conn)
    if args.claude:
        total += import_claude(args.claude, conn)
    if args.gemini:
        total += import_gemini(args.gemini, conn)
    if args.demo:
        import os
        demo_path = os.path.join(os.path.dirname(__file__), "data", "demo.json")
        total += import_demo(demo_path, conn)
    if args.demo2:
        import os
        cur = conn.cursor()
        cur.execute("TRUNCATE TABLE demo RESTART IDENTITY")
        conn.commit()
        cur.close()
        print("  Demo table cleared.")
        demo2_path = os.path.join(os.path.dirname(__file__), "data", "demo2.json")
        total += import_demo(demo2_path, conn)
    if args.demo3:
        import os
        cur = conn.cursor()
        cur.execute("TRUNCATE TABLE demo RESTART IDENTITY")
        conn.commit()
        cur.close()
        print("  Demo table cleared.")
        demo3_path = os.path.join(os.path.dirname(__file__), "data", "demo3.json")
        total += import_demo(demo3_path, conn)

    conn.close()
    print(f"\nDone. Total imported: {total}")
    print("Next: edit settings.yaml, then run: python run.py <source> <count>")


if __name__ == "__main__":
    main()
