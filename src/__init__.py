# -*- coding: utf-8 -*-
"""G6 Options Trading Platform."""

# Add this before launching the subprocess
import sys  # noqa: F401
import os  # noqa: F401

# Import key components for convenience
try:
    from .broker.kite_provider import KiteProvider, DummyKiteProvider
except ImportError:
    # Skip if not available yet
    pass