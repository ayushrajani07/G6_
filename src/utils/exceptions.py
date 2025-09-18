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


__all__ = [
    "G6Exception",
    "ConfigError",
    "APIError",
    "RetryError",
    "DataQualityError",
    "StorageError",
]
