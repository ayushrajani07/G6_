"""Shared helpers for overlay plotting scripts.

This module centralizes common logic used by overlay visualization scripts:
- CSV loading (live and weekday master) with optional chunked reads
- Lightweight memory monitoring hooks (optional psutil)
- Trace construction for Plotly figures
- Config JSON loading and EMA annotations

These helpers are intentionally dependency-light and safe to import from scripts.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional
import os
import json
import gc
from math import floor

try:
    import pandas as pd  # type: ignore
    import plotly.graph_objects as go  # type: ignore
except Exception:  # pragma: no cover - scripts will raise a clearer message
    pd = None  # type: ignore
    go = None  # type: ignore

try:
    import psutil  # type: ignore
except Exception:  # pragma: no cover
    psutil = None  # type: ignore

# Palette
BLUE = "#1f77b4"
ORANGE = "#ff7f0e"
GREEN = "#2ca02c"


def env_int(name: str, default_val: int) -> int:
    try:
        return int(os.environ.get(name, default_val))
    except Exception:
        return default_val


def proc_mem_mb() -> float:
    if psutil is None:
        return -1.0
    try:
        return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
    except Exception:
        return -1.0


def monitor_memory(label: str, threshold_mb: int | None) -> None:
    if not threshold_mb:
        return
    cur = proc_mem_mb()
    if cur > 0 and cur > threshold_mb:
        print(f"[WARN] High memory usage at {label}: {cur:.1f}MB (threshold {threshold_mb}MB)")
        gc.collect()


def _round_time_to_tolerance(series, seconds: int):
    """Round pandas datetime series down to nearest tolerance seconds and return HH:MM:SS strings.

    If seconds <= 0, returns the original HH:MM:SS.
    """
    if pd is None:
        raise RuntimeError("pandas not available")
    if seconds and seconds > 0:
        # Convert to epoch seconds, floor divide, then multiply back
        # Use // for integer division on numpy arrays
        epoch = (series.view('int64') // 10**9)  # nanosecond to seconds
        rounded = (epoch // seconds) * seconds
        # Assign back as datetime64[ns]
        series = pd.to_datetime(rounded, unit='s')
    return series.dt.strftime('%H:%M:%S')


def load_live_series(
    live_root: Path,
    index: str,
    expiry_tag: str,
    offset: str,
    trade_date,
    *,
    chunk_size: Optional[int] = None,
    mem_limit_mb: Optional[int] = None,
    validate_header: bool = True,
):
    """Load live series CSV; returns DataFrame with derived columns or empty DataFrame.

    Columns ensured: timestamp (datetime), time_key (HH:MM:SS), tp_live, avg_tp_live.
    """
    if pd is None:  # pragma: no cover
        raise RuntimeError("pandas not available")
    daily_file = live_root / index / expiry_tag / offset / f"{trade_date:%Y-%m-%d}.csv"
    if not daily_file.exists():
        return pd.DataFrame()
    # Optional header validation to avoid large failed reads
    if validate_header:
        try:
            import csv
            with daily_file.open('r', newline='') as f:
                reader = csv.reader(f)
                header = next(reader, [])
                if 'timestamp' not in header:
                    return pd.DataFrame()
        except Exception:
            return pd.DataFrame()
    try:
        if chunk_size and daily_file.stat().st_size > 10 * 1024 * 1024:
            parts = []
            for ch in pd.read_csv(daily_file, chunksize=chunk_size):
                parts.append(ch)
                monitor_memory(f"live_chunk_{index}_{expiry_tag}_{offset}", mem_limit_mb)
            df = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
            del parts
        else:
            df = pd.read_csv(daily_file)
    except Exception:
        return pd.DataFrame()
    if df.empty or 'timestamp' not in df.columns:
        return pd.DataFrame()
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    for c in ['ce', 'pe', 'avg_ce', 'avg_pe']:
        if c not in df.columns:
            df[c] = 0.0
    df['tp_live'] = df['ce'].fillna(0) + df['pe'].fillna(0)
    df['avg_tp_live'] = df['avg_ce'].fillna(0) + df['avg_pe'].fillna(0)
    tol = env_int('G6_TIME_TOLERANCE_SECONDS', 0)
    if tol < 0:
        tol = 0
    df['time_key'] = _round_time_to_tolerance(df['timestamp'], tol)
    return df


def load_overlay_series(
    weekday_root: Path,
    weekday_name: str,
    index: str,
    expiry_tag: str,
    offset: str,
    *,
    chunk_size: Optional[int] = None,
    mem_limit_mb: Optional[int] = None,
    validate_header: bool = True,
):
    """Load weekday master overlay; returns DataFrame with expected columns or empty."""
    if pd is None:  # pragma: no cover
        raise RuntimeError("pandas not available")
    f = weekday_root / weekday_name / f"{index}_{expiry_tag}_{offset}.csv"
    if not f.exists():
        return pd.DataFrame()
    if validate_header:
        try:
            import csv
            with f.open('r', newline='') as fh:
                reader = csv.reader(fh)
                header = next(reader, [])
                # timestamp is essential for alignment
                if 'timestamp' not in header:
                    return pd.DataFrame()
        except Exception:
            return pd.DataFrame()
    try:
        if chunk_size and f.stat().st_size > 25 * 1024 * 1024:
            parts = []
            for ch in pd.read_csv(f, chunksize=chunk_size):
                parts.append(ch)
                monitor_memory(f"overlay_chunk_{index}_{expiry_tag}_{offset}", mem_limit_mb)
            df = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
            del parts
        else:
            df = pd.read_csv(f)
    except Exception:
        return pd.DataFrame()
    if df.empty:
        return df
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    tol = env_int('G6_TIME_TOLERANCE_SECONDS', 0)
    if tol < 0:
        tol = 0
    df['time_key'] = _round_time_to_tolerance(df['timestamp'], tol)
    for col in ['tp_mean', 'tp_ema', 'avg_tp_mean', 'avg_tp_ema']:
        if col not in df.columns:
            df[col] = None
    return df


def build_merged(live_df, overlay_df):
    if pd is None:  # pragma: no cover
        raise RuntimeError("pandas not available")
    if live_df.empty:
        return pd.DataFrame()
    return live_df.merge(
        overlay_df[['time_key', 'tp_mean', 'tp_ema', 'avg_tp_mean', 'avg_tp_ema']],
        on='time_key',
        how='left',
    )


def filter_overlay_by_density(overlay_df, *, min_count: int | None = None, min_confidence: float | None = None):
    """Return a filtered copy of overlay_df using sample-count based criteria.

    - min_count: keep rows with counter_tp >= min_count
    - min_confidence: keep rows with counter_tp / max(counter_tp) >= min_confidence

    If neither threshold is provided, returns overlay_df unchanged. Non-destructive.
    """
    if pd is None:  # pragma: no cover
        raise RuntimeError("pandas not available")
    if overlay_df is None or overlay_df.empty:
        return overlay_df
    df = overlay_df.copy()
    try:
        if 'counter_tp' not in df.columns:
            return df
        mask = pd.Series([True] * len(df))
        if isinstance(min_count, int) and min_count > 0:
            mask = mask & (df['counter_tp'].fillna(0) >= int(min_count))
        if isinstance(min_confidence, (int, float)) and float(min_confidence) > 0:
            max_c = float(df['counter_tp'].max()) if 'counter_tp' in df.columns else 0.0
            if max_c > 0:
                conf = df['counter_tp'].fillna(0) / max_c
                mask = mask & (conf >= float(min_confidence))
        if mask.all():
            return df
        # Apply mask; keep time_key/timestamp continuity for merge by dropping others
        return df[mask].reset_index(drop=True)
    except Exception:
        return df


def add_traces(fig, merged, title: str, show_deviation: bool, *, row: Optional[int] = None, col: Optional[int] = None):
    """Add live/overlay traces into a figure; supports subplot row/col or single figure."""
    if go is None:  # pragma: no cover
        raise RuntimeError("plotly not available")
    kwargs = {}
    if row is not None and col is not None:
        kwargs = {"row": row, "col": col}
    if merged.empty:
        if row is not None and col is not None:
            fig.add_annotation(text=f"No data: {title}", row=row, col=col, showarrow=False)
        else:
            fig.add_annotation(text=f"No data: {title}", xref='paper', yref='paper', x=0.5, y=0.5, showarrow=False)
        return
    x = merged['timestamp']
    fig.add_trace(go.Scatter(x=x, y=merged['tp_live'], name=f"{title} tp live", line=dict(color=BLUE, width=2)), **kwargs)
    fig.add_trace(go.Scatter(x=x, y=merged['tp_mean'], name=f"{title} tp mean", line=dict(color=BLUE, dash='dash')), **kwargs)
    fig.add_trace(go.Scatter(x=x, y=merged['tp_ema'], name=f"{title} tp ema", line=dict(color=BLUE, dash='dot')), **kwargs)
    fig.add_trace(go.Scatter(x=x, y=merged['avg_tp_live'], name=f"{title} avg_tp live", line=dict(color=ORANGE, width=2)), **kwargs)
    fig.add_trace(go.Scatter(x=x, y=merged['avg_tp_mean'], name=f"{title} avg_tp mean", line=dict(color=ORANGE, dash='dash')), **kwargs)
    fig.add_trace(go.Scatter(x=x, y=merged['avg_tp_ema'], name=f"{title} avg_tp ema", line=dict(color=ORANGE, dash='dot')), **kwargs)
    if show_deviation and 'tp_mean' in merged and 'tp_live' in merged:
        dev = merged['tp_live'] - merged['tp_mean']
        fig.add_trace(go.Scatter(x=x, y=dev, name=f"{title} dev(tp-live-mean)", line=dict(color='rgba(31,119,180,0.3)', dash='solid')), **kwargs)


def calculate_z_score(df, value_col: str, mean_col: str, std_col: str | None = None):
    """Return a Series with z-score of value_col against mean_col/std.

    If std_col not provided, estimate std via rolling window based on available EMA effective window length.
    Returns None if insufficient data.
    """
    if pd is None:  # pragma: no cover
        raise RuntimeError("pandas not available")
    if df is None or df.empty:
        return None
    if std_col and std_col in df.columns:
        std = df[std_col].replace(0, pd.NA)
    else:
        # Estimate std with a modest rolling window; default 30 buckets
        try:
            std = (df[value_col] - df[mean_col]).rolling(window=30, min_periods=5).std()
        except Exception:
            return None
    try:
        z = (df[value_col] - df[mean_col]) / std
        return z.replace([pd.NA, pd.NaT], None)
    except Exception:
        return None


def add_volatility_bands(fig, x, mean_series, std_series, *, k: float = 2.0, name_prefix: str = ""):
    """Add simple mean ± k*std bands as filled region. Safe no-op if inputs invalid."""
    if go is None:  # pragma: no cover
        raise RuntimeError("plotly not available")
    try:
        upper = mean_series + (k * std_series)
        lower = mean_series - (k * std_series)
        fig.add_trace(go.Scatter(x=x, y=upper, name=f"{name_prefix} +{k}σ", line=dict(color=GREEN, width=1), mode='lines', showlegend=True))
        fig.add_trace(go.Scatter(x=x, y=lower, name=f"{name_prefix} -{k}σ", line=dict(color=GREEN, width=1), mode='lines', fill='tonexty', fillcolor='rgba(44,160,44,0.12)', showlegend=True))
    except Exception:
        return


def load_config_json(path: str | None) -> dict:
    if not path:
        return {}
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"[WARN] Could not load JSON config {path}: {e}")
        return {}


def effective_window(alpha: float) -> float:
    if alpha <= 0 or alpha > 1:
        return float('nan')
    return (2 / alpha) - 1


# Time helpers for UTC metadata stamps
try:
    from src.utils.timeutils import ensure_utc_helpers  # type: ignore
    utc_now, isoformat_z = ensure_utc_helpers()  # type: ignore
except Exception:  # pragma: no cover - fallback only
    from datetime import datetime, timezone

    def utc_now():  # type: ignore
        return datetime.now(timezone.utc)

    def isoformat_z(ts):  # type: ignore
        try:
            return ts.isoformat().replace('+00:00', 'Z')
        except Exception:
            return str(ts)


def annotate_alpha(fig, alpha: float, weekday_name: str, trade_date):
    """Add EMA alpha/effective window annotation and embed metadata into layout meta."""
    if go is None:  # pragma: no cover
        raise RuntimeError("plotly not available")
    eff = effective_window(alpha)
    fig.add_annotation(
        text=f"EMA α={alpha:.3g} (eff≈{eff:.2f} buckets) | {weekday_name} {trade_date}",
        xref='paper', yref='paper', x=0.01, y=0.99, showarrow=False,
        font=dict(size=11, color='#444'), align='left', bgcolor='rgba(255,255,255,0.6)'
    )
    meta = fig.layout.meta or {}
    meta.update({
        'ema': {
            'alpha': alpha,
            'effective_window_buckets': eff,
            'generated_utc': isoformat_z(utc_now()),
        }
    })
    fig.update_layout(meta=meta)


# Static export handling (debounced warnings)
_STATIC_EXPORT_AVAILABLE = True
_STATIC_EXPORT_WARNED = False


def export_figure_image(fig, path: Path, label: str) -> None:
    global _STATIC_EXPORT_AVAILABLE, _STATIC_EXPORT_WARNED
    if not _STATIC_EXPORT_AVAILABLE:
        return
    try:
        fig.write_image(str(path))
    except Exception as e:  # pragma: no cover - environment-dependent
        if not _STATIC_EXPORT_WARNED:
            print(f"[WARN] static export disabled after failure on {label}: {e}")
            print("[INFO] Install 'kaleido' (pip install kaleido) to enable PNG export.")
            _STATIC_EXPORT_WARNED = True
        _STATIC_EXPORT_AVAILABLE = False
        try:
            if path.exists():
                path.unlink()
        except Exception:
            pass
