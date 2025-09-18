#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CSV Storage Sink for G6 Platform.
"""

import os
import csv
import json
import datetime
import logging
from typing import Dict, Any, List, Tuple
import os as _os_env  # for env access without shadowing
from ..utils.timeutils import round_timestamp  # type: ignore

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
        self.base_dir = resolved_dir
        os.makedirs(self.base_dir, exist_ok=True)
        # Initialize logger
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"CsvSink initialized with base_dir: {self.base_dir}")
        # Detect global concise mode (default enabled) to reduce repetitive write logs
        self._concise = _os_env.environ.get('G6_CONCISE_LOGS', '1').lower() not in ('0','false','no','off')
        # Lazy metrics registry (optional injection later)
        self.metrics = None
        # Configurable overview aggregation interval (seconds)
        try:
            self.overview_interval_seconds = int(_os_env.environ.get('G6_OVERVIEW_INTERVAL_SECONDS', '180'))
        except ValueError:
            self.overview_interval_seconds = 180
        # Cardinality suppression threshold (unique strikes per write)
        try:
            self.cardinality_max_strikes = int(_os_env.environ.get('G6_CSV_MAX_STRIKES', '1200'))
        except ValueError:
            self.cardinality_max_strikes = 1200
        # Verbose logging flag
        self.verbose = _os_env.environ.get('G6_CSV_VERBOSE', '1').lower() not in ('0','false','no')
        # Internal state for aggregation & suppression
        self._agg_last_write: Dict[str, datetime.datetime] = {}
        self._agg_pcr_snapshot: Dict[str, Dict[str, float]] = {}
        self._agg_day_width: Dict[str, float] = {}
        self._suppression_active: Dict[Tuple[str,str], bool] = {}
        # Last write tracking for summarizer/runtime status
        self.last_write_ts = None
        self.last_write_per_index = {}

    def attach_metrics(self, metrics_registry):
        """Attach metrics registry after initialization to avoid circular imports."""
        self.metrics = metrics_registry
    
    def _clean_for_json(self, obj):
        """Convert non-serializable objects for JSON."""
        if isinstance(obj, (datetime.date, datetime.datetime)):
            return obj.isoformat()
        elif hasattr(obj, 'to_dict'):
            return obj.to_dict()
        return str(obj)
    
    def write_options_data(self, index, expiry, options_data, timestamp, index_price=None, index_ohlc=None,
                           suppress_overview: bool = False, return_metrics: bool = False):
        """
        Write options data to CSV file.
        
        Args:
            index: Index symbol (e.g., 'NIFTY')
            expiry: Expiry date
            options_data: Dict of options data keyed by option symbol
            timestamp: Timestamp of data collection
            index_price: Current index price (if available)
            index_ohlc: Index OHLC data (if available)
        """
        self.logger.debug(f"write_options_data called with index={index}, expiry={expiry}")
        
        # Create directory structure if it doesn't exist
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
        
        # Determine expiry tag based on expiry date (factored out for testability)
        exp_date = expiry if isinstance(expiry, datetime.date) else datetime.datetime.strptime(str(expiry), '%Y-%m-%d').date()
        expiry_code = self._determine_expiry_code(exp_date)
            
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
        
        # Calculate day width if OHLC data is available
        day_width = 0
        if index_ohlc and 'high' in index_ohlc and 'low' in index_ohlc:
            day_width = float(index_ohlc.get('high', 0)) - float(index_ohlc.get('low', 0))
        
        # Update the overview file (segregated by index) unless suppressed for aggregation
        if not suppress_overview:
            self._write_overview_file(index, expiry_code, pcr, day_width, timestamp, index_price)
        
        # Group options by strike
        strike_data = self._group_by_strike(options_data)
        unique_strikes = len(strike_data)

        # Cardinality suppression decision (per index+expiry)
        suppressed = False
        key = (index, expiry_code)
        prev_state = self._suppression_active.get(key, False)
        if unique_strikes > self.cardinality_max_strikes:
            suppressed = True
            self._suppression_active[key] = True
            if not prev_state:
                self._record_cardinality_event(index, expiry_code, 'activate')
        else:
            # If previously suppressed and back under threshold, deactivate
            if prev_state and unique_strikes <= self.cardinality_max_strikes:
                self._suppression_active[key] = False
                self._record_cardinality_event(index, expiry_code, 'deactivate')
            suppressed = self._suppression_active.get(key, False)
        
        # Create expiry-specific directory
        expiry_dir = os.path.join(self.base_dir, index, expiry_code)
        os.makedirs(expiry_dir, exist_ok=True)
        
        # Create debug file
        debug_file = os.path.join(expiry_dir, f"{timestamp.strftime('%Y-%m-%d')}_debug.json")
        
        # Format timestamp for records - use actual collection time
        ts_str = timestamp.strftime('%Y-%m-%d %H:%M:%S')
        
        # Round timestamp using utility (nearest 30s) and format
        rounded_timestamp = round_timestamp(timestamp, step_seconds=30, strategy='nearest')
        ts_str_rounded = rounded_timestamp.strftime('%d-%m-%Y %H:%M:%S')
        
        # Process each strike and write to offset directory (skip if suppressed)
        if suppressed:
            self.logger.warning(f"Cardinality suppression active for {index} {expiry_code}: unique_strikes={unique_strikes} threshold={self.cardinality_max_strikes}; skipping per-strike writes")
        for strike, data in ({} if suppressed else strike_data).items():
            offset = int(strike - atm_strike)
            
            # Format offset for directory name
            if offset > 0:
                offset_dir = f"+{offset}"
            else:
                offset_dir = f"{offset}"
            
            # Create offset directory
            option_dir = os.path.join(self.base_dir, index, expiry_code, offset_dir)
            os.makedirs(option_dir, exist_ok=True)
            
            # Create option CSV file
            option_file = os.path.join(option_dir, f"{timestamp.strftime('%Y-%m-%d')}.csv")
            
            # Check if file exists
            file_exists = os.path.isfile(option_file)
            
            # Extract call and put data
            call_data = data.get('CE', {})
            put_data = data.get('PE', {})
            
            # Prepare row data via helper
            row, header = self._prepare_option_row(index=index,
                                                   expiry_code=expiry_code,
                                                   offset=offset,
                                                   index_price=index_price,
                                                   atm_strike=atm_strike,
                                                   call_data=call_data,
                                                   put_data=put_data,
                                                   ts_str_rounded=ts_str_rounded)

            # Write option file with new format (header if needed)
            self._append_csv_row(option_file, row, header if not file_exists else None)
            if self.verbose:
                self.logger.debug(f"Option data written to {option_file}")
            # Metrics per row
            try:
                if self.metrics:
                    self.metrics.csv_records_written.inc()
            except Exception:
                pass

        # Cardinality metrics (once per call)
        try:
            if self.metrics:
                self.metrics.csv_cardinality_unique_strikes.labels(index=index, expiry=expiry_code).set(unique_strikes)
                self.metrics.csv_cardinality_suppressed.labels(index=index, expiry=expiry_code).set(1 if suppressed else 0)
        except Exception:
            pass
        
        # Write debug JSON with all data
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
                'rounded_timestamp': ts_str_rounded
            }, f, indent=2)
        
        if self.verbose and not self._concise:
            self.logger.info(f"Data written for {index} {expiry_code} (unique_strikes={unique_strikes}{' SUPPRESSED' if suppressed else ''})")
        else:
            self.logger.debug(f"Data written for {index} {expiry_code} (unique_strikes={unique_strikes}{' SUPPRESSED' if suppressed else ''})")

        # Aggregation snapshot update (only update if not suppressed to avoid skew)
        self._update_aggregation_state(index, expiry_code, pcr, day_width, timestamp)
        self._maybe_write_aggregated_overview(index, timestamp)

        # Update last write tracking
        try:
            self.last_write_ts = timestamp if isinstance(timestamp, datetime.datetime) else datetime.datetime.now(datetime.timezone.utc)
            self.last_write_per_index[index] = self.last_write_ts
        except Exception:
            pass

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

    def _prepare_option_row(self, index: str, expiry_code: str, offset: int, index_price: float, atm_strike: float,
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
            'timestamp', 'index', 'expiry_tag', 'offset', 'index_price', 'atm', 'strike',
            'ce', 'pe', 'tp', 'avg_ce', 'avg_pe', 'avg_tp',
            'ce_vol', 'pe_vol', 'ce_oi', 'pe_oi',
            'ce_iv', 'pe_iv', 'ce_delta', 'pe_delta', 'ce_theta', 'pe_theta',
            'ce_vega', 'pe_vega', 'ce_gamma', 'pe_gamma', 'ce_rho', 'pe_rho'
        ]
        row = [
            ts_str_rounded, index, expiry_code, offset, index_price, atm_strike, offset_price,
            ce_price, pe_price, tp_price, ce_avg, pe_avg, avg_tp,
            ce_vol, pe_vol, ce_oi, pe_oi,
            ce_iv, pe_iv, ce_delta, pe_delta, ce_theta, pe_theta,
            ce_vega, pe_vega, ce_gamma, pe_gamma, ce_rho, pe_rho
        ]
        return row, header

    def _append_csv_row(self, filepath: str, row: List[Any], header: List[str] | None):
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        file_exists = os.path.isfile(filepath)
        with open(filepath, 'a' if file_exists else 'w', newline='') as f:
            writer = csv.writer(f)
            if not file_exists and header:
                writer.writerow(header)
            writer.writerow(row)

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

    # ---------------- Cardinality Metrics Helpers -----------------
    def _record_cardinality_event(self, index: str, expiry_code: str, event: str):
        try:
            if self.metrics:
                self.metrics.csv_cardinality_events.labels(index=index, expiry=expiry_code, event=event).inc()
        except Exception:
            pass

    # ---------------- Test Helper (pure suppression decision) -----------------
    def _test_eval_suppression(self, index: str, expiry_code: str, unique_strikes: int) -> bool:
        """Pure-ish function for tests: returns suppression state after feeding unique_strikes.
        Does not perform writes, only mutates suppression state map and records events.
        """
        key = (index, expiry_code)
        prev_state = self._suppression_active.get(key, False)
        if unique_strikes > self.cardinality_max_strikes:
            self._suppression_active[key] = True
            if not prev_state:
                self._record_cardinality_event(index, expiry_code, 'activate')
        else:
            if prev_state and unique_strikes <= self.cardinality_max_strikes:
                self._suppression_active[key] = False
                self._record_cardinality_event(index, expiry_code, 'deactivate')
        return self._suppression_active.get(key, False)
    
    def _write_overview_file(self, index, expiry_code, pcr, day_width, timestamp, index_price):
        """Write overview file for a specific index."""
        # Create overview directory for this index
        overview_dir = os.path.join(self.base_dir, "overview", index)
        os.makedirs(overview_dir, exist_ok=True)
        
        # Determine file path
        overview_file = os.path.join(overview_dir, f"{timestamp.strftime('%Y-%m-%d')}.csv")
        
        # Check if file exists
        file_exists = os.path.isfile(overview_file)
        
        # Format timestamp - use actual collection time with proper rounding
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
        # Reuse the same rounding logic for consistency
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