"""Unified summary + panels prototype loop (skeleton).

Phase 1 goal: integrate with existing summary_view derivation and rendering
without changing external behavior unless --unified passed.
"""
from __future__ import annotations

import json
import logging
import os
import signal
import time
from collections.abc import Iterable, Mapping
from typing import Any

from . import (
    snapshot_builder,  # reuse existing builder for status-driven fields
)
from .config import SummaryConfig
from .env_config import load_summary_env
from .plugins.base import MetricsEmitter, OutputPlugin, SummarySnapshot

logger = logging.getLogger(__name__)

class UnifiedLoop:
    def __init__(self, plugins: Iterable[OutputPlugin], panels_dir: str, refresh: float = 1.0) -> None:
        pl = list(plugins)
        # Auto-activate SSEPanelsIngestor if endpoint configured and not already present
        try:
            env = load_summary_env()
            if env.client_sse_url and not any(getattr(p, 'name', '') == 'sse_panels_ingestor' for p in pl):
                from .plugins.sse_panels import SSEPanelsIngestor  # type: ignore
                pl.append(SSEPanelsIngestor())
        except Exception:
            logger.debug("SSEPanelsIngestor activation skipped (import or env failure)")
        # Phase 4: StreamGaterPlugin always active (flags retired). Insert immediately after PanelsWriter if present.
        try:  # pragma: no cover - plugin wiring
            already_gater = any(getattr(p,'name','') == 'stream_gater' for p in pl)
            if not already_gater:
                pw_index = None
                for i, _p in enumerate(pl):
                    if getattr(_p, 'name', '') == 'panels_writer':
                        pw_index = i
                        break
                from .plugins.stream_gater import StreamGaterPlugin  # type: ignore
                if pw_index is not None:
                    try:
                        pl.insert(pw_index + 1, StreamGaterPlugin())
                    except Exception:
                        pl.append(StreamGaterPlugin())
                else:
                    pl.append(StreamGaterPlugin())
        except Exception:
            logger.debug("StreamGaterPlugin activation skipped (import failure)")
        self._plugins = pl
        self._refresh = refresh
        self._panels_dir = panels_dir
        self._cycle = 0
        self._running = False
        # Eager-start unified HTTP (if enabled) to avoid test races where the
        # loop thread hasn't yet executed the server startup code.
        try:
            env0 = load_summary_env(force_reload=True)
            if env0.unified_http_enabled:
                try:
                    from .unified_http import serve_unified_http
                    serve_unified_http(port=env0.unified_http_port)
                    # brief readiness
                    try:
                        import socket as _sock
                        import time as _t
                        for _i in range(10):
                            s = _sock.socket()
                            s.settimeout(0.05)
                            try:
                                s.connect(("127.0.0.1", env0.unified_http_port))
                                s.close()
                                break
                            except Exception:
                                try:
                                    s.close()
                                except Exception:
                                    pass
                                _t.sleep(0.05)
                    except Exception:
                        pass
                except Exception:
                    logger.debug("Unified HTTP eager start failed (init phase)")
        except Exception:
            pass

    def _read_status(self) -> dict[str, Any] | None:
        env = load_summary_env()  # status file path stable; no need to force reload each cycle
        path = env.status_file
        # Prefer centralized StatusReader (cached + robust) with defensive fallback
        try:
            from src.utils.status_reader import get_status_reader  # type: ignore
        except Exception:
            get_status_reader = None  # type: ignore
        try:
            if get_status_reader is not None:
                reader = get_status_reader(path)
                data = reader.get_raw_status()
                return data if isinstance(data, dict) else None
            # Fallback: mtime-cached JSON read if available
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

    def _build_snapshot(self) -> SummarySnapshot:
        # Phase 2: domain-first snapshot (still populate legacy derived for backward compatibility)
        status = self._read_status()  # concrete dict or None
        now = time.time()
        panels_dir = self._panels_dir if (self._panels_dir and os.path.isdir(self._panels_dir)) else None
        errors: list[str] = []
        derived: Mapping[str, Any] = {}
        panel_map: Mapping[str, Any] = {}
        domain_obj = None
        try:
            if status is not None:
                from scripts.summary.domain import build_domain_snapshot  # local import
                domain_obj = build_domain_snapshot(status, ts_read=now)
                # Legacy derived map population from domain
                derived = {
                    "cycle": domain_obj.cycle.number,
                    "indices_count": domain_obj.coverage.indices_count,
                    "alerts_total": domain_obj.alerts.total,
                }
        except Exception as e:  # noqa: BLE001
            logger.exception("Domain snapshot build failure")
            errors.append(str(e))
        # Legacy frame builder for panels_mode / memory info still (transitional)
        try:
            if (status is not None or panels_dir):
                frame = snapshot_builder.build_frame_snapshot(status, panels_dir=panels_dir)
                derived = {**derived, **{
                    "memory_rss_mb": frame.memory.rss_mb,
                    "panels_mode": frame.panels_mode,
                }}
                panel_map = {"_legacy_panels_mode": frame.panels_mode}
        except Exception as e:  # noqa: BLE001
            logger.debug("Frame builder fallback failed: %s", e)
        model_obj = None
        try:
            if status is not None or panels_dir:
                from src.summary.unified.model import assemble_model_snapshot  # local import
                model_obj, _diag = assemble_model_snapshot(
                    runtime_status=status or {},
                    panels_dir=panels_dir,
                    include_panels=True,
                )
        except Exception as e:  # noqa: BLE001
            logger.debug("Unified model assembly failed (dual emission fallback): %s", e)
        # Phase 5: central panel hash computation (single source of truth)
        panel_hashes = None
        try:
            if domain_obj is not None:  # domain and raw status present
                from scripts.summary.hashing import compute_all_panel_hashes  # centralized
                panel_hashes = compute_all_panel_hashes(status, domain=domain_obj)
                # Inject into status meta for legacy plugins still reading there
                if isinstance(status, dict):
                    meta_field = status.get('panel_push_meta')
                    meta = meta_field if isinstance(meta_field, dict) else status.setdefault('panel_push_meta', {})
                    if isinstance(meta, dict):
                        meta.setdefault('shared_hashes', panel_hashes)
        except Exception as e:  # noqa: BLE001
            logger.debug("Central hash computation failed (will rely on plugin fallback): %s", e)
            panel_hashes = None
        return SummarySnapshot(
            status=status or {},
            derived=derived,
            panels=panel_map,
            ts_read=now,
            ts_built=time.time(),
            cycle=self._cycle,
            errors=tuple(errors),
            model=model_obj,
            domain=domain_obj,
            panel_hashes=panel_hashes,
        )

    def run(self, cycles: int | None = None) -> None:  # pragma: no cover - loop skeleton
        self._running = True
        # Graceful shutdown flag local to loop
        shutdown_requested = {"v": False}
        diag_timing = os.getenv("G6_SUMMARY_DIAG_TIMING") == "1"
        max_seconds_env = os.getenv("G6_SUMMARY_MAX_SECONDS")
        max_cycles_env = os.getenv("G6_SUMMARY_MAX_CYCLES")
        hard_start = time.time()
        try:
            max_seconds = float(max_seconds_env) if max_seconds_env else None
        except Exception:  # pragma: no cover - defensive
            max_seconds = None
        try:
            max_cycles_override = int(max_cycles_env) if max_cycles_env else None
        except Exception:  # pragma: no cover
            max_cycles_override = None

        def _handle_signal(signum: int, frame: Any) -> None:  # noqa: ANN001
            if not shutdown_requested["v"]:
                logger.debug("UnifiedLoop received signal %s; initiating graceful shutdown", signum)
            shutdown_requested["v"] = True

        for sig in (getattr(signal, 'SIGINT', None), getattr(signal, 'SIGTERM', None)):
            if sig is not None:
                try:
                    signal.signal(sig, _handle_signal)  # type: ignore[arg-type]
                except Exception:
                    pass
        ctx = {"panels_dir": self._panels_dir}
        # Load centralized config (Phase 7 auto-enable semantics)
        cfg = SummaryConfig.load()
        # Force reload so tests that just set env vars (e.g., G6_SSE_HTTP=1) before constructing
        # the loop observe correct toggles even if a prior test populated the cache.
        env = load_summary_env(force_reload=True)
        unified_http_mode = env.unified_http_enabled
        # Start unified HTTP ASAP (before plugin setup) to minimize test timing races
        unified_started = False
        if unified_http_mode and not unified_started:
            try:
                from .unified_http import serve_unified_http
                serve_unified_http(port=env.unified_http_port)
                # Readiness probe (extended) to ensure port is listening before tests connect
                try:
                    import socket as _sock
                    import time as _t
                    for _i in range(20):  # ~1s total (20 * 0.05)
                        for _host in ("127.0.0.1", "localhost"):
                            s = _sock.socket()
                            s.settimeout(0.05)
                            try:
                                s.connect((_host, env.unified_http_port))
                                s.close()
                                unified_started = True
                                break
                            except Exception:
                                try:
                                    s.close()
                                except Exception:
                                    pass
                                continue
                        if unified_started:
                            break
                        _t.sleep(0.05)
                except Exception:
                    unified_started = True  # best effort
                logger.debug("Unified HTTP server active (early start)")
            except Exception as e:  # noqa: BLE001
                logger.debug("Failed to start unified HTTP server (early): %s", e)
        # Optional resync HTTP server activation (skip if unified HTTP running)
        if cfg.resync_http and not unified_http_mode:
            try:
                from .http_resync import serve_resync  # lazy import
                srv = serve_resync()
                logger.debug(
                    "Resync HTTP server started on port %s (auto-enable)%s",
                    srv.server_address[1],
                    f" override={env.resync_http_port}" if env.resync_http_port else "",
                )
            except Exception as e:  # noqa: BLE001
                logger.debug("Resync HTTP server start failed: %s", e)
        # Optional standalone metrics HTTP server
        if env.metrics_http_enabled:
            try:
                from .metrics_server import start_metrics_server
                start_metrics_server()
            except Exception:
                logger.debug("Metrics HTTP server start failed")
        for p in self._plugins:
            try:
                p.setup(ctx)
            except Exception as e:  # noqa: BLE001, PERF203 - intentional defensive isolation per plugin
                logger.exception("Plugin %s setup failed: %s", p.name, e)
        # Identify metrics plugin (optional)
        metrics_plugin: MetricsEmitter | None = None
        sse_publisher = None
        for p in self._plugins:
            if isinstance(p, MetricsEmitter):  # type: ignore[arg-type]
                metrics_plugin = p
            try:
                from .plugins.sse import SSEPublisher  # local import
                if isinstance(p, SSEPublisher):  # type: ignore[arg-type]
                    sse_publisher = p
            except Exception:
                pass
        # Optional SSE HTTP server
        if sse_publisher is not None:
            try:
                from .sse_http import set_publisher
                set_publisher(sse_publisher)
            except Exception:
                pass
        # Unified HTTP server (consolidated SSE, resync, metrics, health)
        if unified_http_mode and not unified_started:
            try:
                from .unified_http import serve_unified_http
                serve_unified_http(port=env.unified_http_port)
                # Brief readiness probe to avoid connection races in fast tests
                try:
                    import socket as _sock
                    import time as _t
                    for _i in range(20):  # ~1s total
                        ok = False
                        for _host in ("127.0.0.1", "localhost"):
                            s = _sock.socket()
                            s.settimeout(0.05)
                            try:
                                s.connect((_host, env.unified_http_port))
                                s.close()
                                ok = True
                                break
                            except Exception:
                                try:
                                    s.close()
                                except Exception:
                                    pass
                                continue
                        if ok:
                            break
                        _t.sleep(0.05)
                except Exception:
                    pass
                logger.debug("Unified HTTP server active (env G6_UNIFIED_HTTP)")
            except Exception as e:  # noqa: BLE001
                logger.debug("Failed to start unified HTTP server: %s", e)
        else:
            # Legacy separate SSE HTTP path (will be retired once unified stabilized)
            if sse_publisher is not None and env.sse_http_enabled:
                try:
                    from .sse_http import serve_sse_http
                    serve_sse_http(port=env.sse_http_port)
                    try:
                        # Diagnostic sentinel for tests to confirm server start path executed
                        with open(
                            os.path.join(
                                self._panels_dir or '.',
                                f".sse_http_started_{env.sse_http_port}",
                            ),
                            'w',
                            encoding='utf-8',
                        ) as _f:
                            _f.write(str(time.time()))
                    except Exception:
                        pass
                    # Brief readiness window to avoid race in fast tests immediately connecting
                    try:
                        import socket
                        import time as _t
                        for _i in range(10):  # up to ~250ms (10 * 0.025)
                            s = socket.socket()
                            s.settimeout(0.05)
                            try:
                                s.connect(("127.0.0.1", env.sse_http_port))
                                s.close()
                                break
                            except Exception:
                                s.close()
                                _t.sleep(0.025)
                    except Exception:
                        pass
                    logger.debug("SSE HTTP endpoint active (env G6_SSE_HTTP)")
                except Exception as e:  # noqa: BLE001
                    logger.debug("Failed to start SSE HTTP endpoint: %s", e)
        while self._running and not shutdown_requested["v"]:
            start = time.time()
            self._cycle += 1
            if diag_timing:
                print(f"[summary-diag] cycle={self._cycle} start t={start - hard_start:0.3f}s")
            if max_cycles_override is not None and self._cycle > max_cycles_override:
                if diag_timing:
                    print(f"[summary-diag] max cycles {max_cycles_override} reached -> break")
                break
            build_start = time.time()
            snap = self._build_snapshot()
            if cfg.resync_http:
                try:
                    from .http_resync import set_last_snapshot  # type: ignore
                    set_last_snapshot(snap)
                except Exception:
                    pass
            build_dur = time.time() - build_start
            plugin_errors: dict[str, bool] = {}
            for p in self._plugins:
                proc_start = time.time()
                had_err = False
                try:
                    p.process(snap)
                except Exception as e:  # noqa: BLE001
                    had_err = True
                    logger.exception("Plugin %s process error: %s", p.name, e)
                finally:
                    duration = time.time() - proc_start
                    plugin_errors[p.name] = had_err
                    if metrics_plugin is not None and p is not metrics_plugin:
                        # record per plugin including panels & terminal; metrics plugin self-process is noop
                        metrics_plugin.observe_plugin(p.name, duration, had_err)
                # Observe SSE metrics if both plugins present
                try:
                    if metrics_plugin is not None:
                        from .plugins.sse import SSEPublisher  # local import to avoid hard dep
                        for p in self._plugins:
                            if isinstance(p, SSEPublisher):  # type: ignore[arg-type]
                                metrics_plugin.observe_sse_metrics(p.metrics_snapshot())
                                break
                except Exception:
                    pass
            elapsed = time.time() - start
            sleep_for = max(0.0, self._refresh - elapsed)
            # Emit cycle-level metrics last
            if metrics_plugin is not None:
                metrics_plugin.observe_cycle(elapsed, build_dur, errors=len(snap.errors))
            if diag_timing:
                print(
                    f"[summary-diag] cycle={self._cycle} "
                    f"build_dur={build_dur:0.4f}s total_elapsed={elapsed:0.4f}s "
                    f"sleep_for={sleep_for:0.4f}s"
                )
            if max_seconds is not None and (time.time() - hard_start) >= max_seconds:
                if diag_timing:
                    print(f"[summary-diag] max seconds {max_seconds}s exceeded -> break")
                break
            if shutdown_requested["v"]:
                break
            if cycles is not None and self._cycle >= cycles:
                break
            if sleep_for:
                time.sleep(sleep_for)
        # Loop exiting: previously broadcast an immediate SSE bye which caused late
        # test connections to see only 'bye' without backlog events. Suppressed to
        # allow late readers to consume hello/full_snapshot from publisher backlog.
        self._running = False
        # Optional controlled bye emission (opt-in) to signal clean end to connected clients
        import os as _os
        _emit_bye = _os.getenv('G6_SSE_BYE_ON_SHUTDOWN', '0').lower() in {'1','true','yes','on'}
        sse_pub = None
        if _emit_bye:
            try:
                from .plugins.sse import SSEPublisher  # local import
                for p in self._plugins:
                    if isinstance(p, SSEPublisher):  # type: ignore[arg-type]
                        sse_pub = p
                        break
            except Exception:
                sse_pub = None
            if sse_pub is not None:
                try:
                    # Use internal _emit method if present to maintain counters; fallback append
                    if hasattr(sse_pub, '_emit'):
                        sse_pub._emit({'event':'bye','data':{'reason':'shutdown','cycle':self._cycle}})  # type: ignore[attr-defined]
                    else:
                        sse_pub.events.append({'event':'bye','data':{'reason':'shutdown','cycle':self._cycle}})
                except Exception:
                    pass
        for p in self._plugins:
            try:
                p.teardown()
            except Exception:  # pragma: no cover - defensive  # noqa: PERF203
                # Intentional defensive cleanup per plugin
                logger.exception("Plugin %s teardown failed", p.name)

__all__ = ["UnifiedLoop"]
