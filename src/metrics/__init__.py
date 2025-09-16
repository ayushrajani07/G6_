#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Metrics module for G6 Platform."""

# Add this before launching the subprocess
import sys  # noqa: F401
import os  # noqa: F401

from .metrics import MetricsRegistry, setup_metrics_server