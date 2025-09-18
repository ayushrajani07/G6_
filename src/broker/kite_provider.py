#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kite Provider for G6 Options Trading Platform.
"""

import os
import logging
import datetime
from datetime import date, timedelta
from typing import Dict, List, Optional, Set, Tuple, Any
import json
from src.utils.retry import call_with_retry
from src.utils.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

# Global / env controlled concise logging toggle.
CONCISE_ENV_VAR = "G6_CONCISE_LOGS"
# Default: concise ON unless explicitly disabled via env var (e.g. 0/false/no/off)
_raw_concise = os.environ.get(CONCISE_ENV_VAR)
if _raw_concise is None:
    _CONCISE = True
else:
    _CONCISE = _raw_concise.lower() not in ("0", "false", "no", "off")

def enable_concise_logs(value: bool = True):  # lightweight helper
    global _CONCISE  # noqa: PLW0603
    _CONCISE = value
    logger.info(f"Concise logging {'ENABLED' if _CONCISE else 'DISABLED'} (runtime override)")

# Indices and their exchange pools
POOL_FOR = {
    "NIFTY": "NFO",
    "BANKNIFTY": "NFO", 
    "FINNIFTY": "NFO",
    "MIDCPNIFTY": "NFO",  # Added MidcpNifty
    "SENSEX": "BFO",
}

# Index name mappings for LTP queries
INDEX_MAPPING = {
    "NIFTY": ("NSE", "NIFTY 50"),
    "BANKNIFTY": ("NSE", "NIFTY BANK"),
    "FINNIFTY": ("NSE", "NIFTY FIN SERVICE"),
    "MIDCPNIFTY": ("NSE", "NIFTY MIDCAP SELECT"), 
    "SENSEX": ("BSE", "SENSEX"),
}

class KiteProvider:
    """Real Kite API provider."""
    
    @classmethod
    def from_env(cls):
        """Create KiteProvider from environment variables."""
        api_key = os.environ.get("KITE_API_KEY")
        access_token = os.environ.get("KITE_ACCESS_TOKEN")
        
        if not api_key or not access_token:
            raise ValueError("KITE_API_KEY or KITE_ACCESS_TOKEN not set")
        
        return cls(api_key=api_key, access_token=access_token)
    
    def __init__(self, api_key=None, access_token=None):
        """Initialize KiteProvider."""
        self.api_key = api_key
        self.access_token = access_token
        self.kite = None
        self._instruments_cache = {}  # Cache for instruments
        self._expiry_dates_cache = {}  # Cache for expiry dates
        self._used_fallback = False  # instrumentation flag
        # Rate limiters to suppress repetitive fallback/info logs
        self._rl_fallback = RateLimiter(min_interval=30)
        self._rl_quote_fallback = RateLimiter(min_interval=30)
        
        if not api_key or not access_token:
            logger.warning("API key or access token missing, trying to load from environment")
            self.api_key = os.environ.get("KITE_API_KEY")
            self.access_token = os.environ.get("KITE_ACCESS_TOKEN")
        
        self.initialize_kite()
        # Log only the first few chars of API key for security
        safe_api_key = f"{self.api_key[:4]}...{self.api_key[-4:]}" if self.api_key else "None"
        logger.info(f"KiteProvider initialized with API key: {safe_api_key}")
    
    def initialize_kite(self):
        """Initialize Kite Connect client."""
        try:
            from kiteconnect import KiteConnect
            
            # Initialize Kite
            self.kite = KiteConnect(api_key=self.api_key)
            
            # Set access token
            if self.access_token:
                self.kite.set_access_token(self.access_token)
                
            return True
        except Exception as e:
            logger.error(f"Failed to initialize Kite Connect: {e}")
            return False
    
    def close(self):
        """Clean up resources."""
        logger.info("KiteProvider closed")

    # NOTE: Duplicate dummy method block removed below; authoritative implementations retained.

    def get_instruments(self, exchange=None):
        """Return instruments, using cache if available. If real API unavailable, return minimal synthetic list.

        This is a simplified placeholder; production path should populate self._instruments_cache externally.
        """
        if exchange in self._instruments_cache:
            return self._instruments_cache[exchange]

        # If real kite client exists attempt fetch, otherwise fallback
        try:
            if self.kite is not None and hasattr(self.kite, 'instruments'):
                def _fetch_instruments():
                    return self.kite.instruments()  # type: ignore[attr-defined]
                all_instr = call_with_retry(_fetch_instruments)
                # Filter by exchange if provided
                if exchange:
                    filtered = [i for i in all_instr if str(i.get('exchange')) == exchange]
                else:
                    filtered = all_instr
                self._instruments_cache[exchange or '*'] = filtered
                return filtered
        except Exception as e:
            if self._rl_fallback():
                logger.debug(f"Falling back to synthetic instruments: {e}")

        # Synthetic minimal list (only enough for expiry detection)
        today = datetime.date.today()
        synthetic = [
            {
                "instrument_token": 1,
                "tradingsymbol": "NIFTY25SEP24800CE",
                "name": "NIFTY",
                "expiry": today + datetime.timedelta(days=14),
                "strike": 24800,
                "segment": "NFO-OPT",
                "exchange": "NFO"
            },
            {
                "instrument_token": 2,
                "tradingsymbol": "NIFTY25SEP24800PE",
                "name": "NIFTY",
                "expiry": today + datetime.timedelta(days=14),
                "strike": 24800,
                "segment": "NFO-OPT",
                "exchange": "NFO"
            },
        ]
        return synthetic

    def get_ltp(self, instruments):
        """Get last traded prices (real API or synthetic)."""
        data = {}
        # Real path
        try:
            if self.kite is not None and hasattr(self.kite, 'ltp'):
                formatted = []
                for exch, ts in instruments:
                    formatted.append(f"{exch}:{ts}")
                if formatted:
                    def _fetch_ltp():
                        return self.kite.ltp(formatted)  # type: ignore[attr-defined]
                    raw = call_with_retry(_fetch_ltp)
                    return raw
        except Exception as e:
            logger.debug(f"LTP real fetch failed, using synthetic: {e}")

        # Synthetic prices by simple heuristics
        for exch, ts in instruments:
            if "NIFTY 50" in ts:
                price = 24800
            elif "NIFTY BANK" in ts:
                price = 54000
            elif "NIFTY FIN SERVICE" in ts:
                price = 26000
            elif "MIDCAP" in ts:
                price = 12000
            elif "SENSEX" in ts:
                price = 81000
            else:
                price = 1000
            data[f"{exch}:{ts}"] = {"last_price": price}
        return data

    def get_quote(self, instruments):
        """Get full quotes (attempt real API, fallback to LTP structure).

        The interface expects a dict keyed by "EXCHANGE:TRADINGSYMBOL" with at least
        'last_price' and optionally 'ohlc'. We try KiteConnect.quote first. If that
        fails (network/auth issues) we downgrade to LTP synthetic values to avoid
        readiness probe hard-failing with missing method errors.
        """
        try:
            if self.kite is not None and hasattr(self.kite, 'quote'):
                formatted = [f"{exch}:{sym}" for exch, sym in instruments]
                if formatted:
                    def _fetch_quote():
                        return self.kite.quote(formatted)  # type: ignore[attr-defined]
                    raw = call_with_retry(_fetch_quote)
                    return raw
        except Exception as e:
            if self._rl_quote_fallback():
                logger.debug(f"Quote real fetch failed, falling back to LTP: {e}")

        # Fallback: build quote-like dict from LTP data
        ltp_data = self.get_ltp(instruments)
        quotes = {}
        if isinstance(ltp_data, dict):
            for key, payload in ltp_data.items():  # type: ignore[assignment]
                if not isinstance(payload, dict):  # defensive
                    continue
                lp = payload.get('last_price', 0)
                quotes[key] = {
                    'last_price': lp,
                    'ohlc': {},  # unknown in fallback
                }
        return quotes

    def get_atm_strike(self, index_symbol):
        """Derive ATM strike using current LTP or heuristic."""
        instruments = [INDEX_MAPPING.get(index_symbol, ("NSE", index_symbol))]
        ltp_data = self.get_ltp(instruments)
        if isinstance(ltp_data, dict):
            for v in ltp_data.values():
                lp = v.get('last_price')
                if lp:
                    # Round to nearest 50/100 based on magnitude
                    step = 100 if lp > 20000 else 50
                    return int(round(lp / step) * step)
        # Fallback heuristic
        defaults = {
            "NIFTY": 24800,
            "BANKNIFTY": 54000,
            "FINNIFTY": 26000,
            "MIDCPNIFTY": 12000,
            "SENSEX": 81000,
        }
        return defaults.get(index_symbol, 20000)
    
    def get_expiry_dates(self, index_symbol):
        """
        Get all available expiry dates for an index.
        """
        try:
            # Check cache first
            if index_symbol in self._expiry_dates_cache:
                logger.debug(f"Using cached expiry dates for {index_symbol}")
                return self._expiry_dates_cache[index_symbol]
            
            # Get ATM strike for the index
            atm_strike = self.get_atm_strike(index_symbol)
            
            # Get instruments based on the exchange pool
            exchange_pool = POOL_FOR.get(index_symbol, "NFO")
            instruments = self.get_instruments(exchange_pool)
            
            # Filter for options that match the index and are near the ATM strike
            opts = [
                inst for inst in instruments
                if str(inst.get("segment", "")).endswith("-OPT")  # Is an option
                and abs(float(inst.get("strike", 0)) - atm_strike) <= 500  # Near ATM
                and index_symbol in str(inst.get("tradingsymbol", ""))  # Matches index symbol
            ]
            
            # Parse and dedupe expiries
            today = datetime.date.today()
            expiry_dates = set()
            
            for opt in opts:
                expiry = opt.get("expiry")
                
                # Handle datetime.date object
                if isinstance(expiry, datetime.date):
                    if expiry >= today:
                        expiry_dates.add(expiry)
                # Handle string format
                elif isinstance(expiry, str):
                    try:
                        expiry_date = datetime.datetime.strptime(expiry, '%Y-%m-%d').date()
                        if expiry_date >= today:
                            expiry_dates.add(expiry_date)
                    except ValueError:
                        pass
            
            # Sort dates
            sorted_dates = sorted(list(expiry_dates))
            
            # Use ASCII-only framing (avoid box-drawing unicode for Windows cp1252 consoles)
            if _CONCISE:
                # Single line summary: EXPIRIES idx=... total=.. next=YYYY-MM-DD,YYYY-MM-DD monthlies=... sample=[...]
                total = len(sorted_dates)
                weeklies = []
                if total:
                    weeklies = sorted_dates[:2]
                # Monthlies = last expiry per month
                month_map = {}
                for d in sorted_dates:
                    mk = (d.year, d.month)
                    month_map.setdefault(mk, []).append(d)
                monthlies = [max(v) for _, v in sorted(month_map.items())]
                sample = []
                if sorted_dates:
                    if total <= 4:
                        sample = [sd.isoformat() for sd in sorted_dates]
                    else:
                        sample = [sorted_dates[0].isoformat(), sorted_dates[1].isoformat(), sorted_dates[-2].isoformat(), sorted_dates[-1].isoformat()]
                # Demote to debug in concise mode to reduce high-frequency log noise
                _exp_fn = logger.debug if _CONCISE else logger.info
                _exp_fn(
                    "EXPIRIES idx=%s total=%d weeklies=%s monthlies=%d next=%s sample=[%s]",
                    index_symbol.upper(),
                    total,
                    ','.join(d.isoformat() for d in weeklies) if weeklies else '-',
                    len(monthlies),
                    ','.join(d.isoformat() for d in weeklies) if weeklies else '-',
                    ','.join(sample)
                )
            else:
                logger.info(f"+-- Expiry Dates for {index_symbol.upper()} --" + "-" * 40)
                if sorted_dates:
                    # Group by month for better readability
                    by_month = {}
                    for d in sorted_dates:
                        month_key = f"{d.year}-{d:02d}"
                        if month_key not in by_month:
                            by_month[month_key] = []
                        by_month[month_key].append(d)
                        
                    for month, dates in sorted(by_month.items()):
                        logger.info(f"| {month}: {', '.join(d.strftime('%d') for d in dates)}")
                        
                    # Show weekly expiries
                    weeklies = sorted_dates[:2] if len(sorted_dates) >= 2 else sorted_dates
                    logger.info(f"| Next expiries: {', '.join(str(d) for d in weeklies)}")
                else:
                    logger.info(f"| No expiry dates found")
                logger.info("+" + "-" * 52)
            
            # Cache the results
            self._expiry_dates_cache[index_symbol] = sorted_dates
            
            if not sorted_dates:
                # Fallback: use current week's Thursday and next week's Thursday
                today = datetime.date.today()
                
                # Find next Thursday (weekday 3)
                days_until_thursday = (3 - today.weekday()) % 7
                if days_until_thursday == 0:
                    days_until_thursday = 7  # If today is Thursday, use next week
                
                this_week = today + datetime.timedelta(days=days_until_thursday)
                next_week = this_week + datetime.timedelta(days=7)
                
                fallback_dates = [this_week, next_week]
                logger.info(f"Using fallback expiry dates for {index_symbol}: {fallback_dates}")
                
                self._expiry_dates_cache[index_symbol] = fallback_dates
                return fallback_dates
                
            return sorted_dates
            
        except Exception as e:
            logger.error(f"Failed to get expiry dates: {e}", exc_info=True)
            
            # Fallback to calculated expiry dates
            today = datetime.date.today()
            days_until_thursday = (3 - today.weekday()) % 7
            this_week = today + datetime.timedelta(days=days_until_thursday)
            next_week = this_week + datetime.timedelta(days=7)
            
            fallback_dates = [this_week, next_week]
            logger.info(f"Using emergency fallback expiry dates for {index_symbol}: {fallback_dates}")
            return fallback_dates
    
    def get_weekly_expiries(self, index_symbol):
        """
        Get weekly expiry dates for an index.
        Returns first two upcoming expiries.
        """
        try:
            # Get all expiry dates
            all_expiries = self.get_expiry_dates(index_symbol)
            
            # Return first two (this week and next week)
            weekly_expiries = all_expiries[:2] if len(all_expiries) >= 2 else all_expiries
            return weekly_expiries
        except Exception as e:
            logger.error(f"Error getting weekly expiries: {e}")
            return []
    
    def get_monthly_expiries(self, index_symbol):
        """
        Get monthly expiry dates for an index.
        Groups expiries by month and returns the last expiry of each month.
        """
        try:
            # Get all expiry dates
            all_expiries = self.get_expiry_dates(index_symbol)
            
            # Group by month
            by_month = {}
            today = datetime.date.today()
            
            for expiry in all_expiries:
                if expiry >= today:
                    month_key = (expiry.year, expiry.month)
                    if month_key not in by_month:
                        by_month[month_key] = []
                    by_month[month_key].append(expiry)
            
            # Get last expiry of each month
            monthly_expiries = []
            for _, expiries in sorted(by_month.items()):
                monthly_expiries.append(max(expiries))
            
            return monthly_expiries
        except Exception as e:
            logger.error(f"Error getting monthly expiries: {e}")
            return []
    
    def resolve_expiry(self, index_symbol, expiry_rule):
        """
        Resolve expiry date based on rule.
        
        Valid rules:
        - this_week: Next weekly expiry (for NIFTY, SENSEX)
        - next_week: Following weekly expiry (for NIFTY, SENSEX)
        - this_month: Current month's expiry (for all indices)
        - next_month: Next month's expiry (for all indices)
        """
        try:
            self._used_fallback = False
            monthly_only_indices = ["BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"]
            all_expiries = self.get_expiry_dates(index_symbol)
            if not all_expiries:
                logger.warning(f"No expiry dates found for {index_symbol}")
                # Simple weekly fallback: today -> next standard weekday (Thursday for NFO / Thursday for BFO here simplified)
                today = datetime.date.today()
                weekday_target = 3  # Thursday
                delta = (weekday_target - today.weekday()) % 7
                if delta == 0:
                    delta = 7
                return today + datetime.timedelta(days=delta)

            today = datetime.date.today()
            by_month: dict[tuple[int,int], list[datetime.date]] = {}
            for e in all_expiries:
                if e >= today:
                    by_month.setdefault((e.year, e.month), []).append(e)
            if not by_month:
                logger.warning(f"No future expiries found for {index_symbol}")
                today = datetime.date.today()
                weekday_target = 3
                delta = (weekday_target - today.weekday()) % 7
                if delta == 0:
                    delta = 7
                return today + datetime.timedelta(days=delta)
            monthly_expiries = [max(v) for _, v in sorted(by_month.items())]

            log_fn = (logger.debug if _CONCISE else logger.info)

            # Normalize rule (accept variations like THIS_WEEK, thisWeek, current_week)
            normalized = (expiry_rule or '').strip().lower().replace('-', '_')
            if normalized in {'current_week'}:
                normalized = 'this_week'
            if normalized in {'current_month'}:
                normalized = 'this_month'
            if normalized in {'following_week'}:
                normalized = 'next_week'
            if normalized in {'following_month'}:
                normalized = 'next_month'

            if normalized == 'this_week' and index_symbol not in monthly_only_indices:
                log_fn(f"Resolved 'this_week' for {index_symbol} to {all_expiries[0]}")
                return all_expiries[0]
            if normalized == 'next_week' and index_symbol not in monthly_only_indices:
                if len(all_expiries) >= 2:
                    log_fn(f"Resolved 'next_week' for {index_symbol} to {all_expiries[1]}")
                    return all_expiries[1]
                log_fn(f"Only one expiry available, using {all_expiries[0]} for 'next_week'")
                return all_expiries[0]
            if normalized == 'this_month':
                if monthly_expiries:
                    log_fn(f"Resolved 'this_month' for {index_symbol} to {monthly_expiries[0]}")
                    return monthly_expiries[0]
                log_fn(f"No monthly expiry found, using {all_expiries[0]} for 'this_month'")
                return all_expiries[0]
            if normalized == 'next_month':
                if len(monthly_expiries) >= 2:
                    log_fn(f"Resolved 'next_month' for {index_symbol} to {monthly_expiries[1]}")
                    return monthly_expiries[1]
                if monthly_expiries:
                    log_fn(f"Only one monthly expiry available, using {monthly_expiries[0]} for 'next_month'")
                    return monthly_expiries[0]
                log_fn(f"No monthly expiries found, using {all_expiries[0]} for 'next_month'")
                return all_expiries[0]
            if expiry_rule != normalized:
                logger.warning(f"Unknown expiry rule '{expiry_rule}' (normalized to '{normalized}'), using first available expiry")
            else:
                logger.warning(f"Unknown expiry rule '{expiry_rule}', using first available expiry")
            log_fn(f"Using {all_expiries[0]} for unknown rule '{expiry_rule}' -> {normalized}")
            return all_expiries[0]
        except Exception as e:  # pragma: no cover
            logger.error(f"Failed to resolve expiry: {e}", exc_info=True)
            return datetime.date.today()
    
    # (Duplicate get_atm_strike removed; consolidated version earlier in class.)
    
    def option_instruments(self, index_symbol, expiry_date, strikes):
        """
        Get option instruments for specific expiry and strikes.
        """
        try:
            # Convert expiry_date to string format YYYY-MM-DD for comparison
            if hasattr(expiry_date, 'strftime'):
                expiry_str = expiry_date.strftime('%Y-%m-%d')
                expiry_obj = expiry_date
            else:
                # Try to parse string to date
                try:
                    expiry_obj = datetime.datetime.strptime(str(expiry_date), '%Y-%m-%d').date()
                    expiry_str = str(expiry_date)
                except:
                    logger.error(f"Could not parse expiry date: {expiry_date}")
                    expiry_obj = datetime.date.today()
                    expiry_str = expiry_obj.strftime('%Y-%m-%d')
            
            # Determine the appropriate exchange
            exchange_pool = POOL_FOR.get(index_symbol, "NFO")
            
            # Get instruments
            instruments = self.get_instruments(exchange_pool)
            # Demote high-frequency search line under concise mode
            (logger.debug if _CONCISE else logger.info)(
                f"Searching for {index_symbol} options (expiry: {expiry_date}, exchange: {exchange_pool})"
            )
            
            # Filter for matching instruments
            matching_instruments = []
            
            for instrument in instruments:
                # Check if it's a CE or PE option
                is_option = (instrument.get('instrument_type') == 'CE' or 
                             instrument.get('instrument_type') == 'PE')
                
                # Check if symbol matches our index
                tradingsymbol = instrument.get('tradingsymbol', '')
                symbol_matches = index_symbol in tradingsymbol
                
                # Check expiry match - handle both date objects and strings
                instrument_expiry = instrument.get('expiry')
                expiry_matches = False
                
                if isinstance(instrument_expiry, datetime.date):
                    expiry_matches = instrument_expiry == expiry_obj
                elif isinstance(instrument_expiry, str):
                    expiry_matches = instrument_expiry == expiry_str
                
                # Check if strike is in our list
                strike = float(instrument.get('strike', 0))
                strike_matches = any(abs(strike - s) < 0.01 for s in strikes)
                
                if is_option and symbol_matches and expiry_matches and strike_matches:
                    matching_instruments.append(instrument)
            
            # Group by strike and type for better reporting
            strikes_summary = {}
            for inst in matching_instruments:
                strike = float(inst.get('strike', 0))
                opt_type = inst.get('instrument_type', '')
                
                if strike not in strikes_summary:
                    strikes_summary[strike] = {'CE': 0, 'PE': 0}
                
                strikes_summary[strike][opt_type] += 1
            
            # Log summary (concise vs verbose)
            if _CONCISE:
                # Single-line concise summary with richer aggregate context
                total = len(matching_instruments)
                strikes_sorted = sorted(strikes_summary.keys())
                strike_count = len(strikes_sorted)
                ce_total = sum(v.get('CE', 0) for v in strikes_summary.values())
                pe_total = sum(v.get('PE', 0) for v in strikes_summary.values())
                # Coverage ratios (how many CE/PE legs obtained vs number of strikes)
                cov_denom = strike_count if strike_count else 1
                cov_ce = ce_total / cov_denom
                cov_pe = pe_total / cov_denom
                # Range & step heuristics
                if strike_count >= 2:
                    strike_min = strikes_sorted[0]
                    strike_max = strikes_sorted[-1]
                    # Determine typical step by min diff
                    diffs = [b - a for a, b in zip(strikes_sorted, strikes_sorted[1:]) if b - a > 0]
                    step = min(diffs) if diffs else 0
                elif strike_count == 1:
                    strike_min = strike_max = strikes_sorted[0]
                    step = 0
                else:
                    strike_min = strike_max = 0
                    step = 0
                # Provide first, middle, last few strikes as a compact footprint
                sample: List[str] = []
                if strikes_sorted:
                    if strike_count <= 5:
                        sample = [f"{s:.0f}" for s in strikes_sorted]
                    else:
                        head = [f"{s:.0f}" for s in strikes_sorted[:2]]
                        mid = [f"{strikes_sorted[strike_count//2]:.0f}"]
                        tail = [f"{s:.0f}" for s in strikes_sorted[-2:]]
                        sample = head + mid + tail
                sample_str = ",".join(sample)
                _opt_fn = logger.debug if _CONCISE else logger.info
                _opt_fn(
                    "OPTIONS idx=%s expiry=%s instruments=%d strikes=%d ce_total=%d pe_total=%d range=%s step=%s coverage=CE:%.2f,PE:%.2f sample=[%s]",
                    index_symbol,
                    expiry_date,
                    total,
                    strike_count,
                    ce_total,
                    pe_total,
                    f"{int(strike_min)}-{int(strike_max)}" if strike_count else "-",
                    int(step) if step else 0,
                    cov_ce,
                    cov_pe,
                    sample_str,
                )
            else:
                # Verbose legacy multi-line table
                logger.info(f"+ Options for {index_symbol} (Expiry: {expiry_date}) " + "-" * 30)
                logger.info(f"| Found {len(matching_instruments)} matching instruments")
                if strikes_summary:
                    logger.info("| Strike    CE  PE")
                    logger.info("| " + "-" * 15)
                    for strike in sorted(strikes_summary.keys()):
                        ce_count = strikes_summary[strike]['CE']
                        pe_count = strikes_summary[strike]['PE']
                        logger.info(f"| {strike:<8.1f} {ce_count:>2}  {pe_count:>2}")
                logger.info("+" + "-" * 50)
            
            return matching_instruments
        
        except Exception as e:
            logger.error(f"Failed to get option instruments: {e}", exc_info=True)
            return []
    
    # Add alias for compatibility
    def get_option_instruments(self, index_symbol, expiry_date, strikes):
        """Alias for option_instruments."""
        return self.option_instruments(index_symbol, expiry_date, strikes)
        
        
class DummyKiteProvider:
    """Dummy Kite provider for testing and fallback purposes."""
    
    def __init__(self):
        """Initialize DummyKiteProvider."""
        self.current_time = datetime.datetime.now()  # local-ok
        logger.info("DummyKiteProvider initialized")
    
    def close(self):
        """Clean up resources."""
        logger.info("DummyKiteProvider closed")
    
    
    def get_instruments(self, exchange=None):
        """Get dummy instruments."""
        if exchange == "NFO":
            return [
                {
                    "instrument_token": 1,
                    "exchange_token": "1",
                    "tradingsymbol": "NIFTY25SEP24800CE",
                    "name": "NIFTY",
                    "last_price": 100,
                    "expiry": datetime.date(2025, 9, 30),
                    "strike": 24800,
                    "tick_size": 0.05,
                    "lot_size": 50,
                    "instrument_type": "CE",
                    "segment": "NFO-OPT",
                    "exchange": "NFO"
                },
                {
                    "instrument_token": 2,
                    "exchange_token": "2",
                    "tradingsymbol": "NIFTY25SEP24800PE",
                    "name": "NIFTY",
                    "last_price": 100,
                    "expiry": datetime.date(2025, 9, 30),
                    "strike": 24800,
                    "tick_size": 0.05,
                    "lot_size": 50,
                    "instrument_type": "PE",
                    "segment": "NFO-OPT",
                    "exchange": "NFO"
                },
                {
                    "instrument_token": 3,
                    "exchange_token": "3",
                    "tradingsymbol": "BANKNIFTY25SEP54000CE",
                    "name": "BANKNIFTY",
                    "last_price": 100,
                    "expiry": datetime.date(2025, 9, 30),
                    "strike": 54000,
                    "tick_size": 0.05,
                    "lot_size": 25,
                    "instrument_type": "CE",
                    "segment": "NFO-OPT",
                    "exchange": "NFO"
                }
            ]
        return []
    
    def get_ltp(self, instruments):
        """Get last traded price for instruments."""
        ltp_data = {}
        
        for exchange, tradingsymbol in instruments:
            # Generate LTP based on index
            if "NIFTY 50" in tradingsymbol:
                price = 24800.0
            elif "NIFTY BANK" in tradingsymbol:
                price = 54000.0
            elif "NIFTY FIN SERVICE" in tradingsymbol:
                price = 26000.0
            elif "NIFTY MIDCAP SELECT" in tradingsymbol:
                price = 12000.0
            elif "SENSEX" in tradingsymbol:
                price = 81000.0
            else:
                price = 1000.0
                
            ltp_data[f"{exchange}:{tradingsymbol}"] = {
                "instrument_token": 1,
                "last_price": price
            }
            
        return ltp_data

    def get_quote(self, instruments):
        """Return quote-like structure using dummy LTP data.

        Mirrors the real provider interface so higher layers can request quotes
        without branching. Provides minimal fields: last_price + empty ohlc.
        """
        base = self.get_ltp(instruments)
        quotes = {}
        for key, payload in base.items():
            quotes[key] = {
                'last_price': payload.get('last_price', 0.0),
                'ohlc': {},
            }
        return quotes
    
    def get_atm_strike(self, index_symbol):
        """Get ATM strike for an index."""
        if index_symbol == "NIFTY":
            return 24800
        elif index_symbol == "BANKNIFTY":
            return 54000
        elif index_symbol == "FINNIFTY":
            return 26000
        elif index_symbol == "MIDCPNIFTY":
            return 12000
        elif index_symbol == "SENSEX":
            return 81000
        else:
            return 20000
    
    def get_expiry_dates(self, index_symbol):
        """Get dummy expiry dates."""
        today = datetime.date.today()
        
        # Generate weekly expiries (Thursdays)
        days_to_thur = (3 - today.weekday()) % 7
        if days_to_thur == 0:
            days_to_thur = 7  # If today is Thursday, go to next week
        
        this_thur = today + datetime.timedelta(days=days_to_thur)
        next_thur = this_thur + datetime.timedelta(days=7)
        
        # Generate monthly expiry (last Thursday of month)
        if today.month == 12:
            next_month = datetime.date(today.year + 1, 1, 1)
        else:
            next_month = datetime.date(today.year, today.month + 1, 1)
        
        last_day = next_month - datetime.timedelta(days=1)
        days_to_last_thur = (last_day.weekday() - 3) % 7
        monthly_expiry = last_day - datetime.timedelta(days=days_to_last_thur)
        
        # For next month's expiry
        if next_month.month == 12:
            month_after_next = datetime.date(next_month.year + 1, 1, 1)
        else:
            month_after_next = datetime.date(next_month.year, next_month.month + 1, 1)
        
        last_day_next = month_after_next - datetime.timedelta(days=1)
        days_to_last_thur_next = (last_day_next.weekday() - 3) % 7
        next_month_expiry = last_day_next - datetime.timedelta(days=days_to_last_thur_next)
        
        # Return appropriate expiries based on index
        if index_symbol in ["NIFTY", "SENSEX"]:
            # Weekly and monthly expiries
            return [this_thur, next_thur, monthly_expiry, next_month_expiry]
        else:
            # Only monthly expiries
            return [monthly_expiry, next_month_expiry]
    
    def resolve_expiry(self, index_symbol, expiry_rule):
        """Resolve expiry date based on rule (duplicate simplified resolver - normalized)."""
        expiry_dates = self.get_expiry_dates(index_symbol)
        monthly_only_indices = ["BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"]
        norm = (expiry_rule or '').strip().lower().replace('-', '_')
        if norm in {'current_week'}:
            norm = 'this_week'
        if norm in {'current_month'}:
            norm = 'this_month'
        if norm in {'following_week'}:
            norm = 'next_week'
        if norm in {'following_month'}:
            norm = 'next_month'
        if norm == 'this_week' and index_symbol not in monthly_only_indices:
            return expiry_dates[0]
        if norm == 'next_week' and index_symbol not in monthly_only_indices:
            return expiry_dates[min(1, len(expiry_dates)-1)]
        if norm == 'this_month':
            idx = 0 if index_symbol in monthly_only_indices else 2
            return expiry_dates[min(idx, len(expiry_dates)-1)]
        if norm == 'next_month':
            idx = 1 if index_symbol in monthly_only_indices else 3
            return expiry_dates[min(idx, len(expiry_dates)-1)]
        return expiry_dates[0]
    
    def option_instruments(self, index_symbol, expiry_date, strikes):
        """Get dummy option instruments."""
        instruments = []
        
        # Format expiry for tradingsymbol
        if isinstance(expiry_date, datetime.date):
            expiry_str = expiry_date.strftime('%y%b').upper()
        else:
            expiry_str = "25SEP"  # Default
        
        for strike in strikes:
            # Add CE instrument
            ce_instrument = {
                "instrument_token": int(strike * 10 + 1),
                "exchange_token": str(int(strike * 10 + 1)),
                "tradingsymbol": f"{index_symbol}{expiry_str}{int(strike)}CE",
                "name": index_symbol,
                "last_price": 100.0,
                "expiry": expiry_date if isinstance(expiry_date, datetime.date) else datetime.date(2025, 9, 30),
                "strike": float(strike),
                "tick_size": 0.05,
                "lot_size": 50 if index_symbol == "NIFTY" else 25,
                "instrument_type": "CE",
                "segment": "NFO-OPT",
                "exchange": "NFO"
            }
            instruments.append(ce_instrument)
            
            # Add PE instrument
            pe_instrument = {
                "instrument_token": int(strike * 10 + 2),
                "exchange_token": str(int(strike * 10 + 2)),
                "tradingsymbol": f"{index_symbol}{expiry_str}{int(strike)}PE",
                "name": index_symbol,
                "last_price": 100.0,
                "expiry": expiry_date if isinstance(expiry_date, datetime.date) else datetime.date(2025, 9, 30),
                "strike": float(strike),
                "tick_size": 0.05,
                "lot_size": 50 if index_symbol == "NIFTY" else 25,
                "instrument_type": "PE",
                "segment": "NFO-OPT",
                "exchange": "NFO"
            }
            instruments.append(pe_instrument)
        
        return instruments
    
    # Add alias for compatibility
    def get_option_instruments(self, index_symbol, expiry_date, strikes):
        """Alias for option_instruments."""
        return self.option_instruments(index_symbol, expiry_date, strikes)
        
        
    def check_health(self):
        """
        Check if the provider is healthy and connected.
        
        Returns:
            Dict with health status information
        """
        try:
            # Simple check - try to get NIFTY LTP
            ltp_resp = self.get_ltp("NIFTY")
            price_ok = False
            if isinstance(ltp_resp, dict):
                # Extract any numeric last_price
                for _k, _v in ltp_resp.items():
                    if isinstance(_v, dict) and isinstance(_v.get('last_price'), (int, float)):
                        if _v['last_price'] > 0:
                            price_ok = True
                            break
            # If we get a positive price, healthy
            if price_ok:
                return {
                    'status': 'healthy',
                    'message': 'Kite provider is connected'
                }
            else:
                return {
                    'status': 'degraded',
                    'message': 'Kite provider returned invalid price'
                }
        except Exception as e:
            # Check if we need to refresh the token
            if "token expired" in str(e).lower() or "invalid token" in str(e).lower():
                # Attempt refresh only if real kite client exposes it
                try:
                    kite_obj = getattr(self, 'kite', None)
                    refresh_fn = getattr(self, 'refresh_access_token', None)
                    if callable(refresh_fn):  # type: ignore
                        refresh_fn()  # type: ignore
                        logging.info("Token refreshed after expiration")
                        return {
                            'status': 'degraded',
                            'message': 'Token refreshed, reconnecting'
                        }
                except Exception as refresh_error:
                    return {
                        'status': 'unhealthy',
                        'message': f"Token refresh failed: {str(refresh_error)}"
                    }
            
            return {
                'status': 'unhealthy',
                'message': f"Connection check failed: {str(e)}"
            }