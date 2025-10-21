"""
Option Greeks Calculator for G6 Platform
Calculates theoretical option prices and greeks.
"""

from __future__ import annotations

import logging
import math
from datetime import UTC, date, datetime
from datetime import time as _time

from src.error_handling import handle_api_error

try:  # Prefer scipy for accuracy
    from scipy.stats import norm  # type: ignore
except Exception:  # Fallback minimal normal cdf/pdf implementation
    class _NormApprox:
        @staticmethod
        def cdf(x: float) -> float:
            # Abramowitz-Stegun approximation via error function
            import math
            return 0.5 * (1.0 + math.erf(x / math.sqrt(2)))
        @staticmethod
        def pdf(x: float) -> float:
            import math
            return (1.0 / math.sqrt(2 * math.pi)) * math.exp(-0.5 * x * x)
    norm = _NormApprox()  # type: ignore

logger = logging.getLogger(__name__)

class OptionGreeks:
    """Calculate option theoretical prices and greeks."""

    def __init__(
        self,
        risk_free_rate: float = 0.05,  # 5% as default
        use_actual_dte: bool = True
    ):
        self.risk_free_rate = risk_free_rate
        self.use_actual_dte = use_actual_dte

    @staticmethod
    def _calculate_dte(expiry_date: date | datetime, current_date: date | datetime | None = None) -> float:
        """Calculate time to expiry in years.

        Improves handling of same-day expiry by using intraday time until 15:30 local,
        instead of truncating to 0 days. If `expiry_date` is a date, we assume options
        expire at 15:30 local time on that day (Indian markets convention). For a
        datetime input, it is used as-is.
        """
        # Current timestamp (timezone-aware, UTC) by default to avoid naive datetimes
        now_dt = None
        if current_date is None:
            # Use UTC now to ensure timezone awareness in calculations
            now_dt = datetime.now(UTC)
        else:
            # Coerce provided current_date to datetime
            if isinstance(current_date, datetime):
                # If provided datetime is naive, assume UTC to avoid timezone-mismatch
                now_dt = current_date if (current_date.tzinfo is not None) else current_date.replace(tzinfo=UTC)
            else:
                # Treat provided date as "now" at current local time (best effort)
                # If caller provided only date, default to start of day to avoid negative durations
                now_dt = datetime.combine(current_date, _time(0, 0, 0)).replace(tzinfo=UTC)

        # Coerce expiry input to a concrete datetime
        if isinstance(expiry_date, datetime):
            exp_dt = expiry_date
        else:
            # Assume market expiry at 15:30 UTC for date-only inputs to keep timezone-aware arithmetic
            exp_dt = datetime.combine(expiry_date, _time(15, 30, 0)).replace(tzinfo=UTC)

        # Compute fractional years, clamp at 0
        seconds = (exp_dt - now_dt).total_seconds()
        if seconds <= 0:
            return 0.0
        return seconds / (365.0 * 24.0 * 3600.0)

    def black_scholes(
        self,
        is_call: bool,
        S: float,  # Spot price
        K: float,  # Strike price
        T: float | datetime | date,  # Time to expiry in years or expiry date
        r: float | None = None,  # Risk-free rate
        sigma: float = 0.20,  # Implied volatility / historical volatility
        q: float = 0.0,  # Dividend yield
        current_date: date | datetime | None = None
    ) -> dict[str, float]:
        """
        Calculate option price and greeks using Black-Scholes model.
        
        Args:
            is_call: True for call option, False for put option
            S: Current stock/index price
            K: Strike price
            T: Time to expiry in years or expiry date
            r: Risk-free interest rate (annual)
            sigma: Volatility (annual)
            q: Dividend yield
            current_date: Current date for DTE calculation if T is a date
            
        Returns:
            Dict with option price and greeks
        """
        # Handle date inputs for T
        if isinstance(T, (date, datetime)):
            T = self._calculate_dte(T, current_date)

        # Use default risk-free rate if not provided
        if r is None:
            r = self.risk_free_rate

        # Handle edge cases
        if T <= 0 or sigma <= 0:
            return self._intrinsic_value(is_call, S, K)

        try:
            # Black-Scholes formula
            d1 = (math.log(S/K) + (r - q + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
            d2 = d1 - sigma * math.sqrt(T)

            # Calculate option price
            if is_call:
                price = S * math.exp(-q * T) * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
            else:
                price = K * math.exp(-r * T) * norm.cdf(-d2) - S * math.exp(-q * T) * norm.cdf(-d1)

            # Calculate greeks
            delta = math.exp(-q * T) * norm.cdf(d1) if is_call else math.exp(-q * T) * (norm.cdf(d1) - 1)

            gamma = math.exp(-q * T) * norm.pdf(d1) / (S * sigma * math.sqrt(T))

            theta_days = -(S * sigma * math.exp(-q * T) * norm.pdf(d1)) / (2 * math.sqrt(T))
            if is_call:
                theta_days -= r * K * math.exp(-r * T) * norm.cdf(d2) - q * S * math.exp(-q * T) * norm.cdf(d1)
            else:
                theta_days -= r * K * math.exp(-r * T) * norm.cdf(-d2) - q * S * math.exp(-q * T) * norm.cdf(-d1)

            # Convert theta to daily
            theta = theta_days / 365.0

            vega = S * math.exp(-q * T) * norm.pdf(d1) * math.sqrt(T) / 100  # For 1% change in vol

            rho = K * T * math.exp(-r * T) * norm.cdf(d2) / 100 if is_call else -K * T * math.exp(-r * T) * norm.cdf(-d2) / 100

            return {
                "price": price,
                "delta": delta,
                "gamma": gamma,
                "theta": theta,
                "vega": vega,
                "rho": rho
            }

        except Exception as e:
            # Route analytics calculation error centrally; keep log and fallback
            handle_api_error(e, component="analytics.option_greeks", context={"fn": "black_scholes"})
            logger.error(f"Black-Scholes calculation error: {e}")
            return {
                "price": 0.0,
                "delta": 0.0,
                "gamma": 0.0,
                "theta": 0.0,
                "vega": 0.0,
                "rho": 0.0
            }

    def _intrinsic_value(self, is_call: bool, S: float, K: float) -> dict[str, float]:
        """Calculate intrinsic value for expired/near-expired options."""
        if is_call:
            price = max(0, S - K)
            delta = 1.0 if S > K else 0.0
        else:
            price = max(0, K - S)
            delta = -1.0 if S < K else 0.0

        return {
            "price": price,
            "delta": delta,
            "gamma": 0.0,
            "theta": 0.0,
            "vega": 0.0,
            "rho": 0.0
        }

    def implied_volatility(
        self,
        is_call: bool,
        S: float,
        K: float,
        T: float | datetime | date,
        market_price: float,
        r: float | None = None,
        q: float = 0.0,
        current_date: date | datetime | None = None,
        precision: float = 0.00001,
        max_iterations: int = 100,
        min_iv: float = 0.01,
        max_iv: float = 5.0,
        return_iterations: bool = False
    ) -> float | tuple[float, int]:
        """
        Calculate implied volatility using Newton-Raphson method.
        
        Returns the implied volatility or 0.0 if cannot be calculated.
        Parameters
        ----------
        min_iv / max_iv : float
            Hard bounds for solver (clamped each iteration).
        return_iterations : bool
            When True returns tuple (iv, iterations_used) for metrics instrumentation.
        """
        # Handle date inputs for T
        if isinstance(T, (date, datetime)):
            T = self._calculate_dte(T, current_date)

        # Use default risk-free rate if not provided
        if r is None:
            r = self.risk_free_rate

        # Handle edge cases
        if T <= 0:
            return (0.0, 0) if return_iterations else 0.0

        if market_price <= 0.01:
            return (min_iv, 0) if return_iterations else min_iv  # Minimum IV to avoid division by zero issues

        # Initial guess
        sigma = 0.3  # 30% as starting point
        if sigma < min_iv:
            sigma = min_iv
        if sigma > max_iv:
            sigma = max_iv

        # Newton-Raphson iterations
        iterations_used = 0
        for i in range(max_iterations):
            iterations_used = i + 1
            bs_price = self.black_scholes(is_call, S, K, T, r, sigma, q)["price"]
            price_diff = bs_price - market_price

            if abs(price_diff) < precision:
                return (sigma, iterations_used) if return_iterations else sigma

            vega = self.black_scholes(is_call, S, K, T, r, sigma, q)["vega"] * 100  # Convert back from 1% to 1.0 scale
            if abs(vega) < 1e-10:
                return (sigma, iterations_used) if return_iterations else sigma

            sigma = sigma - price_diff / vega

            # Bounds check
            if sigma < min_iv:
                sigma = min_iv
            elif sigma > max_iv:
                sigma = max_iv

        # If we didn't converge, return our best guess
        return (sigma, iterations_used) if return_iterations else sigma
