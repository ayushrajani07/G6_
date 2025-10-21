"""StreamGaterPlugin
=====================

Phase 1 plugin implementing legacy `indices_stream` cadence gating + heartbeat emission
inside the unified summary loop. Enabled when environment variable
`G6_UNIFIED_STREAM_GATER` is truthy (1/true/yes/on).

Responsibilities:
- Maintain last seen cycle and/or minute bucket (persisted to `.indices_stream_state.json`).
- Decide whether to append new indices_stream entries each cycle.
- Build stream items using existing helpers (best-effort) mirroring legacy format.
- Inject derived `time_hms` convenience field (IST HH:MM:SS) if possible.
- Emit heartbeat update (bridge.last_publish) into system panel (merge semantics) without
  overwriting unrelated keys.
- Expose Prometheus-style counters via the shared metrics registry if available.

Metrics (incremented lazily if prometheus_client available):
- g6_stream_append_total{mode}
- g6_stream_skipped_total{mode,reason}
- g6_stream_state_persist_errors_total
- g6_stream_conflict_total (heuristic potential concurrent writer)

The plugin is conservative: failures never raise; they log at debug and continue.
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import threading
from collections.abc import Mapping
from typing import Any

from .base import OutputPlugin, SummarySnapshot

logger = logging.getLogger(__name__)

_GATE_FILE = ".indices_stream_state.json"

# One-time warning sentinels. We prefer attaching state to the logger so that
# even if this module is imported via distinct package paths (creating separate
# module objects and thus separate globals), the shared logger instance (keyed
# by name) prevents duplicate emissions.
_FLAGS_WARNED = False  # legacy global fallback
_FLAGS_WARNED_LOCK = threading.Lock()
if not hasattr(logger, '_flags_warned_once'):
    logger._flags_warned_once = False  # type: ignore[attr-defined]

_TRUTHY = {"1","true","yes","on"}

def _env_truthy(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return str(v).lower() in _TRUTHY

class StreamGaterPlugin(OutputPlugin):
    name = "stream_gater"

    def __init__(self) -> None:
        self._panels_dir: str | None = None
        self._loaded_state = False
        self._last_cycle: int | None = None
        self._last_bucket: str | None = None
        self._gate_mode: str = "auto"  # auto|cycle|minute|bucket
        # Metrics handles (resolved lazily)
        self._metrics_bound = False
        # Metric family handles (counters) – may support labels via .labels(...)
        self._m_append = None
        self._m_skipped = None
        self._m_state_err = None
        self._m_conflict = None  # incremented if concurrent legacy bridge usage inferred

    # --- Metrics binding helpers --------------------------------------------------
    def _bind_metrics(self) -> None:
        if self._metrics_bound:
            return
        try:  # pragma: no cover - best effort instrumentation
            from prometheus_client import REGISTRY, Counter  # type: ignore

            def _get_or_create(name: str, doc: str, labels: tuple[str, ...] | None = None) -> Any:
                prom_name = name
                existing = getattr(REGISTRY, '_names_to_collectors', {})  # type: ignore[attr-defined]
                coll = existing.get(prom_name) if isinstance(existing, dict) else None
                if coll is not None:
                    return coll
                try:
                    if labels:
                        return Counter(prom_name, doc, labels)  # type: ignore[return-value]
                    return Counter(prom_name, doc)  # type: ignore[return-value]
                except ValueError:
                    # Race: created by another thread
                    existing2 = getattr(REGISTRY, '_names_to_collectors', {})  # type: ignore[attr-defined]
                    return existing2.get(prom_name)
                except Exception:  # noqa: BLE001
                    return None

            # Option A: explicit *_total naming to align with spec & catalog.
            self._m_append = _get_or_create(
                'g6_stream_append_total',
                'Total indices_stream append events (labels: mode)',
                ('mode',),
            )
            self._m_skipped = _get_or_create(
                'g6_stream_skipped_total',
                'Total indices_stream skips (labels: mode,reason)',
                ('mode', 'reason'),
            )
            self._m_state_err = _get_or_create(
                'g6_stream_state_persist_errors_total',
                'State file persistence errors',
            )
            self._m_conflict = _get_or_create(
                'g6_stream_conflict_total',
                'Detected potential indices_stream write conflict',
            )
            # Backward compatibility: if earlier base-name counters exist, do nothing; we deliberately
            # do not alias to avoid double counting. Historical scrape continuity is acceptable since
            # *_total metrics are new for Phase 1/2 rollout.
        except Exception:
            # Swallow – metrics optional
            pass
        self._metrics_bound = True

    # --- State persistence ---------------------------------------------------------
    def _state_path(self) -> str | None:
        if not self._panels_dir:
            return None
        return os.path.join(self._panels_dir, _GATE_FILE)

    def _load_state(self) -> None:
        if self._loaded_state:
            return
        self._loaded_state = True
        path = self._state_path()
        if not path:
            return
        try:
            if os.path.exists(path):
                with open(path, encoding='utf-8') as f:
                    obj = json.load(f)
                if isinstance(obj, dict):
                    lc = obj.get('last_cycle')
                    lb = obj.get('last_bucket')
                    if isinstance(lc, (int,float)):
                        self._last_cycle = int(lc)
                    if isinstance(lb, str):
                        self._last_bucket = lb
        except Exception:
            # Corrupt state; ignore (optionally increment metric)
            try:
                if self._m_state_err is not None:
                    self._m_state_err.inc()  # type: ignore[attr-defined]
            except Exception:
                pass

    def _persist_state(self) -> None:
        path = self._state_path()
        if not path:
            return
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            payload: dict[str, int | str] = {}
            if isinstance(self._last_cycle, int):
                payload['last_cycle'] = self._last_cycle
            if isinstance(self._last_bucket, str):
                payload['last_bucket'] = self._last_bucket
            if payload:
                tmp = path + '.tmp'
                with open(tmp, 'w', encoding='utf-8') as f:
                    json.dump(payload, f)
                os.replace(tmp, path)
        except Exception:
            try:
                if self._m_state_err is not None:
                    self._m_state_err.inc()  # type: ignore[attr-defined]
            except Exception:
                pass

    # --- Derivations ---------------------------------------------------------------
    def _extract_cycle_bucket(self, status: Mapping[str, Any]) -> tuple[int | None, str | None]:
        cur_cycle = None
        bucket = None
        try:
            loop = status.get('loop') if isinstance(status.get('loop'), Mapping) else None
            if isinstance(loop, Mapping):
                c = loop.get('cycle') or loop.get('number')
                if isinstance(c, (int,float)):
                    cur_cycle = int(c)
                # last_run or last_start minute bucket
                ts = loop.get('last_run') or loop.get('last_start')
                bucket = self._to_minute_bucket(ts)
            if cur_cycle is None:
                # top-level cycle shape
                cyc = status.get('cycle')
                if isinstance(cyc, Mapping):
                    n = cyc.get('number') or cyc.get('cycle')
                    if isinstance(n, (int,float)):
                        cur_cycle = int(n)
            if bucket is None:
                bucket = self._to_minute_bucket(status.get('timestamp'))
        except Exception:
            pass
        return cur_cycle, bucket

    def _to_minute_bucket(self, ts: Any) -> str | None:
        if not ts:
            return None
        try:
            if isinstance(ts, (int,float)):
                dt = _dt.datetime.fromtimestamp(float(ts), tz=_dt.UTC)
            elif isinstance(ts, str):
                # Accept already UTC ISO with Z or offset
                dt = _dt.datetime.fromisoformat(ts.replace('Z','+00:00'))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=_dt.UTC)
            elif isinstance(ts, _dt.datetime):
                dt = ts if ts.tzinfo else ts.replace(tzinfo=_dt.UTC)
            else:
                return None
            dt_utc = dt.astimezone(_dt.UTC)
            return dt_utc.strftime('%Y-%m-%dT%H:%MZ')
        except Exception:
            return None

    def _decorate_time_hms(self, item: dict[str, Any]) -> None:
        try:
            raw_ts = item.get('time') or item.get('ts') or item.get('timestamp')
            if not raw_ts:
                return
            if isinstance(raw_ts, (int,float)):
                dt = _dt.datetime.fromtimestamp(float(raw_ts), tz=_dt.UTC)
            elif isinstance(raw_ts, str):
                dt = _dt.datetime.fromisoformat(raw_ts.replace('Z','+00:00'))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=_dt.UTC)
            else:
                return
            ist = dt.astimezone(_dt.timezone(_dt.timedelta(hours=5, minutes=30)))
            item['time_hms'] = ist.strftime('%H:%M:%S')
        except Exception:
            pass

    # --- Heartbeat -----------------------------------------------------------------
    def _emit_heartbeat(self, status_mut: dict[str, Any]) -> None:
        try:
            now_iso = _dt.datetime.now(_dt.UTC).isoformat().replace('+00:00','Z')
        except Exception:
            # Fallback: avoid forbidden direct UTC naive timestamp helper (policy disallows datetime.utcnow)
            try:
                now_iso = _dt.datetime.now(_dt.UTC).replace(microsecond=0).isoformat().replace('+00:00','Z')
            except Exception:
                now_iso = '1970-01-01T00:00:00Z'
        bridge_meta = {
            'last_publish': {
                'metric': 'last_publish',
                'value': now_iso,
                'status': 'OK'
            }
        }
        system_panel = status_mut.get('system') if isinstance(status_mut.get('system'), dict) else None
        if not isinstance(system_panel, dict):
            system_panel = {}
            status_mut['system'] = system_panel
        bridge_block = system_panel.get('bridge') if isinstance(system_panel.get('bridge'), dict) else None
        if not isinstance(bridge_block, dict):
            system_panel['bridge'] = bridge_meta['last_publish']
        else:
            # merge
            bridge_block.update(bridge_meta['last_publish'])

    # --- Main API ------------------------------------------------------------------
    def setup(self, context: Mapping[str, Any]) -> None:  # pragma: no cover minimal side-effects
        self._panels_dir = context.get('panels_dir') if isinstance(context.get('panels_dir'), str) else None
        self._gate_mode = (os.getenv('G6_STREAM_GATE_MODE','auto').strip().lower() or 'auto')
        self._bind_metrics()

    def process(self, snap: SummarySnapshot) -> None:
        # Phase 4: always active. Retired flags produce a one-time warning only.
        global _FLAGS_WARNED  # noqa: PLW0603 (explicitly modifying module sentinel)
        try:
            # Double-checked locking to avoid emitting duplicate warnings under rare
            # concurrent first-call invocation scenarios.
            if (
                not getattr(logger, '_flags_warned_once', False)
                and (os.getenv('G6_UNIFIED_STREAM_GATER') or os.getenv('G6_DISABLE_UNIFIED_GATER'))
            ):
                with _FLAGS_WARNED_LOCK:
                    if not getattr(logger, '_flags_warned_once', False):
                        logger.warning(
                            "[stream_gater] Flags G6_UNIFIED_STREAM_GATER / G6_DISABLE_UNIFIED_GATER "
                            "are retired and ignored (always enabled)."
                        )
                        logger._flags_warned_once = True  # type: ignore[attr-defined]
                        # keep global in sync for completeness
                        _FLAGS_WARNED = True
        except Exception:
            # Defensive: never let logging guard raise
            pass
        try:
            status_obj = snap.status if isinstance(snap.status, Mapping) else {}
            if not isinstance(status_obj, Mapping):  # defensive
                return
            # We mutate a shallow copy to avoid surprising other plugins that iterate keys
            if not isinstance(status_obj, dict):  # ensure mutability
                try:
                    status_obj = dict(status_obj)  # type: ignore[assignment]
                except Exception:
                    return
            self._load_state()
            cur_cycle, cur_bucket = self._extract_cycle_bucket(status_obj)
            should_append = True
            reason = None
            if self._gate_mode in ('auto','cycle') and isinstance(cur_cycle, int):
                should_append = (self._last_cycle != cur_cycle)
                if not should_append:
                    reason = 'same_cycle'
            elif self._gate_mode in ('auto','minute','bucket') and isinstance(cur_bucket, str):
                should_append = (self._last_bucket != cur_bucket)
                if not should_append:
                    reason = 'same_bucket'
            # Append logic
            if should_append:
                items = self._build_stream_items(status_obj)
                if items:
                    # Write/append file JSON – we rely on PanelsWriter pattern (list payload) for indices_stream.json
                    pre_len = self._existing_stream_length()
                    self._append_indices_stream(items)
                    # Update state (only after successful append)
                    if isinstance(cur_cycle, int):
                        self._last_cycle = cur_cycle
                    if isinstance(cur_bucket, str):
                        self._last_bucket = cur_bucket
                    self._persist_state()
                    # Metric: append
                    try:
                        if self._m_append is not None:
                            inc_lbl = getattr(self._m_append, 'labels', None)
                            if callable(inc_lbl):
                                inc_lbl(mode=self._gate_mode).inc()  # type: ignore[attr-defined]
                            else:
                                self._m_append.inc()  # type: ignore[attr-defined]
                        # Conflict heuristic: if stream file existed with newer mtime within same
                        # cycle and pre_len changed unexpectedly (duplicate cycle append)
                        if (
                            self._m_conflict is not None
                            and reason is None
                            and not should_append
                            and pre_len is not None
                        ):
                            pass  # nothing (heuristic disabled here – see conflict block below)
                    except Exception:
                        pass
            else:
                # Metric: skipped
                try:
                    if self._m_skipped is not None:
                        # treat skipped_total as counter with labels via helper _inc(labels)
                        # if such API exists (best-effort)
                        inc_fn = getattr(self._m_skipped, 'labels', None)
                        if callable(inc_fn):
                            inc_fn(mode=self._gate_mode, reason=reason or 'unknown').inc()  # type: ignore[attr-defined]
                        else:
                            self._m_skipped.inc()  # type: ignore[attr-defined]
                except Exception:
                    pass
            # Heartbeat always emitted (even if skipped) to provide freshness signal
            try:
                if isinstance(status_obj, dict):
                    self._emit_heartbeat(status_obj)
            except Exception:
                pass
            # Simple conflict detection: if legacy bridge also wrote indices_stream.json in the same
            # cycle (detected by presence of 'time_hms' missing or duplicate index without new cycle)
            try:
                if self._m_conflict is not None and should_append and isinstance(cur_cycle, int):
                    # If we appended but the new last item lacks time_hms while prior items have it,
                    # suggests a competing writer pattern
                    path = self._stream_path()
                    if path and os.path.exists(path):
                        with open(path,encoding='utf-8') as f:
                            arr = json.load(f)
                        if isinstance(arr, list) and len(arr) >= 2:
                            last = arr[-1]
                            prev = arr[-2]
                            if isinstance(last, dict) and isinstance(prev, dict):
                                if ('time_hms' not in last) and ('time_hms' in prev):
                                    self._m_conflict.inc()  # type: ignore[attr-defined]
            except Exception:
                pass
        except Exception as e:  # noqa: BLE001
            logger.debug("stream_gater process error: %s", e)

    # --- Helpers -------------------------------------------------------------------
    def _stream_path(self) -> str | None:
        if not self._panels_dir:
            return None
        return os.path.join(self._panels_dir, 'indices_stream.json')

    def _append_indices_stream(self, items: list[dict[str, Any]]) -> None:
        path = self._stream_path()
        if not path:
            return
        existing: list[dict[str, Any]] = []
        try:
            if os.path.exists(path):
                with open(path, encoding='utf-8') as f:
                    obj = json.load(f)
                if isinstance(obj, list):
                    existing = obj
                elif isinstance(obj, dict):
                    # Legacy variant (panel wrapper) – attempt to unwrap
                    inner = obj.get('data') if isinstance(obj.get('data'), list) else None
                    if isinstance(inner, list):
                        existing = inner
        except Exception:
            existing = []
        existing.extend(items)
        cap = 50
        if len(existing) > cap:
            existing = existing[-cap:]
        try:
            tmp = path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(existing, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except Exception:
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(existing, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

    def _existing_stream_length(self) -> int | None:
        path = self._stream_path()
        if not path or not os.path.exists(path):
            return None
        try:
            with open(path,encoding='utf-8') as f:
                obj = json.load(f)
            if isinstance(obj, list):
                return len(obj)
            if isinstance(obj, dict):
                data_field = obj.get('data')
                if isinstance(data_field, list):
                    return len(data_field)
        except Exception:
            return None
        return None

    def _build_stream_items(self, status: Mapping[str, Any]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        # Attempt to leverage indices_panel via indices_detail structure
        try:
            indices_detail = status.get('indices_detail') if isinstance(status.get('indices_detail'), Mapping) else {}
            if isinstance(indices_detail, Mapping):
                for name, data in indices_detail.items():  # type: ignore[assignment]
                    if not isinstance(data, Mapping):
                        continue
                    item = {
                        'index': name,
                        'status': data.get('status'),
                        'dq_score': (
                            (data.get('dq') or {}).get('score_percent')
                            if isinstance(data.get('dq'), Mapping)
                            else None
                        ),
                        'time': (
                            data.get('last_update')
                            or data.get('timestamp')
                            or status.get('timestamp')
                        ),
                    }
                    self._decorate_time_hms(item)
                    items.append(item)
        except Exception:
            pass
        return items

    def teardown(self) -> None:  # pragma: no cover - minimal
        return

__all__ = ["StreamGaterPlugin"]
