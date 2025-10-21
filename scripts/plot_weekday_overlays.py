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
    --weekday-root data/weekday_master --index NIFTY --expiry-tag this_week --offset 0 \
      --date 2025-09-14 --output overlays.html

Multiple indices:
    python scripts/plot_weekday_overlays.py --index NIFTY --index BANKNIFTY --expiry-tag this_week --offset 0

Dependencies: plotly, pandas
"""
from __future__ import annotations

import argparse
import json

# Ensure repository root is on sys.path when running as a script
import sys
from datetime import date, datetime
from pathlib import Path
from pathlib import Path as _Path
from typing import TYPE_CHECKING

_ROOT = _Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


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

from src.utils.assets import get_plotly_js_src
from src.utils.overlay_plotting import (
    add_traces,
    add_volatility_bands,
    annotate_alpha,
    build_merged,
    calculate_z_score,
    effective_window,
    env_int,
    export_figure_image,
    filter_overlay_by_density,
    load_config_json,
    load_live_series,
    load_overlay_series,
    monitor_memory,
    proc_mem_mb,
)

WEEKDAY_NAMES = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]

# colors centralized in overlay_plotting

# Memory management defaults (overridable via CLI/env)
DEFAULT_VIS_MEMORY_LIMIT_MB = 768
DEFAULT_PLOT_CHUNK_SIZE = 5000

_env_int = env_int
_proc_mem_mb = proc_mem_mb
_monitor_memory = monitor_memory


_load_config_json = load_config_json
_annotate_alpha = annotate_alpha
_effective_window = effective_window

def main() -> None:
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
    # Optional live updates and theming
    ap.add_argument('--live-endpoint', help='HTTP endpoint returning JSON to drive live updates (optional).')
    ap.add_argument('--live-interval-ms', type=int, default=5000, help='Polling interval for live updates in ms (default 5000).')
    ap.add_argument('--theme', choices=['light','dark'], help='Page theme (light/dark). Defaults to light or last saved.')
    # Optional statistical helpers (computed client-side if enabled)
    ap.add_argument('--enable-zscore', action='store_true', help='Render z-score panel below each chart (beta).')
    ap.add_argument('--enable-bands', action='store_true', help='Add simple volatility bands around mean (beta).')
    ap.add_argument('--bands-multiplier', type=float, default=2.0, help='Stddev multiplier for bands if enabled (default 2.0).')
    # Data quality / density filters (optional)
    ap.add_argument('--min-count', type=int, help='Minimum sample count (counter_tp) to include overlay rows')
    ap.add_argument('--min-confidence', type=float, help='Minimum relative confidence (counter_tp / max counter) in [0,1]')
    # Memory tuning (optional)
    ap.add_argument('--memory-limit', type=int, help=f'Memory limit in MB (default env G6_OVERLAY_VIS_MEMORY_LIMIT_MB or {DEFAULT_VIS_MEMORY_LIMIT_MB})')
    ap.add_argument('--chunk-size', type=int, help=f'Chunk size for reading large CSVs (default env G6_OVERLAY_VIS_CHUNK_SIZE or {DEFAULT_PLOT_CHUNK_SIZE})')
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
    # Density filters
    min_count = args.min_count if args.min_count is not None else cfg.get('min_count')
    min_conf = args.min_confidence if args.min_confidence is not None else cfg.get('min_confidence')
    if layout_mode not in {'by-index','grid','tabs','split'}:
        layout_mode = 'by-index'

    # Resolve memory parameters
    mem_limit_mb = args.memory_limit or _env_int('G6_OVERLAY_VIS_MEMORY_LIMIT_MB', DEFAULT_VIS_MEMORY_LIMIT_MB)
    chunk_size = args.chunk_size or _env_int('G6_OVERLAY_VIS_CHUNK_SIZE', DEFAULT_PLOT_CHUNK_SIZE)
    start_mem = _proc_mem_mb()
    if start_mem > 0:
        print(f"[INFO] Starting memory usage: {start_mem:.1f}MB; chunk_size={chunk_size}; limit={mem_limit_mb}MB")

    # Build combinations; each index gets its own grouping
    combos = []
    for idx in indices:
        for exp in expiry_tags:
            for off in offsets:
                combos.append((idx, exp, off))
    live_root = Path(args.live_root)
    weekday_root = Path(args.weekday_root)

    # Client-side config JSON for live/theme
    client_cfg = {
        'live': {
            'endpoint': args.live_endpoint or cfg.get('live_endpoint'),
            'intervalMs': int(args.live_interval_ms or cfg.get('live_interval_ms', 5000)),
        },
        'theme': args.theme or cfg.get('theme'),
    }

    # Asset tags
    theme_css_tag = "<link rel='stylesheet' href='src/assets/css/overlay_themes.css'>"
    updates_js_tag = "<script src='src/assets/js/overlay_live_updates.js'></script>"
    plotly_tag = f"<script src='{get_plotly_js_src()}'></script>"

    page_title = f"Weekday Overlays ({weekday_name}) – {trade_date}"
    header_controls = f"<div class='header'><div class='title'>{page_title}</div><div class='controls'><button id='g6-theme-toggle' class='theme-toggle'>Toggle theme</button></div></div>"

    if layout_mode == 'by-index':
        index_groups: dict[str, list[tuple[str, str]]] = {}
        for idx, exp, off in combos:
            index_groups.setdefault(idx, []).append((exp, off))
        # Enable secondary y for optional z-score
        specs = [[{"secondary_y": True}] for _ in range(len(index_groups))]
        fig = sp.make_subplots(rows=len(index_groups), cols=1, shared_xaxes=True, vertical_spacing=0.02, subplot_titles=list(index_groups.keys()), specs=specs)
        row_i = 1
        for idx, pairs in index_groups.items():
            for exp, off in pairs:
                live_df = load_live_series(live_root, idx, exp, off, trade_date, chunk_size=chunk_size, mem_limit_mb=mem_limit_mb)
                overlay_df = load_overlay_series(weekday_root, weekday_name, idx, exp, off, chunk_size=chunk_size, mem_limit_mb=mem_limit_mb)
                overlay_df = filter_overlay_by_density(overlay_df, min_count=min_count, min_confidence=min_conf)
                merged = build_merged(live_df, overlay_df)
                title = f"{idx}-{exp}-{off}"
                add_traces(fig, merged, row=row_i, col=1, title=title, show_deviation=show_deviation)
                # Optional volatility bands around tp_mean
                if args.enable_bands and not merged.empty and 'tp_mean' in merged:
                    try:
                        dev_std = (merged['tp_live'] - merged['tp_mean']).rolling(window=30, min_periods=5).std()
                        add_volatility_bands(fig, merged['timestamp'], merged['tp_mean'], dev_std, k=float(args.bands_multiplier), name_prefix=f"{title} tp")
                    except Exception:
                        pass
                # Optional z-score on secondary y-axis
                if args.enable_zscore and not merged.empty:
                    try:
                        z = calculate_z_score(merged, 'tp_live', 'tp_mean')
                        if z is not None:
                            fig.add_trace(go.Scatter(x=merged['timestamp'], y=z, name=f"{title} z(tp vs mean)", line=dict(color='#2ca02c', dash='dash')), row=row_i, col=1, secondary_y=True)
                    except Exception:
                        pass
            _monitor_memory(f"subplot_row_{idx}", mem_limit_mb)
            row_i += 1
        fig.update_layout(
            title=f"Weekday Overlay ({weekday_name}) – {trade_date}",
            hovermode='x unified',
            legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='left', x=0),
            template='plotly_white',
            height=max(400, height_per_panel * len(index_groups))
        )
        if args.enable_zscore:
            fig.update_yaxes(title_text="z-score", secondary_y=True)
        if alpha_ann:
            _annotate_alpha(fig, alpha_val, weekday_name, trade_date)
        # Always exclude plotly bundle and add a script tag explicitly using resolver
        html = fig.to_html(include_plotlyjs=False, full_html=False)
        html_body = header_controls + html
        # wrap minimal template
        # Force default theme to dark unless overridden by cfg
        if not client_cfg.get('theme'):
            client_cfg['theme'] = 'dark'
        cfg_script = f"<script>window.G6 = window.G6 || {{}}; window.G6.overlay = window.G6.overlay || {{}}; window.G6.overlay.cfg = {json.dumps(client_cfg)};</script>"
        boot_script = """
<script>
document.addEventListener('DOMContentLoaded', function(){
    try{ if(window.G6 && G6.overlay){ G6.overlay.initTheme((G6.overlay.cfg && G6.overlay.cfg.theme) || 'dark'); } }catch(_){ }
    try{
        const btn = document.getElementById('g6-theme-toggle');
        if(btn && window.G6 && G6.overlay){ btn.addEventListener('click', function(){
            const root = document.documentElement; const isDark = root.getAttribute('data-theme')==='dark';
            G6.overlay.setTheme(isDark ? 'light' : 'dark');
        }); }
        // register the unified figure div if present
        const div = document.querySelector('.plotly-graph-div');
        if(div && div.id){ G6.overlay.registerGraph(div.id, { layout: 'by-index' }); }
        if(G6.overlay && G6.overlay.cfg && G6.overlay.cfg.live){ G6.overlay.startPolling(G6.overlay.cfg.live); }
    }catch(_){ }
});
</script>
"""
        final_html = f"""
<html>
    <head>
        <meta charset='utf-8'>
        <title>Weekday Overlays</title>
        {theme_css_tag}
    </head>
    <body>
        {plotly_tag}
        {updates_js_tag}
        {cfg_script}
        {html_body}
        {boot_script}
    </body>
</html>
"""
        Path(args.output).write_text(final_html, encoding='utf-8')
        if args.static_dir:
            outdir = Path(args.static_dir); outdir.mkdir(parents=True, exist_ok=True)
            export_figure_image(fig, outdir / 'by_index.png', 'by-index')
    else:
        # Non by-index modes
        panels = []
        for idx, exp, off in combos:
            live_df = load_live_series(live_root, idx, exp, off, trade_date, chunk_size=chunk_size, mem_limit_mb=mem_limit_mb)
            overlay_df = load_overlay_series(weekday_root, weekday_name, idx, exp, off, chunk_size=chunk_size, mem_limit_mb=mem_limit_mb)
            overlay_df = filter_overlay_by_density(overlay_df, min_count=min_count, min_confidence=min_conf)
            merged = build_merged(live_df, overlay_df)
            fig_one = go.Figure()
            add_traces(fig_one, merged, title=f"{idx}-{exp}-{off}", show_deviation=show_deviation)
            # Optional bands
            if args.enable_bands and not merged.empty and 'tp_mean' in merged:
                try:
                    dev_std = (merged['tp_live'] - merged['tp_mean']).rolling(window=30, min_periods=5).std()
                    add_volatility_bands(fig_one, merged['timestamp'], merged['tp_mean'], dev_std, k=float(args.bands_multiplier), name_prefix=f"{idx}-{exp}-{off} tp")
                except Exception:
                    pass
            # Optional z-score on y2
            if args.enable_zscore and not merged.empty:
                try:
                    z = calculate_z_score(merged, 'tp_live', 'tp_mean')
                    if z is not None:
                        fig_one.add_trace(go.Scatter(x=merged['timestamp'], y=z, name=f"{idx}-{exp}-{off} z(tp vs mean)", line=dict(color='#2ca02c', dash='dash'), yaxis='y2'))
                        fig_one.update_layout(yaxis2=dict(title='z-score', overlaying='y', side='right'))
                except Exception:
                    pass
            fig_one.update_layout(
                margin=dict(l=40, r=10, t=40, b=40),
                height=max(height_per_panel, 520),
                title=f"{idx} | {exp} | {off}",
                hovermode='x unified',
                template='plotly_white'
            )
            if alpha_ann:
                _annotate_alpha(fig_one, alpha_val, weekday_name, trade_date)
            div_id = f"panel-{idx}-{exp}-{off}"
            div_html = fig_one.to_html(include_plotlyjs=False, full_html=False, div_id=div_id)
            panels.append((idx, exp, off, div_id, div_html, fig_one))
            _monitor_memory(f"panel_{idx}_{exp}_{off}", mem_limit_mb)

        if layout_mode == 'grid':
            # Build filters UI
            unique_exp = sorted(set(e for _, e, _ in combos))
            unique_off = sorted(set(o for _, _, o in combos))
            filter_ui = ["<section id='filters'><strong>Filters:</strong>"]
            filter_ui.append("<div>Expiry Tags:" + ''.join([f"<label><input type='checkbox' class='f-exp' value='{e}' checked> {e}</label>" for e in unique_exp]) + "</div>")
            filter_ui.append("<div>Offsets:" + ''.join([f"<label><input type='checkbox' class='f-off' value='{o}' checked> {o}</label>" for o in unique_off]) + "</div>")
            filter_ui.append("<a href='#' id='all-on'>All On</a> | <a href='#' id='all-off'>All Off</a>")
            filter_ui.append("</section>")
            grid_css = """
<style>
body { font-family: Arial, sans-serif; margin:0; }
html, body { width:100%; height:100%; }
#filters { padding:8px 12px; }
#filters label { margin-right: 12px; font-size: 13px; }
.sim-controls { padding: 4px 12px 8px; display:flex; align-items:center; gap:12px; font-size:13px; }
.sim-controls input[type='range'] { width: 260px; }
.sim-controls .tick { font-variant-numeric: tabular-nums; color:#666; }
.panel-grid { display: grid; grid-template-columns: repeat(1, minmax(0, 1fr)); grid-gap: 16px; padding: 8px 12px; }
.panel { border:1px solid #ddd; padding:4px; border-radius:4px; background:#fff; width:100%; }
.panel .plotly-graph-div { width:100% !important; }
.panel h3 { font-size:14px; margin:4px 0 6px; font-weight:600; }
</style>
"""
            # Simulation controls (time scrubber)
            sim_controls = """
<section class='sim-controls'>
    <label><input type='checkbox' id='simulate-live'> Simulate live (reveal over time)</label>
    <input type='range' id='time-scrub' min='0' max='100' step='1' value='100'>
    <span class='tick'>0%</span>
    <span class='tick' style='margin-left:auto'>100%</span>
</section>
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
    // After show/hide, ask Plotly to resize visible graphs to avoid blank renders
    setTimeout(()=>{
        document.querySelectorAll('.panel').forEach(p=>{
            if(p.style.display!=='none'){
                const div=p.querySelector('.plotly-graph-div');
                if(div && window.Plotly && Plotly.Plots){ try{ Plotly.Plots.resize(div); }catch(_){} }
            }
        });
    }, 50);
}
document.querySelectorAll('.f-exp,.f-off').forEach(cb=>cb.addEventListener('change',applyFilters));
document.getElementById('all-on').addEventListener('click',e=>{e.preventDefault();document.querySelectorAll('.f-exp,.f-off').forEach(c=>c.checked=true);applyFilters();});
document.getElementById('all-off').addEventListener('click',e=>{e.preventDefault();document.querySelectorAll('.f-exp,.f-off').forEach(c=>c.checked=false);applyFilters();});

// Time scrubber logic
function applyScrub(){
    const enabled = document.getElementById('simulate-live')?.checked;
    const slider = document.getElementById('time-scrub');
    const pct = slider ? (parseFloat(slider.value)||0) : 100;
    const graphs = document.querySelectorAll('.plotly-graph-div');
    graphs.forEach(div=>{
        try{
            const data = div.data || [];
            if(!data.length) return;
            if(!div._orig){
                // store shallow copies of original arrays
                div._orig = data.map(tr=>({ x: (tr.x||[]).slice(), y: (tr.y||[]).slice() }));
            }
            const orig = div._orig;
            if(!enabled){
                // restore original full series
                orig.forEach((tr,i)=>{ Plotly.restyle(div, { x:[tr.x], y:[tr.y] }, [i]); });
                return;
            }
            const xs = orig[0].x || [];
            if(!xs.length) return;
            const start = new Date(xs[0]).getTime();
            const end = new Date(xs[xs.length-1]).getTime();
            const cutoff = start + (Math.max(0, Math.min(100, pct))/100.0) * (end - start);
            for(let i=0;i<orig.length;i++){
                const xarr = orig[i].x; const yarr = orig[i].y;
                const ynew = yarr.map((yv, idx)=>{
                    const t = new Date(xarr[idx]).getTime();
                    return (t <= cutoff) ? yv : null;
                });
                Plotly.restyle(div, { y:[ynew] }, [i]);
            }
            if(window.Plotly && Plotly.Plots){ try{ Plotly.Plots.resize(div); }catch(_){ } }
        }catch(_){ }
    });
}
document.addEventListener('DOMContentLoaded', function(){
    const slider = document.getElementById('time-scrub');
    const box = document.getElementById('simulate-live');
    if(slider){ slider.addEventListener('input', applyScrub); }
    if(box){ box.addEventListener('change', applyScrub); }
});
</script>
"""
            panel_divs = []
            for idx, exp, off, _div_id, div_html, _fig_ref in panels:
                panel_divs.append(f"<div class='panel' data-exp='{exp}' data-off='{off}'>{div_html}</div>")
            container = "<div class='panel-grid'>" + ''.join(panel_divs) + "</div>"
            if not client_cfg.get('theme'):
                client_cfg['theme'] = 'dark'
            cfg_script = f"<script>window.G6 = window.G6 || {{}}; window.G6.overlay = window.G6.overlay || {{}}; window.G6.overlay.cfg = {json.dumps(client_cfg)};</script>"
            boot = """
<script>
document.addEventListener('DOMContentLoaded', function(){
    try{ if(window.G6 && G6.overlay){ G6.overlay.initTheme((G6.overlay.cfg && G6.overlay.cfg.theme) || 'dark'); } }catch(_){ }
    try{
        document.querySelectorAll('.plotly-graph-div').forEach(div=>{ if(div.id){ G6.overlay.registerGraph(div.id, { layout: 'grid' }); }});
        if(G6.overlay && G6.overlay.cfg && G6.overlay.cfg.live){ G6.overlay.startPolling(G6.overlay.cfg.live); }
        // Apply initial scrub state if any (ensures slider reflects current graph)
        try{ applyScrub(); }catch(_){ }
    }catch(_){ }
});
</script>
"""
            # Important: load Plotly bundle before any inline Plotly.newPlot scripts inside panel divs
            html_full = f"<html><head><meta charset='utf-8'><title>Weekday Overlays</title>{grid_css}{theme_css_tag}</head><body>{plotly_tag}{updates_js_tag}{cfg_script}{header_controls}{''.join(filter_ui)}{sim_controls}{container}{script}{boot}</body></html>"
            Path(args.output).write_text(html_full, encoding='utf-8')
        elif layout_mode == 'tabs':
            # Simple tabs: one panel visible at a time
            tabs_css = """
<style>
body { font-family: Arial, sans-serif; }
.tabs { display: flex; border-bottom: 1px solid #ccc; margin-bottom: 8px; }
.tab { padding: 8px 12px; cursor: pointer; border: 1px solid #ccc; border-bottom: none; margin-right: 6px; border-top-left-radius: 4px; border-top-right-radius: 4px; background:#f7f7f7; }
.tab.active { background: #fff; font-weight: 600; }
.tab-content { border: 1px solid #ccc; border-radius: 0 4px 4px 4px; padding: 6px; background:#fff; }
</style>
"""
            tab_headers = []
            tab_contents = []
            for i, (idx, exp, off, div_id, div_html, _fig) in enumerate(panels):
                tab_id = f"tab-{idx}-{exp}-{off}"
                active_cls = 'active' if i == 0 else ''
                style = '' if i == 0 else 'style=\"display:none\"'
                tab_headers.append(f"<div class='tab {active_cls}' data-target='{div_id}'>{idx} | {exp} | {off}</div>")
                tab_contents.append(f"<div class='tab-content' id='{div_id}' {style}>{div_html}</div>")
            script = """
<script>
document.addEventListener('DOMContentLoaded', function(){
  document.querySelectorAll('.tab').forEach(function(tab){
    tab.addEventListener('click', function(){
      document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
      this.classList.add('active');
      const target = this.getAttribute('data-target');
      document.querySelectorAll('.tab-content').forEach(div=>{
        if(div.id === target) { div.style.display='block'; } else { div.style.display='none'; }
      });
    });
  });
});
</script>
"""
            tabs_html = "<div class='tabs'>" + ''.join(tab_headers) + "</div>" + ''.join(tab_contents)
            cfg_script = f"<script>window.G6 = window.G6 || {{}}; window.G6.overlay = window.G6.overlay || {{}}; window.G6.overlay.cfg = {json.dumps(client_cfg)};</script>"
            boot = """
<script>
document.addEventListener('DOMContentLoaded', function(){
    try{ if(window.G6 && G6.overlay){ G6.overlay.initTheme((G6.overlay.cfg && G6.overlay.cfg.theme) || 'light'); } }catch(_){ }
    try{
        document.querySelectorAll('.tab-content .plotly-graph-div').forEach(div=>{ if(div.id){ G6.overlay.registerGraph(div.id, { layout: 'tabs' }); }});
        if(G6.overlay && G6.overlay.cfg && G6.overlay.cfg.live){ G6.overlay.startPolling(G6.overlay.cfg.live); }
    }catch(_){ }
});
</script>
"""
            html_full = f"<html><head><meta charset='utf-8'><title>Weekday Overlays</title>{tabs_css}{theme_css_tag}</head><body>{plotly_tag}{updates_js_tag}{cfg_script}{header_controls}{tabs_html}{script}{boot}</body></html>"
            Path(args.output).write_text(html_full, encoding='utf-8')
        elif layout_mode == 'split':
            # Two-column layout with synchronized x-range among all panels
            split_css = """
<style>
body { font-family: Arial, sans-serif; }
.split-grid { display: grid; grid-template-columns: repeat(2, 1fr); grid-gap: 12px; }
.panel { border:1px solid #ddd; padding:4px; border-radius:4px; background:#fff; }
</style>
"""
            # Build container with div ids
            items = []
            for idx, exp, off, div_id, div_html, _fig in panels:
                items.append(f"<div class='panel' id='wrap-{div_id}'>{div_html}</div>")
            container = "<div class='split-grid'>" + ''.join(items) + "</div>"
            # JS to sync x-range using Plotly relayout events
            sync_js = """
<script>
function syncX(range){
    const ids = Array.from(document.querySelectorAll('.tab-content, .panel .plotly-graph-div')).map(d=>d.id).filter(Boolean);
}
document.addEventListener('DOMContentLoaded', function(){
    const graphs = document.querySelectorAll('.plotly-graph-div');
    let isSyncing = false;
    graphs.forEach(g=>{
        g.on('plotly_relayout', ev=>{
            if(isSyncing) return;
            if(ev['xaxis.range[0]'] && ev['xaxis.range[1]']){
                isSyncing = true;
                const update = { 'xaxis.range': [ev['xaxis.range[0]'], ev['xaxis.range[1]']] };
                graphs.forEach(other=>{ if(other!==g){ Plotly.relayout(other, update); }});
                isSyncing = false;
            }
        });
    });
});
</script>
"""
            cfg_script = f"<script>window.G6 = window.G6 || {{}}; window.G6.overlay = window.G6.overlay || {{}}; window.G6.overlay.cfg = {json.dumps(client_cfg)};</script>"
            boot = """
<script>
document.addEventListener('DOMContentLoaded', function(){
    try{ if(window.G6 && G6.overlay){ G6.overlay.initTheme((G6.overlay.cfg && G6.overlay.cfg.theme) || 'light'); } }catch(_){ }
    try{
        document.querySelectorAll('.split-grid .plotly-graph-div').forEach(div=>{ if(div.id){ G6.overlay.registerGraph(div.id, { layout: 'split' }); }});
        if(G6.overlay && G6.overlay.cfg && G6.overlay.cfg.live){ G6.overlay.startPolling(G6.overlay.cfg.live); }
    }catch(_){ }
});
</script>
"""
            html_full = f"<html><head><meta charset='utf-8'><title>Weekday Overlays</title>{split_css}{theme_css_tag}</head><body>{plotly_tag}{updates_js_tag}{cfg_script}{header_controls}{container}{sync_js}{boot}</body></html>"
            Path(args.output).write_text(html_full, encoding='utf-8')
        else:
            # Fallback: treat as grid
            panel_divs = []
            for idx, exp, off, _div_id, div_html, _fig_ref in panels:
                panel_divs.append(f"<div class='panel'>{div_html}</div>")
            cfg_script = f"<script>window.G6 = window.G6 || {{}}; window.G6.overlay = window.G6.overlay || {{}}; window.G6.overlay.cfg = {json.dumps(client_cfg)};</script>"
            boot = """
<script>
document.addEventListener('DOMContentLoaded', function(){
    try{ if(window.G6 && G6.overlay){ G6.overlay.initTheme((G6.overlay.cfg && G6.overlay.cfg.theme) || 'light'); } }catch(_){ }
    try{
        document.querySelectorAll('.plotly-graph-div').forEach(div=>{ if(div.id){ G6.overlay.registerGraph(div.id, { layout: 'grid' }); }});
        if(G6.overlay && G6.overlay.cfg && G6.overlay.cfg.live){ G6.overlay.startPolling(G6.overlay.cfg.live); }
    }catch(_){ }
});
</script>
"""
            html_full = f"<html><head><meta charset='utf-8'><title>Weekday Overlays</title>{theme_css_tag}</head><body>{plotly_tag}{updates_js_tag}{cfg_script}{header_controls}{''.join(panel_divs)}{boot}</body></html>"
            Path(args.output).write_text(html_full, encoding='utf-8')

        # static export per panel if requested
        if args.static_dir:
            outdir = Path(args.static_dir)
            outdir.mkdir(parents=True, exist_ok=True)
            for idx, exp, off, _div_id, _div, fig_obj in panels:
                fname = f"{idx}_{exp}_{off}.png".replace('|', '_')
                export_figure_image(fig_obj, outdir / fname, fname)
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
            'offsets': offsets,
        }
        try:
            (Path(args.output).parent / 'weekday_overlays_meta.json').write_text(json.dumps(meta, indent=2), encoding='utf-8')
        except Exception as e:
            print(f"[WARN] could not write sidecar meta: {e}")
    print(f"[OK] wrote {args.output} (layout={layout_mode})")

if __name__ == '__main__':
    main()
