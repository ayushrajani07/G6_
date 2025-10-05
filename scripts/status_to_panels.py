from __future__ import annotations
"""Bridge: convert runtime status JSON into per-panel JSON files for Summary View.

(DEPRECATION NOTICE) Prefer unified CLI: `python scripts/g6.py panels-bridge`.
Set G6_SUPPRESS_LEGACY_CLI=1 to silence this warning.
"""
import argparse
import json
import os
import sys
import time
import threading
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone, timedelta

#!/usr/bin/env python3
"""TOMBSTONE: legacy panels bridge.

This script was replaced by in-process panel emission inside the unified summary
loop (PanelsWriter + StreamGaterPlugin). It now exits immediately.

Invoke instead:
    python -m scripts.summary.app --refresh 1

Note: Stream gating is now unconditional; legacy enable/disable flags are ignored.

Environment:
  G6_SUPPRESS_LEGACY_CLI=1  suppresses this notification (still exits 2).
"""
from __future__ import annotations
import os, sys

def main():  # pragma: no cover - trivial stub
    if os.getenv('G6_SUPPRESS_LEGACY_CLI','').lower() not in {'1','true','yes','on'}:
        print('[REMOVED] status_to_panels.py -> use `python -m scripts.summary.app` (see DEPRECATIONS.md).', file=sys.stderr)
    sys.exit(2)

if __name__ == '__main__':
    main()
            try:
                os.makedirs(base, exist_ok=True)
            except Exception:
                pass
        def _path(self, name: str) -> str:
            return os.path.join(self.base, f"{name}.json")
        def _atomic_write(self, path: str, data: Any) -> None:
            try:
                # Reuse shared Windows-safe atomic helper
                from src.utils.output import atomic_write_json  # reuse central atomic helper if present
                # Ensure standard envelope for panels (PanelFileSink writes with keys, but fallback can accept raw data)
                payload = data
                if isinstance(data, (list, dict)) and not (isinstance(data, dict) and 'data' in data):
                    # Keep structure as-is; atomic_write_json handles dumping
                    pass
                atomic_write_json(path, payload, ensure_ascii=False, indent=2)
            except Exception:
                try:
                    tmp = path + ".tmp"
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False)
                    os.replace(tmp, path)
                except Exception:
                    # Best-effort non-atomic fallback
                    try:
                        with open(path, "w", encoding="utf-8") as f:
                            json.dump(data, f, ensure_ascii=False)
                    except Exception:
                        pass
        def panel_update(self, name: str, obj: Any, *, kind: Optional[str] = None) -> None:
            path = self._path(name)
            payload = obj
            self._atomic_write(path, payload)
        def panel_append(self, name: str, item: Any, *, cap: int = 50, kind: Optional[str] = None) -> None:
            path = self._path(name)
            existing: List[Any] = []
            try:
                if os.path.exists(path):
                    with open(path, "r", encoding="utf-8") as f:
                        obj = json.load(f)
                    if isinstance(obj, list):
                        existing = obj
                    elif isinstance(obj, dict):
                        items_obj = obj.get("items")
                        if isinstance(items_obj, list):
                            existing = items_obj
            except Exception:
                existing = []
            existing.append(item)
            if cap and cap > 0 and len(existing) > cap:
                existing = existing[-cap:]
            self._atomic_write(path, existing)
    base = os.getenv("G6_PANELS_DIR", os.path.join("data", "panels"))
    return _FallbackPanels(base)

# ---------------- Stream cadence gating ----------------
# Append to indices_stream only when the collector cadence advances
# (based on loop.cycle) or when the minute bucket changes (fallback).
_LAST_STREAM_CYCLE: Optional[int] = None
_LAST_STREAM_BUCKET: Optional[str] = None


def _parse_iso_to_utc_minute_bucket(s: Optional[str]) -> Optional[str]:
    if not s or not isinstance(s, str):
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        dt_utc = dt.astimezone(timezone.utc)
        return dt_utc.strftime("%Y-%m-%dT%H:%MZ")
    except Exception:
        return None


def _extract_cycle_and_bucket(status: Dict[str, Any], reader_cycle: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cur_cycle: Optional[int] = None
    bucket: Optional[str] = None
    try:
        cy = reader_cycle or {}
        if isinstance(cy, dict):
            c = cy.get("cycle")
            if isinstance(c, (int, float)):
                cur_cycle = int(c)
            # derive bucket from last_start if present
            b1 = _parse_iso_to_utc_minute_bucket(cy.get("last_start"))
            if b1:
                bucket = b1
        loop = status.get("loop") if isinstance(status, dict) else None
        if cur_cycle is None and isinstance(loop, dict):
            c2 = loop.get("cycle") or loop.get("number")
            if isinstance(c2, (int, float)):
                cur_cycle = int(c2)
        # prefer last_run for minute anchor
        if isinstance(loop, dict):
            b2 = _parse_iso_to_utc_minute_bucket(loop.get("last_run"))
            if b2:
                bucket = b2
        # fallback to top-level timestamp minute
        if bucket is None and isinstance(status, dict):
            bucket = _parse_iso_to_utc_minute_bucket(status.get("timestamp"))
    except Exception:
        pass
    return {"cycle": cur_cycle, "bucket": bucket}


def _get_panels_dir() -> str:
    return os.getenv("G6_PANELS_DIR", os.path.join("data", "panels"))


def _gate_state_path() -> str:
    return os.path.join(_get_panels_dir(), ".indices_stream_state.json")


def _load_gate_state() -> None:
    global _LAST_STREAM_CYCLE, _LAST_STREAM_BUCKET
    if _LAST_STREAM_CYCLE is not None or _LAST_STREAM_BUCKET is not None:
        return
    try:
        p = _gate_state_path()
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                obj = json.load(f)
            if isinstance(obj, dict):
                lc = obj.get("last_cycle")
                lb = obj.get("last_bucket")
                if isinstance(lc, (int, float)):
                    _LAST_STREAM_CYCLE = int(lc)
                if isinstance(lb, str):
                    _LAST_STREAM_BUCKET = lb
    except Exception:
        pass


def _save_gate_state(cycle: Optional[int], bucket: Optional[str]) -> None:
    try:
        st: Dict[str, object] = {}
        if isinstance(cycle, int):
            st["last_cycle"] = cycle
        if isinstance(bucket, str):
            st["last_bucket"] = bucket
        if st:
            # ensure panels dir exists; best-effort
            try:
                os.makedirs(_get_panels_dir(), exist_ok=True)
            except Exception:
                pass
            with open(_gate_state_path(), "w", encoding="utf-8") as f:
                json.dump(st, f)
    except Exception:
        pass

_DEPRECATION_WARNED = False

def _maybe_warn_deprecated():  # pragma: no cover - side-effect path
    """Immediate stub-style deprecation logic.

    Behavior:
      - Warn once unless suppressed.
      - Block execution by default (exit code 3) unless G6_ALLOW_LEGACY_PANELS_BRIDGE=1.
      - No phased automation; unified path considered production-ready.
    """
    global _DEPRECATION_WARNED
    if _DEPRECATION_WARNED:
        return
    suppress_all = os.getenv("G6_SUPPRESS_DEPRECATIONS", "0").lower() in {"1","true","yes","on"}
    suppress_bridge = os.getenv("G6_PANELS_BRIDGE_SUPPRESS", "0").lower() in {"1","true","yes","on"}
    allow = os.getenv("G6_ALLOW_LEGACY_PANELS_BRIDGE", "0").lower() in {"1","true","yes","on"}
    if not (suppress_all or suppress_bridge):
        try:
            print("[DEPRECATION] status_to_panels.py blocked by default; use unified summary PanelsWriter (scripts/summary/app.py).", flush=True)
        except Exception:
            pass
    _DEPRECATION_WARNED = True
    if not allow:
        try:
            print("Set G6_ALLOW_LEGACY_PANELS_BRIDGE=1 to temporarily run this legacy bridge (will be removed soon).", flush=True)
        except Exception:
            pass
        raise SystemExit(3)


def publish_once(router, status_file: str) -> None:
    global _LAST_STREAM_CYCLE, _LAST_STREAM_BUCKET
    reader = get_status_reader(status_file)
    status = reader.get_raw_status()
    # Write all panels within a single transaction to avoid partial snapshots
    try:
        begin_txn = getattr(router, "begin_panels_txn", None)
    except Exception:
        begin_txn = None
    if begin_txn:
        with begin_txn():
            # Build all standard panels in one shot
            panels = build_panels(reader, status)
            for name, payload in panels.items():
                router.panel_update(name, payload, kind=name if isinstance(name, str) else None)
            # Indices stream: append items only when collector cadence advances.
            gate_mode = (os.getenv("G6_STREAM_GATE_MODE", "auto").strip().lower() or "auto")
            _load_gate_state()
            cycle_info = _extract_cycle_and_bucket(status, reader_cycle=reader.get_cycle_data())
            cur_cycle = cycle_info.get("cycle")
            bucket = cycle_info.get("bucket")
            should_append = True
            if gate_mode in ("auto", "cycle") and isinstance(cur_cycle, int):
                should_append = (_LAST_STREAM_CYCLE != cur_cycle)
            elif gate_mode in ("auto", "minute", "bucket") and isinstance(bucket, str):
                should_append = (_LAST_STREAM_BUCKET != bucket)
            if should_append:
                for item in build_indices_stream_items(reader, status):
                    try:
                        # Add front-end friendly date-less time
                        raw_ts = item.get("time") or item.get("ts") or item.get("timestamp")
                        hms = _to_ist_hms_30s(raw_ts)
                        if isinstance(hms, str):
                            item = {**item, "time_hms": hms}
                    except Exception:
                        pass
                    router.panel_append("indices_stream", item, cap=50, kind="stream")
                if isinstance(cur_cycle, int):
                    _LAST_STREAM_CYCLE = cur_cycle
                if isinstance(bucket, str):
                    _LAST_STREAM_BUCKET = bucket
                _save_gate_state(_LAST_STREAM_CYCLE, _LAST_STREAM_BUCKET)
            # Bridge heartbeat: emit/update minimal system.bridge metrics for freshness checks
            try:
                import datetime as _dt
                _now_iso = _dt.datetime.now(tz=_dt.timezone.utc).isoformat().replace("+00:00", "Z")
                hb = {
                    "bridge": {
                        "last_publish": {"metric": "last_publish", "value": _now_iso, "status": "OK"},
                    }
                }
                # Publish lightweight hint under system panel without disturbing other keys
                router.panel_update("system", hb, kind="system")
            except Exception:
                pass
    else:
        # Non-transactional path: still use factory to keep logic centralized
        panels = build_panels(reader, status)
        for name, payload in panels.items():
            router.panel_update(name, payload, kind=name if isinstance(name, str) else None)
        # Apply same gating in non-transactional path
        gate_mode = (os.getenv("G6_STREAM_GATE_MODE", "auto").strip().lower() or "auto")
        _load_gate_state()
        cycle_info = _extract_cycle_and_bucket(status, reader_cycle=reader.get_cycle_data())
        cur_cycle = cycle_info.get("cycle")
        bucket = cycle_info.get("bucket")
        should_append = True
        if gate_mode in ("auto", "cycle") and isinstance(cur_cycle, int):
            should_append = (_LAST_STREAM_CYCLE != cur_cycle)
        elif gate_mode in ("auto", "minute", "bucket") and isinstance(bucket, str):
            should_append = (_LAST_STREAM_BUCKET != bucket)
        if should_append:
            for item in build_indices_stream_items(reader, status):
                try:
                    raw_ts = item.get("time") or item.get("ts") or item.get("timestamp")
                    hms = _to_ist_hms_30s(raw_ts)
                    if isinstance(hms, str):
                        item = {**item, "time_hms": hms}
                except Exception:
                    pass
                router.panel_append("indices_stream", item, cap=50, kind="stream")
            if isinstance(cur_cycle, int):
                _LAST_STREAM_CYCLE = cur_cycle
            if isinstance(bucket, str):
                _LAST_STREAM_BUCKET = bucket
            _save_gate_state(_LAST_STREAM_CYCLE, _LAST_STREAM_BUCKET)
        # Bridge heartbeat in non-txn path as well
        try:
            import datetime as _dt
            _now_iso = _dt.datetime.now(tz=_dt.timezone.utc).isoformat().replace("+00:00", "Z")
            hb = {
                "bridge": {
                    "last_publish": {"metric": "last_publish", "value": _now_iso, "status": "OK"},
                }
            }
            router.panel_update("system", hb, kind="system")
        except Exception:
            pass


# Factory-only publish path retained; legacy helpers removed


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Publish panels from a status JSON file")
    parser.add_argument("--status-file", default=os.getenv("G6_STATUS_FILE", os.path.join("data", "runtime_status.json")))
    parser.add_argument("--refresh", type=float, default=1.0, help="Polling interval seconds when not --once")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    args = parser.parse_args(argv)

    _maybe_warn_deprecated()

    router = _ensure_panels_sink_active()

    # Ensure panels dir exists early
    try:
        base = os.getenv("G6_PANELS_DIR", os.path.join("data", "panels"))
        os.makedirs(base, exist_ok=True)
    except Exception:
        pass

    try:
        if args.once:
            try:
                publish_once(router, args.status_file)
                return 0
            except Exception as e:
                try:
                    print(f"status_to_panels publish_once error: {e}", flush=True)
                except Exception:
                    pass
                return 2
        last_mtime = 0.0
        while True:
            try:
                st = os.stat(args.status_file)
                if st.st_mtime > last_mtime:
                    try:
                        publish_once(router, args.status_file)
                    except Exception as e:
                        try:
                            print(f"status_to_panels publish error: {e}", flush=True)
                        except Exception:
                            pass
                        # Backoff a bit on error and continue
                        try:
                            backoff_ms = float(os.getenv("G6_PANELS_LOOP_BACKOFF_MS", "300") or "300")
                        except Exception:
                            backoff_ms = 300.0
                        try:
                            print(f"status_to_panels: retrying in {int(backoff_ms)} ms", flush=True)
                        except Exception:
                            pass
                        # Publish a small system panel hint for UI, include timestamp for recency checks
                        try:
                            import datetime as _dt
                            _now_iso = _dt.datetime.now(tz=_dt.timezone.utc).isoformat().replace("+00:00", "Z")
                            router.panel_update(
                                "system",
                                {
                                    "bridge": {
                                        "metric": "backoff_ms",
                                        "value": int(backoff_ms),
                                        "status": "WARN",
                                        "time": _now_iso,
                                    }
                                },
                                kind="system",
                            )
                        except Exception:
                            pass
                        time.sleep(max(0.05, backoff_ms / 1000.0))
                    last_mtime = st.st_mtime
            except FileNotFoundError:
                # No status file yet; just sleep and retry
                pass
            time.sleep(max(0.2, float(args.refresh)))
    except KeyboardInterrupt:
        return 0
    except Exception as e:
        try:
            print(f"status_to_panels error: {e}", flush=True)
        except Exception:
            pass
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
