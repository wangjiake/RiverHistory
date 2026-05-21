
import json
from agent.config.prompts import get_labels


def _format_trajectory_block(trajectory: dict | None, language: str = "en") -> str:
    L = get_labels("context.labels", language)
    if not trajectory or not trajectory.get("life_phase"):
        return f"\n{L['trajectory_summary']}：{L['trajectory_none']}\n"
    return (
        f"\n{L['trajectory_summary']}：\n"
        f"  {L['phase']}: {trajectory.get('life_phase', '?')}\n"
        f"  {L['characteristics']}: {trajectory.get('phase_characteristics', '?')}\n"
        f"  {L['direction']}: {trajectory.get('trajectory_direction', '?')}\n"
        f"  {L['stability']}: {trajectory.get('stability_assessment', '?')}\n"
        f"  {L['anchors']}: {json.dumps(trajectory.get('key_anchors', []), ensure_ascii=False)}\n"
        f"  {L['volatile_areas']}: {json.dumps(trajectory.get('volatile_areas', []), ensure_ascii=False)}\n"
        f"  {L['recent_momentum']}: {trajectory.get('recent_momentum', '?')}\n"
        f"  {L['summary']}: {trajectory.get('full_summary', '?')}\n"
    )


def _format_profile_for_llm(profile: list[dict], timeline: list[dict] | None = None, language: str = "en", max_items: int = 80) -> str:
    L = get_labels("context.labels", language)
    if not profile:
        return L["no_profile"] + "\n"

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
        if p.get("superseded_by"):
            layer_tag = L["layer_disputed"]
        elif layer == "confirmed":
            layer_tag = L["layer_core"]
        else:
            layer_tag = L["layer_suspected"]

        line = (
            f"#{fact_id} {layer_tag} [{p['category']}] {p['subject']}: {p['value']} "
            f"({L['mentions']}{mention_count}, source={p.get('source_type', 'stated')}, "
            f"{L['start']}={start}, {L['updated']}={updated}, {L['evidence']}{len(ev)}"
        )
        if p.get("superseded_by"):
            line += f", {L['challenged_by'].format(p['superseded_by'])}"
        if p.get("supersedes"):
            line += f", {L['challenges'].format(p['supersedes'])}"
        line += ")\n"
        text += line

    if timeline:
        closed = [t for t in timeline if t.get("end_time") or t.get("human_end_time") or t.get("rejected")]
        if closed:
            text += f"\n{L['closed_timeline']}：\n"
            for t in closed:
                start = t["start_time"].strftime("%Y-%m-%d") if t.get("start_time") else "?"
                if t.get("rejected"):
                    text += (
                        f"  [{t['category']}] {t['subject']}: {t['value']} "
                        f"({start}, {L['marked_error']})\n"
                    )
                else:
                    eff_end = t.get("human_end_time") or t.get("end_time")
                    end = eff_end.strftime("%Y-%m-%d") if eff_end else "?"
                    text += (
                        f"  [{t['category']}] {t['subject']}: {t['value']} "
                        f"({start} ~ {end})\n"
                    )
    return text
