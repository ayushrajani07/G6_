"""SSE Panels Ingestor Plugin

Standalone plugin version using internal simple SSE loop and PanelStateStore.
This replaces earlier experimental implementation referencing sse_client to
avoid tight coupling and hidden threads.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Mapping
from datetime import UTC
from typing import Any, Callable
from urllib import error as _er
from urllib import parse as _parse
from urllib import request as _rq

from scripts.summary.sse_state import PanelStateStore

from .base import OutputPlugin, SummarySnapshot

logger = logging.getLogger(__name__)

class SSEPanelsIngestor(OutputPlugin):  # pragma: no cover - network IO side effects
    name = "sse_panels_ingestor"

    def __init__(self) -> None:
        self._url = os.getenv("G6_PANELS_SSE_URL")
        self._types = os.getenv("G6_PANELS_SSE_TYPES", "panel_full,panel_diff")
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._store = PanelStateStore()
        self._debug = os.getenv("G6_PANELS_SSE_DEBUG", "").lower() in {"1","true","yes","on"}
        self._last_event_id: int = 0
        self._metrics_enabled = os.getenv("G6_UNIFIED_METRICS", "").lower() in {"1","true","yes","on"}
        self._m_events = None
        self._m_errors = None
        self._m_latency = None
        self._m_hb_stale = None
        self._m_hb_health = None

    def _init_metrics(self) -> None:
        if not self._metrics_enabled or self._m_events is not None:
            return
        try:
            from prometheus_client import Counter, Gauge, Histogram
            self._m_events = Counter(
                "g6_sse_ingestor_events_total",
                "SSE panel events processed",
                ["type"],
            )  # type: ignore[attr-defined]
            self._m_errors = Counter(
                "g6_sse_ingestor_errors_total",
                "SSE ingest errors",
            )  # type: ignore[attr-defined]
            self._m_latency = Histogram(
                "g6_sse_ingestor_apply_seconds",
                "Latency applying SSE event",
                buckets=[0.001, 0.002, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5],
            )  # type: ignore[attr-defined]
            self._m_hb_stale = Gauge(
                "g6_sse_heartbeat_stale_seconds",
                "Seconds since last SSE event (panels ingestor)",
            )  # type: ignore[attr-defined]
            self._m_hb_health = Gauge(
                "g6_sse_heartbeat_health",
                "Heartbeat health state (enum: 0=init,1=ok,2=warn,3=stale)",
            )  # type: ignore[attr-defined]
        except Exception:
            self._metrics_enabled = False

    def setup(self, context: Mapping[str, Any]) -> None:
        if not self._url:
            return
        self._init_metrics()
        self._thread = threading.Thread(target=self._loop, name="g6-sse-panels", daemon=True)
        self._thread.start()
        logger.info("SSEPanelsIngestor started url=%s", self._url)

    def process(self, snap: SummarySnapshot) -> None:
        # Inject counters into snapshot for UI uniformity
        _st, srv_gen, ui_gen, need_full, counters, sev_counts, sev_state, followups = self._store.snapshot()
        hb = self._store.heartbeat()
        status = snap.status
        # Optional overlay: replace/merge snapshot.status with SSE store baseline when enabled.
        # This allows live panel data even if the underlying status file is stale or absent.
        overlay_enabled = os.getenv('G6_PANELS_SSE_OVERLAY','').lower() in {'1','true','yes','on'}
        strict_overlay = os.getenv('G6_PANELS_SSE_STRICT','').lower() in {'1','true','yes','on'}
        if overlay_enabled and isinstance(_st, dict):
            try:
                if strict_overlay:
                    # Replace entire status object with SSE baseline (authoritative)
                    if isinstance(status, dict):
                        # Clear then update to preserve reference used elsewhere
                        status.clear()
                        for k, v in _st.items():
                            status[k] = v
                    else:
                        if hasattr(snap, 'status'):
                            snap.status.clear()  # type: ignore[attr-defined]
                            snap.status.update(_st)  # type: ignore[attr-defined]
                else:
                    # Merge mode: SSE keys overwrite known dynamic sections only
                    if isinstance(status, dict):
                        for k, v in _st.items():
                            if k not in status:
                                status[k] = v
                            else:
                                if k in ('indices_detail','alerts','events','analytics','memory','loop'):
                                    status[k] = v
                    else:
                        if hasattr(snap, 'status'):
                            snap.status.clear()  # type: ignore[attr-defined]
                            snap.status.update(_st)  # type: ignore[attr-defined]
            except Exception:
                pass
        if isinstance(status, dict):
            meta = status.get('panel_push_meta')
            if not isinstance(meta, dict):
                meta = {}
                status['panel_push_meta'] = meta
            if isinstance(meta, dict):
                meta['sse_events'] = counters
                if overlay_enabled:
                    meta['overlay_mode'] = 'strict' if strict_overlay else 'merge'
                else:
                    meta['overlay_mode'] = 'off'
                # Flag whether overlay appears active (received at least one full or diff)
                try:
                    full_ct = counters.get('panel_full', 0)
                    diff_ct = counters.get('panel_diff', 0)
                    meta['overlay_active'] = bool(full_ct or diff_ct)
                except Exception:
                    meta['overlay_active'] = False
                if srv_gen is not None:
                    meta['panel_generation'] = srv_gen
                if hb:
                    # Embed heartbeat with compact key names to limit bloat
                    meta['sse_heartbeat'] = {
                        'last_evt': hb.get('last_event_epoch'),
                        'last_full': hb.get('last_panel_full_epoch'),
                        'last_diff': hb.get('last_panel_diff_epoch'),
                        'stale_sec': hb.get('stale_seconds'),
                        'health': hb.get('health'),
                    }
                    # Metrics update (best-effort)
                    if self._metrics_enabled and self._m_hb_stale is not None and hb.get('stale_seconds') is not None:
                        try:
                            self._m_hb_stale.set(float(hb['stale_seconds']))  # type: ignore[attr-defined]
                        except Exception:
                            pass
                    if self._metrics_enabled and self._m_hb_health is not None:
                        code_map = {'init':0,'ok':1,'warn':2,'stale':3}
                        try:
                            self._m_hb_health.set(code_map.get(hb.get('health'), -1))  # type: ignore[attr-defined]
                        except Exception:
                            pass
                if sev_counts:
                    adaptive_bucket = status.get('adaptive_stream')
                    if not isinstance(adaptive_bucket, dict):
                        adaptive_bucket = {}
                        status['adaptive_stream'] = adaptive_bucket
                    adaptive_bucket['severity_counts'] = sev_counts
                if sev_state:
                    adaptive_bucket = status.get('adaptive_stream')
                    if not isinstance(adaptive_bucket, dict):
                        adaptive_bucket = {}
                        status['adaptive_stream'] = adaptive_bucket
                    adaptive_bucket['severity_state'] = sev_state
                if followups:
                    adaptive_bucket = status.get('adaptive_stream')
                    if not isinstance(adaptive_bucket, dict):
                        adaptive_bucket = {}
                        status['adaptive_stream'] = adaptive_bucket
                    adaptive_bucket['followup_alerts'] = followups
                if need_full:
                    meta['need_full'] = True
                    reasons = []
                    try:
                        if hasattr(self._store, 'pop_need_full_reasons'):
                            reasons = self._store.pop_need_full_reasons()
                    except Exception:
                        reasons = []
                    if reasons:
                        meta['need_full_reasons'] = reasons
                        meta.setdefault('need_full_reason', reasons[-1])
                    else:
                        meta.setdefault('need_full_reason', 'snapshot_required')
                else:
                    meta.pop('need_full', None)
                    meta.pop('need_full_reason', None)
                    meta.pop('need_full_reasons', None)

    def teardown(self) -> None:
        self._stop.set()
        if self._thread:
            try:
                self._thread.join(timeout=2.0)
            except Exception:
                pass
        logger.info("SSEPanelsIngestor stopped")

    # ---------------- internal loop -----------------
    def _loop(self) -> None:
        backoff = 1.0
        types = [t.strip() for t in self._types.split(',') if t.strip()]
        while not self._stop.is_set():
            try:
                url = self._build_url(types)
                req = _rq.Request(url, headers={'Accept': 'text/event-stream'})
                if self._last_event_id:
                    req.add_header('Last-Event-ID', str(self._last_event_id))
                with _rq.urlopen(req, timeout=float(os.getenv('G6_PANELS_SSE_TIMEOUT','45'))) as resp:
                    backoff = 1.0
                    data_lines: list[str] = []
                    event_label: str | None = None
                    event_id_local: int | None = None
                    for raw in resp:
                        if self._stop.is_set():
                            break
                        try:
                            line = raw.decode('utf-8').rstrip('\r\n')
                        except Exception:
                            continue
                        if line == '':
                            if data_lines:
                                self._dispatch_event(event_label, '\n'.join(data_lines), event_id_local)
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
            except (_er.URLError, _er.HTTPError, TimeoutError) as exc:
                if self._debug:
                    logger.warning("SSEPanelsIngestor reconnect in %.1fs: %s", backoff, exc)
            except Exception as exc:  # noqa: BLE001
                logger.exception("SSEPanelsIngestor loop error: %s", exc)
            if self._stop.wait(backoff):
                break
            backoff = min(backoff * 2.0, 30.0)

    def _build_url(self, types: list[str]) -> str:
        try:
            parsed = _parse.urlparse(self._url or '')
        except Exception:
            parsed = _parse.urlparse(self._url or '', scheme='http')
        qs = dict(_parse.parse_qsl(parsed.query, keep_blank_values=True))
        if types:
            qs['types'] = ','.join(types)
        if self._last_event_id:
            qs['last_id'] = str(self._last_event_id)
        new_query = _parse.urlencode(qs, doseq=True)
        return _parse.urlunparse(parsed._replace(query=new_query))

    def _dispatch_event(self, label: str | None, data_block: str, event_id_local: int | None) -> None:
        try:
            payload = json.loads(data_block)
        except Exception:
            return
        if isinstance(event_id_local, int):
            self._last_event_id = event_id_local
        ev_type = payload.get('type') or label
        # Normalize alternate / vendor-specific event type names
        if isinstance(ev_type, str):
            low = ev_type.lower()
            if low in {'full','panelfull','panel_full_event','panel_full'}:
                ev_type = 'panel_full'
            elif low in {'diff','paneldiff','panel_diff_event','panel_diff'}:
                ev_type = 'panel_diff'
            elif low in {'severity','severitystate'}:
                ev_type = 'severity_state'
        inner = payload.get('payload') if isinstance(payload.get('payload'), dict) else None
        # Fallback: many feeds emit root-level objects without a 'payload' wrapper.
        # If so, treat the entire payload as inner for recognized event types.
        if inner is None:
            # Heuristic: if payload already contains keys typical for an inner block, reuse it.
            likely_keys = (
                'status',
                'diff',
                'counts',
                'alert',
                'alert_type',
                'severity',
                'index',
            )
            if isinstance(payload, dict) and any(k in payload for k in likely_keys):
                inner = payload  # type: ignore[assignment]
        if inner is None:
            # As a last resort, if there is no explicit type but root keys look like a full or diff, infer.
            if ev_type is None and isinstance(payload, dict):
                if 'status' in payload:
                    ev_type = 'panel_full'
                    inner = payload
                elif 'diff' in payload:
                    ev_type = 'panel_diff'
                    inner = payload
        if inner is None:
            if self._debug:
                logger.debug(
                    "SSEPanelsIngestor ignored event (no inner) type=%s keys=%s",
                    ev_type,
                    list(payload.keys()) if isinstance(payload, dict) else '?',
                )
            return
        try:
            gen_val = payload.get('generation')
            gen_int = int(gen_val) if isinstance(gen_val, (int,float,str)) and str(gen_val).isdigit() else None
        except Exception:
            gen_int = None
        if ev_type == 'panel_full':
            # Accept status via inner['status'] or alias keys (e.g., inner['panel_full'])
            status_obj = None
            if isinstance(inner, dict):
                if isinstance(inner.get('status'), dict):
                    status_obj = inner.get('status')
                elif isinstance(inner.get('panel_full'), dict):
                    status_obj = inner.get('panel_full')
            if status_obj:
                self._apply_metrics(
                    'panel_full',
                    lambda: self._store.apply_panel_full(status_obj, gen_int),
                )
            elif self._debug:
                logger.debug(
                    "panel_full missing status object keys=%s",
                    list(inner.keys()) if isinstance(inner, dict) else '?',
                )
        elif ev_type == 'panel_diff':
            diff_obj = None
            if isinstance(inner, dict):
                if isinstance(inner.get('diff'), dict):
                    diff_obj = inner.get('diff')
                elif isinstance(inner.get('panel_diff'), dict):
                    diff_obj = inner.get('panel_diff')
            if diff_obj:
                self._apply_metrics(
                    'panel_diff',
                    lambda: self._store.apply_panel_diff(diff_obj, gen_int),
                )
            elif self._debug:
                logger.debug(
                    "panel_diff missing diff object keys=%s",
                    list(inner.keys()) if isinstance(inner, dict) else '?',
                )
        elif ev_type == 'severity_state':
            # counts + specific alert type state
            counts_obj = inner.get('counts') if isinstance(inner.get('counts'), dict) else None
            if counts_obj:
                try:
                    self._store.update_severity_counts(counts_obj)
                except Exception:
                    pass
            alert_type = inner.get('alert_type')
            if isinstance(alert_type, str):
                try:
                    self._store.update_severity_state(alert_type, inner)
                except Exception:
                    pass
        elif ev_type == 'severity_counts':
            counts_obj = inner.get('counts') if isinstance(inner.get('counts'), dict) else None
            if counts_obj:
                try:
                    self._store.update_severity_counts(counts_obj)
                except Exception:
                    pass
        elif ev_type == 'followup_alert':
            inner_alert = inner.get('alert') if isinstance(inner.get('alert'), dict) else {}
            idx = inner_alert.get('index') if isinstance(inner_alert, dict) else inner.get('index')
            alert_type = inner_alert.get('type') if isinstance(inner_alert, dict) else inner.get('type')
            sev_val = inner_alert.get('severity') if isinstance(inner_alert, dict) else inner.get('severity')
            if isinstance(sev_val, str):
                level = sev_val.upper()
            else:
                level = 'INFO'
            ts_epoch = inner.get('ts')
            if isinstance(ts_epoch, (int, float)):
                try:
                    from datetime import datetime
                    ts_iso = datetime.fromtimestamp(ts_epoch, tz=UTC).isoformat()
                except Exception:
                    from datetime import datetime
                    ts_iso = datetime.now(UTC).isoformat()
            else:
                from datetime import datetime
                ts_iso = datetime.now(UTC).isoformat()
            message = inner.get('message')
            if isinstance(inner_alert, dict):
                inner_msg = inner_alert.get('message')
                if inner_msg:
                    message = inner_msg
            if not message:
                message = f"{alert_type or 'followup'} triggered"
            component = "Follow-up"
            if alert_type:
                component = f"Follow-up {alert_type}"
            if idx:
                component = f"{component} {idx}"
            entry = {
                'time': ts_iso,
                'level': level,
                'component': component,
                'message': str(message),
            }
            try:
                self._store.add_followup_alert(entry)
            except Exception:
                pass
        else:
            if self._debug:
                logger.debug(
                    "Unhandled SSE event type=%s keys=%s",
                    ev_type,
                    list(inner.keys()) if isinstance(inner, dict) else '?',
                )

    def _apply_metrics(self, ev_type: str, fn: Callable[[], Any]) -> None:
        start = time.time()
        try:
            fn()
            if self._metrics_enabled and self._m_events is not None:
                try:
                    self._m_events.labels(ev_type).inc()  # type: ignore[attr-defined]
                except Exception:
                    pass
        except Exception:
            if self._metrics_enabled and self._m_errors is not None:
                try:
                    self._m_errors.inc()  # type: ignore[attr-defined]
                except Exception:
                    pass
        finally:
            if self._metrics_enabled and self._m_latency is not None:
                try:
                    self._m_latency.observe(time.time() - start)  # type: ignore[attr-defined]
                except Exception:
                    pass

__all__ = ["SSEPanelsIngestor"]
