"""Step 5.1: Dispute resolution with LLM."""

import json
from datetime import datetime, timedelta
from agent.utils.llm_client import call_llm
from agent.core.sleep_prompts import get_prompt
from agent.storage import (
    load_conversation_summaries_around,
    load_summaries_by_observation_subject,
)
from ._parsing import _parse_json_array


def resolve_disputes_with_llm(disputed_pairs: list[dict], config: dict,
                              trajectory: dict | None = None,
                              language: str = "zh") -> list[dict]:
    """Step 5.1: 矛盾争议解决 — 用 LLM 判断每对矛盾中哪个值是正确的当前状态。
    v15: 精确时间线 — 按矛盾创建时间分成"之前/之后"两组观察。"""
    llm_config = config.get("llm", {})
    if not disputed_pairs:
        return []

    # ── 规则预处理 ──
    rule_results = []
    llm_candidates = []
    now = datetime.now()
    for pair in disputed_pairs:
        old = pair["old"]
        new = pair["new"]
        new_mc = new.get("mention_count") or 1
        old_mc = old.get("mention_count") or 1
        new_start = new.get("start_time")
        old_start = old.get("start_time")

        # 规则1：新值 mention_count>=2 且时间更新 → accept_new
        if new_mc >= 2 and new_start and old_start and new_start > old_start:
            rule_results.append({
                "old_fact_id": old["id"], "new_fact_id": new["id"],
                "action": "accept_new",
                "reason": "规则：新值mention>=2且时间更新"
            })
            continue

        # 规则2：争议超过 90 天无新证据 → mention_count 高的胜出
        dispute_age = (now - new_start.replace(tzinfo=None)).days if new_start else 0
        if dispute_age > 90:
            if new_mc > old_mc:
                rule_results.append({
                    "old_fact_id": old["id"], "new_fact_id": new["id"],
                    "action": "accept_new",
                    "reason": f"规则：争议{dispute_age}天，新值mention更高"
                })
            else:
                rule_results.append({
                    "old_fact_id": old["id"], "new_fact_id": new["id"],
                    "action": "reject_new",
                    "reason": f"规则：争议{dispute_age}天，旧值mention更高"
                })
            continue

        llm_candidates.append(pair)

    if not llm_candidates:
        return rule_results

    items_text = ""
    for pair in llm_candidates:
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
    llm_results = _parse_json_array(raw)
    llm_results = [r for r in llm_results if isinstance(r, dict)
                   and r.get("old_fact_id") and r.get("new_fact_id") and r.get("action")]
    return rule_results + llm_results
