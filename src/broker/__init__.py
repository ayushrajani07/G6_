# -*- coding: utf-8 -*-
"""Broker module for G6 Platform."""
# Add this before launching the subprocess
import sys  # standard imports only
import os

# Only import what's actually available in our implementation
from .kite_provider import KiteProvider, DummyKiteProvider