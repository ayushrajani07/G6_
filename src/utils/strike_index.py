"""StrikeIndex helper (R2 performance optimization).

Provides fast membership, diff, and descriptive statistics for strike ladders.
Uses scaled-integer representation to avoid repeated float rounding & tolerance checks.

Design Goals:
- O(1) membership checks
- Cheap diff between requested & realized sets
- Central place to extend adaptive logic (future: dynamic depth scaling)
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

__all__ = ["StrikeIndex", "build_strike_index"]

SCALE = 100  # two decimal precision scaling
TOL_UNITS = 1  # <=1 unit => <=0.01 actual difference considered equal

@dataclass(slots=True)
class StrikeIndex:
    original: Sequence[float]
    sorted: list[float]
    scaled_set: set[int]
    min_step: float

    def contains(self, value: float) -> bool:
        try:
            sv = int(round(float(value) * SCALE))
        except Exception:
            return False
        if sv in self.scaled_set:
            return True
        # tolerant check (+/-1 unit) for small float jitter
        return (sv - 1 in self.scaled_set) or (sv + 1 in self.scaled_set)

    def diff(self, realized: Iterable[float]) -> dict[str, list[float]]:
        """Return missing and extra strikes relative to realized list."""
        r_scaled = set()
        for v in realized:
            try:
                r_scaled.add(int(round(float(v) * SCALE)))
            except Exception:
                continue
        missing_scaled = [s for s in self.scaled_set if s not in r_scaled]
        extra_scaled = [s for s in r_scaled if s not in self.scaled_set]
        # Convert back (sorted for stable output)
        missing = sorted({ms / SCALE for ms in missing_scaled})
        extra = sorted({es / SCALE for es in extra_scaled})
        return {"missing": missing, "extra": extra}

    def describe(self, sample: int = 6) -> dict[str, Any]:
        strikes = self.sorted
        n = len(strikes)
        if n == 0:
            return {"count": 0, "min": None, "max": None, "step": 0, "sample": []}
        # step heuristic: min positive diff
        diffs = [b - a for a, b in zip(strikes, strikes[1:], strict=False) if b - a > 0]
        step = min(diffs) if diffs else 0
        if n <= sample:
            samp = [f"{s:.0f}" for s in strikes]
        else:
            head = [f"{s:.0f}" for s in strikes[:2]]
            mid = [f"{strikes[n//2]:.0f}"]
            tail = [f"{s:.0f}" for s in strikes[-2:]]
            samp = head + mid + tail
        return {"count": n, "min": strikes[0], "max": strikes[-1], "step": step, "sample": samp, "min_step": self.min_step}

    def realized_coverage(self, realized: Iterable[float]) -> float:
        try:
            r_scaled = {int(round(float(v) * SCALE)) for v in realized if float(v) > 0}
        except Exception:
            r_scaled = set()
        if not self.scaled_set:
            return 0.0
        matched = sum(1 for s in self.scaled_set if s in r_scaled or (s-1 in r_scaled) or (s+1 in r_scaled))
        return matched / len(self.scaled_set)


def build_strike_index(strikes: Sequence[float]) -> StrikeIndex:
    filtered: list[float] = []
    for s in strikes:
        try:
            fv = float(s)
            if fv > 0:
                filtered.append(fv)
        except Exception:
            continue
    filtered.sort()
    scaled_set = {int(round(s * SCALE)) for s in filtered}
    # Precompute min step
    diffs = [b - a for a, b in zip(filtered, filtered[1:], strict=False) if b - a > 0]
    min_step = min(diffs) if diffs else 0
    return StrikeIndex(original=strikes, sorted=filtered, scaled_set=scaled_set, min_step=min_step)
