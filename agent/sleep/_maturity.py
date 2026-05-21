
_MATURITY_TIERS = [
    (730, 10, 730),
    (365, 6, 365),
    (90, 3, 180),
]


def _calculate_maturity_decay(span_days: int, evidence_count: int,
                               current_decay: int, in_key_anchors: bool = False) -> int:
    boost = 0.6 if in_key_anchors else 1.0
    for min_span, min_ev, target in _MATURITY_TIERS:
        if (span_days >= min_span * boost
                and evidence_count >= max(1, int(min_ev * boost))
                and target > current_decay):
            return target
    return current_decay
