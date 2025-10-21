from __future__ import annotations

import re
import threading
import time
import urllib.request
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from src.error_handling import ErrorCategory, ErrorSeverity, get_error_handler
from src.types.dashboard_types import (
    ErrorEvent,
    FooterSummary,
    HistoryEntry,
    HistoryStorage,
    RollState,
    StorageSnapshot,
    StreamRow,
)

METRIC_LINE_RE = re.compile(r"^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)\{?(?P<labels>[^}]*)}?\s+(?P<value>[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?\d+)?)")
LABEL_RE = re.compile(r"(\w+)=\"([^\"]*)\"")

@dataclass
class MetricSample:
    value: float
    labels: dict[str,str]

@dataclass
class ParsedMetrics:
    ts: float
    raw: dict[str, list[MetricSample]] = field(default_factory=dict)
    age_seconds: float = 0.0
    stale: bool = False
    # Stream row schema (narrow fields used by templates)
    stream_rows: list[StreamRow] = field(default_factory=list)
    footer: FooterSummary | dict[str, Any] = field(default_factory=dict)
    storage: StorageSnapshot | dict[str, Any] = field(default_factory=dict)
    error_events: list[ErrorEvent] = field(default_factory=list)
    # DEBUG_CLEANUP_BEGIN: store missing core metrics list for temporary banner
    missing_core: list[str] = field(default_factory=list)
    # DEBUG_CLEANUP_END

class MetricsCache:
    # Per-index rolling aggregation state: index -> numeric counters/meta
    _roll_index: dict[str, RollState]
    # History of (timestamp, partial_state) where partial_state may hold 'errors' or 'storage'
    _history: deque[tuple[float, HistoryEntry]]
    def __init__(self, endpoint: str, interval: float = 5.0, timeout: float = 1.5) -> None:
        self.endpoint = endpoint.rstrip('/')
        if not self.endpoint.endswith('/metrics'):
            self.endpoint += '/metrics'
        self.interval = interval
        self.timeout = timeout
        self._lock = threading.RLock()
        self._data: ParsedMetrics | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="metrics-cache", daemon=True)
        # Rolling per-index aggregation state
        self._roll_index: dict[str, RollState] = {}
        # History of (timestamp, partial_state dict)
        self._history = deque(maxlen=50)
        # DEBUG_CLEANUP_BEGIN: history & roll structures partly support temporary
        # diagnostic stream/status panels. If long-term retention not needed, these
        # can be simplified or removed. See markers throughout file.

    def start(self) -> None:
        if not self._thread.is_alive():
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def snapshot(self) -> ParsedMetrics | None:
        with self._lock:
            if self._data:
                # update age
                self._data.age_seconds = time.time() - self._data.ts
                self._data.stale = self._data.age_seconds > (self.interval * 4)
            return self._data

    def _fetch(self) -> ParsedMetrics:
        ts = time.time()
        try:
            with urllib.request.urlopen(self.endpoint, timeout=self.timeout) as resp:
                text = resp.read().decode('utf-8', errors='replace')
        except Exception as e:
            # Route network/endpoint fetch failure; caller will keep old data
            get_error_handler().handle_error(
                e,
                category=ErrorCategory.NETWORK,
                severity=ErrorSeverity.MEDIUM,
                component="web.metrics_cache",
                function_name="_fetch",
                message=f"Failed to fetch metrics from {self.endpoint}",
                context={"endpoint": self.endpoint, "timeout": self.timeout},
                should_log=False,
            )
            # Raise to let caller's try/except path keep old data
            raise
        parsed: dict[str,list[MetricSample]] = {}
        # DEBUG_CLEANUP_BEGIN: unknown line counter placeholder (no metrics registry in this process)
        unknown_lines = 0
        try:
            for line in text.splitlines():
                if not line or line.startswith('#'):
                    continue
                m = METRIC_LINE_RE.match(line)
                if not m:
                    unknown_lines += 1
                    continue
                name = m.group('name')
                labels_raw = m.group('labels')
                labels: dict[str,str] = {}
                if labels_raw:
                    for lm in LABEL_RE.finditer(labels_raw):
                        labels[lm.group(1)] = lm.group(2)
                try:
                    value = float(m.group('value'))
                except ValueError:
                    continue
                parsed.setdefault(name, []).append(MetricSample(value=value, labels=labels))
        except Exception as e:
            get_error_handler().handle_error(
                e,
                category=ErrorCategory.DATA_PARSING,
                severity=ErrorSeverity.LOW,
                component="web.metrics_cache",
                function_name="_fetch",
                message="Failed parsing metrics response",
                should_log=False,
            )
        pm = ParsedMetrics(ts=ts, raw=parsed)
        # DEBUG_CLEANUP_BEGIN: compute missing core metrics
        expected = {
            'g6_uptime_seconds','g6_collection_cycle_time_seconds','g6_options_processed_per_minute',
            'g6_collection_success_rate_percent','g6_api_success_rate_percent','g6_cpu_usage_percent',
            'g6_memory_usage_mb','g6_index_cycle_attempts','g6_index_cycle_success_percent',
            'g6_index_options_processed','g6_index_options_processed_total'
        }
        present = set(parsed.keys())
        pm.missing_core = sorted(list(expected - present))
        # DEBUG_CLEANUP_END
        try:
            self._augment_stream(pm)
            self._augment_storage(pm)
            self._augment_errors(pm)
        except Exception as e:
            get_error_handler().handle_error(
                e,
                category=ErrorCategory.CALCULATION,
                severity=ErrorSeverity.LOW,
                component="web.metrics_cache",
                function_name="_fetch",
                message="Augmentation failed",
                should_log=False,
            )
        return pm

    def _augment_stream(self, pm: ParsedMetrics) -> None:
        """Compute rolling stream-style rows similar to terminal dashboard.

        Uses metrics:
        - g6_index_options_processed
        - g6_index_success_rate_percent
        - g6_collection_errors_total (for recent error flag)
        """
        idx_opts = pm.raw.get('g6_index_options_processed', [])
        idx_cycle_attempts = pm.raw.get('g6_index_cycle_attempts', [])
        idx_cycle_success = pm.raw.get('g6_index_cycle_success_percent', [])
        idx_attempts_total = pm.raw.get('g6_index_attempts_total', [])
        idx_failures_total = pm.raw.get('g6_index_failures_total', [])
        idx_opts_cum = pm.raw.get('g6_index_options_processed_total', [])
        now_ts = pm.ts
        opts_map = {s.labels.get('index','?'): s.value for s in idx_opts}
        opts_cum_map = {s.labels.get('index','?'): s.value for s in idx_opts_cum}
        cycle_attempts_map = {s.labels.get('index','?'): s.value for s in idx_cycle_attempts}
        cycle_success_map = {s.labels.get('index','?'): s.value for s in idx_cycle_success}
        attempts_total_map = {s.labels.get('index','?'): s.value for s in idx_attempts_total}
        failures_total_map: dict[str, float] = {}
        for s in idx_failures_total:
            idx = s.labels.get('index','?')
            failures_total_map[idx] = failures_total_map.get(idx, 0.0) + s.value
        for name,val in opts_map.items():
            rs = self._roll_index.setdefault(name, {'legs_total':0.0,'legs_cycles':0,'succ_total':0.0,'succ_cycles':0,'last_err_ts':0.0,'last_err_type':''})
            rs['legs_total'] += val
            rs['legs_cycles'] += 1
        for name,val in cycle_success_map.items():
            rs = self._roll_index.setdefault(name, {'legs_total':0.0,'legs_cycles':0,'succ_total':0.0,'succ_cycles':0,'last_err_ts':0.0,'last_err_type':''})
            rs['succ_total'] += val
            rs['succ_cycles'] += 1
        # use Mapping for historical reference; may be underlying dict but we only read
        prev_errors: Mapping[str, float] = {}
        if self._history:
            _, prev_state = self._history[-1]
            # Discriminated union on 'kind'
            if isinstance(prev_state, dict) and prev_state.get('kind') == 'errors':  # legacy dict shape
                prev_errs_obj = prev_state.get('errors', {})
                if isinstance(prev_errs_obj, dict):
                    prev_errors = prev_errs_obj
        errs = pm.raw.get('g6_collection_errors_total', [])
        curr_errors_map: dict[str, float] = {}
        for e in errs:
            idx = e.labels.get('index','?')
            et = e.labels.get('error_type','err')
            key = f"{idx}|{et}"
            curr_errors_map[key] = e.value
            prev_val = prev_errors.get(key, 0.0)
            if e.value > prev_val:
                rs = self._roll_index.setdefault(idx, {'legs_total':0.0,'legs_cycles':0,'succ_total':0.0,'succ_cycles':0,'last_err_ts':0.0,'last_err_type':''})
                rs['last_err_ts'] = now_ts
                rs['last_err_type'] = et
        self._history.append((now_ts, {'kind': 'errors', 'errors': curr_errors_map}))
        rows: list[StreamRow] = []
        for name, rs in sorted(self._roll_index.items()):
            legs = opts_map.get(name, 0)
            legs_avg = (rs['legs_total']/rs['legs_cycles']) if rs['legs_cycles'] else 0
            cycle_attempts = cycle_attempts_map.get(name)
            succ = cycle_success_map.get(name)
            if cycle_attempts is not None and cycle_attempts <= 0:
                succ = None
            succ_avg = (rs['succ_total']/rs['succ_cycles']) if rs['succ_cycles'] else None
            lifetime_success = None
            at_tot = attempts_total_map.get(name)
            fl_tot = failures_total_map.get(name)
            if at_tot is not None and fl_tot is not None and at_tot > 0:
                lifetime_success = ((at_tot - fl_tot)/at_tot)*100.0
            err_recent = (now_ts - rs['last_err_ts']) < (self.interval * 3)
            # Stall heuristic: if legs==0 but historical cumulative is >0, mark a stall for visibility.
            cumulative = opts_cum_map.get(name)
            if legs == 0 and cumulative and cumulative > 0:
                rs['last_err_type'] = rs.get('last_err_type') or 'stall'
                err_recent = True
            try:
                from src.panels.helpers import compute_status_and_reason
                status, reason_opt = compute_status_and_reason(
                    success_pct=succ,
                    legs=int(legs) if isinstance(legs, (int, float)) else None,
                    err_recent=bool(err_recent),
                    err_type=rs.get('last_err_type'),
                    style='web',
                )
                reason = reason_opt or ''
            except Exception:
                # Fallback inline logic if helper unavailable
                status = 'ok'
                reason = ''
                if succ is None or (succ is not None and succ < 80) or legs == 0:
                    status = 'bad'
                    if legs == 0:
                        reason = 'no legs this cycle'
                    elif succ is None:
                        reason = 'no success metric'
                    else:
                        reason = f'low success {succ:.1f}%'
                elif (succ is not None and succ < 92) or err_recent:
                    status = 'warn'
                    if err_recent and rs.get('last_err_type'):
                        reason = f'error: {rs.get("last_err_type")}'
                    elif succ is not None:
                        reason = f'success {succ:.1f}%'
                if not reason and rs.get('last_err_type') == 'stall':
                    reason = 'possible stall'
            rows.append({
                'time': time.strftime('%H:%M:%S', time.localtime(now_ts)),
                'index': name,
                'legs': int(legs),
                'legs_avg': int(legs_avg) if legs_avg else None,
                'legs_cum': int(cumulative) if cumulative is not None else None,
                'succ': succ,
                'succ_avg': succ_avg,
                'succ_life': lifetime_success,
                'cycle_attempts': cycle_attempts,
                'err': rs['last_err_type'] if err_recent else '',
                'status': status,
                'status_reason': reason,
            })
        # rows already matches List[StreamRow]
        pm.stream_rows = rows
        total_legs = sum(r['legs'] for r in rows)
        valid_succ: list[float] = [float(r['succ']) for r in rows if r['succ'] is not None and isinstance(r['succ'], (int, float))]
        overall_succ = sum(valid_succ)/len(valid_succ) if valid_succ else None
        pm.footer = {
            'total_legs': total_legs,
            'overall_success': overall_succ,
            'indices': len(rows)
        }

    def _augment_storage(self, pm: ParsedMetrics) -> None:
        raw = pm.raw

        def first(name: str) -> float | None:
            arr = raw.get(name)
            return arr[0].value if arr else None

        csv_files = first('g6_csv_files_created_total')
        csv_records = first('g6_csv_records_written_total')
        csv_errors = first('g6_csv_write_errors_total')
        csv_disk = first('g6_csv_disk_usage_mb')
        influx_points = first('g6_influxdb_points_written_total')
        influx_rate = first('g6_influxdb_write_success_rate_percent')
        influx_conn = first('g6_influxdb_connection_status')
        influx_latency = first('g6_influxdb_query_time_ms')
        backup_files = first('g6_backup_files_created_total')
        backup_time = first('g6_last_backup_unixtime')
        backup_size = first('g6_backup_size_mb')

        # compute deltas vs previous snapshot
        prev: StorageSnapshot | None = None
        if self._history:
            for _pts, obj in reversed(self._history):
                if isinstance(obj, dict) and obj.get('kind') == 'storage':  # legacy dict variant
                    storage_field = obj.get('storage')
                    if isinstance(storage_field, dict) and {'csv','influx','backup'} <= set(storage_field.keys()):
                        from typing import cast
                        prev = cast(StorageSnapshot, storage_field)  # runtime validation of keys performed
                    break

        def delta(curr: float | None, prev_val: float | None) -> float | None:
            if curr is None or prev_val is None:
                return None
            d = curr - prev_val
            return d if d >= 0 else None

        storage: StorageSnapshot = {
            'csv': {
                'files_total': csv_files,
                'records_total': csv_records,
                'records_delta': delta(csv_records, prev.get('csv', {}).get('records_total') if prev else None),
                'errors_total': csv_errors,
                'disk_mb': csv_disk,
            },
            'influx': {
                'points_total': influx_points,
                'points_delta': delta(influx_points, prev.get('influx', {}).get('points_total') if prev else None),
                'write_success_pct': influx_rate,
                'connection': influx_conn,
                'query_latency_ms': influx_latency,
            },
            'backup': {
                'files_total': backup_files,
                'last_backup_unixtime': backup_time,
                'age_seconds': (pm.ts - backup_time) if (backup_time and backup_time > 0) else None,
                'size_mb': backup_size,
            }
        }

        pm.storage = storage
        storage_entry: HistoryStorage = {'kind': 'storage', 'storage': storage}
        self._history.append((pm.ts, storage_entry))

    def _augment_errors(self, pm: ParsedMetrics, max_events: int = 40) -> None:
        pm.error_events = self._build_error_events(pm, max_events)

    def _build_error_events(self, pm: ParsedMetrics, max_events: int) -> list[ErrorEvent]:
        cutoff = pm.ts - (self.interval * 60)
        events: list[ErrorEvent] = []
        seen: set[str] = set()
        for ts, state in reversed(self._history):
            if ts < cutoff or len(events) >= max_events:
                break
            if not (isinstance(state, dict) and state.get('kind') == 'errors'):
                continue
            raw_errs = state.get('errors')
            errs: Mapping[str, float] | None = raw_errs if isinstance(raw_errs, dict) else None
            if not errs:
                continue
            for key, val in errs.items():
                if key in seen or len(events) >= max_events:
                    continue
                idx, et = key.split('|', 1)
                prev_val = self._previous_error_value(key, ts)
                delta = val - prev_val
                if delta <= 0:
                    continue
                events.append({
                    'index': idx,
                    'error_type': et,
                    'delta': delta,
                    'ago': pm.ts - ts,
                    'ts': ts,
                })
                seen.add(key)
        # Newest first
        events.sort(key=lambda ev: float(ev.get('ts', 0.0)), reverse=True)
        return events

    def _previous_error_value(self, key: str, before_ts: float) -> float:
        for pts, pstate in reversed(self._history):
            if pts >= before_ts:
                continue
            if not (isinstance(pstate, dict) and pstate.get('kind') == 'errors'):
                continue
            raw = pstate.get('errors')
            if isinstance(raw, dict) and key in raw:
                pv = raw[key]
                if isinstance(pv, (int, float)):
                    return float(pv)
                return 0.0
        return 0.0

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                data = self._fetch()
                with self._lock:
                    self._data = data
            except Exception as e:
                get_error_handler().handle_error(
                    e,
                    category=ErrorCategory.RESOURCE,
                    severity=ErrorSeverity.LOW,
                    component="web.metrics_cache",
                    function_name="_loop",
                    message="Background fetch failed; retaining previous snapshot",
                    should_log=False,
                )
            finally:
                # Wait even on failure so we don't spin aggressively
                self._stop.wait(self.interval)
