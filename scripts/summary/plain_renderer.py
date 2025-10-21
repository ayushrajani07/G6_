"""Plain terminal renderer using the new domain + panel registry (Phase 1).

Activated when the rewrite flag is enabled and rich mode is disabled.
"""
from __future__ import annotations

import hashlib
import os
import sys
from collections.abc import Mapping
from typing import Any

from .domain import build_domain_snapshot
from .panel_registry import build_all_panels
from .plugins.base import OutputPlugin, SummarySnapshot  # reuse existing snapshot container


class PlainRenderer(OutputPlugin):
    name = "plain_renderer"

    def __init__(self, *, max_width: int = 160) -> None:
        self._max_width = max_width
        self._last_hash: str | None = None
        # Diff suppression can be disabled via env (flag reinstated for backward compatibility)
        # Read environment directly so test monkeypatching before instantiation is honored without cached summary env
        self._diff_enabled = os.getenv('G6_SUMMARY_PLAIN_DIFF', '1').lower() in {'1','true','yes','on'}

    def setup(self, context: Mapping[str, Any]) -> None:  # pragma: no cover - trivial
        pass

    def process(self, snap: SummarySnapshot) -> None:  # pragma: no cover - exercised via tests
        # Build domain snapshot from raw status (Phase 1 bridge)
        domain = build_domain_snapshot(snap.status, ts_read=snap.ts_read)
        panels = build_all_panels(domain)
        out_lines = []
        for p in panels:
            out_lines.append(f"[{p.title}]")
            for line in p.lines:
                # Simple width clamp; richer formatting can follow
                clipped = (line[: self._max_width - 1] + '…') if len(line) > self._max_width else line
                out_lines.append(clipped)
            out_lines.append("")
        rendered = "\n".join(out_lines).rstrip() + "\n"
        if self._diff_enabled:
            h = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
            if self._last_hash == h:
                return  # suppress unchanged frame
            self._last_hash = h
        # If diff disabled, intentionally always emit (no suppression)
        stream = sys.stdout
        try:
            stream.write(rendered)
        except Exception:
            pass

    def teardown(self) -> None:  # pragma: no cover - trivial
        pass

__all__ = ["PlainRenderer"]
