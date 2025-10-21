"""Centralized configuration parsing for summary/unified loop.

Consolidates scattered os.getenv calls so tests and future refactors can override
behavior via a single object. Keep lightweight; no external dependencies.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

try:  # local optional import (avoid hard dependency if moved)
    from src.utils.deprecations import emit_deprecation  # type: ignore
except Exception:  # pragma: no cover - defensive: fallback no-op
    def emit_deprecation(key: str, message: str, **_: object) -> None:  # type: ignore
        pass

_BOOL_TRUE = {"1","true","yes","on"}

def _b(val: str | None, default: bool = False) -> bool:
    if val is None:
        return default
    return val.lower() in _BOOL_TRUE

@dataclass(slots=True)
class SummaryConfig:
    # Unified configuration (legacy gating flags fully removed 2025-10-03).
    rewrite_active: bool  # always True (legacy flag removed)
    sse_enabled: bool     # True when SSE HTTP serving or panels ingestion configured
    sse_heartbeat_cycles: int
    unified_metrics: bool
    panels_dir: str
    write_panels: bool
    resync_http: bool
    resync_port: int
    dossier_path: str | None
    panels_sse_url: str | None

    @classmethod
    def load(cls) -> SummaryConfig:
        # Auto-enable logic (Phase 7 G1):
        #  - Rewrite path is unconditional; ignore G6_SUMMARY_REWRITE value.
        #  - SSE publisher auto-enables when either:
        #        * G6_SSE_HTTP=1 (serving HTTP SSE directly), or
        #        * panels_sse_url configured (downstream panels ingestion enabled)
        #    G6_SSE_ENABLED no longer controls behavior (warning only).
        raw_panels_url = os.getenv("G6_PANELS_SSE_URL")
        sse_http_active = _b(os.getenv("G6_SSE_HTTP"))
        auto_sse = sse_http_active or bool(raw_panels_url)
        cfg = cls(
            rewrite_active=True,
            sse_enabled=auto_sse,
            sse_heartbeat_cycles=int(os.getenv("G6_SSE_HEARTBEAT_CYCLES", "5") or 5),
            unified_metrics=_b(os.getenv("G6_UNIFIED_METRICS")),
            panels_dir=os.getenv("G6_PANELS_DIR", "data/panels"),
            write_panels=not _b(os.getenv("G6_NO_WRITE_PANELS")),
            # Resync: previously opt-in via G6_SUMMARY_RESYNC_HTTP; now default ON when SSE auto-enabled
            # unless explicit opt-out G6_DISABLE_RESYNC_HTTP=1.
            resync_http=(not _b(os.getenv("G6_DISABLE_RESYNC_HTTP"))) and auto_sse,
            resync_port=int(os.getenv("G6_RESYNC_HTTP_PORT", "9316") or 9316),
            dossier_path=os.getenv("G6_SUMMARY_DOSSIER_PATH"),
            panels_sse_url=raw_panels_url,
        )

    # Legacy summary flags removed:
    #   G6_SUMMARY_REWRITE, G6_SSE_ENABLED,
    #   G6_SUMMARY_RESYNC_HTTP, G6_SUMMARY_PLAIN_DIFF.
        # Any export of those env vars is now silently ignored (no warning to avoid noise post-removal window).
        return cfg

__all__ = ["SummaryConfig"]
