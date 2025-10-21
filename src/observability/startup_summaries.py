"""Central dispatcher for one-shot startup summaries.

This module provides a registration mechanism so future summaries can be
added without editing orchestrator/bootstrap directly. It is intentionally
lightweight and idempotent. Each summary emitter is a callable returning
True if it emitted (structured) or False if skipped.

The dispatcher records which summary types have already emitted to avoid
double logging if called multiple times (e.g., tests + runtime).

It also computes a composite stable hash across field hashes emitted by
JSON summaries (when available) and will emit a combined summary line
`startup.summaries.hash` once after all registered summaries attempted.
"""
from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)

_REGISTRY: list[tuple[str, Callable[[], bool]]] = []
_EMITTED: dict[str, bool] = {}
_JSON_FIELD_HASHES: list[str] = []
_COMPOSITE_EMITTED = False

def register_summary(name: str, emitter: Callable[[], bool]) -> None:
    if any(n == name for n,_ in _REGISTRY):  # preserve existing order, ignore duplicate
        return
    _REGISTRY.append((name, emitter))

def register_or_note_summary(name: str, emitted: bool) -> None:
    """Idempotently register a no-op emitter if not present and mark emission status.

    This reduces boilerplate in summary producers who historically had to both
    register a dummy callable and handle the case where the structured line was
    already emitted earlier (e.g., prior import or different code path).

    Parameters
    ----------
    name : str
        Logical summary name (without .summary suffix).
    emitted : bool
        Whether the summary's structured line has already been emitted.
    """
    if not any(n == name for n,_ in _REGISTRY):
        def _noop():  # noqa: D401 - trivial callable
            return False
        _REGISTRY.append((name, _noop))
    _EMITTED[name] = bool(emitted) or _EMITTED.get(name, False)

def emit_and_register_summary(name: str, emitter: Callable[[], bool]) -> bool:
    """Emit a summary immediately via provided emitter and record its status.

    If the summary has already emitted (tracked in _EMITTED), the emitter will
    not be re-run unless the caller explicitly desires (current behavior: skip).
    The emitter is still registered for future dispatcher accounting.

    Returns
    -------
    bool
        True if emitter ran this invocation; False if skipped due to prior emission.
    """
    if _EMITTED.get(name):  # already emitted; just ensure registration and exit
        register_or_note_summary(name, emitted=True)
        return False
    try:
        emitted = bool(emitter())
    except Exception:  # pragma: no cover - defensive path
        logger.debug("summary_emitter_failed immediate name=%s", name, exc_info=True)
        emitted = False
    register_or_note_summary(name, emitted=emitted)
    return emitted

def note_json_hash(h: str) -> None:
    # Called by JSON emitters (optional). Stored for composite hash.
    if h and h not in _JSON_FIELD_HASHES:
        _JSON_FIELD_HASHES.append(h)

def emit_all_summaries(include_composite: bool = True) -> None:
    global _COMPOSITE_EMITTED
    for name, fn in _REGISTRY:
        if _EMITTED.get(name):
            continue
        try:
            emitted = fn()
            _EMITTED[name] = bool(emitted)
        except Exception:  # pragma: no cover
            logger.debug("summary_emitter_failed name=%s", name, exc_info=True)
            _EMITTED[name] = False
    if include_composite and not _COMPOSITE_EMITTED:
        try:
            ordered = sorted(_JSON_FIELD_HASHES)
            composite = hashlib.sha256('|'.join(ordered).encode('utf-8')).hexdigest()[:24]
            logger.info("startup.summaries.hash count=%s composite=%s ts=%s", len(ordered), composite, int(time.time()))
            _COMPOSITE_EMITTED = True
        except Exception:  # pragma: no cover
            pass

# --- Test / internal utilities (not part of production public API) ---
def _reset_startup_summaries_state(clear_registry: bool = False) -> None:  # pragma: no cover - exercised via tests
    """Reset dispatcher internal state for deterministic test scenarios.

    Parameters
    ----------
    clear_registry : bool, default False
        When True also clears the registered emitters. Most tests only need
        to reset emitted flags & composite hash while preserving registrations
        performed at import time (e.g., env.deprecations). Set True if a test
        wants to simulate a brand-new interpreter import sequence.
    """
    global _COMPOSITE_EMITTED
    _EMITTED.clear()
    _JSON_FIELD_HASHES.clear()
    _COMPOSITE_EMITTED = False
    if clear_registry:
        _REGISTRY.clear()

def _force_emit_env_deprecations_summary() -> bool:  # pragma: no cover - deterministic helper
    """Force (re)emission attempt of env.deprecations summary.

    This calls the registered emitter directly if present; otherwise returns False.
    Useful for integration tests that need deterministic presence of the
    env.deprecations.summary line even when zero deprecated vars are set.
    """
    for name, fn in _REGISTRY:
        if name == 'env.deprecations':
            try:
                emitted = fn()
                _EMITTED[name] = bool(emitted)
                return emitted
            except Exception:
                logger.debug("env_deprecations_force_emit_failed", exc_info=True)
                return False
    return False

__all__ = [
    'register_summary',
    'emit_all_summaries',
    'note_json_hash',
    'register_or_note_summary',
    'emit_and_register_summary',
    # Internal/testing helpers (intentionally underscored)
    '_reset_startup_summaries_state',
    '_force_emit_env_deprecations_summary',
]
