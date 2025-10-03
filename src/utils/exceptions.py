"""G6 Platform exception hierarchy.

Define a small, clear exception tree for categorizing failures across the
platform. Use these to communicate intent up the stack and enable targeted
retry, metrics, and user-facing messages.
"""
from __future__ import annotations


class G6Exception(Exception):
    """Base class for all G6 exceptions."""


class ConfigError(G6Exception):
    """Configuration-related issues (missing/invalid keys, schema errors)."""


class APIError(G6Exception):
    """Upstream API errors (network/auth/server)."""


class RetryError(G6Exception):
    """Raised when a retryable operation ultimately fails after retries."""


class DataQualityError(G6Exception):
    """Raised when data fails validation or sanity checks."""


class StorageError(G6Exception):
    """Persistence layer failures (CSV/Influx/FS)."""


# Collector step-specific exceptions for clearer diagnostics
class ResolveExpiryError(G6Exception):
    """Failure resolving expiry date from provider for a given rule/index."""


class NoInstrumentsError(G6Exception):
    """No option instruments found for index/expiry/strikes request."""


class NoQuotesError(G6Exception):
    """No quotes were returned for requested option instruments."""


class CsvWriteError(StorageError):
    """CSV persistence failure for options data or overview snapshots."""


class InfluxWriteError(StorageError):
    """InfluxDB persistence failure for options data or snapshots."""


__all__ = [
    "G6Exception",
    "ConfigError",
    "APIError",
    "RetryError",
    "DataQualityError",
    "StorageError",
    "ResolveExpiryError",
    "NoInstrumentsError",
    "NoQuotesError",
    "CsvWriteError",
    "InfluxWriteError",
]
