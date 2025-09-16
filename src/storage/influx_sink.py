#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
InfluxDB sink for G6 Options Trading Platform.
"""

import logging
import time
from datetime import datetime
from typing import Dict, Any

# Add this before launching the subprocess
import sys  # noqa: F401
import os  # noqa: F401

logger = logging.getLogger(__name__)

class InfluxSink:
    """InfluxDB storage sink for G6 data."""
    
    def __init__(self, url='http://localhost:8086', token='', org='', bucket='g6_data', enable_symbol_tag: bool = True, max_retries: int = 3, backoff_base: float = 0.25):
        """
        Initialize InfluxDB sink.
        
        Args:
            url: InfluxDB server URL
            token: InfluxDB API token
            org: InfluxDB organization
            bucket: InfluxDB bucket name
        """
        self.url = url
        self.token = token
        self.org = org
        self.bucket = bucket
        self.client = None
        self.enable_symbol_tag = enable_symbol_tag
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.metrics = None  # attach externally like CsvSink
        
        try:
            from influxdb_client.client.influxdb_client import InfluxDBClient
            
            # Initialize client
            self.client = InfluxDBClient(url=url, token=token, org=org)
            # Use batching with default flush interval
            self.write_api = self.client.write_api()
            
            logger.info(f"InfluxDB sink initialized with bucket: {bucket}")
        except ImportError:
            logger.warning("influxdb_client package not installed, using dummy implementation")
        except Exception as e:
            logger.error(f"Error initializing InfluxDB client: {e}")
    
    def close(self):
        """Close InfluxDB client."""
        if self.client:
            try:
                self.client.close()
                logger.info("InfluxDB client closed")
            except Exception as e:
                logger.error(f"Error closing InfluxDB client: {e}")
    
    def attach_metrics(self, metrics_registry):
        self.metrics = metrics_registry

    def write_options_data(self, index_symbol, expiry_date, options_data: Dict[str, Dict[str, Any]], timestamp=None):
        """
        Write options data to InfluxDB.
        
        Args:
            index_symbol: Index symbol
            expiry_date: Expiry date string or date object
            options_data: Dictionary of options data
            timestamp: Timestamp for the data (default: current time)
        """
        if not self.client or not self.write_api:
            return
        
        # Use current time if timestamp not provided
        if timestamp is None:
            timestamp = datetime.now()
        
        # Convert expiry_date to string if it's a date object
        if hasattr(expiry_date, 'strftime'):
            expiry_str = expiry_date.strftime('%Y-%m-%d')
        else:
            expiry_str = str(expiry_date)
        
        try:
            # Check if we have data
            if not options_data:
                logger.warning(f"No options data to write for {index_symbol} {expiry_date}")
                return

            # Import Point from canonical path
            from influxdb_client.client.write.point import Point

            points = []
            for symbol, data in options_data.items():
                strike = data.get('strike', 0)
                opt_type = data.get('type', data.get('instrument_type', ''))  # 'CE' or 'PE'
                ltp = data.get('last_price', 0)
                oi = data.get('oi', 0)
                volume = data.get('volume', 0)
                iv = data.get('iv', 0)
                delta = data.get('delta')
                gamma = data.get('gamma')
                theta = data.get('theta')
                vega = data.get('vega')
                rho = data.get('rho')

                point = Point("option_data") \
                    .tag("index", index_symbol) \
                    .tag("expiry", expiry_str) \
                    .tag("type", opt_type) \
                    .tag("strike", str(strike)) \
                    .field("price", float(ltp)) \
                    .field("oi", float(oi)) \
                    .field("volume", float(volume)) \
                    .field("iv", float(iv))
                if self.enable_symbol_tag:
                    point = point.tag("symbol", symbol)
                # Add greek fields conditionally if present to avoid writing zeros when not computed
                if delta is not None:
                    point = point.field("delta", float(delta))
                if gamma is not None:
                    point = point.field("gamma", float(gamma))
                if theta is not None:
                    point = point.field("theta", float(theta))
                if vega is not None:
                    point = point.field("vega", float(vega))
                if rho is not None:
                    point = point.field("rho", float(rho))
                point = point.time(timestamp)
                points.append(point)

            success = False
            for attempt in range(self.max_retries):
                try:
                    self.write_api.write(bucket=self.bucket, record=points)
                    success = True
                    break
                except Exception as e:  # noqa
                    wait = self.backoff_base * (2 ** attempt)
                    logger.warning(f"Influx write attempt {attempt+1}/{self.max_retries} failed: {e}; retrying in {wait:.2f}s")
                    time.sleep(wait)
            if success:
                logger.info(f"Wrote {len(points)} data points to InfluxDB")
                try:
                    if self.metrics:
                        self.metrics.influxdb_points_written.inc(len(points))
                        self.metrics.influxdb_write_success_rate.set(100.0)
                        self.metrics.influxdb_connection_status.set(1)
                except Exception:
                    pass
            else:
                logger.error("Failed to write points to InfluxDB after retries")
                try:
                    if self.metrics:
                        self.metrics.influxdb_write_success_rate.set(0.0)
                        self.metrics.influxdb_connection_status.set(0)
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Error writing options data to InfluxDB: {e}")
            try:
                if self.metrics:
                    self.metrics.influxdb_connection_status.set(0)
            except Exception:
                pass

    def write_overview_snapshot(self, index_symbol, pcr_snapshot, timestamp, day_width=0, expected_expiries=None):
        """Write aggregated PCR overview for multiple expiries as a single point.

        Measurement: options_overview
        Tags: index
        Fields: pcr_this_week, pcr_next_week, pcr_this_month, pcr_next_month, day_width
        """
        if not self.client or not self.write_api:
            return
        try:
            from influxdb_client.client.write.point import Point
            expiry_bit_map = {'this_week':1,'next_week':2,'this_month':4,'next_month':8}
            collected_mask = 0
            for k in pcr_snapshot.keys():
                collected_mask |= expiry_bit_map.get(k,0)
            expected_mask = 0
            if expected_expiries:
                for k in expected_expiries:
                    expected_mask |= expiry_bit_map.get(k,0)
            else:
                expected_mask = collected_mask
            missing_mask = expected_mask & (~collected_mask)
            expiries_collected = len(pcr_snapshot)
            expiries_expected = len(expected_expiries) if expected_expiries else expiries_collected

            point = Point("options_overview") \
                .tag("index", index_symbol) \
                .field("pcr_this_week", float(pcr_snapshot.get('this_week', 0))) \
                .field("pcr_next_week", float(pcr_snapshot.get('next_week', 0))) \
                .field("pcr_this_month", float(pcr_snapshot.get('this_month', 0))) \
                .field("pcr_next_month", float(pcr_snapshot.get('next_month', 0))) \
                .field("day_width", float(day_width)) \
                .field("expiries_expected", expiries_expected) \
                .field("expiries_collected", expiries_collected) \
                .field("expected_mask", expected_mask) \
                .field("collected_mask", collected_mask) \
                .field("missing_mask", missing_mask) \
                .time(timestamp)
            success = False
            for attempt in range(self.max_retries):
                try:
                    self.write_api.write(bucket=self.bucket, record=point)
                    success = True
                    break
                except Exception as e2:  # noqa
                    wait = self.backoff_base * (2 ** attempt)
                    logger.warning(f"Influx overview write attempt {attempt+1}/{self.max_retries} failed: {e2}; retrying in {wait:.2f}s")
                    time.sleep(wait)
            if success:
                logger.info(f"Wrote aggregated overview snapshot for {index_symbol} to InfluxDB")
                try:
                    if self.metrics:
                        self.metrics.influxdb_points_written.inc()
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Error writing overview snapshot to InfluxDB: {e}")

class NullInfluxSink:
    """Null implementation of InfluxDB sink that does nothing."""
    
    def __init__(self):
        """Initialize null sink."""
        pass
    
    def close(self):
        """Close sink (no-op)."""
        pass
    
    def write_options_data(self, index_symbol, expiry_date, options_data, timestamp=None):
        """Write options data (no-op)."""
        pass

    def write_overview_snapshot(self, index_symbol, pcr_snapshot, timestamp, day_width=0):
        """Write aggregated overview snapshot (no-op)."""
        pass