"""Storage layer."""

import json
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor


from agent.config import load_config as _load_config
_cfg = _load_config()
_db_cfg = _cfg.get("database", {})

DB_CONFIG = {
    "dbname": _db_cfg.get("name", "Riverse"),
    "user": _db_cfg.get("user", "postgres"),
    "host": _db_cfg.get("host", "localhost"),
    "options": "-c client_encoding=UTF8",
}


def configure_db(name: str, user: str = "postgres", host: str = "localhost"):
    DB_CONFIG["dbname"] = name
    DB_CONFIG["user"] = user
    DB_CONFIG["host"] = host


def get_db_connection():
    conn = psycopg2.connect(**DB_CONFIG)
    return conn


def _as_dict(row):
    return dict(row) if row else None


def _as_dicts(rows):
    return [dict(r) for r in rows]


_CATEGORY_SYNONYM_GROUPS = [
    {"位置", "居住地", "居住城市", "地点", "住址", "居住", "所在地"},
    {"职业", "职位", "工作", "岗位"},
    {"教育", "教育背景", "学历"},
    {"家乡", "籍贯", "出生地", "老家"},
    {"兴趣", "爱好", "休闲活动", "休闲", "运动", "运动与锻炼"},
    {"感情", "恋爱", "情感", "婚恋"},
    {"出生年份", "年龄", "出生年"},
    {"专业", "学科", "主修"},
    {"娱乐", "游戏"},
    {"宠物", "养宠"},
    {"技能", "技术", "编程"},
    {"身份", "个人信息"},
    {"饮食", "饮食与美食", "美食"},
]

_CAT_SYNONYM_MAP: dict[str, set[str]] = {}
for _group in _CATEGORY_SYNONYM_GROUPS:
    for _name in _group:
        _CAT_SYNONYM_MAP[_name] = _group

_SUBJECT_SYNONYM_GROUPS = [
    {"居住地", "居住城市", "当前居住地", "所在城市"},
    {"职业", "当前职位", "工作", "职位", "岗位"},
    {"学校", "大学", "毕业学校"},
    {"专业", "主修", "学科"},
    {"家乡", "老家", "出生地"},
    {"运动", "体育", "锻炼"},
    {"游戏", "电子游戏"},
    {"出生年", "出生年份"},
    {"女朋友", "女友", "对象"},
    {"男朋友", "男友"},
]

_SUBJ_SYNONYM_MAP: dict[str, set[str]] = {}
for _group in _SUBJECT_SYNONYM_GROUPS:
    for _name in _group:
        _SUBJ_SYNONYM_MAP[_name] = _group


def _get_category_synonyms(category: str) -> set[str]:
    return _CAT_SYNONYM_MAP.get(category, {category})


def _get_subject_synonyms(subject: str) -> set[str]:
    return _SUBJ_SYNONYM_MAP.get(subject, {subject})


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


def save_event(category: str, summary: str, session_id: str | None = None,
               importance: float | None = None, decay_days: int | None = None,
               reference_time=None):
    if importance is None:
        importance = 0.5

    now = reference_time if reference_time else datetime.now()
    if decay_days and decay_days > 0:
        expires_at = now + timedelta(days=decay_days)
    else:
        expires_at = None

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, summary FROM event_log "
                "WHERE category = %s "
                "AND (expires_at IS NULL OR expires_at > %s) "
                "ORDER BY created_at DESC LIMIT 5",
                (category, now),
            )
            rows = cur.fetchall()

            existing_id = None
            for row_id, row_summary in rows:
                if _is_similar_event(row_summary, summary):
                    existing_id = row_id
                    break

            if existing_id:
                cur.execute(
                    "UPDATE event_log SET expires_at = %s, importance = %s WHERE id = %s",
                    (expires_at, importance, existing_id),
                )
            else:
                cur.execute(
                    "INSERT INTO event_log (category, summary, importance, expires_at, source_session) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (category, summary, importance, expires_at, session_id),
                )
        conn.commit()
    finally:
        conn.close()


def _is_similar_event(existing: str, new: str) -> bool:
    STOPWORDS = ["用户", "的", "是", "了", "在", "很", "比较", "非常",
                 "喜欢", "感兴趣", "关注", " ", "。", "，"]
    def clean(s):
        s = s.strip()
        for w in STOPWORDS:
            s = s.replace(w, "")
        return s
    a, b = clean(existing), clean(new)
    if not a or not b:
        return True
    return a == b or a in b or b in a


def load_active_events(top_k: int = 10, category: str | None = None) -> list[dict]:
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            conditions = ["(expires_at IS NULL OR expires_at > NOW())"]
            params: list = []
            if category:
                conditions.append("category = %s")
                params.append(category)
            where = "WHERE " + " AND ".join(conditions)
            params.append(top_k)
            cur.execute(
                f"SELECT id, category, summary, importance, expires_at, created_at "
                f"FROM event_log {where} "
                f"ORDER BY importance DESC, created_at DESC "
                f"LIMIT %s",
                params,
            )
            return _as_dicts(cur.fetchall())
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



def _find_existing_hypothesis(cur, category: str, subject: str):
    _FIELDS = "id, claim, evidence_for, confidence, status, suspected_value, mention_count"
    _STATUS_SET = "('pending', 'active', 'established', 'suspected', 'dormant', 'confirmed')"
    _ORDER = (
        "ORDER BY CASE status "
        "  WHEN 'established' THEN 1 WHEN 'active' THEN 2 WHEN 'pending' THEN 3 "
        "  WHEN 'suspected' THEN 4 WHEN 'dormant' THEN 5 WHEN 'confirmed' THEN 6 "
        "END LIMIT 1"
    )
    cur.execute(
        f"SELECT {_FIELDS} FROM hypotheses "
        f"WHERE category = %s AND subject = %s "
        f"AND status IN {_STATUS_SET} "
        f"{_ORDER}",
        (category, subject),
    )
    row = cur.fetchone()
    if row:
        return row
    cat_syns = _get_category_synonyms(category)
    subj_syns = _get_subject_synonyms(subject)
    all_cats = list(cat_syns)
    all_subjs = list(subj_syns)
    if len(all_cats) > 1 or len(all_subjs) > 1:
        cur.execute(
            f"SELECT {_FIELDS} FROM hypotheses "
            f"WHERE category = ANY(%s) AND subject = ANY(%s) "
            f"AND status IN {_STATUS_SET} "
            f"{_ORDER}",
            (all_cats, all_subjs),
        )
        row = cur.fetchone()
        if row:
            return row
    cur.execute(
        f"SELECT {_FIELDS} FROM hypotheses "
        f"WHERE category = ANY(%s) AND status IN {_STATUS_SET} "
        f"AND (subject ILIKE '%%' || %s || '%%' OR %s ILIKE '%%' || subject || '%%') "
        f"{_ORDER}",
        (all_cats, subject, subject),
    )
    row = cur.fetchone()
    if row:
        return row
    return None


def save_hypothesis(category: str, subject: str, claim: str,
                    evidence_for: list | None = None,
                    confidence: float = 0.5,
                    source_type: str = 'stated',
                    decay_days: int | None = None,
                    start_time=None) -> int:
    if evidence_for is None:
        evidence_for = []
    now = start_time if start_time else datetime.now()
    if not decay_days or decay_days <= 0:
        decay_days = 365
    expires_at = now + timedelta(days=decay_days)
    confidence = 0.5
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            row = _find_existing_hypothesis(cur, category, subject)

            if row:
                (existing_id, existing_claim, existing_evidence, existing_conf,
                 existing_status, suspected_value, existing_mention_count) = row
                existing_evidence = existing_evidence if existing_evidence else []
                existing_mention_count = existing_mention_count or 1

                if existing_claim and existing_claim.strip() != claim.strip() and existing_status != 'dormant':
                    if suspected_value:
                        evidence_entry = {
                            "reason": f"新观察支持: {claim}",
                        }
                        cur.execute("SELECT suspected_evidence FROM hypotheses WHERE id = %s", (existing_id,))
                        se_row = cur.fetchone()
                        if se_row:
                            suspected_ev = se_row[0] if se_row[0] else []
                            suspected_ev.append(evidence_entry)
                            cur.execute(
                                "UPDATE hypotheses SET suspected_evidence = %s, "
                                "status = 'suspected', last_updated_at = %s WHERE id = %s",
                                (json.dumps(suspected_ev, ensure_ascii=False), now, existing_id),
                            )
                    else:
                        cur.execute(
                            "UPDATE hypotheses SET suspected_value = %s, "
                            "suspected_since = %s, suspected_evidence = '[]', "
                            "status = 'suspected', last_updated_at = %s "
                            "WHERE id = %s",
                            (claim, now, now, existing_id),
                        )
                    conn.commit()
                    return existing_id

                new_mention_count = existing_mention_count + 1
                merged_evidence = existing_evidence + evidence_for

                new_status = existing_status
                if existing_status == 'dormant':
                    new_status = 'active'

                cur.execute(
                    "UPDATE hypotheses SET claim = %s, evidence_for = %s, "
                    "confidence = 0.5, mention_count = %s, status = %s, "
                    "last_updated_at = %s, "
                    "decay_days = COALESCE(%s, decay_days), "
                    "expires_at = COALESCE(%s, expires_at) "
                    "WHERE id = %s",
                    (claim, json.dumps(merged_evidence, ensure_ascii=False),
                     new_mention_count, new_status, now,
                     decay_days, expires_at, existing_id),
                )
                conn.commit()
                return existing_id
            else:
                effective_decay = decay_days
                effective_expires = now + timedelta(days=effective_decay)
                try:
                    cur.execute(
                        "INSERT INTO hypotheses "
                        "(category, subject, claim, evidence_for, confidence, "
                        " mention_count, status, source_type, "
                        " decay_days, expires_at, first_seen_at, last_updated_at) "
                        "VALUES (%s, %s, %s, %s, 0.5, 1, 'active', %s, %s, %s, %s, %s) "
                        "RETURNING id",
                        (category, subject, claim,
                         json.dumps(evidence_for, ensure_ascii=False),
                         source_type,
                         effective_decay, effective_expires, now, now),
                    )
                    hyp_id = cur.fetchone()[0]
                    conn.commit()
                    return hyp_id
                except Exception:
                    conn.rollback()
                    cur.execute(
                        "SELECT id FROM hypotheses WHERE category = %s AND subject = %s "
                        "ORDER BY last_updated_at DESC LIMIT 1",
                        (category, subject),
                    )
                    fallback = cur.fetchone()
                    return fallback[0] if fallback else -1
    finally:
        conn.close()


def update_hypothesis_evidence(hypothesis_id: int,
                               evidence_for: dict | None = None,
                               evidence_against: dict | None = None,
                               new_confidence: float | None = None,
                               supports_suspected: bool = False,
                               reference_time=None) -> bool:
    now = reference_time if reference_time else datetime.now()
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT evidence_for, evidence_against, confidence, suspected_value, mention_count "
                "FROM hypotheses WHERE id = %s",
                (hypothesis_id,),
            )
            row = cur.fetchone()
            if not row:
                return False

            cur_for = row[0] if row[0] else []
            cur_against = row[1] if row[1] else []
            has_suspected = bool(row[3])
            cur_mention_count = row[4] if row[4] is not None else 1

            if has_suspected and supports_suspected and evidence_for:
                conn.close()
                update_suspected_evidence(hypothesis_id, evidence_for)
                return True

            if evidence_for:
                cur_for.append(evidence_for)
            if evidence_against:
                cur_against.append(evidence_against)

            new_mention_count = cur_mention_count
            if evidence_for:
                new_mention_count = cur_mention_count + 1

            cur.execute("SELECT decay_days FROM hypotheses WHERE id = %s", (hypothesis_id,))
            decay_row = cur.fetchone()
            decay = decay_row[0] if decay_row and decay_row[0] and decay_row[0] > 0 else 365
            refreshed_expires = now + timedelta(days=decay)

            cur.execute(
                "UPDATE hypotheses SET evidence_for = %s, evidence_against = %s, "
                "mention_count = %s, last_updated_at = %s, expires_at = %s "
                "WHERE id = %s",
                (json.dumps(cur_for, ensure_ascii=False),
                 json.dumps(cur_against, ensure_ascii=False),
                 new_mention_count, now, refreshed_expires,
                 hypothesis_id),
            )
        conn.commit()
        return True
    finally:
        conn.close()


def load_active_hypotheses(category: str | None = None,
                           min_confidence: float = 0.0) -> list[dict]:
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            conditions = [
                "status IN ('pending', 'active', 'established', 'suspected', 'confirmed')",
            ]
            params: list = []
            if category:
                conditions.append("category = %s")
                params.append(category)
            where = "WHERE " + " AND ".join(conditions)
            cur.execute(
                f"SELECT id, category, subject, claim, evidence_for, evidence_against, "
                f"confidence, mention_count, status, source_type, decay_days, expires_at, "
                f"first_seen_at, last_updated_at, "
                f"suspected_value, suspected_confidence, suspected_since, suspected_evidence, history "
                f"FROM hypotheses {where} "
                f"ORDER BY CASE status "
                f"  WHEN 'established' THEN 1 WHEN 'active' THEN 2 WHEN 'confirmed' THEN 3 "
                f"  WHEN 'suspected' THEN 4 WHEN 'pending' THEN 5 "
                f"END, mention_count DESC",
                params,
            )
            return _as_dicts(cur.fetchall())
    finally:
        conn.close()


def get_expired_hypotheses() -> list[dict]:
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id, category, subject, claim, confidence, status, "
                "mention_count, decay_days, expires_at, first_seen_at, last_updated_at "
                "FROM hypotheses "
                "WHERE expires_at IS NOT NULL AND expires_at < NOW() "
                "AND status IN ('pending', 'active', 'established', 'confirmed') "
                "ORDER BY expires_at ASC"
            )
            return _as_dicts(cur.fetchall())
    finally:
        conn.close()


def get_hypothesis_by_subject(category: str, subject: str) -> dict | None:
    _FIELDS = (
        "id, category, subject, claim, evidence_for, evidence_against, "
        "confidence, mention_count, source_type, status, first_seen_at, last_updated_at, "
        "suspected_value, suspected_confidence, suspected_since, suspected_evidence, history"
    )
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _STATUS_FILTER = "status IN ('pending', 'active', 'established', 'suspected', 'confirmed')"
            cur.execute(
                f"SELECT {_FIELDS} FROM hypotheses "
                f"WHERE category = %s AND subject = %s AND {_STATUS_FILTER}",
                (category, subject),
            )
            result = cur.fetchone()
            if result:
                return result
            cat_syns = list(_get_category_synonyms(category))
            subj_syns = list(_get_subject_synonyms(subject))
            if len(cat_syns) > 1 or len(subj_syns) > 1:
                cur.execute(
                    f"SELECT {_FIELDS} FROM hypotheses "
                    f"WHERE category = ANY(%s) AND subject = ANY(%s) AND {_STATUS_FILTER} "
                    f"LIMIT 1",
                    (cat_syns, subj_syns),
                )
                result = cur.fetchone()
                if result:
                    return result
            cur.execute(
                f"SELECT {_FIELDS} FROM hypotheses "
                f"WHERE subject = %s AND {_STATUS_FILTER}",
                (subject,),
            )
            result = cur.fetchone()
            if result:
                return result
            if len(subj_syns) > 1:
                cur.execute(
                    f"SELECT {_FIELDS} FROM hypotheses "
                    f"WHERE subject = ANY(%s) AND {_STATUS_FILTER} "
                    f"LIMIT 1",
                    (subj_syns,),
                )
                result = cur.fetchone()
                if result:
                    return result
            cur.execute(
                f"SELECT {_FIELDS} FROM hypotheses "
                f"WHERE category = ANY(%s) AND {_STATUS_FILTER} "
                "AND (subject ILIKE '%%' || %s || '%%' OR %s ILIKE '%%' || subject || '%%') "
                "ORDER BY mention_count DESC LIMIT 1",
                (cat_syns, subject, subject),
            )
            result = cur.fetchone()
            if result:
                return result
            return None
    finally:
        conn.close()


def enter_suspicion_mode(hypothesis_id: int, suspected_value: str):
    now = datetime.now()
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE hypotheses SET "
                "status = 'suspected', "
                "suspected_value = %s, suspected_confidence = 0, "
                "suspected_since = %s, suspected_evidence = '[]', "
                "last_updated_at = %s "
                "WHERE id = %s",
                (suspected_value, now, now, hypothesis_id),
            )
        conn.commit()
    finally:
        conn.close()


def update_suspected_evidence(hypothesis_id: int, evidence: dict):
    now = datetime.now()
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT suspected_evidence FROM hypotheses WHERE id = %s",
                (hypothesis_id,),
            )
            row = cur.fetchone()
            if not row:
                return
            cur_evidence = row[0] if row[0] else []
            cur_evidence.append(evidence)
            cur.execute(
                "UPDATE hypotheses SET suspected_evidence = %s, "
                "last_updated_at = %s WHERE id = %s",
                (json.dumps(cur_evidence, ensure_ascii=False), now, hypothesis_id),
            )
        conn.commit()
    finally:
        conn.close()


def resolve_suspicion(hypothesis_id: int, accept: bool):
    now = datetime.now()
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT claim, confidence, evidence_for, evidence_against, "
                "first_seen_at, suspected_value, suspected_confidence, "
                "suspected_since, suspected_evidence, history, mention_count "
                "FROM hypotheses WHERE id = %s",
                (hypothesis_id,),
            )
            row = cur.fetchone()
            if not row:
                return
            (old_claim, old_confidence, old_evidence_for, old_evidence_against,
             old_first_seen, suspected_value, suspected_confidence,
             suspected_since, suspected_evidence, history, mention_count) = row

            if accept:
                history = history if history else []
                old_from = old_first_seen.strftime("%Y-%m-%d") if old_first_seen else "?"
                old_to = now.strftime("%Y-%m-%d")
                history.append({
                    "value": old_claim,
                    "from": old_from,
                    "to": old_to,
                    "mention_count": mention_count or 1,
                })

                suspected_evidence = suspected_evidence if suspected_evidence else []
                cur.execute(
                    "UPDATE hypotheses SET "
                    "claim = %s, confidence = 0.5, "
                    "status = 'active', mention_count = 2, "
                    "evidence_for = %s, evidence_against = '[]', "
                    "first_seen_at = %s, "
                    "suspected_value = NULL, suspected_confidence = 0, "
                    "suspected_since = NULL, suspected_evidence = '[]', "
                    "history = %s, last_updated_at = %s "
                    "WHERE id = %s",
                    (suspected_value,
                     json.dumps(suspected_evidence, ensure_ascii=False),
                     suspected_since, json.dumps(history, ensure_ascii=False),
                     now, hypothesis_id),
                )
            else:
                mc = mention_count or 1
                if mc >= 4:
                    restored_status = 'established'
                elif mc >= 2:
                    restored_status = 'active'
                else:
                    restored_status = 'pending'

                old_evidence_against = old_evidence_against if old_evidence_against else []
                suspected_evidence = suspected_evidence if suspected_evidence else []
                for se in suspected_evidence:
                    old_evidence_against.append({
                        "reason": f"[驳回] {se.get('reason', '')}",
                    })
                cur.execute(
                    "UPDATE hypotheses SET "
                    "status = %s, "
                    "suspected_value = NULL, suspected_confidence = 0, "
                    "suspected_since = NULL, suspected_evidence = '[]', "
                    "evidence_against = %s, last_updated_at = %s "
                    "WHERE id = %s",
                    (restored_status,
                     json.dumps(old_evidence_against, ensure_ascii=False),
                     now, hypothesis_id),
                )
        conn.commit()
    finally:
        conn.close()


def upgrade_hypothesis_decay(hypothesis_id: int, new_decay_days: int,
                             reference_time=None):
    now = reference_time if reference_time else datetime.now()
    new_expires = now + timedelta(days=new_decay_days)
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE hypotheses SET decay_days = %s, expires_at = %s, last_updated_at = %s "
                "WHERE id = %s",
                (new_decay_days, new_expires, now, hypothesis_id),
            )
        conn.commit()
    finally:
        conn.close()


def set_hypothesis_status(hypothesis_id: int, status: str):
    now = datetime.now()
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE hypotheses SET status = %s, last_updated_at = %s WHERE id = %s",
                (status, now, hypothesis_id),
            )
        conn.commit()
    finally:
        conn.close()



def upsert_profile(category: str, field: str, value: str,
                   hypothesis_id: int | None = None):
    now = datetime.now()
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO current_profile (category, field, value, hypothesis_id, confirmed_at, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (category, field, value) DO UPDATE "
                "SET hypothesis_id = %s, updated_at = %s",
                (category, field, value, hypothesis_id, now, now,
                 hypothesis_id, now),
            )
        conn.commit()
    finally:
        conn.close()


def load_current_profile() -> list[dict]:
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id, category, field, value, hypothesis_id, confirmed_at, updated_at "
                "FROM current_profile "
                "ORDER BY category, field"
            )
            return _as_dicts(cur.fetchall())
    finally:
        conn.close()


def remove_profile(category: str, field: str, value: str | None = None):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            if value:
                cur.execute(
                    "DELETE FROM current_profile WHERE category = %s AND field = %s AND value = %s",
                    (category, field, value),
                )
            else:
                cur.execute(
                    "DELETE FROM current_profile WHERE category = %s AND field = %s",
                    (category, field),
                )
        conn.commit()
    finally:
        conn.close()



def upsert_user_model(dimension: str, assessment: str,
                      evidence_summary: str | None = None,
                      reference_time=None):
    if isinstance(evidence_summary, (dict, list)):
        evidence_summary = json.dumps(evidence_summary, ensure_ascii=False)
    now = reference_time or datetime.now()
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO user_model (dimension, assessment, evidence_summary, updated_at) "
                "VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (dimension) DO UPDATE "
                "SET assessment = %s, evidence_summary = %s, updated_at = %s",
                (dimension, assessment, evidence_summary, now,
                 assessment, evidence_summary, now),
            )
        conn.commit()
    finally:
        conn.close()


def load_user_model() -> list[dict]:
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id, dimension, assessment, evidence_summary, updated_at "
                "FROM user_model ORDER BY dimension"
            )
            return _as_dicts(cur.fetchall())
    finally:
        conn.close()



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




def save_trajectory_summary(trajectory: dict, session_count: int = 0,
                            reference_time=None):
    def _text(val):
        if isinstance(val, (dict, list)):
            return json.dumps(val, ensure_ascii=False)
        return val if val is not None else ""

    now = reference_time or datetime.now()
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO trajectory_summary "
                "(life_phase, phase_characteristics, trajectory_direction, "
                " stability_assessment, key_anchors, volatile_areas, "
                " recent_momentum, predicted_shifts, full_summary, "
                " session_count, created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    _text(trajectory.get("life_phase", "")),
                    _text(trajectory.get("phase_characteristics", "")),
                    _text(trajectory.get("trajectory_direction", "")),
                    _text(trajectory.get("stability_assessment", "")),
                    json.dumps(trajectory.get("key_anchors", []), ensure_ascii=False),
                    json.dumps(trajectory.get("volatile_areas", []), ensure_ascii=False),
                    _text(trajectory.get("recent_momentum", "")),
                    _text(trajectory.get("predicted_shifts", "")),
                    _text(trajectory.get("full_summary", "")),
                    session_count, now, now,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def load_trajectory_summary() -> dict | None:
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM trajectory_summary ORDER BY updated_at DESC LIMIT 1"
            )
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()



def save_or_update_relationship(name: str | None, relation: str,
                                 details: dict | None = None,
                                 reference_time=None) -> int:
    now = reference_time or datetime.now()
    details = details or {}
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            if name:
                cur.execute(
                    "SELECT id, details, mention_count FROM relationships "
                    "WHERE name = %s AND relation = %s AND status = 'active' "
                    "ORDER BY id LIMIT 1",
                    (name, relation),
                )
            else:
                cur.execute(
                    "SELECT id, details, mention_count FROM relationships "
                    "WHERE name IS NULL AND relation = %s AND status = 'active' "
                    "ORDER BY id LIMIT 1",
                    (relation,),
                )
            row = cur.fetchone()
            if row:
                rid, old_details_raw, mc = row
                old_details = old_details_raw if isinstance(old_details_raw, dict) else json.loads(old_details_raw or "{}")
                merged = {**old_details, **details}
                cur.execute(
                    "UPDATE relationships SET details = %s, mention_count = %s, "
                    "last_mentioned_at = %s WHERE id = %s",
                    (json.dumps(merged, ensure_ascii=False), mc + 1, now, rid),
                )
                conn.commit()
                return rid
            else:
                cur.execute(
                    "INSERT INTO relationships (name, relation, details, "
                    "first_mentioned_at, last_mentioned_at, mention_count) "
                    "VALUES (%s, %s, %s, %s, %s, 1) RETURNING id",
                    (name, relation, json.dumps(details, ensure_ascii=False), now, now),
                )
                rid = cur.fetchone()[0]
                conn.commit()
                return rid
    finally:
        conn.close()


def load_relationships(status: str = "active") -> list[dict]:
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id, name, relation, details, mention_count, "
                "first_mentioned_at, last_mentioned_at "
                "FROM relationships WHERE status = %s "
                "ORDER BY last_mentioned_at DESC",
                (status,),
            )
            return _as_dicts(cur.fetchall())
    finally:
        conn.close()





def save_profile_fact(category: str, subject: str, value: str,
                      source_type: str = 'stated',
                      decay_days: int | None = None,
                      evidence: list | None = None,
                      start_time=None) -> int:
    if not start_time:
        start_time = datetime.now()
    now = start_time
    if evidence is None:
        evidence = []
    if not decay_days or decay_days <= 0:
        decay_days = 365
    expires_at = now + timedelta(days=decay_days)

    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            existing = _find_current_fact_cursor(cur, category, subject)

            if existing:
                if existing["value"].strip().lower() == value.strip().lower():
                    old_evidence = existing["evidence"] if existing["evidence"] else []
                    merged = old_evidence + evidence
                    new_mc = (existing["mention_count"] or 1) + 1
                    new_expires = now + timedelta(days=decay_days)
                    cur.execute(
                        "UPDATE user_profile SET mention_count = %s, evidence = %s, "
                        "updated_at = %s, expires_at = %s "
                        "WHERE id = %s",
                        (new_mc, json.dumps(merged, ensure_ascii=False),
                         now, new_expires, existing["id"]),
                    )
                    conn.commit()
                    return existing["id"]
                elif existing["category"] in ("兴趣",):
                    cur.execute(
                        "SELECT id, evidence, mention_count FROM user_profile "
                        "WHERE category = %s AND subject = %s "
                        "AND LOWER(TRIM(value)) = LOWER(TRIM(%s)) "
                        "AND end_time IS NULL LIMIT 1",
                        (existing["category"], existing["subject"], value),
                    )
                    exact_match = cur.fetchone()
                    if exact_match:
                        old_ev = exact_match["evidence"] if exact_match["evidence"] else []
                        merged_ev = old_ev + evidence
                        new_mc = (exact_match["mention_count"] or 1) + 1
                        new_expires = now + timedelta(days=decay_days)
                        cur.execute(
                            "UPDATE user_profile SET mention_count = %s, evidence = %s, "
                            "updated_at = %s, expires_at = %s WHERE id = %s",
                            (new_mc, json.dumps(merged_ev, ensure_ascii=False),
                             now, new_expires, exact_match["id"]),
                        )
                        conn.commit()
                        return exact_match["id"]
                    else:
                        cur.execute(
                            "INSERT INTO user_profile "
                            "(category, subject, value, layer, source_type, "
                            " start_time, decay_days, expires_at, evidence, "
                            " mention_count, created_at, updated_at) "
                            "VALUES (%s, %s, %s, 'suspected', %s, %s, %s, %s, %s, "
                            "1, %s, %s) "
                            "RETURNING id",
                            (category, subject, value, source_type,
                             start_time, decay_days, expires_at,
                             json.dumps(evidence, ensure_ascii=False),
                             now, now),
                        )
                        new_id = cur.fetchone()["id"]
                        conn.commit()
                        return new_id
                else:
                    cur.execute(
                        "INSERT INTO user_profile "
                        "(category, subject, value, layer, source_type, "
                        " start_time, decay_days, expires_at, evidence, "
                        " mention_count, created_at, updated_at, "
                        " supersedes) "
                        "VALUES (%s, %s, %s, 'suspected', %s, %s, %s, %s, %s, "
                        "1, %s, %s, %s) "
                        "RETURNING id",
                        (category, subject, value, source_type,
                         start_time, decay_days, expires_at,
                         json.dumps(evidence, ensure_ascii=False),
                         now, now, existing["id"]),
                    )
                    new_id = cur.fetchone()["id"]
                    cur.execute(
                        "UPDATE user_profile SET superseded_by = %s WHERE id = %s",
                        (new_id, existing["id"]),
                    )
                    conn.commit()
                    return new_id
            else:
                cur.execute(
                    "INSERT INTO user_profile "
                    "(category, subject, value, layer, source_type, "
                    " start_time, decay_days, expires_at, evidence, "
                    " mention_count, created_at, updated_at) "
                    "VALUES (%s, %s, %s, 'suspected', %s, %s, %s, %s, %s, "
                    "1, %s, %s) "
                    "RETURNING id",
                    (category, subject, value, source_type,
                     start_time, decay_days, expires_at,
                     json.dumps(evidence, ensure_ascii=False),
                     now, now),
                )
                new_id = cur.fetchone()["id"]
                conn.commit()
                return new_id
    finally:
        conn.close()


def close_time_period(fact_id: int, end_time=None, superseded_by: int | None = None,
                      reference_time=None):
    now = reference_time or datetime.now()
    if not end_time:
        end_time = now
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            if superseded_by:
                cur.execute(
                    "UPDATE user_profile SET end_time = %s, updated_at = %s, "
                    "superseded_by = %s WHERE id = %s",
                    (end_time, now, superseded_by, fact_id),
                )
            else:
                cur.execute(
                    "UPDATE user_profile SET end_time = %s, updated_at = %s "
                    "WHERE id = %s",
                    (end_time, now, fact_id),
                )
        conn.commit()
    finally:
        conn.close()


def confirm_profile_fact(fact_id: int, reference_time=None):
    now = reference_time if reference_time else datetime.now()
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE user_profile SET layer = 'confirmed', "
                "confirmed_at = %s, updated_at = %s WHERE id = %s",
                (now, now, fact_id),
            )
        conn.commit()
    finally:
        conn.close()


def add_evidence(fact_id: int, evidence_entry: dict, reference_time=None):
    now = reference_time if reference_time else datetime.now()
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT evidence FROM user_profile WHERE id = %s",
                (fact_id,),
            )
            row = cur.fetchone()
            if not row:
                return
            cur_evidence = row[0] if row[0] else []
            cur_evidence.append(evidence_entry)
            cur.execute(
                "UPDATE user_profile SET evidence = %s, updated_at = %s "
                "WHERE id = %s",
                (json.dumps(cur_evidence, ensure_ascii=False), now, fact_id),
            )
        conn.commit()
    finally:
        conn.close()


def _find_current_fact_cursor(cur, category: str, subject: str):
    _FIELDS = ("id, category, subject, value, layer, source_type, "
               "start_time, end_time, decay_days, expires_at, evidence, "
               "mention_count, created_at, updated_at, confirmed_at, "
               "superseded_by, supersedes")
    _ORDER = "ORDER BY (superseded_by IS NULL) DESC, created_at DESC LIMIT 1"

    cur.execute(
        f"SELECT {_FIELDS} FROM user_profile "
        f"WHERE category = %s AND subject = %s AND end_time IS NULL "
        f"{_ORDER}",
        (category, subject),
    )
    row = cur.fetchone()
    if row:
        return row

    cat_syns = list(_get_category_synonyms(category))
    subj_syns = list(_get_subject_synonyms(subject))
    if len(cat_syns) > 1 or len(subj_syns) > 1:
        cur.execute(
            f"SELECT {_FIELDS} FROM user_profile "
            f"WHERE category = ANY(%s) AND subject = ANY(%s) AND end_time IS NULL "
            f"{_ORDER}",
            (cat_syns, subj_syns),
        )
        row = cur.fetchone()
        if row:
            return row

    cur.execute(
        f"SELECT {_FIELDS} FROM user_profile "
        f"WHERE category = ANY(%s) AND end_time IS NULL "
        f"AND (subject ILIKE '%%' || %s || '%%' OR %s ILIKE '%%' || subject || '%%') "
        f"{_ORDER}",
        (cat_syns, subject, subject),
    )
    row = cur.fetchone()
    if row:
        return row
    return None


def find_current_fact(category: str, subject: str) -> dict | None:
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            row = _find_current_fact_cursor(cur, category, subject)
            return _as_dict(row) if row else None
    finally:
        conn.close()


def load_suspected_profile() -> list[dict]:
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id, category, subject, value, layer, source_type, "
                "start_time, decay_days, expires_at, evidence, mention_count, "
                "created_at, updated_at, supersedes "
                "FROM user_profile "
                "WHERE layer = 'suspected' AND end_time IS NULL "
                "ORDER BY category, subject"
            )
            return _as_dicts(cur.fetchall())
    finally:
        conn.close()


def load_confirmed_profile() -> list[dict]:
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id, category, subject, value, layer, source_type, "
                "start_time, decay_days, expires_at, evidence, mention_count, "
                "created_at, updated_at, confirmed_at, supersedes "
                "FROM user_profile "
                "WHERE layer = 'confirmed' AND end_time IS NULL "
                "ORDER BY category, subject"
            )
            return _as_dicts(cur.fetchall())
    finally:
        conn.close()


def load_full_current_profile(exclude_superseded: bool = False) -> list[dict]:
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            where = "WHERE end_time IS NULL"
            if exclude_superseded:
                where += " AND superseded_by IS NULL"
            cur.execute(
                f"SELECT id, category, subject, value, layer, source_type, "
                f"start_time, decay_days, expires_at, evidence, mention_count, "
                f"created_at, updated_at, confirmed_at, superseded_by, supersedes "
                f"FROM user_profile "
                f"{where} "
                f"ORDER BY CASE layer WHEN 'confirmed' THEN 1 WHEN 'suspected' THEN 2 END, "
                f"category, subject"
            )
            return _as_dicts(cur.fetchall())
    finally:
        conn.close()


def load_timeline(category: str | None = None,
                  subject: str | None = None) -> list[dict]:
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            conditions = []
            params: list = []
            if category:
                conditions.append("category = %s")
                params.append(category)
            if subject:
                conditions.append("subject = %s")
                params.append(subject)
            where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
            cur.execute(
                f"SELECT id, category, subject, value, layer, source_type, "
                f"start_time, end_time, decay_days, expires_at, evidence, "
                f"mention_count, created_at, updated_at, confirmed_at, "
                f"superseded_by, supersedes "
                f"FROM user_profile {where} "
                f"ORDER BY category, subject, start_time",
                params,
            )
            return _as_dicts(cur.fetchall())
    finally:
        conn.close()


def get_expired_facts(reference_time=None) -> list[dict]:
    ref = reference_time if reference_time else datetime.now()
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id, category, subject, value, layer, source_type, "
                "start_time, decay_days, expires_at, evidence, mention_count, "
                "created_at, updated_at "
                "FROM user_profile "
                "WHERE expires_at IS NOT NULL AND expires_at < %s "
                "AND end_time IS NULL "
                "ORDER BY expires_at ASC",
                (ref,)
            )
            return _as_dicts(cur.fetchall())
    finally:
        conn.close()


def load_disputed_facts() -> list[dict]:
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id, category, subject, value, layer, source_type, "
                "start_time, decay_days, expires_at, evidence, mention_count, "
                "created_at, updated_at, confirmed_at, superseded_by "
                "FROM user_profile "
                "WHERE superseded_by IS NOT NULL AND end_time IS NULL "
                "ORDER BY category, subject"
            )
            old_records = list(cur.fetchall())

            pairs = []
            for old in old_records:
                new_id = old["superseded_by"]
                cur.execute(
                    "SELECT id, category, subject, value, layer, source_type, "
                    "start_time, decay_days, expires_at, evidence, mention_count, "
                    "created_at, updated_at, supersedes "
                    "FROM user_profile WHERE id = %s AND end_time IS NULL",
                    (new_id,),
                )
                new = cur.fetchone()
                if new:
                    pairs.append({"old": dict(old), "new": dict(new)})
            return pairs
    finally:
        conn.close()


def resolve_dispute(old_fact_id: int, new_fact_id: int, accept_new: bool,
                    resolution_time=None):
    now = resolution_time or datetime.now()
    end_time = now
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            if accept_new:
                cur.execute(
                    "UPDATE user_profile SET end_time = %s, updated_at = %s "
                    "WHERE id = %s",
                    (end_time, now, old_fact_id),
                )
            else:
                cur.execute(
                    "UPDATE user_profile SET end_time = %s, updated_at = %s "
                    "WHERE id = %s",
                    (end_time, now, new_fact_id),
                )
                cur.execute(
                    "UPDATE user_profile SET superseded_by = NULL, updated_at = %s "
                    "WHERE id = %s",
                    (now, old_fact_id),
                )
        conn.commit()
    finally:
        conn.close()


def update_fact_decay(fact_id: int, new_decay_days: int, reference_time=None):
    now = reference_time if reference_time else datetime.now()
    new_expires = now + timedelta(days=new_decay_days)
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE user_profile SET decay_days = %s, expires_at = %s, "
                "updated_at = %s WHERE id = %s",
                (new_decay_days, new_expires, now, fact_id),
            )
        conn.commit()
    finally:
        conn.close()


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




def parse_turns(row: dict) -> list[dict]:
    source = row["source"]
    content = row["content"]
    conversation_time = row["conversation_time"]

    if isinstance(content, str):
        content = json.loads(content)

    if source == "claude":
        return _parse_claude(content, conversation_time)
    elif source == "chatgpt":
        return _parse_chatgpt(content, conversation_time)
    elif source == "gemini":
        return _parse_gemini(content, conversation_time)
    elif source == "demo":
        return _parse_demo(content, conversation_time)
    else:
        return []


def _parse_claude(content: dict, conversation_time) -> list[dict]:
    messages = content.get("chat_messages", [])
    turns = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        if msg.get("sender") == "human":
            user_text = ""
            for part in msg.get("content", []):
                if isinstance(part, dict) and part.get("type") == "text":
                    user_text += part.get("text", "")
                elif isinstance(part, str):
                    user_text += part

            assistant_text = ""
            if i + 1 < len(messages) and messages[i + 1].get("sender") == "assistant":
                for part in messages[i + 1].get("content", []):
                    if isinstance(part, dict) and part.get("type") == "text":
                        assistant_text += part.get("text", "")
                    elif isinstance(part, str):
                        assistant_text += part
                i += 2
            else:
                i += 1

            if user_text.strip():
                turns.append({
                    "user_input": user_text.strip(),
                    "assistant_reply": assistant_text.strip(),
                    "timestamp": conversation_time,
                })
        else:
            i += 1
    return turns


def _parse_chatgpt(content: dict, conversation_time) -> list[dict]:
    mapping = content.get("mapping", {})

    msgs = []
    for node_id, node in mapping.items():
        msg = node.get("message")
        if not msg:
            continue
        author = msg.get("author", {}).get("role", "")
        parts = msg.get("content", {}).get("parts", [])
        text = ""
        for p in parts:
            if isinstance(p, str):
                text += p
        create_time = msg.get("create_time")
        if text.strip() and author in ("user", "assistant"):
            msgs.append({
                "role": author,
                "text": text.strip(),
                "create_time": create_time,
            })

    msgs.sort(key=lambda m: m["create_time"] or 0)

    turns = []
    i = 0
    while i < len(msgs):
        if msgs[i]["role"] == "user":
            user_text = msgs[i]["text"]
            ts = msgs[i]["create_time"]
            from datetime import timezone
            if ts:
                timestamp = datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None)
            else:
                timestamp = conversation_time

            assistant_text = ""
            if i + 1 < len(msgs) and msgs[i + 1]["role"] == "assistant":
                assistant_text = msgs[i + 1]["text"]
                i += 2
            else:
                i += 1

            turns.append({
                "user_input": user_text,
                "assistant_reply": assistant_text,
                "timestamp": timestamp,
            })
        else:
            i += 1
    return turns


def _parse_gemini(content: dict, conversation_time) -> list[dict]:
    prompt = content.get("prompt", "")
    response = content.get("response", "")

    if not prompt or not isinstance(prompt, str):
        return []

    return [{
        "user_input": prompt.strip(),
        "assistant_reply": (response or "").strip(),
        "timestamp": conversation_time,
    }]


def _parse_demo(content: dict, conversation_time) -> list[dict]:
    messages = content.get("messages", [])
    turns = []
    for msg in messages:
        if isinstance(msg, dict):
            user = msg.get("user", "").strip()
            assistant = msg.get("assistant", "").strip()
            if user:
                turns.append({
                    "user_input": user,
                    "assistant_reply": assistant,
                    "timestamp": conversation_time,
                })
    return turns


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
