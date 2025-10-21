"""Runtime status JSON validator (lightweight, no external deps).

Performs minimal structural & semantic checks approximating the JSON schema
in `runtime_status_schema.json` without requiring jsonschema package.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

REQUIRED_TOP = [
    "timestamp", "cycle", "elapsed", "interval", "sleep_sec", "indices", "indices_info"
]

OPTIONAL_NUMERIC_BOUNDS = {
    "success_rate_pct": (0, 100),
    "api_success_rate": (0, 100),
    "options_last_cycle": (0, None),
    "options_per_minute": (0, None),
    "memory_mb": (0, None),
    "cpu_pct": (0, None),
}


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _known_top_level_keys() -> Iterable[str]:  # small helper for strict mode
    yield from REQUIRED_TOP
    yield from OPTIONAL_NUMERIC_BOUNDS.keys()
    # dynamic / evolving optional fields (keep list minimal to avoid masking issues)
    for k in (
        "success_rate_pct", "api_success_rate", "readiness_ok", "readiness_reason",
        "options_last_cycle", "options_per_minute", "memory_mb", "cpu_pct",
    ):
        yield k


def validate_runtime_status(obj: dict[str, Any], *, strict: bool = False) -> list[str]:
    """Validate runtime status structure.

    Parameters:
        obj: Parsed JSON object.
        strict: When True, reject unknown top-level keys not part of the
                documented set. This is useful in tests/CI to surface
                unexpected drift but should remain False in production to
                allow forward-compatible additive fields.
    Returns:
        List of human-readable error strings. Empty when valid.
    """
    errors: list[str] = []
    if not isinstance(obj, dict):
        return ["Root must be object"]
    # Required fields
    for k in REQUIRED_TOP:
        if k not in obj:
            errors.append(f"Missing required field: {k}")
    # Basic types
    if isinstance(obj.get("timestamp"), str):
        if not obj["timestamp"].endswith("Z"):
            errors.append("timestamp must end with 'Z'")
    else:
        errors.append("timestamp must be string")
    for numeric_key in ("cycle", "elapsed", "interval", "sleep_sec"):
        v = obj.get(numeric_key)
        if not _is_number(v):
            errors.append(f"{numeric_key} must be number")
        else:
            if v < 0:  # type: ignore[operator]
                errors.append(f"{numeric_key} must be >=0")
    # indices
    inds = obj.get("indices")
    if not isinstance(inds, list):
        errors.append("indices must be list")
    else:
        if not all(isinstance(i, str) for i in inds):
            errors.append("indices entries must be strings")
    # indices_info
    info = obj.get("indices_info")
    if not isinstance(info, dict):
        errors.append("indices_info must be object")
    else:
        for name, sub in info.items():
            if not isinstance(sub, dict):
                errors.append(f"indices_info.{name} must be object")
                continue
            # required subfields
            for req in ("ltp", "options"):
                if req not in sub:
                    errors.append(f"indices_info.{name} missing {req}")
            # ltp numeric/null
            if "ltp" in sub and sub["ltp"] is not None and not _is_number(sub["ltp"]):
                errors.append(f"indices_info.{name}.ltp must be number or null")
            if "options" in sub and sub["options"] is not None and not isinstance(sub["options"], int):
                errors.append(f"indices_info.{name}.options must be int or null")
    # Optional bounded fields
    for key, (lo, hi) in OPTIONAL_NUMERIC_BOUNDS.items():
        val = obj.get(key)
        if val is None:
            continue
        if not _is_number(val):
            errors.append(f"{key} must be numeric or null")
            continue
        if lo is not None and val < lo:
            errors.append(f"{key} must be >= {lo}")
        if hi is not None and val > hi:
            errors.append(f"{key} must be <= {hi}")
    if strict:
        known = set(_known_top_level_keys())
        for k in obj.keys():
            if k not in known:
                errors.append(f"Unknown top-level field: {k}")
    return errors

__all__ = ["validate_runtime_status"]
