"""
Option Spread Builder for G6 Platform
Creates and analyzes option spreads.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

logger = logging.getLogger(__name__)

class Leg:
    """Represents a single leg in an option spread."""

    def __init__(
        self,
        instrument_key: str,
        quantity: int = 1,
        is_buy: bool = True,
        data: dict[str, Any] | None = None
    ):
        self.instrument_key = instrument_key
        self.quantity = quantity
        self.is_buy = is_buy
        self.data = data or {}

    @property
    def price(self) -> float:
        """Get the current price of the leg."""
        if not self.data:
            return 0.0
        return float(self.data.get("last_price", 0.0))

    @property
    def value(self) -> float:
        """Get the current value of the leg (price * quantity, negative if selling)."""
        multiplier = 1 if self.is_buy else -1
        return self.price * self.quantity * multiplier

class Spread:
    """Represents an option spread with multiple legs."""

    def __init__(self, name: str):
        self.name = name
        self.legs: list[Leg] = []

    def add_leg(self, leg: Leg) -> Spread:
        """Add a leg to the spread."""
        self.legs.append(leg)
        return self

    def buy(self, instrument_key: str, quantity: int = 1, data: dict[str, Any] | None = None) -> Spread:
        """Add a buy leg to the spread."""
        self.legs.append(Leg(instrument_key, quantity, True, data))
        return self

    def sell(self, instrument_key: str, quantity: int = 1, data: dict[str, Any] | None = None) -> Spread:
        """Add a sell leg to the spread."""
        self.legs.append(Leg(instrument_key, quantity, False, data))
        return self

    @property
    def net_value(self) -> float:
        """Get the net value of the spread."""
        return sum(leg.value for leg in self.legs)

    @property
    def max_profit(self) -> float:
        """Calculate theoretical max profit if available."""
        # This is a simplistic calculation, would need enhancement for specific spread types
        return abs(self.net_value)  # Placeholder

    @property
    def max_loss(self) -> float:
        """Calculate theoretical max loss if available."""
        # This is a simplistic calculation, would need enhancement for specific spread types
        return abs(self.net_value)  # Placeholder

class SpreadBuilder:
    """Builds common option spread strategies."""

    def __init__(self, quote_provider: Any):
        self.provider = quote_provider

    def _get_quotes(self, instrument_keys: list[str]) -> dict[str, dict[str, Any]]:
        """Get quotes for instruments."""
        if hasattr(self.provider, 'get_quote'):
            return self.provider.get_quote(instrument_keys)
        return {}

    def long_straddle(
        self,
        index_symbol: str,
        expiry_date: date | datetime,
        strike: float,
        exchange: str = "NFO"
    ) -> Spread:
        """Create a long straddle (buy ATM call and put)."""
        # Find call and put options
        call_put_options = self.provider.option_instruments(
            index_symbol, expiry_date, [strike]
        )

        call_options = [opt for opt in call_put_options if opt.get("instrument_type") == "CE"]
        put_options = [opt for opt in call_put_options if opt.get("instrument_type") == "PE"]

        if not call_options or not put_options:
            raise ValueError(f"Could not find call and put options for {index_symbol} {expiry_date} {strike}")

        call = call_options[0]
        put = put_options[0]

        call_key = f"{exchange}:{call.get('tradingsymbol')}"
        put_key = f"{exchange}:{put.get('tradingsymbol')}"

        # Get quotes
        quotes = self._get_quotes([call_key, put_key])

        # Create spread
        spread = Spread("Long Straddle")
        spread.buy(call_key, 1, quotes.get(call_key))
        spread.buy(put_key, 1, quotes.get(put_key))

        return spread

    def short_straddle(
        self,
        index_symbol: str,
        expiry_date: date | datetime,
        strike: float,
        exchange: str = "NFO"
    ) -> Spread:
        """Create a short straddle (sell ATM call and put)."""
        # Find call and put options
        call_put_options = self.provider.option_instruments(
            index_symbol, expiry_date, [strike]
        )

        call_options = [opt for opt in call_put_options if opt.get("instrument_type") == "CE"]
        put_options = [opt for opt in call_put_options if opt.get("instrument_type") == "PE"]

        if not call_options or not put_options:
            raise ValueError(f"Could not find call and put options for {index_symbol} {expiry_date} {strike}")

        call = call_options[0]
        put = put_options[0]

        call_key = f"{exchange}:{call.get('tradingsymbol')}"
        put_key = f"{exchange}:{put.get('tradingsymbol')}"

        # Get quotes
        quotes = self._get_quotes([call_key, put_key])

        # Create spread
        spread = Spread("Short Straddle")
        spread.sell(call_key, 1, quotes.get(call_key))
        spread.sell(put_key, 1, quotes.get(put_key))

        return spread

    def long_strangle(
        self,
        index_symbol: str,
        expiry_date: date | datetime,
        center_strike: float,
        width: float,
        exchange: str = "NFO"
    ) -> Spread:
        """Create a long strangle (buy OTM call and put)."""
        call_strike = center_strike + width
        put_strike = center_strike - width

        # Find call and put options
        call_put_options = self.provider.option_instruments(
            index_symbol, expiry_date, [call_strike, put_strike]
        )

        call_options = [opt for opt in call_put_options if opt.get("instrument_type") == "CE" and float(opt.get("strike", 0)) == call_strike]
        put_options = [opt for opt in call_put_options if opt.get("instrument_type") == "PE" and float(opt.get("strike", 0)) == put_strike]

        if not call_options or not put_options:
            raise ValueError(f"Could not find call and put options for {index_symbol} {expiry_date} strangle")

        call = call_options[0]
        put = put_options[0]

        call_key = f"{exchange}:{call.get('tradingsymbol')}"
        put_key = f"{exchange}:{put.get('tradingsymbol')}"

        # Get quotes
        quotes = self._get_quotes([call_key, put_key])

        # Create spread
        spread = Spread("Long Strangle")
        spread.buy(call_key, 1, quotes.get(call_key))
        spread.buy(put_key, 1, quotes.get(put_key))

        return spread

    def iron_condor(
        self,
        index_symbol: str,
        expiry_date: date | datetime,
        center_strike: float,
        inner_width: float,
        outer_width: float,
        exchange: str = "NFO"
    ) -> Spread:
        """Create an iron condor."""
        put_sell_strike = center_strike - inner_width
        put_buy_strike = center_strike - outer_width
        call_sell_strike = center_strike + inner_width
        call_buy_strike = center_strike + outer_width

        # Find options
        options = self.provider.option_instruments(
            index_symbol, expiry_date,
            [put_buy_strike, put_sell_strike, call_sell_strike, call_buy_strike]
        )

        put_buy_options = [opt for opt in options if opt.get("instrument_type") == "PE" and float(opt.get("strike", 0)) == put_buy_strike]
        put_sell_options = [opt for opt in options if opt.get("instrument_type") == "PE" and float(opt.get("strike", 0)) == put_sell_strike]
        call_sell_options = [opt for opt in options if opt.get("instrument_type") == "CE" and float(opt.get("strike", 0)) == call_sell_strike]
        call_buy_options = [opt for opt in options if opt.get("instrument_type") == "CE" and float(opt.get("strike", 0)) == call_buy_strike]

        if not put_buy_options or not put_sell_options or not call_sell_options or not call_buy_options:
            raise ValueError(f"Could not find all options for {index_symbol} {expiry_date} iron condor")

        put_buy = put_buy_options[0]
        put_sell = put_sell_options[0]
        call_sell = call_sell_options[0]
        call_buy = call_buy_options[0]

        put_buy_key = f"{exchange}:{put_buy.get('tradingsymbol')}"
        put_sell_key = f"{exchange}:{put_sell.get('tradingsymbol')}"
        call_sell_key = f"{exchange}:{call_sell.get('tradingsymbol')}"
        call_buy_key = f"{exchange}:{call_buy.get('tradingsymbol')}"

        # Get quotes
        quotes = self._get_quotes([put_buy_key, put_sell_key, call_sell_key, call_buy_key])

        # Create spread
        spread = Spread("Iron Condor")
        spread.buy(put_buy_key, 1, quotes.get(put_buy_key))
        spread.sell(put_sell_key, 1, quotes.get(put_sell_key))
        spread.sell(call_sell_key, 1, quotes.get(call_sell_key))
        spread.buy(call_buy_key, 1, quotes.get(call_buy_key))

        return spread

    def butterfly(
        self,
        index_symbol: str,
        expiry_date: date | datetime,
        center_strike: float,
        width: float,
        option_type: str = "CE",
        exchange: str = "NFO"
    ) -> Spread:
        """Create a butterfly spread."""
        low_strike = center_strike - width
        high_strike = center_strike + width

        # Find options
        options = self.provider.option_instruments(
            index_symbol, expiry_date,
            [low_strike, center_strike, high_strike]
        )

        low_options = [opt for opt in options if opt.get("instrument_type") == option_type and float(opt.get("strike", 0)) == low_strike]
        center_options = [opt for opt in options if opt.get("instrument_type") == option_type and float(opt.get("strike", 0)) == center_strike]
        high_options = [opt for opt in options if opt.get("instrument_type") == option_type and float(opt.get("strike", 0)) == high_strike]

        if not low_options or not center_options or not high_options:
            raise ValueError(f"Could not find all options for {index_symbol} {expiry_date} butterfly")

        low = low_options[0]
        center = center_options[0]
        high = high_options[0]

        low_key = f"{exchange}:{low.get('tradingsymbol')}"
        center_key = f"{exchange}:{center.get('tradingsymbol')}"
        high_key = f"{exchange}:{high.get('tradingsymbol')}"

        # Get quotes
        quotes = self._get_quotes([low_key, center_key, high_key])

        # Create spread
        spread = Spread(f"{option_type} Butterfly")
        spread.buy(low_key, 1, quotes.get(low_key))
        spread.sell(center_key, 2, quotes.get(center_key))
        spread.buy(high_key, 1, quotes.get(high_key))

        return spread
