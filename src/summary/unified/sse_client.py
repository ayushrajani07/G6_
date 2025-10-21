"""SSE ingestion scaffolding (Phase 1).

Non-goals: full reconnect logic, auth headers, compression, production backoff.
Focus: minimal event parsing + in-memory panel state application using merge_panel_diff.

Environment flags (initial):
- G6_PANELS_SSE_URL: if set, SSEPanelsIngestor plugin activates.
- G6_PANELS_SSE_DEBUG: verbose logging when 'on'.

Event Format (expected minimal JSON lines):
  data: {"panel":"indices","diff":{...}}
  data: {"panel":"adaptive_alerts","full":{...}}

We treat 'full' as replacement, 'diff' as deep merge via merge_panel_diff.
Unknown panels are stored under their given name.
"""
from __future__ import annotations

import http.client
import io
import json
import logging
import os
import threading
import time
import urllib.parse
from typing import Any

from .sse import merge_panel_diff

logger = logging.getLogger(__name__)

TRUE_SET = {"1","true","yes","on"}

def _env_true(name: str) -> bool:
    v = os.getenv(name, "").strip().lower()
    return v in TRUE_SET

class PanelStateStore:
    """Thread-safe in-memory panel snapshot store.

    Public methods are lock protected; retrieval returns shallow copies to avoid
    accidental mutation by callers.
    """
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._panels: dict[str, Any] = {}
        self._gen = 0  # generation counter (increment on any update)
        # Hold registry reference (lazy fetched) for unified metrics
        self._metrics_ref = None  # populated on first use

    def _metrics(self) -> object | None:  # pragma: no cover - trivial accessor
        ref = self._metrics_ref
        if ref is None:
            try:
                from src.metrics import get_metrics as _get_metrics  # type: ignore
                ref = _get_metrics()
            except Exception:  # noqa: BLE001
                ref = None
            self._metrics_ref = ref
        return ref

    def apply_full(self, panel: str, payload: Any) -> None:
        with self._lock:
            m = self._metrics()
            self._panels[panel] = payload
            self._gen += 1
            try:
                c = getattr(m, 'sse_apply_full_total', None)
                if c is not None:
                    c.inc()
            except Exception:  # noqa: BLE001
                pass

    def apply_diff(self, panel: str, diff_obj: Any) -> None:
        with self._lock:
            m = self._metrics()
            base = self._panels.get(panel)
            merged = merge_panel_diff(base, diff_obj) if base is not None else diff_obj
            self._panels[panel] = merged
            self._gen += 1
            try:
                c = getattr(m, 'sse_apply_diff_total', None)
                if c is not None:
                    c.inc()
            except Exception:  # noqa: BLE001
                pass

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            # Return shallow copies of dict-valued panels to reduce accidental mutations
            out: dict[str, Any] = {}
            for k, v in self._panels.items():
                if isinstance(v, dict):
                    out[k] = dict(v)
                else:
                    out[k] = v
            out['__generation__'] = self._gen
            return out

    def generation(self) -> int:
        with self._lock:
            return self._gen

class SSEClient(threading.Thread):  # pragma: no cover - network/UI side effects
    """Minimal blocking SSE client reading from a URL.

    Implemented using http.client to avoid extra dependency. For production
    robustness consider using 'requests' with stream=True or an async variant.
    """
    def __init__(self, url: str, store: PanelStateStore, *, reconnect_delay: float = 3.0, timeout: float = 30.0, debug: bool = False, max_backoff: float = 60.0) -> None:
        super().__init__(daemon=True)
        self._url = url
        self._store = store
        self._base_reconnect_delay = reconnect_delay
        self._timeout = timeout
        self._debug = debug
        self._stop = threading.Event()
        self._max_backoff = max_backoff
        # Backoff state
        self._attempt = 0
        # Metrics registry ref (lazy)
        self._metrics_ref = None

    def _metrics(self) -> object | None:  # pragma: no cover
        ref = self._metrics_ref
        if ref is None:
            try:
                from src.metrics import get_metrics as _get_metrics  # type: ignore
                ref = _get_metrics()
            except Exception:  # noqa: BLE001
                ref = None
            self._metrics_ref = ref
        return ref

    def _next_backoff(self) -> float:
        # Exponential backoff with decorrelated jitter (based on AWS architecture blog variant)
        import random
        if self._attempt == 0:
            self._attempt = 1
            return self._base_reconnect_delay
        # prev cap doubling but limited by max_backoff
        prev = self._base_reconnect_delay * (2 ** (self._attempt - 1))
        cap = min(self._max_backoff, prev * 2)
        sleep = random.uniform(self._base_reconnect_delay, cap)
        self._attempt += 1
        return min(sleep, self._max_backoff)

    def _record_backoff(self, seconds: float) -> None:
        try:
            m = self._metrics()
            h = getattr(m, 'sse_backoff_seconds', None)
            if h is not None:
                h.observe(seconds)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass

    def _inc_reconnect(self, reason: str) -> None:
        try:
            m = self._metrics()
            c = getattr(m, 'sse_reconnects_total', None)
            if c is not None:
                c.labels(reason=reason).inc()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:  # noqa: D401
        parsed = urllib.parse.urlparse(self._url)
        scheme = parsed.scheme or 'http'
        while not self._stop.is_set():
            try:
                conn_cls = http.client.HTTPSConnection if scheme == 'https' else http.client.HTTPConnection
                host = parsed.hostname or parsed.netloc or ''
                if not host:
                    raise RuntimeError('invalid SSE URL host')
                conn = conn_cls(host, parsed.port or (443 if scheme=='https' else 80), timeout=self._timeout)
                path = parsed.path or '/'
                if parsed.query:
                    path += '?' + parsed.query
                headers = {
                    'Accept': 'text/event-stream',
                    'Cache-Control': 'no-cache',
                    'Connection': 'keep-alive',
                }
                conn.request('GET', path, headers=headers)
                resp = conn.getresponse()
                if resp.status != 200:
                    self._inc_reconnect("status_" + str(resp.status))
                    if self._debug:
                        logger.warning("SSE non-200 status=%s", resp.status)
                    delay = self._next_backoff()
                    self._record_backoff(delay)
                    time.sleep(delay)
                    continue
                # Successful connection -> reset backoff attempt counter
                self._attempt = 0
                buf = io.TextIOWrapper(resp, encoding='utf-8')  # type: ignore[arg-type]
                event_data_lines: list[str] = []
                for line in buf:
                    if self._stop.is_set():
                        break
                    line = line.rstrip('\n')
                    if line.startswith(':'):  # comment/heartbeat
                        continue
                    if not line:
                        if event_data_lines:
                            self._handle_event_data('\n'.join(event_data_lines))
                            event_data_lines = []
                        continue
                    if line.startswith('data:'):
                        event_data_lines.append(line[5:].strip())
                conn.close()
                # Treat normal loop exit (EOF) as reconnect attempt
                if not self._stop.is_set():
                    self._inc_reconnect("eof")
                    delay = self._next_backoff()
                    self._record_backoff(delay)
                    time.sleep(delay)
            except Exception as e:  # noqa: BLE001
                if self._debug:
                    logger.exception("SSE client error: %s", e)
                self._inc_reconnect("exception")
                delay = self._next_backoff()
                self._record_backoff(delay)
                time.sleep(delay)
        if self._debug:
            logger.info("SSE client thread exiting")

    def _handle_event_data(self, data_block: str) -> None:
        try:
            # Multiple data: lines concatenated with newlines -> join to single JSON
            payload = json.loads(data_block)
            if not isinstance(payload, dict):
                return
            panel = payload.get('panel')
            if not isinstance(panel, str):
                return
            if 'full' in payload:
                self._store.apply_full(panel, payload['full'])
            elif 'diff' in payload:
                self._store.apply_diff(panel, payload['diff'])
            else:
                # treat everything else as full replacement
                self._store.apply_full(panel, payload)
        except Exception:
            if self._debug:
                logger.exception("Failed to handle SSE event data len=%s", len(data_block))

__all__ = ["PanelStateStore", "SSEClient"]
