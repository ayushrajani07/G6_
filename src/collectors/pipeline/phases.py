from __future__ import annotations
from typing import Any
import logging, datetime, inspect
from .state import ExpiryState
from .error_helpers import add_phase_error
from src.collectors.errors import PhaseRecoverableError, PhaseAbortError, PhaseFatalError  # type: ignore
from src.utils.exceptions import ResolveExpiryError, NoInstrumentsError, NoQuotesError  # domain -> taxonomy mappings

logger = logging.getLogger(__name__)

# Helper import indirections kept local to avoid heavy imports if shadow flag off

def _try_call(fn, variants):
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


def phase_resolve(ctx, state: ExpiryState):
    if state.expiry_date is not None:
        return state
    try:
        try:
            from src.collectors.modules.expiry_helpers import resolve_expiry as _resolve_expiry  # type: ignore
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
            from src.collectors.unified_collectors import _resolve_expiry  # type: ignore
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

def phase_fetch(ctx, state: ExpiryState, precomputed_strikes):
    if not precomputed_strikes:
        # Abort: nothing to fetch (upstream selection produced empty strikes)
        raise PhaseAbortError('no_strikes')
    state.strikes = list(precomputed_strikes)
    try:
        used_unified = False
        try:
            from src.collectors.modules.expiry_helpers import fetch_option_instruments as _fetch_option_instruments  # type: ignore
            try:
                instruments = _fetch_option_instruments(state.index, state.rule, state.expiry_date, state.strikes, ctx.providers, None)
            except NoInstrumentsError as nie:
                # Explicit domain mapping: recoverable (provider likely transient or data gap)
                raise PhaseRecoverableError('no_instruments_domain') from nie
            if not instruments:
                raise ValueError('modular_fetch_returned_empty')
        except PhaseRecoverableError:
            raise
        except Exception:
            from src.collectors.unified_collectors import _fetch_option_instruments  # type: ignore
            variants = [
                (state.index, state.rule, state.expiry_date, state.strikes, ctx.providers, getattr(ctx, 'metrics', None)),
                (state.index, state.rule, state.expiry_date, state.strikes, ctx.providers),
            ]
            instruments = _try_call(_fetch_option_instruments, variants)
            used_unified = True
        state.instruments = instruments or []
        if not state.instruments and not used_unified:
            # One more attempt with unified helpers if modular path yielded empty safely
            try:  # pragma: no cover - defensive
                from src.collectors.unified_collectors import _fetch_option_instruments as _f2  # type: ignore
                variants2 = [
                    (state.index, state.rule, state.expiry_date, state.strikes, ctx.providers, getattr(ctx,'metrics', None)),
                    (state.index, state.rule, state.expiry_date, state.strikes, ctx.providers),
                ]
                instruments = _try_call(_f2, variants2)
                state.instruments = instruments or []
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

def phase_prefilter(ctx, state: ExpiryState):
    if not state.instruments:
        return state
    try:
        from src.collectors.modules.prefilter_flow import run_prefilter_clamp  # type: ignore
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

def phase_enrich(ctx, state: ExpiryState):
    if not state.instruments:
        return state
    try:
        used_unified = False
        try:
            from src.collectors.modules.expiry_helpers import enrich_quotes as _enrich_quotes  # type: ignore
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
            from src.collectors.unified_collectors import _enrich_quotes  # type: ignore
            variants = [
                (state.index, state.rule, state.expiry_date, state.instruments, ctx.providers, getattr(ctx,'metrics', None)),
                (state.index, state.rule, state.expiry_date, state.instruments, ctx.providers, None),
                (state.index, state.rule, state.expiry_date, state.instruments, ctx.providers),
            ]
            enriched = _try_call(_enrich_quotes, variants)
            used_unified = True
        if isinstance(enriched, dict):
            # Normalize key->dict shape
            state.enriched = {str(k): v for k, v in enriched.items() if isinstance(v, dict)}
        elif isinstance(enriched, list):
            state.enriched = {str(i.get('symbol') or i.get('tradingsymbol') or idx): i for idx,i in enumerate(enriched) if isinstance(i, dict)}  # type: ignore
        else:
            state.enriched = {}
        if not state.enriched and not used_unified:
            # final attempt with unified helper if modular returned empty without raising
            try:  # pragma: no cover - defensive
                from src.collectors.unified_collectors import _enrich_quotes  # type: ignore
                enriched2 = _enrich_quotes(state.index, state.rule, state.expiry_date, state.instruments, ctx.providers, None)
                if isinstance(enriched2, dict) and enriched2:
                    state.enriched = {str(k): v for k,v in enriched2.items() if isinstance(v, dict)}
            except Exception:
                pass
        if not state.enriched:
            # Recoverable: could be transient quote fetch issue
            raise PhaseRecoverableError('enrich_empty')
    except PhaseRecoverableError as e:  # pragma: no cover
        token = f"enrich_recoverable:{e}"
        add_phase_error(state, 'enrich', 'enrich_recoverable', str(e), token=token)
    except Exception as e:  # pragma: no cover
        token = f"enrich:{e}"
        add_phase_error(state, 'enrich', 'enrich', str(e), token=token)
    return state

def phase_preventive_validate(ctx, state: ExpiryState):
    """Mirror preventive validation step to observe potential drops.

    Swallows errors; records meta counts similar to legacy preventive_validate block.
    """
    # Run even if enriched empty to surface preventive_report meta for observability
    try:  # pragma: no cover - defensive
        from src.collectors.modules.preventive_validate import run_preventive_validation  # type: ignore
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

def phase_salvage(ctx, state: ExpiryState):
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
                state.enriched = state.meta['orig_enriched_snapshot']  # type: ignore
            return state
        # Distinct expiry detection: reuse logic simplified (assume instruments contain 'expiry')
        distinct = set()
        for sym, row in list(state.meta.get('orig_enriched_snapshot', {}).items()):  # type: ignore
            exp = row.get('expiry') or row.get('expiry_date') or row.get('instrument_expiry')
            if exp:
                distinct.add(str(exp))
        if len(distinct) == 1 and state.meta.get('orig_enriched_snapshot'):
            # salvage by reusing snapshot (structural parity only)
            state.enriched = state.meta['orig_enriched_snapshot']  # type: ignore
            state.meta['salvage_applied'] = True
    except Exception as e:  # pragma: no cover
        token = f"salvage:{e}"
        add_phase_error(state, 'salvage', 'salvage', str(e), token=token)
    return state


# ---------------- Phase 3 shadow extensions (read-only observational) -----------------

def phase_coverage(ctx, state: ExpiryState):
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
        try:
            from src.collectors.modules.coverage_eval import coverage_metrics as _cov, field_coverage_metrics as _f_cov  # type: ignore
            strike_cov = _cov(ctx, state.instruments, state.strikes, state.index, state.rule, state.expiry_date)
            field_cov = _f_cov(ctx, state.enriched, state.index, state.rule, state.expiry_date)
        except Exception:
            try:
                from src.collectors.modules.coverage_eval import compute_coverage as _compute  # type: ignore
                res = _compute(state.enriched)
                if isinstance(res, dict):
                    strike_cov = res.get('strike') or res.get('strike_cov') or res.get('s')
                    field_cov = res.get('field') or res.get('field_cov') or res.get('f')
                elif isinstance(res, tuple) and len(res) >= 2:
                    strike_cov, field_cov = res[0], res[1]
            except Exception as inner:  # pragma: no cover
                raise inner
        state.meta['coverage'] = {'strike': strike_cov, 'field': field_cov}
    except Exception as e:  # pragma: no cover
        token = f"coverage:{e}"
        add_phase_error(state, 'coverage', 'coverage', str(e), token=token)
    return state

def phase_iv(ctx, state: ExpiryState):
    """Attempt IV estimation observationally. Does not modify quotes.

    Records meta['iv_phase'] with attempted flag and optional error.
    """
    if not state.enriched:
        # Observability placeholder
        state.meta.setdefault('iv_phase', {'attempted': False, 'skipped': True})
        return state
    meta: dict[str, Any] = {'attempted': False}
    try:
        from src.collectors.modules.iv_estimation import run_iv_estimation  # type: ignore
        meta['attempted'] = True
        try:
            # Pass explicit booleans / placeholders where required; tolerate signature drift
            run_iv_estimation(ctx, state.enriched, state.index, state.rule, state.expiry_date, 0.0, None, False, False, False, False, None, None)  # type: ignore[arg-type]
            meta['ok'] = True
        except Exception as inner:  # pragma: no cover
            meta.update({'ok': False, 'error': str(inner)})
    except Exception as e:  # pragma: no cover
        meta.update({'import_error': str(e)})
    state.meta['iv_phase'] = meta
    return state

def phase_greeks(ctx, state: ExpiryState):
    """Attempt greeks computation observationally (no persistence coupling)."""
    if not state.enriched:
        state.meta.setdefault('greeks_phase', {'attempted': False, 'skipped': True})
        return state
    meta: dict[str, Any] = {'attempted': False}
    try:
        from src.collectors.modules.greeks_compute import run_greeks_compute  # type: ignore
        meta['attempted'] = True
        try:
            run_greeks_compute(ctx, state.enriched, state.index, state.rule, state.expiry_date, None, None, 0.0, False, False, None, None)  # type: ignore[arg-type]
            meta['ok'] = True
        except Exception as inner:  # pragma: no cover
            meta.update({'ok': False, 'error': str(inner)})
    except Exception as e:  # pragma: no cover
        meta.update({'import_error': str(e)})
    state.meta['greeks_phase'] = meta
    return state

def phase_persist_sim(ctx, state: ExpiryState):
    """Simulate a persist outcome (option count + naive PCR) for parity hashing.

    PCR approximation: (# put legs)/(# call legs) if both >0 else None.
    Stores meta['persist_sim'].
    """
    if not state.enriched:
        state.meta['persist_sim'] = {'option_count': 0, 'simulated': True}
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
    except Exception as e:  # pragma: no cover
        token = f"persist_sim:{e}"
        add_phase_error(state, 'persist_sim', 'persist_sim', str(e), token=token)
    return state

__all__ = [
    'phase_resolve', 'phase_fetch', 'phase_prefilter', 'phase_enrich',
    'phase_preventive_validate', 'phase_salvage',
    'phase_coverage','phase_iv','phase_greeks','phase_persist_sim'
]
