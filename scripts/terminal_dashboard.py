#!/usr/bin/env python3
"""Terminal dashboard for G6 Platform.

Displays key metrics and log tail when Grafana/Prometheus are unavailable.
Designed to degrade gracefully if 'rich' is not installed.

Initial version: includes metrics fetcher & parser + basic plain output fallback.
Subsequent iterations will add rich layout, log panel, thresholds, and color coding.
"""
from __future__ import annotations
import argparse
import time
import re
import sys
import math
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
from pathlib import Path

try:  # optional dependency
    from rich.console import Console  # type: ignore
    from rich.table import Table  # type: ignore
    from rich.panel import Panel  # type: ignore
    from rich.layout import Layout  # type: ignore
    from rich.live import Live  # type: ignore
    from rich.text import Text  # type: ignore
    RICH_AVAILABLE = True
except Exception:  # pragma: no cover - absence path
    Console = Table = Panel = Layout = Live = Text = None  # type: ignore
    RICH_AVAILABLE = False

METRIC_LINE_RE = re.compile(r"^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)\{?(?P<labels>[^}]*)}?\s+(?P<value>[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?\d+)?)")
LABEL_RE = re.compile(r"(\w+)=\"([^\"]*)\"")

@dataclass
class MetricSample:
    value: float
    labels: Dict[str,str] = field(default_factory=dict)

@dataclass
class MetricsSnapshot:
    ts: float
    metrics: Dict[str, List[MetricSample]]

@dataclass
class IndexRollup:
    legs_total: int = 0
    legs_cycles: int = 0
    success_accum: float = 0.0
    success_cycles: int = 0
    last_error: str = ''
    last_error_ts: float = 0.0

class DashboardState:
    def __init__(self):
        self.index: Dict[str, IndexRollup] = defaultdict(IndexRollup)
        self.counter_cache: Dict[Tuple[str, Tuple[Tuple[str,str],...]], float] = {}
        self.consecutive_failures: int = 0
        self.last_fetch_ok: float = 0.0
        self.last_fetch_ms: float = 0.0
        self.attempts: int = 0  # total fetch attempts
        self.last_error: Optional[str] = None
        self.degraded_plain: bool = False

    def diff_counter(self, name: str, sample: MetricSample) -> float:
        key = (name, tuple(sorted(sample.labels.items())))
        prev = self.counter_cache.get(key)
        self.counter_cache[key] = sample.value
        if prev is None:
            return 0.0
        delta = sample.value - prev
        if delta < 0:
            return 0.0
        return delta

class MetricsFetcher:
    def __init__(self, endpoint: str, timeout: float = 1.0):
        self.endpoint = endpoint
        self.timeout = timeout

    def fetch(self) -> MetricsSnapshot:
        ts = time.time()
        with urllib.request.urlopen(self.endpoint, timeout=self.timeout) as resp:
            raw = resp.read().decode('utf-8', errors='replace')
        metrics: Dict[str, List[MetricSample]] = {}
        for line in raw.splitlines():
            if not line or line.startswith('#'):
                continue
            m = METRIC_LINE_RE.match(line)
            if not m:
                continue
            name = m.group('name')
            labels_raw = m.group('labels')
            labels: Dict[str,str] = {}
            if labels_raw:
                for lm in LABEL_RE.finditer(labels_raw):
                    labels[lm.group(1)] = lm.group(2)
            try:
                value = float(m.group('value'))
            except ValueError:
                continue
            metrics.setdefault(name, []).append(MetricSample(value=value, labels=labels))
        return MetricsSnapshot(ts=ts, metrics=metrics)


# ------------------------------ Log Tail ------------------------------
SEVERITY_COLORS = {
    'INFO': 'dim',
    'WARNING': 'yellow',
    'ERROR': 'red',
    'CRITICAL': 'bold red',
    'ANOMALY': 'magenta',
    'DEBUG': 'cyan'
}

LOG_LEVEL_RE = re.compile(r"\b(INFO|WARNING|ERROR|CRITICAL|ANOMALY|DEBUG)\b")

class LogTail:
    """Tail a log file incrementally with basic rotation handling.

    Keeps only the last `max_lines` lines in memory.
    """
    def __init__(self, path: Path, max_lines: int = 200):
        self.path = path
        self.max_lines = max_lines
        self._position = 0
        self._inode = None
        self._buffer: List[str] = []

    def _reset(self):
        self._position = 0
        self._inode = None

    def read_new(self):
        if not self.path.exists():
            return
        try:
            st = self.path.stat()
            inode = getattr(st, 'st_ino', None)
            # Rotation or truncation detection
            if self._inode is not None and inode == self._inode and st.st_size < self._position:
                self._reset()
            self._inode = inode
            with self.path.open('r', encoding='utf-8', errors='replace') as f:
                if self._position:
                    f.seek(self._position)
                for line in f:
                    line = line.rstrip('\n')
                    self._buffer.append(line)
                self._position = f.tell()
            if len(self._buffer) > self.max_lines:
                self._buffer = self._buffer[-self.max_lines:]
        except Exception:
            pass

    def get_lines(self) -> List[str]:
        return list(self._buffer)

# Simple plain renderer (rich version will supersede)

def render_plain(snapshot: MetricsSnapshot, prev: Optional[MetricsSnapshot], *, bars: bool, mem_cap_mb: float):
    lines = []
    ts = time.strftime('%H:%M:%S', time.localtime(snapshot.ts))
    lines.append(f"[{ts}] Metrics scraped: {len(snapshot.metrics)} metric families")
    # Example subset
    base_keys = ['g6_uptime_seconds','g6_collection_cycle_time_seconds','g6_options_processed_per_minute','g6_collection_success_rate_percent']
    for key in base_keys:
        samples = snapshot.metrics.get(key)
        if not samples:
            continue
        # If single sample: show value
        val = samples[0].value if len(samples)==1 else sum(s.value for s in samples)/len(samples)
        lines.append(f"  {key}: {val:.2f}")
    # Bars
    if bars:
        def ascii_bar(val, maxv, width=20):
            if maxv <= 0: return '-'*width
            ratio = max(0.0, min(val/maxv, 1.0))
            fill = int(ratio*width)
            return '#' * fill + '.' * (width-fill)
        cpu = snapshot.metrics.get('g6_cpu_usage_percent',[MetricSample(0.0)])[0].value
        mem = snapshot.metrics.get('g6_memory_usage_mb',[MetricSample(0.0)])[0].value
        api = snapshot.metrics.get('g6_api_response_time_ms',[MetricSample(0.0)])[0].value
        mem_cap = mem_cap_mb if mem_cap_mb>0 else max(mem*1.25,1.0)
        lines.append(f"  cpu: {cpu:5.1f}% [{ascii_bar(cpu,100.0)}]")
        lines.append(f"  mem: {mem:5.1f}MB/{mem_cap:.1f} [{ascii_bar(mem,mem_cap)}]")
        lines.append(f"  api_ms: {api:6.1f} [{ascii_bar(api,500.0)}]")
    return '\n'.join(lines)


def main():
    ap = argparse.ArgumentParser(description='G6 Terminal Dashboard (fallback)')
    ap.add_argument('--endpoint', default='http://localhost:8000', help='Base URL (will append /metrics if missing)')
    ap.add_argument('--refresh', type=float, default=5.0)
    ap.add_argument('--timeout', type=float, default=1.5, help='HTTP timeout in seconds for metrics fetch')
    ap.add_argument('--plain', action='store_true', help='Force plain mode (ignore rich)')
    ap.add_argument('--log', default='g6_platform.log', help='Path to platform log file to tail')
    ap.add_argument('--log-lines', type=int, default=120, help='Maximum log lines to keep in panel')
    ap.add_argument('--stale-warn-mult', type=float, default=2.2, help='Warn if metrics older than refresh*mult')
    ap.add_argument('--max-indices', type=int, default=12, help='Maximum indices to display in streaming table')
    ap.add_argument('--mem-cap-mb', type=float, default=0.0, help='Approx memory cap for process (MB) to scale memory bar (0=auto/disable scaling)')
    ap.add_argument('--no-bars', action='store_true', help='Disable severity bars (show plain numeric values)')
    ap.add_argument('--state-export', help='Path to write JSON state snapshot after each successful fetch')
    ap.add_argument('--no-screen', action='store_true', help='Disable alternate screen mode (prevents blank screen issue on some terminals)')
    ap.add_argument('--simple-loop', action='store_true', help='Bypass Rich Live; print a refreshed snapshot each cycle (reduced flicker risk)')
    ap.add_argument('--force-plain-cycles', action='store_true', help='Force plain ASCII summary each cycle (ignores rich panels)')
    ap.add_argument('--raw', action='store_true', help='Absolute fallback: disable ALL rich features and print plain lines (no screen clearing)')
    args = ap.parse_args()

    # Raw overrides everything
    if args.raw:
        args.plain = True
        args.simple_loop = True
        args.force_plain_cycles = True
    use_rich = RICH_AVAILABLE and not args.plain and not args.raw
    endpoint = args.endpoint.rstrip('/')
    if not re.search(r"/metrics($|\?)", endpoint):
        endpoint = endpoint + '/metrics'
    fetcher = MetricsFetcher(endpoint, timeout=args.timeout)
    prev: Optional[MetricsSnapshot] = None
    log_tail = LogTail(Path(args.log), max_lines=args.log_lines)
    state = DashboardState()

    if not use_rich:
        try:
            while True:
                try:
                    fetch_start = time.time()
                    state.attempts += 1
                    snap = fetcher.fetch()
                    state.last_fetch_ms = (time.time() - fetch_start) * 1000.0
                    state.consecutive_failures = 0
                    out = render_plain(snap, prev, bars=not args.no_bars, mem_cap_mb=args.mem_cap_mb)
                    prev = snap
                except Exception as e:
                    state.consecutive_failures += 1
                    state.last_error = str(e)
                    state.last_fetch_ms = 0.0
                    out = f"[WARN] metrics fetch failed: {e}"
                log_tail.read_new()
                plain_logs = '\n'.join(log_tail.get_lines()[-10:])
                out = out + "\n--- logs (last 10) ---\n" + plain_logs
                if args.raw:
                    # Do not clear screen, always append time-stamped block
                    print(f"\n==== DASH CYCLE {int(time.time())} attempts={getattr(state,'attempts',0)} failures={getattr(state,'consecutive_failures',0)} ====", flush=True)
                    print(out, flush=True)
                else:
                    print(out)
                time.sleep(args.refresh)
        except KeyboardInterrupt:
            print('\nExiting.')
            return
    else:
        console = Console()  # type: ignore

        if RICH_AVAILABLE:
            # Define helpers only if rich present
            def build_logs_panel(lines: List[str]):  # type: ignore
                from rich.console import Group  # type: ignore
                rendered = []
                for ln in lines[-args.log_lines:]:
                    sev_match = LOG_LEVEL_RE.search(ln)
                    sev = sev_match.group(1) if sev_match else 'INFO'
                    color = SEVERITY_COLORS.get(sev, 'white')
                    rendered.append(Text(ln, style=color))  # type: ignore
                return Panel(Group(*rendered), title=f"Logs (last {min(len(lines), args.log_lines)})", border_style="cyan")  # type: ignore

            def build_metrics_panel(snapshot: Optional[MetricsSnapshot]):  # type: ignore
                if not snapshot:
                    return Panel(Text('No metrics yet'), title='System Metrics')  # type: ignore
                table = Table.grid(padding=1)  # type: ignore
                table.add_column('Metric', style='bold')
                table.add_column('Value')
                def mval(name, default='-'):
                    samples = snapshot.metrics.get(name) if snapshot else None
                    if not samples:
                        return default
                    return f"{samples[0].value:.2f}"
                def make_bar(value: float, max_value: float, thresholds: List[float], width: int = 12) -> str:
                    try:
                        ratio = 0 if max_value <= 0 else min(max(value / max_value, 0), 1)
                    except Exception:
                        ratio = 0
                    filled = int(ratio * width)
                    empty = width - filled
                    color = 'green'
                    if len(thresholds) >= 2:
                        if value >= thresholds[1]:
                            color = 'red'
                        elif value >= thresholds[0]:
                            color = 'yellow'
                    bar = '█'*filled + '░'*empty
                    return f"[{color}]{bar}[/] {value:.1f}"
                cpu = snapshot.metrics.get('g6_cpu_usage_percent',[MetricSample(0.0)])[0].value
                mem = snapshot.metrics.get('g6_memory_usage_mb',[MetricSample(0.0)])[0].value
                api_ms = snapshot.metrics.get('g6_api_response_time_ms',[MetricSample(0.0)])[0].value
                table.add_row('Uptime(s)', mval('g6_uptime_seconds'))
                table.add_row('CycleTime(s)', mval('g6_collection_cycle_time_seconds'))
                table.add_row('Fetch ms', f"{state.last_fetch_ms:.1f}" if state.last_fetch_ms else '-')
                if not args.no_bars:
                    table.add_row('CPU Load', make_bar(cpu, 100.0, [60.0,85.0]))
                    # Memory bar scaling: if no cap provided, adaptively scale to current usage *1.25
                    mem_cap = args.mem_cap_mb if args.mem_cap_mb > 0 else max(mem * 1.25, 1.0)
                    mem_t1 = 0.6 * mem_cap; mem_t2 = 0.85 * mem_cap
                    table.add_row('Memory', make_bar(mem, mem_cap, [mem_t1, mem_t2]))
                    table.add_row('API Latency', make_bar(api_ms, 500.0, [100.0,300.0]))
                else:
                    table.add_row('CPU Load', f"{cpu:.1f}%")
                    mem_cap = args.mem_cap_mb if args.mem_cap_mb > 0 else max(mem * 1.25, 1.0)
                    table.add_row('Memory', f"{mem:.1f}MB ({mem/mem_cap*100:.1f}%)")
                    table.add_row('API Latency', f"{api_ms:.1f} ms")
                table.add_row('Options/min', mval('g6_options_processed_per_minute'))
                table.add_row('Success%', mval('g6_collection_success_rate_percent'))
                table.add_row('API Succ%', mval('g6_api_success_rate_percent'))
                table.add_row('DataQual%', mval('g6_data_quality_score_percent'))
                table.add_row('MemPressLvl', mval('g6_memory_pressure_level'))
                table.add_row('DepthScale', mval('g6_memory_depth_scale'))
                return Panel(table, title='System & Performance', border_style='green')  # type: ignore

            def build_storage_panel(snapshot: Optional[MetricsSnapshot]):  # type: ignore
                if not snapshot:
                    return Panel(Text('No data'), title='Storage')  # type: ignore
                t = Table.grid(padding=1)  # type: ignore
                t.add_column('Metric', style='bold'); t.add_column('Value')
                def mv(n, default='-'):
                    sm = snapshot.metrics.get(n)
                    if not sm:
                        return default
                    return f"{sm[0].value:.2f}"
                t.add_row('CSV Files', mv('g6_csv_files_created_total'))
                t.add_row('CSV Records', mv('g6_csv_records_written_total'))
                t.add_row('CSV Errors', mv('g6_csv_write_errors_total'))
                t.add_row('CSV Disk(MB)', mv('g6_csv_disk_usage_mb'))
                t.add_row('Influx Points', mv('g6_influxdb_points_written_total'))
                t.add_row('Influx Write%', mv('g6_influxdb_write_success_rate_percent'))
                t.add_row('Influx Conn', mv('g6_influxdb_connection_status'))
                t.add_row('Backup TS', mv('g6_last_backup_unixtime'))
                t.add_row('Backup Size(MB)', mv('g6_backup_size_mb'))
                return Panel(t, title='Storage & Backup', border_style='magenta')  # type: ignore

            def build_index_table(snapshot: Optional[MetricsSnapshot]):  # type: ignore
                tbl = Table(show_header=True, header_style='bold cyan', expand=True, pad_edge=False)  # type: ignore
                tbl.add_column('Time', no_wrap=True)
                tbl.add_column('Index', no_wrap=True)
                tbl.add_column('Legs', justify='right')
                tbl.add_column('Success%', justify='right')
                tbl.add_column('Err', no_wrap=True)
                tbl.add_column('Status', no_wrap=True)
                tbl.add_column('Desc')
                if not snapshot:
                    return Panel(tbl, title='Enhanced Rolling Live Data Stream', border_style='yellow')  # type: ignore
                idx_opts = snapshot.metrics.get('g6_index_options_processed', [])
                idx_success = snapshot.metrics.get('g6_index_success_rate_percent', [])
                opts_map = {s.labels.get('index','?'): s.value for s in idx_opts}
                succ_map = {s.labels.get('index','?'): s.value for s in idx_success}
                now_ts = snapshot.ts
                # Update rollups
                for name,val in opts_map.items():
                    roll = state.index[name]
                    roll.legs_total += int(val)
                    roll.legs_cycles += 1
                for name,val in succ_map.items():
                    roll = state.index[name]
                    roll.success_accum += val
                    roll.success_cycles += 1
                # Errors
                errs = snapshot.metrics.get('g6_collection_errors_total', [])
                for e in errs:
                    delta = state.diff_counter('g6_collection_errors_total', e)
                    if delta > 0:
                        idx = e.labels.get('index','?')
                        etype = e.labels.get('error_type','err')
                        roll = state.index[idx]
                        roll.last_error = etype
                        roll.last_error_ts = now_ts
                names = sorted(state.index.keys())[:args.max_indices]
                for i,name in enumerate(names):
                    roll = state.index[name]
                    legs = opts_map.get(name, 0)
                    legs_avg = (roll.legs_total/roll.legs_cycles) if roll.legs_cycles else 0
                    succ = succ_map.get(name, float('nan'))
                    succ_avg = (roll.success_accum/roll.success_cycles) if roll.success_cycles else float('nan')
                    err_flag = 'Y' if (now_ts - roll.last_error_ts) < (args.refresh*3) and roll.last_error else ''
                    err_desc = roll.last_error if err_flag else ''
                    status_char = '✓'; status_style='green'
                    if math.isnan(succ) or succ < 80 or legs == 0:
                        status_char='X'; status_style='red'
                    elif succ < 92 or err_flag:
                        status_char='!'; status_style='yellow'
                    legs_cell = f"{int(legs)}({int(legs_avg)})" if legs_avg else f"{int(legs)}"
                    succ_cell = f"{succ:.1f}({succ_avg:.1f})" if not math.isnan(succ_avg) else (f"{succ:.1f}" if not math.isnan(succ) else '-')
                    time_cell = time.strftime('%H:%M:%S', time.localtime(now_ts))
                    row_style = 'on grey11' if i % 2 else ''
                    tbl.add_row(time_cell, name, legs_cell, succ_cell, err_flag, f"[{status_style}]{status_char}[/]", err_desc, style=row_style)
                return Panel(tbl, title='Enhanced Rolling Live Data Stream', border_style='yellow')  # type: ignore

            def build_layout(snapshot: Optional[MetricsSnapshot], logs: List[str]):  # type: ignore
                """Construct dashboard layout.

                NOTE: Previous version created a detached 'body' Layout and then attempted
                to update children directly on root (layout['stream']) before attaching,
                causing KeyError: 'stream'. We now split the root first, then operate on
                layout['body'] so all named regions are registered.
                """
                if not RICH_AVAILABLE or Layout is None:  # safety
                    return 'Rich not available'
                layout = Layout()  # type: ignore
                layout.split(
                    Layout(name='body', ratio=18),
                    Layout(name='footer', size=3)
                )
                body = layout['body']  # type: ignore
                body.split_row(
                    Layout(name='stream', ratio=3),  # live index table
                    Layout(name='mid', ratio=2),      # system + storage stack
                    Layout(name='logs', ratio=4)      # log tail
                )
                body['mid'].split(Layout(name='system'), Layout(name='storage'))  # type: ignore
                # Populate panels
                body['stream'].update(build_index_table(snapshot))
                body['system'].update(build_metrics_panel(snapshot))
                body['storage'].update(build_storage_panel(snapshot))
                body['logs'].update(build_logs_panel(logs))
                # Footer/help panel
                bars_status = 'off' if args.no_bars else 'on'
                degraded = state.consecutive_failures > 0
                foot_txt = Text(
                    f"Endpoint: {endpoint}  Refresh: {args.refresh:.1f}s  Timeout: {args.timeout:.1f}s  Bars: {bars_status}  Attempts: {state.attempts}  Failures: {state.consecutive_failures}  LastFetch(ms): {state.last_fetch_ms:.1f}",
                    style='yellow' if degraded else 'green'
                )  # type: ignore
                foot_hint = Text("  Keys: Ctrl+C quit  Args: --no-bars --plain --mem-cap-mb", style='dim')  # type: ignore
                layout['footer'].update(Panel(Text.assemble(foot_txt, foot_hint), border_style='yellow' if degraded else 'green'))  # type: ignore
                # Stale data highlighting
                if snapshot:
                    age = time.time() - snapshot.ts
                    if age > args.refresh * args.stale_warn_mult:
                        degraded_now = state.consecutive_failures > 0
                        style = 'red' if not degraded_now else 'grey50'
                        title = 'STALE DATA' if not degraded_now else 'STALE + DEGRADED'
                        # build_index_table already returns a Panel; wrap modification by updating its title/border if possible
                        stale_panel = build_index_table(snapshot)  # type: ignore
                        try:
                            # Rich Panel is immutable-ish; easiest is create a new Panel with same renderable
                            inner = getattr(stale_panel, 'renderable', stale_panel)
                            from rich.panel import Panel as _Panel  # type: ignore
                            stale_panel = _Panel(inner, title=title, border_style=style, subtitle='cached & stale' if degraded_now else None)
                        except Exception:
                            pass
                        body['stream'].update(stale_panel)  # type: ignore
                # Degradation banner overlay
                if state.consecutive_failures > 0:
                    root = Layout()  # type: ignore
                    root.split(Layout(name='banner', size=3), Layout(name='body'))  # type: ignore
                    color = 'red' if state.consecutive_failures >= 3 else 'yellow'
                    age_sec = 0 if state.last_fetch_ok == 0 else int(time.time() - state.last_fetch_ok)
                    msg = f" METRICS ENDPOINT UNREACHABLE (attempts={state.attempts}, failures={state.consecutive_failures}, age={age_sec}s) – cached/placeholder data shown "
                    root['banner'].update(Panel(Text(msg, style=color), border_style=color))  # type: ignore
                    root['body'].update(layout)
                    return root
                return layout
        else:
            def build_layout(snapshot: Optional[MetricsSnapshot], logs: List[str]):  # type: ignore
                return 'Rich not available'

        def export_state_if_needed(snap: MetricsSnapshot):
            if not args.state_export:
                return
            try:
                import json
                export = {
                    'ts': snap.ts,
                    'consecutive_failures': state.consecutive_failures,
                    'last_fetch_ms': state.last_fetch_ms,
                    'indices': {
                        k: {
                            'legs_total': v.legs_total,
                            'legs_cycles': v.legs_cycles,
                            'success_accum': v.success_accum,
                            'success_cycles': v.success_cycles,
                            'last_error': v.last_error,
                            'last_error_ts': v.last_error_ts
                        } for k,v in state.index.items()
                    }
                }
                with open(args.state_export, 'w', encoding='utf-8') as f:
                    json.dump(export, f, indent=2)
            except Exception:
                pass

        def perform_fetch():
            nonlocal prev
            try:
                _t0 = time.time()
                snap = fetcher.fetch()
                prev = snap
                state.last_fetch_ms = (time.time() - _t0) * 1000.0
                state.consecutive_failures = 0
                state.last_fetch_ok = time.time()
                export_state_if_needed(snap)
            except Exception:
                state.consecutive_failures += 1
                import traceback, io
                buf = io.StringIO()
                traceback.print_exc(file=buf)
                state.last_error = buf.getvalue().strip().splitlines()[-1]
            state.attempts += 1
            log_tail.read_new()

        def print_plain_cycle():
            if prev is None:
                console.print(f"[bold yellow]No metrics yet - attempts={state.attempts} failures={state.consecutive_failures} endpoint={endpoint}[/]")
                if state.last_error:
                    console.print(f"Last error: {state.last_error}")
                return
            try:
                summary = render_plain(prev, None, bars=not args.no_bars, mem_cap_mb=args.mem_cap_mb)
            except Exception as e:
                console.print(f"[red]Plain render failure: {e}")
                return
            console.print(summary)
            tail = log_tail.get_lines()[-10:]
            if tail:
                console.print("--- logs (last 10) ---")
                for ln in tail:
                    console.print(ln)

        # Simple loop mode (no Live) for terminals with flicker/blank issues
        if args.simple_loop or args.force_plain_cycles:
            try:
                while True:
                    perform_fetch()
                    if args.force_plain_cycles or state.degraded_plain:
                        print_plain_cycle()
                    else:
                        try:
                            layout_obj = build_layout(prev, log_tail.get_lines())
                            console.print(layout_obj)  # type: ignore
                        except Exception as e:
                            console.print(f"[red]Render error:[/] {e}")
                            if prev is None:
                                console.print(f"Waiting for metrics from {endpoint} (attempt {state.attempts}, failures {state.consecutive_failures})")
                    if prev is None and state.attempts >= 5:
                        if not state.degraded_plain:
                            console.print("[yellow]Auto-degrading to plain output until first successful metrics fetch...[/]")
                        state.degraded_plain = True
                    time.sleep(args.refresh)
            except KeyboardInterrupt:
                return
        else:
            # Auto-switch to simple loop if repeated failures or suspected screen issue
            try:
                with Live(console=console, refresh_per_second=4, screen=not args.no_screen):  # type: ignore
                    while True:
                        perform_fetch()
                        # If many consecutive failures or every ~10s only a flash (user symptom), fallback
                        if state.consecutive_failures >= 5 or (args.refresh <= 1 and state.attempts >= 15 and state.consecutive_failures > 0):
                            console.print("[yellow]Switching to simple loop mode due to repeated failures / flicker.[/]")
                            args.simple_loop = True
                            break
                        if prev is None and state.attempts >= 5:
                            if not state.degraded_plain:
                                console.print("[yellow]No successful metrics yet, showing placeholder plain output...[/]")
                            state.degraded_plain = True
                        try:
                            if state.degraded_plain:
                                print_plain_cycle()
                            else:
                                layout_obj = build_layout(prev, log_tail.get_lines())
                                console.print(layout_obj, justify='left', overflow='crop')  # type: ignore
                        except Exception as render_err:
                            console.print(f"[red]Render error:[/] {render_err}")
                            if prev is None:
                                console.print(f"Waiting for metrics from {endpoint} (attempt {state.attempts}, failures {state.consecutive_failures})")
                        time.sleep(args.refresh)
            except KeyboardInterrupt:
                return
            # If switched, enter simple loop
            if args.simple_loop:
                try:
                    while True:
                        perform_fetch()
                        if state.degraded_plain:
                            print_plain_cycle()
                        else:
                            try:
                                layout_obj = build_layout(prev, log_tail.get_lines())
                                console.print(layout_obj)  # type: ignore
                            except Exception as e:
                                console.print(f"[red]Render error:[/] {e}")
                                if prev is None:
                                    console.print(f"Waiting for metrics from {endpoint} (attempt {state.attempts}, failures {state.consecutive_failures})")
                        if prev is None and state.attempts >= 5:
                            if not state.degraded_plain:
                                console.print("[yellow]Auto-degrading to plain output until first successful metrics fetch...[/]")
                            state.degraded_plain = True
                        time.sleep(args.refresh)
                except KeyboardInterrupt:
                    return

if __name__ == '__main__':
    main()
