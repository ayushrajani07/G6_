"""Partial reason hierarchy & grouping utilities.

Provides a stable ordering + grouping layer above flat partial_reason tokens.
Backward compatible: legacy flat counts remain unchanged; new grouped structure
is additive and optional for downstream consumers.
"""
from __future__ import annotations

# Ordered group definitions (group_name, reasons in display order)
REASON_GROUPS: list[tuple[str, list[str]]] = [
    ("coverage_low", ["low_strike", "low_field", "low_both"]),
    ("prefilter", ["prefilter_clamp"]),  # emitted when strict prefilter clamp or clamp fallback
    ("other", ["unknown"]),
]

# Build reverse lookup reason -> group
_REASON_TO_GROUP: dict[str, str] = {}
for g, reasons in REASON_GROUPS:
    for r in reasons:
        _reason = r.strip()
        if _reason:
            _REASON_TO_GROUP[_reason] = g

STABLE_REASON_ORDER: list[str] = [r for _, rs in REASON_GROUPS for r in rs]
STABLE_GROUP_ORDER: list[str] = [g for g, _ in REASON_GROUPS]


def group_reason_counts(flat_counts: dict[str, int] | None) -> dict[str, dict[str, object]]:
    """Return grouped structure:
    {
       group: { 'total': int, 'reasons': { reason: count, ... } }, ...
    }
    Only include groups that have any member reason present (>0 or explicitly in flat counts).
    """
    grouped: dict[str, dict[str, object]] = {}
    if not flat_counts:
        return grouped
    for reason, cnt in flat_counts.items():
        g = _REASON_TO_GROUP.get(reason, 'other')
        bucket = grouped.setdefault(g, {'total': 0, 'reasons': {}})
        bucket['reasons'][reason] = int(cnt)
        bucket['total'] = int(bucket['total']) + int(cnt)
    # Ensure deterministic ordering of reasons inside each group
    for g, data in grouped.items():
        reasons_map = data['reasons']  # type: ignore
        ordered: dict[str, int] = {}
        for r in [r for grp, rs in REASON_GROUPS if grp == g for r in rs]:
            if r in reasons_map:
                ordered[r] = int(reasons_map[r])  # type: ignore[index]
        # Append any unknowns captured under 'other' not in predefined list (stability)
        if g == 'other':
            for r, v in sorted(reasons_map.items()):  # type: ignore[attr-defined]
                if r not in ordered:
                    ordered[r] = int(v)
        data['reasons'] = ordered  # type: ignore
    return grouped

__all__ = [
    'REASON_GROUPS', 'STABLE_REASON_ORDER', 'STABLE_GROUP_ORDER', 'group_reason_counts'
]
