"""Autouse fixtures to reduce cross-test interference / flakiness.

Scope: clean up background threads (SSE / summary) that some tests start and
leave running briefly. The earlier transient full-suite failure likely stemmed
from overlapping SSE servers or metrics registry state.

Strategy:
 - After each test, attempt to join any non-daemon threads whose name matches
   known launcher prefixes within a short timeout.
 - Provide a helper to force reload summary env to prevent state leakage.
 - Ensure metrics registry group filters are reloaded if mutated.

Low risk: best-effort cleanup; failures are swallowed to avoid masking real test failures.
"""
from __future__ import annotations
import threading, time, os
import pytest

SAFE_THREAD_PREFIXES = ("SSEPublisher", "UnifiedLoop", "SummaryLoop")

@pytest.fixture(autouse=True)
def _cleanup_background_threads():
    yield
    # Post-test cleanup phase
    deadline = time.time() + 0.5  # 500ms budget
    for t in list(threading.enumerate()):
        if t is threading.current_thread():
            continue
        name = t.name or ""
        if any(name.startswith(p) for p in SAFE_THREAD_PREFIXES):
            # Attempt graceful join
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            try:
                t.join(timeout=max(0.01, remaining))
            except RuntimeError:
                continue

    # Clear summary env cache if present to avoid bleed of env var modifications between tests
    try:
        from scripts.summary import env_config as _ec  # type: ignore
        if getattr(_ec, "_CACHED", None) is not None:
            _ec._CACHED = None  # reset cache so next test re-parses env
    except Exception:
        pass

    # Attempt metrics group filter reload if registry mutated
    try:
        from src.metrics import metrics as _m  # type: ignore
        reg = _m.get_metrics_singleton()
        if reg is not None:
            try:
                reg.reload_group_filters()  # type: ignore[attr-defined]
            except Exception:
                pass
    except Exception:
        pass
