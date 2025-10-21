"""Minimal DossierWriter plugin.

Purpose: Periodically write a unified model snapshot JSON file using
`assemble_model_snapshot` (status + optional panels). Activates automatically when a dossier path env var is provided.

Env Variables:
    G6_SUMMARY_DOSSIER_PATH            = output file path (required to enable plugin)
    G6_SUMMARY_DOSSIER_INTERVAL_SEC    = min seconds between writes (default 5)

Behavior:
    - On each process() call (each loop cycle), checks elapsed since last write.
    - If interval elapsed, assembles snapshot and atomically writes JSON.
    - Best-effort; errors are logged and swallowed (won't break loop).
    - Writes via atomic replace if possible; fallback to simple write on failure.

Out of Scope (later phases): SSE merge, derivations registry, compression, diffing.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from collections.abc import Mapping
from typing import Any

from .base import OutputPlugin, SummarySnapshot

TRUE_SET = {"1","true","yes","on"}

def _env_true(name: str) -> bool:
    v = os.getenv(name) or ""
    return v.strip().lower() in TRUE_SET

class DossierWriter(OutputPlugin):
    name = "dossier_writer"

    def __init__(self) -> None:
        self._path: str | None = None
        self._interval: float = 5.0
        self._last_write: float = 0.0
        self._panels_dir: str | None = None
        self._enabled: bool = False

    def setup(self, context: Mapping[str, Any]) -> None:  # pragma: no cover - side effects trivial
        self._path = os.getenv("G6_SUMMARY_DOSSIER_PATH")
        if not self._path:
            return
        try:
            self._interval = float(os.getenv("G6_SUMMARY_DOSSIER_INTERVAL_SEC", "5") or 5)
        except Exception:
            self._interval = 5.0
        self._interval = max(0.5, self._interval)
        self._panels_dir = os.getenv("G6_PANELS_DIR")
        self._enabled = True

    def process(self, snap: SummarySnapshot) -> None:  # pragma: no cover - IO + defensive
        if not self._enabled or not self._path:
            return
        now = time.time()
        if now - self._last_write < self._interval:
            return
        self._last_write = now
        # Prefer model if dual emission provided it; else assemble new one.
        # TODO(dossier:rolling-stats): Inject rolling latency / error streak stats once model exposes them.
        model_snap = getattr(snap, 'model', None)
        diag_warnings: list[str] = []
        if model_snap is None:
            try:
                from src.summary.unified.model import assemble_model_snapshot
                runtime_status = (
                    dict(snap.status) if isinstance(snap.status, Mapping) else None
                )
                model_snap, diag = assemble_model_snapshot(
                    runtime_status=runtime_status,
                    panels_dir=self._panels_dir,
                    include_panels=True,
                )
                diag_warnings = list(diag.get('warnings', [])) if isinstance(diag.get('warnings'), list) else []
            except Exception:
                model_snap = None
        if model_snap is not None:
            try:
                payload = model_snap.to_dict()
                payload["dossier_meta"] = {
                    "cycle": snap.cycle,
                    "written_ts": now,
                    "interval": self._interval,
                    "warnings": diag_warnings,
                }
                self._safe_write_json(self._path, payload)
                return
            except Exception:
                pass
        # Fallback: reduced legacy payload
        reduced = {
            "cycle": snap.cycle,
            "ts_built": snap.ts_built,
            "errors": list(snap.errors),
            "status_present": bool(snap.status),
        }
        self._safe_write_json(self._path, reduced)
        return

    def teardown(self) -> None:  # pragma: no cover - nothing persistent
        return

    # --- internal helpers ---
    def _safe_write_json(self, path: str, payload: Any) -> None:
        try:
            base_dir = os.path.dirname(path) or "."
            os.makedirs(base_dir, exist_ok=True)
        except Exception:
            pass
        tmp_path = None
        try:
            # Create temp file in same directory for atomic rename semantics
            dir_name = os.path.dirname(path) or "."
            fd, tmp_path = tempfile.mkstemp(prefix=".dossier_tmp_", dir=dir_name)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
                try:
                    f.flush()
                    os.fsync(f.fileno())
                except Exception:
                    pass
            try:
                os.replace(tmp_path, path)
                tmp_path = None
                return
            except Exception:
                pass
        except Exception:
            pass
        # Fallback direct write
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        finally:
            if tmp_path:
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

__all__ = ["DossierWriter"]
