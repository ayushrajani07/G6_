"""Option instrument acceptance logic extracted from provider.

Provides reusable acceptance predicate decoupled from KiteProvider implementation.
Future extension: plug-in rejection metrics, dynamic rule injection, symbol alias maps.
"""
from __future__ import annotations

from dataclasses import dataclass
import datetime as _dt
from typing import Any, Optional, Dict, Tuple

try:  # lightweight root + symbol utilities (optional failure tolerant)
    from src.utils.symbol_root import detect_root, parse_root_before_digits, symbol_matches_index  # type: ignore
    from src.utils.root_cache import cached_detect_root  # type: ignore
except Exception:  # pragma: no cover
    def detect_root(s: str) -> str:  # type: ignore
        return ""
    def cached_detect_root(s: str):  # type: ignore
        return detect_root(s)
    def parse_root_before_digits(s: str) -> str:  # type: ignore
        return ""
    def symbol_matches_index(index: str, ts: str, mode: str = "strict") -> bool:  # type: ignore
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

    def normalize_expiry(self, raw: Any) -> Optional[_dt.date]:  # noqa: D401
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
def accept_option(inst: Dict[str, Any], ctx: OptionFilterContext, root_cache: Dict[str,str], *, expected_expiry: Optional[_dt.date] = None, contamination_samples: list[str] | None = None) -> Tuple[bool, str]:
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
