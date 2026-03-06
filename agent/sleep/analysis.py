"""Step 3.5, 4d, 5, 6: Analysis functions (strategies, user model, behavioral patterns, cross-verify)."""

import json
from datetime import datetime, timedelta
from agent.utils.llm_client import call_llm
from agent.core.sleep_prompts import get_prompt, get_label
from agent.storage import (
    load_user_model, load_full_current_profile, load_timeline,
    load_summaries_by_observation_subject,
)
from agent.utils.profile_filter import prepare_profile
from ._parsing import _parse_json_array
from ._formatting import _format_trajectory_block


def generate_strategies(changed_items: list[dict], config: dict,
                        current_profile: list[dict] | None = None,
                        trajectory: dict | None = None,
                        language: str = "en") -> list[dict]:
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

    # 用户画像概览（截断到 top 15）
    profile_context = ""
    if current_profile:
        _strat_query = " ".join(item.get("category", "") + " " + item.get("subject", "") for item in changed_items)
        top_profile, _ = prepare_profile(current_profile, query_text=_strat_query, max_entries=15, language=language)
        profile_lines = []
        for p in top_profile:
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
                       language: str = "en") -> list[dict]:
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

    # 用户画像概览（截断到 top 20）
    profile_block = ""
    if current_profile:
        top_profile, _ = prepare_profile(current_profile, max_entries=20, language=language)
        profile_lines = []
        for p in top_profile:
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
                                 language: str = "en") -> list[dict]:
    """Step 3.5: 行为模式分析（v14: 用双层画像）"""
    llm_config = config.get("llm", {})
    if not observations or len(observations) < 1:
        return []

    # 格式化画像（截断到 top 20）
    if current_profile:
        top_profile, _ = prepare_profile(current_profile, max_entries=20, language=language)
        profile_text = ""
        for p in top_profile:
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
                                  language: str = "en") -> list[dict]:
    """Step 5: 交叉验证怀疑画像（v14: suspected → confirmed）。"""
    llm_config = config.get("llm", {})
    if not suspected_facts:
        return []

    # ── 规则预处理：source_type=stated + mention_count>=2 → 直接确认 ──
    rule_results = []
    llm_candidates = []
    for f in suspected_facts:
        mc = f.get("mention_count") or 1
        if f.get("source_type") == "stated" and mc >= 2:
            rule_results.append({"fact_id": f["id"], "action": "confirm",
                                 "reason": "规则：stated+mention>=2直接确认"})
        else:
            llm_candidates.append(f)

    if not llm_candidates:
        return rule_results

    # 按 mention_count 降序，限制最多 80 条发给 LLM
    llm_candidates.sort(key=lambda f: -(f.get("mention_count") or 1))
    llm_candidates = llm_candidates[:80]

    # 预加载全量画像，用于查找被取代的旧事实
    all_current = load_full_current_profile()
    all_facts_map = {p["id"]: p for p in all_current}

    # 格式化怀疑画像
    items_text = ""
    seen_subjects = set()  # 收集 (category, subject) 用于加载时间线
    for f in llm_candidates:
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

    # 按 subject 分类加载相关对话摘要作为佐证（限最近 3 个月）
    obs_context = ""
    three_months_ago = datetime.now() - timedelta(days=90)
    for cat, subj in seen_subjects:
        if not subj:
            continue
        subj_summaries = load_summaries_by_observation_subject(subject=subj)
        all_subj = subj_summaries.get("before", [])
        all_subj = [s for s in all_subj
                     if s.get('user_input_at') and s['user_input_at'].replace(tzinfo=None) >= three_months_ago]
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
    llm_results = _parse_json_array(raw)
    llm_results = [r for r in llm_results if isinstance(r, dict) and r.get("fact_id") and r.get("action")]
    return rule_results + llm_results
