"""Step 2-4b: Observation extraction, classification, and fact creation."""

import json
from datetime import datetime
from agent.utils.llm_client import call_llm
from agent.core.sleep_prompts import get_prompt, get_label
from agent.storage import load_existing_tags
from agent.utils.profile_filter import prepare_profile
from ._parsing import _parse_json_array, _parse_json_object
from ._formatting import _format_profile_for_llm


def extract_observations_and_tags(conversations: list[dict], config: dict,
                                   existing_profile: list[dict] | None = None,
                                   language: str = "en") -> dict:
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

    # 组装已知信息块（当前画像，双层标签）— 截断到 top 25
    known_lines = []
    if existing_profile:
        top_profile, _ = prepare_profile(existing_profile, max_entries=25, language=language)
        for p in top_profile:
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
                    language: str = "en") -> list[dict]:
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
                           language: str = "en") -> list[dict]:
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
    cleaned = []
    for r in results:
        if not isinstance(r, dict):
            continue
        if not r.get("action"):
            r["action"] = "new"
            r.setdefault("reason", "LLM未返回action，自动补为new")
        cleaned.append(r)
    return cleaned


def create_new_facts(new_observations: list[dict],
                     existing_profile: list[dict],
                     config: dict,
                     behavioral_signals: list | None = None,
                     trajectory: dict | None = None,
                     language: str = "en") -> list[dict]:
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
