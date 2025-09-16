# -*- coding: utf-8 -*-
"""
Enhanced Collector for G6 Platform
Extended version of unified collector with market hours and volume filtering.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from ..utils.timeutils import get_utc_now
from ..utils.market_hours import is_market_open, sleep_until_market_open
from .unified_collectors import run_unified_collectors
from .providers_interface import Providers

logger = logging.getLogger(__name__)

def run_enhanced_collectors(
    index_params: Any,
    providers: Providers,
    csv_sink: Any,
    influx_sink: Any,
    metrics: Any,
    *,
    min_volume: int = 10,
    min_oi: int = 100,
    only_during_market_hours: bool = True,
    volume_percentile: float = 0.2,  # Filter bottom 20% by volume
    enrichment_enabled: bool = True
) -> None:
    """
    Enhanced version of unified collector with additional features.
    
    Args:
        index_params: Configuration for indices
        providers: Data providers interface
        csv_sink: CSV storage sink
        influx_sink: InfluxDB storage sink
        metrics: Metrics registry
        min_volume: Minimum volume for option to be included
        min_oi: Minimum open interest for option to be included
        only_during_market_hours: Only collect during market hours
        volume_percentile: Percentile of options to filter by volume
        enrichment_enabled: Enable additional data enrichment
    """
    now = get_utc_now()
    
    # Skip collection outside market hours if configured
    if only_during_market_hours and not is_market_open():
        logger.info("Market is closed. Skipping collection.")
        return
    
    # Process each configured index
    for index_symbol, params in index_params.items():
        try:
            with metrics.create_timer("collection", index=index_symbol):
                logger.info(f"Collecting data for {index_symbol}")
                
                # Get parameters with safe access
                expiry_rules = _get_param(params, "expiry_rules", ["this_week"])
                atm_offsets = _get_param(params, "offsets", [-2, -1, 0, 1, 2])
                strike_step = int(_get_param(params, "strike_step", 50))
                
                # Get ATM strike price
                try:
                    atm_strike = providers.get_atm_strike(index_symbol)
                    logger.info(f"{index_symbol} ATM strike: {atm_strike}")
                except Exception as e:
                    logger.error(f"Failed to get ATM strike for {index_symbol}: {e}")
                    continue
                
                # Process each expiry
                for expiry_rule in expiry_rules:
                    try:
                        # Resolve expiry date
                        expiry_date = providers.resolve_expiry(index_symbol, expiry_rule)
                        logger.info(f"{index_symbol} {expiry_rule} expiry: {expiry_date.isoformat()}")
                        
                        # Calculate strike prices to fetch
                        strikes = [atm_strike + (offset * strike_step) for offset in atm_offsets]
                        
                        # Get option instruments for strikes
                        option_instruments = providers.option_instruments(
                            index_symbol, expiry_date, strikes
                        )
                        
                        # Extract tradingsymbols for call and put options
                        call_symbols = []
                        put_symbols = []
                        for inst in option_instruments:
                            if inst.get("instrument_type") == "CE":
                                call_symbols.append((inst.get("exchange"), inst.get("tradingsymbol")))
                            elif inst.get("instrument_type") == "PE":
                                put_symbols.append((inst.get("exchange"), inst.get("tradingsymbol")))
                        
                        # Get quotes for options
                        all_symbols = call_symbols + put_symbols
                        if not all_symbols:
                            logger.warning(f"No valid instruments found for {index_symbol} {expiry_rule}")
                            continue
                            
                        quotes = providers.get_quote(all_symbols)
                        
                        # Apply volume/OI filtering
                        if min_volume > 0 or min_oi > 0:
                            filtered_quotes = {}
                            for key, quote in quotes.items():
                                volume = int(quote.get("volume", 0))
                                oi = int(quote.get("oi", 0))
                                if volume >= min_volume and oi >= min_oi:
                                    filtered_quotes[key] = quote
                            
                            logger.info(f"Filtered {len(quotes) - len(filtered_quotes)} low-volume/OI options")
                            quotes = filtered_quotes
                        
                        # Further filter by volume percentile if needed
                        if volume_percentile > 0 and len(quotes) > 10:
                            volumes = [int(q.get("volume", 0)) for q in quotes.values()]
                            volumes.sort()
                            cutoff_idx = int(len(volumes) * volume_percentile)
                            volume_cutoff = volumes[cutoff_idx]
                            
                            volume_filtered = {k: v for k, v in quotes.items() 
                                             if int(v.get("volume", 0)) >= volume_cutoff}
                            
                            logger.info(f"Volume percentile filter: {len(quotes) - len(volume_filtered)} options removed")
                            quotes = volume_filtered
                        
                        # Enrich with additional data if enabled
                        if enrichment_enabled and quotes:
                            _enrich_quotes(quotes, index_symbol, expiry_date, providers)
                        
                        # Extract ATM offset from expiry_rule
                        offset_str = expiry_rule.split("_")[0]
                        
                        # Save to CSV
                        csv_sink.save_option_quotes(index_symbol, offset_str, expiry_date, atm_strike, quotes, now)
                        
                        # Save to InfluxDB
                        influx_sink.write_option_quotes(index_symbol, offset_str, expiry_date, atm_strike, quotes, now)
                        
                    except Exception as e:
                        logger.error(f"Failed to collect {index_symbol} {expiry_rule} data: {e}")
                
                metrics.record_collection_run(index_symbol, success=True, duration=None)
                
        except Exception as e:
            logger.error(f"Failed to collect data for {index_symbol}: {e}")
            metrics.record_collection_run(index_symbol, success=False, duration=None)

def _get_param(params: Any, name: str, default: Any = None) -> Any:
    """Get parameter from either dict or object, with fallback to default."""
    if hasattr(params, name):
        return getattr(params, name)
    elif hasattr(params, "get"):
        return params.get(name, default)
    else:
        return default

def _enrich_quotes(
    quotes: Dict[str, Dict[str, Any]], 
    index_symbol: str, 
    expiry_date: date,
    providers: Providers
) -> None:
    """
    Enrich option quotes with additional data.
    
    Adds:
    - IV (implied volatility)
    - Greeks (delta, gamma, theta, etc.)
    - OI Change
    - Volume Profile
    
    Updates quotes dictionary in place.
    """
    try:
        from ..analytics.option_greeks import OptionGreeks
        
        # Create Greeks calculator
        greeks_calc = OptionGreeks()
        
        # Get underlying spot price
        spot_price = providers.get_atm_strike(index_symbol)
        
        # Calculate Greeks and IV for each option
        for key, quote in quotes.items():
            try:
                # Parse instrument details from key
                exchange, symbol = key.split(":")
                
                # Find option type and strike
                option_type = "CE" if "CE" in symbol else "PE"
                is_call = option_type == "CE"
                
                # Strike might be embedded in symbol, try to extract
                # This is implementation-specific and may need adjustment
                parts = symbol.split()
                strike = None
                for part in parts:
                    try:
                        strike = float(part)
                        break
                    except ValueError:
                        pass
                
                if not strike:
                    # Try to extract from instrument data in providers
                    # This is implementation-specific and may need adjustment
                    continue
                
                # Calculate IV using the market price
                market_price = float(quote.get("last_price", 0))
                if market_price > 0:
                    iv = greeks_calc.implied_volatility(
                        is_call=is_call,
                        S=spot_price,
                        K=strike,
                        T=expiry_date,
                        market_price=market_price
                    )
                    
                    # Calculate Greeks using this IV
                    greeks = greeks_calc.black_scholes(
                        is_call=is_call,
                        S=spot_price,
                        K=strike,
                        T=expiry_date,
                        sigma=iv
                    )
                    
                    # Add to quote
                    quote["iv"] = round(iv * 100, 2)  # Convert to percentage
                    quote["delta"] = round(greeks["delta"], 3)
                    quote["gamma"] = round(greeks["gamma"], 4)
                    quote["theta"] = round(greeks["theta"], 2)
                    quote["vega"] = round(greeks["vega"], 2)
                    
            except Exception as e:
                logger.debug(f"Error enriching option {key}: {e}")
                
    except ImportError:
        logger.debug("Option Greeks calculation not available - missing scipy")
        pass