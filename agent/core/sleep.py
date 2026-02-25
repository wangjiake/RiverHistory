"""
睡觉脚本 — 离线批量处理当天的对话（v15 — 矛盾处理重构）。

v15 核心变化（相对 v14）：
  - Step 4c 不再用 LLM 当场判断矛盾，只做基本过滤后直接创建 dispute pair
  - 真正的判断交给 dispute resolution（Step 5.1），它能看到跨会话积累的证据
  - dispute resolution 给 LLM 精确的时间线：矛盾创建时间 + 之前的观察 + 之后的观察
  - 时间趋势比提及次数更重要

工作流程：
  0. 预加载：画像、轨迹（贯穿全流程的全局上下文）
  1. 读取未处理对话
  Per-session:
    2. 提取观察 + 标签（合并，1次LLM）→ observations + session_tags
    3. 提取事件 → event_log
  Global:
    3.5 行为模式分析（跨观察聚合推理）
    4. 画像更新 + 策略生成（合并，带时间标记 + 轨迹）→ user_profile + strategies
      4c: 矛盾标记（基本过滤后直接创建 dispute pair，不用 LLM）
    5. 交叉验证（suspected facts with corroborating evidence → confirmed）
    5.1 矛盾争议解决（精确时间线 + LLM 判断）
    5.5 过期处理（过期事实 → close_time_period）
    5.7 成熟度演进
    6. 分析用户模型 → user_model
    7. 更新轨迹总结（条件触发）
    8. 标记已处理

可手动调用：python3 -m agent.sleep
"""

import json
from datetime import datetime, timedelta
from agent.config import load_config
from agent.utils.llm_client import call_llm
from psycopg2.extras import RealDictCursor
from agent.core.sleep_prompts import get_prompt, get_label
from agent.storage import (
    get_db_connection, save_event, save_session_tag, load_existing_tags,
    save_observation, update_observation_classification, load_observations,
    load_observations_by_time_range,
    load_conversation_summaries_around,
    load_summaries_by_observation_subject,
    # v14: 新画像函数
    save_profile_fact, close_time_period, confirm_profile_fact,
    add_evidence, find_current_fact,
    load_suspected_profile, load_confirmed_profile,
    load_full_current_profile, load_timeline,
    get_expired_facts, update_fact_decay,
    load_disputed_facts, resolve_dispute,
    # 保留兼容
    upsert_user_model, load_user_model,
    save_strategy,
    save_trajectory_summary, load_trajectory_summary,
    load_active_events,
    save_or_update_relationship, load_relationships,
)


# (Prompts moved to sleep_prompts.py — use get_prompt(name, language))


# ══════════════════════════════════════════════════════════════
# 通用工具
# ══════════════════════════════════════════════════════════════

def _format_trajectory_block(trajectory: dict | None, language: str = "zh") -> str:
    """把轨迹总结格式化为可嵌入 prompt 的文本块。"""
    if not trajectory or not trajectory.get("life_phase"):
        return get_label("no_trajectory", language)
    return (
        f"{get_label('trajectory_header', language)}"
        f"{get_label('phase', language)}{trajectory.get('life_phase', '?')}\n"
        f"{get_label('characteristics', language)}{trajectory.get('phase_characteristics', '?')}\n"
        f"{get_label('direction', language)}{trajectory.get('trajectory_direction', '?')}\n"
        f"{get_label('stability', language)}{trajectory.get('stability_assessment', '?')}\n"
        f"{get_label('anchors', language)}{json.dumps(trajectory.get('key_anchors', []), ensure_ascii=False)}\n"
        f"{get_label('volatile', language)}{json.dumps(trajectory.get('volatile_areas', []), ensure_ascii=False)}\n"
        f"{get_label('momentum', language)}{trajectory.get('recent_momentum', '?')}\n"
        f"{get_label('summary', language)}{trajectory.get('full_summary', '?')}\n"
    )


# (PRE_MATCH removed — replaced by classify_observations in Step 4a)


def _format_profile_for_llm(profile: list[dict], timeline: list[dict] | None = None,
                            language: str = "zh") -> str:
    """把画像列表格式化为 LLM 可读文本（v14: 双层画像 + 时间线）。"""
    if not profile:
        return get_label("no_profile", language)
    text = ""
    for p in profile:
        ev = p.get("evidence", [])
        layer = p.get("layer", "suspected")
        mention_count = p.get("mention_count", 1) or 1
        start = p["start_time"].strftime("%m-%d") if p.get("start_time") else "?"
        updated = p["updated_at"].strftime("%m-%d") if p.get("updated_at") else "?"
        fact_id = p.get("id", "?")
        # 矛盾标记
        if p.get("superseded_by"):
            layer_tag = get_label("layer_conflict", language)
        elif layer == "confirmed":
            layer_tag = get_label("layer_confirmed", language)
        else:
            layer_tag = get_label("layer_suspected", language)

        mention_fmt = get_label("mention_fmt", language)
        line = (
            f"#{fact_id} {layer_tag} [{p['category']}] {p['subject']}: {p['value']} "
            + mention_fmt.format(mc=mention_count, src=p.get('source_type', 'stated'),
                                 start=start, updated=updated, ev=len(ev))
        )
        if p.get("superseded_by"):
            line += get_label("challenged_by", language).format(sid=p['superseded_by'])
        if p.get("supersedes"):
            line += get_label("challenges", language).format(sid=p['supersedes'])
        line += ")\n"
        text += line

    # 附加时间线（已关闭的时间段）
    if timeline:
        closed = [t for t in timeline if t.get("end_time")]
        if closed:
            text += get_label("closed_periods_header", language)
            for t in closed:
                start = t["start_time"].strftime("%Y-%m-%d") if t.get("start_time") else "?"
                end = t["end_time"].strftime("%Y-%m-%d") if t.get("end_time") else "?"
                text += (
                    f"  [{t['category']}] {t['subject']}: {t['value']} "
                    f"({start} ~ {end})\n"
                )
    return text


# 兴趣成熟度演进阈值（min_span_days, min_evidence_count, target_decay）
_MATURITY_TIERS = [
    (730, 10, 730),   # 2年+10条证据 → 终身特质
    (365, 6, 365),    # 1年+6条证据 → 长期
    (90, 3, 180),     # 3个月+3条证据 → 中期
]


def _calculate_maturity_decay(span_days: int, evidence_count: int,
                               current_decay: int, in_key_anchors: bool = False) -> int:
    """计算假设的成熟度 decay_days。锚点加速：门槛降至60%。"""
    boost = 0.6 if in_key_anchors else 1.0
    for min_span, min_ev, target in _MATURITY_TIERS:
        if (span_days >= min_span * boost
                and evidence_count >= max(1, int(min_ev * boost))
                and target > current_decay):
            return target
    return current_decay


# ══════════════════════════════════════════════════════════════
# 提取函数
# ══════════════════════════════════════════════════════════════

def extract_observations_and_tags(conversations: list[dict], config: dict,
                                   existing_profile: list[dict] | None = None,
                                   language: str = "zh") -> dict:
    """Step 2: 从对话中提取观察 + 标签（v14: 使用 user_profile 画像）"""
    llm_config = config.get("llm", {})

    text = ""
    msg_index = 0
    for msg in conversations:
        ts = msg.get("user_input_at")
        time_str = ts.strftime("%Y-%m-%d %H:%M") if hasattr(ts, 'strftime') else ""
        prefix = f"[{time_str}] " if time_str else ""
        intent = msg.get('intent', '')
        intent_tag = f" [意图: {intent}]" if intent else ""
        msg_index += 1
        text += f"{prefix}[msg-{msg_index}] 用户：{msg.get('ai_summary') or msg['user_input']}{intent_tag}\n"
        # 加入 AI 回复作为上下文（截断避免过长）
        reply = msg.get('assistant_reply', '')
        if reply:
            if len(reply) > 200:
                reply = reply[:200] + "..."
            text += f"{prefix}助手：{reply}\n"
        text += "\n"
    total_user_msgs = msg_index

    if not text.strip():
        return {"observations": [], "tags": []}

    # 组装已知信息块（当前画像，双层标签）
    known_lines = []
    if existing_profile:
        for p in existing_profile:
            layer = p.get("layer", "suspected")
            layer_tag = get_label("layer_confirmed", language) if layer == "confirmed" else get_label("layer_suspected", language)
            known_lines.append(
                f"  {layer_tag} [{p['category']}] {p['subject']}: {p['value']}"
            )

    if known_lines:
        known_block = "已知信息（用于判断 contradiction）：\n" + "\n".join(known_lines)
    else:
        known_block = "已知信息：（暂无，跳过 contradiction 类型检测）"

    # 提取已有 category 列表（去重）
    if existing_profile:
        categories = sorted(set(p["category"] for p in existing_profile if p.get("category")))
        category_hint = "、".join(categories) if categories else "（暂无）"
    else:
        category_hint = "（暂无）"

    # 已有标签
    existing = load_existing_tags()
    tag_hint = "、".join(existing) if existing else "（暂无）"

    prompt = get_prompt("extract_observations_and_tags", language).replace(
        "{known_info_block}", known_block
    ).replace("{existing_tags}", tag_hint
    ).replace("{category_list}", category_hint)

    # 用对话时间（而非系统时间）算年龄
    conv_times = [m["user_input_at"] for m in conversations if m.get("user_input_at")]
    ref_time = max(conv_times) if conv_times else datetime.now()
    ref_year = ref_time.year if hasattr(ref_time, 'year') else datetime.now().year
    date_prefix = (
        f"对话时间：{ref_time.strftime('%Y-%m-%d %H:%M') if hasattr(ref_time, 'strftime') else '?'}（当年是{ref_year}年）\n"
        f"注意：用户说\"今年XX岁\"时，出生年 = {ref_year} - 年龄。例如\"今年25岁\"→出生年={ref_year}-25={ref_year - 25}。\n\n"
    )
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": date_prefix + text},
    ]
    raw = call_llm(messages, llm_config)
    result = _parse_json_object(raw)

    # 清洗
    obs = [o for o in result.get("observations", []) if isinstance(o, dict) and o.get("type") and o.get("content")]
    tags = [t for t in result.get("tags", []) if isinstance(t, dict) and t.get("tag")]
    rels = [r for r in result.get("relationships", []) if isinstance(r, dict) and r.get("relation")]

    # 覆盖率检查：观察数 vs 用户消息数
    return {"observations": obs, "tags": tags, "relationships": rels}


def extract_events(conversations: list[dict], config: dict,
                    language: str = "zh") -> list[dict]:
    """Step 3: 从对话中提取事件"""
    llm_config = config.get("llm", {})

    dialogue = ""
    for msg in conversations:
        dialogue += f"用户：{msg['user_input']}\n"
        dialogue += f"助手：{msg['assistant_reply']}\n\n"

    if not dialogue.strip():
        return []

    messages = [
        {"role": "system", "content": get_prompt("extract_event", language)},
        {"role": "user", "content": dialogue},
    ]
    raw = call_llm(messages, llm_config)
    events = _parse_json_array(raw)
    return [e for e in events if isinstance(e, dict) and e.get("category") and e.get("summary")]


def classify_observations(observations: list[dict],
                           current_profile: list[dict],
                           config: dict,
                           timeline: list[dict] | None = None,
                           trajectory: dict | None = None,
                           language: str = "zh") -> list[dict]:
    """Step 4a: 对每条观察分类 — support/contradict/new/etc.
    v14: 使用双层画像 + 时间线 + 轨迹。"""
    llm_config = config.get("llm", {})
    if not observations:
        return []

    # 按会话分组格式化观察
    obs_text = ""
    grouped: dict[int, list[tuple[int, dict]]] = {}
    for i, o in enumerate(observations):
        order = o.get("_session_order", 0)
        if order not in grouped:
            grouped[order] = []
        grouped[order].append((i, o))

    if grouped:
        total = max(grouped.keys()) if grouped else 1
        for order in sorted(grouped.keys()):
            first_obs = grouped[order][0][1] if grouped[order] else None
            time_str = ""
            if first_obs and first_obs.get("_conv_time"):
                time_str = f" {first_obs['_conv_time'].strftime('%Y-%m-%d')}"
            label = f"[会话 {order}/{total}{time_str}"
            if order == total:
                label += " — 最新"
            label += "]"
            obs_text += f"{label}\n"
            for i, o in grouped[order]:
                # v18.A.1: 传入 subject 字段，帮助 4a 跨 category 语义匹配
                subj = o.get('subject', '')
                subj_tag = f" [subject:{subj}]" if subj else ""
                obs_text += f"  [{i}] [{o['type']}]{subj_tag} {o['content']}\n"
    else:
        for i, o in enumerate(observations):
            subj = o.get('subject', '')
            subj_tag = f" [subject:{subj}]" if subj else ""
            obs_text += f"[{i}] [{o['type']}]{subj_tag} {o['content']}\n"

    # v14: 使用双层画像格式
    profile_text = _format_profile_for_llm(current_profile, timeline, language=language)

    # 轨迹上下文（帮助判断矛盾是否合理）
    traj_context = ""
    if trajectory and trajectory.get("life_phase"):
        traj_context = (
            f"\n人物轨迹参考（帮助判断矛盾合理性）：\n"
            f"  当前阶段: {trajectory.get('life_phase', '?')}\n"
            f"  锚点（不易变）: {json.dumps(trajectory.get('key_anchors', []), ensure_ascii=False)}\n"
            f"  易变区域: {json.dumps(trajectory.get('volatile_areas', []), ensure_ascii=False)}\n"
        )

    user_content = (
        f"当前画像（双层）：\n{profile_text}\n"
        f"本次新观察：\n{obs_text}"
        f"{traj_context}"
    )
    messages = [
        {"role": "system", "content": get_prompt("classify_observations", language)},
        {"role": "user", "content": user_content},
    ]
    raw = call_llm(messages, llm_config)
    results = _parse_json_array(raw)
    return [r for r in results if isinstance(r, dict) and r.get("action")]


def create_new_facts(new_observations: list[dict],
                     existing_profile: list[dict],
                     config: dict,
                     behavioral_signals: list | None = None,
                     trajectory: dict | None = None,
                     language: str = "zh") -> list[dict]:
    """Step 4b: 为未匹配的观察创建新画像事实。只看 'new' 类观察。"""
    llm_config = config.get("llm", {})
    if not new_observations:
        return []

    obs_text = ""
    for o in new_observations:
        time_str = ""
        if o.get("_conv_time"):
            time_str = f" ({o['_conv_time'].strftime('%Y-%m-%d')})"
        subj_str = f" (subject: {o['subject']})" if o.get('subject') else ""
        obs_text += f"[{o['type']}] {o['content']}{subj_str}{time_str}\n"

    # 已有 category+subject 供命名参考（原逻辑）
    existing_cats = set()
    for p in existing_profile:
        existing_cats.add(f"  {p['category']}: {p['subject']}")
    default_cats = (
        "出生地: 家乡城市 | 居住城市: 居住城市 | 身份: 姓名 | 身份: 性别\n"
        "出生年: 出生年份 | 教育背景: 毕业院校 | 教育背景: 专业\n"
        "职业: 职位 | 兴趣: [爱好名称] | 感情状态: 感情状态"
    )
    if existing_cats:
        cat_block = ("已有命名（复用）：\n"
                     + "\n".join(sorted(existing_cats))
                     + "\n参考：" + default_cats)
    else:
        cat_block = default_cats

    # 构建"原文→归类"历史（让 LLM 看到之前的分类先例，减少 category 冗余）
    categorization_history = []
    for p in existing_profile:
        ev = p.get("evidence") or []
        for e in ev:
            obs_text_ev = e.get("observation", "")
            if obs_text_ev:
                categorization_history.append(
                    f"  \"{obs_text_ev}\" → [{p['category']}] {p['subject']} = {p['value']}"
                )
                break  # 每条 fact 只取第一条 observation
    if categorization_history:
        history_block = ("═══ 之前的归类先例（同类观察必须复用相同 category:subject）═══\n"
                         + "\n".join(categorization_history))
    else:
        history_block = ""

    # 行为模式提示
    signal_block = ""
    if behavioral_signals:
        signal_block = "\n行为模式提示（参考）：\n"
        for s in behavioral_signals:
            signal_block += (
                f"  [{s.get('category', '?')}] {s.get('subject', '?')}: "
                f"可能是「{s.get('inferred_value', '?')}」\n"
            )

    # 轨迹上下文（帮助判断 decay_days 和避免重复）
    traj_context = ""
    if trajectory and trajectory.get("life_phase"):
        traj_context = (
            f"\n人物背景（参考，帮助设定合理的 decay_days）：\n"
            f"  当前阶段: {trajectory.get('life_phase', '?')}\n"
            f"  锚点（稳定不变）: {json.dumps(trajectory.get('key_anchors', []), ensure_ascii=False)}\n"
            f"  易变区域: {json.dumps(trajectory.get('volatile_areas', []), ensure_ascii=False)}\n"
        )

    # 用观察里的对话时间算年龄
    _obs_times = [o.get("_conv_time") for o in new_observations if o.get("_conv_time")]
    ref_time = max(_obs_times) if _obs_times else datetime.now()
    ref_year = ref_time.year if hasattr(ref_time, 'year') else datetime.now().year
    prompt = get_prompt("create_hypotheses", language).replace(
        "{existing_categories}", cat_block
    ).replace(
        "{categorization_history}", history_block
    ).replace(
        "{birth_year}", str(ref_year)
    )

    user_content = (
        f"对话时间：{ref_time.strftime('%Y-%m-%d %H:%M') if hasattr(ref_time, 'strftime') else '?'}（当年是{ref_year}年）\n"
        f"注意：用户说\"今年XX岁\"时，出生年 = {ref_year} - 年龄。\n\n"
        f"新观察：\n{obs_text}"
        f"{signal_block}"
        f"{traj_context}"
    )
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": user_content},
    ]
    raw = call_llm(messages, llm_config)
    return _parse_json_array(raw)


def cross_validate_contradictions(contradictions: list[dict],
                                  observations: list[dict],
                                  current_profile: list[dict],
                                  config: dict,
                                  trajectory: dict | None = None,
                                  language: str = "zh") -> list[dict]:
    """Step 4c: 交叉验证矛盾（v14: 使用 user_profile + 时间线）。"""
    llm_config = config.get("llm", {})
    if not contradictions:
        return []

    profile_map = {p["id"]: p for p in current_profile}

    # 收集矛盾涉及的 subject 关键词
    relevant_keywords = set()
    for c in contradictions:
        fid = c.get("fact_id")
        if fid and fid in profile_map:
            p = profile_map[fid]
            relevant_keywords.add(p.get("subject", ""))
            relevant_keywords.add(p.get("value", ""))
            relevant_keywords.add(p.get("category", ""))
        new_val = c.get("new_value", "")
        if new_val:
            relevant_keywords.add(new_val)
    relevant_keywords = {k for k in relevant_keywords if k and len(k) >= 2}

    # 格式化矛盾详情（带时间线）
    items_text = ""
    now = datetime.now()
    for c in contradictions:
        obs_idx = c.get("obs_index", "?")
        obs = observations[obs_idx] if isinstance(obs_idx, int) and obs_idx < len(observations) else {}
        fid = c.get("fact_id")
        fact = profile_map.get(fid, {})
        # 新述说时间（矛盾发生点）
        obs_time = obs.get('_conv_time') or now
        obs_time_str = obs_time.strftime('%Y-%m-%d')
        # 老值时间区间
        fact_start = fact['start_time'].strftime('%Y-%m-%d') if fact.get('start_time') else '?'
        fact_updated = fact['updated_at'].strftime('%Y-%m-%d') if fact.get('updated_at') else '?'
        fact_mentions = fact.get('mention_count', 1)

        items_text += (
            f"[矛盾{obs_idx}] [{fact.get('category', '?')}] {fact.get('subject', '?')}\n"
            f"  老值: \"{fact.get('value', '?')}\" (从 {fact_start} 到 {obs_time_str}, 提及{fact_mentions}次)\n"
            f"  新述说: \"{c.get('new_value', '?')}\" (开始于 {obs_time_str})\n"
            f"  原文: {obs.get('content', '?')}\n"
            f"  分类理由: {c.get('reason', '')}\n"
        )
        # 加载该 subject 的历史时间线
        if fact.get("category") and fact.get("subject"):
            tl = load_timeline(category=fact["category"], subject=fact["subject"])
            closed = [t for t in tl if t.get("end_time")]
            if closed:
                items_text += "  历史时间线:\n"
                for t in closed:
                    t_start = t["start_time"].strftime('%Y-%m-%d') if t.get("start_time") else "?"
                    t_end = t["end_time"].strftime('%Y-%m-%d') if t.get("end_time") else "?"
                    items_text += f"    \"{t.get('value', '?')}\" ({t_start} ~ {t_end})\n"
        items_text += "\n"

    # 按 subject 过滤历史观察（不灌全量100条）
    historical_obs = load_observations(limit=100)
    hist_text = ""
    if historical_obs and relevant_keywords:
        filtered = [ho for ho in historical_obs
                    if any(kw in (ho.get("content", "") + " " + (ho.get("subject", "") or ""))
                           for kw in relevant_keywords)]
        if filtered:
            for ho in filtered[:30]:
                time_str = ho['created_at'].strftime('%Y-%m-%d') if ho.get('created_at') else '?'
                hist_text += f"  [{time_str}] [{ho['observation_type']}] {ho['content']}"
                if ho.get("subject"):
                    hist_text += f" (subject: {ho['subject']})"
                hist_text += "\n"
        else:
            hist_text = "（无相关历史观察）\n"
    else:
        hist_text = "（无历史观察）\n"

    # 轨迹参考
    traj_block = ""
    if trajectory and trajectory.get("life_phase"):
        traj_block = (
            f"\n轨迹参考：\n"
            f"  锚点（不易变）: {json.dumps(trajectory.get('key_anchors', []), ensure_ascii=False)}\n"
            f"  易变区域: {json.dumps(trajectory.get('volatile_areas', []), ensure_ascii=False)}\n"
        )

    user_content = (
        f"矛盾详情：\n{items_text}"
        f"相关历史观察：\n{hist_text}"
        f"{traj_block}"
    )
    messages = [
        {"role": "system", "content": get_prompt("cross_validate", language)},
        {"role": "user", "content": user_content},
    ]
    raw = call_llm(messages, llm_config)
    return _parse_json_array(raw)


def generate_strategies(changed_items: list[dict], config: dict,
                        current_profile: list[dict] | None = None,
                        trajectory: dict | None = None,
                        language: str = "zh") -> list[dict]:
    """Step 4d: 为新建/矛盾的假设生成验证策略。"""
    llm_config = config.get("llm", {})
    if not changed_items:
        return []

    items_text = ""
    for item in changed_items:
        items_text += (
            f"[{item.get('change_type', '?')}] [{item.get('category', '?')}] "
            f"{item.get('subject', '?')}: {item.get('claim', '?')}"
        )
        if item.get("source_type"):
            items_text += f" (source={item['source_type']})"
        items_text += "\n"

    # 用户画像概览（帮助生成更贴切的策略）
    profile_context = ""
    if current_profile:
        profile_lines = []
        for p in current_profile:
            layer_tag = get_label("layer_confirmed", language) if p.get("layer") == "confirmed" else get_label("layer_suspected", language)
            profile_lines.append(f"  {layer_tag} [{p['category']}] {p['subject']}: {p['value']}")
        profile_context = get_label("profile_overview_header", language) + "\n".join(profile_lines) + "\n"

    # 轨迹上下文（帮助理解用户阶段）
    traj_context = ""
    if trajectory and trajectory.get("life_phase"):
        traj_context = (
            f"\n人物轨迹（参考）：\n"
            f"  阶段: {trajectory.get('life_phase', '?')}\n"
            f"  方向: {trajectory.get('trajectory_direction', '?')}\n"
            f"  易变区域: {json.dumps(trajectory.get('volatile_areas', []), ensure_ascii=False)}\n"
        )

    # 用户沟通风格（帮助选择合适的策略方式）
    user_model = load_user_model()
    model_context = ""
    if user_model:
        model_lines = [f"  {m['dimension']}: {m['assessment']}" for m in user_model]
        model_context = "\n用户沟通特征（参考，策略要匹配用户风格）：\n" + "\n".join(model_lines) + "\n"

    user_content = (
        f"本轮变更的假设：\n{items_text}"
        f"{profile_context}"
        f"{traj_context}"
        f"{model_context}"
    )
    messages = [
        {"role": "system", "content": get_prompt("generate_strategies", language)},
        {"role": "user", "content": user_content},
    ]
    raw = call_llm(messages, llm_config)
    return _parse_json_array(raw)


def analyze_user_model(conversations: list[dict], config: dict,
                       current_profile: list[dict] | None = None,
                       language: str = "zh") -> list[dict]:
    """Step 6: 分析用户沟通特征"""
    llm_config = config.get("llm", {})

    dialogue = ""
    for msg in conversations:
        dialogue += f"用户：{msg['user_input']}\n"
        dialogue += f"助手：{msg['assistant_reply']}\n\n"

    if not dialogue.strip():
        return []

    existing_model = load_user_model()
    if existing_model:
        model_lines = []
        for m in existing_model:
            model_lines.append(f"  {m['dimension']}: {m['assessment']}")
        existing_block = get_label("existing_model_header", language) + "\n".join(model_lines)
    else:
        existing_block = get_label("no_existing_model", language)

    # 用户画像概览（帮助理解用户身份背景，提升分析质量）
    profile_block = ""
    if current_profile:
        profile_lines = []
        for p in current_profile:
            layer_tag = get_label("layer_confirmed", language) if p.get("layer") == "confirmed" else get_label("layer_suspected", language)
            profile_lines.append(f"  {layer_tag} [{p['category']}] {p['subject']}: {p['value']}")
        profile_block = get_label("profile_overview_header", language) + "\n".join(profile_lines) + "\n"

    prompt = get_prompt("analyze_user_model", language).replace("{existing_model_block}", existing_block)

    user_content = f"{dialogue}{profile_block}"
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": user_content},
    ]
    raw = call_llm(messages, llm_config)
    results = _parse_json_array(raw)
    return [r for r in results if isinstance(r, dict) and r.get("dimension") and r.get("assessment")]


def analyze_behavioral_patterns(observations: list[dict],
                                 current_profile: list[dict],
                                 trajectory: dict | None,
                                 config: dict,
                                 language: str = "zh") -> list[dict]:
    """Step 3.5: 行为模式分析（v14: 用双层画像）"""
    llm_config = config.get("llm", {})
    if not observations or len(observations) < 1:
        return []

    # 格式化画像（双层标签）
    profile_text = ""
    if current_profile:
        for p in current_profile:
            layer_tag = get_label("layer_confirmed", language) if p.get("layer") == "confirmed" else get_label("layer_suspected", language)
            profile_text += f"  {layer_tag} [{p['category']}] {p['subject']}: {p['value']}\n"
    else:
        profile_text = get_label("no_profile", language)

    # 格式化近期观察
    obs_text = ""
    for o in observations:
        obs_text += f"[{o['type']}] {o['content']}"
        if o.get("subject"):
            obs_text += f" (subject: {o['subject']})"
        obs_text += "\n"

    trajectory_block = _format_trajectory_block(trajectory, language=language)

    user_content = (
        f"当前系统时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}（今年是{datetime.now().year}年）\n\n"
        f"当前画像：\n{profile_text}\n"
        f"近期观察：\n{obs_text}\n"
        f"{trajectory_block}"
        f"\n⚠️ 请直接输出JSON数组，不要输出分析文字。"
    )
    messages = [
        {"role": "system", "content": get_prompt("behavioral_pattern", language)},
        {"role": "user", "content": user_content},
    ]
    raw = call_llm(messages, llm_config)
    results = _parse_json_array(raw)
    return [r for r in results
            if isinstance(r, dict) and r.get("category") and r.get("inferred_value")]


def cross_verify_suspected_facts(suspected_facts: list[dict], config: dict,
                                  trajectory: dict | None = None,
                                  language: str = "zh") -> list[dict]:
    """Step 5: 交叉验证怀疑画像（v14: suspected → confirmed）。"""
    llm_config = config.get("llm", {})
    if not suspected_facts:
        return []

    # 预加载全量画像，用于查找被取代的旧事实
    all_current = load_full_current_profile()
    all_facts_map = {p["id"]: p for p in all_current}

    # 格式化怀疑画像
    items_text = ""
    seen_subjects = set()  # 收集 (category, subject) 用于加载时间线
    for f in suspected_facts:
        ev = f.get("evidence", [])
        mention_count = f.get("mention_count", 1) or 1
        start = f["start_time"].strftime("%Y-%m-%d") if f.get("start_time") else "?"
        updated = f["updated_at"].strftime("%Y-%m-%d") if f.get("updated_at") else "?"

        items_text += (
            f"事实 ID={f['id']}:\n"
            f"  [{f['category']}] {f['subject']}: {f['value']}\n"
            f"  提及{mention_count}次, source={f.get('source_type', 'stated')}, "
            f"开始={start}, 更新={updated}, 证据{len(ev)}条\n"
        )
        if ev:
            items_text += f"  证据: {json.dumps(ev, ensure_ascii=False)}\n"
        if f.get("supersedes"):
            old_fact = all_facts_map.get(f["supersedes"])
            if old_fact:
                old_layer = old_fact.get("layer", "suspected")
                old_start = old_fact["start_time"].strftime("%Y-%m-%d") if old_fact.get("start_time") else "?"
                old_mc = old_fact.get("mention_count", 1) or 1
                items_text += (
                    f"  取代了旧事实 #{f['supersedes']}: "
                    f"{old_fact['value']} (层级={old_layer}, 提及{old_mc}次, 开始={old_start})\n"
                )
            else:
                items_text += f"  取代了旧事实 #{f['supersedes']}\n"
        items_text += "\n"
        seen_subjects.add((f.get("category", ""), f.get("subject", "")))

    # 加载每个 subject 的完整时间线（含已关闭 + 当前开放的全部记录）
    timeline_context = ""
    for cat, subj in seen_subjects:
        if cat and subj:
            subj_timeline = load_timeline(category=cat, subject=subj)
            if subj_timeline:
                timeline_context += f"\n[{cat}] {subj} 完整时间线：\n"
                for t in subj_timeline:
                    t_start = t["start_time"].strftime("%Y-%m-%d") if t.get("start_time") else "?"
                    if t.get("end_time"):
                        t_end = t["end_time"].strftime("%Y-%m-%d")
                        timeline_context += f"  {t['value']} ({t_start} ~ {t_end}) [已关闭]\n"
                    else:
                        layer = t.get("layer", "suspected")
                        tag = "[矛盾中]" if t.get("superseded_by") else f"[{layer}]"
                        timeline_context += f"  {t['value']} ({t_start} ~ 至今) {tag}\n"

    # 按 subject 分类加载相关对话摘要作为佐证
    obs_context = ""
    for cat, subj in seen_subjects:
        if not subj:
            continue
        subj_summaries = load_summaries_by_observation_subject(subject=subj)
        all_subj = subj_summaries.get("before", [])
        if all_subj:
            obs_context += f"\n[{cat}] {subj} 相关对话摘要：\n"
            for s in all_subj[-30:]:
                time_str = s['user_input_at'].strftime('%Y-%m-%d') if s.get('user_input_at') else '?'
                obs_context += f"  [{time_str}] {s.get('ai_summary', '')}\n"

    # 轨迹上下文
    traj_context = ""
    if trajectory and trajectory.get("life_phase"):
        traj_context = (
            f"\n轨迹参考：\n"
            f"  锚点（不易变）: {json.dumps(trajectory.get('key_anchors', []), ensure_ascii=False)}\n"
            f"  易变区域: {json.dumps(trajectory.get('volatile_areas', []), ensure_ascii=False)}\n"
        )

    now = datetime.now()
    user_content = (
        f"当前系统时间：{now.strftime('%Y-%m-%d %H:%M')}（今年是{now.year}年）\n\n"
        f"待验证的怀疑画像：\n{items_text}"
        f"{timeline_context}"
        f"{obs_context}"
        f"{traj_context}"
        f"\n⚠️ 请直接输出JSON数组。"
    )
    messages = [
        {"role": "system", "content": get_prompt("cross_verify_suspected", language)},
        {"role": "user", "content": user_content},
    ]
    raw = call_llm(messages, llm_config)
    results = _parse_json_array(raw)
    return [r for r in results if isinstance(r, dict) and r.get("fact_id") and r.get("action")]


def resolve_disputes_with_llm(disputed_pairs: list[dict], config: dict,
                              trajectory: dict | None = None,
                              language: str = "zh") -> list[dict]:
    """Step 5.1: 矛盾争议解决 — 用 LLM 判断每对矛盾中哪个值是正确的当前状态。
    v15: 精确时间线 — 按矛盾创建时间分成"之前/之后"两组观察。"""
    llm_config = config.get("llm", {})
    if not disputed_pairs:
        return []

    items_text = ""
    for pair in disputed_pairs:
        old = pair["old"]
        new = pair["new"]

        old_start = old["start_time"].strftime("%Y-%m-%d") if old.get("start_time") else "?"
        old_mention = old.get("mention_count", 1) or 1
        old_layer = old.get("layer", "suspected")
        old_layer_tag = "核心画像" if old_layer == "confirmed" else "怀疑画像"

        new_start = new["start_time"].strftime("%Y-%m-%d") if new.get("start_time") else "?"
        new_mention = new.get("mention_count", 1) or 1

        # 矛盾创建时间 = 新记录的 start_time（对话时间）优先于 created_at（DB插入时间）
        pivot_time = new.get("start_time") or new.get("created_at")
        pivot_str = pivot_time.strftime("%Y-%m-%d") if pivot_time else "?"

        # 从新值的 evidence 中提取触发矛盾的原始观察
        trigger_text = ""
        new_evidence = new.get("evidence") or []
        for ev in new_evidence:
            if ev.get("observation"):
                trigger_text = ev["observation"]
                break
        trigger_line = f"触发矛盾的原文: \"{trigger_text}\"\n" if trigger_text else ""

        items_text += (
            f"═══ 矛盾: [{old.get('category', '?')}] {old.get('subject', '?')} ═══\n"
            f"旧值: \"{old['value']}\" ({old_layer_tag}, 从 {old_start} 起, 提及{old_mention}次)\n"
            f"新值: \"{new['value']}\" (怀疑画像, 从 {new_start} 起, 提及{new_mention}次)\n"
            f"{trigger_line}"
            f"矛盾创建时间: {pivot_str}\n"
        )

        # 按矛盾 subject 分类加载相关对话摘要（旧消息 + 新消息）
        subject_key = old.get("subject", "") or new.get("subject", "")
        if pivot_time and subject_key:
            summary_groups = load_summaries_by_observation_subject(
                subject=subject_key,
                pivot_time=pivot_time,
            )
        elif pivot_time:
            summary_groups = load_conversation_summaries_around(
                pivot_time=pivot_time,
                limit_before=30,
                limit_after=50,
            )
        else:
            summary_groups = {"before": [], "after": []}

        # 格式化"矛盾之前"的对话摘要
        before_summaries = summary_groups.get("before", [])
        if before_summaries:
            items_text += "\n█ 矛盾之前的对话摘要（按时间顺序）:\n"
            session_ids_before = []
            for s in before_summaries:
                sid = s.get("session_id", "")
                if sid and sid not in session_ids_before:
                    session_ids_before.append(sid)
            for s in before_summaries[-20:]:
                time_str = s['user_input_at'].strftime('%Y-%m-%d') if s.get('user_input_at') else '?'
                sid = s.get("session_id", "")
                sess_num = session_ids_before.index(sid) + 1 if sid in session_ids_before else "?"
                items_text += f"  [{time_str} 会话{sess_num}] {s.get('ai_summary', '')}\n"
        else:
            items_text += "\n█ 矛盾之前的对话摘要: （无）\n"

        # 格式化"矛盾之后"的对话摘要
        after_summaries = summary_groups.get("after", [])
        if after_summaries:
            items_text += "\n█ 矛盾之后的对话摘要（按时间顺序，完整生活场景）:\n"
            session_ids_after = []
            for s in after_summaries:
                sid = s.get("session_id", "")
                if sid and sid not in session_ids_after:
                    session_ids_after.append(sid)
            base_num = len(session_ids_before) if before_summaries else 0
            for s in after_summaries[:30]:
                time_str = s['user_input_at'].strftime('%Y-%m-%d') if s.get('user_input_at') else '?'
                sid = s.get("session_id", "")
                sess_num = base_num + (session_ids_after.index(sid) + 1) if sid in session_ids_after else "?"
                items_text += f"  [{time_str} 会话{sess_num}] {s.get('ai_summary', '')}\n"
        else:
            items_text += "\n█ 矛盾之后的对话摘要: （无新对话）\n"

        items_text += f"\n  old_fact_id={old['id']}, new_fact_id={new['id']}\n\n"

    # 轨迹上下文
    traj_context = ""
    if trajectory and trajectory.get("life_phase"):
        traj_context = (
            f"\n轨迹参考：\n"
            f"  锚点（不易变）: {json.dumps(trajectory.get('key_anchors', []), ensure_ascii=False)}\n"
            f"  易变区域: {json.dumps(trajectory.get('volatile_areas', []), ensure_ascii=False)}\n"
        )

    now = datetime.now()
    user_content = (
        f"当前系统时间：{now.strftime('%Y-%m-%d %H:%M')}（今年是{now.year}年）\n\n"
        f"待解决的矛盾：\n{items_text}"
        f"{traj_context}"
        f"\n⚠️ 请直接输出JSON数组。"
    )
    messages = [
        {"role": "system", "content": get_prompt("resolve_dispute", language)},
        {"role": "user", "content": user_content},
    ]
    raw = call_llm(messages, llm_config)
    results = _parse_json_array(raw)
    return [r for r in results if isinstance(r, dict)
            and r.get("old_fact_id") and r.get("new_fact_id") and r.get("action")]


def generate_trajectory_summary(current_profile: list[dict],
                                config: dict,
                                new_observations: list[dict] | None = None,
                                language: str = "zh") -> dict:
    """Step 7: 生成/更新人物轨迹总结（v14: 使用双层画像）。"""
    llm_config = config.get("llm", {})

    # 格式化画像（双层标签）
    profile_text = ""
    if current_profile:
        for p in current_profile:
            layer_tag = get_label("layer_confirmed", language) if p.get("layer") == "confirmed" else get_label("layer_suspected", language)
            profile_text += f"  {layer_tag} [{p['category']}] {p['subject']}: {p['value']}\n"
    else:
        profile_text = get_label("no_profile", language)

    # 本次新观察（增量输入）
    new_obs_text = ""
    if new_observations:
        for o in new_observations:
            obs_type = o.get("type") or o.get("observation_type", "?")
            content = o.get("content", "")
            new_obs_text += f"  [{obs_type}] {content}\n"
    else:
        new_obs_text = "（本次无新观察）\n"

    # 历史观察（全量，帮助理解用户变化轨迹）
    historical_obs = load_observations(limit=200)
    hist_obs_text = ""
    if historical_obs:
        for o in historical_obs:
            time_str = o['created_at'].strftime('%Y-%m-%d') if o.get('created_at') else '?'
            hist_obs_text += f"  [{time_str}] [{o['observation_type']}] {o['content']}\n"
    else:
        hist_obs_text = "（暂无历史观察）\n"

    # 加载事件（保留，数量少）
    events = load_active_events(top_k=10)
    event_text = ""
    if events:
        for e in events:
            event_text += f"  [{e['category']}] {e['summary']}\n"
    else:
        event_text = "（暂无事件）\n"

    # 加载上一次轨迹
    prev_trajectory = load_trajectory_summary()
    prev_text = ""
    if prev_trajectory:
        prev_text = (
            f"上一次轨迹总结：\n"
            f"  阶段: {prev_trajectory['life_phase']}\n"
            f"  特征: {prev_trajectory['phase_characteristics']}\n"
            f"  方向: {prev_trajectory['trajectory_direction']}\n"
            f"  稳定性: {prev_trajectory['stability_assessment']}\n"
            f"  动向: {prev_trajectory.get('recent_momentum', '')}\n"
            f"  总结: {prev_trajectory.get('full_summary', '')}\n"
        )
    else:
        prev_text = "上一次轨迹总结：（首次生成）\n"

    user_content = (
        f"当前系统时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}（今年是{datetime.now().year}年）\n\n"
        f"当前画像（活跃假设）：\n{profile_text}\n"
        f"本次新观察：\n{new_obs_text}\n"
        f"历史观察（完整时间线）：\n{hist_obs_text}\n"
        f"近期事件：\n{event_text}\n"
        f"{prev_text}"
    )
    messages = [
        {"role": "system", "content": get_prompt("trajectory_summary", language)},
        {"role": "user", "content": user_content},
    ]
    raw = call_llm(messages, llm_config)
    return _parse_json_object(raw)


def _sweep_uncovered_observations(observations: list[dict], config: dict,
                                   trajectory: dict | None = None,
                                   language: str = "zh"):
    """Step 4.5: 兜底扫描 — 确保所有 statement/contradiction 观察都有对应画像（v14）。"""
    llm_config = config.get("llm", {})

    # statement 和 contradiction 类型都需要兜底
    statements = [o for o in observations if o.get("type") in ("statement", "contradiction")]
    if not statements:
        return

    # 从观察中提取最晚对话时间
    _sweep_times = [o.get("_conv_time") for o in statements if o.get("_conv_time")]
    _sweep_conv_time = max(_sweep_times) if _sweep_times else None

    # 加载所有当前画像（v14: user_profile, end_time IS NULL）
    all_facts = load_full_current_profile()

    # 格式化观察（带时间戳）
    obs_text = ""
    for o in statements:
        ts = o.get("_conv_time")
        time_str = f"[{ts.strftime('%Y-%m-%d %H:%M')}] " if ts and hasattr(ts, 'strftime') else ""
        obs_text += f"{time_str}[statement] {o['content']}"
        if o.get("subject"):
            obs_text += f" (subject: {o['subject']})"
        obs_text += "\n"

    # 格式化画像（带时间信息）
    fact_text = ""
    if all_facts:
        for f in all_facts:
            start = f["start_time"].strftime("%m-%d") if f.get("start_time") and hasattr(f["start_time"], 'strftime') else "?"
            updated = f["updated_at"].strftime("%m-%d") if f.get("updated_at") and hasattr(f["updated_at"], 'strftime') else "?"
            layer_tag = get_label("layer_confirmed", language) if f.get("layer") == "confirmed" else get_label("layer_suspected", language)
            fact_text += (
                f"[id={f['id']}] {layer_tag} [{f['category']}] {f['subject']}: {f['value']} "
                f"(start={start}, updated={updated})\n"
            )
    else:
        fact_text = get_label("no_profile", language)

    # 轨迹上下文（帮助判断旅行 vs 居住地等）
    traj_context = ""
    if trajectory and trajectory.get("life_phase"):
        traj_context = (
            f"\n人物轨迹参考（帮助判断是否是旅行/出差等临时行为）：\n"
            f"  当前阶段: {trajectory.get('life_phase', '?')}\n"
            f"  锚点（稳定）: {json.dumps(trajectory.get('key_anchors', []), ensure_ascii=False)}\n"
            f"  易变区域: {json.dumps(trajectory.get('volatile_areas', []), ensure_ascii=False)}\n"
        )

    # 用观察里的对话时间算年龄
    ref_time = _sweep_conv_time or datetime.now()
    ref_year = ref_time.year if hasattr(ref_time, 'year') else datetime.now().year
    messages = [
        {"role": "system", "content": get_prompt("sweep_uncovered", language)},
        {"role": "user", "content": (
            f"对话时间：{ref_time.strftime('%Y-%m-%d %H:%M') if hasattr(ref_time, 'strftime') else '?'}（当年是{ref_year}年）\n"
            f"注意：用户说\"今年XX岁\"时，出生年 = {ref_year} - 年龄。例如\"今年25岁\"→出生年={ref_year}-25={ref_year - 25}。\n\n"
            f"Statement 观察：\n{obs_text}\n"
            f"当前所有画像：\n{fact_text}"
            f"{traj_context}"
        )},
    ]
    raw = call_llm(messages, llm_config)
    result = _parse_json_object(raw)
    if result and ("new_facts" in result or "contradictions" in result):
        new_facts_list = result.get("new_facts", [])
        sweep_contradictions = result.get("contradictions", [])
    else:
        new_facts_list = _parse_json_array(raw)
        sweep_contradictions = []

    if new_facts_list:
        for nf in new_facts_list:
            if not isinstance(nf, dict) or not nf.get("category") or not nf.get("subject") or not nf.get("value"):
                continue
            value = nf["value"]
            if value.startswith("用户") or len(value) > 80:
                continue
            decay = nf.get("decay_days")
            fact_id = save_profile_fact(
                category=nf["category"],
                subject=nf["subject"],
                value=nf["value"],
                source_type=nf.get("source_type", "stated"),
                decay_days=decay,
                start_time=_sweep_conv_time,
            )

    # 兜底扫描也能触发矛盾处理
    if sweep_contradictions:
        for s in sweep_contradictions:
            new_val = s.get("new_value")
            if not new_val:
                continue
            fid = s.get("fact_id")
            fact = None
            if fid:
                for af in all_facts:
                    if af.get("id") == fid:
                        fact = af
                        break
            if not fact:
                cat = s.get("category")
                subj = s.get("subject")
                if cat and subj:
                    fact = find_current_fact(cat, subj)
            if not fact:
                continue
            # 同值过滤
            if new_val.strip().lower() == (fact.get("value") or "").strip().lower():
                add_evidence(fact["id"], {"reason": s.get("reason", "再次提及")},
                             reference_time=_sweep_conv_time)
                continue
            # 矛盾：save_profile_fact 会自动关闭旧记录+创建新记录
            new_id = save_profile_fact(
                category=fact["category"],
                subject=fact["subject"],
                value=new_val,
                source_type="stated",
                decay_days=fact.get("decay_days"),
                start_time=_sweep_conv_time,
            )


# ══════════════════════════════════════════════════════════════
# 数据库操作
# ══════════════════════════════════════════════════════════════

def get_unprocessed_conversations() -> dict[str, list[dict]]:
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT r.id, r.session_id, r.user_input, r.assistant_reply, "
                "       ct.ai_summary, r.user_input_at, ct.intent "
                "FROM raw_conversations r "
                "LEFT JOIN conversation_turns ct "
                "  ON r.session_id = ct.session_id "
                "  AND r.user_input_at = ct.user_input_at "
                "WHERE r.processed = FALSE "
                "ORDER BY r.id"
            )
            sessions: dict[str, list[dict]] = {}
            for id_, sid, user_input, assistant_reply, ai_summary, user_input_at, intent in cur.fetchall():
                if sid not in sessions:
                    sessions[sid] = []
                sessions[sid].append({
                    "id": id_,
                    "user_input": user_input,
                    "assistant_reply": assistant_reply,
                    "ai_summary": ai_summary or user_input,
                    "user_input_at": user_input_at,
                    "intent": intent or "",
                })
            return sessions
    finally:
        conn.close()


def mark_processed(message_ids: list[int]):
    if not message_ids:
        return
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE raw_conversations SET processed = TRUE WHERE id = ANY(%s)",
                (message_ids,),
            )
        conn.commit()
    finally:
        conn.close()


def _parse_json_array(raw: str) -> list[dict]:
    text = raw.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()
    # 先尝试直接解析（最快路径）
    start = text.find("[")
    end = text.rfind("]") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end])
        except (json.JSONDecodeError, ValueError):
            pass
    # 回退：LLM 可能返回多个分散的 JSON 数组夹杂文字，逐个提取合并
    import re
    merged = []
    for m in re.finditer(r'\[.*?\]', text, re.DOTALL):
        try:
            arr = json.loads(m.group())
            if isinstance(arr, list):
                merged.extend(arr)
        except (json.JSONDecodeError, ValueError):
            continue
    return merged


def _parse_json_object(raw: str) -> dict:
    text = raw.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        text = text[start:end]
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return {}


# ══════════════════════════════════════════════════════════════
# 主流程（Step 0 ~ Step 8）
# ══════════════════════════════════════════════════════════════

def run(fallback_time=None):
    config = load_config()
    language = config.get("language", "zh")

    print("  [sleep] start")

    # Step 1: 读取未处理的对话
    session_convs = get_unprocessed_conversations()
    if not session_convs:
        print("  [sleep] no new conversations, skip")
        return

    total_msgs = sum(len(msgs) for msgs in session_convs.values())
    print(f"  [sleep] {total_msgs} conversations, {len(session_convs)} sessions")

    all_msg_ids = []
    all_convs = []
    all_observations = []

    # 预加载已有画像（v14: user_profile）
    existing_profile = load_full_current_profile()

    # Step 0: 预加载轨迹
    trajectory = load_trajectory_summary()
    if trajectory and trajectory.get("life_phase"):
        print(f"  [sleep] trajectory loaded")
    else:
        print("  [sleep] no trajectory yet")
        trajectory = None

    total_session_count = len(session_convs)
    for session_idx, (session_id, convs) in enumerate(session_convs.items(), 1):
        print(f"  [sleep] session {session_idx}/{total_session_count}")
        msg_ids = [c["id"] for c in convs]
        all_msg_ids.extend(msg_ids)
        all_convs.extend(convs)

        # Step 2: 提取观察 + 标签 + 人际关系
        result = extract_observations_and_tags(convs, config,
                                               existing_profile=existing_profile,
                                               language=language)
        observations_raw = result.get("observations", [])
        tags = result.get("tags", [])
        relationships = result.get("relationships", [])

        # 按 about 字段分流：user 观察 vs 第三方观察
        observations = []      # 用户本人的观察 → 进入假设管道
        third_party_obs = []   # 第三方观察 → 仅记录，不进假设管道
        for o in observations_raw:
            about = o.get("about", "user")
            if about == "user" or about == "" or about is None or about == "null":
                observations.append(o)
            else:
                third_party_obs.append(o)

        # 给每条用户观察打上会话时间戳
        conv_times = [c["user_input_at"] for c in convs if c.get("user_input_at")]
        session_time = min(conv_times) if conv_times else None
        for o in observations:
            o["_session_order"] = session_idx
            o["_session_total"] = total_session_count
            o["_conv_time"] = session_time

        user_count = len(observations)
        tp_count = len(third_party_obs)
        print(f"  [sleep] extracted {user_count + tp_count} observations, {len(tags)} tags")

        # 保存用户观察
        for o in observations:
            obs_id = save_observation(
                session_id=session_id,
                observation_type=o["type"],
                content=o["content"],
                subject=o.get("subject"),
                context=o.get("context"),
                reference_time=session_time,
            )
            o["_db_id"] = obs_id

        # 保存第三方观察（仍然存 observations 表，但不进入假设管道）
        for o in third_party_obs:
            obs_id = save_observation(
                session_id=session_id,
                observation_type=o["type"],
                content=o["content"],
                subject=o.get("subject"),
                context=f"about:{o.get('about', '?')}",
                reference_time=session_time,
            )
            o["_db_id"] = obs_id

        # 只有用户观察进入后续假设管道
        all_observations.extend(observations)

        # 保存人际关系
        for r in relationships:
            name = r.get("name")
            relation = r.get("relation", "")
            details = r.get("details", {})
            if relation:
                save_or_update_relationship(name, relation, details,
                                            reference_time=session_time)

        for t in tags:
            save_session_tag(session_id, t["tag"], t.get("summary", ""),
                           reference_time=session_time)

        # Step 3: 提取事件 → event_log
        events = extract_events(convs, config, language=language)
        print(f"  [sleep] extracted {len(events)} events")
        for e in events:
            decay_days = e.get("decay_days")
            importance = e.get("importance")
            save_event(e["category"], e["summary"], session_id,
                       importance=importance, decay_days=decay_days,
                       reference_time=session_time)

    # Step 3.5: 行为模式分析
    behavioral_signals = []
    if all_observations and len(all_observations) >= 1:
        print("  [sleep] analyzing behavioral patterns...")
        current_profile = load_full_current_profile()
        behavioral_signals = analyze_behavioral_patterns(
            all_observations, current_profile, trajectory, config,
            language=language
        )
        if behavioral_signals:
            # 计算最早的会话时间（用于 start_time）
            _obs_times = [o.get("_conv_time") for o in all_observations if o.get("_conv_time")]
            _earliest_time = min(_obs_times) if _obs_times else None

            for bs in behavioral_signals:
                pattern_type = bs.get('pattern_type', '?')
                cat = bs.get('category', '')
                subj = bs.get('subject', '')
                inferred = bs.get('inferred_value', '')
                conf = bs.get('confidence', 0)
                ev_count = bs.get("evidence_count", 0)

                # 行为模式直接创建 suspected 画像事实（inferred 来源）
                # 只要检测到模式就创建，裁决交给后续 Step 5/5.1
                if cat and subj and inferred:
                    # 检查是否已有同 category+subject 的事实（避免重复创建）
                    existing = find_current_fact(cat, subj)
                    if existing and existing.get("value", "").strip().lower() == inferred.strip().lower():
                        pass
                    else:
                        fact_id = save_profile_fact(
                            category=cat,
                            subject=subj,
                            value=inferred,
                            source_type="inferred",
                            start_time=_earliest_time,
                        )

                # 证据足够时额外生成 clarify 策略
                if ev_count >= 3:
                    try:
                        save_strategy(
                            hypothesis_category=cat,
                            hypothesis_subject=subj,
                            strategy_type="clarify",
                            description=f"行为模式暗示{subj}可能是{inferred}",
                            trigger_condition=f"用户提到{subj}相关话题时",
                            approach=f"自然地确认：你是不是{inferred}？",
                            reference_time=_earliest_time,
                        )
                    except Exception:
                        pass
            pass
        else:
            pass

    # ═══ Step 4: 分步画像更新（v14 拆分版）═══
    print("  [sleep] classifying observations...")
    current_profile = load_full_current_profile()
    timeline = load_timeline()

    # 辅助：按 fact_id 查找画像
    def _find_fact(fid) -> dict | None:
        if not fid:
            return None
        for p in current_profile:
            if p.get("id") == fid:
                return p
        return None

    # 计算最晚对话时间（用于非观察直接关联的操作，如争议解决、过期处理）
    _all_conv_times = [o["_conv_time"] for o in all_observations if o.get("_conv_time")]
    latest_conv_time = max(_all_conv_times) if _all_conv_times else fallback_time

    if all_observations:
        # Step 4a: 分类每条观察
        classifications = classify_observations(
            all_observations, current_profile, config, timeline,
            trajectory=trajectory, language=language
        )

        # 校验：检查是否所有观察都被分类
        classified_indices = {c.get("obs_index") for c in classifications if c.get("obs_index") is not None}
        all_indices = set(range(len(all_observations)))
        missing_indices = all_indices - classified_indices
        if missing_indices:
            print(f"  [sleep] warning: {len(missing_indices)} unclassified observations")
            # 漏掉的 statement/contradiction 自动补为 new，其他补为 irrelevant
            for idx in missing_indices:
                obs = all_observations[idx]
                if obs.get("type") in ("statement", "contradiction"):
                    classifications.append({"obs_index": idx, "action": "new",
                                            "reason": "4a漏分类，自动补为new"})
                else:
                    pass

        # 按 action 分组
        supports = [c for c in classifications if c.get("action") == "support"]
        contradictions = [c for c in classifications if c.get("action") == "contradict"]
        evidence_against_list = [c for c in classifications if c.get("action") == "evidence_against"]
        new_obs_cls = [c for c in classifications if c.get("action") == "new"]
        irrelevant_cls = [c for c in classifications if c.get("action") == "irrelevant"]

        # 回写分类结果到 observations 表
        for c in classifications:
            obs_idx = c.get("obs_index")
            action = c.get("action", "")
            if isinstance(obs_idx, int) and 0 <= obs_idx < len(all_observations):
                db_id = all_observations[obs_idx].get("_db_id")
                if db_id:
                    update_observation_classification(db_id, action)

        print(f"  [sleep] classified: {len(supports)} support, {len(contradictions)} contradict, {len(new_obs_cls)} new")

        # 处理 support → 追加证据 + mention_count
        for s in supports:
            fact = _find_fact(s.get("fact_id"))
            if fact:
                # v20: 先计算 obs_time，传给 add_evidence 和 save_profile_fact
                _obs_idx = s.get("obs_index")
                _obs_time = all_observations[_obs_idx].get("_conv_time") if isinstance(_obs_idx, int) and 0 <= _obs_idx < len(all_observations) else latest_conv_time
                add_evidence(fact["id"], {"reason": s.get("reason", "")},
                             reference_time=_obs_time)
                # 同值重复提及走 save_profile_fact 触发 mention_count++
                save_profile_fact(
                    category=fact["category"],
                    subject=fact["subject"],
                    value=fact["value"],
                    source_type=fact.get("source_type", "stated"),
                    decay_days=fact.get("decay_days"),
                    start_time=_obs_time,
                )
                pass

        # 处理 evidence_against → 追加反面证据
        for ea in evidence_against_list:
            fact = _find_fact(ea.get("fact_id"))
            if fact:
                _ea_idx = ea.get("obs_index")
                _ea_time = all_observations[_ea_idx].get("_conv_time") if isinstance(_ea_idx, int) and 0 <= _ea_idx < len(all_observations) else latest_conv_time
                add_evidence(fact["id"], {"reason": f"[反面] {ea.get('reason', '')}"},
                             reference_time=_ea_time)
                pass

        # Step 4b: 创建新画像（只处理 "new" 类观察）
        new_fact_count = 0
        changed_items = []  # 收集变更，供 Step 4d 策略生成
        if new_obs_cls:
            print(f"  [sleep] creating {len(new_obs_cls)} new facts...")
            new_obs_data = []
            for c in new_obs_cls:
                idx = c.get("obs_index")
                if isinstance(idx, int) and 0 <= idx < len(all_observations):
                    new_obs_data.append(all_observations[idx])

            if new_obs_data:
                _new_obs_times = [o.get("_conv_time") for o in new_obs_data if o.get("_conv_time")]
                _new_batch_time = max(_new_obs_times) if _new_obs_times else None
                new_facts = create_new_facts(
                    new_obs_data, current_profile, config, behavioral_signals,
                    trajectory=trajectory, language=language
                )
                for nf in new_facts:
                    # 兼容旧 LLM 输出：claim → value
                    value = nf.get("value") or nf.get("claim")
                    if not nf.get("category") or not nf.get("subject") or not value:
                        continue
                    if value.startswith("用户") or len(value) > 80:
                        continue
                    decay = nf.get("decay_days")
                    # 找到来源 observation 原文，存入 evidence
                    _src_obs = ""
                    for _o in new_obs_data:
                        _cnt = _o.get("content") or ""
                        if _cnt and (value in _cnt or _cnt in value):
                            _src_obs = _cnt
                            break
                    _evidence = [{"observation": _src_obs}] if _src_obs else None
                    fact_id = save_profile_fact(
                        category=nf["category"],
                        subject=nf["subject"],
                        value=value,
                        source_type=nf.get("source_type", "stated"),
                        decay_days=decay,
                        evidence=_evidence,
                        start_time=_new_batch_time,
                    )
                    new_fact_count += 1
                    changed_items.append({
                        "change_type": "new",
                        "category": nf["category"],
                        "subject": nf["subject"],
                        "claim": value,
                        "source_type": nf.get("source_type", "stated"),
                    })

        # Step 4c: 标记矛盾（不再当场判断，交给 dispute resolution）
        contradict_count = 0
        if contradictions:
            print(f"  [sleep] processing {len(contradictions)} contradictions...")
            for c in contradictions:
                fid = c.get("fact_id")
                fact = _find_fact(fid)
                new_val = c.get("new_value")
                if not fact or not new_val:
                    continue
                # v20: 先计算 obs_time
                _obs_idx = c.get("obs_index")
                _obs_time = all_observations[_obs_idx].get("_conv_time") if isinstance(_obs_idx, int) and 0 <= _obs_idx < len(all_observations) else latest_conv_time
                # 同值过滤
                if new_val.strip().lower() == (fact.get("value") or "").strip().lower():
                    add_evidence(fact["id"], {"reason": c.get("reason", "再次提及")},
                                 reference_time=_obs_time)
                    continue
                # 脏值过滤
                if new_val.startswith("用户") or len(new_val) > 40:
                    continue
                # 直接创建 dispute pair，不用 LLM 判断
                # 保存触发矛盾的原始对话，供 Step 5.1 判断
                _obs = all_observations[_obs_idx] if isinstance(_obs_idx, int) and 0 <= _obs_idx < len(all_observations) else {}
                _evidence_entry = {"reason": c.get("reason", "")}
                if _obs.get("content"):
                    _evidence_entry["observation"] = _obs["content"]
                new_id = save_profile_fact(
                    category=fact["category"],
                    subject=fact["subject"],
                    value=new_val,
                    source_type="stated",
                    decay_days=fact.get("decay_days"),
                    evidence=[_evidence_entry],
                    start_time=_obs_time,
                )
                contradict_count += 1
                changed_items.append({
                    "change_type": "contradict",
                    "category": fact["category"],
                    "subject": fact["subject"],
                    "claim": f"{fact['value']}→{new_val}",
                })

        # Step 4d: 策略生成（只对新建/矛盾的画像）
        strategy_count = 0
        if changed_items:
            print(f"  [sleep] generating strategies for {len(changed_items)} changes...")
            strategies = generate_strategies(changed_items, config,
                                            current_profile=current_profile,
                                            trajectory=trajectory,
                                            language=language)
            for s in strategies:
                cat = s.get("category")
                subj = s.get("subject")
                if not cat or not subj:
                    continue
                try:
                    save_strategy(
                        hypothesis_category=cat,
                        hypothesis_subject=subj,
                        strategy_type=s.get("type", "probe"),
                        description=s.get("description", ""),
                        trigger_condition=s.get("trigger", ""),
                        approach=s.get("approach", ""),
                        reference_time=latest_conv_time,
                    )
                    strategy_count += 1
                except Exception as e:
                    pass

        print(f"  [sleep] step4 done: {len(supports)} support, {new_fact_count} new, {contradict_count} contradict, {strategy_count} strategies")

        # Step 4.5: 观察兜底 — 已移除（v15）
        # 原因：与 4a+4b 完全重复，且是重复记录循环的直接触发点
        # _sweep_uncovered_observations(all_observations, config, trajectory=trajectory)
    else:
        print("  [sleep] no new observations, skip")

    # Step 5: 交叉验证（v14: suspected → confirmed）
    print("  [sleep] cross-verifying suspected facts...")
    suspected_facts = load_suspected_profile()
    confirmed_count = 0

    if suspected_facts:
        judgments = cross_verify_suspected_facts(suspected_facts, config, trajectory=trajectory, language=language)
        judgment_map = {j["fact_id"]: j for j in judgments}

        for f in suspected_facts:
            j = judgment_map.get(f["id"])
            if not j:
                continue

            action = j["action"]
            reason = j.get("reason", "")

            if action == "confirm":
                confirm_profile_fact(f["id"], reference_time=latest_conv_time)
                confirmed_count += 1
            else:
                pass

    print(f"  [sleep] {confirmed_count} confirmed, {len(suspected_facts) - confirmed_count} still suspected")

    # Step 5.1: 矛盾争议解决
    print("  [sleep] resolving disputes...")
    disputed_pairs = load_disputed_facts()
    dispute_resolved = 0
    if disputed_pairs:
        judgments = resolve_disputes_with_llm(disputed_pairs, config, trajectory=trajectory, language=language)
        for j in judgments:
            old_fid = j["old_fact_id"]
            new_fid = j["new_fact_id"]
            action = j["action"]
            reason = j.get("reason", "")

            if action == "accept_new":
                resolve_dispute(old_fid, new_fid, accept_new=True, resolution_time=latest_conv_time)
                dispute_resolved += 1
            elif action == "reject_new":
                resolve_dispute(old_fid, new_fid, accept_new=False, resolution_time=latest_conv_time)
                dispute_resolved += 1
            else:
                pass

        print(f"  [sleep] {dispute_resolved} disputes resolved")
    else:
        pass

    # Step 5.5: 过期处理（v14: 过期事实 → close_time_period）
    print("  [sleep] checking expired facts...")
    expired_facts = get_expired_facts(reference_time=latest_conv_time)
    stale_count = 0
    if expired_facts:
        for f in expired_facts:
            fact_id = f["id"]
            cat = f["category"]
            subj = f["subject"]

            close_time_period(fact_id, end_time=latest_conv_time)
            try:
                save_strategy(
                    hypothesis_category=cat,
                    hypothesis_subject=subj,
                    strategy_type="verify",
                    description=f"{subj}信息长期未提及，已过期关闭",
                    trigger_condition=f"用户提到{subj}相关话题时",
                    approach=f"自然地确认用户的{subj}是否有变化",
                    reference_time=latest_conv_time,
                )
            except Exception:
                pass
            stale_count += 1

        print(f"  [sleep] {stale_count} expired")
    else:
        pass

    # Step 5.7: 兴趣成熟度演进（纯代码，不调 LLM）
    print("  [sleep] maturity evolution...")
    key_anchors = []
    if trajectory and trajectory.get("key_anchors"):
        key_anchors = [str(a).lower() for a in trajectory["key_anchors"]]

    # v14: 从 user_profile 查询
    all_living = load_full_current_profile()

    maturity_count = 0
    for f in all_living:
        start = f.get("start_time")
        updated = f.get("updated_at")
        if not start or not updated:
            continue
        # 统一时区
        f_naive = start.replace(tzinfo=None) if hasattr(start, 'tzinfo') and start.tzinfo else start
        l_naive = updated.replace(tzinfo=None) if hasattr(updated, 'tzinfo') and updated.tzinfo else updated
        span_days = (l_naive - f_naive).days
        ev = f.get("evidence", [])
        evidence_count = len(ev) if isinstance(ev, list) else 0
        current_decay = f.get("decay_days") or 90

        subj_lower = (f.get("subject") or "").lower()
        value_lower = (f.get("value") or "").lower()
        in_anchors = any(subj_lower in a or value_lower in a or a in subj_lower or a in value_lower
                         for a in key_anchors)

        new_decay = _calculate_maturity_decay(span_days, evidence_count, current_decay, in_anchors)
        if new_decay > current_decay:
            update_fact_decay(f["id"], new_decay, reference_time=latest_conv_time)
            maturity_count += 1

    print(f"  [sleep] {maturity_count} upgraded")

    # Step 6: 分析用户模型 → user_model
    print("  [sleep] analyzing user model...")
    if all_convs:
        current_profile_for_model = load_full_current_profile()
        model_results = analyze_user_model(all_convs, config,
                                           current_profile=current_profile_for_model,
                                           language=language)
        print(f"  [sleep] {len(model_results)} dimensions analyzed")
        for m in model_results:
            upsert_user_model(
                dimension=m["dimension"],
                assessment=m["assessment"],
                evidence_summary=m.get("evidence", ""),
            )
    else:
        pass

    # Step 7: 条件更新轨迹总结
    print("  [sleep] checking trajectory update...")
    should_update_trajectory = False
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(DISTINCT session_id) FROM raw_conversations WHERE processed = TRUE")
            total_sessions = cur.fetchone()[0] + len(session_convs)
    finally:
        conn.close()

    prev_session_count = trajectory.get("session_count", 0) if trajectory else 0
    sessions_since_update = total_sessions - prev_session_count

    if sessions_since_update >= 3:
        should_update_trajectory = True

    if not trajectory:
        current_profile = load_full_current_profile()
        if current_profile:
            should_update_trajectory = True

    if should_update_trajectory:
        current_profile = load_full_current_profile()
        if current_profile:
            trajectory_result = generate_trajectory_summary(
                current_profile, config, new_observations=all_observations,
                language=language
            )
            if trajectory_result and trajectory_result.get("life_phase"):
                try:
                    save_trajectory_summary(trajectory_result, session_count=total_sessions,
                                            reference_time=latest_conv_time)
                    print(f"  [sleep] trajectory updated: {trajectory_result.get('life_phase', '?')}")
                except Exception as e:
                    print(f"  [sleep] trajectory save failed: {e}")
            else:
                print("  [sleep] trajectory generation failed")
        else:
            pass
    else:
        pass

    # Step 8: 标记已处理
    mark_processed(all_msg_ids)
    print(f"  [sleep] processed {len(all_msg_ids)} conversations")

    print("  [sleep] done")


if __name__ == "__main__":
    run()
