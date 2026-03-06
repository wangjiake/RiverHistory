"""Formatting helpers for LLM prompts."""

import json
from agent.core.sleep_prompts import get_label


def _format_trajectory_block(trajectory: dict | None, language: str = "en") -> str:
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


def _format_profile_for_llm(profile: list[dict], timeline: list[dict] | None = None,
                            language: str = "en", max_items: int = 80) -> str:
    """把画像列表格式化为 LLM 可读文本（v14: 双层画像 + 时间线）。"""
    if not profile:
        return get_label("no_profile", language)

    # 排序：confirmed 优先，mention_count 高优先；截断到 max_items
    sorted_profile = sorted(profile,
                            key=lambda p: (0 if p.get("layer") == "confirmed" else 1,
                                           -(p.get("mention_count") or 1)))
    if max_items and len(sorted_profile) > max_items:
        sorted_profile = sorted_profile[:max_items]

    text = ""
    for p in sorted_profile:
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
