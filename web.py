"""Web viewer."""

import os
import sys
import json
import argparse
from datetime import datetime, date, timedelta
from decimal import Decimal
from flask import Flask, render_template, jsonify, request, send_from_directory
import psycopg2
from psycopg2.extras import RealDictCursor

from agent.config import load_config

app = Flask(__name__)
_cfg = load_config()
_db = _cfg.get("database", {})
DB_NAME = _db.get("name", "Riverse")
DB_USER = _db.get("user", "postgres")
DB_HOST = _db.get("host", "localhost")
IMG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "img")


def get_conn():
    return psycopg2.connect(
        dbname=DB_NAME, user=DB_USER, host=DB_HOST,
        options="-c client_encoding=UTF8",
    )


def _serialize(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    return str(obj)



@app.route("/img/<path:filename>")
def serve_img(filename):
    return send_from_directory(IMG_DIR, filename)


@app.route("/")
def index():
    return render_template("profile.html", db_name=DB_NAME)


@app.route("/api/stats")
def api_stats():
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(DISTINCT session_id) FROM raw_conversations")
        sessions = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM observations WHERE rejected = false")
        observations = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM user_profile WHERE end_time IS NULL AND human_end_time IS NULL AND layer='confirmed' AND rejected = false")
        confirmed = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM user_profile WHERE end_time IS NULL AND human_end_time IS NULL AND layer='suspected' AND rejected = false")
        suspected = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM user_profile WHERE rejected = false AND (end_time IS NOT NULL OR human_end_time IS NOT NULL)")
        closed = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM user_profile WHERE superseded_by IS NOT NULL AND end_time IS NULL AND human_end_time IS NULL")
        disputes = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM relationships WHERE status='active'")
        relationships = cur.fetchone()[0]
        return jsonify({
            "sessions": sessions,
            "observations": observations,
            "confirmed": confirmed,
            "suspected": suspected,
            "closed": closed,
            "disputes": disputes,
            "relationships": relationships,
        })
    finally:
        conn.close()


@app.route("/api/profile")
def api_profile():
    category = request.args.get("category")
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        conditions = ["end_time IS NULL"]
        params = []
        if category:
            conditions.append("category = %s")
            params.append(category)
        where = "WHERE " + " AND ".join(conditions)
        cur.execute(
            f"SELECT id, category, subject, value, layer, source_type, "
            f"start_time, decay_days, expires_at, evidence, mention_count, "
            f"created_at, updated_at, confirmed_at, superseded_by, supersedes, "
            f"rejected, human_end_time, note "
            f"FROM user_profile {where} "
            f"ORDER BY rejected ASC, "
            f"CASE layer WHEN 'confirmed' THEN 1 WHEN 'suspected' THEN 2 END, "
            f"category, subject",
            params,
        )
        rows = cur.fetchall()
        return jsonify([{k: _serialize(v) if isinstance(v, (datetime, date)) else v
                         for k, v in row.items()} for row in rows])
    finally:
        conn.close()


@app.route("/api/categories")
def api_categories():
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT category FROM user_profile WHERE end_time IS NULL AND rejected = false AND human_end_time IS NULL ORDER BY category"
        )
        return jsonify([row[0] for row in cur.fetchall()])
    finally:
        conn.close()


@app.route("/api/timeline")
def api_timeline():
    category = request.args.get("category")
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        conditions = []
        params = []
        if category:
            conditions.append("category = %s")
            params.append(category)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        cur.execute(
            f"SELECT id, category, subject, value, layer, source_type, "
            f"start_time, end_time, mention_count, superseded_by, supersedes, "
            f"rejected, human_end_time, note "
            f"FROM user_profile {where} "
            f"ORDER BY category, subject, start_time",
            params,
        )
        rows = cur.fetchall()
        return jsonify([{k: _serialize(v) if isinstance(v, (datetime, date)) else v
                         for k, v in row.items()} for row in rows])
    finally:
        conn.close()


@app.route("/api/relationships")
def api_relationships():
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT id, name, relation, details, mention_count, "
            "first_mentioned_at, last_mentioned_at "
            "FROM relationships WHERE status = 'active' "
            "ORDER BY last_mentioned_at DESC"
        )
        rows = cur.fetchall()
        return jsonify([{k: _serialize(v) if isinstance(v, (datetime, date)) else v
                         for k, v in row.items()} for row in rows])
    finally:
        conn.close()


@app.route("/api/snapshot")
def api_snapshot():
    month = request.args.get("month", "")
    if not month:
        return jsonify([])
    try:
        year, mon = month.split("-")
        year, mon = int(year), int(mon)
        if mon == 12:
            next_month = datetime(year + 1, 1, 1)
        else:
            next_month = datetime(year, mon + 1, 1)
        month_end = next_month - timedelta(seconds=1)
        month_start = datetime(year, mon, 1)
    except Exception:
        return jsonify([])

    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT id, category, subject, value, layer, source_type, "
            "start_time, end_time, mention_count, superseded_by, "
            "(start_time >= %s AND start_time <= %s) AS is_new "
            "FROM user_profile "
            "WHERE start_time <= %s "
            "AND (end_time IS NULL OR end_time > %s) "
            "ORDER BY CASE layer WHEN 'confirmed' THEN 1 WHEN 'suspected' THEN 2 END, "
            "category, subject",
            (month_start, month_end, month_end, month_end),
        )
        rows = cur.fetchall()
        return jsonify([{k: _serialize(v) if isinstance(v, (datetime, date)) else v
                         for k, v in row.items()} for row in rows])
    finally:
        conn.close()


@app.route("/api/snapshot/months")
def api_snapshot_months():
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT TO_CHAR(start_time, 'YYYY-MM') as m "
            "FROM user_profile WHERE start_time IS NOT NULL "
            "ORDER BY m"
        )
        months = [row[0] for row in cur.fetchall()]
        return jsonify(months)
    finally:
        conn.close()


@app.route("/api/observations")
def api_observations():
    obs_type = request.args.get("type")
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        conditions = []
        params = []
        if obs_type:
            conditions.append("observation_type = %s")
            params.append(obs_type)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        cur.execute(
            f"SELECT id, session_id, observation_type, content, subject, context, created_at, "
            f"rejected, note "
            f"FROM observations {where} "
            f"ORDER BY rejected ASC, created_at DESC",
            params,
        )
        rows = cur.fetchall()
        return jsonify([{k: _serialize(v) if isinstance(v, (datetime, date)) else v
                         for k, v in row.items()} for row in rows])
    finally:
        conn.close()


@app.route("/api/trajectory")
def api_trajectory():
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM trajectory_summary ORDER BY updated_at DESC LIMIT 1")
        row = cur.fetchone()
        if row:
            return jsonify({k: _serialize(v) if isinstance(v, (datetime, date)) else v
                            for k, v in row.items()})
        return jsonify(None)
    finally:
        conn.close()


def _log_review(conn, target_table, target_id, action, old_value, new_value, note):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO review_log (target_table, target_id, action, old_value, new_value, note) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (target_table, target_id, action,
             json.dumps(old_value, default=_serialize, ensure_ascii=False) if old_value else None,
             json.dumps(new_value, default=_serialize, ensure_ascii=False) if new_value else None,
             note),
        )


@app.route("/api/review/profile", methods=["POST"])
def api_review_profile():
    data = request.get_json(force=True)
    fact_id = data.get("id")
    action = data.get("action")
    note = data.get("note", "")
    human_end_time = data.get("human_end_time")

    if not fact_id or action not in ("reject", "unreject", "close", "reopen"):
        return jsonify({"error": "Invalid parameters"}), 400

    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT id, rejected, human_end_time, end_time, note FROM user_profile WHERE id = %s", (fact_id,))
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "Record not found"}), 404

        old_value = {k: _serialize(v) if isinstance(v, (datetime, date)) else v for k, v in row.items()}

        if action == "reject":
            cur.execute(
                "UPDATE user_profile SET rejected = true, note = %s WHERE id = %s",
                (note or row["note"], fact_id),
            )
            new_value = {"rejected": True, "note": note}

        elif action == "unreject":
            cur.execute(
                "UPDATE user_profile SET rejected = false, note = %s WHERE id = %s",
                (note or None, fact_id),
            )
            new_value = {"rejected": False, "note": note}

        elif action == "close":
            if human_end_time:
                try:
                    het = datetime.fromisoformat(human_end_time)
                except (ValueError, TypeError):
                    return jsonify({"error": "Invalid time format"}), 400
            else:
                het = datetime.now()
            cur.execute(
                "UPDATE user_profile SET human_end_time = %s, note = %s WHERE id = %s",
                (het, note or row["note"], fact_id),
            )
            new_value = {"human_end_time": het.isoformat(), "note": note}

        elif action == "reopen":
            cur.execute(
                "UPDATE user_profile SET human_end_time = NULL, note = %s WHERE id = %s",
                (note or None, fact_id),
            )
            new_value = {"human_end_time": None, "note": note}

        _log_review(conn, "user_profile", fact_id, action, old_value, new_value, note)
        conn.commit()
        return jsonify({"ok": True, "action": action, "id": fact_id})
    finally:
        conn.close()


@app.route("/api/review/observation", methods=["POST"])
def api_review_observation():
    data = request.get_json(force=True)
    obs_id = data.get("id")
    action = data.get("action")
    note = data.get("note", "")

    if not obs_id or action not in ("reject", "unreject"):
        return jsonify({"error": "Invalid parameters"}), 400

    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT id, rejected, note FROM observations WHERE id = %s", (obs_id,))
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "Record not found"}), 404

        old_value = dict(row)

        if action == "reject":
            cur.execute(
                "UPDATE observations SET rejected = true, note = %s WHERE id = %s",
                (note or row["note"], obs_id),
            )
            new_value = {"rejected": True, "note": note}
        else:
            cur.execute(
                "UPDATE observations SET rejected = false, note = %s WHERE id = %s",
                (note or None, obs_id),
            )
            new_value = {"rejected": False, "note": note}

        _log_review(conn, "observations", obs_id, action, old_value, new_value, note)
        conn.commit()
        return jsonify({"ok": True, "action": action, "id": obs_id})
    finally:
        conn.close()


@app.route("/api/review/log")
def api_review_log():
    target_table = request.args.get("table")
    target_id = request.args.get("id")
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        conditions = []
        params = []
        if target_table:
            conditions.append("target_table = %s")
            params.append(target_table)
        if target_id:
            conditions.append("target_id = %s")
            params.append(int(target_id))
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        cur.execute(
            f"SELECT id, target_table, target_id, action, old_value, new_value, note, created_at "
            f"FROM review_log {where} "
            f"ORDER BY created_at DESC LIMIT 100",
            params,
        )
        rows = cur.fetchall()
        return jsonify([{k: _serialize(v) if isinstance(v, (datetime, date)) else v
                         for k, v in row.items()} for row in rows])
    finally:
        conn.close()


def main():
    global DB_NAME, DB_USER, DB_HOST
    parser = argparse.ArgumentParser(description="Web viewer")
    parser.add_argument("--db", default=DB_NAME, help=f"database name (default: {DB_NAME})")
    parser.add_argument("--user", default=DB_USER, help=f"database user (default: {DB_USER})")
    parser.add_argument("--host", default=DB_HOST, help=f"database host (default: {DB_HOST})")
    parser.add_argument("--port", type=int, default=2345, help="port (default: 2345)")
    args = parser.parse_args()
    DB_NAME = args.db
    DB_USER = args.user
    DB_HOST = args.host
    print(f"Database: {DB_NAME}")
    print(f"Open: http://localhost:{args.port}")
    app.run(host="127.0.0.1", port=args.port, debug=False)


if __name__ == "__main__":
    main()
