#!/usr/bin/env python3
"""
Data quality utilities for G6 Platform.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

class DataQualityChecker:
    """Data quality validation for options data."""

    def __init__(self):
        """Initialize data quality checker."""
        self.logger = logging.getLogger(__name__)

    def validate_options_data(self, options_data):
        """
        Validate options data for quality issues.
        
        Args:
            options_data: Dictionary of options data
            
        Returns:
            Tuple of (valid_data, issues)
            - valid_data: Dictionary with valid options data
            - issues: List of data quality issues found
        """
        valid_data = {}
        issues = []

        if not options_data:
            issues.append("Empty options data")
            return valid_data, issues

        # Check for each option
        for symbol, data in options_data.items():
            # Basic validation
            if not isinstance(data, dict):
                issues.append(f"Invalid data format for {symbol}")
                continue

            # Required fields
            required_fields = [
                'strike', 'instrument_type', 'last_price',
                'expiry', 'tradingsymbol'
            ]

            missing_fields = [f for f in required_fields if f not in data]
            if missing_fields:
                issues.append(f"Missing fields for {symbol}: {', '.join(missing_fields)}")
                continue

            # Type validation
            if data.get('instrument_type') not in ['CE', 'PE']:
                issues.append(f"Invalid instrument_type for {symbol}: {data.get('instrument_type')}")
                continue

            # Price validation
            try:
                price = float(data.get('last_price', 0))
                if price < 0:
                    issues.append(f"Negative price for {symbol}: {price}")
                    continue
            except (ValueError, TypeError):
                issues.append(f"Invalid price for {symbol}: {data.get('last_price')}")
                continue

            # Strike validation
            try:
                strike = float(data.get('strike', 0))
                if strike <= 0:
                    issues.append(f"Invalid strike for {symbol}: {strike}")
                    continue
            except (ValueError, TypeError):
                issues.append(f"Invalid strike for {symbol}: {data.get('strike')}")
                continue

            # Volume sanity (if present)
            try:
                if 'volume' in data and data['volume'] is not None:
                    v = data.get('volume')
                    if v is not None:
                        vol = float(v)
                        if vol < 0:
                            issues.append(f"Negative volume for {symbol}: {vol}")
                            # keep item but mark issue
            except (ValueError, TypeError):
                issues.append(f"Invalid volume for {symbol}: {data.get('volume')}")

            # Open interest sanity (if present)
            try:
                oi_key = 'open_interest' if 'open_interest' in data else ('oi' if 'oi' in data else None)
                if oi_key:
                    v = data.get(oi_key)
                    if v is not None:
                        oi_val = float(v)
                        if oi_val < 0:
                            issues.append(f"Negative OI for {symbol}: {oi_val}")
                            # keep item but mark issue
            except (ValueError, TypeError):
                if 'open_interest' in data or 'oi' in data:
                    issues.append(f"Invalid OI for {symbol}: {data.get('open_interest', data.get('oi'))}")

            # Check for extreme values (outliers)
            if self.is_price_outlier(data):
                issues.append(f"Price outlier detected for {symbol}: {data.get('last_price')}")
                # Don't exclude outliers, just log them

            # If we got here, data is valid
            valid_data[symbol] = data

        return valid_data, issues

    def is_price_outlier(self, option_data, z_threshold=3.0):
        """
        Check if option price is an outlier.
        
        Args:
            option_data: Option data dictionary
            z_threshold: Z-score threshold for outlier detection
            
        Returns:
            bool: True if price is an outlier, False otherwise
        """
        # Need historical data for real outlier detection
        # This is a placeholder implementation

        # For now, use simple rules
        price = float(option_data.get('last_price', 0))

        # Basic sanity check - option price shouldn't be more than 20% of strike
        # (This is a simplistic rule and might need adjustment)
        strike = float(option_data.get('strike', 0))
        if price > 0.2 * strike:
            return True

        return False

    def check_expiry_consistency(self, options_data: dict[str, Any], *, index_price: float | None = None, expiry_rule: str | None = None) -> list[str]:
        """Detect consistency issues across an expiry set, focusing on next-week anomalies.

        Heuristics (lightweight):
        - If expiry_rule indicates next week (e.g., 'next_week', 'next'), and median option price is far above
          a fraction of ATM (e.g., > 30% of ATM for most strikes), flag as "next_week_price_outlier".
        - If IV values (when present) are absurd (e.g., > 5.0), flag as "iv_out_of_range".

        Returns a list of issue labels. Non-fatal: intended for surfacing in DQ labels.
        """
        issues: list[str] = []
        try:
            if not isinstance(options_data, dict) or not options_data:
                return issues
            rule = (expiry_rule or "").lower().strip()
            # Gather last_price and iv values
            prices: list[float] = []
            ivs: list[float] = []
            for _sym, od in options_data.items():
                try:
                    p = float(od.get('last_price', 0) or 0)
                    if p > 0:
                        prices.append(p)
                except Exception:
                    pass
                try:
                    iv = float(od.get('iv', 0) or 0)
                    if iv > 0:
                        ivs.append(iv)
                except Exception:
                    pass
            # Rule-based next-week price anomaly
            if rule in ("next_week", "next", "week_next", "nextweek") and index_price and prices:
                try:
                    import statistics as _st
                    med = _st.median(prices)
                    # If median option trade is unusually high vs. ATM proxy, flag
                    # Using 0.3 of index_price as simplistic ceiling
                    if med > 0.3 * float(index_price):
                        issues.append("next_week_price_outlier")
                except Exception:
                    pass
            # IV range sanity
            if ivs and any(iv > 5.0 for iv in ivs):
                issues.append("iv_out_of_range")

            # Monthly static pricing detection (non-fatal; for observability)
            if 'month' in rule:
                try:
                    # Compute diversity in CE and PE prices separately when possible
                    ce_prices: list[float] = []
                    pe_prices: list[float] = []
                    for _sym, od in options_data.items():
                        t = (od.get('instrument_type') or od.get('type') or '').upper()
                        p = float(od.get('last_price', 0) or 0)
                        if p <= 0:
                            continue
                        if t == 'CE':
                            ce_prices.append(p)
                        elif t == 'PE':
                            pe_prices.append(p)
                    def _low_diversity(vals: list[float]) -> bool:
                        if len(vals) < 3:
                            return False
                        return len({round(v, 2) for v in vals}) <= 2
                    if _low_diversity(ce_prices):
                        issues.append('monthly_ce_price_static')
                    if _low_diversity(pe_prices):
                        issues.append('monthly_pe_price_static')
                except Exception:
                    pass
        except Exception:
            # DQ should be best-effort and never raise
            pass
        return issues

    def validate_index_data(self, index_price, index_ohlc=None):
        """
        Validate index price and OHLC data.
        
        Args:
            index_price: Index price value
            index_ohlc: Optional OHLC data dictionary
            
        Returns:
            Tuple of (is_valid, issues)
        """
        issues = []

        # Check price is valid
        try:
            price = float(index_price)
            if price <= 0:
                issues.append(f"Invalid index price: {price}")
                return False, issues
        except (ValueError, TypeError):
            issues.append(f"Invalid index price format: {index_price}")
            return False, issues

        # Check OHLC data if provided
        if index_ohlc:
            if not isinstance(index_ohlc, dict):
                issues.append("Invalid OHLC data format")
                return False, issues

            # Check OHLC fields
            for field in ['open', 'high', 'low', 'close']:
                if field not in index_ohlc:
                    issues.append(f"Missing {field} in OHLC data")
                    return False, issues

                try:
                    value = float(index_ohlc[field])
                    if value <= 0:
                        issues.append(f"Invalid {field} in OHLC: {value}")
                        return False, issues
                except (ValueError, TypeError):
                    issues.append(f"Invalid {field} format: {index_ohlc[field]}")
                    return False, issues

            # Check consistency
            if float(index_ohlc['high']) < float(index_ohlc['low']):
                issues.append(f"High ({index_ohlc['high']}) is less than Low ({index_ohlc['low']})")
                return False, issues

        # All checks passed
        return True, issues

    def get_statistics(self, options_data):
        """
        Calculate statistics for the options data.
        
        Args:
            options_data: Dictionary of options data
            
        Returns:
            Dict with calculated statistics
        """
        if not options_data:
            return {}

        # Initialize containers
        call_prices = []
        put_prices = []
        call_oi = []
        put_oi = []
        call_volume = []
        put_volume = []

        # Collect data
        for symbol, data in options_data.items():
            if data.get('instrument_type') == 'CE':
                call_prices.append(float(data.get('last_price', 0)))
                call_oi.append(float(data.get('oi', 0)))
                call_volume.append(float(data.get('volume', 0)))
            elif data.get('instrument_type') == 'PE':
                put_prices.append(float(data.get('last_price', 0)))
                put_oi.append(float(data.get('oi', 0)))
                put_volume.append(float(data.get('volume', 0)))

        # Calculate statistics
        from typing import Any
        stats: dict[str, Any] = {
            'call_count': int(len(call_prices)),
            'put_count': int(len(put_prices)),
            'total_count': int(len(options_data))
        }

        # Price statistics
        if call_prices:
            stats['call_price_min'] = float(min(call_prices))
            stats['call_price_max'] = float(max(call_prices))
            stats['call_price_avg'] = float(sum(call_prices) / len(call_prices))

        if put_prices:
            stats['put_price_min'] = float(min(put_prices))
            stats['put_price_max'] = float(max(put_prices))
            stats['put_price_avg'] = float(sum(put_prices) / len(put_prices))

        # OI statistics
        if call_oi:
            stats['call_oi_total'] = float(sum(call_oi))
            stats['call_oi_avg'] = float(sum(call_oi) / len(call_oi))

        if put_oi:
            stats['put_oi_total'] = float(sum(put_oi))
            stats['put_oi_avg'] = float(sum(put_oi) / len(put_oi))

        # PCR
        if call_oi and put_oi and sum(call_oi) > 0:
            stats['pcr'] = float(sum(put_oi) / sum(call_oi))

        # Volume statistics
        if call_volume:
            stats['call_volume_total'] = float(sum(call_volume))
            stats['call_volume_avg'] = float(sum(call_volume) / len(call_volume))

        if put_volume:
            stats['put_volume_total'] = float(sum(put_volume))
            stats['put_volume_avg'] = float(sum(put_volume) / len(put_volume))

        return stats
