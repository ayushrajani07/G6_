from __future__ import annotations

import os

# Environment and sizing helpers

def _env_int(name: str) -> int | None:
    val = os.getenv(name)
    if val is None or val == "":
        return None
    try:
        return int(val)
    except Exception:
        return None


def _env_true(name: str) -> bool:
    v = os.getenv(name, "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _env_clip_len() -> int:
    try:
        return max(10, int(os.getenv("G6_PANEL_CLIP", "60")))
    except Exception:
        return 60


def panel_width(name: str) -> int | None:
    # Example: G6_PANEL_W_MARKET=60
    return _env_int(f"G6_PANEL_W_{name.upper()}")


def panel_height(name: str) -> int | None:
    # Example: G6_PANEL_H_MARKET=5
    return _env_int(f"G6_PANEL_H_{name.upper()}")


def effective_panel_width(name: str) -> int | None:
    """Return env-specified width if set; otherwise, when auto-fit is enabled,
    provide a sensible narrow default so panels don't assume full column width.

    If auto-fit is off, defer to Rich to auto-size by returning None.
    """
    w = panel_width(name)
    if w is not None:
        return w
    if _env_true("G6_PANEL_AUTO_FIT"):
        base = _env_clip_len()
        return max(30, min(base + 4, 80))
    return None


def _env_min_col_width() -> int:
    v = _env_int("G6_PANEL_MIN_COL_W")
    if v and v > 0:
        return v
    return max(30, min(_env_clip_len() + 4, 80))
