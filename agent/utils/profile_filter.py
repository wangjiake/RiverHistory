
from datetime import datetime, timedelta
from agent.core.sleep_prompts import get_label


def prepare_profile(profile, query_text=None, config=None,
                    max_entries=30, language="zh"):
    """
    过滤 → 排序 → 截断

    1. 过滤：去掉 superseded_by is not None 的条目
    2. 排序：fallback 评分（confirmed +3, 近30天 +2, mention>=3 +1）
    3. rest_summary：剩余按 category 计数归并

    Returns: (top_entries: list[dict], rest_summary: str)
    """
    active = [p for p in profile if not p.get("superseded_by")]
    if not active:
        return [], ""

    now = datetime.now()
    thirty_days_ago = now - timedelta(days=30)

    def _fallback_score(p):
        score = 0
        if p.get("layer") == "confirmed":
            score += 3
        updated = p.get("updated_at")
        if updated and updated.replace(tzinfo=None) >= thirty_days_ago:
            score += 2
        mc = p.get("mention_count") or 0
        if mc >= 3:
            score += 1
        return score

    active.sort(key=_fallback_score, reverse=True)

    top = active[:max_entries]
    rest = active[max_entries:]

    rest_summary = ""
    if rest:
        from collections import Counter
        cat_counts = Counter(p.get("category", "?") for p in rest)
        parts = [f"{cat}×{cnt}" for cat, cnt in cat_counts.most_common()]
        rest_summary = "（其余 " + ", ".join(parts) + "）"

    return top, rest_summary


def format_profile_text(profile, keywords=None, config=None,
                        max_entries=30, detail="full", language="zh"):
    """
    prepare_profile + 格式化为文本

    detail="full":  [核心] [职业] 当前公司: 字节跳动
    detail="light": [职业] 当前公司: 字节跳动

    Returns: str（top-K 完整行 + 摘要行）
    """
    top_entries, rest_summary = prepare_profile(
        profile, query_text=keywords, config=config,
        max_entries=max_entries, language=language,
    )
    if not top_entries:
        return ""

    lines = []
    for p in top_entries:
        if detail == "full":
            layer = p.get("layer", "suspected")
            if layer == "confirmed":
                tag = get_label("layer_confirmed", language)
            else:
                tag = get_label("layer_suspected", language)
            lines.append(f"  {tag} [{p['category']}] {p['subject']}: {p['value']}")
        else:
            lines.append(f"  [{p['category']}] {p['subject']}: {p['value']}")

    text = "\n".join(lines)
    if rest_summary:
        text += "\n" + rest_summary
    return text
