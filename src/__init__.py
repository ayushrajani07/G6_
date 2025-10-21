"""G6 Options Trading Platform."""

# Add this before launching the subprocess
import os  # noqa: F401
import sys  # noqa: F401

# Import key components for convenience
try:
    from .broker.kite_provider import DummyKiteProvider, KiteProvider
except ImportError:
    # Skip if not available yet
    pass
