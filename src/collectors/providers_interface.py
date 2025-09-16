#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Providers Interface for G6 Options Trading Platform.
Serves as a facade for the various data providers.
"""

import logging
import datetime
from typing import Dict, List, Any, Optional, Tuple
import os

# Add this before launching the subprocess
import sys  # retained for potential future use
import os  # retained

logger = logging.getLogger(__name__)

# Global concise mode detection (default ON unless explicitly disabled)
_CONCISE = os.environ.get('G6_CONCISE_LOGS', '1').lower() not in ('0','false','no','off')

class Providers:
    """Interface for all data providers."""
    
    def __init__(self, primary_provider=None, secondary_provider=None):
        """
        Initialize providers interface.
        
        Args:
            primary_provider: Primary data provider (e.g., KiteProvider)
            secondary_provider: Secondary provider for fallback
        """
        self.primary_provider = primary_provider
        self.secondary_provider = secondary_provider
        self.logger = logger
        
        # Log which providers are being used
        provider_names = []
        if primary_provider:
            provider_class = primary_provider.__class__.__name__
            provider_names.append(provider_class)
        if secondary_provider:
            provider_class = secondary_provider.__class__.__name__
            provider_names.append(provider_class)
            
        self.logger.info(f"Providers initialized with: {', '.join(provider_names)}")
    
    def close(self):
        """Close all providers."""
        if self.primary_provider:
            self.primary_provider.close()
        if self.secondary_provider:
            self.secondary_provider.close()
    
    def get_index_data(self, index_symbol):
        """
        Get index price and OHLC data.
        
        Args:
            index_symbol: Index symbol (e.g., 'NIFTY')
        
        Returns:
            Tuple of (price, ohlc_data)
        """
        try:
            # Format for Quote API
            if index_symbol == "NIFTY":
                instruments = [("NSE", "NIFTY 50")]
            elif index_symbol == "BANKNIFTY":
                instruments = [("NSE", "NIFTY BANK")]
            elif index_symbol == "FINNIFTY":
                instruments = [("NSE", "NIFTY FIN SERVICE")]
            elif index_symbol == "MIDCPNIFTY":
                instruments = [("NSE", "NIFTY MIDCAP SELECT")]
            elif index_symbol == "SENSEX":
                instruments = [("BSE", "SENSEX")]
            else:
                instruments = [("NSE", index_symbol)]
            
            # Get quote from primary provider (includes OHLC) if available
            quotes = {}
            if self.primary_provider and hasattr(self.primary_provider, 'get_quote'):
                try:
                    quotes = self.primary_provider.get_quote(instruments)  # type: ignore
                except Exception as qe:
                    self.logger.warning(f"get_quote failed, will fallback to LTP: {qe}")
            else:
                # Avoid noisy error spam; debug is sufficient because we can fallback to LTP
                if not self.primary_provider:
                    self.logger.error("Primary provider not initialized")
                    return 0, {}
                self.logger.debug("Primary provider missing get_quote, using LTP fallback")
            
            # Extract price and OHLC
            for key, quote in quotes.items():
                price = quote.get('last_price', 0)
                ohlc = quote.get('ohlc', {})
                
                if _CONCISE:
                    self.logger.debug(f"Index data for {index_symbol}: Price={price}, OHLC={ohlc}")
                else:
                    self.logger.info(f"Index data for {index_symbol}: Price={price}, OHLC={ohlc}")
                return price, ohlc
                
            # Fall back to LTP if quote doesn't have OHLC
            if not self.primary_provider or not hasattr(self.primary_provider, 'get_ltp'):
                self.logger.error("Primary provider not initialized or missing get_ltp for fallback")
                return 0, {}
            ltp_data = {}
            try:
                ltp_data = self.primary_provider.get_ltp(instruments)  # type: ignore
            except Exception as le:
                self.logger.error(f"get_ltp fallback failed: {le}")
                return 0, {}
            
            for key, data in ltp_data.items():
                price = data.get('last_price', 0)
                if _CONCISE:
                    self.logger.debug(f"LTP for {index_symbol}: {price}")
                else:
                    self.logger.info(f"LTP for {index_symbol}: {price}")
                return price, {}
            
            self.logger.error(f"No index data returned for {index_symbol}")
            return 0, {}
            
        except Exception as e:
            self.logger.error(f"Error getting index data: {e}")
            return 0, {}
    
    def get_ltp(self, index_symbol):
        """
        Get last traded price for an index.
        
        Args:
            index_symbol: Index symbol (e.g., 'NIFTY')
        
        Returns:
            Float: Last traded price
        """
        try:
            # Get index price and OHLC
            price, _ = self.get_index_data(index_symbol)
            
            # Calculate ATM strike based on index
            if index_symbol in ["BANKNIFTY", "SENSEX"]:
                # Round to nearest 100
                atm_strike = round(float(price) / 100) * 100
            else:
                # Round to nearest 50
                atm_strike = round(float(price) / 50) * 50
                
            if _CONCISE:
                self.logger.debug(f"LTP for {index_symbol}: {price}")
                self.logger.debug(f"ATM strike for {index_symbol}: {atm_strike}")
            else:
                self.logger.info(f"LTP for {index_symbol}: {price}")
                self.logger.info(f"ATM strike for {index_symbol}: {atm_strike}")
            
            return atm_strike
            
        except Exception as e:
            self.logger.error(f"Error getting LTP: {e}")
            return 20000 if index_symbol == "BANKNIFTY" else 22000

    def get_atm_strike(self, index_symbol: str):
        """Return an approximate ATM strike for the index.

        Reuses get_ltp rounding logic (already produces the rounded strike).
        Provided for analytics compatibility (OptionChainAnalytics expects this).
        """
        try:
            return self.get_ltp(index_symbol)
        except Exception as e:  # pragma: no cover
            self.logger.error(f"Error computing ATM strike: {e}")
            return 0

    # ---- Compatibility aliases expected by analytics modules ----
    def option_instruments(self, index_symbol, expiry_date, strikes):  # noqa: D401
        """Alias to get_option_instruments / option instruments provider API.

        Prefer primary provider's native method when available, else fall back to
        internal resolution chain via get_option_instruments().
        """
        try:
            if self.primary_provider and hasattr(self.primary_provider, 'option_instruments'):
                return self.primary_provider.option_instruments(index_symbol, expiry_date, strikes)  # type: ignore
            return self.get_option_instruments(index_symbol, expiry_date, strikes)
        except Exception as e:  # pragma: no cover
            self.logger.error(f"option_instruments alias failure: {e}")
            return []
    
    def resolve_expiry(self, index_symbol, expiry_rule):
        """
        Resolve expiry date based on rule.
        
        Args:
            index_symbol: Index symbol (e.g., 'NIFTY')
            expiry_rule: Expiry rule (e.g., 'this_week')
        
        Returns:
            datetime.date: Resolved expiry date
        """
        try:
            if hasattr(self.primary_provider, 'resolve_expiry'):
                if not self.primary_provider or not hasattr(self.primary_provider, 'resolve_expiry'):
                    raise RuntimeError("Primary provider missing resolve_expiry")
                return self.primary_provider.resolve_expiry(index_symbol, expiry_rule)  # type: ignore
            
            self.logger.error("Error resolving expiry from primary provider")
            # Calculate fallback expiry based on rule
            today = datetime.date.today()
            
            if expiry_rule == 'this_week':
                # Find next Thursday (weekday 3) for weekly expiry
                days_until_thursday = (3 - today.weekday()) % 7
                if days_until_thursday == 0:  # Today is Thursday
                    days_until_thursday = 7   # Use next Thursday
                
                expiry = today + datetime.timedelta(days=days_until_thursday)
                self.logger.warning(f"Using fallback expiry resolution for {index_symbol} {expiry_rule}")
                return expiry
                
            elif expiry_rule == 'next_week':
                # Find next Thursday (weekday 3) for weekly expiry
                days_until_thursday = (3 - today.weekday()) % 7
                if days_until_thursday == 0:  # Today is Thursday
                    days_until_thursday = 7   # Use next Thursday
                
                next_week = today + datetime.timedelta(days=days_until_thursday + 7)
                self.logger.warning(f"Using fallback expiry resolution for {index_symbol} {expiry_rule}")
                return next_week
                
            elif expiry_rule == 'this_month':
                # Calculate last Thursday of current month
                if today.month == 12:
                    next_month = datetime.date(today.year + 1, 1, 1)
                else:
                    next_month = datetime.date(today.year, today.month + 1, 1)
                
                last_day = next_month - datetime.timedelta(days=1)
                days_to_subtract = (last_day.weekday() - 3) % 7
                this_month = last_day - datetime.timedelta(days=days_to_subtract)
                
                self.logger.warning(f"Using fallback expiry resolution for {index_symbol} {expiry_rule}")
                return this_month
                
            elif expiry_rule == 'next_month':
                # Calculate last Thursday of next month
                if today.month == 12:
                    month_after_next = datetime.date(today.year + 1, 2, 1)
                elif today.month == 11:
                    month_after_next = datetime.date(today.year + 1, 1, 1)
                else:
                    month_after_next = datetime.date(today.year, today.month + 2, 1)
                
                last_day = month_after_next - datetime.timedelta(days=1)
                days_to_subtract = (last_day.weekday() - 3) % 7
                next_month = last_day - datetime.timedelta(days=days_to_subtract)
                
                self.logger.warning(f"Using fallback expiry resolution for {index_symbol} {expiry_rule}")
                return next_month
                
            else:
                # Default to this week's expiry
                days_until_thursday = (3 - today.weekday()) % 7
                if days_until_thursday == 0:  # Today is Thursday
                    days_until_thursday = 7   # Use next Thursday
                
                expiry = today + datetime.timedelta(days=days_until_thursday)
                self.logger.warning(f"Unknown expiry rule '{expiry_rule}', using this week's expiry")
                return expiry
                
        except Exception as e:
            self.logger.error(f"Error resolving expiry: {e}")
            # Emergency fallback
            today = datetime.date.today()
            days_until_thursday = (3 - today.weekday()) % 7
            expiry = today + datetime.timedelta(days=days_until_thursday)
            self.logger.error(f"Using emergency fallback expiry: {expiry}")
            return expiry
    
    def get_option_instruments(self, index_symbol, expiry_date, strikes):
        """
        Get option instruments for specific expiry and strikes.
        
        Args:
            index_symbol: Index symbol (e.g., 'NIFTY')
            expiry_date: Expiry date
            strikes: List of strike prices
        
        Returns:
            List of option instruments
        """
        try:
            # Try get_option_instruments first
            if hasattr(self.primary_provider, 'get_option_instruments'):
                if not self.primary_provider or not hasattr(self.primary_provider, 'get_option_instruments'):
                    self.logger.error("Primary provider missing get_option_instruments")
                    return []
                instruments = self.primary_provider.get_option_instruments(index_symbol, expiry_date, strikes)  # type: ignore
                if instruments:
                    return instruments
            
            # Fallback to option_instruments if available
            if hasattr(self.primary_provider, 'option_instruments'):
                if not self.primary_provider or not hasattr(self.primary_provider, 'option_instruments'):
                    self.logger.error("Primary provider missing option_instruments")
                    return []
                instruments = self.primary_provider.option_instruments(index_symbol, expiry_date, strikes)  # type: ignore
                if instruments:
                    return instruments
            
            self.logger.error("Error getting option instruments from primary provider")
            
            # Emergency fallback - return empty list
            return []
            
        except Exception as e:
            self.logger.error(f"Error getting option instruments: {e}")
            return []
    
    def get_quote(self, instruments):
        """
        Get quotes for a list of instruments.
        
        Args:
            instruments: List of (exchange, symbol) tuples
        
        Returns:
            Dict of quotes keyed by "exchange:symbol"
        """
        try:
            if hasattr(self.primary_provider, 'get_quote'):
                if not self.primary_provider or not hasattr(self.primary_provider, 'get_quote'):
                    self.logger.error("Primary provider missing get_quote for index quotes")
                    return {}
                return self.primary_provider.get_quote(instruments)  # type: ignore
            return {}
        except Exception as e:
            self.logger.error(f"Error getting quotes: {e}")
            return {}
    
    def enrich_with_quotes(self, instruments):
        """
        Enrich option instruments with quotes data.
        
        Args:
            instruments: List of option instruments
        
        Returns:
            Dict of enriched instruments keyed by symbol
        """
        try:
            # Format instruments for quote API
            quote_instruments = []
            for instrument in instruments:
                symbol = instrument.get('tradingsymbol', '')
                exchange = instrument.get('exchange', 'NFO')
                quote_instruments.append((exchange, symbol))
            
            # Get quotes from provider
            if not self.primary_provider or not hasattr(self.primary_provider, 'get_quote'):
                self.logger.error("Primary provider missing get_quote for option quotes")
                return {}
            quotes = self.primary_provider.get_quote(quote_instruments)  # type: ignore
            
            # Enrich instruments with quote data
            enriched_data = {}
            for instrument in instruments:
                symbol = instrument.get('tradingsymbol', '')
                exchange = instrument.get('exchange', 'NFO')
                key = f"{exchange}:{symbol}"
                
                # Create a copy of the instrument
                enriched = instrument.copy()
                
                # Add quote data if available
                if key in quotes:
                    quote = quotes[key]
                    
                    # Add basic price fields
                    enriched['last_price'] = quote.get('last_price', 0)
                    enriched['volume'] = quote.get('volume', 0)
                    enriched['oi'] = quote.get('oi', 0)
                    
                    # Add average price (new field)
                    enriched['avg_price'] = quote.get('average_price', 0)
                    
                    # If average_price not available, try to calculate from OHLC
                    if not enriched['avg_price'] and 'ohlc' in quote:
                        ohlc = quote.get('ohlc', {})
                        if ohlc:
                            high = float(ohlc.get('high', 0))
                            low = float(ohlc.get('low', 0))
                            if high > 0 and low > 0:
                                enriched['avg_price'] = (high + low) / 2
                    
                    # Add depth if available
                    if 'depth' in quote:
                        enriched['depth'] = quote.get('depth')
                
                # Add to enriched data
                enriched_data[symbol] = enriched
            
            return enriched_data
        
        except Exception as e:
            self.logger.error(f"Error enriching instruments with quotes: {e}")
            
            # Return basic dict with original instruments
            basic_data = {}
            for instrument in instruments:
                symbol = instrument.get('tradingsymbol', '')
                if symbol:
                    basic_data[symbol] = instrument
            
            return basic_data