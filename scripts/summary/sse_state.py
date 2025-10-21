"""Thread-safe panel state & diff application utilities.

Extracted from inline logic in app.py to reduce complexity and centralize
SSE panel_full / panel_diff application semantics.

Design goals:
- Provide a PanelStateStore with generation and counters
- Use existing merge_panel_diff helper from src.web.dashboard.diff_merge
- Avoid any heavy imports at module import time (prometheus optional)
"""
from __future__ import annotations

import copy
import logging
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

try:  # optional import for merge helper
    from src.web.dashboard.diff_merge import merge_panel_diff  # type: ignore
except Exception:  # pragma: no cover
    def merge_panel_diff(base: dict[str, Any], delta: dict[str, Any]) -> dict[str, Any]:  # type: ignore
        # Fallback simplistic recursive merge (no remove sentinel handling)
        out = dict(base or {})
        for k, v in (delta or {}).items():
            if v is None:
                out.pop(k, None)
            elif isinstance(v, dict) and isinstance(out.get(k), dict):
                out[k] = merge_panel_diff(out[k], v)
            else:
                out[k] = v
        return out


class PanelStateStore:
    """Thread-safe store for last applied status/panels and diff counters.

    This holds the composite status JSON (server's panel_full baseline + applied diffs)
    rather than per-panel maps to closely match existing app.py behavior.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._status: dict[str, Any] | None = None
        self._server_generation: int | None = None  # generation from server events
        self._ui_generation: int = 0  # local increment each successful apply
        self._need_full: bool = True
        self._need_full_reasons: list[str] = []
        self._counters: dict[str, int] = {
            'panel_full': 0,
            'panel_diff_applied': 0,
            'panel_diff_dropped': 0,
        }
        # Severity & follow-up state (populated by plugin)
        self._severity_counts: dict[str, int] = {}
        self._severity_state: dict[str, dict[str, Any]] = {}
        self._followup_alerts: list[dict[str, Any]] = []  # newest first
        # Heartbeat / timing
        self._last_event_ts: float | None = None
        self._last_panel_full_ts: float | None = None
        self._last_panel_diff_ts: float | None = None

    # -------------------- properties --------------------
    def snapshot(
        self,
    ) -> tuple[
        dict[str, Any] | None,
        int | None,
        int,
        bool,
        dict[str, int],
        dict[str, int],
        dict[str, dict[str, Any]],
        list[dict[str, Any]],
    ]:
        """Return a copy of core state for safe external use.

        Returns:
            status, server_generation, ui_generation, need_full,
            counters, severity_counts, severity_state, followup_alerts
        """
        with self._lock:
            st = copy.deepcopy(self._status) if isinstance(self._status, dict) else None
            return (
                st,
                self._server_generation,
                self._ui_generation,
                self._need_full,
                dict(self._counters),
                dict(self._severity_counts),
                copy.deepcopy(self._severity_state),
                list(self._followup_alerts),
            )

    # -------------------- mutation methods --------------------
    def apply_panel_full(self, status_obj: dict[str, Any], server_generation: int | None) -> None:
        with self._lock:
            self._status = copy.deepcopy(status_obj) if isinstance(status_obj, dict) else {}
            self._server_generation = server_generation if isinstance(server_generation, int) else (
                (self._server_generation or 0) + 1
            )
            self._ui_generation += 1
            self._need_full = False
            self._counters['panel_full'] += 1
            now = time.time()
            self._last_event_ts = now
            self._last_panel_full_ts = now

    def apply_panel_diff(self, diff_obj: dict[str, Any], server_generation: int | None) -> bool:
        """Attempt to merge a diff; returns True if applied, False if dropped."""
        with self._lock:
            if self._status is None:
                self._counters['panel_diff_dropped'] += 1
                return False
            # Generation checking: if server_generation provided and mismatched -> drop
            if server_generation is not None and self._server_generation is not None:
                if server_generation != self._server_generation:
                    self._counters['panel_diff_dropped'] += 1
                    # Request a full on next cycle
                    self._need_full = True
                    return False
            # Determine merge strategy: if diff_obj looks like a panel event (panel/op keys)
            # delegate to merge_panel_diff; else perform a shallow recursive key merge treating
            # diff_obj as a root-level status patch (legacy summary diff semantics).
            merged: dict[str, Any]
            if isinstance(diff_obj, dict) and {'panel','op','data'} <= set(diff_obj.keys()):
                try:
                    merged = merge_panel_diff(self._status, diff_obj)
                except Exception as e:  # pragma: no cover
                    logger.warning("Failed to merge panel diff: %s", e)
                    self._counters['panel_diff_dropped'] += 1
                    return False
            else:
                # Fallback root-level recursive merge mirroring earlier inline logic:
                def _recur(base: dict[str, Any], delta: dict[str, Any]) -> dict[str, Any]:
                    out = dict(base)
                    for k, v in delta.items():
                        if v is None:
                            out.pop(k, None)
                        elif isinstance(v, dict) and isinstance(out.get(k), dict):
                            out[k] = _recur(out[k], v)  # type: ignore[index]
                        else:
                            out[k] = v
                    return out
                try:
                    merged = _recur(self._status, diff_obj)
                except Exception as e:  # pragma: no cover
                    logger.warning("Failed to merge root-level diff: %s", e)
                    self._counters['panel_diff_dropped'] += 1
                    return False
            self._status = merged
            # Update generation if server supplied new one
            if server_generation is not None:
                self._server_generation = server_generation
            self._ui_generation += 1
            self._counters['panel_diff_applied'] += 1
            now = time.time()
            self._last_event_ts = now
            self._last_panel_diff_ts = now
            return True

    def mark_need_full(self) -> None:
        with self._lock:
            self._need_full = True

    # -------------------- external request full --------------------
    def request_full(
        self,
        reason: str | None = None,
        *,
        append: bool = True,
        dedupe: bool = True,
        limit: int = 10,
    ) -> None:
        """Public API to signal that a baseline full snapshot is required.

        Args:
            reason: Optional human-readable reason (e.g., 'generation_mismatch').
            append: When True, keep prior reasons (bounded); when False, replace list with single reason.
            dedupe: Avoid adding duplicate sequential reason entries.
            limit: Max number of stored reasons (oldest dropped when exceeded).
        """
        with self._lock:
            self._need_full = True
            if reason:
                if not append:
                    self._need_full_reasons = [reason]
                else:
                    if dedupe and self._need_full_reasons and self._need_full_reasons[-1] == reason:
                        return
                    self._need_full_reasons.append(reason)
                    if len(self._need_full_reasons) > limit:
                        self._need_full_reasons = self._need_full_reasons[-limit:]

    def pop_need_full_reasons(self) -> list[str]:
        """Return current reasons list (copy) without clearing (UI may clear separately)."""
        with self._lock:
            return list(self._need_full_reasons)

    # -------------------- severity / followups --------------------
    def update_severity_counts(self, counts: dict[str, Any]) -> None:
        with self._lock:
            try:
                self._severity_counts = {k: int(counts.get(k, 0)) for k in ('info','warn','critical')}
            except Exception:
                # fallback: retain only numeric keys cast to int
                tmp: dict[str, int] = {}
                for k, v in counts.items():
                    if isinstance(v, (int, float)):
                        tmp[k] = int(v)
                self._severity_counts = tmp
            self._ui_generation += 1
            self._last_event_ts = time.time()

    def update_severity_state(self, alert_type: str, payload: dict[str, Any]) -> None:
        with self._lock:
            state_entry: dict[str, Any] = {
                'active': payload.get('active'),
                'previous_active': payload.get('previous_active'),
                'last_change_cycle': payload.get('last_change_cycle'),
                'resolved': payload.get('resolved'),
                'resolved_count': payload.get('resolved_count'),
                'reasons': list(payload.get('reasons') or []),
                'alert': (
                    copy.deepcopy(payload.get('alert'))
                    if isinstance(payload.get('alert'), dict)
                    else payload.get('alert')
                ),
            }
            self._severity_state[alert_type] = state_entry
            self._ui_generation += 1
            self._last_event_ts = time.time()

    def add_followup_alert(self, entry: dict[str, Any], maxlen: int = 50) -> None:
        with self._lock:
            self._followup_alerts.insert(0, entry)
            if len(self._followup_alerts) > maxlen:
                del self._followup_alerts[maxlen:]
            self._ui_generation += 1
            self._last_event_ts = time.time()

    # -------------------- heartbeat helpers --------------------
    def heartbeat(self, warn_after: float = 10.0, stale_after: float = 30.0) -> dict[str, Any]:
        """Return heartbeat / freshness metadata.

        Args:
            warn_after: seconds since last event after which status is 'warn'.
            stale_after: seconds since last event after which status is 'stale'.
        """
        with self._lock:
            now = time.time()
            last_evt = self._last_event_ts
            stale_seconds: float | None
            if last_evt is None:
                stale_seconds = None
                health = 'init'
            else:
                stale_seconds = now - last_evt
                if stale_seconds >= stale_after:
                    health = 'stale'
                elif stale_seconds >= warn_after:
                    health = 'warn'
                else:
                    health = 'ok'
            return {
                'last_event_epoch': last_evt,
                'last_panel_full_epoch': self._last_panel_full_ts,
                'last_panel_diff_epoch': self._last_panel_diff_ts,
                'stale_seconds': stale_seconds,
                'health': health,
                'warn_after': warn_after,
                'stale_after': stale_after,
            }

__all__ = ["PanelStateStore"]
