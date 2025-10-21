"""SSE Publisher Plugin (Phase 4 Scaffold)

This is a non-networking scaffold that prepares event payloads for a future
HTTP layer exposing a text/event-stream endpoint. It:

- Computes per-panel hashes (reusing rich_diff) each cycle.
- Determines which panels changed vs prior cycle.
- Produces structured event dicts appended to an internal queue (for tests).

Networking, concurrency, and actual streaming lifecycles are intentionally
omitted until the interface stabilizes.
"""
from __future__ import annotations

import logging
import os
import time
from collections.abc import Mapping
from typing import Any

try:
    from prometheus_client import Histogram  # type: ignore
except Exception:  # pragma: no cover - optional
    Histogram = None  # type: ignore

from scripts.summary.domain import SummaryDomainSnapshot, build_domain_snapshot
from scripts.summary.hashing import PANEL_KEYS, compute_all_panel_hashes
from scripts.summary.panel_registry import build_all_panels, build_panels_subset
from scripts.summary.schema import SCHEMA_VERSION

from .base import OutputPlugin, SummarySnapshot

logger = logging.getLogger(__name__)

class SSEPublisher(OutputPlugin):
    name = "sse_publisher"

    def __init__(self, *, diff: bool = True) -> None:
        # Legacy env gating (G6_SSE_ENABLED) removed; publisher always active when instantiated.
        # Upstream logic decides whether to construct this plugin based on HTTP/panels configuration.
        self._enabled = True
        self._diff_mode = diff
        # Structured diff mode (Phase 7): emit subset panel map under 'panel_diff' events
        self._structured = os.getenv("G6_SSE_STRUCTURED", "0").lower() in {"1","true","yes","on"}
        self._last_hashes: dict[str,str] | None = None
        self._events: list[dict[str, Any]] = []  # captured events (MVP, for inspection/tests)
        self._cycle = 0
        self._heartbeat_cycles = int(os.getenv("G6_SSE_HEARTBEAT_CYCLES", "5") or 5)
        self._since_change = 0
        # Metrics counters (internal only, surfaced via panel_push_meta)
        self._m_events_total = 0
        self._m_full_snapshots = 0
        self._m_panel_updates = 0
        self._m_heartbeats = 0
        self._m_errors = 0
        # perf profiling toggled by env G6_SSE_PERF_PROFILE
        self._perf_enabled = os.getenv("G6_SSE_PERF_PROFILE", "0").lower() in {"1","true","yes","on"}
        self._h_diff_build = None
        self._h_emit_latency = None
        if self._perf_enabled and Histogram is not None:
            try:
                self._h_diff_build = Histogram(
                    'g6_sse_pub_diff_build_seconds',
                    'Time to build diff/full snapshot panels',
                    buckets=(
                        0.0005, 0.001, 0.002, 0.005, 0.01,
                        0.02, 0.05, 0.1, 0.25, 0.5,
                    ),
                )
                self._h_emit_latency = Histogram(
                    'g6_sse_pub_emit_latency_seconds',
                    'Latency between enqueue timestamp tag and post-append (internal)',
                    buckets=(0.0001, 0.0005, 0.001, 0.002, 0.005, 0.01, 0.02),
                )
            except Exception:
                pass
        # Instrumentation: how often we had to rebuild domain internally (should be 0 once loop passes domain)
        self._domain_rebuilds = 0

    # Public accessor for tests
    @property
    def events(self) -> list[dict[str, Any]]:
        return list(self._events)

    def setup(self, context: Mapping[str, Any]) -> None:  # pragma: no cover - trivial
        if not self._enabled:
            logger.debug("[sse] disabled via env")
        else:
            logger.debug("[sse] enabled (diff=%s)", self._diff_mode)

    def process(self, snap: SummarySnapshot) -> None:  # pragma: no cover - behavior covered indirectly
        if not self._enabled:
            return
        status = snap.status if isinstance(snap.status, Mapping) else None
        # Direct domain reuse: prefer the pre-built domain snapshot if supplied by unified loop.
        domain: SummaryDomainSnapshot | None = snap.domain if getattr(snap, 'domain', None) is not None else None
        # Reuse pre-computed hashes (unified loop) or meta; else compute centrally
        hashes = getattr(snap, 'panel_hashes', None)
        # Attempt legacy meta reuse if not on snapshot (transitional)
        try:
            if hashes is None and isinstance(status, dict):
                phm = status.get('panel_push_meta') if isinstance(status.get('panel_push_meta'), dict) else None
                if phm and isinstance(phm.get('shared_hashes'), dict):
                    candidate = phm.get('shared_hashes')
                    if candidate and all(isinstance(k, str) and isinstance(v, str) for k,v in candidate.items()):
                        hashes = candidate  # type: ignore[assignment]
        except Exception:
            hashes = None
        if hashes is None:
            t0_hash = time.perf_counter() if self._perf_enabled else 0.0
            try:
                hashes = compute_all_panel_hashes(status, domain=domain)
            except Exception as e:  # noqa: BLE001
                logger.debug("[sse] hash compute failed: %s", e)
                self._emit({"event": "error", "data": {"message": str(e), "recoverable": True}})
                return
            finally:
                if self._perf_enabled and self._h_diff_build is not None:
                    try:
                        self._h_diff_build.observe(
                            max(0.0, time.perf_counter() - t0_hash)
                        )  # type: ignore[attr-defined]
                    except Exception:
                        pass
        self._cycle = snap.cycle
        if self._last_hashes is None:
            # Initial connect semantics: hello + full snapshot
            hello_payload = {
                "cycle": snap.cycle,
                "version": self._extract_version(status),
                "schema_version": SCHEMA_VERSION,
                "panels": [{"key": k, "hash": v} for k,v in hashes.items()]
            }
            if self._structured:
                hello_payload["diff_mode"] = "structured"
            self._emit({"event": "hello", "data": hello_payload})
            full_payload = self._build_full_snapshot(status, hashes, domain=domain)
            full_payload["schema_version"] = SCHEMA_VERSION
            if self._structured:
                full_payload["structured"] = True
            self._emit({"event": "full_snapshot", "data": full_payload})
            self._last_hashes = hashes
            self._since_change = 0
            self._m_full_snapshots += 1
            self._inject_meta(status)
            return
        # Diff mode path
        changed: list[str] = [k for k,v in hashes.items() if self._last_hashes.get(k) != v]
        if not changed:
            self._since_change += 1
            if self._since_change >= self._heartbeat_cycles:
                self._emit({"event": "heartbeat", "data": {"cycle": snap.cycle, "unchanged": True}})
                self._since_change = 0
                self._m_heartbeats += 1
                self._inject_meta(status)
            return
        t0_full = time.perf_counter() if self._perf_enabled else 0.0
        # Optimization: build only changed panels instead of full map
        panels_subset_map = self._build_subset(status, hashes, changed, domain=domain)
        if self._perf_enabled and self._h_diff_build is not None:
            try:
                self._h_diff_build.observe(max(0.0, time.perf_counter() - t0_full))  # type: ignore[attr-defined]
            except Exception:
                pass
        if self._structured:
            subset_map = {k: panels_subset_map[k] for k in changed if k in panels_subset_map}
            self._emit({
                "event": "panel_diff",
                "data": {
                    "cycle": snap.cycle,
                    "panels": subset_map,
                    "structured": True,
                }
            })
        else:
            updates = [
                {"key": k, **panels_subset_map[k]}
                for k in changed
                if k in panels_subset_map
            ]
            self._emit({
                "event": "panel_update",
                "data": {
                    "cycle": snap.cycle,
                    "updates": updates,
                }
            })
        # Update baseline
        for k in changed:
            self._last_hashes[k] = hashes[k]
        self._since_change = 0
        self._m_panel_updates += 1
        self._inject_meta(status)

    def teardown(self) -> None:  # pragma: no cover - trivial
        logger.debug("[sse] teardown events=%s", len(self._events))

    # --- internal helpers -------------------------------------------------
    def _emit(self, evt: dict[str, Any]) -> None:
        # Tag raw enqueue timestamp for downstream latency metrics (SSE HTTP layer)
        t_emit = time.time()
        try:
            evt['_ts_emit'] = t_emit
        except Exception:
            pass
        self._events.append(evt)
        self._m_events_total += 1
        if self._perf_enabled and self._h_emit_latency is not None:
            try:
                self._h_emit_latency.observe(
                    max(0.0, time.time() - t_emit)
                )  # type: ignore[attr-defined]
            except Exception:
                pass
        if evt.get("event") == "error":
            self._m_errors += 1

    def _build_full_snapshot(
        self,
        status: Mapping[str, Any] | None,
        hashes: dict[str, str],
        *,
        domain: SummaryDomainSnapshot | None = None,
    ) -> dict[str, Any]:
        """Build a full snapshot payload using panel registry for line parity.

        We prefer an existing domain snapshot attached to SummarySnapshot (Phase 2+),
        else we build a transient domain snapshot from raw status (cheap). This keeps
        SSE output aligned with plain/rich renderers.
        """
        # Domain snapshot reuse: domain is passed in from process(); rebuild only if absent.
        if domain is None:
            try:
                domain = build_domain_snapshot(status)
                self._domain_rebuilds += 1
            except Exception:
                domain = None
        panels_map: dict[str, Any] = {}
        built_lines: dict[str, dict[str, Any]] = {}
        try:
            if domain is not None:
                for p in build_all_panels(domain):
                    built_lines[p.key] = {"title": p.title, "lines": p.lines}
        except Exception:
            pass
        for k in PANEL_KEYS:
            meta = built_lines.get(k) or {"title": k.capitalize(), "lines": self._render_panel_lines(k, status)}
            panels_map[k] = {
                "hash": hashes.get(k),
                "title": meta["title"],
                "lines": meta["lines"],
            }
        return {"cycle": self._cycle, "panels": panels_map}

    def _build_subset(
        self,
        status: Mapping[str, Any] | None,
        hashes: dict[str, str],
        keys: list[str],
        *,
        domain: SummaryDomainSnapshot | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Build only the changed panels (subset) using provided domain snapshot when available.

        Rebuild domain only if not supplied. This reduces per-cycle overhead
        when UnifiedLoop already constructed the domain snapshot.
        """
        if domain is None:
            try:
                domain = build_domain_snapshot(status)
                self._domain_rebuilds += 1
            except Exception:
                domain = None
        panels_map: dict[str, dict[str, Any]] = {}
        if domain is not None:
            try:
                subset_objs = build_panels_subset(domain, keys)
                for p in subset_objs:
                    panels_map[p.key] = {
                        "hash": hashes.get(p.key),
                        "title": p.title,
                        "lines": p.lines,
                    }
            except Exception:
                pass
        # Fallback for any missing keys (domain build failure or provider miss)
        for k in keys:
            if k not in panels_map:
                panels_map[k] = {
                    "hash": hashes.get(k),
                    "title": k.capitalize(),
                    "lines": self._render_panel_lines(k, status),
                }
        return panels_map

    # --- metrics/meta helpers ---------------------------------------------
    def _inject_meta(self, status: Mapping[str, Any] | None) -> None:
        """Inject lightweight counters into status['panel_push_meta']['sse_publisher'].

        Safe no-op if status is not a mutable mapping (e.g., None or tuple).
        """
        try:
            if not isinstance(status, dict):  # pragma: no cover - defensive
                return
            meta_bucket = (
                status.setdefault('panel_push_meta', {})
                if isinstance(status.get('panel_push_meta'), dict)
                else status.setdefault('panel_push_meta', {})
            )
            if not isinstance(meta_bucket, dict):  # pragma: no cover - defensive
                return
            ssub = (
                meta_bucket.setdefault('sse_publisher', {})
                if isinstance(meta_bucket.get('sse_publisher'), dict)
                else meta_bucket.setdefault('sse_publisher', {})
            )
            if not isinstance(ssub, dict):  # pragma: no cover - defensive
                return
            ssub.update({
                'events_total': self._m_events_total,
                'full_snapshots': self._m_full_snapshots,
                'panel_updates': self._m_panel_updates,
                'heartbeats': self._m_heartbeats,
                'errors': self._m_errors,
                'diff_mode': self._diff_mode,
                'heartbeat_cycles': self._heartbeat_cycles,
            })
        except Exception:
            pass

    # Accessor for tests / external inspection
    def metrics_snapshot(self) -> dict[str, int]:  # pragma: no cover - thin getter
        return {
            'events_total': self._m_events_total,
            'full_snapshots': self._m_full_snapshots,
            'panel_updates': self._m_panel_updates,
            'heartbeats': self._m_heartbeats,
            'errors': self._m_errors,
        }

    @property
    def domain_rebuilds(self) -> int:  # pragma: no cover - simple accessor
        return self._domain_rebuilds

    def _render_panel_lines(self, key: str, status: Mapping[str, Any] | None) -> list[str]:
        if key == "indices" and status:
            try:
                src = status.get("indices") or []
                if isinstance(src, list):
                    return [", ".join([str(s) for s in src])[:120]]
            except Exception:
                return ["error"]
        if key == "alerts" and status:
            try:
                a = status.get("alerts")
                if isinstance(a, dict):
                    tot = a.get("total") or a.get("alerts_total")
                    return [f"total: {tot}"]
            except Exception:
                return ["error"]
        return ["…"]

    def _extract_version(self, status: Mapping[str, Any] | None) -> str | None:
        try:
            if status and isinstance(status.get("app"), Mapping):
                v = status["app"].get("version")
                if isinstance(v, (str, int, float)):
                    return str(v)
        except Exception:
            return None
        return None

__all__ = ["SSEPublisher"]
