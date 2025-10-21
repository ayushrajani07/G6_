"""Health utilities for Kite provider ecosystem.

Centralizes a simple health probe contract so both real and dummy providers
can expose a consistent structure. This keeps future extension (latency,
error rate, auth freshness) isolated here instead of duplicating logic.
"""
from __future__ import annotations

from typing import Any

# Minimal status schema (intentionally narrow)
# {'status': 'healthy'|'degraded'|'error', 'message': str}

def basic_health(status: bool, *, message_ok: str = 'OK', message_bad: str = 'Degraded') -> dict[str, Any]:
    return {'status': 'healthy' if status else 'degraded', 'message': message_ok if status else message_bad}

__all__ = ['basic_health']
