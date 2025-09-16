#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Data quality utilities for G6 Platform.
"""

import logging
import numpy as np
from typing import Dict, Any, List, Optional, Union

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
                issues.append(f"Invalid OHLC data format")
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
        stats = {
            'call_count': len(call_prices),
            'put_count': len(put_prices),
            'total_count': len(options_data)
        }
        
        # Price statistics
        if call_prices:
            stats.update({
                'call_price_min': min(call_prices),
                'call_price_max': max(call_prices),
                'call_price_avg': sum(call_prices) / len(call_prices)
            })
        
        if put_prices:
            stats.update({
                'put_price_min': min(put_prices),
                'put_price_max': max(put_prices),
                'put_price_avg': sum(put_prices) / len(put_prices)
            })
        
        # OI statistics
        if call_oi:
            stats.update({
                'call_oi_total': sum(call_oi),
                'call_oi_avg': sum(call_oi) / len(call_oi)
            })
        
        if put_oi:
            stats.update({
                'put_oi_total': sum(put_oi),
                'put_oi_avg': sum(put_oi) / len(put_oi)
            })
        
        # PCR
        if call_oi and put_oi and sum(call_oi) > 0:
            stats['pcr'] = sum(put_oi) / sum(call_oi)
        
        # Volume statistics
        if call_volume:
            stats.update({
                'call_volume_total': sum(call_volume),
                'call_volume_avg': sum(call_volume) / len(call_volume)
            })
        
        if put_volume:
            stats.update({
                'put_volume_total': sum(put_volume),
                'put_volume_avg': sum(put_volume) / len(put_volume)
            })
        
        return stats