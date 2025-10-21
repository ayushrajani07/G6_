from __future__ import annotations

import argparse
import copy
import json
import os
import time
from collections import deque
from typing import Any, cast
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

# Ensure project root is on sys.path when executed directly as a script (python scripts/summary/app.py)
try:
    import sys as _sys
    _this_dir = os.path.dirname(os.path.abspath(__file__))
    _scripts_dir = os.path.dirname(_this_dir)          # .../scripts
    _proj_root = os.path.dirname(_scripts_dir)         # project root
    if _proj_root and _proj_root not in _sys.path:
        _sys.path.insert(0, _proj_root)
except Exception:
    pass

from typing import Protocol

from scripts.summary.derive import derive_cycle
from scripts.summary.env_config import load_summary_env
from scripts.summary.layout import build_layout, refresh_layout
from scripts.summary.plugins.base import OutputPlugin, PanelsWriter, SummarySnapshot, TerminalRenderer
from scripts.summary.unified_loop import UnifiedLoop
from src.error_handling import handle_ui_error


class _Logger(Protocol):
    def info(self, msg: str, **kw: Any) -> None: ...
    def error(self, msg: str, **kw: Any) -> None: ...

def _load_status(path: str) -> dict[str, Any] | None:
    """Minimal status loader (legacy StatusCache removed)."""
    try:
        from src.utils.status_reader import get_status_reader  # optional optimized reader
    except Exception:
        get_status_reader = None  # type: ignore
    try:
        if get_status_reader is not None:
            reader = get_status_reader(path)
            data = reader.get_raw_status()
            return data if isinstance(data, dict) else None
        # Fallback: use cached JSON reader when available
        try:
            from pathlib import Path as _Path

            from src.utils.csv_cache import read_json_cached as _read_json_cached
            obj = _read_json_cached(_Path(path))
            return obj if isinstance(obj, dict) else None
        except Exception:
            pass
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
            return data if isinstance(data, dict) else None
    except Exception:
        return None

# Optional event bus for reactive refresh
try:  # Optional event bus (guarded)
    from src.utils.file_watch_events import (
        PANEL_FILE_CHANGED,
        STATUS_FILE_CHANGED,
    )
    from src.utils.file_watch_events import (
        FileWatchEventBus as _FWBus,
    )
    HAVE_FILE_WATCH_BUS = True
except Exception:  # pragma: no cover
    _FWBus = None  # type: ignore
    HAVE_FILE_WATCH_BUS = False
    STATUS_FILE_CHANGED = "status_file_changed"
    PANEL_FILE_CHANGED = "panel_file_changed"

def _get_output_lazy() -> _Logger:
    class _O:
        def info(self, msg: str, **kw: Any) -> None:
            try:
                print(msg)
            except Exception:
                pass
        def error(self, msg: str, **kw: Any) -> None:
            try:
                import sys as _sys
                print(msg, file=_sys.stderr)
            except Exception:
                pass
    return _O()


def plain_fallback(status: dict[str, Any] | None, status_file: str, metrics_url: str) -> str:
    """Minimal plain output string if Rich is unavailable.

    Keeps behavior deterministic and avoids importing heavy machinery.
    """
    try:
        keys = ", ".join(sorted(list((status or {}).keys())[:12]))
    except Exception:
        keys = ""
    return f"G6 Summary (plain) | keys: {keys or '—'} | file: {status_file} | metrics: {metrics_url}"


def compute_cadence_defaults() -> dict[str, float]:
    """Return effective refresh intervals using centralized SummaryEnv."""
    # Force reload so tests that monkeypatch os.environ see fresh values each call
    env = load_summary_env(force_reload=True)
    return {"meta": env.refresh_meta_sec, "res": env.refresh_res_sec}


def run(argv: list[str] | None = None) -> int:

    parser = argparse.ArgumentParser(description="G6 Summarizer View")
    parser.add_argument(
        "--status-file",
        default=os.getenv("G6_STATUS_FILE", "data/runtime_status.json"),
    )
    parser.add_argument(
        "--metrics-url",
        default=os.getenv("G6_METRICS_URL", "http://127.0.0.1:9108/metrics"),
    )
    parser.add_argument("--refresh", type=float, default=0.5, help="UI frame refresh seconds (visual)")
    parser.add_argument("--no-rich", action="store_true", help="Disable rich UI and print plain text")
    parser.add_argument("--compact", action="store_true", help="Compact layout with fewer details")
    parser.add_argument("--low-contrast", action="store_true", help="Use neutral borders/colors")
    # Phase 3: panels mode auto-detect (default 'auto'); explicit flag retained temporarily
    parser.add_argument(
        "--panels",
        choices=["auto", "on", "off"],
        default="auto",
        help="Prefer data/panels JSON (on/off/auto, default auto-detect)",
    )
    parser.add_argument(
        "--panels-dir",
        help="Override panels directory (sets G6_PANELS_DIR for this process)",
    )
    parser.add_argument(
        "--sse-url",
        default=os.getenv("G6_SUMMARY_SSE_URL"),
        help=(
            "Subscribe to SSE endpoint for live updates "
            "(e.g., http://127.0.0.1:9315/events)"
        ),
    )
    parser.add_argument(
        "--no-write-panels",
        action="store_true",
        help="(Unified) Do not write panels JSON artifact",
    )
    parser.add_argument(
        "--sse-types",
        default=os.getenv("G6_SUMMARY_SSE_TYPES", "panel_full,panel_diff"),
        help=(
            "Comma-separated event types to consume from SSE "
            "(default panel_full,panel_diff)"
        ),
    )
    parser.add_argument(
        "--cycles",
        type=int,
        default=None,
        help="(Unified) Run only N cycles then exit (CI / deterministic testing)",
    )
    args = parser.parse_args(argv)

    env = load_summary_env()
    mode = (env.summary_mode or "").strip().lower()
    if mode in ("condensed", "compact") and not args.compact:
        args.compact = True
    elif mode in ("expanded", "full") and args.compact:
        args.compact = False

    out = _get_output_lazy()
    status = _load_status(args.status_file)

    # Panels directory override only; panels mode now auto-detected (ignore --panels except for future removal notice)
    if args.panels_dir:
        try:
            os.environ["G6_PANELS_DIR"] = str(args.panels_dir)
        except Exception:
            pass

    # status already loaded above (single shot; unified loop owns subsequent refreshes)

    # Optional one-time model debug emission (replacement for deprecated G6_SUMMARY_UNIFIED_SNAPSHOT gate)
    try:
        if env.unified_model_init_debug:
            from src.summary.unified.model import assemble_model_snapshot
            model_snap, model_diag = assemble_model_snapshot(
                runtime_status=status,
                panels_dir=env.panels_dir,
                include_panels=True,
            )
            debug_payload = {
                'schema_version': model_snap.schema_version,
                'cycle': {
                    'number': model_snap.cycle.number,
                    'last_duration_sec': model_snap.cycle.last_duration_sec,
                    'success_rate_pct': model_snap.cycle.success_rate_pct,
                },
                'market_status': model_snap.market_status,
                'indices': [ {'name': i.name, 'legs': i.legs, 'dq_score': i.dq_score} for i in model_snap.indices[:6] ],
                'dq': {
                    'g': model_snap.dq.green,
                    'w': model_snap.dq.warn,
                    'e': model_snap.dq.error,
                    'warn_threshold': model_snap.dq.warn_threshold,
                    'error_threshold': model_snap.dq.error_threshold,
                },
                'adaptive': {
                    'alerts_total': model_snap.adaptive.alerts_total,
                    'severity_counts': model_snap.adaptive.severity_counts,
                },
                'provenance': model_snap.provenance,
                'diag_warnings': model_diag.get('warnings', []),
            }
            out.info(f"[unified_model:init] {json.dumps(debug_payload, separators=(',',':'))}")
    except Exception:
        pass

    # Rewrite flag (Phase 1): activates new domain + plain renderer path
    from scripts.summary.config import SummaryConfig
    cfg = SummaryConfig.load()

    # --- Unified loop (sole execution path) ---
    if True:
        panels_dir = cfg.panels_dir
        write_panels = (not args.no_write_panels) and cfg.write_panels
        try:
            if write_panels:
                os.makedirs(panels_dir, exist_ok=True)
        except Exception:
            write_panels = False
        # Plugin assembly: if rewrite flag + no-rich => PlainRenderer, else traditional TerminalRenderer
        plugins: list[OutputPlugin] = []
        # Always prefer PlainRenderer for --no-rich if available; rewrite gating removed
        if args.no_rich:
            try:
                from scripts.summary.plain_renderer import PlainRenderer
                plugins.append(PlainRenderer())
            except Exception:
                plugins.append(TerminalRenderer(rich_enabled=False))
        else:
            plugins.append(TerminalRenderer(rich_enabled=True))
        if write_panels:
            # Legacy bridge removed; always enable PanelsWriter when write_panels is true.
            plugins.append(PanelsWriter(panels_dir=panels_dir))
        # Optional metrics emitter (prometheus) gated by G6_UNIFIED_METRICS
        if cfg.unified_metrics:
            try:
                from scripts.summary.plugins.base import MetricsEmitter
                plugins.append(MetricsEmitter())
            except Exception:
                pass
        # Optional SSE publisher (Phase 4) - internal event queue only (no network yet)
        if cfg.sse_enabled:
            try:
                from scripts.summary.plugins.sse import SSEPublisher
                plugins.append(SSEPublisher(diff=True))
            except Exception:
                pass
        # Optional dossier writer (unified path only): activate if path present
        if cfg.dossier_path:
            try:
                from scripts.summary.plugins.dossier import DossierWriter
                plugins.append(DossierWriter())
            except Exception:
                pass
        # Optional SSE panels ingestor (Phase 1) - activates if G6_PANELS_SSE_URL set
        if cfg.panels_sse_url:
            try:
                from scripts.summary.plugins.sse_panels import SSEPanelsIngestor
                plugins.append(SSEPanelsIngestor())
            except Exception:
                pass
        loop = UnifiedLoop(plugins, panels_dir=panels_dir, refresh=args.refresh)
        try:
            loop.run(cycles=args.cycles)
            return 0
        except KeyboardInterrupt:
            return 0
        except Exception as e:  # noqa: BLE001
            out.error(f"Unified loop failure: {e}")
            return 1

    # Plain one-shot rendering path (retained only for non-rich mode) -----------------------------
    try:
        import rich  # noqa: F401
        RICH_AVAILABLE = True
    except Exception:
        RICH_AVAILABLE = False
    if not RICH_AVAILABLE or args.no_rich:
        # One-shot plain render using PlainRenderer if importable; otherwise print minimal JSON keys
        try:
            from scripts.summary.plain_renderer import PlainRenderer
            renderer = PlainRenderer()
            snap = SummarySnapshot(
                status=status or {},
                derived={},
                panels={},
                ts_read=time.time(),
                ts_built=time.time(),
                cycle=0,
                errors=tuple(),
                model=None,
            )
            renderer.process(snap)
        except Exception:
            try:
                keys = ", ".join(sorted(list((status or {}).keys())[:12]))
                print(f"G6 Summary (plain) | keys: {keys or '—'} | file: {args.status_file}")
            except Exception:
                print(f"G6 Summary (plain) | file: {args.status_file}")
    # One-shot dossier write in plain mode when a dossier path is provided
        try:
            env = load_summary_env()
            dossier_path = env.dossier_path
            if dossier_path:
                from src.summary.unified.model import assemble_model_snapshot
                model_snap, _diag = assemble_model_snapshot(
                    runtime_status=status,
                    panels_dir=env.panels_dir,
                    include_panels=True,
                )
                os.makedirs(os.path.dirname(dossier_path), exist_ok=True)
                tmp = dossier_path + ".tmp"
                with open(tmp, 'w', encoding='utf-8') as f:
                    json.dump(model_snap.to_dict(), f, ensure_ascii=False, indent=2)
                try:
                    import os as _os
                    _os.replace(tmp, dossier_path)
                except Exception:
                    pass
        except Exception:
            pass
        return 0

    try:
        from rich.console import Console
        from rich.live import Live
    except Exception:
        Console = None  # type: ignore
        Live = None  # type: ignore
    import threading

    class _StatusCache:
        def __init__(self, path: str) -> None:
            self._path = path
            self._last_mtime: float = -1.0
            self._last: dict[str, Any] | None = status if isinstance(status, dict) else None
        def refresh(self) -> dict[str, Any] | None:
            try:
                st = os.stat(self._path)
                mt = float(getattr(st, 'st_mtime', 0.0))
            except Exception:
                return self._last
            if mt != self._last_mtime:
                self._last = _load_status(self._path)
                self._last_mtime = mt
            return self._last

    cache = _StatusCache(args.status_file)

    use_sse = bool(args.sse_url)
    sse_stop: threading.Event | None = None
    sse_thread: threading.Thread | None = None

    # Pre-init references (assigned later when rich loop starts)
    bus = None
    status_event: threading.Event | None = None
    stop_watcher: threading.Event | None = None
    watcher_thread: threading.Thread | None = None

    # Enable ANSI VT processing on Windows and force terminal control sequences
    try:
        os.system("")
    except Exception:
        pass
    console = Console(force_terminal=True) if Console is not None else None
    try:
        if console is not None:
            console.clear()
    except Exception:
        pass

    window: deque[float] = deque(maxlen=120)
    def compute_roll() -> dict[str, Any]:
        if not window:
            return {"avg": None, "p95": None}
        vals = list(window)
        vals_sorted = sorted(vals)
        p95_idx = max(0, int(0.95 * (len(vals_sorted) - 1)))
        return {"avg": sum(vals) / len(vals), "p95": vals_sorted[p95_idx]}
    # Refresh cadence: unified knob with per-knob overrides
    cad = compute_cadence_defaults()
    meta_refresh = cad["meta"]
    res_refresh = cad["res"]
    last_meta = 0.0
    last_res = 0.0
    last_status: dict[str, Any] | None = status
    last_cycle_id: Any = None
    # Dossier writer state (rich loop)
    _dossier_state: dict[str, Any] = {
        'last_write': 0.0,
    }

    layout = build_layout(
        status,
        args.status_file,
        args.metrics_url,
        rolling=compute_roll(),
        compact=bool(args.compact),
        low_contrast=bool(args.low_contrast),
    )

    # Event-driven refresh wiring (optional, safe no-op if bus unavailable)
    status_event = threading.Event()
    stop_watcher = threading.Event()
    def _on_status_changed() -> None:  # publisher guarantees best-effort; keep callback cheap
        try:
            if status_event is not None:
                status_event.set()
        except Exception:
            pass
    def _on_panel_changed(_name: str) -> None:
        try:
            if status_event is not None:
                status_event.set()
        except Exception:
            pass
    try:
        if HAVE_FILE_WATCH_BUS and _FWBus is not None:
            bus = _FWBus.instance()
            bus.subscribe(STATUS_FILE_CHANGED, _on_status_changed)
            bus.subscribe(PANEL_FILE_CHANGED, _on_panel_changed)
            def _watcher_loop() -> None:
                try:
                    from src.data_access.unified_source import UnifiedDataSource
                except Exception:
                    return
                uds = UnifiedDataSource()
                try:
                    poll = float(getattr(uds.config, "file_poll_interval", 0.5) or 0.5)
                except Exception:
                    poll = 0.5
                while stop_watcher is not None and not stop_watcher.is_set():
                    try:
                        uds.get_runtime_status()
                        uds.get_panel_raw("indices_stream")
                    except Exception:
                        pass
                    if stop_watcher is not None:
                        stop_watcher.wait(poll)
            watcher_thread = threading.Thread(target=_watcher_loop, name="g6-summary-watcher", daemon=True)
            watcher_thread.start()
    except Exception:
        bus = None

    # SSE consumer (optional)
        sse_state_lock = threading.Lock()
        sse_latest_status: dict[str, Any] | None = None
        sse_last_timestamp: str | None = None
        sse_last_event_id = 0
        # Render generation counts local (UI composite signal increments for ANY accepted event affecting layout)
        sse_generation = 0
        sse_rendered_generation = 0
        # Panel snapshot baseline generation (from server) and need-full flag
        sse_panel_generation: int | None = None
        sse_need_full: bool = False
        # Need-full episode tracking
        sse_need_full_active_prev: bool = False  # previous rendered need_full state
        # Metric handles (resolved lazily via registry module attributes if present)
        _m_need_full_active = None  # gauge
        _m_need_full_episodes = None  # counter
        # Tracks whether the current connection cycle already attempted a forced full recovery
        sse_full_recovery_attempted: bool = False
        # Auto recovery flag (env gated; default on)
        try:
            sse_auto_full_recovery = env.auto_full_recovery
        except Exception:
            sse_auto_full_recovery = True
    # Severity and followup events are now handled via PanelStateStore in plugin (sse_panels_ingestor)
        # SSE event counters (Phase: model instrumentation)
        # Keys:
        #   panel_full: number of full snapshot events accepted
        #   panel_diff_applied: number of diffs successfully merged
        #   panel_diff_dropped: number of diffs dropped due to no baseline or generation mismatch
        # Centralized panel+diff state store (replaces local counters/diff merge)
        from scripts.summary.sse_state import PanelStateStore
        panel_state_store = PanelStateStore()
        type_filters: list[str] = []
        if args.sse_types:
            for part in str(args.sse_types).split(','):
                p = part.strip()
                if p:
                    type_filters.append(p)
        if use_sse and not type_filters:
            type_filters = ["panel_full", "panel_diff"]
        if use_sse:
            type_filters = list(dict.fromkeys(type_filters))

            # Inline merge helper removed; PanelStateStore uses shared diff_merge implementation.

            base_sse_url = str(args.sse_url)
            try:
                parsed_base = urllib_parse.urlparse(base_sse_url)
            except Exception:
                parsed_base = urllib_parse.urlparse(base_sse_url, scheme='http')

            def _build_sse_url(last_id: int) -> str:
                qs_pairs = urllib_parse.parse_qsl(parsed_base.query, keep_blank_values=True)
                qs = dict(qs_pairs)
                if type_filters:
                    qs['types'] = ','.join(type_filters)
                if last_id:
                    qs['last_id'] = str(last_id)
                elif 'last_id' in qs:
                    qs.pop('last_id', None)
                # Add force_full param for recovery path
                with sse_state_lock:
                    need_full_local = sse_need_full
                    recovery_done = sse_full_recovery_attempted
                    auto_ok = sse_auto_full_recovery
                if auto_ok and need_full_local and not recovery_done:
                    qs['force_full'] = '1'
                new_query = urllib_parse.urlencode(qs, doseq=True)
                return urllib_parse.urlunparse(parsed_base._replace(query=new_query))

            def _handle_payload(payload: dict[str, Any]) -> None:
                nonlocal sse_latest_status, sse_last_timestamp, sse_generation, sse_panel_generation, sse_need_full
                if not isinstance(payload, dict):
                    return
                event_type = payload.get('type') or payload.get('event')
                inner = payload.get('payload') if isinstance(payload.get('payload'), dict) else None
                if inner is None:
                    return
                ts = payload.get('timestamp_ist') if isinstance(payload.get('timestamp_ist'), str) else None
                # Extract server-side generation (present for panel_full/panel_diff)
                try:
                    gen_val = payload.get('generation')
                    gen_int = (
                        int(gen_val)
                        if isinstance(gen_val, (int, float, str)) and str(gen_val).isdigit()
                        else None
                    )
                except Exception:
                    gen_int = None
                if event_type == 'panel_full':
                    status_obj = inner.get('status') if isinstance(inner.get('status'), dict) else None
                    if status_obj is None:
                        return
                    snapshot = copy.deepcopy(status_obj)
                    panel_state_store.apply_panel_full(snapshot, gen_int)
                    (
                        snap_status,
                        srv_gen,
                        ui_gen,
                        need_full_flag,
                        counters,
                        _sev_counts_unused,
                        _sev_state_unused,
                        _followups_unused,
                    ) = panel_state_store.snapshot()
                    with sse_state_lock:
                        sse_latest_status = snap_status
                        if ts:
                            sse_last_timestamp = ts
                        sse_panel_generation = srv_gen
                        sse_need_full = need_full_flag
                        sse_generation = ui_gen
                    if status_event is not None:
                        status_event.set()
                elif event_type == 'panel_diff':
                    diff_obj = inner.get('diff') if isinstance(inner.get('diff'), dict) else None
                    if diff_obj is None:
                        return
                    with sse_state_lock:
                        base_status = sse_latest_status
                        baseline_gen = sse_panel_generation
                    if not isinstance(base_status, dict):
                        return
                    # Generation validation: reject diff if generation missing or mismatched
                    if baseline_gen is None:
                        # No baseline yet -> mark need_full and ignore diff
                        panel_state_store.mark_need_full()
                        with sse_state_lock:
                            sse_need_full = True
                        # Metrics: increment events_dropped_total{reason="no_baseline",type="panel_diff"}
                        try:
                            import importlib as _il
                            _reg = getattr(_il.import_module('src.metrics'), 'registry', None)
                            _m_any = cast(Any, getattr(_reg, 'events_dropped_total', None))
                            if _m_any is not None:
                                _m_any.labels(reason='no_baseline', type='panel_diff').inc()
                        except Exception:
                            pass
                        return
                    if gen_int is None or gen_int != baseline_gen:
                        # Panel generation bumped (or malformed); require new full
                        panel_state_store.mark_need_full()
                        with sse_state_lock:
                            sse_need_full = True
                        try:
                            import importlib as _il2
                            _reg2 = getattr(_il2.import_module('src.metrics'), 'registry', None)
                            _m2_any = cast(Any, getattr(_reg2, 'events_dropped_total', None))
                            if _m2_any is not None:
                                _m2_any.labels(reason='generation_mismatch', type='panel_diff').inc()
                        except Exception:
                            pass
                        return
                    applied = panel_state_store.apply_panel_diff(diff_obj, gen_int)
                    if applied:
                        (
                            snap_status2,
                            srv_gen2,
                            ui_gen2,
                            need_full2,
                            counters2,
                            _sc2,
                            _ss2,
                            _fu2,
                        ) = panel_state_store.snapshot()
                        with sse_state_lock:
                            sse_latest_status = snap_status2
                            if ts:
                                sse_last_timestamp = ts
                            sse_panel_generation = srv_gen2
                            sse_need_full = need_full2
                            sse_generation = ui_gen2
                    if status_event is not None:
                        status_event.set()

            def _sse_consumer_loop() -> None:
                nonlocal sse_last_event_id, sse_full_recovery_attempted
                backoff = 1.0
                timeout_sec = env.client_sse_timeout_sec
                while sse_stop is not None and not sse_stop.is_set():
                    try:
                        target_url = _build_sse_url(sse_last_event_id)
                        req = urllib_request.Request(target_url, headers={'Accept': 'text/event-stream'})
                        if sse_last_event_id:
                            req.add_header('Last-Event-ID', str(sse_last_event_id))
                        with urllib_request.urlopen(req, timeout=timeout_sec) as resp:
                            backoff = 1.0
                            # If we reached here with need_full flagged this connection will attempt force_full;
                            # mark attempt so we don't continually append force_full on subsequent reconnects.
                            with sse_state_lock:
                                if sse_auto_full_recovery and sse_need_full and not sse_full_recovery_attempted:
                                    sse_full_recovery_attempted = True
                                    # Metric: increment events_full_recovery_total counter if available
                                    try:
                                        import importlib as _il3
                                        _reg3 = getattr(_il3.import_module('src.metrics'), 'registry', None)
                                        mfr_any = cast(Any, getattr(_reg3, 'events_full_recovery_total', None))
                                        if mfr_any is not None:
                                            mfr_any.inc()
                                    except Exception:
                                        pass
                            data_lines: list[str] = []
                            event_label: str | None = None
                            event_id_local: int | None = None
                            for raw_line in resp:
                                if sse_stop is not None and sse_stop.is_set():
                                    break
                                try:
                                    line = raw_line.decode('utf-8').rstrip('\r\n')
                                except Exception:
                                    continue
                                if line == '':
                                    if data_lines:
                                        try:
                                            payload_obj = json.loads('\n'.join(data_lines))
                                        except Exception:
                                            payload_obj = None
                                        if isinstance(payload_obj, dict):
                                            if event_label and 'type' not in payload_obj:
                                                payload_obj['type'] = event_label
                                            event_id_val = (
                                                payload_obj.get('id')
                                                or payload_obj.get('sequence')
                                                or event_id_local
                                            )
                                            if isinstance(event_id_val, int):
                                                sse_last_event_id = event_id_val
                                            _handle_payload(payload_obj)
                                            # If we just received a panel_full while in recovery state,
                                            # clear flag allowing future recoveries if problem reoccurs
                                            if payload_obj.get('type') == 'panel_full':
                                                with sse_state_lock:
                                                    if sse_auto_full_recovery and sse_need_full is False:
                                                        sse_full_recovery_attempted = False
                                    data_lines = []
                                    event_label = None
                                    event_id_local = None
                                    continue
                                if line.startswith(':'):
                                    continue
                                if line.startswith('data:'):
                                    data_lines.append(line[5:].lstrip())
                                    continue
                                if line.startswith('event:'):
                                    event_label = line[6:].strip() or None
                                    continue
                                if line.startswith('id:'):
                                    try:
                                        event_id_local = int(line[3:].strip())
                                    except Exception:
                                        event_id_local = None
                                    continue
                                if line.startswith('retry:'):
                                    continue
                            # Connection ended normally; loop to reconnect immediately
                            continue
                    except (urllib_error.URLError, urllib_error.HTTPError, TimeoutError) as exc:
                        try:
                            out.error(f"SSE reconnect in {backoff:.1f}s: {exc}", scope="summary_sse")
                        except Exception:
                            pass
                    except Exception as exc:
                        try:
                            out.error(f"SSE loop error, retrying in {backoff:.1f}s: {exc}", scope="summary_sse")
                        except Exception:
                            pass
                    if sse_stop is not None and sse_stop.wait(backoff):
                        break
                    backoff = min(backoff * 2.0, 30.0)

            if use_sse and sse_stop is not None:
                sse_thread = threading.Thread(target=_sse_consumer_loop, name="g6-summary-sse", daemon=True)
                sse_thread.start()

    # Use alternate screen to keep the frame static (no scroll).
    # Default off on Windows to avoid flicker; env can force on.
        default_alt = "off" if os.name == "nt" else "on"
        use_alt_screen = env.alt_screen if env.alt_screen is not None else (default_alt == "on")
        fps = max(1, int(round(1.0 / max(0.1, args.refresh))))
        if Live is None or console is None:
            # Fallback plain mode if rich became unavailable after initial check
            print(plain_fallback(status, args.status_file, args.metrics_url))
            return 0
        with Live(
            layout,
            console=console,
            screen=use_alt_screen,
            refresh_per_second=fps,
            redirect_stdout=False,
            redirect_stderr=False,
            auto_refresh=False,
        ) as live:
            last_render_sig: str | None = None
            while True:
                try:
                    now = time.time()
                    # Dossier interval writer: Build snapshot & write if path + interval
                    try:
                        _dossier_path = env.dossier_path
                        if _dossier_path:
                            try:
                                _dossier_int = env.dossier_interval_sec
                            except Exception:
                                _dossier_int = 5.0
                            lw = _dossier_state.get('last_write', 0.0)
                            if now - float(lw) >= max(0.5, float(_dossier_int)):
                                from src.summary.unified.model import (
                                    assemble_model_snapshot as _assemble_model,
                                )
                                model_loop, _diag_loop = _assemble_model(
                                    runtime_status=last_status,
                                    panels_dir=env.panels_dir,
                                    include_panels=True,
                                )
                                try:
                                    os.makedirs(os.path.dirname(_dossier_path), exist_ok=True)
                                except Exception:
                                    pass
                                _tmp_dp = _dossier_path + ".tmp"
                                try:
                                    with open(_tmp_dp, 'w', encoding='utf-8') as f:
                                        json.dump(model_loop.to_dict(), f, ensure_ascii=False, indent=2)
                                    try:
                                        os.replace(_tmp_dp, _dossier_path)
                                    except Exception:
                                        pass
                                    _dossier_state['last_write'] = now
                                except Exception:
                                    pass
                    except Exception:
                        pass
                    if use_sse:
                        snapshot = None
                        ts_snapshot = None
                        gen_snapshot = None
                        with sse_state_lock:
                            if sse_latest_status is not None and sse_generation > sse_rendered_generation:
                                snapshot = copy.deepcopy(sse_latest_status)
                                ts_snapshot = sse_last_timestamp
                                gen_snapshot = sse_generation
                        if snapshot is not None:
                            last_status = snapshot
                            if isinstance(last_status, dict) and ts_snapshot:
                                meta = last_status.setdefault('panel_push_meta', {})
                                if isinstance(meta, dict):
                                    meta['last_event_ist'] = ts_snapshot
                            try:
                                cy = derive_cycle(last_status)
                                cur_cycle = cy.get("cycle") or cy.get("number") or cy.get("count")
                            except Exception:
                                cur_cycle = None
                            if cur_cycle is not None:
                                last_cycle_id = cur_cycle
                            last_meta = now
                            if gen_snapshot is not None:
                                sse_rendered_generation = gen_snapshot
                    # If we observed a change event, force an immediate meta refresh
                    if status_event is not None and status_event.is_set():
                        status_event.clear()
                        last_meta = 0.0  # ensure the block below refreshes
                    if now - last_meta >= meta_refresh:
                        cur = cache.refresh()
                        if cur is not None:
                            try:
                                cy = derive_cycle(cur)
                                cur_cycle = cy.get("cycle") or cy.get("count") or cur.get("cycle")
                            except Exception:
                                cur_cycle = None
                            if last_status is None:
                                last_status = cur
                            if cur_cycle is not None and cur_cycle != last_cycle_id:
                                last_status = cur
                                last_cycle_id = cur_cycle
                        last_meta = now

                    interval = None
                    try:
                        if last_status:
                            interval = last_status.get("interval")
                            if interval is None:
                                loop = last_status.get("loop") if isinstance(last_status, dict) else None
                                if isinstance(loop, dict):
                                    interval = loop.get("target_interval")
                    except Exception:
                        interval = None

                    effective_status = dict(last_status or {}) if last_status else {}
                    # Severity & followups now provided by plugin; inline copies removed
                    with sse_state_lock:
                        pass
                        need_full_flag = bool(sse_need_full)
                        panel_gen_val = sse_panel_generation
                    # Inject push meta block
                    if isinstance(effective_status, dict):
                        meta_bucket = (
                            effective_status.setdefault('panel_push_meta', {})
                            if isinstance(effective_status.get('panel_push_meta'), dict)
                            else effective_status.setdefault('panel_push_meta', {})
                        )
                        if isinstance(meta_bucket, dict):
                            if need_full_flag:
                                meta_bucket['need_full'] = True
                                meta_bucket['need_full_reason'] = (
                                    meta_bucket.get('need_full_reason')
                                    or 'snapshot_required'
                                )
                            else:
                                meta_bucket.pop('need_full', None)
                                meta_bucket.pop('need_full_reason', None)
                            if panel_gen_val is not None:
                                meta_bucket['panel_generation'] = panel_gen_val
                            # Snapshot SSE event counters (immutable per render)
                            try:
                                if use_sse:
                                    try:
                                        (
                                            _snap_status,
                                            _srv_gen,
                                            _ui_gen,
                                            _need_full,
                                            _counters,
                                            _sc_tmp,
                                            _ss_tmp,
                                            _fu_tmp,
                                        ) = panel_state_store.snapshot()
                                        meta_bucket['sse_events'] = dict(_counters)
                                    except Exception:
                                        pass
                            except Exception:
                                pass
                    # Need-full metrics: register lazily & emit transitions
                    if need_full_flag != sse_need_full_active_prev:
                        try:
                            import importlib as _il_nf3
                            _reg_nf3 = getattr(_il_nf3.import_module('src.metrics'), 'registry', None)
                            # Expect attributes created elsewhere via explicit registration;
                            # if absent, attempt simple helper usage.
                            if _m_need_full_active is None:
                                _m_need_full_active = getattr(_reg_nf3, 'events_need_full_active', None)
                            if _m_need_full_episodes is None:
                                _m_need_full_episodes = getattr(_reg_nf3, 'events_need_full_episodes_total', None)
                            # If not pre-registered but registry exposes _register, create them (gauge then counter)
                            _reg_fn = getattr(_reg_nf3, '_register', None)
                            if _m_need_full_active is None and callable(_reg_fn):
                                try:
                                    _m_need_full_active = _reg_fn(
                                        'events',
                                        'events_need_full_active',
                                        'gauge',
                                        'Client currently in need_full state (1 active / 0 normal)',
                                    )
                                except Exception:
                                    _m_need_full_active = None
                            if _m_need_full_episodes is None and callable(_reg_fn):
                                try:
                                    _m_need_full_episodes = _reg_fn(
                                        'events',
                                        'events_need_full_episodes_total',
                                        'counter',
                                        'Distinct need_full episodes (false->true transitions)',
                                    )
                                except Exception:
                                    _m_need_full_episodes = None
                            # Set gauge value
                            if _m_need_full_active is not None:
                                try:
                                    getattr(
                                        _m_need_full_active,
                                        'set',
                                        lambda *_a, **_k: None,
                                    )(1 if need_full_flag else 0)
                                except Exception:
                                    pass
                            # Increment episodes counter on transition to active
                            if need_full_flag and not sse_need_full_active_prev and _m_need_full_episodes is not None:
                                try:
                                    getattr(_m_need_full_episodes, 'inc', lambda *_a, **_k: None)()
                                except Exception:
                                    pass
                        except Exception:
                            pass
                        sse_need_full_active_prev = need_full_flag
                    # Adaptive stream enrichment moved to plugin ingestion path
                    if now - last_res >= res_refresh:
                        try:
                            latest = cache.refresh()
                            if latest and isinstance(latest, dict) and isinstance(effective_status, dict):
                                if "resources" in latest:
                                    effective_status["resources"] = latest.get("resources")
                        except Exception:
                            pass
                        last_res = now
                    try:
                        from scripts.summary.derive import derive_cycle as _dc
                        cy = _dc(effective_status)
                        ld = cy.get("last_duration")
                        if isinstance(ld, (int, float)):
                            window.append(float(ld))
                    except Exception:
                        pass

                    # Build in-mem panels mapping (provider/resources/loop/indices/adaptive_alerts)
                    # for optional model assembly
                    in_memory_panels: dict[str, Any] = {}
                    try:
                        if isinstance(effective_status, dict):
                            prov_panel = effective_status.get('provider')
                            if isinstance(prov_panel, dict):
                                in_memory_panels['provider'] = prov_panel
                            res_panel = effective_status.get('resources')
                            if isinstance(res_panel, dict):
                                in_memory_panels['resources'] = res_panel
                            loop_panel = effective_status.get('loop')
                            if isinstance(loop_panel, dict):
                                in_memory_panels['loop'] = loop_panel
                            # Indices detail -> indices panel
                            idx_detail = effective_status.get('indices_detail')
                            if isinstance(idx_detail, dict):
                                in_memory_panels['indices'] = idx_detail
                            # Adaptive alerts (mirror expected file panel name adaptive_alerts)
                            adaptive_alerts = effective_status.get('adaptive_alerts')
                            if isinstance(adaptive_alerts, dict):
                                in_memory_panels['adaptive_alerts'] = adaptive_alerts
                            # If severity snapshots exist but no adaptive_alerts panel, synthesize minimal
                            if 'adaptive_alerts' not in in_memory_panels:
                                adaptive_stream = effective_status.get('adaptive_stream')
                                if isinstance(adaptive_stream, dict):
                                    synth: dict[str, Any] = {}
                                    sc = adaptive_stream.get('severity_counts')
                                    if isinstance(sc, dict):
                                        synth['severity_counts'] = sc
                                    fu = adaptive_stream.get('followup_alerts')
                                    if isinstance(fu, list):
                                        synth['followups_recent'] = fu[-10:]
                                    if synth:
                                        in_memory_panels['adaptive_alerts'] = synth
                    except Exception:
                        in_memory_panels = {}

                    # Optional unified model build (lightweight) using in-memory panels to avoid FS reads
                    try:
                        if env.rich_diff_demo_enabled:  # repurpose flag for model build demo gating (temporary)
                            from src.summary.unified.model import (
                                assemble_model_snapshot as _assemble_model_live,
                            )
                            model_live, _diag_live = _assemble_model_live(
                                runtime_status=effective_status,
                                panels_dir=env.panels_dir,
                                include_panels=True,
                                in_memory_panels=in_memory_panels,
                            )
                            # Attach a minimal subset into panel_push_meta (avoid heavy duplication)
                            meta_bucket_live = (
                                effective_status.setdefault('panel_push_meta', {})
                                if isinstance(effective_status.get('panel_push_meta'), dict)
                                else effective_status.setdefault('panel_push_meta', {})
                            )
                            if isinstance(meta_bucket_live, dict):
                                model_meta: dict[str, Any] = {
                                    'cycle': model_live.cycle.number,
                                    'schema_version': model_live.schema_version,
                                    'dq': {
                                        'g': model_live.dq.green,
                                        'w': model_live.dq.warn,
                                        'e': model_live.dq.error,
                                    },
                                }
                                meta_bucket_live['unified_model'] = model_meta
                    except Exception:
                        pass

                    refresh_layout(
                        layout,
                        effective_status,
                        args.status_file,
                        args.metrics_url,
                        rolling=compute_roll(),
                        compact=bool(args.compact),
                        low_contrast=bool(args.low_contrast),
                    )
                    # Stable subset signature (default anti-flicker): cycle, indices set, alerts count, severity counts
                    try:
                        from scripts.summary.derive import derive_cycle as _dc
                        from scripts.summary.derive import derive_indices as _dinds
                        cy2 = _dc(effective_status)
                        cycle_val = cy2.get('cycle') or cy2.get('count')
                        if isinstance(cycle_val, (int,float)):
                            cycle_part = f"c={int(cycle_val)}"
                        else:
                            cycle_part = f"c={cycle_val}"
                        try:
                            indices_list = _dinds(effective_status)
                        except Exception:
                            indices_list = []
                        indices_part = ",".join(sorted([i.upper() for i in indices_list]))
                        alerts_total = None
                        if isinstance(effective_status, dict):
                            alerts_val = effective_status.get('alerts')
                            if isinstance(alerts_val, list):
                                alerts_total = len(alerts_val)
                        sev_counts = None
                        adaptive_stream = (
                            effective_status.get('adaptive_stream')
                            if isinstance(effective_status, dict)
                            else None
                        )
                        if (
                            isinstance(adaptive_stream, dict)
                            and isinstance(adaptive_stream.get('severity_counts'), dict)
                        ):
                            sev = adaptive_stream['severity_counts']
                            sev_counts = f"sc={sev.get('info',0)}-{sev.get('warn',0)}-{sev.get('critical',0)}"
                        parts = [cycle_part, f"idx={indices_part}"]
                        if alerts_total is not None:
                            parts.append(f"a={alerts_total}")
                        if sev_counts:
                            parts.append(sev_counts)
                        render_sig = "|".join(parts)
                        # Fallback path only if subset somehow empty
                        if not render_sig:
                            from scripts.summary import snapshot_builder as _sb
                            sig = _sb.compute_snapshot_signature(effective_status)
                            if sig:
                                render_sig = sig
                    except Exception:
                        render_sig = last_render_sig or "*"
                    if render_sig != last_render_sig:
                        live.update(layout, refresh=False)
                        live.refresh()
                        last_render_sig = render_sig
                    else:
                        # Increment skip counter metric if available and signature flag enabled
                        try:
                            from scripts.summary import snapshot_builder as _sb2
                            m = getattr(_sb2, '_get_refresh_skipped_metric', lambda: None)()
                            if m is not None:
                                try:
                                    m.inc()
                                except Exception:
                                    pass
                        except Exception:
                            pass
                    time.sleep(max(0.1, args.refresh))
                except KeyboardInterrupt:  # noqa: PERF203 - intentional try/except inside loop for graceful exit
                    raise
                except Exception as e:
                    # Soft-fail: print a short notice and back off, then continue
                    try:
                        handle_ui_error(e, component="summary_app", context={"op": "loop"})
                    except Exception:
                        pass
                    try:
                        out.error(f"Summary loop error: {e}", scope="summary_view")
                    except Exception:
                        pass
                    try:
                        back_ms = float(os.getenv("G6_SUMMARY_LOOP_BACKOFF_MS", "300") or "300")
                    except Exception:
                        back_ms = 300.0
                    time.sleep(max(0.05, back_ms / 1000.0))
    # Normal termination path (loop returns via KeyboardInterrupt handled inside loop)
    return 0

if __name__ == "__main__":
    raise SystemExit(run())
