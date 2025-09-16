#!/usr/bin/env python3
"""plot_weekday_overlays.py

Generate interactive Plotly HTML showing live vs weekday overlays (mean + EMA) for one or more
(index, expiry_tag, offset) combinations on a single page.

Features:
- Six lines per key in a single unified figure (subplot per index, shared x):
    tp_live (solid blue)
    tp_mean (dashed blue)
    tp_ema (dotted blue)
    avg_tp_live (solid orange)
    avg_tp_mean (dashed orange)
    avg_tp_ema (dotted orange)
- Gaps left where overlay history missing (no forward fill)
- Toggleable legend (click to isolate curves)
- Optional deviation shaded region (tp_live - tp_mean) via --deviation
- Filter via CLI: --index, --expiry-tag, --offset (repeatable)
- Automatically picks current weekday master file set.

Usage:
  python scripts/plot_weekday_overlays.py --live-root data/g6_data \
      --weekday-root data/weekday_master --index NIFTY --expiry-tag this_week --offset ATM \
      --date 2025-09-14 --output overlays.html

Multiple indices:
  python scripts/plot_weekday_overlays.py --index NIFTY --index BANKNIFTY --expiry-tag this_week --offset ATM

Dependencies: plotly, pandas
"""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
from datetime import datetime, date
from typing import TYPE_CHECKING
from src.utils.bootstrap import bootstrap

try:
    # Bootstrap (enable_metrics False to avoid starting server for a plotting script)
    bootstrap(enable_metrics=False, log_level="WARNING")
    import pandas as pd  # type: ignore
    import plotly.graph_objects as go  # type: ignore
    import plotly.subplots as sp  # type: ignore
except ImportError as e:  # Hard requirement for this script
    raise SystemExit("Missing dependency. Install with: pip install pandas plotly kaleido") from e

if TYPE_CHECKING:  # hinting only
    import pandas as pd  # noqa: F401
    import plotly.graph_objects as go  # noqa: F401
    import plotly.subplots as sp  # noqa: F401
from typing import Optional

# Global flags for static export handling
_STATIC_EXPORT_AVAILABLE = True
_STATIC_EXPORT_WARNED = False

def _export_figure_image(fig, path: Path, label: str):
    """Attempt static export with debounced warnings.

    If kaleido (plotly image export engine) is not installed or another
    recoverable error occurs, we emit *one* warning and mark exports disabled
    for the remainder of this run. Subsequent export attempts become no-ops.
    """
    global _STATIC_EXPORT_AVAILABLE, _STATIC_EXPORT_WARNED
    if not _STATIC_EXPORT_AVAILABLE:
        return
    try:
        fig.write_image(str(path))
    except Exception as e:  # broad: plotly raises ValueError/ImportError variants
        if not _STATIC_EXPORT_WARNED:
            print(f"[WARN] static export disabled after failure on {label}: {e}")
            print("[INFO] Install 'kaleido' (pip install kaleido) to enable PNG export.")
            _STATIC_EXPORT_WARNED = True
        _STATIC_EXPORT_AVAILABLE = False
        # Optionally cleanup partial file
        try:
            if path.exists():
                path.unlink()
        except Exception:
            pass

WEEKDAY_NAMES = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]

BLUE = "#1f77b4"  # consistent palette
ORANGE = "#ff7f0e"


def load_live_series(live_root: Path, index: str, expiry_tag: str, offset: str, trade_date: date):
    """Load live series CSV for given parameters, returning a DataFrame (may be empty)."""
    daily_file = live_root / index / expiry_tag / offset / f"{trade_date:%Y-%m-%d}.csv"
    if not daily_file.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(daily_file)
    except Exception:
        return pd.DataFrame()
    if df.empty:
        return df
    if 'timestamp' not in df.columns:
        return pd.DataFrame()
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    # derive tp, avg_tp if present columns exist
    for c in ['ce','pe','avg_ce','avg_pe']:
        if c not in df.columns:
            df[c] = 0.0
    df['tp_live'] = df['ce'].fillna(0) + df['pe'].fillna(0)
    df['avg_tp_live'] = df['avg_ce'].fillna(0) + df['avg_pe'].fillna(0)
    df['time_key'] = df['timestamp'].dt.strftime('%H:%M:%S')
    return df


def load_overlay_series(weekday_root: Path, weekday_name: str, index: str, expiry_tag: str, offset: str):
    """Load overlay (weekday master) DataFrame for index/expiry/offset."""
    f = weekday_root / weekday_name / f"{index}_{expiry_tag}_{offset}.csv"
    if not f.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(f)
    except Exception:
        return pd.DataFrame()
    if df.empty:
        return df
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['time_key'] = df['timestamp'].dt.strftime('%H:%M:%S')
    # Ensure expected columns exist (backward compatibility)
    for col in ['tp_mean','tp_ema','avg_tp_mean','avg_tp_ema']:
        if col not in df.columns:
            df[col] = None
    return df


def build_merged(live_df: pd.DataFrame, overlay_df: pd.DataFrame) -> pd.DataFrame:
    if live_df.empty:
        return pd.DataFrame()
    return live_df.merge(
        overlay_df[['time_key','tp_mean','tp_ema','avg_tp_mean','avg_tp_ema']],
        on='time_key', how='left'
    )


def add_traces(fig, merged: pd.DataFrame, title: str, show_deviation: bool, row: Optional[int]=None, col: Optional[int]=None):
    """Add traces to a subplot figure (if row/col given) or a standalone figure."""
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


def _load_config_json(path: str):
    if not path:
        return {}
    try:
        with open(path,'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"[WARN] Could not load JSON config {path}: {e}")
        return {}

def _effective_window(alpha: float) -> float:
    if alpha <= 0 or alpha > 1:
        return float('nan')
    return (2/alpha) - 1

def _annotate_alpha(fig, alpha: float, weekday_name: str, trade_date: date):
    eff = _effective_window(alpha)
    fig.add_annotation(
        text=f"EMA α={alpha:.3g} (eff≈{eff:.2f} buckets) | {weekday_name} {trade_date}",
        xref='paper', yref='paper', x=0.01, y=0.99, showarrow=False,
        font=dict(size=11, color='#444'), align='left', bgcolor='rgba(255,255,255,0.6)'
    )
    # embed into layout meta
    meta = fig.layout.meta or {}
    meta.update({
        'ema': {
            'alpha': alpha,
            'effective_window_buckets': eff,
            'generated_utc': datetime.utcnow().isoformat()+'Z'
        }
    })
    fig.update_layout(meta=meta)

def main():
    ap = argparse.ArgumentParser(description="Plot weekday overlays (live vs mean & EMA).")
    ap.add_argument('--live-root', default='data/g6_data')
    ap.add_argument('--weekday-root', default='data/weekday_master')
    ap.add_argument('--date', help='Trade date (YYYY-MM-DD), default today')
    ap.add_argument('--index', action='append', help='Index symbol(s)')
    ap.add_argument('--expiry-tag', action='append', help='Expiry tag(s) like this_week,next_week,this_month')
    ap.add_argument('--offset', action='append', help='Offset(s) e.g. ATM')
    ap.add_argument('--output', default='weekday_overlays.html', help='Output HTML file')
    ap.add_argument('--deviation', action='store_true', help='Include tp deviation trace (live - mean)')
    ap.add_argument('--config-json', help='Path to JSON config controlling indices, expiry_tags, offsets, layout, etc.')
    ap.add_argument('--layout', choices=['by-index','grid','tabs','split'], default=None, help='Layout strategy override')
    ap.add_argument('--alpha', type=float, help='EMA alpha (used only for annotation / meta; data already computed in CSV)')
    ap.add_argument('--static-dir', help='If provided, export PNG images (requires kaleido) into this directory.')
    args = ap.parse_args()
    cfg = _load_config_json(args.config_json)
    # Resolve primitives with precedence: CLI > JSON > defaults
    trade_date_str = args.date or cfg.get('date')
    trade_date = datetime.strptime(trade_date_str, '%Y-%m-%d').date() if trade_date_str else date.today()
    weekday_name = WEEKDAY_NAMES[trade_date.weekday()]
    indices = args.index or cfg.get('indices') or ['NIFTY']
    expiry_tags = args.expiry_tag or cfg.get('expiry_tags') or ['this_week']
    offsets = args.offset or cfg.get('offsets') or ['ATM']
    layout_mode = args.layout or cfg.get('layout') or 'by-index'
    show_deviation = args.deviation or cfg.get('show_deviation', False)
    max_columns = cfg.get('max_columns', 3)
    panel_cfg = cfg.get('panel', {})
    height_per_panel = panel_cfg.get('height_per_panel', 320)
    alpha_ann = cfg.get('alpha_annotation', True)
    alpha_val = args.alpha if args.alpha is not None else cfg.get('alpha', 0.5)
    if layout_mode not in {'by-index','grid','tabs','split'}:
        layout_mode = 'by-index'

    # Build combinations; each index gets its own grouping
    combos = []
    for idx in indices:
        for exp in expiry_tags:
            for off in offsets:
                combos.append((idx, exp, off))
    live_root = Path(args.live_root)
    weekday_root = Path(args.weekday_root)

    if layout_mode == 'by-index':
        index_groups = {}
        for idx, exp, off in combos:
            index_groups.setdefault(idx, []).append((exp, off))
        fig = sp.make_subplots(rows=len(index_groups), cols=1, shared_xaxes=True, vertical_spacing=0.02, subplot_titles=list(index_groups.keys()))
        row_i = 1
        for idx, pairs in index_groups.items():
            for exp, off in pairs:
                live_df = load_live_series(live_root, idx, exp, off, trade_date)
                overlay_df = load_overlay_series(weekday_root, weekday_name, idx, exp, off)
                merged = build_merged(live_df, overlay_df)
                title = f"{idx}-{exp}-{off}"
                add_traces(fig, merged, row=row_i, col=1, title=title, show_deviation=show_deviation)
            row_i += 1
        fig.update_layout(
            title=f"Weekday Overlay ({weekday_name}) – {trade_date}",
            hovermode='x unified',
            legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='left', x=0),
            template='plotly_white',
            height=max(400, height_per_panel * len(index_groups))
        )
        if alpha_ann:
            _annotate_alpha(fig, alpha_val, weekday_name, trade_date)
        html = fig.to_html(include_plotlyjs='cdn', full_html=False)
        html_body = f"<h2>Weekday Overlays ({weekday_name})</h2>" + html
        # wrap minimal template
        final_html = f"""<html><head><meta charset='utf-8'><title>Weekday Overlays</title></head><body>{html_body}</body></html>"""
        Path(args.output).write_text(final_html, encoding='utf-8')
        if args.static_dir:
            outdir = Path(args.static_dir); outdir.mkdir(parents=True, exist_ok=True)
            _export_figure_image(fig, outdir / 'by_index.png', 'by-index')
    else:
        # grid / tabs / split placeholder simplified initial version (grid rendering only for now)
        panels = []
        for idx, exp, off in combos:
            live_df = load_live_series(live_root, idx, exp, off, trade_date)
            overlay_df = load_overlay_series(weekday_root, weekday_name, idx, exp, off)
            merged = build_merged(live_df, overlay_df)
            fig_one = go.Figure()
            add_traces(fig_one, merged, title=f"{idx}-{exp}-{off}", show_deviation=show_deviation)
            fig_one.update_layout(
                margin=dict(l=40,r=10,t=40,b=40),
                height=height_per_panel,
                title=f"{idx} | {exp} | {off}",
                hovermode='x unified',
                template='plotly_white'
            )
            if alpha_ann:
                _annotate_alpha(fig_one, alpha_val, weekday_name, trade_date)
            div_html = fig_one.to_html(include_plotlyjs=False, full_html=False, div_id=f"panel-{idx}-{exp}-{off}")
            panels.append((idx, exp, off, div_html, fig_one))
        # Build filters UI
        unique_exp = sorted(set(e for _, e, _ in combos))
        unique_off = sorted(set(o for _, _, o in combos))
        filter_ui = ["<section id='filters'><strong>Filters:</strong>"]
        filter_ui.append("<div>Expiry Tags:" + ''.join([f"<label><input type='checkbox' class='f-exp' value='{e}' checked> {e}</label>" for e in unique_exp]) + "</div>")
        filter_ui.append("<div>Offsets:" + ''.join([f"<label><input type='checkbox' class='f-off' value='{o}' checked> {o}</label>" for o in unique_off]) + "</div>")
        filter_ui.append("<a href='#' id='all-on'>All On</a> | <a href='#' id='all-off'>All Off</a>")
        filter_ui.append("</section>")
        grid_css = f"""
<style>
body {{ font-family: Arial, sans-serif; }}
#filters label {{ margin-right: 12px; font-size: 13px; }}
.panel-grid {{ display: grid; grid-template-columns: repeat({max_columns}, 1fr); grid-gap: 16px; }}
.panel {{ border:1px solid #ddd; padding:4px; border-radius:4px; background:#fff; }}
.panel h3 {{ font-size:14px; margin:4px 0 6px; font-weight:600; }}
</style>
"""
        script = """
<script>
function applyFilters(){
  const expSel=[...document.querySelectorAll('.f-exp:checked')].map(c=>c.value);
  const offSel=[...document.querySelectorAll('.f-off:checked')].map(c=>c.value);
  document.querySelectorAll('.panel').forEach(p=>{
    const e=p.getAttribute('data-exp');
    const o=p.getAttribute('data-off');
    if(expSel.includes(e) && offSel.includes(o)) { p.style.display='block'; } else { p.style.display='none'; }
  });
}
document.querySelectorAll('.f-exp,.f-off').forEach(cb=>cb.addEventListener('change',applyFilters));
document.getElementById('all-on').addEventListener('click',e=>{e.preventDefault();document.querySelectorAll('.f-exp,.f-off').forEach(c=>c.checked=true);applyFilters();});
document.getElementById('all-off').addEventListener('click',e=>{e.preventDefault();document.querySelectorAll('.f-exp,.f-off').forEach(c=>c.checked=false);applyFilters();});
</script>
"""
        panel_divs = []
        for idx, exp, off, div_html, fig_ref in panels:
            panel_divs.append(f"<div class='panel' data-exp='{exp}' data-off='{off}'>{div_html}</div>")
        container = "<div class='panel-grid'>" + ''.join(panel_divs) + "</div>"
        html_full = f"<html><head><meta charset='utf-8'><title>Weekday Overlays</title>{grid_css}</head><body><h2>Weekday Overlays ({weekday_name}) – {trade_date}</h2>{''.join(filter_ui)}{container}<script src='https://cdn.plot.ly/plotly-latest.min.js'></script>{script}</body></html>"
        Path(args.output).write_text(html_full, encoding='utf-8')
        # static export per panel if requested
        if args.static_dir:
            outdir = Path(args.static_dir); outdir.mkdir(parents=True, exist_ok=True)
            for idx, exp, off, _div, fig_obj in panels:
                fname = f"{idx}_{exp}_{off}.png".replace('|','_')
                _export_figure_image(fig_obj, outdir / fname, fname)
        # sidecar metadata
        meta = {
            'layout_mode': layout_mode,
            'weekday': weekday_name,
            'trade_date': str(trade_date),
            'alpha': alpha_val,
            'effective_window_buckets': _effective_window(alpha_val),
            'panel_count': len(panels),
            'indices': indices,
            'expiry_tags': expiry_tags,
            'offsets': offsets
        }
        try:
            (Path(args.output).parent / 'weekday_overlays_meta.json').write_text(json.dumps(meta, indent=2), encoding='utf-8')
        except Exception as e:
            print(f"[WARN] could not write sidecar meta: {e}")
    print(f"[OK] wrote {args.output} (layout={layout_mode})")

if __name__ == '__main__':
    main()
