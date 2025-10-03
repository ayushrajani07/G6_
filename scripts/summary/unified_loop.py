"""Unified summary + panels prototype loop (skeleton).

Phase 1 goal: integrate with existing summary_view derivation and rendering
without changing external behavior unless --unified passed.
"""
from __future__ import annotations

import time
import logging
import json
import os
from typing import List, Mapping, Any, Iterable, Optional

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
            if os.getenv("G6_PANELS_SSE_URL") and not any(getattr(p, 'name', '') == 'sse_panels_ingestor' for p in pl):
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
        path = os.getenv("G6_SUMMARY_STATUS_FILE", "data/runtime_status.json")
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data  # narrow to concrete dict for builder
                return None
        except Exception:
            return None

    def _build_snapshot(self) -> SummarySnapshot:
        # Phase 1 adapter: leverage snapshot_builder for core fields; map to generic SummarySnapshot.
        status = self._read_status()  # concrete dict or None
        now = time.time()
        panels_dir = self._panels_dir if (self._panels_dir and os.path.isdir(self._panels_dir)) else None
        # Use build_frame_snapshot only if status present or panels directory exists (to avoid unnecessary work)
        derived: Mapping[str, Any] = {}
        panel_map: Mapping[str, Any] = {}
        errors: List[str] = []
        try:
            if status is not None or panels_dir:
                frame = snapshot_builder.build_frame_snapshot(status, panels_dir=panels_dir)
                # Convert frame dataclass to dict for derived: keep semantic grouping minimal for now
                derived = {
                    "cycle": frame.cycle.cycle,
                    "indices_count": len(frame.indices),
                    "alerts_total": frame.alerts.total,
                    "memory_rss_mb": frame.memory.rss_mb,
                    "panels_mode": frame.panels_mode,
                }
                # Panels placeholder: future phases will build structured panel outputs prior to write
                panel_map = {"_legacy_panels_mode": frame.panels_mode}
        except Exception as e:  # noqa: BLE001
            logger.exception("Snapshot build failure (unified loop)")
            errors.append(str(e))
        # Phase 2: Attempt unified model assembly (dual emission). Failures do not block legacy fields.
        model_obj = None
        try:
            if status is not None or panels_dir:
                from src.summary.unified.model import assemble_model_snapshot  # local import
                model_obj, _diag = assemble_model_snapshot(runtime_status=status or {}, panels_dir=panels_dir, include_panels=True)
        except Exception as e:  # noqa: BLE001
            logger.debug("Unified model assembly failed (dual emission fallback): %s", e)
        snap = SummarySnapshot(
            status=status or {},
            derived=derived,
            panels=panel_map,
            ts_read=now,
            ts_built=time.time(),
            cycle=self._cycle,
            errors=tuple(errors),
            model=model_obj,
        )
        return snap

    def run(self, cycles: int | None = None) -> None:  # pragma: no cover - loop skeleton
        self._running = True
        ctx = {"panels_dir": self._panels_dir}
        for p in self._plugins:
            try:
                p.setup(ctx)
            except Exception as e:  # noqa: BLE001
                logger.exception("Plugin %s setup failed: %s", p.name, e)
        # Identify metrics plugin (optional)
        metrics_plugin: MetricsEmitter | None = None
        for p in self._plugins:
            if isinstance(p, MetricsEmitter):  # type: ignore[arg-type]
                metrics_plugin = p
                break
        while self._running:
            start = time.time()
            self._cycle += 1
            build_start = time.time()
            snap = self._build_snapshot()
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
            elapsed = time.time() - start
            sleep_for = max(0.0, self._refresh - elapsed)
            # Emit cycle-level metrics last
            if metrics_plugin is not None:
                metrics_plugin.observe_cycle(elapsed, build_dur, errors=len(snap.errors))
            if cycles is not None and self._cycle >= cycles:
                break
            if sleep_for:
                time.sleep(sleep_for)
        for p in self._plugins:
            try:
                p.teardown()
            except Exception:  # pragma: no cover - defensive
                logger.exception("Plugin %s teardown failed", p.name)

__all__ = ["UnifiedLoop"]
