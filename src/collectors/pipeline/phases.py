from __future__ import annotations

from collections.abc import Callable, Iterable, MutableMapping, Sequence
from typing import Any, Protocol, cast

InstrumentRow = dict[str, Any]

import datetime
import logging

from src.collectors.errors import PhaseAbortError, PhaseRecoverableError
from src.utils.exceptions import NoInstrumentsError, NoQuotesError, ResolveExpiryError  # domain -> taxonomy mappings

from .error_helpers import add_phase_error
from .state import ExpiryState
from .struct_events import emit_struct_event

logger = logging.getLogger(__name__)

# Helper import indirections kept local to avoid heavy imports if shadow flag off



# Flexible instrument fetch protocol (accepts minor signature drift)
class _FetchInstrumentsLike(Protocol):  # pragma: no cover
    def __call__(self, index: str, rule: str, expiry: Any, strikes: Sequence[float] | Iterable[float], providers: Any, metrics: Any | None = ...) -> Any: ...

Variants = Sequence[tuple[Any, ...]]

def _try_call(fn: Callable[..., Any], variants: Variants) -> Any | None:
    """Attempt calling fn with each arg tuple in variants, returning first success.

    Designed to smooth over signature drift between legacy unified helpers and
    newer modular helpers without littering code with many nested try blocks.
    """
    for args in variants:
        try:  # noqa: PERF203 small loop, variants tiny (<=3)
            return fn(*args)
        except TypeError:
            continue
        except Exception:
            raise
    # Final attempt: call with first variant (will raise original error)
    try:
        return fn(*variants[0])
    except Exception:
        return None


def phase_resolve(ctx: Any, state: ExpiryState) -> ExpiryState:
    if state.expiry_date is not None:
        return state
    try:
        try:
            from src.collectors.modules.expiry_helpers import resolve_expiry as _resolve_expiry
            try:
                expiry_date = _resolve_expiry(state.index, state.rule, ctx.providers, None, True)
            except ResolveExpiryError as re_err:
                # Map domain resolve failure directly to taxonomy abort for observability
                raise PhaseAbortError(f'resolve_expiry:{re_err}') from re_err
            state.expiry_date = expiry_date
            if state.expiry_date is None:
                raise PhaseAbortError('expiry_unresolved')
        except PhaseAbortError:
            raise
        except Exception:
            from src.collectors.unified_collectors import _resolve_expiry
            strikes = getattr(ctx, 'precomputed_strikes', [])
            metrics = getattr(ctx, 'metrics', None)
            variants = [
                (state.index, state.rule, strikes, metrics, False),  # full (modern) expected
                (state.index, state.rule, strikes, metrics),         # without concise flag
                (state.index, state.rule, strikes),                  # legacy minimal
            ]
            resolved = _try_call(_resolve_expiry, variants)
            if isinstance(resolved, tuple) and resolved:
                state.expiry_date = resolved[0]
            elif isinstance(resolved, datetime.date):
                state.expiry_date = resolved
        if state.expiry_date is None:
            raise PhaseAbortError('expiry_unresolved')
    except PhaseAbortError as e:  # pragma: no cover - taxonomy-specific capture for in-phase reporting
        token = f"resolve_abort:{e}"
        add_phase_error(state, 'resolve', 'resolve_abort', str(e), token=token)
    except Exception as e:  # pragma: no cover - safety net
        token = f"resolve:{e}"
        add_phase_error(state, 'resolve', 'resolve', str(e), token=token)
    return state

def phase_fetch(ctx: Any, state: ExpiryState, precomputed_strikes: Sequence[float] | Iterable[float]) -> ExpiryState:
    if not precomputed_strikes:
        # Abort: nothing to fetch (upstream selection produced empty strikes)
        raise PhaseAbortError('no_strikes')
    state.strikes = list(precomputed_strikes)
    try:
        used_unified = False
        raw_instruments: Any = None
        try:
            # Use distinct local alias to avoid confusion with unified helper name
            from src.collectors.modules.expiry_helpers import fetch_option_instruments as _mod_fetch_option_instruments
            try:
                raw_instruments = _mod_fetch_option_instruments(
                    state.index, state.rule, state.expiry_date, state.strikes, ctx.providers, None
                )
            except NoInstrumentsError as nie:
                raise PhaseRecoverableError('no_instruments_domain') from nie
            if not raw_instruments:
                raise ValueError('modular_fetch_returned_empty')
        except PhaseRecoverableError:
            raise
        except Exception:
            from src.collectors.unified_collectors import _fetch_option_instruments
            variants = [
                (state.index, state.rule, state.expiry_date, state.strikes, ctx.providers, getattr(ctx, 'metrics', None)),
                (state.index, state.rule, state.expiry_date, state.strikes, ctx.providers),
            ]
            raw_instruments = _try_call(_fetch_option_instruments, variants)
            used_unified = True
        # Normalize shapes into list[InstrumentRow]
        norm: list[InstrumentRow] = []
        if isinstance(raw_instruments, list):
            norm = [r for r in raw_instruments if isinstance(r, dict)]
        elif isinstance(raw_instruments, dict):
            try:
                norm = [v for v in raw_instruments.values() if isinstance(v, dict)]
            except Exception:
                norm = []
        state.instruments = norm
        if not state.instruments and not used_unified:
            # One more attempt with unified helpers if modular path yielded empty safely
            try:  # pragma: no cover - defensive
                from src.collectors.unified_collectors import _fetch_option_instruments as _f2
                variants2 = [
                    (state.index, state.rule, state.expiry_date, state.strikes, ctx.providers, getattr(ctx,'metrics', None)),
                    (state.index, state.rule, state.expiry_date, state.strikes, ctx.providers),
                ]
                raw2 = _try_call(_f2, variants2)
                norm2: list[InstrumentRow] = []
                if isinstance(raw2, list):
                    norm2 = [r for r in raw2 if isinstance(r, dict)]
                elif isinstance(raw2, dict):
                    try:
                        norm2 = [v for v in raw2.values() if isinstance(v, dict)]
                    except Exception:
                        norm2 = []
                state.instruments = norm2
            except Exception:
                pass
        if not state.instruments:
            # Recoverable: treat as transient (could be provider outage or data delay)
            raise PhaseRecoverableError('no_instruments')
    except PhaseRecoverableError as e:
        token = f"fetch_recoverable:{e}"
        add_phase_error(state, 'fetch', 'fetch_recoverable', str(e), token=token)
    except PhaseAbortError as e:
        token = f"fetch_abort:{e}"
        add_phase_error(state, 'fetch', 'fetch_abort', str(e), token=token)
    except Exception as e:  # pragma: no cover
        token = f"fetch:{e}"
        add_phase_error(state, 'fetch', 'fetch', str(e), token=token)
    return state

def phase_prefilter(ctx: Any, state: ExpiryState) -> ExpiryState:
    if not state.instruments:
        return state
    try:
        from src.collectors.modules.prefilter_flow import run_prefilter_clamp
        inst, clamp_meta = run_prefilter_clamp(state.index, state.rule, state.expiry_date, state.instruments)
        state.instruments = inst or []
        if clamp_meta:
            state.meta['prefilter_clamp'] = {
                'orig': clamp_meta[0],
                'dropped': clamp_meta[1],
                'max_allowed': clamp_meta[2],
                'strict': clamp_meta[3],
            }
    except Exception as e:  # pragma: no cover
        token = f"prefilter:{e}"
        add_phase_error(state, 'prefilter', 'prefilter', str(e), token=token)
    return state

def phase_enrich(ctx: Any, state: ExpiryState) -> ExpiryState:
    if not state.instruments:
        return state
    try:
        used_unified = False
        enriched: Any = None
        try:
            from src.collectors.modules.expiry_helpers import enrich_quotes as _enrich_quotes
            try:
                try:
                    enriched = _enrich_quotes(state.index, state.rule, state.expiry_date, state.instruments, ctx.providers, getattr(ctx, 'metrics', None))
                except NoQuotesError as nq:
                    raise PhaseRecoverableError('enrich_no_quotes_domain') from nq
                except Exception:
                    enriched = _enrich_quotes(state.index, state.rule, state.expiry_date, state.instruments, ctx.providers, None)
            except NoQuotesError as nq:  # fallback if second call raised domain error
                raise PhaseRecoverableError('enrich_no_quotes_domain') from nq
            if not enriched:
                raise ValueError('modular_enrich_empty')
        except PhaseRecoverableError:
            raise
        except Exception:
            from src.collectors.unified_collectors import _enrich_quotes
            variants = [
                (state.index, state.rule, state.expiry_date, state.instruments, ctx.providers, getattr(ctx,'metrics', None)),
                (state.index, state.rule, state.expiry_date, state.instruments, ctx.providers, None),
                (state.index, state.rule, state.expiry_date, state.instruments, ctx.providers),
            ]
            enriched = _try_call(_enrich_quotes, variants)
            used_unified = True
        # Normalize enriched shapes
        if isinstance(enriched, dict):
            state.enriched = {str(k): v for k, v in enriched.items() if isinstance(v, dict)}
        elif isinstance(enriched, list):
            state.enriched = {str(i.get('symbol') or i.get('tradingsymbol') or idx): i for idx, i in enumerate(enriched) if isinstance(i, dict)}
        else:
            state.enriched = {}
        if not state.enriched and not used_unified:
            try:  # pragma: no cover - defensive
                from src.collectors.unified_collectors import _enrich_quotes
                enriched2 = _enrich_quotes(state.index, state.rule, state.expiry_date, state.instruments, ctx.providers, None)
                if isinstance(enriched2, dict) and enriched2:
                    state.enriched = {str(k): v for k, v in enriched2.items() if isinstance(v, dict)}
            except Exception:
                pass
        if not state.enriched:
            raise PhaseRecoverableError('enrich_empty')
    except PhaseRecoverableError as e:  # pragma: no cover
        token = f"enrich_recoverable:{e}"
        add_phase_error(state, 'enrich', 'enrich_recoverable', str(e), token=token)
    except Exception as e:  # pragma: no cover
        token = f"enrich:{e}"
        add_phase_error(state, 'enrich', 'enrich', str(e), token=token)
    return state

def phase_preventive_validate(ctx: Any, state: ExpiryState) -> ExpiryState:
    """Mirror preventive validation step to observe potential drops.

    Swallows errors; records meta counts similar to legacy preventive_validate block.
    """
    # Run even if enriched empty to surface preventive_report meta for observability
    try:  # pragma: no cover - defensive
        from src.collectors.modules.preventive_validate import run_preventive_validation
        cleaned, report = run_preventive_validation(state.index, state.rule, state.expiry_date, state.instruments, state.enriched, None)
        if isinstance(cleaned, dict):
            state.enriched = cleaned
        if isinstance(report, dict):
            state.meta['preventive_report'] = {
                'dropped': report.get('dropped_count'),
                'kept': report.get('post_enriched_count'),
                'issues': report.get('issues'),
                'ok': report.get('ok', True),
            }
    except Exception as e:
        token = f"preventive:{e}"
        add_phase_error(state, 'preventive_validate', 'preventive', str(e), token=token)
    return state

def phase_salvage(ctx: Any, state: ExpiryState) -> ExpiryState:
    """Attempt foreign expiry salvage mimic (structural only) to gauge impact.

    Applies only if enriched empty, preventive report indicates foreign_expiry issues, and settings allow salvage.
    """
    if state.enriched:
        return state
    try:
        salvage_enabled = bool(getattr(state.settings, 'foreign_expiry_salvage', False) or getattr(state.settings, 'salvage_enabled', False))
        report = state.meta.get('preventive_report') or {}
        issues = report.get('issues') or []
        if not issues or not any(i=='foreign_expiry' for i in issues):
            return state
        if not all(i in ('foreign_expiry','insufficient_strike_coverage') for i in issues):
            return state
        if not salvage_enabled:
            # Observability mode: rehydrate original snapshot for parity without marking salvage_applied
            if state.meta.get('orig_enriched_snapshot'):
                snapshot = state.meta.get('orig_enriched_snapshot')
                if isinstance(snapshot, dict):
                    state.enriched = snapshot
            return state
        # Distinct expiry detection: reuse logic simplified (assume instruments contain 'expiry')
        distinct = set()
        for _sym, row in list((state.meta.get('orig_enriched_snapshot') or {}).items()):
            if not isinstance(row, dict):
                continue
            exp = row.get('expiry') or row.get('expiry_date') or row.get('instrument_expiry')
            if exp:
                distinct.add(str(exp))
        if len(distinct) == 1 and state.meta.get('orig_enriched_snapshot'):
            # salvage by reusing snapshot (structural parity only)
            snap2 = state.meta.get('orig_enriched_snapshot')
            if isinstance(snap2, dict):
                state.enriched = snap2
            state.meta['salvage_applied'] = True
    except Exception as e:  # pragma: no cover
        token = f"salvage:{e}"
        add_phase_error(state, 'salvage', 'salvage', str(e), token=token)
    return state


# ---------------- Phase 3 shadow extensions (read-only observational) -----------------

def phase_coverage(ctx: Any, state: ExpiryState) -> ExpiryState:
    """Capture strike & field coverage metrics without mutating legacy path.

    Stores state.meta['coverage'] = {'strike': <float|None>, 'field': <float|None>}.
    """
    if not state.enriched:
        # Ensure meta key present for observability even when earlier phases produced no data
        state.meta.setdefault('coverage', {'strike': None, 'field': None})
        return state
    try:
        # Support multiple naming conventions to keep test stubs light:
        # Preferred pair: coverage_metrics, field_coverage_metrics
        # Fallback single: compute_coverage(enriched) returning dict or tuple
        strike_cov = field_cov = None
        from src.collectors.modules.coverage_eval import coverage_metrics as _cov
        from src.collectors.modules.coverage_eval import field_coverage_metrics as _f_cov
        try:
            strike_cov = _cov(ctx, state.instruments, state.strikes, state.index, state.rule, state.expiry_date)
        except Exception:
            strike_cov = None
        try:
            field_cov = _f_cov(ctx, state.enriched, state.index, state.rule, state.expiry_date)
        except Exception:
            field_cov = None
        state.meta['coverage'] = {'strike': strike_cov, 'field': field_cov}
    except Exception as e:  # pragma: no cover
        token = f"coverage:{e}"
        add_phase_error(state, 'coverage', 'coverage', str(e), token=token)
    return state

def phase_iv(ctx: Any, state: ExpiryState) -> ExpiryState:
    """Attempt IV estimation observationally. Does not modify quotes.

    Records meta['iv_phase'] with attempted flag and optional error.
    """
    if not state.enriched:
        # Observability placeholder
        state.meta.setdefault('iv_phase', {'attempted': False, 'skipped': True})
        try:
            emit_struct_event(
                'expiry.phase.event',
                {
                    'phase': 'iv',
                    'outcome': 'skipped',
                    'attempt': 1,
                    'index': getattr(state,'index','?'),
                    'rule': getattr(state,'rule','?'),
                    'errors': len(getattr(state,'errors',[]) or []),
                    'enriched': 0,
                },
                state=state,
            )
        except Exception:
            pass
        return state
    meta: dict[str, Any] = {'attempted': False}
    try:
        from src.collectors.modules.iv_estimation import run_iv_estimation  # pragma: no cover - optional dependency
        meta['attempted'] = True
        try:
            run_iv_estimation(
                ctx,
                cast(dict[str, MutableMapping[str, Any]], state.enriched),
                state.index,
                state.rule,
                state.expiry_date,
                0.0,
                None,
                False,
                False,
                False,
                False,
                None,
                None,
            )
            meta['ok'] = True
        except Exception as inner:  # pragma: no cover
            meta.update({'ok': False, 'error': str(inner)})
    except Exception as e:  # pragma: no cover
        meta.update({'import_error': str(e)})
    state.meta['iv_phase'] = meta
    # Structured event
    try:
        emit_struct_event(
            'expiry.phase.event',
            {
                'phase': 'iv',
                'outcome': 'ok' if meta.get('ok') else ('error' if meta.get('attempted') else 'skipped'),
                'attempt': 1,
                'index': getattr(state,'index','?'),
                'rule': getattr(state,'rule','?'),
                'errors': len(getattr(state,'errors',[]) or []),
                'enriched': len(getattr(state,'enriched',{}) or {}),
            },
            state=state,
        )
    except Exception:
        pass
    return state

def phase_greeks(ctx: Any, state: ExpiryState) -> ExpiryState:
    """Attempt greeks computation observationally (no persistence coupling)."""
    if not state.enriched:
        state.meta.setdefault('greeks_phase', {'attempted': False, 'skipped': True})
        try:
            emit_struct_event(
                'expiry.phase.event',
                {
                    'phase': 'greeks',
                    'outcome': 'skipped',
                    'attempt': 1,
                    'index': getattr(state,'index','?'),
                    'rule': getattr(state,'rule','?'),
                    'errors': len(getattr(state,'errors',[]) or []),
                    'enriched': 0,
                },
                state=state,
            )
        except Exception:
            pass
        return state
    meta: dict[str, Any] = {'attempted': False}
    try:
        from src.collectors.modules.greeks_compute import run_greeks_compute  # pragma: no cover - optional dependency
        meta['attempted'] = True
        try:
            run_greeks_compute(
                ctx,
                cast(dict[str, MutableMapping[str, Any]], state.enriched),
                state.index,
                state.rule,
                state.expiry_date,
                None,
                None,
                0.0,
                False,
                False,
                None,
                None,
                None,
            )
            meta['ok'] = True
        except Exception as inner:  # pragma: no cover
            meta.update({'ok': False, 'error': str(inner)})
    except Exception as e:  # pragma: no cover
        meta.update({'import_error': str(e)})
    state.meta['greeks_phase'] = meta
    try:
        emit_struct_event(
            'expiry.phase.event',
            {
                'phase': 'greeks',
                'outcome': 'ok' if meta.get('ok') else ('error' if meta.get('attempted') else 'skipped'),
                'attempt': 1,
                'index': getattr(state,'index','?'),
                'rule': getattr(state,'rule','?'),
                'errors': len(getattr(state,'errors',[]) or []),
                'enriched': len(getattr(state,'enriched',{}) or {}),
            },
            state=state,
        )
    except Exception:
        pass
    return state

def phase_persist_sim(ctx: Any, state: ExpiryState) -> ExpiryState:
    """Simulate a persist outcome (option count + naive PCR) for parity hashing.

    PCR approximation: (# put legs)/(# call legs) if both >0 else None.
    Stores meta['persist_sim'].
    """
    if not state.enriched:
        state.meta['persist_sim'] = {'option_count': 0, 'simulated': True}
        try:
            emit_struct_event(
                'expiry.phase.event',
                {
                    'phase': 'persist_sim',
                    'outcome': 'skipped',
                    'attempt': 1,
                    'index': getattr(state,'index','?'),
                    'rule': getattr(state,'rule','?'),
                    'errors': len(getattr(state,'errors',[]) or []),
                    'enriched': 0,
                },
                state=state,
            )
        except Exception:
            pass
        return state
    try:
        puts = calls = 0
        for _sym, row in state.enriched.items():
            t = (row.get('instrument_type') or row.get('type') or '').upper()
            if t == 'PE':
                puts += 1
            elif t == 'CE':
                calls += 1
        pcr = None
        if calls > 0 and puts > 0:
            try:
                pcr = round(puts / calls, 4)
            except Exception:
                pcr = None
        state.meta['persist_sim'] = {
            'option_count': len(state.enriched),
            'puts': puts,
            'calls': calls,
            'pcr': pcr,
            'simulated': True,
        }
        try:
            emit_struct_event(
                'expiry.phase.event',
                {
                    'phase': 'persist_sim',
                    'outcome': 'ok',
                    'attempt': 1,
                    'index': getattr(state,'index','?'),
                    'rule': getattr(state,'rule','?'),
                    'errors': len(getattr(state,'errors',[]) or []),
                    'enriched': len(getattr(state,'enriched',{}) or {}),
                },
                state=state,
            )
        except Exception:
            pass
    except Exception as e:  # pragma: no cover
        token = f"persist_sim:{e}"
        add_phase_error(state, 'persist_sim', 'persist_sim', str(e), token=token)
        try:
            emit_struct_event(
                'expiry.phase.event',
                {
                    'phase': 'persist_sim',
                    'outcome': 'error',
                    'attempt': 1,
                    'index': getattr(state,'index','?'),
                    'rule': getattr(state,'rule','?'),
                    'errors': len(getattr(state,'errors',[]) or []),
                    'enriched': len(getattr(state,'enriched',{}) or {}),
                },
                state=state,
            )
        except Exception:
            pass
    return state

__all__ = [
    'phase_resolve', 'phase_fetch', 'phase_prefilter', 'phase_enrich',
    'phase_preventive_validate', 'phase_salvage',
    'phase_coverage','phase_iv','phase_greeks','phase_persist_sim'
]
