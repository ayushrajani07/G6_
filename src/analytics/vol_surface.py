"""Volatility Surface Builder (Phase 5.6 initial implementation)

Turns option snapshot structures into a coarse volatility surface organized by
index, expiry, and moneyness bucket. This replaces the previous stub with a
minimal but useful aggregation suitable for operator visualization and future
interpolation.

Activation:
    G6_VOL_SURFACE=1 | true | on

Environment (new):
    G6_VOL_SURFACE_BUCKETS   Comma separated moneyness bucket edges (percent).
                                                     Example: "-20,-10,-5,0,5,10,20" (default)
    G6_VOL_SURFACE_MAX_OPTIONS  Upper bound on options processed (safety) default 20000

Snapshot Source Contract (duck-typed):
    Expects either an iterable of option dicts each containing:
        index, expiry, strike, underlying (ltp), iv
    OR an object with attribute `get_option_snapshots()` returning such iterable.

Output Structure:
    {
        "meta": {"version": 1, "buckets": [...], "builder": "basic", "interpolated": bool, "persisted": bool},
        "data": [
             {"index": str, "expiry": str, "bucket": "[-5,0]", "avg_iv": float, "count": int, "source": "raw|interp"}
        ]
    }

Metrics:
    g6_vol_surface_builds_total{index="global"}
    g6_vol_surface_last_build_unixtime{index="global"}
    g6_vol_surface_build_seconds (histogram)
"""
from __future__ import annotations

import gzip
import json
import os
import time
from collections.abc import Iterable
from collections.abc import Iterable as _IterableABC
from statistics import mean
from typing import Any, Protocol

_surface_cache: dict[str, Any] = {}
_last_build_ts: float | None = None


def _parse_buckets() -> list[float]:
    raw = os.environ.get('G6_VOL_SURFACE_BUCKETS', '-20,-10,-5,0,5,10,20')
    edges: list[float] = []
    for part in raw.split(','):
        part = part.strip()
        if not part:
            continue
        try:
            edges.append(float(part))
        except ValueError:
            continue
    return sorted(set(edges))


def _iter_options(snapshot_source: Any) -> Iterable[dict[str, Any]]:
    # Direct iterable
    if isinstance(snapshot_source, list):
        for row in snapshot_source:
            if isinstance(row, dict):
                yield row
        return
    # Attribute hook
    getter = getattr(snapshot_source, 'get_option_snapshots', None)
    if callable(getter):
        try:
            it = getter()
            if isinstance(it, _IterableABC):
                for row in it:
                    if isinstance(row, dict):
                        yield row
        except Exception:
            return


def _interpolate_missing(rows: list[dict[str, Any]], buckets: list[float]) -> list[dict[str, Any]]:
    """Fill missing bucket entries per (index, expiry) by linear interpolating avg_iv across bucket midpoints.

    Rules:
      - Only interpolate if at least 2 real (raw) points exist.
      - For a contiguous run of missing internal buckets, interpolate along straight line between the nearest
        known neighbors.
      - Do NOT extrapolate beyond first/last known bucket.
      - Mark interpolated rows with source='interp' and count=0.
    """
    # Organize by (index, expiry)
    by_key: dict[tuple[str,str], dict[str, dict[str, Any]]] = {}
    def _bucket_mid(b: str) -> float | None:
        # b forms: "[a,b]", "<-inf,x]", "[x,+inf)" -> only interpolate finite ones
        if b.startswith('[') and ',' in b and b.endswith(']'):
            try:
                parts = b.strip('[]').split(',')
                return (float(parts[0]) + float(parts[1]))/2.0
            except Exception:
                return None
        return None
    for r in rows:
        if r.get('source') == 'interp':
            continue
        key = (r['index'], r['expiry'])
        by_key.setdefault(key, {})[r['bucket']] = r
    augmented = list(rows)
    finite_bucket_labels = []
    # Build list of finite bucket labels in order for interpolation domain
    for i in range(len(buckets)-1):
        finite_bucket_labels.append(f"[{buckets[i]},{buckets[i+1]}]")
    for (idx, exp), bucket_map in by_key.items():
        # Collect existing finite points in order
        existing = []
        for lbl in finite_bucket_labels:
            if lbl in bucket_map:
                mid = _bucket_mid(lbl)
                if mid is not None:
                    existing.append((mid, bucket_map[lbl]['avg_iv']))
        if len(existing) < 2:
            continue  # need at least two anchors
        # Now walk spans between consecutive known anchors and fill missing labels lying strictly between
        for a_i in range(len(existing)-1):
            left_mid, left_iv = existing[a_i]
            right_mid, right_iv = existing[a_i+1]
            span = right_mid - left_mid
            if span == 0:
                continue
            # Determine which bucket labels lie between these midpoints
            for lbl in finite_bucket_labels:
                if lbl in bucket_map:
                    continue
                mid = _bucket_mid(lbl)
                if mid is None:
                    continue
                if left_mid < mid < right_mid:
                    # Linear interpolation
                    t = (mid - left_mid)/span
                    iv_interp = left_iv + t * (right_iv - left_iv)
                    augmented.append({
                        'index': idx,
                        'expiry': exp,
                        'bucket': lbl,
                        'avg_iv': round(float(iv_interp), 6),
                        'count': 0,
                        'source': 'interp'
                    })
                    # Add to map so later spans see it only for preventing duplicate work (but not a real anchor)
                    bucket_map[lbl] = augmented[-1]
    return augmented


class _MetricLabel(Protocol):  # minimal subset of prometheus-like label objects
    def set(self, value: int | float) -> Any: ...
    def inc(self, value: int | float=1) -> Any: ...
    def observe(self, value: int | float) -> Any: ...

def _safe_label(obj: Any) -> _MetricLabel | None:
    if obj is None:
        return None
    # duck-typing: ensure at least one expected attribute
    if any(hasattr(obj, attr) for attr in ('set','inc','observe')):
        return obj  # type: ignore[return-value]
    return None

def build_surface(snapshot_source: Any) -> dict[str, Any] | None:
    if os.environ.get('G6_VOL_SURFACE','').lower() not in ('1','true','yes','on'):
        return None
    start = time.time()
    buckets = _parse_buckets()
    max_options = int(os.environ.get('G6_VOL_SURFACE_MAX_OPTIONS','20000'))
    interpolate = os.environ.get('G6_VOL_SURFACE_INTERPOLATE','').lower() in ('1','true','yes','on')
    persist = os.environ.get('G6_VOL_SURFACE_PERSIST','').lower() in ('1','true','yes','on')
    compress = os.environ.get('G6_ANALYTICS_COMPRESS','').lower() in ('1','true','yes','on')
    persist_dir = os.environ.get('G6_ANALYTICS_DIR', 'data/analytics')

    # Accumulator: (index, expiry, bucket_label) -> list[iv]
    acc: dict[tuple[str,str,str], list[float]] = {}
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
            iv = opt.get('iv')
            if index_v is None or expiry_v is None or strike_v is None or underlying_v is None or iv is None:
                continue
            index = str(index_v)
            expiry = str(expiry_v)
            strike = float(strike_v)
            underlying = float(underlying_v)
            if underlying and underlying > 0 and iv is not None:
                moneyness_pct = ((strike / underlying) - 1.0) * 100.0
                # Find bucket (between edge_i and edge_{i+1})
                bucket_label = None
                for i in range(len(buckets)-1):
                    if buckets[i] <= moneyness_pct <= buckets[i+1]:
                        bucket_label = f"[{buckets[i]},{buckets[i+1]}]"
                        break
                if bucket_label is None:
                    # Outside range, clamp to outer bucket
                    if moneyness_pct < buckets[0]:
                        bucket_label = f"<-inf,{buckets[0]}]"
                    else:
                        bucket_label = f"[{buckets[-1]},+inf)"
                key = (index, expiry, bucket_label)
                acc.setdefault(key, []).append(float(iv))
        except Exception:
            continue

    rows = []
    for (index, expiry, bucket_label), ivs in acc.items():
        if not ivs:
            continue
        rows.append({
            'index': index,
            'expiry': expiry,
            'bucket': bucket_label,
            'avg_iv': round(mean(ivs), 6),
            'count': len(ivs),
            'source': 'raw'
        })

    interp_start = None
    if interpolate:
        interp_start = time.time()
        rows = _interpolate_missing(rows, buckets)
    interp_elapsed = (time.time() - interp_start) if interp_start else 0.0

    # Placeholder model hook (future SABR, etc.)
    model_elapsed = 0.0
    if os.environ.get('G6_VOL_SURFACE_MODEL','').lower() in ('1','true','yes','on'):
        model_start = time.time()
        # No-op model build placeholder; future implementation can populate calibrated params
        time.sleep(0)  # intentional noop for clarity
        model_elapsed = time.time() - model_start

    surface = {
        'meta': {'version': 1, 'builder': 'basic', 'buckets': buckets, 'processed': processed, 'interpolated': interpolate, 'persisted': False},
        'data': rows
    }
    global _surface_cache, _last_build_ts
    _surface_cache = surface
    _last_build_ts = time.time()
    # Metrics hooks (consolidated)
    elapsed = max(_last_build_ts - start, 0.0)

    def _emit(metrics_obj: Any) -> None:
        if not metrics_obj:
            return
        try:
            if hasattr(metrics_obj, 'vol_surface_last_build_unixtime'):
                lbl = metrics_obj.vol_surface_last_build_unixtime.labels(index='global')
                ts_val = float(_last_build_ts) if _last_build_ts is not None else time.time()
                _l = _safe_label(lbl);  _l.set(ts_val) if _l else None
            if hasattr(metrics_obj, 'vol_surface_builds'):
                lbl = metrics_obj.vol_surface_builds.labels(index='global')
                _l = _safe_label(lbl);  _l.inc() if _l else None
            if hasattr(metrics_obj, 'vol_surface_build_seconds'):
                _l = _safe_label(metrics_obj.vol_surface_build_seconds)
                if _l: _l.observe(elapsed)
            if hasattr(metrics_obj, 'vol_surface_rows'):
                raw_count = sum(1 for r in rows if r.get('source') == 'raw')
                interp_count = sum(1 for r in rows if r.get('source') == 'interp')
                try:
                    lbl_r = metrics_obj.vol_surface_rows.labels(index='global', source='raw')
                    lbl_i = metrics_obj.vol_surface_rows.labels(index='global', source='interp')
                    _lr = _safe_label(lbl_r); _li = _safe_label(lbl_i)
                    _lr.set(raw_count) if _lr else None
                    _li.set(interp_count) if _li else None
                except Exception:
                    pass
                if hasattr(metrics_obj, 'vol_surface_interpolated_fraction'):
                    total_rows = raw_count + interp_count
                    frac = (interp_count / total_rows) if total_rows else 0.0
                    try:
                        lbl_f = metrics_obj.vol_surface_interpolated_fraction.labels(index='global')
                        _lf = _safe_label(lbl_f); _lf.set(frac) if _lf else None
                    except Exception:
                        pass
                    # Follow-up guards feed (interpolation fraction)
                    try:
                        from src.adaptive import followups
                        try:
                            followups.feed('global', interpolated_fraction=frac)  # type: ignore[attr-defined]
                        except Exception:
                            pass
                    except Exception:
                        pass
                    # Interpolation guard alert (record streak & potential alert)
                    try:
                        from src.adaptive.alerts import record_interpolation_fraction
                        alert = record_interpolation_fraction('global', frac)
                        if alert is not None:
                            # Attach to snapshot_source (if it exposes list) for later status writer consumption
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
                # Quality score heuristic: weight raw coverage and penalize heavy interpolation
                if hasattr(metrics_obj, 'vol_surface_quality_score'):
                    try:
                        coverage = raw_count / (raw_count + interp_count) if (raw_count + interp_count) else 0.0
                        # Simple score: coverage * (1 - frac). Range 0-1.
                        quality = coverage * (1 - (interp_count / (raw_count + interp_count) if (raw_count + interp_count) else 0))
                        lbl_q = metrics_obj.vol_surface_quality_score.labels(index='global')
                        _lq = _safe_label(lbl_q); _lq.set(quality) if _lq else None
                    except Exception:
                        pass
                if hasattr(metrics_obj, 'vol_surface_interp_seconds') and interp_elapsed:
                    try:
                        _li2 = _safe_label(metrics_obj.vol_surface_interp_seconds)
                        if _li2: _li2.observe(interp_elapsed)
                    except Exception:
                        pass
                if hasattr(metrics_obj, 'vol_surface_model_build_seconds') and model_elapsed:
                    try:
                        _lm = _safe_label(metrics_obj.vol_surface_model_build_seconds)
                        if _lm: _lm.observe(model_elapsed)
                    except Exception:
                        pass
                # Per-expiry (optional)
                if os.getenv('G6_VOL_SURFACE_PER_EXPIRY') == '1':
                    if not hasattr(metrics_obj, 'vol_surface_rows_expiry') and hasattr(metrics_obj, '_maybe_register'):
                        try:
                            from prometheus_client import Gauge as _Gauge  # type: ignore
                        except Exception:  # pragma: no cover - defensive
                            _Gauge = None  # type: ignore
                        if _Gauge is not None:
                            try:
                                metrics_obj._maybe_register(  # type: ignore[attr-defined]
                                    'analytics_vol_surface',
                                    'vol_surface_rows_expiry',
                                    _Gauge,
                                    'g6_vol_surface_rows_expiry',
                                    'Vol surface per-expiry row count by source',
                                    ['index','expiry','source']
                                )
                                metrics_obj._maybe_register(  # type: ignore[attr-defined]
                                    'analytics_vol_surface',
                                    'vol_surface_interpolated_fraction_expiry',
                                    _Gauge,
                                    'g6_vol_surface_interpolated_fraction_expiry',
                                    'Fraction interpolated per expiry',
                                    ['index','expiry']
                                )
                            except Exception:
                                pass
                    if hasattr(metrics_obj, 'vol_surface_rows_expiry'):
                        try:
                            per_expiry: dict[str, dict[str, int]] = {}
                            for r in rows:
                                exp = r.get('expiry')
                                src = r.get('source')
                                if exp is None or src not in ('raw','interp'):
                                    continue
                                per_expiry.setdefault(exp, {'raw': 0, 'interp': 0})
                                per_expiry[exp][src] += 1
                            for exp, counts in per_expiry.items():
                                try:
                                    lbl_er = metrics_obj.vol_surface_rows_expiry.labels(index='global', expiry=exp, source='raw')
                                    lbl_ei = metrics_obj.vol_surface_rows_expiry.labels(index='global', expiry=exp, source='interp')
                                    _ler = _safe_label(lbl_er); _lei = _safe_label(lbl_ei)
                                    _ler.set(counts.get('raw', 0)) if _ler else None
                                    _lei.set(counts.get('interp', 0)) if _lei else None
                                    if hasattr(metrics_obj, 'vol_surface_interpolated_fraction_expiry'):
                                        total_e = counts.get('raw', 0) + counts.get('interp', 0)
                                        frac_e = (counts.get('interp', 0) / total_e) if total_e else 0.0
                                        lbl_fe = metrics_obj.vol_surface_interpolated_fraction_expiry.labels(index='global', expiry=exp)
                                        _lfe = _safe_label(lbl_fe); _lfe.set(frac_e) if _lfe else None
                                except Exception:
                                    continue
                        except Exception:
                            pass
        except Exception:
            pass

    # Attempt with metrics attached to snapshot source first
    _emit(getattr(snapshot_source, 'metrics', None))
    # Fallback to singleton (covers paths where snapshot_source lacks bound metrics)
    try:  # pragma: no cover - fallback should rarely be needed
        from src.metrics import get_metrics as _gm  # facade import
        _emit(_gm())
    except Exception:
        pass
    # Persistence (best effort)
    if persist:
        try:
            os.makedirs(persist_dir, exist_ok=True)
            fname = 'vol_surface.latest.json'
            path = os.path.join(persist_dir, fname)
            payload = json.dumps(surface, separators=(',', ':'), ensure_ascii=False)
            if compress:
                gz_path = path + '.gz'
                with gzip.open(gz_path, 'wt', encoding='utf-8') as gz:
                    gz.write(payload)
                surface['meta']['persisted'] = True
                surface['meta']['persist_path'] = gz_path
            else:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(payload)
                surface['meta']['persisted'] = True
                surface['meta']['persist_path'] = path
        except Exception:
            pass
    # Assurance path no longer needed; consolidated emitter performs late-binding & retry.
    return surface


def get_latest_surface() -> dict[str, Any] | None:
    return _surface_cache or None

__all__ = ["build_surface", "get_latest_surface"]
