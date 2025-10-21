"""Terminal dashboard stub (placeholder).
Real implementation can provide multi-panel layout; this just prints a banner once.
"""
from __future__ import annotations

from .color import FG_CYAN, FG_GREEN, colorize


class TerminalDashboardStub:
    def __init__(self, refresh_interval: int = 10):
        self.refresh_interval = refresh_interval
        self._running = False

    def start(self):
        if self._running: return
        self._running = True
        print(colorize("[Enhanced Dashboard] (stub active)", FG_CYAN, bold=True))

    def stop(self):
        if not self._running: return
        self._running = False
        print(colorize("[Enhanced Dashboard stopped]", FG_GREEN, bold=True))

__all__ = ['TerminalDashboardStub']
