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
from typing import Any, Dict, Optional, Mapping
import threading, time, json, os, logging, io, http.client, urllib.parse

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
        self._panels: Dict[str, Any] = {}
        self._gen = 0  # generation counter (increment on any update)
        # Lazy metrics family refs (populated on first use if available & env gate)
        self._metrics_tried = False
        self._m_full = None
        self._m_diff = None

    def _ensure_metrics(self) -> None:
        if self._metrics_tried:
            return
        self._metrics_tried = True
        try:
            if os.getenv("G6_UNIFIED_METRICS", "0").lower() in {"1","true","yes","on"}:
                from prometheus_client import Counter  # type: ignore
                self._m_full = Counter("g6_sse_apply_full_total", "Count of full panel replacements")
                self._m_diff = Counter("g6_sse_apply_diff_total", "Count of diff panel merges")
        except Exception:
            self._m_full = None
            self._m_diff = None

    def apply_full(self, panel: str, payload: Any) -> None:
        with self._lock:
            self._ensure_metrics()
            self._panels[panel] = payload
            self._gen += 1
            if self._m_full:
                try: self._m_full.inc()  # type: ignore[attr-defined]
                except Exception: pass

    def apply_diff(self, panel: str, diff_obj: Any) -> None:
        with self._lock:
            self._ensure_metrics()
            base = self._panels.get(panel)
            merged = merge_panel_diff(base, diff_obj) if base is not None else diff_obj
            self._panels[panel] = merged
            self._gen += 1
            if self._m_diff:
                try: self._m_diff.inc()  # type: ignore[attr-defined]
                except Exception: pass

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            # Return shallow copies of dict-valued panels to reduce accidental mutations
            out: Dict[str, Any] = {}
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
        # Metrics (lazy init)
        self._metrics_tried = False
        self._m_reconnects = None
        self._m_backoff = None

    def _ensure_metrics(self) -> None:
        if self._metrics_tried:
            return
        self._metrics_tried = True
        try:
            if os.getenv("G6_UNIFIED_METRICS", "0").lower() in {"1","true","yes","on"}:
                from prometheus_client import Counter, Histogram  # type: ignore
                self._m_reconnects = Counter("g6_sse_reconnects_total", "Number of SSE reconnect attempts", ["reason"])  # type: ignore
                self._m_backoff = Histogram("g6_sse_backoff_seconds", "Backoff sleep duration seconds")  # type: ignore
        except Exception:
            self._m_reconnects = None
            self._m_backoff = None

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
        if self._m_backoff:
            try: self._m_backoff.observe(seconds)  # type: ignore[attr-defined]
            except Exception: pass

    def _inc_reconnect(self, reason: str) -> None:
        if self._m_reconnects:
            try: self._m_reconnects.labels(reason=reason).inc()  # type: ignore[attr-defined]
            except Exception: pass

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:  # noqa: D401
        parsed = urllib.parse.urlparse(self._url)
        scheme = parsed.scheme or 'http'
        self._ensure_metrics()
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
                event_data_lines = []
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
