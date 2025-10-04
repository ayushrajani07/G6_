"""Resync snapshot builder (Phase 4 stub).

This module provides a lightweight helper to produce the same structure as the
SSEPublisher "full_snapshot" event for future /summary/resync (HTTP) endpoint
implementation. No networking is performed here. The intent is to centralize
serialization logic so both SSE streaming and on-demand resync share a single
code path.

Public API:
    get_resync_snapshot(status: Mapping[str, Any] | None, *, cycle: int = 0,
                        domain: SummaryDomainSnapshot | None = None,
                        reuse_hashes: Mapping[str,str] | None = None) -> Dict[str, Any]

Behavior:
- Builds/uses a domain snapshot (if not provided) for panel registry parity.
- Computes panel hashes unless a precomputed map is supplied (hash reuse).
- Returns dict: {"cycle": int, "panels": {panel_key: {hash, title, lines}}}

Future enhancements:
- Include structured provenance / version metadata.
- Accept optional filters or inclusion masks for selective resync.
"""
from __future__ import annotations
from typing import Any, Mapping, Dict, Optional

from .panel_registry import build_all_panels, DEFAULT_PANEL_PROVIDERS
from .domain import build_domain_snapshot, SummaryDomainSnapshot
from .rich_diff import compute_panel_hashes, PANEL_KEYS

# Narrow surface; callers passing an invalid status won't raise.

def get_resync_snapshot(status: Mapping[str, Any] | None, *, cycle: int = 0,
                        domain: SummaryDomainSnapshot | None = None,
                        reuse_hashes: Mapping[str,str] | None = None) -> Dict[str, Any]:
    try:
        dom = domain or build_domain_snapshot(status)
    except Exception:
        dom = None
    hashes: Dict[str,str]
    if reuse_hashes and all(isinstance(k, str) and isinstance(v, str) for k,v in reuse_hashes.items()):
        hashes = dict(reuse_hashes)  # copy to avoid accidental mutation
    else:
        try:
            hashes = compute_panel_hashes(status if isinstance(status, Mapping) else None, domain=dom)
        except Exception:
            hashes = {}
    panels: Dict[str, Any] = {}
    panel_data = []
    if dom is not None:
        try:
            panel_data = build_all_panels(dom, providers=DEFAULT_PANEL_PROVIDERS)
        except Exception:
            panel_data = []
    pd_map: Dict[str, Any] = {p.key: p for p in panel_data}
    for key in PANEL_KEYS:
        pdata = pd_map.get(key)
        if pdata is not None:
            panels[key] = {
                'hash': hashes.get(key),
                'title': pdata.title,
                'lines': pdata.lines,
            }
        else:
            panels[key] = {
                'hash': hashes.get(key),
                'title': key.capitalize(),
                'lines': ['…'],
            }
    return {'cycle': cycle, 'panels': panels}

__all__ = ["get_resync_snapshot"]
