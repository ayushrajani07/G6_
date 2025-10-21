"""Option instrument acceptance logic extracted from provider.

Provides reusable acceptance predicate decoupled from KiteProvider implementation.
Future extension: plug-in rejection metrics, dynamic rule injection, symbol alias maps.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from importlib import import_module
from typing import Any

# Safe adapters around optional utilities with signature normalization
try:  # pragma: no cover - import resolution only
    _sym_mod = import_module('src.utils.symbol_root')
    _detect_root_opt = getattr(_sym_mod, 'detect_root', None)
    _parse_root_before_digits_opt = getattr(_sym_mod, 'parse_root_before_digits', None)
    _symbol_matches_index_opt = getattr(_sym_mod, 'symbol_matches_index', None)
except Exception:
    _detect_root_opt = None
    _parse_root_before_digits_opt = None
    _symbol_matches_index_opt = None
try:
    _cache_mod = import_module('src.utils.root_cache')
    _cached_detect_root_opt = getattr(_cache_mod, 'cached_detect_root', None)
except Exception:
    _cached_detect_root_opt = None

def detect_root(s: str) -> str:
    try:
        if callable(_detect_root_opt):
            r = _detect_root_opt(s)
            return str(r or "")
    except Exception:
        pass
    return ""

def cached_detect_root(s: str) -> str:
    try:
        if callable(_cached_detect_root_opt):
            r = _cached_detect_root_opt(s)
            return str(r or "")
    except Exception:
        pass
    return detect_root(s)

def parse_root_before_digits(s: str) -> str:
    try:
        if callable(_parse_root_before_digits_opt):
            r = _parse_root_before_digits_opt(s)
            return str(r or "")
    except Exception:
        pass
    return ""

def symbol_matches_index(index: str, ts: str, mode: str = "strict") -> bool:
    try:
        if callable(_symbol_matches_index_opt):
            # External function may require keyword-only parameters
            return bool(_symbol_matches_index_opt(index_symbol=index, tradingsymbol=ts, mode=mode))
    except Exception:
        pass
    # Fallback heuristic: prefix match
    return ts.upper().startswith(index.upper())

@dataclass(slots=True)
class OptionFilterContext:
    index_symbol: str
    expiry_target: _dt.date
    strike_key_set: set[float]
    match_mode: str = "strict"
    underlying_strict: bool = True
    safe_mode: bool = True

    def normalize_expiry(self, raw: Any) -> _dt.date | None:  # noqa: D401
        """Best effort normalization of instrument expiry to date."""
        if raw is None:
            return None
        if isinstance(raw, _dt.datetime):
            return raw.date()
        if isinstance(raw, _dt.date):
            return raw
        s = str(raw).strip()
        if not s:
            return None
        # Fast path YYYY-MM-DD
        try:
            return _dt.datetime.strptime(s[:10], '%Y-%m-%d').date()
        except Exception:
            pass
        for fmt in ('%d-%b-%Y', '%d-%m-%Y', '%Y/%m/%d', '%d/%m/%Y'):
            try:
                return _dt.datetime.strptime(s, fmt).date()
            except Exception:
                continue
        return None

# Rejection reasons canonical list
REJECT_NOT_OPTION = 'not_option_type'
REJECT_ROOT = 'root_mismatch'
REJECT_EXPIRY = 'expiry_mismatch'
REJECT_STRIKE = 'strike_mismatch'
REJECT_UNDERLYING = 'underlying_mismatch'
ACCEPT = 'accepted'

# Public API
def accept_option(inst: dict[str, Any], ctx: OptionFilterContext, root_cache: dict[str,str], *, expected_expiry: _dt.date | None = None, contamination_samples: list[str] | None = None) -> tuple[bool, str]:
    tsym = str(inst.get('tradingsymbol',''))
    itype = (inst.get('instrument_type') or '').upper()
    if itype not in ('CE','PE'):
        return False, REJECT_NOT_OPTION

    def _get_root(ts: str) -> str:
        # First consult per-call root_cache (short-lived) then global cache
        r = root_cache.get(ts)
        if r is not None:
            return r
        try:
            r = cached_detect_root(ts) or ''
        except Exception:
            r = ''
        root_cache[ts] = r
        return r

    # Early root gate
    try:
        _r = _get_root(tsym) or ''
        if _r and _r != ctx.index_symbol.upper():
            if contamination_samples is not None and len(contamination_samples) < 6:
                contamination_samples.append(tsym)
            return False, REJECT_ROOT
    except Exception:
        pass

    inst_exp_raw = inst.get('expiry')
    inst_exp_norm = ctx.normalize_expiry(inst_exp_raw)
    target = expected_expiry or ctx.expiry_target
    if not inst_exp_norm or inst_exp_norm != target:
        return False, REJECT_EXPIRY

    # Strike membership
    try:
        strike_val = float(inst.get('strike',0) or 0)
    except Exception:
        strike_val = 0.0
    if round(strike_val,2) not in ctx.strike_key_set:
        return False, REJECT_STRIKE

    # Symbol matching
    if not symbol_matches_index(ctx.index_symbol, tsym, mode=ctx.match_mode.lower()):
        return False, REJECT_ROOT

    if ctx.safe_mode:
        parsed = parse_root_before_digits(tsym) or ''
        if parsed and parsed != ctx.index_symbol.upper():
            if contamination_samples is not None and len(contamination_samples) < 6:
                contamination_samples.append(tsym)
            return False, REJECT_ROOT

    if ctx.underlying_strict:
        base_name = str(inst.get('name') or inst.get('underlying') or '').upper()
        if base_name and base_name != ctx.index_symbol.upper():
            if contamination_samples is not None and len(contamination_samples) < 6:
                contamination_samples.append(tsym)
            return False, REJECT_UNDERLYING

    return True, ACCEPT
