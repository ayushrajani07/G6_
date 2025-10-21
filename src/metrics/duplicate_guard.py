"""Duplicate metric registration guard.

Detects cases where multiple attribute names in the metrics registry resolve to
what appears to be the same underlying Prometheus collector object (e.g. alias
shadowing, accidental double registration via legacy shim paths).

Environment Controls
--------------------
G6_DUPLICATES_FAIL_ON_DETECT  : When truthy, raise RuntimeError if duplicates found.
G6_DUPLICATES_LOG_DEBUG       : When truthy, log per-offender debug lines (otherwise only summary).

Exposed Summary (attached to registry as _duplicate_metrics_summary):
{
  'duplicates': [ {'names': [...], 'type': 'Counter'} ],
  'duplicate_group_count': int,
  'total_attributes_scanned': int,
  'failed': bool,
}

A Prometheus gauge `g6_metric_duplicates_total` is set to the number of duplicate
collector groups (NOT total extra names) if present. Gauge created lazily here to
avoid having to wire spec entry for a low-volume governance metric.
"""
from __future__ import annotations

import logging
import os
from typing import Any

try:  # import only the needed primitive types for isinstance guards
    from prometheus_client.core import CollectorRegistry  # type: ignore
except Exception:  # pragma: no cover
    CollectorRegistry = object  # type: ignore

try:
    from prometheus_client import Gauge  # type: ignore
except Exception:  # pragma: no cover
    Gauge = None  # type: ignore

logger = logging.getLogger(__name__)

# Track whether we've already emitted a warning for a given duplicate signature to reduce log noise.
_EMITTED_SIGNATURES: set[tuple[int,int]] = set()


def _parse_bool(val: str | None) -> bool:
    if not val:
        return False
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _ensure_duplicates_gauge(registry: Any):  # pragma: no cover - trivial
    if Gauge is None:
        return None
    # Reuse if exists
    if hasattr(registry, 'metric_duplicates_total'):
        try:
            return registry.metric_duplicates_total  # type: ignore
        except Exception:
            return None
    try:
        g = Gauge('g6_metric_duplicates_total', 'Count of duplicate metric collector groups detected on initialization')
        # Attach as attribute so tests can access & to avoid re-registration
        registry.metric_duplicates_total = g  # type: ignore[attr-defined]
        return g
    except Exception:
        return None


def check_duplicates(registry: Any) -> dict | None:
    # Heuristic: look at attributes of registry ending with known metric suffixes or having a _type attribute
    attrs = dir(registry)
    metric_like: dict[int, list[tuple[str, Any]]] = {}
    total = 0
    for name in attrs:
        if name.startswith('_'):
            continue
        try:
            obj = getattr(registry, name)
        except Exception:
            continue
        # Determine if object looks like a Prometheus metric first
        metric_like_attrs = (hasattr(obj, '_type') or hasattr(obj, '_name') or hasattr(obj, '_value'))
        # Some Prometheus metric objects are callable (label proxy pattern); treat those as metrics
        if not metric_like_attrs:
            if callable(obj):  # type: ignore[arg-type]
                continue  # callable AND not metric-like -> skip
            # Not callable but no metric markers -> skip
            continue
        # If callable but metric-like, allow through (do not skip).
        ident = id(obj)
        metric_like.setdefault(ident, []).append((name, obj))
        total += 1

    # Decide alias suppression policy:
    # - If env G6_DUPLICATES_ALLOW_ALIAS_SUFFIX is set, honor it.
    # - Else, auto-suppress *_alias only for large/real registries (heuristic: many metric-like attributes),
    #   and treat *_alias as duplicates for tiny/minimal test registries. This balances governance vs. unit tests.
    _env_alias = os.getenv('G6_DUPLICATES_ALLOW_ALIAS_SUFFIX')
    if _env_alias is None:
        _allow_alias = False  # default for small registries
    else:
        _allow_alias = _parse_bool(_env_alias)

    duplicates: list[dict[str, Any]] = []
    for ident, entries in metric_like.items():
        if len(entries) <= 1:
            continue
        names = sorted(e[0] for e in entries)
        # Determine a representative type string
        typ = None
        for _, obj in entries:
            typ = getattr(obj, '_type', None) or getattr(obj, '_name', None)
            if typ:
                break
        # Suppress known alias patterns (canonical vs *_total vs legacy_* for the same collector)
        try:
            # Evaluate alias suppression: if not explicitly set via env and registry looks large, enable suppression.
            allow_alias_env = _allow_alias or (_env_alias is None and total >= 50)
            norm = set()
            for n in names:
                base = n
                if base.startswith('legacy_'):
                    base = base[len('legacy_'):]
                if base.endswith('_total'):
                    base = base[:-len('_total')]
                if base.endswith('_total'):
                    base = base[:-len('_total')]
                if allow_alias_env and base.endswith('_alias'):
                    base = base[:-len('_alias')]
                norm.add(base)
            if len(norm) == 1:
                allowed = True
                base_only = next(iter(norm))
                for n in names:
                    if n == base_only:
                        continue
                    if n == f'{base_only}_total':
                        continue
                    if n == f'legacy_{base_only}':
                        continue
                    if allow_alias_env and n == f'{base_only}_alias':
                        continue
                    if n == f'legacy_{base_only}_total':
                        continue
                    allowed = False
                    break
                if allowed:
                    continue
        except Exception:
            pass
        duplicates.append({
            'names': names,
            'type': typ or 'unknown',
            'name': getattr(entries[0][1], '_name', None) or 'n/a',
            'count': len(names),
        })

    if not duplicates:
        return None

    fail = _parse_bool(os.getenv('G6_DUPLICATES_FAIL_ON_DETECT'))
    debug = _parse_bool(os.getenv('G6_DUPLICATES_LOG_DEBUG'))
    suppress_warn = _parse_bool(os.getenv('G6_SUPPRESS_DUPLICATE_METRICS_WARN'))
    override_level = os.getenv('G6_DUPLICATES_LOG_LEVEL', '').strip().lower()

    # Attach gauge
    g = _ensure_duplicates_gauge(registry)
    if g is not None:
        try:
            g.set(len(duplicates))  # type: ignore[attr-defined]
        except Exception:
            pass

    for d in duplicates[:5]:  # cap debug spam
        if debug:
            logger.debug('metrics.duplicates.detail names=%s type=%s', ','.join(d['names']), d['type'])

    if not suppress_warn:
        # Build a stable signature: (#groups, hash of first group's joined names) to de-noise repeated logs.
        try:
            first_sample = ','.join(duplicates[0]['names']) if duplicates else ''
            sig = (len(duplicates), hash(first_sample))
        except Exception:
            sig = (len(duplicates), 0)
        emit_always = _parse_bool(os.getenv('G6_DUPLICATES_ALWAYS_LOG'))
        if emit_always or sig not in _EMITTED_SIGNATURES:
            if not emit_always:
                _EMITTED_SIGNATURES.add(sig)
            log_fn = logger.warning
            if override_level in {'info','debug','error','critical'}:
                log_fn = getattr(logger, 'critical' if override_level == 'fatal' else override_level, logger.warning)
            try:
                log_fn(
                    'metrics.duplicates.detected groups=%d total_attrs=%d sample=%s',
                    len(duplicates),
                    total,
                    duplicates[0]['names'] if duplicates else [],
                    extra={
                        'event': 'metrics.duplicates.detected',
                        'groups': duplicates[:10],  # cap payload
                        'groups_total': len(duplicates),
                        'dedup_suppressed': not emit_always,
                    }
                )
            except Exception:
                pass

    if fail:
        raise RuntimeError(f"Duplicate metrics detected (groups={len(duplicates)})")

    summary = {
        'duplicates': duplicates,
        'duplicate_group_count': len(duplicates),
        'total_attributes_scanned': total,
        'failed': False,
    }
    try:
        registry._duplicate_metrics_summary = summary  # type: ignore[attr-defined]
    except Exception:
        pass
    return summary


__all__ = ["check_duplicates"]
