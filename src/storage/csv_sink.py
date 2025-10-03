#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CSV Storage Sink for G6 Platform.
"""

import os
import csv
import json
import datetime
import time
import logging
import re  # added for ISO date detection in expiry tag
from typing import Dict, Any, List, Tuple
import os as _os_env  # for env access without shadowing
import time
from ..utils.timeutils import (
    round_timestamp,  # generic (still used for raw rounding where needed)
    format_ist_dt_30s,  # unified IST full datetime formatting with 30s rounding
    round_to_30s_ist,
)  # type: ignore

class CsvSink:
    """CSV storage sink for options data."""
    
    def __init__(self, base_dir="data/g6_data"):
        """
        Initialize CSV sink.
        Args:
            base_dir: Base directory for CSV files (relative to project root or absolute)
        """
        # Resolve base_dir relative to project root if not absolute
        if not os.path.isabs(base_dir):
            # Project root is two levels up from this file (src/storage/)
            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
            resolved_dir = os.path.abspath(os.path.join(project_root, base_dir))
        else:
            resolved_dir = base_dir
        # Normalize to an absolute, OS-native path to avoid Windows path quirks
        self.base_dir = os.path.normpath(os.path.abspath(resolved_dir))
        os.makedirs(self.base_dir, exist_ok=True)
        # Initialize logger
        self.logger = logging.getLogger(__name__)
        # Downgrade to DEBUG; startup banner prints data dir at INFO
        self.logger.debug(f"CsvSink initialized with base_dir: {self.base_dir}")
        # Detect global concise mode (default enabled) to reduce repetitive write logs
        self._concise = _os_env.environ.get('G6_CONCISE_LOGS', '1').lower() not in ('0','false','no','off')
        # Lazy metrics registry (optional injection later)
        self.metrics = None
        # Configurable overview aggregation interval (seconds)
        try:
            self.overview_interval_seconds = int(_os_env.environ.get('G6_OVERVIEW_INTERVAL_SECONDS', '180'))
        except ValueError:
            self.overview_interval_seconds = 180
        # Verbose logging flag
        self.verbose = _os_env.environ.get('G6_CSV_VERBOSE', '1').lower() not in ('0','false','no')
        # Internal state for aggregation
        self._agg_last_write: Dict[str, datetime.datetime] = {}
        self._agg_pcr_snapshot: Dict[str, Dict[str, float]] = {}
        self._agg_day_width: Dict[str, float] = {}
        # ---------------- Batching State (Task 10) ----------------
        try:
            self._batch_flush_threshold = int(_os_env.environ.get('G6_CSV_BATCH_FLUSH','0'))  # 0 => disabled
        except ValueError:
            self._batch_flush_threshold = 0
        # key: (index, expiry_code, date_str) -> { option_file: {'header': header, 'rows': [row,...]} }
        self._batch_buffers = {}
        # Track counts per key to know when to flush
        self._batch_counts = {}
        # Track which logical expiry tags have been seen per index per date for advisory (Task 35)
        self._seen_expiry_tags = {}
        self._advisory_emitted = {}

    def attach_metrics(self, metrics_registry):
        """Attach metrics registry after initialization to avoid circular imports."""
        self.metrics = metrics_registry
    
    # ------------------------------------------------------------------
    # Expiry remediation daily summary helpers
    # ------------------------------------------------------------------
    def _update_expiry_daily_stats(self, kind: str) -> None:
        """Update in-memory daily stats for expiry remediation and emit summary events periodically.

        kind: one of 'rewritten','quarantined','rejected'. We aggregate counts per
        ISO date. Every _expiry_summary_interval seconds (default 60) we emit an
        'expiry_quarantine_summary' event with cumulative counts for the day.
        This is intentionally lightweight (best-effort) and safe if events are disabled.
        """
        try:
            from src.events import event_log  # local import to avoid heavy dependency at module import
        except Exception:
            event_log = None  # type: ignore
        if not hasattr(self, '_expiry_daily_stats'):
            self._expiry_daily_stats = {}
        if not hasattr(self, '_last_expiry_summary_emit'):
            self._last_expiry_summary_emit = 0.0
        today = datetime.date.today().isoformat()
        stats = self._expiry_daily_stats.setdefault(today, {'rewritten':0,'quarantined':0,'rejected':0})
        if kind in stats:
            stats[kind] += 1
        now = time.time()
        interval = getattr(self, '_expiry_summary_interval', 60)
        if event_log and now - self._last_expiry_summary_emit >= interval:
            try:
                aggregate = self._expiry_daily_stats.get(today, stats)
                event_log.dispatch('expiry_quarantine_summary', context={
                    'date': today,
                    'rewritten': aggregate.get('rewritten',0),
                    'quarantined': aggregate.get('quarantined',0),
                    'rejected': aggregate.get('rejected',0)
                })
                self._last_expiry_summary_emit = now
            except Exception:
                pass
    
    def _clean_for_json(self, obj):
        """Convert non-serializable objects for JSON."""
        if isinstance(obj, (datetime.date, datetime.datetime)):
            return obj.isoformat()
        elif hasattr(obj, 'to_dict'):
            return obj.to_dict()
        return str(obj)
    
    def write_options_data(self, index, expiry, options_data, timestamp, index_price=None, index_ohlc=None,
                           suppress_overview: bool = False, return_metrics: bool = False,
                           expiry_rule_tag: str | None = None, **_extra):
        """Write options data to CSV with locking, duplicate suppression, and config-tag honoring.

        expiry_rule_tag: Optional logical tag from the collector (e.g. 'this_month') used instead of
        heuristic distance-based tagging for indices whose config restricts expiries.
        """
        self.logger.debug(f"write_options_data called with index={index}, expiry={expiry}")
        concise_mode = False
        try:
            from src.broker.kite_provider import _CONCISE as _PROV_CONCISE  # type: ignore
            concise_mode = bool(_PROV_CONCISE)
        except Exception:
            pass
        if concise_mode:
            self.logger.debug(f"Options data received for {index} expiry {expiry}: {len(options_data)} instruments")
        else:
            self.logger.info(f"Options data received for {index} expiry {expiry}: {len(options_data)} instruments")

        exp_date = expiry if isinstance(expiry, datetime.date) else datetime.datetime.strptime(str(expiry), '%Y-%m-%d').date()
        # Honour supplied logical tag first; fallback to heuristic only if missing
        supplied_tag = (expiry_rule_tag.strip() if isinstance(expiry_rule_tag, str) and expiry_rule_tag.strip() else None)
        # If the supplied tag is a raw ISO date (YYYY-MM-DD), treat it as NOT a logical tag so that
        # config-based logical expiry enforcement does not block persistence. This restores legacy
        # behaviour where explicit dates flowed through and were heuristically classified.
        if supplied_tag and re.fullmatch(r"\d{4}-\d{2}-\d{2}", supplied_tag):
            # Downgrade to debug to avoid noisy logs in normal operation
            try:
                self.logger.debug(f"CSV_EXPIRY_TAG_RAW_DATE index={index} tag={supplied_tag} -> falling back to heuristic classification")
            except Exception:
                pass
            supplied_tag = None
        expiry_code = supplied_tag or self._determine_expiry_code(exp_date)
        expiry_str = exp_date.strftime('%Y-%m-%d')

        # Diagnostic: detect possible mismatch where a logical monthly tag points to a non-month-end anchor.
        try:
            if supplied_tag in ('this_month','next_month'):
                # A monthly anchor should be the last occurrence of its weekday in that month.
                import datetime as _dt
                cand = exp_date
                # Compute last occurrence of the weekday in that month
                if isinstance(cand, _dt.date):
                    if cand.month == 12:
                        nxt_first = _dt.date(cand.year+1,1,1)
                    else:
                        nxt_first = _dt.date(cand.year, cand.month+1,1)
                    last_day = nxt_first - _dt.timedelta(days=1)
                    # Walk backwards to weekday
                    last_weekday = last_day
                    while last_weekday.weekday() != cand.weekday():
                        last_weekday -= _dt.timedelta(days=1)
                    if last_weekday != cand:
                        # Mismatch: not a monthly anchor
                        self.logger.warning(
                            "CSV_EXPIRY_DIAGNOSTIC monthly_mismatch index=%s tag=%s date=%s expected_anchor=%s", index, supplied_tag, expiry_str, last_weekday.isoformat()
                        )
                        try:
                            # Auto-correct (always on; could be env gated later if needed)
                            exp_date = last_weekday
                            expiry_str = exp_date.strftime('%Y-%m-%d')
                            # Rewrite option instrument expiry fields so mixed-expiry pruning doesn't drop them all
                            try:
                                for _sym,_data in options_data.items():
                                    if isinstance(_data, dict) and 'expiry' in _data:
                                        _data['expiry'] = exp_date
                            except Exception:
                                pass
                            self.logger.warning(
                                "CSV_EXPIRY_CORRECTED monthly_anchor index=%s tag=%s corrected_date=%s", index, supplied_tag, expiry_str
                            )
                        except Exception:
                            pass
        except Exception:
            pass

        # ---------------- Config-based expiry enforcement (Task 29) ----------------
        # Only allow writing if the (supplied) expiry_code is within configured expiries for index.
        # If no config or tag supplied, allow heuristic result (legacy behaviour).
        if supplied_tag:  # only enforce if caller explicitly passed a tag
            try:
                # Lazy-load config once and cache on class
                if not hasattr(self, '_config_cache'):
                    cfg_path = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')), 'config', 'g6_config.json')
                    with open(cfg_path, 'r', encoding='utf-8') as _cf:
                        self._config_cache = json.load(_cf)
                indices_cfg = (self._config_cache or {}).get('indices', {})
                allowed = indices_cfg.get(index, {}).get('expiries') or []
                if allowed and expiry_code not in allowed:
                    # Skip writing disallowed tag
                    if self._concise:
                        self.logger.debug(f"CSV_SKIPPED_DISALLOWED index={index} tag={expiry_code} allowed={allowed}")
                    else:
                        self.logger.info(f"Skipping disallowed expiry tag for {index}: {expiry_code} not in {allowed}")
                    try:
                        if self.metrics and hasattr(self.metrics, 'csv_skipped_disallowed'):
                            self.metrics.csv_skipped_disallowed.labels(index=index, expiry=expiry_code).inc()
                    except Exception:  # pragma: no cover
                        pass
                    return {'expiry_code': expiry_code, 'pcr': 0, 'timestamp': timestamp, 'day_width': 0, 'skipped': True} if return_metrics else None
            except Exception as cfg_e:  # pragma: no cover
                self.logger.debug(f"Config enforcement failed for {index} {expiry_code}: {cfg_e}")
            
    # Get or calculate index price
        if not index_price:
            # Use a default value based on index if nothing else is available
            defaults = {
                "NIFTY": 24800,
                "BANKNIFTY": 54200,
                "FINNIFTY": 25900,
                "MIDCPNIFTY": 22000,
                "SENSEX": 80900
            }
            index_price = defaults.get(index, 0)
            
            # Try to find index price in the first option's metadata
            for _, data in options_data.items():
                if 'index_price' in data:
                    index_price = float(data['index_price'])
                    break
        
        # Calculate ATM strike (factored out)
        atm_strike = self._compute_atm_strike(index, float(index_price))
            
        if concise_mode:
            self.logger.debug(f"Index {index} price: {index_price}, ATM strike: {atm_strike}")
        else:
            self.logger.info(f"Index {index} price: {index_price}, ATM strike: {atm_strike}")
        
        # Calculate PCR for this expiry
        put_oi = sum(float(data.get('oi', 0)) for data in options_data.values() 
                    if data.get('instrument_type') == 'PE')
        call_oi = sum(float(data.get('oi', 0)) for data in options_data.values() 
                    if data.get('instrument_type') == 'CE')
        pcr = put_oi / call_oi if call_oi > 0 else 0

        # ---------------- Allowed expiry_dates validation (Task 39) ----------------
        try:
            allowed_set = getattr(self, 'allowed_expiry_dates', None)
            if allowed_set and isinstance(allowed_set, (set, list, tuple)) and exp_date not in allowed_set:
                if self._concise:
                    self.logger.debug(f"CSV_SKIP_INVALID_EXPIRY index={index} tag={expiry_code} expiry={expiry_str}")
                else:
                    self.logger.warning(f"Skipping write: expiry_date {expiry_str} not in allowed set for {index} (size={len(allowed_set)})")
                return {'expiry_code': expiry_code, 'pcr': 0, 'timestamp': timestamp, 'day_width': 0, 'skipped_invalid_expiry': True} if return_metrics else None
        except Exception:
            pass
        
        # Calculate day width if OHLC data is available
        day_width = 0
        if index_ohlc and 'high' in index_ohlc and 'low' in index_ohlc:
            day_width = float(index_ohlc.get('high', 0)) - float(index_ohlc.get('low', 0))

        # ---------------- Mixed-expiry validation (Task 31 / 34) ----------------
        # Some provider payloads may contain stray instruments from other expiries (edge race conditions or
        # overlapping weekly/monthly boundary). We inspect option metadata for an expiry field and drop
        # mismatches. Supported keys: 'expiry', 'expiry_date', 'instrument_expiry'.
        dropped = 0
        if options_data:
            safe_expected = exp_date
            for sym, data in list(options_data.items()):
                try:
                    raw_exp = data.get('expiry') or data.get('expiry_date') or data.get('instrument_expiry')
                    if not raw_exp:
                        continue
                    # Normalize to date
                    if isinstance(raw_exp, datetime.datetime):
                        cand_date = raw_exp.date()
                    elif isinstance(raw_exp, datetime.date):
                        cand_date = raw_exp
                    else:
                        cand_date = None
                        # try common formats
                        for fmt in ('%Y-%m-%d','%d-%m-%Y','%Y-%m-%d %H:%M:%S'):
                            try:
                                cand_date = datetime.datetime.strptime(str(raw_exp), fmt).date()
                                break
                            except Exception:
                                continue
                        if cand_date is None:
                            continue
                    if cand_date != safe_expected:
                        options_data.pop(sym, None)
                        dropped += 1
                except Exception:
                    continue
        if dropped:
            try:
                if self._concise:
                    self.logger.debug(f"CSV_MIXED_EXPIRY_PRUNE index={index} tag={expiry_code} dropped={dropped}")
                else:
                    self.logger.info(f"Pruned {dropped} mixed-expiry records for {index} {expiry_code}")
                if self.metrics and hasattr(self.metrics, 'csv_mixed_expiry_dropped'):
                    self.metrics.csv_mixed_expiry_dropped.labels(index=index, expiry=expiry_code).inc(dropped)
            except Exception:  # pragma: no cover
                pass

        # ---------------- Expected-expiry presence advisory (Task 35) ----------------
        try:
            date_key = timestamp.strftime('%Y-%m-%d')
            key = (index, date_key)
            seen = self._seen_expiry_tags.setdefault(key, set())
            seen.add(expiry_code)
            # Only attempt advisory if we have config and haven't emitted yet
            if not self._advisory_emitted.get(key):
                if not hasattr(self, '_config_cache'):
                    cfg_path = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')), 'config', 'g6_config.json')
                    with open(cfg_path, 'r', encoding='utf-8') as _cf:
                        self._config_cache = json.load(_cf)
                indices_cfg = (self._config_cache or {}).get('indices', {})
                expected_tags = set(indices_cfg.get(index, {}).get('expiries') or [])
                # Only relevant if expected set non-empty
                if expected_tags:
                    missing = expected_tags - seen
                    # Emit once when we have seen at least one tag and others are still missing
                    if missing and len(seen) >= 1:
                        self._advisory_emitted[key] = True  # avoid repetition
                        if self._concise:
                            self.logger.debug(f"CSV_EXPIRY_ADVISORY index={index} seen={sorted(seen)} missing={sorted(missing)}")
                        else:
                            self.logger.info(f"Advisory: Not all configured expiries observed for {index} today. Seen={sorted(seen)} Missing={sorted(missing)}")
        except Exception:  # pragma: no cover
            pass
        
        # Update the overview file (segregated by index) unless suppressed for aggregation
        if not suppress_overview:
            self._write_overview_file(index, expiry_code, pcr, day_width, timestamp, index_price)
        
        # Group options by strike
        strike_data = self._group_by_strike(options_data)
        unique_strikes = len(strike_data)

        # ---------------- Schema Assertions Layer (Task 11) ----------------
        schema_issues: List[str] = []
        for strike_key, leg_map in list(strike_data.items()):
            # Validate strike > 0
            if strike_key <= 0:
                schema_issues.append(f"invalid_strike:{strike_key}")
                # Remove invalid entry to avoid downstream errors
                strike_data.pop(strike_key, None)
                continue
            # Validate instrument_type presence on each populated leg
            for leg_type in ('CE','PE'):
                leg = leg_map.get(leg_type)
                if leg:
                    inst_type = (leg.get('instrument_type') or '').upper()
                    if inst_type not in ('CE','PE'):
                        schema_issues.append(f"missing_or_bad_type:{strike_key}:{leg_type}")
                        # Drop the leg to avoid writing inconsistent row (keeps other leg if valid)
                        leg_map[leg_type] = None
        if schema_issues:
            # Structured warning
            try:
                self.logger.warning(
                    "CSV_SCHEMA_ISSUES index=%s expiry=%s count=%d issues=%s", index, expiry_code, len(schema_issues), ','.join(schema_issues[:25]) + ("+"+str(len(schema_issues)-25) if len(schema_issues)>25 else "")
                )
            except Exception:
                pass
            # Optional metrics hook
            try:
                if self.metrics and hasattr(self.metrics, 'data_errors_labeled'):
                    for issue in schema_issues[:50]:  # cap to prevent explosion
                        self.metrics.data_errors_labeled.labels(index=index, component='csv_sink.schema', error_type=issue.split(':',1)[0]).inc()
            except Exception:
                pass
        
        # Create expiry-specific directory
        expiry_dir = os.path.join(self.base_dir, index, expiry_code)
        os.makedirs(expiry_dir, exist_ok=True)
        
        # Create debug file
        debug_file = os.path.join(expiry_dir, f"{timestamp.strftime('%Y-%m-%d')}_debug.json")
        
        # Format timestamp for records - use actual collection time
        ts_str = timestamp.strftime('%Y-%m-%d %H:%M:%S')
        
        # Unified IST 30s rounding + formatting (Task 12)
        try:
            ts_str_rounded = format_ist_dt_30s(timestamp)  # dd-mm-YYYY HH:MM:SS in IST
        except Exception:
            # Fallback to previous logic on unexpected failure
            rounded_timestamp = round_timestamp(timestamp, step_seconds=30, strategy='nearest')
            ts_str_rounded = rounded_timestamp.strftime('%d-%m-%Y %H:%M:%S')
        
        # Batching decision
        batching_enabled = self._batch_flush_threshold > 0
        batch_key = (index, expiry_code, timestamp.strftime('%Y-%m-%d'))
        if batching_enabled and batch_key not in self._batch_buffers:
            self._batch_buffers[batch_key] = {}
            self._batch_counts[batch_key] = 0

        # Collect mismatch stats if any option legs carry divergent expiry metadata
        mismatched_meta = 0
        # Process each strike and either buffer or write directly
        for strike, data in strike_data.items():
            offset = int(strike - atm_strike)
            
            # Format offset for directory name
            if offset > 0:
                offset_dir = f"+{offset}"
            else:
                offset_dir = f"{offset}"
            
            # Create offset directory
            option_dir = os.path.join(self.base_dir, index, expiry_code, offset_dir)
            os.makedirs(option_dir, exist_ok=True)
            
            # Create option CSV file (date-partitioned)
            option_file = os.path.join(option_dir, f"{timestamp.strftime('%Y-%m-%d')}.csv")
            
            # Check if file exists
            file_exists = os.path.isfile(option_file)
            
            # Extract call and put data
            call_data = data.get('CE', {})
            put_data = data.get('PE', {})
            
            # Prepare row data via helper
            # Canonical expiry_date_str is the resolved exp_date; override any per-leg variant for consistency
            # Detect if either leg advertises a different expiry (post pruning, should be rare)
            try:
                for leg_d in (call_data, put_data):
                    if not leg_d: continue
                    raw_leg_exp = leg_d.get('expiry') or leg_d.get('expiry_date') or leg_d.get('instrument_expiry')
                    if raw_leg_exp:
                        leg_date = raw_leg_exp.date() if isinstance(raw_leg_exp, datetime.datetime) else (raw_leg_exp if isinstance(raw_leg_exp, datetime.date) else None)
                        if leg_date and leg_date != exp_date:
                            mismatched_meta += 1
                            break
            except Exception:
                pass
            row, header = self._prepare_option_row(index=index,
                                                   expiry_code=expiry_code,
                                                   expiry_date_str=expiry_str,  # forced canonical
                                                   offset=offset,
                                                   index_price=index_price,
                                                   atm_strike=atm_strike,
                                                   call_data=call_data,
                                                   put_data=put_data,
                                                   ts_str_rounded=ts_str_rounded)

            # -------- Expiry Misclassification Detection (New) --------
            # Detect case where rows for the same (index, expiry_code) arrive with differing expiry_date values.
            # This indicates upstream classification inconsistency (weekly/monthly boundary, race, or fallback path).
            try:
                if os.environ.get('G6_EXPIRY_MISCLASS_DETECT','1').lower() in ('1','true','yes','on'):
                    if not hasattr(self, '_expiry_canonical_map'):
                        self._expiry_canonical_map = {}
                    # Load remediation policy flags once
                    if not hasattr(self, '_expiry_policy_loaded'):
                        policy = os.environ.get('G6_EXPIRY_MISCLASS_POLICY', 'rewrite').strip().lower()
                        if policy not in ('rewrite','quarantine','reject'):
                            policy = 'rewrite'
                        self._expiry_misclass_policy = policy
                        self._expiry_quarantine_dir = os.environ.get('G6_EXPIRY_QUARANTINE_DIR','data/quarantine/expiries')
                        self._expiry_rewrite_annotate = os.environ.get('G6_EXPIRY_REWRITE_ANNOTATE','1').lower() in ('1','true','yes','on')
                        # Summary emission interval (seconds) for remediation daily aggregates
                        try:
                            self._expiry_summary_interval = int(os.environ.get('G6_EXPIRY_SUMMARY_INTERVAL_SEC', '60') or '60')
                        except Exception:
                            self._expiry_summary_interval = 60
                        self._expiry_daily_stats = {}
                        self._expiry_policy_loaded = True
                    key = (index, expiry_code)
                    prev = self._expiry_canonical_map.get(key)
                    if prev is None:
                        # First occurrence establishes canonical date; expose info gauge if metrics present.
                        self._expiry_canonical_map[key] = expiry_str
                        try:
                            if self.metrics and hasattr(self.metrics, 'expiry_canonical_date'):
                                self.metrics.expiry_canonical_date.labels(index=index, expiry_code=expiry_code, expiry_date=expiry_str).set(1)
                        except Exception:
                            pass
                    elif prev != expiry_str:
                        # Misclassification event.
                        try:
                            if self.metrics and hasattr(self.metrics, 'expiry_misclassification_total'):
                                self.metrics.expiry_misclassification_total.labels(index=index, expiry_code=expiry_code, expected_date=prev, actual_date=expiry_str).inc()
                        except Exception:
                            pass
                        if os.environ.get('G6_EXPIRY_MISCLASS_DEBUG','0').lower() in ('1','true','yes','on'):
                            try:
                                self.logger.warning(f"EXPIRY_MISCLASS index={index} code={expiry_code} expected={prev} actual={expiry_str} offset={offset} ts={row[0]}")
                            except Exception:
                                pass
                        # Apply remediation policy (rewrite | quarantine | reject).
                        # Backward compatibility: legacy G6_EXPIRY_MISCLASS_SKIP=1 is treated as policy=reject for this row.
                        legacy_skip = os.environ.get('G6_EXPIRY_MISCLASS_SKIP','0').lower() in ('1','true','yes','on')
                        if legacy_skip:
                            try:
                                from src.metrics import get_metrics  # facade import
                                _m = get_metrics()
                                if hasattr(_m, 'deprecated_usage_total'):
                                    _m.deprecated_usage_total.labels(component='expiry_misclass_skip_flag').inc()  # type: ignore[attr-defined]
                            except Exception:
                                pass
                        policy = 'reject' if legacy_skip else getattr(self, '_expiry_misclass_policy', 'rewrite')
                        try:
                            if policy == 'rewrite':
                                # Mutate the expiry_code in place to canonical (prev) while preserving original metadata for optional annotation.
                                original_code = expiry_code
                                if self._expiry_rewrite_annotate:
                                    # Append annotation fields if header mutation feasible later; here we add to an auxiliary map for post-row augmentation.
                                    try:
                                        if not hasattr(self, '_rewrite_annotations'):
                                            self._rewrite_annotations = []
                                        self._rewrite_annotations.append((row, original_code, prev))
                                    except Exception:
                                        pass
                                # Switch local variable so downstream path writes canonical tag.
                                expiry_code = original_code  # logical tag remains the same; canonical date already enforced in expiry_str
                                if self.metrics and hasattr(self.metrics, 'expiry_rewritten_total'):
                                    self.metrics.expiry_rewritten_total.labels(index=index, from_code=original_code, to_code=expiry_code).inc()
                                # Track daily remediation stats (rewrite)
                                try:
                                    self._update_expiry_daily_stats('rewritten')
                                except Exception:
                                    pass
                            elif policy == 'quarantine':
                                # Write quarantined record (ndjson) and skip persistence to main CSV.
                                try:
                                    qdir = getattr(self, '_expiry_quarantine_dir', 'data/quarantine/expiries')
                                    # Partition by day
                                    qdate = datetime.date.today().strftime('%Y%m%d')
                                    qpath_dir = os.path.join(qdir)
                                    os.makedirs(qpath_dir, exist_ok=True)
                                    qfile = os.path.join(qpath_dir, f"{qdate}.ndjson")
                                    rec = {
                                        'ts': row[0],
                                        'index': index,
                                        'original_expiry_code': expiry_code,
                                        'canonical_expiry_code': prev,
                                        'reason': 'expiry_misclassification',
                                        'row': {
                                            'expiry_date': expiry_str,
                                            'offset': offset,
                                            'index_price': index_price,
                                            'atm_strike': atm_strike
                                        }
                                    }
                                    with open(qfile, 'a', encoding='utf-8') as qf:
                                        qf.write(json.dumps(rec) + '\n')
                                except Exception as qe:
                                    if self.logger:
                                        self.logger.debug(f"EXPIRY_QUARANTINE_WRITE_FAIL index={index} code={expiry_code} err={qe}")
                                if self.metrics and hasattr(self.metrics, 'expiry_quarantined_total'):
                                    try:
                                        self.metrics.expiry_quarantined_total.labels(index=index, expiry_code=expiry_code).inc()
                                    except Exception:
                                        pass
                                # Increment pending gauge & daily stats
                                try:
                                    iso_date = datetime.date.today().isoformat()
                                    if not hasattr(self, '_expiry_quarantine_pending_counts'):
                                        self._expiry_quarantine_pending_counts = {}
                                    self._expiry_quarantine_pending_counts[iso_date] = self._expiry_quarantine_pending_counts.get(iso_date, 0) + 1
                                    if self.metrics and hasattr(self.metrics, 'expiry_quarantine_pending'):
                                        self.metrics.expiry_quarantine_pending.labels(date=iso_date).set(self._expiry_quarantine_pending_counts[iso_date])
                                except Exception:
                                    pass
                                try:
                                    self._update_expiry_daily_stats('quarantined')
                                except Exception:
                                    pass
                                # Skip writing this misclassified row to main CSV
                                continue
                            else:  # reject
                                if self.metrics and hasattr(self.metrics, 'expiry_rejected_total'):
                                    try:
                                        self.metrics.expiry_rejected_total.labels(index=index, expiry_code=expiry_code).inc()
                                    except Exception:
                                        pass
                                try:
                                    self._update_expiry_daily_stats('rejected')
                                except Exception:
                                    pass
                                continue
                        except Exception:
                            # Fail-safe: if remediation handling errors, proceed with legacy behavior (write row) to avoid data loss.
                            pass
            except Exception:
                pass

            # ---------------- Junk Row Filtering (New) ----------------
            # Goal: suppress obviously placeholder / non-informative rows early (before zero-row logic)
            # Criteria controlled by env vars:
            #   G6_CSV_JUNK_MIN_TOTAL_OI   (int, default 0)  -> if (ce_oi + pe_oi) < this AND junk filtering enabled -> skip
            #   G6_CSV_JUNK_MIN_TOTAL_VOL  (int, default 0)  -> if (ce_vol + pe_vol) < this -> skip
            #   G6_CSV_JUNK_ENABLE         (bool, default on if either threshold >0)
            # A row that passes zero-row gating but is full of static tiny placeholder values can still flood disk.
            try:
                if not hasattr(self, '_junk_cfg_loaded'):
                    jm_oi = int(_os_env.environ.get('G6_CSV_JUNK_MIN_TOTAL_OI', '0') or '0')
                    jm_vol = int(_os_env.environ.get('G6_CSV_JUNK_MIN_TOTAL_VOL', '0') or '0')
                    jm_leg_oi = int(_os_env.environ.get('G6_CSV_JUNK_MIN_LEG_OI', '0') or '0')
                    jm_leg_vol = int(_os_env.environ.get('G6_CSV_JUNK_MIN_LEG_VOL', '0') or '0')
                    stale_thresh = int(_os_env.environ.get('G6_CSV_JUNK_STALE_THRESHOLD','0') or '0')  # max identical consecutive timestamps for same offset
                    whitelist_raw = _os_env.environ.get('G6_CSV_JUNK_WHITELIST','').strip()
                    summary_interval = int(_os_env.environ.get('G6_CSV_JUNK_SUMMARY_INTERVAL','0') or '0')
                    j_enable_env = _os_env.environ.get('G6_CSV_JUNK_ENABLE','auto').lower()
                    if j_enable_env in ('1','true','yes','on'):
                        j_enabled = True
                    elif j_enable_env in ('0','false','no','off'):
                        j_enabled = False
                    else:
                        j_enabled = (jm_oi > 0 or jm_vol > 0 or jm_leg_oi > 0 or jm_leg_vol > 0 or stale_thresh > 0)
                    jm_oi = max(0,jm_oi); jm_vol = max(0,jm_vol); jm_leg_oi = max(0, jm_leg_oi); jm_leg_vol = max(0, jm_leg_vol); stale_thresh = max(0, stale_thresh)
                    whitelist = set()
                    if whitelist_raw:
                        for token in whitelist_raw.split(','):
                            token = token.strip()
                            if token:
                                whitelist.add(token)
                    self._junk_min_total_oi = jm_oi
                    self._junk_min_total_vol = jm_vol
                    self._junk_min_leg_oi = jm_leg_oi
                    self._junk_min_leg_vol = jm_leg_vol
                    self._junk_stale_threshold = stale_thresh
                    self._junk_whitelist = whitelist
                    self._junk_summary_interval = summary_interval
                    self._junk_enabled = j_enabled
                    self._junk_stats = {'threshold':0,'stale':0,'total':0,'last_summary':time.time()}
                    self._junk_cfg_loaded = True
                    # Emit one-time info log summarizing configuration to aid operators diagnosing persistent junk rows
                    try:
                        self.logger.info(
                            f"CSV_JUNK_INIT enabled={self._junk_enabled} total_oi>={self._junk_min_total_oi} total_vol>={self._junk_min_total_vol} "
                            f"leg_oi>={self._junk_min_leg_oi} leg_vol>={self._junk_min_leg_vol} stale_threshold={self._junk_stale_threshold} whitelist={len(self._junk_whitelist)} summary_interval={self._junk_summary_interval}"
                        )
                    except Exception:
                        pass
                if getattr(self, '_junk_enabled', False):
                    # Whitelist bypass: patterns index:* or index:expiry_code or *:expiry_code or *
                    key_token_all = '*'
                    pattern_tokens = {f"{index}:{expiry_code}", f"{index}:*", f"*:{expiry_code}", key_token_all}
                    # Optional debug instrumentation (enabled when G6_CSV_JUNK_DEBUG=1) to help diagnose test failures
                    if _os_env.environ.get('G6_CSV_JUNK_DEBUG','0').lower() in ('1','true','yes','on'):
                        try:
                            self.logger.info(f"CSV_JUNK_DEBUG phase=pre_whitelist index={index} expiry_code={expiry_code} patterns={pattern_tokens} whitelist={getattr(self, '_junk_whitelist', None)} intersect={getattr(self, '_junk_whitelist', set()).intersection(pattern_tokens)} enabled={self._junk_enabled}")
                        except Exception:
                            pass
                    if self._junk_whitelist.intersection(pattern_tokens):
                        # Bypass all junk filtering for whitelisted patterns
                        junk = False
                    else:
                        ce_oi_val = int(call_data.get('oi',0)) if call_data else 0
                        pe_oi_val = int(put_data.get('oi',0)) if put_data else 0
                        ce_vol_val = int(call_data.get('volume',0)) if call_data else 0
                        pe_vol_val = int(put_data.get('volume',0)) if put_data else 0
                        total_oi = ce_oi_val + pe_oi_val
                        total_vol = ce_vol_val + pe_vol_val
                        junk_threshold = False
                        if self._junk_min_total_oi > 0 and total_oi < self._junk_min_total_oi:
                            junk_threshold = True
                        if self._junk_min_total_vol > 0 and total_vol < self._junk_min_total_vol:
                            junk_threshold = True
                        # Per-leg floors (new): if either leg fails leg-level liquidity requirement treat as junk
                        if self._junk_min_leg_oi > 0 and (ce_oi_val < self._junk_min_leg_oi or pe_oi_val < self._junk_min_leg_oi):
                            junk_threshold = True
                        if self._junk_min_leg_vol > 0 and (ce_vol_val < self._junk_min_leg_vol or pe_vol_val < self._junk_min_leg_vol):
                            junk_threshold = True
                        junk_stale = False
                        if not junk_threshold and self._junk_stale_threshold > 0:
                            # Track last N price signatures per (index, expiry_code, offset) and skip once stable repeats exceed threshold
                            if not hasattr(self, '_junk_stale_map'):
                                self._junk_stale_map = {}
                            # Lightweight touch map + periodic pruning to avoid unbounded growth for inactive offsets.
                            # We intentionally keep this internal & heuristic (no env tuning to keep risk low).
                            # Prune only when structure has grown beyond a modest size and at most every 5 minutes.
                            now_ts = time.time()
                            if not hasattr(self, '_junk_stale_touch'):
                                self._junk_stale_touch = {}
                                self._junk_stale_last_prune = now_ts
                            sig_key = (index, expiry_code, offset)
                            ce_price = float(call_data.get('last_price',0) or 0) if call_data else 0.0
                            pe_price = float(put_data.get('last_price',0) or 0) if put_data else 0.0
                            price_sig = (round(ce_price,4), round(pe_price,4))
                            prev_sig, count = self._junk_stale_map.get(sig_key, (None,0))
                            if prev_sig == price_sig:
                                count += 1
                            else:
                                count = 1
                            self._junk_stale_map[sig_key] = (price_sig, count)
                            self._junk_stale_touch[sig_key] = now_ts
                            # Prune if large & interval elapsed
                            if len(self._junk_stale_touch) > 5000 and (now_ts - getattr(self, '_junk_stale_last_prune', 0)) > 300:
                                cutoff = now_ts - 3600  # 1h TTL for untouched keys
                                removed = 0
                                for k, ts_k in list(self._junk_stale_touch.items()):
                                    if ts_k < cutoff:
                                        self._junk_stale_touch.pop(k, None)
                                        self._junk_stale_map.pop(k, None)
                                        removed += 1
                                self._junk_stale_last_prune = now_ts
                                if removed and _os_env.environ.get('G6_CSV_JUNK_DEBUG','0').lower() in ('1','true','yes','on'):
                                    try:
                                        self.logger.info(f"CSV_JUNK_DEBUG phase=prune stale_keys_removed={removed} remaining={len(self._junk_stale_touch)}")
                                    except Exception:
                                        pass
                            # Skip once count exceeds threshold (threshold defines allowed consecutive repeats)
                            if count > self._junk_stale_threshold:
                                junk_stale = True
                        junk = junk_threshold or junk_stale
                        if junk:
                            cat = 'threshold' if junk_threshold else 'stale'
                            if self.verbose:
                                self.logger.debug(f"CSV_JUNK_SKIP index={index} expiry={expiry_code} offset={offset} category={cat}")
                            # Guard against accidental double increment for same (index,expiry,offset,timestamp) in a single call
                            if not hasattr(self, '_junk_skip_keys'):
                                self._junk_skip_keys = set()  # type: ignore[attr-defined]
                            skip_key = (index, expiry_code, offset, row[0])
                            first_time = skip_key not in self._junk_skip_keys
                            if first_time:
                                self._junk_skip_keys.add(skip_key)
                            try:
                                if first_time and self.metrics and hasattr(self.metrics, 'csv_junk_rows_skipped'):
                                    self.metrics.csv_junk_rows_skipped.labels(index=index, expiry=expiry_code).inc()
                                if first_time and junk_threshold and self.metrics and hasattr(self.metrics, 'csv_junk_rows_threshold'):
                                    self.metrics.csv_junk_rows_threshold.labels(index=index, expiry=expiry_code).inc()
                                if first_time and junk_stale and self.metrics and hasattr(self.metrics, 'csv_junk_rows_stale'):
                                    self.metrics.csv_junk_rows_stale.labels(index=index, expiry=expiry_code).inc()
                            except Exception:
                                pass
                            # Stats accumulation & periodic summary
                            st = self._junk_stats
                            st['total'] += 1
                            st[cat] += 1
                            now = time.time()
                            if self._junk_summary_interval > 0 and (now - st['last_summary']) >= self._junk_summary_interval:
                                try:
                                    self.logger.info(f"CSV_JUNK_SUMMARY window={self._junk_summary_interval}s total={st['total']} threshold={st['threshold']} stale={st['stale']}")
                                except Exception:
                                    pass
                                st['last_summary'] = now
                                st['total'] = st['threshold'] = st['stale'] = 0
                            if _os_env.environ.get('G6_CSV_JUNK_DEBUG','0').lower() in ('1','true','yes','on'):
                                try:
                                    self.logger.info(f"CSV_JUNK_DEBUG phase=post_skip index={index} expiry_code={expiry_code} offset={offset} category={cat} first_time={first_time} total_counter={(getattr(self.metrics.csv_junk_rows_skipped, '_value', None) if self.metrics else None)}")
                                except Exception:
                                    pass
                            continue
            except Exception:
                pass

            # Zero-row detection: treat a row as zero if BOTH legs missing meaningful metrics
            try:
                ce_zero = (not call_data) or all(float(call_data.get(k, 0) or 0) == 0 for k in ('last_price','volume','oi','avg_price'))
                pe_zero = (not put_data) or all(float(put_data.get(k, 0) or 0) == 0 for k in ('last_price','volume','oi','avg_price'))
                is_zero_row = ce_zero and pe_zero
            except Exception:
                ce_zero = pe_zero = False
                is_zero_row = False
            if is_zero_row:
                # Increment metric if available
                try:
                    if self.metrics and hasattr(self.metrics, 'zero_option_rows_total'):
                        self.metrics.zero_option_rows_total.labels(index=index, expiry=expiry_str).inc()
                except Exception:  # pragma: no cover
                    pass
                # Respect optional skip flag
                if _os_env.environ.get('G6_SKIP_ZERO_ROWS', '0').lower() in ('1','true','yes','on'):
                    if self.verbose:
                        self.logger.debug(f"Skipping zero option row index={index} expiry={expiry_code} offset={offset}")
                    continue
                else:
                    if self.verbose:
                        self.logger.debug(f"Writing zero option row (flag not set to skip) index={index} expiry={expiry_code} offset={offset}")

            # Duplicate suppression (after row prepared): skip if identical timestamp for same file+offset
            if not hasattr(self, '_last_row_keys'):
                self._last_row_keys = {}
            last_key_map = self._last_row_keys  # type: ignore[attr-defined]
            row_sig = (option_file, offset)
            last_ts = last_key_map.get(row_sig)
            if last_ts == row[0]:
                if self.verbose:
                    self.logger.debug(f"Duplicate row suppressed index={index} expiry={expiry_code} offset={offset} ts={row[0]}")
                continue

            if batching_enabled:
                buf = self._batch_buffers[batch_key].setdefault(option_file, {'header': header, 'rows': []})
                buf['rows'].append(row)
                self._batch_counts[batch_key] += 1
            else:
                # Immediate write path (legacy)
                self._append_csv_row(option_file, row, header if not file_exists else None)
                # Mark written signature
                last_key_map[row_sig] = row[0]
                if self.verbose:
                    self.logger.debug(f"Option data written to {option_file}")
                try:
                    if self.metrics:
                        self.metrics.csv_records_written.inc()
                except Exception:
                    pass

        # (Cardinality suppression removed) unique_strikes computed above is informational only
        if mismatched_meta:
            try:
                self.logger.warning(f"CSV_EXPIRY_META_MISMATCH index={index} tag={expiry_code} mismatched_legs={mismatched_meta}")
            except Exception:
                pass

        # Decide whether to flush batch now (if enabled)
        flushed = False
        if batching_enabled:
            force_flush_env = _os_env.environ.get('G6_CSV_FLUSH_NOW','0').lower() in ('1','true','yes','on')
            if self._batch_counts.get(batch_key,0) >= self._batch_flush_threshold or force_flush_env:
                flushed = True
                buffers = self._batch_buffers.get(batch_key, {})
                for path, payload in buffers.items():
                    header_ref = payload.get('header')
                    rows = payload.get('rows', [])
                    if not rows:
                        continue
                    file_exists_local = os.path.isfile(path)
                    # Open once per file
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    self._append_many_csv_rows(path, rows, header_ref if not file_exists_local else None)
                    if self.verbose:
                        self.logger.debug(f"Flushed {len(rows)} rows to {path}")
                    try:
                        if self.metrics:
                            self.metrics.csv_records_written.inc(len(rows))
                    except Exception:
                        pass
                # Clear buffers for key
                self._batch_buffers.pop(batch_key, None)
                self._batch_counts.pop(batch_key, None)
        else:
            flushed = True  # immediate mode

        # Write debug JSON only when flushed (avoid misleading partial snapshot)
        if flushed:
            try:
                with open(debug_file, 'w') as f:
                    json.dump({
                        'timestamp': ts_str,
                        'index': index,
                        'expiry': str(expiry),
                        'expiry_code': expiry_code,
                        'index_price': index_price,
                        'atm_strike': atm_strike,
                        'pcr': pcr,
                        'day_width': day_width,
                        'data_count': len(options_data),
                        'rounded_timestamp': ts_str_rounded,
                        'batched': batching_enabled,
                        'flushed': True
                    }, f, indent=2)
            except Exception:
                if self.verbose:
                    self.logger.debug("Failed to write debug file", exc_info=True)
        
        if self.verbose and not self._concise:
            self.logger.info(f"Data written for {index} {expiry_code} (unique_strikes={unique_strikes})")
        else:
            self.logger.debug(f"Data written for {index} {expiry_code} (unique_strikes={unique_strikes})")

        # Aggregation snapshot update (only update if not suppressed to avoid skew)
        self._update_aggregation_state(index, expiry_code, pcr, day_width, timestamp)
        self._maybe_write_aggregated_overview(index, timestamp)

        # Optionally return metrics for aggregation mode
        if return_metrics:
            return {
                'expiry_code': expiry_code,
                'pcr': pcr,
                'day_width': day_width,
                'timestamp': timestamp,
                'index_price': index_price
            }

    # ------------------------- Helper Methods -------------------------
    def _determine_expiry_code(self, exp_date: datetime.date, today: datetime.date | None = None) -> str:
        today = today or datetime.date.today()
        days_to_expiry = (exp_date - today).days
        if days_to_expiry <= 7:
            return "this_week"
        if days_to_expiry <= 14:
            return "next_week"
        if exp_date.month == today.month:
            return "this_month"
        return "next_month"

    def _compute_atm_strike(self, index: str, index_price: float) -> float:
        if index in ["BANKNIFTY", "SENSEX"]:
            return round(index_price / 100) * 100
        return round(index_price / 50) * 50

    def _group_by_strike(self, options_data: Dict[str, Dict[str, Any]]) -> Dict[float, Dict[str, Any]]:
        grouped: Dict[float, Dict[str, Any]] = {}
        for symbol, data in options_data.items():
            strike = float(data.get('strike', 0))
            opt_type = data.get('instrument_type', '')
            if strike not in grouped:
                grouped[strike] = {'CE': None, 'PE': None}
            grouped[strike][opt_type] = data
            grouped[strike][f"{opt_type}_symbol"] = symbol
        return grouped

    def _prepare_option_row(self, index: str, expiry_code: str, *, expiry_date_str: str, offset: int, index_price: float, atm_strike: float,
                              call_data: Dict[str, Any] | None, put_data: Dict[str, Any] | None, ts_str_rounded: str) -> Tuple[List[Any], List[str]]:
        offset_price = atm_strike + offset
        # Call side values
        def f(d, k, default=0):
            try:
                return float(d.get(k, default)) if d else default
            except Exception:
                return default
        def i(d, k, default=0):
            try:
                return int(d.get(k, default)) if d else default
            except Exception:
                return default
        ce_price = f(call_data, 'last_price')
        ce_avg = f(call_data, 'avg_price')
        ce_vol = i(call_data, 'volume')
        ce_oi = i(call_data, 'oi')
        ce_iv = f(call_data, 'iv')
        ce_delta = f(call_data, 'delta')
        ce_theta = f(call_data, 'theta')
        ce_vega = f(call_data, 'vega')
        ce_gamma = f(call_data, 'gamma')
        ce_rho = f(call_data, 'rho')
        # Put side
        pe_price = f(put_data, 'last_price')
        pe_avg = f(put_data, 'avg_price')
        pe_vol = i(put_data, 'volume')
        pe_oi = i(put_data, 'oi')
        pe_iv = f(put_data, 'iv')
        pe_delta = f(put_data, 'delta')
        pe_theta = f(put_data, 'theta')
        pe_vega = f(put_data, 'vega')
        pe_gamma = f(put_data, 'gamma')
        pe_rho = f(put_data, 'rho')
        # Aggregates
        tp_price = ce_price + pe_price
        avg_tp = ce_avg + pe_avg
        header = [
            'timestamp', 'index', 'expiry_tag', 'expiry_date', 'offset', 'index_price', 'atm', 'strike',
            'ce', 'pe', 'tp', 'avg_ce', 'avg_pe', 'avg_tp',
            'ce_vol', 'pe_vol', 'ce_oi', 'pe_oi',
            'ce_iv', 'pe_iv', 'ce_delta', 'pe_delta', 'ce_theta', 'pe_theta',
            'ce_vega', 'pe_vega', 'ce_gamma', 'pe_gamma', 'ce_rho', 'pe_rho'
        ]
        row = [
            ts_str_rounded, index, expiry_code, expiry_date_str, offset, index_price, atm_strike, offset_price,
            ce_price, pe_price, tp_price, ce_avg, pe_avg, avg_tp,
            ce_vol, pe_vol, ce_oi, pe_oi,
            ce_iv, pe_iv, ce_delta, pe_delta, ce_theta, pe_theta,
            ce_vega, pe_vega, ce_gamma, pe_gamma, ce_rho, pe_rho
        ]
        return row, header

    def _append_csv_row(self, filepath: str, row: List[Any], header: List[str] | None):
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        file_exists = os.path.isfile(filepath)
        # Lightweight write lock gate using .lock sentinel (best-effort, non-blocking if exists)
        lock_path = filepath + '.lock'
        lock_created = False
        if not os.path.exists(lock_path):
            try:
                with open(lock_path, 'x') as _lf:
                    _lf.write(str(os.getpid()))
                lock_created = True
            except Exception:
                pass
        try:
            with open(filepath, 'a' if file_exists else 'w', newline='') as f:
                writer = csv.writer(f)
                if not file_exists and header:
                    writer.writerow(header)
                writer.writerow(row)
        finally:
            if lock_created:
                try:
                    os.remove(lock_path)
                except Exception:
                    pass

    def _append_many_csv_rows(self, filepath: str, rows: List[List[Any]], header: List[str] | None):
        if not rows:
            return
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        file_exists = os.path.isfile(filepath)
        lock_path = filepath + '.lock'
        lock_created = False
        if not os.path.exists(lock_path):
            try:
                with open(lock_path, 'x') as _lf:
                    _lf.write(str(os.getpid()))
                lock_created = True
            except Exception:
                pass
        try:
            with open(filepath, 'a' if file_exists else 'w', newline='') as f:
                writer = csv.writer(f)
                if not file_exists and header:
                    writer.writerow(header)
                writer.writerows(rows)
        finally:
            if lock_created:
                try:
                    os.remove(lock_path)
                except Exception:
                    pass

    # ---------------- Aggregation Support -----------------
    def _update_aggregation_state(self, index: str, expiry_code: str, pcr: float, day_width: float, timestamp: datetime.datetime):
        snap = self._agg_pcr_snapshot.setdefault(index, {})
        snap[expiry_code] = pcr
        # Track max day_width across expiries (or last non-zero)
        prev = self._agg_day_width.get(index, 0.0)
        if day_width >= prev:
            self._agg_day_width[index] = day_width
        self._agg_last_write.setdefault(index, timestamp)

    def _maybe_write_aggregated_overview(self, index: str, timestamp: datetime.datetime):
        last = self._agg_last_write.get(index)
        if not last:
            self._agg_last_write[index] = timestamp
            return
        if (timestamp - last).total_seconds() < self.overview_interval_seconds:
            return
        snapshot = self._agg_pcr_snapshot.get(index, {})
        if not snapshot:
            return
        day_width = self._agg_day_width.get(index, 0.0)
        try:
            self.write_overview_snapshot(index, snapshot, timestamp, day_width=day_width, expected_expiries=list(snapshot.keys()))
        except Exception as e:
            self.logger.error(f"Error writing aggregated overview for {index}: {e}")
        self._agg_last_write[index] = timestamp
        # Reset snapshot for next window
        self._agg_pcr_snapshot[index] = {}
        self._agg_day_width[index] = 0.0

    # (Cardinality suppression helpers removed)
    
    def _write_overview_file(self, index, expiry_code, pcr, day_width, timestamp, index_price):
        """Write overview file for a specific index."""
        # Create overview directory for this index
        overview_dir = os.path.join(self.base_dir, "overview", index)
        os.makedirs(overview_dir, exist_ok=True)
        
        # Determine file path
        overview_file = os.path.join(overview_dir, f"{timestamp.strftime('%Y-%m-%d')}.csv")
        
        # Check if file exists
        file_exists = os.path.isfile(overview_file)
        
        # Unified IST 30s rounding for overview timestamp
        try:
            ts_str = format_ist_dt_30s(timestamp)
        except Exception:
            # Fallback to legacy rounding logic
            second = timestamp.second
            if second % 30 < 15:
                rounded_second = (second // 30) * 30
                rounded_timestamp = timestamp.replace(second=rounded_second, microsecond=0)
            else:
                rounded_second = ((second // 30) + 1) * 30
                if rounded_second == 60:
                    rounded_second = 0
                    rounded_timestamp = timestamp.replace(second=rounded_second, microsecond=0)
                    rounded_timestamp = rounded_timestamp + datetime.timedelta(minutes=1)
                else:
                    rounded_timestamp = timestamp.replace(second=rounded_second, microsecond=0)
            ts_str = rounded_timestamp.strftime('%d-%m-%Y %H:%M:%S')
        
        # Read existing data to update PCR values
        pcr_values = {
            'pcr_this_week': 0,
            'pcr_next_week': 0,
            'pcr_this_month': 0,
            'pcr_next_month': 0
        }
        
        # Update the specific expiry code's PCR
        pcr_values[f'pcr_{expiry_code}'] = pcr
        
        # Write to CSV
        with open(overview_file, 'a' if file_exists else 'w', newline='') as f:
            writer = csv.writer(f)
            
            # Write header if new file
            if not file_exists:
                writer.writerow([
                    'timestamp', 'index', 
                    'pcr_this_week', 'pcr_next_week', 'pcr_this_month', 'pcr_next_month',
                    'day_width'
                ])
            
            # Write data row
            writer.writerow([
                ts_str, index,
                pcr_values['pcr_this_week'], pcr_values['pcr_next_week'],
                pcr_values['pcr_this_month'], pcr_values['pcr_next_month'],
                day_width
            ])
        
        self.logger.info(f"Overview data written to {overview_file}")
        try:
            if self.metrics:
                self.metrics.csv_overview_writes.labels(index=index).inc()
        except Exception:
            pass

    def write_overview_snapshot(self, index: str, pcr_snapshot: Dict[str, float], timestamp, day_width: float = 0, expected_expiries: List[str] | None = None):
        """Write a single aggregated overview row with multiple expiry PCRs.

        Args:
            index: Index symbol
            pcr_snapshot: Mapping of expiry_code -> pcr value (e.g., {'this_week': 0.92, 'next_week': 1.01})
            timestamp: Base timestamp (will be rounded identically to per-expiry method)
            day_width: Representative day width (use last or max); default 0
        """
        # Unified IST rounding for aggregate snapshot
        try:
            ts_str = format_ist_dt_30s(timestamp)
        except Exception:
            second = timestamp.second
            if second % 30 < 15:
                rounded_second = (second // 30) * 30
                rounded_timestamp = timestamp.replace(second=rounded_second, microsecond=0)
            else:
                rounded_second = ((second // 30) + 1) * 30
                if rounded_second == 60:
                    rounded_second = 0
                    rounded_timestamp = timestamp.replace(second=rounded_second, microsecond=0)
                    rounded_timestamp = rounded_timestamp + datetime.timedelta(minutes=1)
                else:
                    rounded_timestamp = timestamp.replace(second=rounded_second, microsecond=0)
            ts_str = rounded_timestamp.strftime('%d-%m-%Y %H:%M:%S')

        # Build output row using existing column set
        overview_dir = os.path.join(self.base_dir, "overview", index)
        os.makedirs(overview_dir, exist_ok=True)
        overview_file = os.path.join(overview_dir, f"{timestamp.strftime('%Y-%m-%d')}.csv")
        file_exists = os.path.isfile(overview_file)

        # Compute masks
        expiry_bit_map = {
            'this_week': 1,
            'next_week': 2,
            'this_month': 4,
            'next_month': 8
        }
        collected_mask = 0
        for k in pcr_snapshot.keys():
            collected_mask |= expiry_bit_map.get(k, 0)
        expected_mask = 0
        if expected_expiries:
            for k in expected_expiries:
                expected_mask |= expiry_bit_map.get(k, 0)
        else:
            # If not provided assume collected set equals expected
            expected_mask = collected_mask
        missing_mask = expected_mask & (~collected_mask)
        expiries_collected = len(pcr_snapshot)
        expiries_expected = len(expected_expiries) if expected_expiries else expiries_collected

        with open(overview_file, 'a' if file_exists else 'w', newline='') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow([
                    'timestamp', 'index',
                    'pcr_this_week', 'pcr_next_week', 'pcr_this_month', 'pcr_next_month',
                    'day_width', 'expiries_expected', 'expiries_collected',
                    'expected_mask', 'collected_mask', 'missing_mask'
                ])

            writer.writerow([
                ts_str, index,
                pcr_snapshot.get('this_week', 0),
                pcr_snapshot.get('next_week', 0),
                pcr_snapshot.get('this_month', 0),
                pcr_snapshot.get('next_month', 0),
                day_width, expiries_expected, expiries_collected,
                expected_mask, collected_mask, missing_mask
            ])

        if getattr(self, '_concise', False):
            self.logger.debug(f"Aggregated overview snapshot written for {index} -> {overview_file}")
        else:
            self.logger.info(f"Aggregated overview snapshot written for {index} -> {overview_file}")
        try:
            if self.metrics:
                self.metrics.csv_overview_aggregate_writes.labels(index=index).inc()
        except Exception:
            pass
    
    def read_options_overview(self, index, date=None):
        """
        Read overview data from CSV file.
        
        Args:
            index: Index symbol (e.g., 'NIFTY')
            date: Date to read data for (defaults to today)
            
        Returns:
            Dict of overview data by timestamp
        """
        # Use today's date if not specified
        if date is None:
            date = datetime.date.today()
            
        # Format date as string
        date_str = date.strftime('%Y-%m-%d') if isinstance(date, datetime.date) else date
        
        # Build file path
        overview_file = os.path.join(self.base_dir, "overview", index, f"{date_str}.csv")
        
        # Check if file exists
        if not os.path.exists(overview_file):
            self.logger.warning(f"No overview file found for {index} on {date_str}")
            return {}
        
        # Read CSV file
        overview_data = {}
        with open(overview_file, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                timestamp = row['timestamp']
                overview_data[timestamp] = {
                    'index': row['index'],
                    'pcr_this_week': float(row.get('pcr_this_week', 0)),
                    'pcr_next_week': float(row.get('pcr_next_week', 0)),
                    'pcr_this_month': float(row.get('pcr_this_month', 0)),
                    'pcr_next_month': float(row.get('pcr_next_month', 0)),
                    'day_width': float(row.get('day_width', 0)),
                    'expiries_expected': int(row.get('expiries_expected', 0)) if 'expiries_expected' in row else 0,
                    'expiries_collected': int(row.get('expiries_collected', 0)) if 'expiries_collected' in row else 0,
                    'expected_mask': int(row.get('expected_mask', 0)) if 'expected_mask' in row else 0,
                    'collected_mask': int(row.get('collected_mask', 0)) if 'collected_mask' in row else 0,
                    'missing_mask': int(row.get('missing_mask', 0)) if 'missing_mask' in row else 0
                }
        
        self.logger.info(f"Read overview data from {overview_file}")
        return overview_data
        
    def read_option_data(self, index, expiry_code, offset, date=None):
        """
        Read option data for a specific offset.
        
        Args:
            index: Index symbol (e.g., 'NIFTY')
            expiry_code: Expiry code (e.g., 'this_week')
            offset: Strike offset from ATM (e.g., +50, -100)
            date: Date to read data for (defaults to today)
            
        Returns:
            List of option data points
        """
        # Use today's date if not specified
        if date is None:
            date = datetime.date.today()
            
        # Format date as string
        date_str = date.strftime('%Y-%m-%d') if isinstance(date, datetime.date) else date
        
        # Format offset for directory name
        if int(offset) > 0:
            offset_dir = f"+{int(offset)}"
        else:
            offset_dir = f"{int(offset)}"
            
        # Build file path
        option_file = os.path.join(self.base_dir, index, expiry_code, offset_dir, f"{date_str}.csv")
        
        # Check if file exists
        if not os.path.exists(option_file):
            self.logger.warning(f"No option file found for {index} {expiry_code} offset {offset} on {date_str}")
            return []
        
        # Read CSV file
        option_data = []
        with open(option_file, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                option_data.append({
                    'timestamp': row['timestamp'],
                    'index': row['index'],
                    'expiry_tag': row['expiry_tag'],
                    'offset': int(row['offset']),
                    # Backward compatibility: legacy columns 'strike' (index price) and 'offset_price' (strike) may exist
                    'index_price': float(row.get('index_price', row.get('strike', 0))),
                    'atm': float(row['atm']),
                    'strike': float(row.get('strike', row.get('offset_price', 0))) if 'index_price' in row else float(row.get('offset_price', 0)),
                    'ce': float(row['ce']),
                    'pe': float(row['pe']),
                    'tp': float(row['tp']),
                    'avg_ce': float(row['avg_ce']),
                    'avg_pe': float(row['avg_pe']),
                    'avg_tp': float(row['avg_tp']),
                    'ce_vol': int(row['ce_vol']),
                    'pe_vol': int(row['pe_vol']),
                    'ce_oi': int(row['ce_oi']),
                    'pe_oi': int(row['pe_oi']),
                    'ce_iv': float(row['ce_iv']),
                    'pe_iv': float(row['pe_iv']),
                    'ce_delta': float(row['ce_delta']),
                    'pe_delta': float(row['pe_delta']),
                    'ce_theta': float(row['ce_theta']),
                    'pe_theta': float(row['pe_theta']),
                    'ce_vega': float(row['ce_vega']),
                    'pe_vega': float(row['pe_vega']),
                    'ce_gamma': float(row['ce_gamma']),
                    'pe_gamma': float(row['pe_gamma']),
                    'ce_rho': float(row.get('ce_rho', 0)),
                    'pe_rho': float(row.get('pe_rho', 0))
                })
        
        self.logger.info(f"Read {len(option_data)} option records from {option_file}")
        return option_data
        
    # Add this method to the CsvSink class

    def check_health(self):
        """
        Check if the CSV sink is healthy.
        
        Returns:
            Dict with health status information
        """
        try:
            # Check if base directory exists and is writable
            if not os.path.exists(self.base_dir):
                try:
                    os.makedirs(self.base_dir, exist_ok=True)
                except Exception as e:
                    return {
                        'status': 'unhealthy',
                        'message': f"Cannot create data directory: {str(e)}"
                    }
            
            # Check if we can write a test file
            test_file = os.path.join(self.base_dir, ".health_check")
            try:
                with open(test_file, 'w') as f:
                    f.write("Health check")
                os.remove(test_file)
            except Exception as e:
                return {
                    'status': 'unhealthy',
                    'message': f"Cannot write to data directory: {str(e)}"
                }
            
            # All checks passed
            return {
                'status': 'healthy',
                'message': 'CSV sink is healthy'
            }
        except Exception as e:
            return {
                'status': 'unhealthy',
                'message': f"Health check failed: {str(e)}"
            }