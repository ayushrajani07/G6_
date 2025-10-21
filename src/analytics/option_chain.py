"""
Option Chain Analytics for G6 Platform
Provides advanced option chain metrics and analysis.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

import pandas as pd

from src.error_handling import (
    handle_api_error,
    handle_provider_error,
)

logger = logging.getLogger(__name__)

class OptionChainAnalytics:
    """Advanced analytics for option chains."""

    def __init__(self, provider: Any):
        self.provider = provider

    def fetch_option_chain(
        self,
        index_symbol: str,
        expiry_date: date | datetime,
        strike_range: tuple[float, float],
        strike_step: float | None = None
    ) -> pd.DataFrame:
        """
        Fetch complete option chain for an index within strike range.
        
        Returns a DataFrame with options data.
        """
        min_strike, max_strike = strike_range

        # Determine strike step from registry if not explicitly provided
        if strike_step is None:
            try:
                from src.utils.index_registry import get_index_meta
                strike_step = float(get_index_meta(index_symbol).step)
                if strike_step <= 0:
                    strike_step = 50.0
            except Exception:
                # Fallback legacy heuristic
                strike_step = 100.0 if "BANK" in index_symbol.upper() or "SENSEX" in index_symbol.upper() else 50.0

        # Generate strikes within range
        strikes = []
        current_strike = min_strike
        while current_strike <= max_strike:
            strikes.append(current_strike)
            current_strike += strike_step

        # Get option instruments
        instruments = []
        try:
            instruments = self.provider.option_instruments(
                index_symbol, expiry_date, strikes
            )
        except AttributeError:
            # Try alternate method name
            if hasattr(self.provider, 'get_option_instruments'):
                try:
                    instruments = self.provider.get_option_instruments(index_symbol, expiry_date, strikes)  # type: ignore
                except Exception as e:  # pragma: no cover
                    # Route provider error centrally, keep existing log for behavior
                    handle_provider_error(
                        e,
                        component="analytics.option_chain",
                        index_name=index_symbol,
                        context={"expiry": str(expiry_date)},
                    )
                    logger.error(f"Provider get_option_instruments failed: {e}")
            else:
                # Provider capability missing -> configuration issue
                handle_api_error(
                    AttributeError("missing option instruments API"),
                    component="analytics.option_chain",
                    context={"index": index_symbol, "expiry": str(expiry_date)},
                )
                logger.error("Provider missing option_instruments / get_option_instruments; returning empty chain")
        except Exception as e:
            handle_provider_error(
                e,
                component="analytics.option_chain",
                index_name=index_symbol,
                context={"expiry": str(expiry_date)},
            )
            logger.error(f"Error fetching option instruments: {e}")

        # Get all option symbols
        option_keys = []
        for inst in instruments:
            exchange = inst.get("exchange", "NFO")
            symbol = inst.get("tradingsymbol")
            if symbol:
                option_keys.append((exchange, symbol))

        # Get quotes
        quotes = {}
        if option_keys:
            try:
                quotes = self.provider.get_quote(option_keys)
            except Exception as e:
                handle_provider_error(
                    e,
                    component="analytics.option_chain",
                    index_name=index_symbol,
                    context={"num_keys": len(option_keys)},
                )
                logger.error(f"Error fetching quotes for option chain: {e}")

        # Convert to DataFrame
        rows = []
        for inst in instruments:
            exchange = inst.get("exchange", "NFO")
            symbol = inst.get("tradingsymbol")
            key = f"{exchange}:{symbol}"
            quote = quotes.get(key, {})

            # Some providers may omit OI or volume fields; default to 0 and log once
            row = {
                "symbol": symbol,
                "strike": float(inst.get("strike", 0)),
                "expiry": inst.get("expiry"),
                "type": inst.get("instrument_type"),
                "last_price": float(quote.get("last_price", 0)),
                "volume": int(quote.get("volume", 0)),
                "buy_quantity": int(quote.get("buy_quantity", 0)),
                "sell_quantity": int(quote.get("sell_quantity", 0)),
                "oi": int(quote.get("oi", 0)),
                "change": float(quote.get("change", 0)),
                "bid": float(quote.get("depth", {}).get("buy", [{}])[0].get("price", 0)),
                "ask": float(quote.get("depth", {}).get("sell", [{}])[0].get("price", 0)),
            }
            rows.append(row)

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)

        # Add call/put columns for analysis
        call_df = df[df["type"] == "CE"].copy()
        put_df = df[df["type"] == "PE"].copy()

        merged_df = pd.merge(
            call_df, put_df, on="strike", how="outer",
            suffixes=("_call", "_put")
        )

        return merged_df

    def calculate_pcr(
        self,
        index_symbol: str,
        expiry_date: date | datetime,
        width_percent: float = 0.05
    ) -> dict[str, float]:
        """
        Calculate Put-Call Ratio metrics.
        
        Args:
            index_symbol: Index symbol (e.g., "NIFTY")
            expiry_date: Expiry date
            width_percent: Width percentage around ATM to consider
            
        Returns:
            Dict with various PCR metrics
        """
        # Get ATM strike
        if hasattr(self.provider, 'get_atm_strike'):
            atm_strike = self.provider.get_atm_strike(index_symbol)
        else:  # Fallback to LTP rounding logic
            try:
                atm_strike = self.provider.get_ltp(index_symbol)
            except Exception:
                handle_api_error(
                    AttributeError("missing ATM strike capability"),
                    component="analytics.option_chain",
                    context={"index": index_symbol},
                )
                logger.error("Provider missing ATM strike capability; defaulting to 0")
                atm_strike = 0

        # Calculate strike range
        current_price = float(atm_strike)
        range_width = current_price * width_percent
        min_strike = current_price - range_width
        max_strike = current_price + range_width

        # Get option chain
        option_chain = self.fetch_option_chain(
            index_symbol, expiry_date, (min_strike, max_strike)
        )

        if option_chain.empty:
            logger.debug(f"Empty option chain for {index_symbol} {expiry_date}; PCR defaults to 0")
            return {"oi_pcr": 0.0, "volume_pcr": 0.0}

        # Calculate PCR
        total_call_oi = option_chain["oi_call"].sum()
        total_put_oi = option_chain["oi_put"].sum()

        total_call_volume = option_chain["volume_call"].sum()
        total_put_volume = option_chain["volume_put"].sum()

        oi_pcr = total_put_oi / total_call_oi if total_call_oi > 0 else 0
        volume_pcr = total_put_volume / total_call_volume if total_call_volume > 0 else 0

        return {
            "oi_pcr": oi_pcr,
            "volume_pcr": volume_pcr
        }

    def calculate_max_pain(
        self,
        index_symbol: str,
        expiry_date: date | datetime
    ) -> float:
        """
        Calculate max pain point (strike where option writers have minimum pain).
        
        Returns the strike price where max pain occurs.
        """
        # Get ATM strike
        if hasattr(self.provider, 'get_atm_strike'):
            atm_strike = self.provider.get_atm_strike(index_symbol)
        else:
            try:
                atm_strike = self.provider.get_ltp(index_symbol)
            except Exception:
                handle_api_error(
                    AttributeError("missing ATM strike capability"),
                    component="analytics.option_chain",
                    context={"index": index_symbol},
                )
                logger.error("Provider missing ATM strike capability; defaulting to 0")
                atm_strike = 0

        # Calculate strike range (wide enough for max pain)
        current_price = float(atm_strike)
        range_width = current_price * 0.1  # 10% range
        min_strike = current_price - range_width
        max_strike = current_price + range_width

        # Get option chain
        option_chain = self.fetch_option_chain(
            index_symbol, expiry_date, (min_strike, max_strike)
        )

        if option_chain.empty:
            logger.debug(f"Empty option chain for max pain calculation {index_symbol} {expiry_date}; returning ATM {atm_strike}")
            return atm_strike

        # Get unique strikes
        strikes = sorted(option_chain["strike"].unique())

        # Calculate pain at each potential expiry price
        min_pain = float("inf")
        max_pain_strike = atm_strike

        for potential_price in strikes:
            # Calculate pain for call options
            call_pain = 0
            for _, row in option_chain[option_chain["type_call"] == "CE"].iterrows():
                strike = row["strike"]
                oi = row["oi_call"]
                if potential_price > strike:
                    # Call ITM, pain to writers
                    call_pain += oi * (potential_price - strike)

            # Calculate pain for put options
            put_pain = 0
            for _, row in option_chain[option_chain["type_put"] == "PE"].iterrows():
                strike = row["strike"]
                oi = row["oi_put"]
                if potential_price < strike:
                    # Put ITM, pain to writers
                    put_pain += oi * (strike - potential_price)

            # Total pain at this price point
            total_pain = call_pain + put_pain

            # Update max pain if this is lower
            if total_pain < min_pain:
                min_pain = total_pain
                max_pain_strike = potential_price

        return max_pain_strike

    def calculate_support_resistance(
        self,
        index_symbol: str,
        expiry_date: date | datetime
    ) -> dict[str, list[float]]:
        """
        Calculate support and resistance levels from option chain.
        
        Returns dict with "support" and "resistance" lists of levels.
        """
        # Get ATM strike
        if hasattr(self.provider, 'get_atm_strike'):
            atm_strike = self.provider.get_atm_strike(index_symbol)
        else:
            try:
                atm_strike = self.provider.get_ltp(index_symbol)
            except Exception:
                handle_api_error(
                    AttributeError("missing ATM strike capability"),
                    component="analytics.option_chain",
                    context={"index": index_symbol},
                )
                logger.error("Provider missing ATM strike capability; defaulting to 0")
                atm_strike = 0

        # Calculate strike range
        current_price = float(atm_strike)
        range_width = current_price * 0.1  # 10% range
        min_strike = current_price - range_width
        max_strike = current_price + range_width

        # Get option chain
        option_chain = self.fetch_option_chain(
            index_symbol, expiry_date, (min_strike, max_strike)
        )

        if option_chain.empty:
            return {"support": [], "resistance": []}

        # Find support levels (put OI clusters)
        put_data = option_chain[["strike", "oi_put"]].dropna()
        put_data = put_data.sort_values("oi_put", ascending=False)

        # Find resistance levels (call OI clusters)
        call_data = option_chain[["strike", "oi_call"]].dropna()
        call_data = call_data.sort_values("oi_call", ascending=False)

        # Get top levels
        support_levels = []
        for _, row in put_data.head(3).iterrows():
            if row["strike"] < current_price:  # Only consider strikes below current price
                support_levels.append(float(row["strike"]))

        resistance_levels = []
        for _, row in call_data.head(3).iterrows():
            if row["strike"] > current_price:  # Only consider strikes above current price
                resistance_levels.append(float(row["strike"]))

        return {
            "support": sorted(support_levels),
            "resistance": sorted(resistance_levels)
        }
