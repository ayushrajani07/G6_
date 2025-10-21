"""Option instrument filtering and retrieval (Phase 6 extraction).

This module encapsulates the previously inlined `KiteProvider.option_instruments` logic
into composable helper functions so the provider class thins down to an orchestration
facade. Responsibilities separated:

Prefilter stage          -> prefilter_option_universe
Strike index build       -> build_strike_membership (wraps existing strike_index helper)
Candidate selection      -> collect_candidates_for_expiry
Core matching            -> match_options (wraps accept_option loop)
Expiry fallbacks         -> apply_expiry_fallbacks (forward / backward strategies)
Caching + logging glue   -> option_instruments (public entrypoint)

The public entrypoint mirrors the provider method signature so existing callers
remain unchanged. It expects a provider-like object supplying:
  - get_instruments(exchange)
  - _settings (with enable_nearest_expiry_fallback / enable_backward_expiry_fallback / trace_collector)
  - _state (ProviderState or shim) with option_instrument_cache, option_cache_day, option_cache_hits/misses
  - logging utilities (module-level logger is used, but provider for ATM helpers if needed in future)

Side-effects (cache population, metrics emission) are preserved.
"""
from __future__ import annotations

import datetime as _dt
import logging
import os
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# Reuse global concise flag from provider module if already imported; else default True
try:  # pragma: no cover - defensive import
    from src.broker.kite_provider import is_concise_logging
except Exception:  # pragma: no cover
    def is_concise_logging() -> bool:  # type: ignore
        return True

# Local type aliases
Instrument = dict[str, Any]


@runtime_checkable
class ProviderLike(Protocol):  # minimal shape required by option_instruments
    _settings: Any
    _state: Any
    def get_instruments(self, exchange: str) -> Sequence[Instrument]: ...  # pragma: no cover
    _daily_universe: Sequence[Instrument] | None

# ---------------------------------------------------------------------------
# Small dataclasses for sharing context between helpers
# ---------------------------------------------------------------------------
@dataclass
class FilterRuntime:
    index_symbol: str
    expiry_target: _dt.date
    strikes: Sequence[float]

# ---------------------------------------------------------------------------
# Prefilter Stage
# ---------------------------------------------------------------------------
def prefilter_option_universe(index_symbol: str, instruments: Sequence[Instrument], raw_total_opts: int) -> tuple[list[Instrument], bool, dict[str, int]]:
    """Prefilter instruments to reduce downstream work.

    Returns (filtered_instruments, used_flag, diagnostics_counts)
    """
    from src.utils.env_flags import is_truthy_env  # type: ignore
    disabled = is_truthy_env('G6_DISABLE_PREFILTER')
    if disabled:
        return [inst for inst in instruments if (inst.get('instrument_type') or '') in ('CE','PE')], False, {'rejected': 0}

    try:
        from src.utils.symbol_root import detect_root as _pf_detect_root
        from src.utils.symbol_root import parse_root_before_digits as _pf_parse_root
    except Exception:  # pragma: no cover
        _pf_detect_root = lambda _s: ''
        _pf_parse_root = lambda _s: ''
    tgt = index_symbol.upper()
    filtered: list[Instrument] = []
    rejected = 0
    start_ts = time.time()
    for inst in instruments:
        itype = (inst.get('instrument_type') or '').upper()
        # Normalize common alternative instrument types (OPTIDX/OPTSTK) by inferring CE/PE from tradingsymbol suffix
        if itype not in ('CE','PE'):
            tsym_norm = str(inst.get('tradingsymbol','')).upper()
            if itype in ('OPTIDX','OPTSTK','OPT'):
                if tsym_norm.endswith('CE'):
                    itype = 'CE'
                elif tsym_norm.endswith('PE'):
                    itype = 'PE'
            if itype not in ('CE','PE'):
                continue
        tsym = str(inst.get('tradingsymbol','')).upper()
        base_name = str(inst.get('name') or inst.get('underlying') or '').upper()
        try:
            root = _pf_detect_root(tsym) or _pf_parse_root(tsym) or ''
        except Exception:
            root = ''
        accept = False
        if root == tgt:
            accept = True
        elif base_name == tgt and (not root or root == tgt):
            accept = True
        elif tsym.startswith(tgt):
            accept = True
        if accept:
            filtered.append(inst)
        else:
            rejected += 1
    kept = len(filtered)
    used = True
    if kept == 0 or (kept < 5 and raw_total_opts > 40) or (kept > 0 and raw_total_opts/kept > 500):
        # Too aggressive – revert but still narrow to option types
        filtered = []
        for inst in instruments:
            itype = (inst.get('instrument_type') or '').upper()
            if itype in ('CE','PE'):
                filtered.append(inst)
            elif itype in ('OPTIDX','OPTSTK','OPT'):
                ts = str(inst.get('tradingsymbol','')).upper()
                if ts.endswith('CE') or ts.endswith('PE'):
                    filtered.append(inst)
        used = False
    # Emit structured event (best-effort)
    try:
        from src.collectors.helpers.struct_events import emit_instrument_prefilter_summary as _emit_prefilter_struct
        ce_ct = pe_ct = 0
        for inst in filtered:
            ity = (inst.get('instrument_type') or '').upper()
            if ity == 'CE': ce_ct += 1
            elif ity == 'PE': pe_ct += 1
        _emit_prefilter_struct(
            index=index_symbol,
            expiry='-',  # filled later by caller with actual expiry string if needed
            rule='-',
            total_raw=raw_total_opts,
            prefiltered=len(filtered),
            option_candidates=raw_total_opts,
            ce=ce_ct,
            pe=pe_ct,
            rejects={'prefilter_rejected': rejected if used else 0},
            latency_ms=(time.time()-start_ts)*1000.0,
            contamination=None,
            contamination_samples=None,
        )
    except Exception:
        pass
    # Centralized trace emission
    try:
        from src.broker.kite.tracing import trace
        if callable(trace):
            trace(
                "instrument_prefilter",
                index=index_symbol,
                universe=len(instruments),
                raw_opts=raw_total_opts,
                kept=(kept if used else len(filtered)),
                rejected=(rejected if used else 0),
                used=used,
            )
    except Exception:
        pass
    else:
        logger.debug(
            "PREFILTER idx=%s raw_opts=%d kept=%d rejected=%d used=%s",
            index_symbol, raw_total_opts,
            len(filtered),
            (raw_total_opts - len(filtered)) if used else 0,
            used,
        )
    return filtered, used, {'prefilter_rejected': rejected if used else 0}

# ---------------------------------------------------------------------------
# Strike membership wrapper – we delegate heavy lifting to existing helper
# ---------------------------------------------------------------------------
class StrikeMembership:
    def __init__(self, strikes: Sequence[float]):
        from src.utils.strike_index import build_strike_index  # local import
        self._idx = build_strike_index(list(strikes))
        self.sorted: Sequence[float] = self._idx.sorted
    def contains(self, v: float) -> bool:  # passthrough
        return self._idx.contains(v)

# ---------------------------------------------------------------------------
# Pre-index build for fast candidate lookups
# ---------------------------------------------------------------------------
def build_preindex(instruments: Sequence[Instrument], strike_membership: StrikeMembership) -> dict[tuple[_dt.date, float, str], list[Instrument]]:
    pre_index: dict[tuple[_dt.date, float, str], list[Instrument]] = {}
    def _norm_exp(exp_val: Any) -> _dt.date | None:
        try:
            if exp_val is None:
                return None
            if isinstance(exp_val, _dt.datetime):
                return exp_val.date()
            if isinstance(exp_val, _dt.date):
                return exp_val
            s = str(exp_val).strip()
            if not s:
                return None
            try:
                return _dt.datetime.strptime(s[:10], '%Y-%m-%d').date()
            except Exception:
                pass
            for fmt in ('%d-%b-%Y','%d-%m-%Y','%Y/%m/%d','%d/%m/%Y'):
                try:
                    return _dt.datetime.strptime(s, fmt).date()
                except Exception:
                    continue
        except Exception:
            return None
        return None
    try:
        for inst in instruments:
            it = (inst.get('instrument_type') or '').upper()
            if it not in ('CE','PE'):
                continue
            exp_norm = _norm_exp(inst.get('expiry'))
            if not exp_norm:
                continue
            try:
                sv = float(inst.get('strike',0) or 0)
            except Exception:
                continue
            rsv = round(sv,2)
            if not strike_membership.contains(rsv):
                continue
            k = (exp_norm, rsv, it)
            bucket = pre_index.get(k)
            if bucket is None:
                pre_index[k] = [inst]
            else:
                bucket.append(inst)
    except Exception:
        logger.debug("Pre-index build failed", exc_info=True)
    return pre_index

# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------
@dataclass
class MatchResult:
    instruments: list[Instrument]
    reject_counts: dict[str, int]
    contamination_list: list[str]


def match_options(provider: ProviderLike | Any, index_symbol: str, expiry_target: _dt.date, strikes: Sequence[float], instruments: Sequence[Instrument], pre_index: Mapping[tuple[_dt.date, float, str], Sequence[Instrument]], strike_membership: StrikeMembership) -> MatchResult:
    from src.filters.option_filter import OptionFilterContext, accept_option
    from src.runtime.runtime_flags import get_flags
    from src.utils.symbol_root import detect_root  # for root cache fallback
    try:
        from src.utils.root_cache import cached_detect_root
    except Exception:  # pragma: no cover
        def cached_detect_root(s: str):  # type: ignore[redefined-outer-name]
            try:
                return detect_root(s)
            except Exception:
                return None

    flags = get_flags()
    match_mode = flags.match_mode
    safe_mode = flags.safe_mode
    underlying_strict = flags.underlying_strict

    # Pre-index already built; construct filter context
    strike_key_set = {round(float(s), 2) for s in strike_membership.sorted}
    filter_ctx = OptionFilterContext(
        index_symbol=index_symbol,
        expiry_target=expiry_target,
        strike_key_set=strike_key_set,
        match_mode=match_mode,
        underlying_strict=underlying_strict,
        safe_mode=safe_mode,
    )

    _root_cache: dict[str,str] = {}
    def _get_root_cached(ts: str) -> str:
        v = _root_cache.get(ts)
        if v is not None: return v
        try:
            v = cached_detect_root(ts) or ''
        except Exception:
            v = ''
        _root_cache[ts] = v
        return v

    # Candidate selection using preindex
    candidate_set: list[Instrument] = []
    try:
        for s in strike_membership.sorted:
            rs = round(float(s),2)
            for t in ('CE','PE'):
                bucket = pre_index.get((expiry_target, rs, t))
                if bucket:
                    candidate_set.extend(bucket)
        if not candidate_set:
            candidate_set = [inst for inst in instruments if (inst.get('instrument_type') or '') in ('CE','PE')]
    except Exception:
        candidate_set = [inst for inst in instruments if (inst.get('instrument_type') or '') in ('CE','PE')]

    reject_counts = {k:0 for k in ('not_option_type','root_mismatch','expiry_mismatch','strike_mismatch','underlying_mismatch')}
    contamination_samples: list[str] = []
    matching: list[Instrument] = []

    for inst in candidate_set:
        ok, reason = accept_option(
            inst,
            filter_ctx,
            root_cache=_root_cache,
            expected_expiry=expiry_target,
            contamination_samples=contamination_samples,
        )
        if ok:
            matching.append(inst)
        else:
            if reason in reject_counts:
                reject_counts[reason] += 1

    return MatchResult(matching, reject_counts, contamination_samples)

# ---------------------------------------------------------------------------
# Expiry fallback strategies
# ---------------------------------------------------------------------------

def apply_expiry_fallbacks(provider: ProviderLike | Any, index_symbol: str, expiry_target: _dt.date, strikes: Sequence[float], instruments: Sequence[Instrument], strike_membership: StrikeMembership, existing_matches: list[Instrument]) -> list[Instrument]:
    if existing_matches:
        return existing_matches  # no need for fallbacks
    settings = getattr(provider, '_settings', None)
    from src.filters.option_filter import OptionFilterContext, accept_option
    from src.runtime.runtime_flags import get_flags
    flags = get_flags()
    match_mode = flags.match_mode
    safe_mode = flags.safe_mode
    underlying_strict = flags.underlying_strict
    strike_key_set = {round(float(s), 2) for s in strike_membership.sorted}
    filter_ctx = OptionFilterContext(
        index_symbol=index_symbol,
        expiry_target=expiry_target,
        strike_key_set=strike_key_set,
        match_mode=match_mode,
        underlying_strict=underlying_strict,
        safe_mode=safe_mode,
    )
    try:
        from src.utils.root_cache import cached_detect_root
    except Exception:
        from src.utils.symbol_root import detect_root as cached_detect_root

    # Build expiry meta map
    by_exp_meta: dict[_dt.date, dict[str, Any]] = {}
    def _norm_exp(ev):
        if isinstance(ev, _dt.datetime): return ev.date()
        if isinstance(ev, _dt.date): return ev
        try:
            return _dt.datetime.strptime(str(ev)[:10], '%Y-%m-%d').date()
        except Exception:
            return None
    for inst in instruments:
        if (inst.get('instrument_type') or '') not in ('CE','PE'): continue
        tsym = str(inst.get('tradingsymbol',''))
        try:
            root = cached_detect_root(tsym) or ''
        except Exception:
            root = ''
        if root != index_symbol.upper(): continue
        inst_exp = _norm_exp(inst.get('expiry'))
        if not inst_exp: continue
        try:
            stv = float(inst.get('strike',0) or 0)
        except Exception:
            continue
        rsv = round(stv,2)
        meta = by_exp_meta.get(inst_exp)
        if meta is None:
            meta = {'pool': [], 'strike_set': set()}
            by_exp_meta[inst_exp] = meta
        meta['pool'].append(inst)
        meta['strike_set'].add(rsv)

    matches: list[Instrument] = []
    # Forward fallback
    if settings and getattr(settings, 'enable_nearest_expiry_fallback', True):
        try:
            forward_candidates = sorted(e for e,m in by_exp_meta.items() if e >= expiry_target and (m.get('strike_set') or set()) & strike_key_set)
            chosen_forward: _dt.date | None = None
            for e in forward_candidates[:4]:
                chosen_forward = e
                break
            if chosen_forward and chosen_forward != expiry_target:
                logger.warning("NEAREST_EXPIRY_FALLBACK index=%s requested=%s using=%s", index_symbol, expiry_target, chosen_forward)
                pool = by_exp_meta.get(chosen_forward, {}).get('pool', [])
                for inst in pool:
                    try:
                        st = round(float(inst.get('strike',0) or 0),2)
                    except Exception:
                        continue
                    if st not in strike_key_set: continue
                    ok, _ = accept_option(inst, filter_ctx, root_cache={}, expected_expiry=chosen_forward, contamination_samples=[])
                    if ok:
                        matches.append(inst)
        except Exception:
            logger.debug("Nearest expiry fallback failed", exc_info=True)
    # Backward fallback
    if not matches and settings and getattr(settings, 'enable_backward_expiry_fallback', True):
        try:
            back_candidates = [e for e,m in by_exp_meta.items() if expiry_target > e and (expiry_target - e).days <= 3 and (m.get('strike_set') or set()) & strike_key_set]
            back_candidates.sort(reverse=True)
            chosen_back: _dt.date | None = None
            for e in back_candidates:
                chosen_back = e
                break
            if chosen_back:
                logger.warning("BACKWARD_EXPIRY_FALLBACK index=%s requested=%s using=%s", index_symbol, expiry_target, chosen_back)
                pool = by_exp_meta.get(chosen_back, {}).get('pool', [])
                for inst in pool:
                    try:
                        st = round(float(inst.get('strike',0) or 0),2)
                    except Exception:
                        continue
                    if st not in strike_key_set: continue
                    ok, _ = accept_option(inst, filter_ctx, root_cache={}, expected_expiry=chosen_back, contamination_samples=[])
                    if ok:
                        matches.append(inst)
        except Exception:
            logger.debug("Backward expiry fallback failed", exc_info=True)
    return matches

# ---------------------------------------------------------------------------
# Summary logging & cache population
# ---------------------------------------------------------------------------

def _log_summary(index_symbol: str, expiry_date: Any, strikes: Sequence[float], matching_instruments: Sequence[Instrument]) -> None:
    strikes_summary: dict[float, dict[str,int]] = {}
    for inst in matching_instruments:
        strike = float(inst.get('strike',0) or 0)
        it = inst.get('instrument_type','')
        if strike not in strikes_summary:
            strikes_summary[strike] = {'CE':0,'PE':0}
        if it in ('CE','PE'):
            strikes_summary[strike][it] += 1
    from src.runtime.runtime_flags import get_flags
    flags = get_flags()
    if is_concise_logging():
        total = len(matching_instruments)
        strike_keys = sorted(strikes_summary.keys())
        strike_count = len(strike_keys)
        ce_total = sum(v.get('CE',0) for v in strikes_summary.values())
        pe_total = sum(v.get('PE',0) for v in strikes_summary.values())
        cov_denom = strike_count if strike_count else 1
        cov_ce = ce_total / cov_denom if cov_denom else 0.0
        cov_pe = pe_total / cov_denom if cov_denom else 0.0
        strike_min = strike_max = 0
        step = 0
        if strike_count >= 2:
            strike_min = strike_keys[0]
            strike_max = strike_keys[-1]
            diffs = [b-a for a,b in zip(strike_keys, strike_keys[1:], strict=False) if b-a>0]
            step = min(diffs) if diffs else 0
        elif strike_count == 1:
            strike_min = strike_max = strike_keys[0]
        sample: list[str] = []
        if strike_keys:
            if strike_count <= 5:
                sample = [f"{s:.0f}" for s in strike_keys]
            else:
                sample = [
                    f"{strike_keys[0]:.0f}",
                    f"{strike_keys[1]:.0f}",
                    f"{strike_keys[strike_count//2]:.0f}",
                    f"{strike_keys[-2]:.0f}",
                    f"{strike_keys[-1]:.0f}",
                ]
        sample_str = ",".join(sample)
        _log_fn = logger.debug if is_concise_logging() else logger.info
        _log_fn(
            "OPTIONS idx=%s expiry=%s instruments=%d strikes=%d ce_total=%d pe_total=%d range=%s step=%s coverage=CE:%.2f,PE:%.2f sample=[%s]",
            index_symbol,
            expiry_date,
            total,
            strike_count,
            ce_total,
            pe_total,
            f"{int(strike_min)}-{int(strike_max)}" if strike_count else '-',
            int(step) if step else 0,
            cov_ce,
            cov_pe,
            sample_str,
        )
        if flags.trace_option_match:
            try:
                from src.broker.kite.tracing import rate_limited_trace
                sample_acc = [
                    {
                        'ts': inst.get('tradingsymbol'),
                        'exp': str(inst.get('expiry')),
                        'strike': inst.get('strike'),
                        'itype': inst.get('instrument_type'),
                    }
                    for inst in matching_instruments[:8]
                ]
                rate_limited_trace(
                    "option_match_sample",
                    index=index_symbol,
                    expiry=str(expiry_date),
                    sample=sample_acc,
                    count=len(matching_instruments),
                )
            except Exception:
                pass
    else:
        logger.info(f"+ Options for {index_symbol} (Expiry: {expiry_date}) " + "-" * 30)
        logger.info(f"| Found {len(matching_instruments)} matching instruments")
        if strikes_summary:
            logger.info("| Strike    CE  PE")
            logger.info("| " + "-" * 15)
            for strike in sorted(strikes_summary.keys()):
                ce_count = strikes_summary[strike]['CE']
                pe_count = strikes_summary[strike]['PE']
                logger.info(f"| {strike:<8.1f} {ce_count:>2}  {pe_count:>2}")
        logger.info("+" + "-" * 50)

# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------

def option_instruments(provider: ProviderLike | Any, index_symbol: str, expiry_date: Any, strikes: Iterable[float]) -> list[Instrument]:
    """Return option instruments for requested strikes and expiry.

    Mirrors the old KiteProvider.option_instruments method so that KiteProvider
    now simply delegates here. Provider must expose _settings and _state (with
    option_instrument_cache, option_cache_day, option_cache_hits/misses).
    """
    try:
        # Defensive bootstrap for settings/state (legacy test subclasses)
        if not hasattr(provider, '_settings'):
            from src.broker.kite.settings import load_settings  # lazy import
            try:
                provider._settings = load_settings()
            except Exception:
                class _Shim:  # pragma: no cover
                    trace_collector = False
                    enable_nearest_expiry_fallback = True
                    enable_backward_expiry_fallback = True
                provider._settings = _Shim()
        if not hasattr(provider, '_state'):
            from src.broker.kite.state import ProviderState  # lazy import
            try:
                provider._state = ProviderState()
            except Exception:
                class _StateShim:  # pragma: no cover
                    option_instrument_cache = {}
                    option_cache_day = _dt.date.today().isoformat()
                    option_cache_hits = 0
                    option_cache_misses = 0
                provider._state = _StateShim()
        state = provider._state
        today_iso = _dt.date.today().isoformat()
        if getattr(state, 'option_cache_day', today_iso) != today_iso:
            try:
                state.option_instrument_cache.clear()
                state.option_cache_day = today_iso
            except Exception:
                pass

        if hasattr(expiry_date, 'strftime'):
            expiry_iso = expiry_date.strftime('%Y-%m-%d')
        else:
            expiry_iso = str(expiry_date)

        strikes_list = list(strikes)
        cached_all: list[Instrument] = []
        cache_hit_complete = True
        for s in strikes_list:
            for opt_type in ('CE','PE'):
                key = (index_symbol, expiry_iso, float(s), opt_type)
                inst = getattr(state, 'option_instrument_cache', {}).get(key)
                if inst:
                    cached_all.append(inst)
                else:
                    cache_hit_complete = False
                    break
            if not cache_hit_complete:
                break
        if cache_hit_complete and cached_all:
            state.option_cache_hits += 1
            if is_concise_logging():
                logger.debug(f"Instrument cache HIT idx={index_symbol} expiry={expiry_iso} strikes={len(strikes_list)} size={len(cached_all)}")
            return cached_all
        else:
            state.option_cache_misses += 1
            if is_concise_logging() and (state.option_cache_misses % 50 == 1):
                logger.debug(f"Instrument cache MISS idx={index_symbol} expiry={expiry_iso} strikes={len(strikes_list)} (miss #{state.option_cache_misses})")

        # Universe fetch (prefer provider daily universe if attached)
        if hasattr(provider, '_daily_universe') and provider._daily_universe:
            universe = provider._daily_universe
        else:
            exchange_pool = 'NFO'
            universe = provider.get_instruments(exchange_pool)

        raw_total_opts = 0
        ce_ct = pe_ct = 0
        distinct_expiries = set()
        for inst in universe:
            ity = (inst.get('instrument_type') or '').upper()
            if ity in ('CE','PE') or ity in ('OPTIDX','OPTSTK','OPT'):
                raw_total_opts += 1
                tsymu = str(inst.get('tradingsymbol','')).upper()
                if ity not in ('CE','PE'):
                    if tsymu.endswith('CE'): ce_ct += 1
                    elif tsymu.endswith('PE'): pe_ct += 1
                else:
                    if ity == 'CE': ce_ct += 1
                    elif ity == 'PE': pe_ct += 1
                expv = inst.get('expiry')
                if expv:
                    try:
                        if hasattr(expv,'strftime'):
                            distinct_expiries.add(expv.strftime('%Y-%m-%d'))
                        else:
                            distinct_expiries.add(str(expv)[:10])
                    except Exception:
                        pass
        filtered, prefiltered_used, prefilter_rejects = prefilter_option_universe(index_symbol, universe, raw_total_opts)
        try:
            logger.debug(
                "option_universe_breakdown index=%s universe=%d raw_opts=%d ce=%d pe=%d distinct_expiries=%d",
                index_symbol, len(universe), raw_total_opts, ce_ct, pe_ct, len(distinct_expiries)
            )
        except Exception:
            pass

        # Normalize expiry target
        if hasattr(expiry_date, 'strftime'):
            expiry_obj = expiry_date
        else:
            try:
                expiry_obj = _dt.datetime.strptime(str(expiry_date), '%Y-%m-%d').date()
            except Exception:
                expiry_obj = _dt.date.today()
        if isinstance(expiry_obj, _dt.datetime):
            expiry_target = expiry_obj.date()
        elif isinstance(expiry_obj, _dt.date):
            expiry_target = expiry_obj
        else:
            try:
                expiry_target = _dt.datetime.strptime(str(expiry_obj), '%Y-%m-%d').date()
            except Exception:
                expiry_target = _dt.date.today()

        strike_membership = StrikeMembership(strikes_list)
        pre_index = build_preindex(filtered, strike_membership)
        # Expiry mismatch diagnostic: if target not in distinct_expiries (normalized)
        try:
            if hasattr(expiry_date,'strftime'):
                expiry_iso_norm = expiry_date.strftime('%Y-%m-%d')
            else:
                expiry_iso_norm = str(expiry_date)[:10]
            if distinct_expiries and expiry_iso_norm not in distinct_expiries:
                logger.warning(
                    "expiry_mismatch index=%s target=%s distinct_in_universe=%s",
                    index_symbol, expiry_iso_norm, sorted(list(distinct_expiries))[:8]
                )
        except Exception:
            logger.debug('expiry_mismatch_diag_failed', exc_info=True)

        match_res = match_options(provider, index_symbol, expiry_target, strikes_list, filtered, pre_index, strike_membership)
        matching = match_res.instruments

        # Fallbacks
        matching = apply_expiry_fallbacks(provider, index_symbol, expiry_target, strikes_list, filtered, strike_membership, matching)

        if not matching:
            try:
                logger.debug(
                    "option_match_empty_pre_relax index=%s expiry=%s strikes=%d filtered=%d prefilter_used=%s",
                    index_symbol, expiry_target, len(strikes_list), len(filtered), prefiltered_used
                )
            except Exception:
                pass

        # Relaxed recovery: if still empty but we have a filtered universe, attempt a permissive selection.
        # Goal: avoid full EMPTY expiry when underlying universe clearly contains option instruments.
        if not matching and filtered:
            from src.utils.env_flags import is_truthy_env  # type: ignore
            if is_truthy_env('G6_RELAX_EMPTY_MATCH') or 'G6_RELAX_EMPTY_MATCH' not in os.environ:
                try:
                    logger.warning(
                        "empty_option_match_relaxing index=%s expiry=%s filtered=%d strikes=%d",
                        index_symbol, expiry_target, len(filtered), len(strikes_list)
                    )
                    strikes_set = {float(s) for s in strikes_list}
                    # First pass: strict expiry + strike match
                    relaxed: list[Instrument] = []
                    def _norm_exp(ev):
                        import datetime as _dt
                        if isinstance(ev, _dt.datetime): return ev.date()
                        if isinstance(ev, _dt.date): return ev
                        try:
                            return _dt.datetime.strptime(str(ev)[:10], '%Y-%m-%d').date()
                        except Exception:
                            return None
                    for inst in filtered:
                        ity = (inst.get('instrument_type') or '').upper()
                        if ity not in ('CE','PE'): continue
                        try:
                            st = float(inst.get('strike') or 0)
                        except Exception:
                            continue
                        if st not in strikes_set: continue
                        expn = _norm_exp(inst.get('expiry'))
                        if expn and expn == expiry_target:
                            relaxed.append(inst)
                    # If still nothing, allow nearest expiry (forward) with strike match
                    if not relaxed:
                        # Build mapping of expiry -> candidates to pick nearest
                        by_exp: dict[Any, list[Instrument]] = {}
                        for inst in filtered:
                            ity = (inst.get('instrument_type') or '').upper()
                            if ity not in ('CE','PE'): continue
                            try:
                                st = float(inst.get('strike') or 0)
                            except Exception:
                                continue
                            if st not in strikes_set: continue
                            expn = _norm_exp(inst.get('expiry'))
                            if not expn: continue
                            by_exp.setdefault(expn, []).append(inst)
                        if by_exp:
                            forward = sorted(e for e in by_exp.keys() if e >= expiry_target)
                            chosen = forward[0] if forward else sorted(by_exp.keys())[0]
                            logger.warning(
                                "empty_option_match_relax_nearest_expiry index=%s requested=%s using=%s",
                                index_symbol, expiry_target, chosen
                            )
                            relaxed.extend(by_exp.get(chosen, []))
                    # Optional: de-duplicate by (strike, type)
                    if relaxed:
                        dedup: dict[tuple[float,str], Instrument] = {}
                        for inst in relaxed:
                            try:
                                st = float(inst.get('strike') or 0)
                            except Exception:
                                continue
                            ity = (inst.get('instrument_type') or '').upper()
                            if ity not in ('CE','PE'): continue
                            dedup[(st, ity)] = inst
                        matching = list(dedup.values())
                        logger.info(
                            "empty_option_match_relax_success index=%s expiry=%s recovered=%d",
                            index_symbol, expiry_target, len(matching)
                        )
                    else:
                        logger.debug(
                            "empty_option_match_relax_failed index=%s expiry=%s",
                            index_symbol, expiry_target
                        )
                        try:
                            logger.debug(
                                "option_match_remains_empty_after_relax index=%s expiry=%s filtered=%d strikes=%d",
                                index_symbol, expiry_target, len(filtered), len(strikes_list)
                            )
                        except Exception:
                            pass
                except Exception:
                    logger.debug("empty_option_match_relax_exception index=%s", index_symbol, exc_info=True)

        # TRACE / diagnostics parity (centralized tracing)
        try:
            from src.broker.kite.tracing import trace  # local import to keep cold path light
            if callable(trace):
                total_opts = sum(1 for inst in filtered if (inst.get('instrument_type') or '') in ('CE','PE'))
                # Build structured context; keep keys sorted-friendly
                contamination_flag = len(match_res.contamination_list) > 0
                trace(
                    "instrument_filter_summary",
                    index=index_symbol,
                    expiry=expiry_iso,
                    mode=getattr(match_res, 'match_mode', getattr(match_res, 'match_mode', '?')),
                    total_opts=total_opts,
                    accepted=len(matching),
                    rejects=match_res.reject_counts,
                    contamination=contamination_flag,
                    underlying_strict='unknown',  # parity placeholder
                    samples=match_res.contamination_list,
                    raw_total_opts=raw_total_opts,
                    prefilter_used=prefiltered_used,
                )
        except Exception:
            pass

        _log_summary(index_symbol, expiry_date, strikes_list, matching)

        # Populate cache
        try:
            for inst in matching:
                try:
                    strike_val = float(inst.get('strike') or 0)
                except Exception:
                    continue
                opt_type = inst.get('instrument_type') or ''
                if strike_val > 0 and opt_type in ('CE','PE'):
                    key = (index_symbol, expiry_iso, strike_val, opt_type)
                    if len(state.option_instrument_cache) > 50000:
                        state.option_instrument_cache.clear()
                    state.option_instrument_cache[key] = inst
        except Exception:
            pass
        return matching
    except Exception as e:  # broad fallback parity with old implementation
        logger.error(f"Failed to get option instruments: {e}", exc_info=True)
        try:
            from src.error_handling import handle_data_collection_error  # lazy import
            handle_data_collection_error(e, component="kite.options.option_instruments", index_name=index_symbol, data_type="option_instruments", context={"expiry": str(expiry_date)})
        except Exception:
            pass
        return []
