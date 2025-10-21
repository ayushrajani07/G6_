from __future__ import annotations

"""CollectorSettings: single-pass environment hydration for collector/expiry logic.

Phase 0 introduction (pipeline rationalization). Goals:
- Centralize parsing of frequently accessed environment flags and numeric thresholds.
- Provide a stable object passed into expiry processing (legacy path first, pipeline v2 later).
- Enable unit testing of filter behavior without patching os.environ repeatedly.

Future extensions: add strike span heuristics, salvage tuning parameters, domain model toggles.
"""
import os
from dataclasses import dataclass

_TRUTHY = {"1","true","yes","on"}

def _to_int(name: str, default: int) -> int:
    try:
        raw = os.getenv(name, "").strip()
        if not raw:
            return default
        val = int(raw)
        if val < 0:
            return default
        return val
    except Exception:
        return default

def _to_float(name: str, default: float) -> float:
    try:
        raw = os.getenv(name, "").strip()
        if not raw:
            return default
        val = float(raw)
        return val
    except Exception:
        return default

def _is_truthy(name: str) -> bool:
    return os.getenv(name, "").lower() in _TRUTHY

@dataclass(slots=True)
class CollectorSettings:
    min_volume: int = 0
    min_open_interest: int = 0
    volume_percentile: float = 0.0  # reserved for future percentile-based filtering
    salvage_enabled: bool = True
    retry_on_empty: bool = False
    trace_enabled: bool = False
    foreign_expiry_salvage: bool = False
    pipeline_v2_flag: bool = False  # Phase 1: enable shadow pipeline (resolve->enrich) comparison
    # Placeholder for future domain model toggles
    domain_models: str | None = None  # raw string spec (comma-separated)

    @classmethod
    def load(cls) -> CollectorSettings:
        return cls(
            min_volume=_to_int('G6_FILTER_MIN_VOLUME', 0),
            min_open_interest=_to_int('G6_FILTER_MIN_OI', 0),
            volume_percentile=_to_float('G6_FILTER_VOLUME_PERCENTILE', 0.0),
            salvage_enabled=not _is_truthy('G6_DISABLE_SALVAGE'),
            retry_on_empty=_is_truthy('G6_RETRY_ON_EMPTY'),
            trace_enabled=_is_truthy('G6_TRACE_COLLECTOR'),
            foreign_expiry_salvage=_is_truthy('G6_FOREIGN_EXPIRY_SALVAGE'),
            pipeline_v2_flag=_is_truthy('G6_COLLECTOR_PIPELINE_V2'),
            domain_models=os.getenv('G6_DOMAIN_MODELS','') or None,
        )

    # Backward compatibility: some legacy code expects .min_oi
    @property
    def min_oi(self) -> int:  # pragma: no cover - trivial alias
        return self.min_open_interest

# Basic filter helper (Phase 0 scope)

def apply_basic_filters(enriched: dict[str, dict], settings: CollectorSettings) -> dict[str, dict]:
    """Return filtered copy of enriched options based on simple volume/OI thresholds.

    - Applies min_volume if >0 and field 'volume' present & numeric.
    - Applies min_open_interest if >0 and field 'oi' present & numeric.
    - Does not mutate input dict; returns a new dict preserving original ordering (insertion order preserved in CPython >=3.7).
    - Percentile filtering intentionally deferred (stub field).
    """
    if not enriched:
        return {}
    out: dict[str, dict] = {}
    mv = settings.min_volume
    moi = settings.min_open_interest
    for k, v in enriched.items():
        try:
            if mv and isinstance(v, dict):
                vol = v.get('volume')
                if isinstance(vol, (int, float)) and vol < mv:
                    continue
            if moi and isinstance(v, dict):
                oi = v.get('oi')
                if isinstance(oi, (int, float)) and oi < moi:
                    continue
            out[k] = v
        except Exception:
            # Defensive: skip pathological entries rather than failing entire filter
            continue
    return out

__all__ = [
    'CollectorSettings',
    'apply_basic_filters',
]
