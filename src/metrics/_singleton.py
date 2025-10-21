"""Central metrics singleton anchor.

This module provides a single source of truth for the process-wide MetricsRegistry
instance to avoid divergence when importing via different paths (facade vs legacy).

Public helpers kept intentionally tiny to minimize import side-effects.
"""
from __future__ import annotations

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from .metrics import MetricsRegistry  # type: ignore

REGISTRY_SINGLETON: MetricsRegistry | None = None
_REGISTRY_LOCK = threading.Lock()


def get_singleton():  # pragma: no cover - trivial
    return REGISTRY_SINGLETON


def set_singleton(reg):  # pragma: no cover - trivial
    global REGISTRY_SINGLETON  # noqa: PLW0603
    if REGISTRY_SINGLETON is reg:
        return REGISTRY_SINGLETON
    with _REGISTRY_LOCK:
        if REGISTRY_SINGLETON is None:
            REGISTRY_SINGLETON = reg
    return REGISTRY_SINGLETON

def create_if_absent(factory):  # pragma: no cover - tiny helper
    """Atomically create and publish singleton using factory() if absent.

    Returns existing singleton if already set; otherwise the newly created one.
    The factory is only invoked inside the lock when the singleton is absent.
    """
    global REGISTRY_SINGLETON  # noqa: PLW0603
    if REGISTRY_SINGLETON is not None:
        return REGISTRY_SINGLETON
    with _REGISTRY_LOCK:
        if REGISTRY_SINGLETON is None:
            REGISTRY_SINGLETON = factory()
        return REGISTRY_SINGLETON

def clear_singleton():  # pragma: no cover - tiny helper
    """Forcefully clear the central MetricsRegistry singleton.

    Used in test reset paths so that environment-based gating is re-evaluated
    on next setup. Safe to call even if already None.
    """
    global REGISTRY_SINGLETON  # noqa: PLW0603
    with _REGISTRY_LOCK:
        REGISTRY_SINGLETON = None

__all__ = ["get_singleton", "set_singleton", "create_if_absent", "clear_singleton", "REGISTRY_SINGLETON"]
