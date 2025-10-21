"""Risk Aggregation Builder (Phase 5.6 initial implementation)

Aggregates option level Greeks into moneyness bands per index & expiry.

Activation:
    G6_RISK_AGG=1 | true | on

Environment (new):
    G6_RISK_AGG_BUCKETS   Comma separated moneyness bucket edges (percent). Default: -20,-10,-5,0,5,10,20
    G6_RISK_AGG_MAX_OPTIONS  Safety cap on processed option rows (default 25000)

Input Contract (duck-typed):
    Iterable of dicts with fields: index, expiry, strike, underlying, delta, gamma, vega, theta, rho
    or provider object exposing get_option_snapshots(). Missing fields skipped.

Output:
    {
        'meta': {version:1, builder:'basic', buckets:[...], processed:int, persisted:bool},
        'data': [ {index, expiry, bucket, delta, gamma, vega, theta, rho, count, notionals:{delta,vega}} ]
    }

Metrics:
    g6_risk_agg_builds_total
    g6_risk_agg_last_build_unixtime
    g6_risk_agg_build_seconds (histogram)
"""
from __future__ import annotations

import gzip
import json
import os
import time
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, TypedDict, cast


# Lightweight metric interaction helpers (avoid repeated attr-defined ignores)
def _set_metric(obj: Any, name: str, value: float | int) -> None:
    try:
        m = getattr(obj, name, None)
        if m is None:
            return
        set_fn = getattr(m, 'set', None)
        if callable(set_fn):
            set_fn(value)
    except Exception:
        pass

def _inc_metric(obj: Any, name: str, amount: int | float = 1) -> None:
    try:
        m = getattr(obj, name, None)
        if m is None:
            return
        inc_fn = getattr(m, 'inc', None)
        if callable(inc_fn):
            inc_fn(amount)
    except Exception:
        pass

def _observe_metric(obj: Any, name: str, value: float | int) -> None:
    try:
        m = getattr(obj, name, None)
        if m is None:
            return
        obs = getattr(m, 'observe', None)
        if callable(obs):
            obs(value)
    except Exception:
        pass

def _labels_set(obj: Any, metric_name: str, labels: dict[str,str], value: float | int) -> None:
    try:
        m = getattr(obj, metric_name, None)
        if m is None:
            return
        lbl = getattr(m, 'labels', None)
        if callable(lbl):
            inst = lbl(**labels)
            setter = getattr(inst, 'set', None)
            if callable(setter):
                setter(value)
    except Exception:
        pass

class _RiskRow(TypedDict, total=False):
    index: str
    expiry: str
    bucket: str
    delta: float
    gamma: float
    vega: float
    theta: float
    rho: float
    count: int
    notionals: dict[str, float]

class _RiskPayload(TypedDict):
    meta: dict[str, Any]
    data: list[_RiskRow]

_risk_cache: _RiskPayload | dict[str, Any] | None = None  # may hold legacy dict shape
_last_build_ts: float | None = None


def _emit_per_index_notionals(metrics: Any, rows: Sequence[Mapping[str, Any]]) -> None:
    """Aggregate per-index delta/vega notionals and emit via already-registered labelled gauges.

    metrics is untyped (Any) due to dynamic runtime registration pattern. All exceptions swallowed.
    """
    try:
        per_index_delta: dict[str, float] = {}
        per_index_vega: dict[str, float] = {}
        for r in rows:
            idx = r.get('index')
            notionals = r.get('notionals') or {}
            if isinstance(idx, str):
                try:
                    per_index_delta[idx] = per_index_delta.get(idx, 0.0) + float(notionals.get('delta') or 0)
                    per_index_vega[idx] = per_index_vega.get(idx, 0.0) + float(notionals.get('vega') or 0)
                except Exception:
                    pass
        for idx, val in per_index_delta.items():
            try:
                metrics.risk_agg_notional_delta_index.labels(index=idx).set(round(val, 6))
            except Exception:
                pass
        for idx, val in per_index_vega.items():
            try:
                metrics.risk_agg_notional_vega_index.labels(index=idx).set(round(val, 6))
            except Exception:
                pass
    except Exception:
        pass


def _parse_buckets() -> list[float]:
    raw = os.environ.get('G6_RISK_AGG_BUCKETS','-20,-10,-5,0,5,10,20')
    out: list[float] = []
    for part in raw.split(','):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(float(part))
        except ValueError:
            continue
    return sorted(set(out))


def _iter_options(snapshot_source) -> Iterable[dict[str, Any]]:
    """Yield option snapshot dicts from either a list or a provider object.

    All non-dict rows are skipped defensively. Any provider errors are swallowed.
    """
    if isinstance(snapshot_source, list):
        for row in snapshot_source:
            if isinstance(row, dict):
                yield row
        return
    getter = getattr(snapshot_source, 'get_option_snapshots', None)
    if callable(getter):
        try:
            it = getter()
            if it:  # Guard None / falsey
                # Some providers may return list-like, ensure iterable at runtime
                try:
                    for row in cast(Iterable[Any], it):
                        if isinstance(row, dict):
                            yield row
                except TypeError:
                    return
        except Exception:
            return


def _contract_multiplier(index: str) -> float:
    env_key = f'G6_CONTRACT_MULTIPLIER_{index.upper()}'
    try:
        if env_key in os.environ:
            return float(os.environ[env_key])
        return float(os.environ.get('G6_CONTRACT_MULTIPLIER_DEFAULT','1'))
    except Exception:
        return 1.0


def build_risk(snapshot_source) -> _RiskPayload | None:
    if os.environ.get('G6_RISK_AGG','').lower() not in ('1','true','yes','on'):
        return None
    start = time.time()
    buckets = _parse_buckets()
    max_options = int(os.environ.get('G6_RISK_AGG_MAX_OPTIONS','25000'))
    persist = os.environ.get('G6_RISK_AGG_PERSIST','').lower() in ('1','true','yes','on')
    compress = os.environ.get('G6_ANALYTICS_COMPRESS','').lower() in ('1','true','yes','on')
    persist_dir = os.environ.get('G6_ANALYTICS_DIR', 'data/analytics')
    acc: dict[tuple[str,str,str], dict[str, float]] = {}
    counts: dict[tuple[str,str,str], int] = {}
    processed = 0
    for opt in _iter_options(snapshot_source):
        if processed >= max_options:
            break
        processed += 1
        try:
            index_v = opt.get('index')
            expiry_v = opt.get('expiry')
            strike_v = opt.get('strike')
            underlying_v = opt.get('underlying')
            if not (index_v and expiry_v and strike_v and underlying_v):
                continue
            delta_v = opt.get('delta')
            gamma_v = opt.get('gamma')
            vega_v = opt.get('vega')
            theta_v = opt.get('theta')
            rho_v = opt.get('rho')
            if any(x is None for x in (delta_v, gamma_v, vega_v, theta_v, rho_v)):
                continue
            # Type safety: ensure numeric
            if not all(isinstance(x, (int,float)) for x in (delta_v, gamma_v, vega_v, theta_v, rho_v)):
                continue
            index = str(index_v)
            expiry = str(expiry_v)
            strike = float(strike_v)
            underlying = float(underlying_v)
            if underlying <= 0:
                continue
            moneyness_pct = ((strike / underlying) - 1.0) * 100.0
            bucket_label = None
            for i in range(len(buckets)-1):
                if buckets[i] <= moneyness_pct <= buckets[i+1]:
                    bucket_label = f"[{buckets[i]},{buckets[i+1]}]"
                    break
            if bucket_label is None:
                if moneyness_pct < buckets[0]:
                    bucket_label = f"<-inf,{buckets[0]}]"
                else:
                    bucket_label = f"[{buckets[-1]},+inf)"
            key = (index, expiry, bucket_label)
            slot = acc.setdefault(key, {'delta':0.0,'gamma':0.0,'vega':0.0,'theta':0.0,'rho':0.0})
            # After numeric validation above, safe to cast to float
            delta_f = float(cast(float | int, delta_v))
            gamma_f = float(cast(float | int, gamma_v))
            vega_f = float(cast(float | int, vega_v))
            theta_f = float(cast(float | int, theta_v))
            rho_f = float(cast(float | int, rho_v))
            slot['delta'] += delta_f
            slot['gamma'] += gamma_f
            slot['vega'] += vega_f
            slot['theta'] += theta_f
            slot['rho'] += rho_f
            counts[key] = counts.get(key,0) + 1
        except Exception:
            continue

    rows: list[_RiskRow] = []
    for (index, expiry, bucket), greeks in acc.items():
        c = counts.get((index, expiry, bucket),0)
        mult = _contract_multiplier(index)
        # notional approximations: delta_notional = |delta| * underlying placeholder (not available now) * multiplier
        # Since underlying per option may differ slightly, we approximate using aggregate delta * synthetic underlying = 1 for now.
        # This can be refined when underlying aggregation is available.
        delta_notional = abs(greeks['delta']) * mult
        vega_notional = abs(greeks['vega']) * mult
        rows.append({
            'index': index,
            'expiry': expiry,
            'bucket': bucket,
            'delta': round(greeks['delta'],6),
            'gamma': round(greeks['gamma'],6),
            'vega': round(greeks['vega'],6),
            'theta': round(greeks['theta'],6),
            'rho': round(greeks['rho'],6),
            'count': c,
            'notionals': {
                'delta': round(delta_notional,6),
                'vega': round(vega_notional,6)
            }
        })

    risk: _RiskPayload = {'meta': {'version':1,'builder':'basic','buckets':buckets,'processed':processed,'persisted':False}, 'data': rows}
    global _risk_cache, _last_build_ts
    _risk_cache = risk
    _last_build_ts = time.time()
    elapsed = max(_last_build_ts - start, 0.0)
    try:  # pragma: no cover
        metrics: Any = getattr(snapshot_source, 'metrics', None)
        if metrics and hasattr(metrics, 'risk_agg_last_build_unixtime'):
            metrics.risk_agg_last_build_unixtime.set(_last_build_ts)
        if metrics and hasattr(metrics, 'risk_agg_builds'):
            metrics.risk_agg_builds.inc()
        if metrics and hasattr(metrics, 'risk_agg_build_seconds'):
            metrics.risk_agg_build_seconds.observe(elapsed)
        if metrics and hasattr(metrics, 'risk_agg_rows'):
            try:
                total_rows = len(rows)
                metrics.risk_agg_rows.set(total_rows)
                # Aggregate notional exposures
                total_delta_notional = 0.0
                total_vega_notional = 0.0
                for r in rows:
                    n = r.get('notionals') or {}
                    try:
                        total_delta_notional += float(n.get('delta') or 0)
                        total_vega_notional += float(n.get('vega') or 0)
                    except Exception:
                        pass
                # Follow-up guards feed (risk drift window)
                try:
                    from src.adaptive import followups
                    followups.feed('global', notional_delta=total_delta_notional, option_count=total_rows)
                except Exception:
                    pass
                # Optional per-index notionals (labelled) behind env flag (dynamic registration allowed)
                if os.environ.get('G6_RISK_NOTIONALS_PER_INDEX','').lower() in ('1','true','yes','on'):
                    try:
                        # Prefer modern grouped registration helper; idempotent and group-aware
                        if not hasattr(metrics, 'risk_agg_notional_delta_index') and hasattr(metrics, '_maybe_register'):
                            try:
                                from prometheus_client import Gauge as _Gauge  # type: ignore
                            except Exception:  # pragma: no cover - defensive
                                _Gauge = None  # type: ignore
                            if _Gauge is not None:
                                metrics._maybe_register(  # type: ignore[attr-defined]
                                    'analytics_risk_agg',
                                    'risk_agg_notional_delta_index',
                                    _Gauge,
                                    'g6_risk_agg_notional_delta_index',
                                    'Aggregate delta notional per index (optional flag)',
                                    ['index']
                                )
                                metrics._maybe_register(  # type: ignore[attr-defined]
                                    'analytics_risk_agg',
                                    'risk_agg_notional_vega_index',
                                    _Gauge,
                                    'g6_risk_agg_notional_vega_index',
                                    'Aggregate vega notional per index (optional flag)',
                                    ['index']
                                )
                        if hasattr(metrics, 'risk_agg_notional_delta_index'):
                            _emit_per_index_notionals(metrics, rows)
                    except Exception:
                        pass
                if hasattr(metrics, 'risk_agg_notional_delta'):
                    metrics.risk_agg_notional_delta.set(round(total_delta_notional,6))
                if hasattr(metrics, 'risk_agg_notional_vega'):
                    metrics.risk_agg_notional_vega.set(round(total_vega_notional,6))
                # Bucket utilization: fraction of theoretical buckets populated (unique bucket labels present across all indices/expiries)
                if hasattr(metrics, 'risk_agg_bucket_utilization'):
                    try:
                        populated = len({r.get('bucket') for r in rows if r.get('bucket')})
                        # theoretical buckets = len(buckets)+2 (outer extensions) unless buckets empty
                        theoretical = (len(buckets) + 1) if not buckets else (len(buckets) + 1)  # buckets list is edges; label count may vary; use populated/len(unique labels in rows)
                        frac_util = (populated / theoretical) if theoretical else 0.0
                        metrics.risk_agg_bucket_utilization.set(min(max(frac_util,0.0),1.0))
                        # Follow-up guards feed (bucket utilization)
                        try:
                            from src.adaptive import followups
                            followups.feed('global', bucket_utilization=frac_util)
                        except Exception:
                            pass
                        # Bucket utilization alert tracking
                        try:
                            from src.adaptive.alerts import record_bucket_util
                            alert = record_bucket_util(frac_util)
                            if alert is not None:
                                try:
                                    alerts_list = getattr(snapshot_source, 'adaptive_alerts', None)
                                    if alerts_list is None:
                                        snapshot_source.adaptive_alerts = [alert]
                                    else:
                                        if isinstance(alerts_list, list):
                                            alerts_list.append(alert)
                                except Exception:
                                    pass
                        except Exception:
                            pass
                    except Exception:
                        pass
                # Risk delta drift alert (after computing delta notionals)
                try:
                    from src.adaptive.alerts import record_risk_delta
                    alert = record_risk_delta(total_delta_notional, len(rows))
                    if alert is not None:
                        try:
                            alerts_list = getattr(snapshot_source, 'adaptive_alerts', None)
                            if alerts_list is None:
                                snapshot_source.adaptive_alerts = [alert]
                            else:
                                if isinstance(alerts_list, list):
                                    alerts_list.append(alert)
                        except Exception:
                            pass
                except Exception:
                    pass
            except Exception:
                pass
    except Exception:
        # Fallback path: late bind metrics if snapshot_source lacked .metrics
        try:
            # Use public facade instead of deprecated deep import of src.metrics.metrics
            from src.metrics import get_metrics as _facade_get_metrics  # type: ignore
            try:
                m = _facade_get_metrics()
            except Exception:
                m = None
        except Exception:
            m = None
        if m is not None:
            _set_metric(m, 'risk_agg_last_build_unixtime', _last_build_ts or 0.0)
            _inc_metric(m, 'risk_agg_builds')
            _observe_metric(m, 'risk_agg_build_seconds', elapsed)
            try:
                total_rows = len(rows)
            except Exception:
                total_rows = 0
            _set_metric(m, 'risk_agg_rows', total_rows)
            # Recompute summaries for fallback
            total_delta_notional = 0.0
            total_vega_notional = 0.0
            for r in rows:
                n = r.get('notionals') or {}
                try:
                    total_delta_notional += float(n.get('delta') or 0)
                    total_vega_notional += float(n.get('vega') or 0)
                except Exception:
                    pass
            # Adaptive followups (best effort)
            try:
                from src.adaptive import followups
                followups.feed('global', notional_delta=total_delta_notional, option_count=total_rows)
            except Exception:
                pass
            # Optional per-index metrics
            if os.environ.get('G6_RISK_NOTIONALS_PER_INDEX','').lower() in ('1','true','yes','on'):
                try:
                    if not hasattr(m, 'risk_agg_notional_delta_index') and hasattr(m, '_maybe_register'):
                        try:
                            from prometheus_client import Gauge as _Gauge  # type: ignore
                        except Exception:
                            _Gauge = None  # type: ignore
                        if _Gauge is not None:
                            m._maybe_register(  # type: ignore[attr-defined]
                                'analytics_risk_agg',
                                'risk_agg_notional_delta_index',
                                _Gauge,
                                'g6_risk_agg_notional_delta_index',
                                'Aggregate delta notional per index (optional flag)',
                                ['index']
                            )
                            m._maybe_register(  # type: ignore[attr-defined]
                                'analytics_risk_agg',
                                'risk_agg_notional_vega_index',
                                _Gauge,
                                'g6_risk_agg_notional_vega_index',
                                'Aggregate vega notional per index (optional flag)',
                                ['index']
                            )
                    if hasattr(m, 'risk_agg_notional_delta_index'):
                        per_index_delta: dict[str,float] = {}
                        per_index_vega: dict[str,float] = {}
                        for r in rows:
                            idx = r.get('index')
                            notionals = r.get('notionals') or {}
                            if isinstance(idx, str):
                                try:
                                    per_index_delta[idx] = per_index_delta.get(idx,0.0) + float(notionals.get('delta') or 0)
                                    per_index_vega[idx] = per_index_vega.get(idx,0.0) + float(notionals.get('vega') or 0)
                                except Exception:
                                    pass
                        for idx, val in per_index_delta.items():
                            _labels_set(m, 'risk_agg_notional_delta_index', {'index': idx}, round(val,6))
                        for idx, val in per_index_vega.items():
                            _labels_set(m, 'risk_agg_notional_vega_index', {'index': idx}, round(val,6))
                except Exception:
                    pass
            _set_metric(m, 'risk_agg_notional_delta', round(total_delta_notional,6))
            _set_metric(m, 'risk_agg_notional_vega', round(total_vega_notional,6))
            # Bucket utilization
            try:
                populated = len({r.get('bucket') for r in rows if r.get('bucket')})
                theoretical = (len(buckets) + 1) if not buckets else (len(buckets) + 1)
                frac_util = (populated / theoretical) if theoretical else 0.0
                _set_metric(m, 'risk_agg_bucket_utilization', min(max(frac_util,0.0),1.0))
                try:
                    from src.adaptive.alerts import record_bucket_util
                    alert = record_bucket_util(frac_util)
                    if alert is not None:
                        alerts_list = getattr(snapshot_source, 'adaptive_alerts', None)
                        if alerts_list is None:
                            snapshot_source.adaptive_alerts = [alert]
                        else:
                            if isinstance(alerts_list, list):
                                alerts_list.append(alert)
                except Exception:
                    pass
            except Exception:
                pass
            # Risk delta drift alert
            try:
                from src.adaptive.alerts import record_risk_delta
                alert = record_risk_delta(total_delta_notional, len(rows))
                if alert is not None:
                    alerts_list = getattr(snapshot_source, 'adaptive_alerts', None)
                    if alerts_list is None:
                        snapshot_source.adaptive_alerts = [alert]
                    else:
                        if isinstance(alerts_list, list):
                            alerts_list.append(alert)
            except Exception:
                pass
    # Persistence
    if persist:
        try:
            os.makedirs(persist_dir, exist_ok=True)
            fname = 'risk_agg.latest.json'
            path = os.path.join(persist_dir, fname)
            payload = json.dumps(risk, separators=(',', ':'), ensure_ascii=False)
            if compress:
                gz_path = path + '.gz'
                with gzip.open(gz_path, 'wt', encoding='utf-8') as gz:
                    gz.write(payload)
                risk['meta']['persisted'] = True
                risk['meta']['persist_path'] = gz_path
            else:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(payload)
                risk['meta']['persisted'] = True
                risk['meta']['persist_path'] = path
        except Exception:
            pass
    return risk


def get_latest_risk() -> _RiskPayload | None:
    cache = _risk_cache
    if not cache:
        return None
    # Runtime shape validation: must have 'meta' dict and 'data' list
    if isinstance(cache, dict):
        meta = cache.get('meta')
        data = cache.get('data')
        if isinstance(meta, dict) and isinstance(data, list):
            # Narrow type for mypy by building new dict with expected keys
            return cast(_RiskPayload, {'meta': meta, 'data': data})
    return None

__all__ = ["build_risk", "get_latest_risk"]
