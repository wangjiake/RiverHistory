"""Interest maturity evolution logic."""

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
