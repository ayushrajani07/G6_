"""Shared schema version constant for summary snapshot & streaming payloads.

Central place so HTTP resync, SSE publisher, tests, and builders stay in sync.
Increment cautiously; bump only with backward-incompatible structural changes.
"""
from __future__ import annotations

SCHEMA_VERSION = "v1"

__all__ = ["SCHEMA_VERSION"]
