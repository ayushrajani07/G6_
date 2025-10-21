"""Panel Diff Emitter (Phase 5.4 scaffold)

Generates JSON diff artifacts between successive status snapshots to reduce
I/O volume and latency for panel consumers.

Activation:
  G6_PANEL_DIFFS=1 enables diff emission.
  G6_PANEL_DIFF_FULL_INTERVAL (int, cycles) forces a full snapshot every N diffs (default 30).
Output:
  Writes *.diff.json and periodic *.full.json siblings next to runtime status file.

Planned Metrics (not yet wired):
  g6_panel_diff_bytes_total{type=diff|full}
  g6_panel_diff_emit_seconds

Diff Strategy (initial simplistic placeholder):
  - Top-level shallow key comparison; for dict values produce added/removed/changed lists.
  - For production, consider structural hashes and selective deep diffs for large sections.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

# Freeze gating: if platform egress (non-Prometheus) is frozen, we no-op.
_EGRESS_FROZEN = os.getenv('G6_EGRESS_FROZEN','').lower() in {'1','true','yes','on'}

try:  # Lazy import to avoid startup impact when SSE not enabled
    from src.events.event_bus import get_event_bus  # type: ignore
except Exception:  # pragma: no cover - fallback when module unavailable
    get_event_bus = None  # type: ignore

@dataclass
class _DiffState:
    last_snapshot: dict[str, Any]
    status_path: str
    counter: int = 0

_state: _DiffState | None = None
_BUS = None


def _copy_jsonable(obj: Any) -> Any:
    # Prefer deepcopy to avoid serialization overhead; fallback to json round-trip if needed.
    try:
        import copy as _copy
        return _copy.deepcopy(obj)
    except Exception:
        try:
            return json.loads(json.dumps(obj))
        except Exception:
            return obj


def _publish_event(event_type: str, payload: dict[str, Any], *, coalesce_key: str | None = None) -> None:
    global _BUS
    if get_event_bus is None:
        return
    if _BUS is None or _BUS is False:  # type: ignore[truthy-bool]
        try:
            _BUS = get_event_bus()
        except Exception:
            _BUS = False  # type: ignore[assignment]
            return
    if _BUS is False:
        return
    try:
        _BUS.publish(event_type, payload, coalesce_key=coalesce_key)
    except Exception:
        pass

def emit_panel_artifacts(status: dict[str, Any], *, status_path: str) -> None:
    """Emit panel diff & periodic full snapshots with optional recursive depth.

    Environment Variables:
      G6_PANEL_DIFFS=1|true|on : enable logic
      G6_PANEL_DIFF_FULL_INTERVAL=int : every N diffs persist a full snapshot
      G6_PANEL_DIFF_NEST_DEPTH=int : recursive dict depth (default 1 - existing behavior)
    """
    if _EGRESS_FROZEN:
        return
    if os.environ.get('G6_PANEL_DIFFS','').lower() not in ('1','true','yes','on'):
        return
    import time as _t
    start_time = _t.time()
    global _state
    # Config
    try:
        full_interval = int(os.environ.get('G6_PANEL_DIFF_FULL_INTERVAL','30'))
    except Exception:
        full_interval = 30
    try:
        nest_depth = int(os.environ.get('G6_PANEL_DIFF_NEST_DEPTH','1'))
    except Exception:
        nest_depth = 1
    if nest_depth < 0:
        nest_depth = 0
    try:
        max_keys = int(os.environ.get('G6_PANEL_DIFF_MAX_KEYS','0'))
    except Exception:
        max_keys = 0
    if max_keys < 0:
        max_keys = 0
    base_dir = os.path.dirname(status_path)
    base_name = os.path.splitext(os.path.basename(status_path))[0]

    # Initial full snapshot bootstrap
    # Reset state if first invocation or status path changed (ensures per-file isolation across tests/processes).
    if _state is None or _state.status_path != status_path:
        _state = _DiffState(last_snapshot=status, status_path=status_path, counter=0)
        try:
            full_payload = _copy_jsonable(status)
            with open(os.path.join(base_dir, base_name + '.full.json'), 'w', encoding='utf-8') as f:
                json.dump(full_payload, f)
            try:
                from src.metrics import get_metrics  # facade import
                m = get_metrics()
                # Dynamic metric families: guarded by hasattr, add type ignores for static checker
                if hasattr(m, 'panel_diff_writes'):
                    m.panel_diff_writes.labels(type='full').inc()  # type: ignore[attr-defined]
                if hasattr(m, 'panel_diff_last_full_unixtime'):
                    m.panel_diff_last_full_unixtime.set(_t.time())  # type: ignore[attr-defined]
                size = len(json.dumps(status))
                if hasattr(m, 'panel_diff_bytes_last'):
                    m.panel_diff_bytes_last.labels(type='full').set(size)  # type: ignore[attr-defined]
                if hasattr(m, 'panel_diff_bytes_total'):
                    try:
                        m.panel_diff_bytes_total.labels(type='full').inc(size)  # type: ignore[attr-defined]
                    except Exception:
                        pass
            except Exception:
                pass
            _publish_event(
                'panel_full',
                {
                    'status': full_payload,
                    'status_path': status_path,
                    'counter': _state.counter,
                    'bootstrap': True,
                },
                coalesce_key='panel_full',
            )
        except Exception:
            pass
        # Observe latency just for completeness of first full
        try:
            from src.metrics import get_metrics  # facade import
            m = get_metrics()
            if hasattr(m, 'panel_diff_emit_seconds'):
                m.panel_diff_emit_seconds.observe(max(_t.time()-start_time,0.0))  # type: ignore[attr-defined]
        except Exception:
            pass
        return

    prev = _state.last_snapshot

    truncated = False
    # Count only top-level diff entries (added + removed + changed + nested keys)
    def _diff_dict(a: dict[str, Any], b: dict[str, Any], depth: int, *, _root: bool = True) -> dict[str, Any]:
        nonlocal truncated
        out: dict[str, Any] = {"added": {}, "removed": [], "changed": {}, "nested": {}}
        key_budget = 0
        # Helper to check & set truncation
        def _maybe_truncate() -> bool:
            nonlocal key_budget, truncated
            if truncated:
                return True
            if max_keys and key_budget >= max_keys:
                truncated = True
                return True
            return False
        for k, v in b.items():
            if _maybe_truncate():
                break
            if k not in a:
                out["added"][k] = v
                key_budget += 1
            else:
                if a[k] != v:
                    if depth > 0 and isinstance(a[k], dict) and isinstance(v, dict):
                        # Add nested key slot first
                        nested_diff = _diff_dict(a[k], v, depth-1, _root=False)
                        if nested_diff.get("added") or nested_diff.get("removed") or nested_diff.get("changed") or nested_diff.get("nested"):
                            out["nested"][k] = nested_diff
                            key_budget += 1
                    else:
                        out["changed"][k] = {"old": a[k], "new": v}
                        key_budget += 1
        if not truncated:
            for k in a.keys():
                if _maybe_truncate():
                    break
                if k not in b:
                    out["removed"].append(k)
                    key_budget += 1
        # Prune empty nested for cleanliness
        if not out["nested"]:
            out.pop("nested")
        return out

    diff = _diff_dict(prev, status, nest_depth)
    if truncated:
        diff["_truncated"] = True
        diff.setdefault("truncated_reasons", []).append("max_keys")
        try:
            from src.metrics import get_metrics  # facade import
            m = get_metrics()
            if hasattr(m, 'panel_diff_truncated'):
                m.panel_diff_truncated.labels(reason='max_keys').inc()  # type: ignore[attr-defined]
        except Exception:
            pass
    _state.last_snapshot = status
    _state.counter += 1
    diff_path = os.path.join(base_dir, base_name + f'.{_state.counter}.diff.json')
    try:
        diff_payload = _copy_jsonable(diff)
        with open(diff_path, 'w', encoding='utf-8') as f:
            json.dump(diff_payload, f)
        try:
            from src.metrics import get_metrics  # facade import
            m = get_metrics()
            if hasattr(m, 'panel_diff_writes'):
                m.panel_diff_writes.labels(type='diff').inc()  # type: ignore[attr-defined]
            size = len(json.dumps(diff))
            if hasattr(m, 'panel_diff_bytes_last'):
                m.panel_diff_bytes_last.labels(type='diff').set(size)  # type: ignore[attr-defined]
            if hasattr(m, 'panel_diff_bytes_total'):
                try:
                    m.panel_diff_bytes_total.labels(type='diff').inc(size)  # type: ignore[attr-defined]
                except Exception:
                    pass
        except Exception:
            pass
        _publish_event(
            'panel_diff',
            {
                'diff': diff_payload,
                'status_path': status_path,
                'counter': _state.counter,
                'truncated': truncated,
            },
        )
        # Phase 4: snapshot guard enforcement (best-effort; only after emitting a diff)
        try:
            if _BUS is not None and _BUS is not False and hasattr(_BUS, 'enforce_snapshot_guard'):
                _BUS.enforce_snapshot_guard()  # type: ignore[attr-defined]
        except Exception:
            pass
    except Exception:
        pass
    # Periodic full snapshot
    if full_interval > 0 and _state.counter % full_interval == 0:
        full_path = os.path.join(base_dir, base_name + f'.{_state.counter}.full.json')
        try:
            full_payload = _copy_jsonable(status)
            with open(full_path, 'w', encoding='utf-8') as f:
                json.dump(full_payload, f)
            try:
                from src.metrics import get_metrics  # facade import
                m = get_metrics()
                if hasattr(m, 'panel_diff_writes'):
                    m.panel_diff_writes.labels(type='full').inc()  # type: ignore[attr-defined]
                if hasattr(m, 'panel_diff_last_full_unixtime'):
                    m.panel_diff_last_full_unixtime.set(_t.time())  # type: ignore[attr-defined]
                size = len(json.dumps(status))
                if hasattr(m, 'panel_diff_bytes_last'):
                    m.panel_diff_bytes_last.labels(type='full').set(size)  # type: ignore[attr-defined]
                if hasattr(m, 'panel_diff_bytes_total'):
                    try:
                        m.panel_diff_bytes_total.labels(type='full').inc(size)  # type: ignore[attr-defined]
                    except Exception:
                        pass
            except Exception:
                pass
            _publish_event(
                'panel_full',
                {
                    'status': full_payload,
                    'status_path': status_path,
                    'counter': _state.counter,
                    'bootstrap': False,
                },
                coalesce_key='panel_full',
            )
            # Guard after a scheduled full (could reset gap logic) but still re-check others
            try:
                if _BUS is not None and _BUS is not False and hasattr(_BUS, 'enforce_snapshot_guard'):
                    _BUS.enforce_snapshot_guard()  # type: ignore[attr-defined]
            except Exception:
                pass
        except Exception:
            pass
    # Observe latency
    try:
        from src.metrics import get_metrics  # facade import
        m = get_metrics()
        if hasattr(m, 'panel_diff_emit_seconds'):
            m.panel_diff_emit_seconds.observe(max(_t.time()-start_time,0.0))  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover - observational
        pass

__all__ = ["emit_panel_artifacts"]
