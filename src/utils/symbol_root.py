"""Symbol root detection and matching utilities.

Goals:
- Provide standardized logic for mapping a tradingsymbol to an index root (e.g. NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, SENSEX, etc.).
- Avoid substring collisions (e.g. NIFTY inside FINNIFTY) by using prefix + boundary heuristics.
- Allow future extension to new exchanges or naming conventions without touching provider logic.
- Support multiple match modes via env var G6_SYMBOL_MATCH_MODE:
    strict (default): prefix match + next token begins with a digit (date) or recognized month code.
    prefix: simple startswith(root) match.
    legacy: substring containment (for backward compatibility if needed).

Public API:
    detect_root(tradingsymbol: str) -> str | None
    symbol_matches_index(index_symbol: str, tradingsymbol: str, *, mode: str | None = None) -> bool

Adding a new index root:
    1. Extend INDEX_ROOTS list with the uppercase root.
    2. (Optional) Add boundary exceptions if its name is a superset of an existing root.

This module is intentionally stateless.
"""
from __future__ import annotations

import os
import re

# Ordered by descending length so longer (more specific) roots match first.
INDEX_ROOTS = [
    "MIDCPNIFTY",
    "BANKNIFTY",
    "FINNIFTY",
    "SENSEX",
    "NIFTY",
]

# Month code heuristic (fallback when no numeric date segment yet). Optional.
_MONTH_FRAGMENT = re.compile(r"(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)")
# Date fragment: two digits day + 3 letter month (e.g. 25SEP) or 2 digits day + 2-4 letters month.
_DATE_FRAGMENT = re.compile(r"\d{1,2}[A-Z]{2,4}")

_DEF_MODE = os.environ.get("G6_SYMBOL_MATCH_MODE", "strict").strip().lower()


def _normalized(s: str) -> str:
    return (s or "").upper().strip()


def detect_root(tradingsymbol: str) -> str | None:
    """Return the index root if the tradingsymbol begins with a known root.

    Longest root wins to prevent partial classification (e.g., MIDCPNIFTY before NIFTY).
    """
    tsu = _normalized(tradingsymbol)
    for root in INDEX_ROOTS:
        if tsu.startswith(root):
            return root
    return None


def _boundary_ok(tradingsymbol: str, root: str) -> bool:
    """Check that the character sequence after the root looks like a boundary into a date or month.

    Accept if:
        - immediately followed by a digit (e.g., NIFTY25...) OR
        - followed by month fragment (e.g., NIFTYSEP...) OR
        - nothing else (exact symbol root, rare) OR
        - followed by a year fragment (YYYY) though not currently used in our naming.
    """
    if len(tradingsymbol) == len(root):  # exact match
        return True
    remainder = tradingsymbol[len(root):]
    if not remainder:
        return True
    if remainder[0].isdigit():  # date style
        return True
    # Month code or date-month hybrid
    if _MONTH_FRAGMENT.match(remainder[:3]):
        return True
    if _DATE_FRAGMENT.match(remainder[:5]):
        return True
    return False


def symbol_matches_index(index_symbol: str, tradingsymbol: str, *, mode: str | None = None) -> bool:
    """Return True if tradingsymbol belongs to index_symbol under chosen mode.

    Modes:
        strict (default): must start with index root and pass boundary heuristic.
        prefix: must start with index root (no boundary check).
        legacy: root substring appears anywhere (NOT recommended; for fallback only).
    """
    idx = _normalized(index_symbol)
    tsu = _normalized(tradingsymbol)
    use_mode = (mode or _DEF_MODE) or 'strict'
    if use_mode not in {"strict", "prefix", "legacy"}:
        use_mode = "strict"

    if use_mode == "legacy":
        return idx in tsu
    if use_mode == "prefix":
        return tsu.startswith(idx)

    # strict
    if not tsu.startswith(idx):
        return False
    return _boundary_ok(tsu, idx)

__all__ = [
    "detect_root",
    "symbol_matches_index",
    "INDEX_ROOTS",
]

# --- Additional helper for stricter heuristics (future scaling) ---
def parse_root_before_digits(tradingsymbol: str) -> str | None:
    """Extract the leading root substring before the first digit (or month code) for comparison.

    Example:
        NIFTY25SEP25000CE -> NIFTY
        FINNIFTY25SEP25000CE -> FINNIFTY
        BANKNIFTY25SEP47000PE -> BANKNIFTY
    Falls back to detect_root if no digits found.
    """
    tsu = _normalized(tradingsymbol)
    for i,ch in enumerate(tsu):
        if ch.isdigit():
            return tsu[:i] if i>0 else None
    # no digit; attempt month fragment boundary
    for root in INDEX_ROOTS:
        if tsu.startswith(root):
            return root
    return None
