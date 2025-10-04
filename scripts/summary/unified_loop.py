"""Unified summary + panels prototype loop (skeleton).

Phase 1 goal: integrate with existing summary_view derivation and rendering
without changing external behavior unless --unified passed.
"""
from __future__ import annotations

import time
import signal
import logging
import json
import os
import hashlib
from typing import List, Mapping, Any, Iterable, Optional
from .env_config import load_summary_env
from .config import SummaryConfig

from .plugins.base import OutputPlugin, SummarySnapshot, MetricsEmitter
from .plugins import base as plugin_base
from . import snapshot_builder  # reuse existing builder for status-driven fields
from . import bridge_detection

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
        self._plugins = pl
        self._refresh = refresh
        self._panels_dir = panels_dir
        self._cycle = 0
        self._running = False

    def _read_status(self) -> Optional[dict[str, Any]]:
        env = load_summary_env()  # status file path stable; no need to force reload each cycle
        path = env.status_file
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data  # narrow to concrete dict for builder
                return None
        except Exception:
            return None

    def _build_snapshot(self) -> SummarySnapshot:
        # Phase 2: domain-first snapshot (still populate legacy derived for backward compatibility)
        status = self._read_status()  # concrete dict or None
        now = time.time()
        panels_dir = self._panels_dir if (self._panels_dir and os.path.isdir(self._panels_dir)) else None
        errors: List[str] = []
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
                model_obj, _diag = assemble_model_snapshot(runtime_status=status or {}, panels_dir=panels_dir, include_panels=True)
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

        def _handle_signal(signum, frame):  # noqa: ANN001
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
        # Optional resync HTTP server activation (skip if unified HTTP running)
        if cfg.resync_http and not unified_http_mode:
            try:
                from .http_resync import serve_resync  # lazy import
                srv = serve_resync()
                logger.debug("Resync HTTP server started on port %s (auto-enable)%s", srv.server_address[1], f" override={env.resync_http_port}" if env.resync_http_port else "")
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
            except Exception as e:  # noqa: BLE001
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
        if unified_http_mode:
            try:
                from .unified_http import serve_unified_http
                serve_unified_http(port=env.unified_http_port)
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
                        with open(os.path.join(self._panels_dir or '.', f".sse_http_started_{env.sse_http_port}"), 'w', encoding='utf-8') as _f:
                            _f.write(str(time.time()))
                    except Exception:
                        pass
                    # Brief readiness window to avoid race in fast tests immediately connecting
                    try:
                        import socket, time as _t
                        for _i in range(10):  # up to ~250ms (10 * 0.025)
                            s = socket.socket(); s.settimeout(0.05)
                            try:
                                s.connect(("127.0.0.1", env.sse_http_port))
                                s.close()
                                break
                            except Exception:
                                s.close(); _t.sleep(0.025)
                    except Exception:
                        pass
                    logger.debug("SSE HTTP endpoint active (env G6_SSE_HTTP)")
                except Exception as e:  # noqa: BLE001
                    logger.debug("Failed to start SSE HTTP endpoint: %s", e)
        while self._running and not shutdown_requested["v"]:
            start = time.time()
            self._cycle += 1
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
        for p in self._plugins:
            try:
                p.teardown()
            except Exception:  # pragma: no cover - defensive
                logger.exception("Plugin %s teardown failed", p.name)

__all__ = ["UnifiedLoop"]
