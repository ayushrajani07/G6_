#!/usr/bin/env python3
"""
Minimal optional HTTP server exposing health endpoints using stdlib only.

Endpoints:
 - /health            -> overall service health
 - /health/liveness   -> always 200 if process alive
 - /health/readiness  -> 200 if ready, 503 otherwise (based on provided callable)
 - /health/components -> all component statuses
 - /health/component/<name> -> specific component

This server is intended to be run in a background thread when enabled. It 
keeps a shared state dictionary provided at construction time.
"""
from __future__ import annotations

import json
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, cast

from .models import HealthLevel, HealthState


class _HealthStateStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._overall_level: HealthLevel = HealthLevel.UNKNOWN
        self._overall_state: str = HealthState.UNKNOWN.value
        self._components: dict[str, dict[str, str | int]] = {}

    def get_snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "status": self._overall_state,
                "level": int(self._overall_level),
                "components": {k: dict(v) for k, v in self._components.items()},
            }

    def set_overall(self, level: HealthLevel, state: str | HealthState) -> None:
        s = state.value if isinstance(state, HealthState) else str(state)
        with self._lock:
            self._overall_level = level
            self._overall_state = s

    def set_component(self, name: str, level: HealthLevel, state: str | HealthState) -> None:
        s = state.value if isinstance(state, HealthState) else str(state)
        with self._lock:
            self._components[name] = {"level": int(level), "state": s}


class _Handler(BaseHTTPRequestHandler):
    def _get_store(self) -> _HealthStateStore | None:
        store = getattr(self.server, "_g6_store", None)
        return store if isinstance(store, _HealthStateStore) else None

    def _get_ready_check(self) -> Callable[[], bool] | None:
        rc = getattr(self.server, "_g6_ready_check", None)
        if callable(rc):
            return cast(Callable[[], bool], rc)
        return None

    def _send_json(self, code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A003 - BaseHTTPRequestHandler API
        # Keep quiet by default to avoid noisy logs
        return

    def do_GET(self) -> None:  # noqa: N802 - stdlib API
        path = self.path or "/health"
        if path == "/health" or path == "/health/":
            store = self._get_store()
            snap = store.get_snapshot() if store is not None else {
                "status": HealthState.UNKNOWN.value,
                "level": int(HealthLevel.UNKNOWN),
                "components": {},
            }
            raw_level = snap.get("level", int(HealthLevel.UNKNOWN))
            lvl: int
            if isinstance(raw_level, int):
                lvl = raw_level
            else:
                try:
                    lvl = int(raw_level)
                except Exception:
                    lvl = int(HealthLevel.UNKNOWN)
            code = 200 if lvl <= int(HealthLevel.WARNING) else 503
            self._send_json(code, snap)
            return

        if path.startswith("/health/liveness"):
            self._send_json(200, {"status": "alive"})
            return

        if path.startswith("/health/readiness"):
            ok = True
            rc = self._get_ready_check()
            if rc is not None:
                try:
                    ok = bool(rc())
                except Exception:
                    ok = False
            code = 200 if ok else 503
            self._send_json(code, {"ready": ok})
            return

        if path.startswith("/health/components"):
            store = self._get_store()
            snap = store.get_snapshot() if store is not None else {"components": {}}
            comps_raw = snap.get("components", {})
            components_map: dict[str, Any] = comps_raw if isinstance(comps_raw, dict) else {}
            self._send_json(200, {"components": components_map})
            return

        if path.startswith("/health/component/"):
            name = path.split("/health/component/")[-1]
            store = self._get_store()
            snap = store.get_snapshot() if store is not None else {"components": {}}
            comps_raw = snap.get("components", {})
            comps_map: dict[str, Any] = comps_raw if isinstance(comps_raw, dict) else {}
            comp_raw = comps_map.get(name)
            comp: dict[str, Any] | None = comp_raw if isinstance(comp_raw, dict) else None
            if comp is None:
                self._send_json(404, {"error": "component not found"})
                return
            payload: dict[str, Any] = {"name": name}
            lvl_val = comp.get("level")
            if isinstance(lvl_val, int):
                payload["level"] = lvl_val
            elif lvl_val is not None:
                try:
                    payload["level"] = int(lvl_val)  # may raise, silently skipped
                except Exception:
                    pass
            state_val = comp.get("state")
            if isinstance(state_val, str):
                payload["state"] = state_val
            elif state_val is not None:
                payload["state"] = str(state_val)
            self._send_json(200, payload)
            return

        self._send_json(404, {"error": "not found"})


class HealthServer:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8099,
        ready_check: Callable[[], bool] | None = None,
    ) -> None:
        self._store = _HealthStateStore()
        self._server = HTTPServer((host, port), _Handler)
        self._server._g6_store = self._store
        self._server._g6_ready_check = ready_check
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._server.serve_forever, name="HealthServer", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Shutdown server and fully close underlying socket.

        Idempotent: safe to call multiple times. Ensures sockets are closed to
        avoid ResourceWarning noise in tests.
        """
        try:
            self._server.shutdown()
        except Exception:
            pass
        try:
            self._server.server_close()
        except Exception:
            pass

    # Convenience context manager usage
    def __enter__(self):  # pragma: no cover - syntactic sugar
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb):  # pragma: no cover - syntactic sugar
        self.stop()
        return False

    def set_overall(self, level: HealthLevel, state: str | HealthState) -> None:
        self._store.set_overall(level, state)

    def set_component(self, name: str, level: HealthLevel, state: str | HealthState) -> None:
        self._store.set_component(name, level, state)


__all__ = ["HealthServer"]
