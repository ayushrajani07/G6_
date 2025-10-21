"""Phase-level error taxonomy for collector pipeline.

Provides explicit exception classes to replace broad generic exceptions and
allow the executor to apply differentiated control flow and logging semantics.

Classes:
  PhaseRecoverableError - transient or external issue; pipeline stops further
                          phases for current expiry but overall cycle continues.
  PhaseAbortError       - expected abort condition (invariant precondition not met);
                          treated as clean early return without error severity.
  PhaseFatalError       - unexpected internal failure; logged at ERROR and may
                          trigger alerting paths.

Helper:
  classify_exception(e) -> str  (returns 'recoverable'|'abort'|'fatal'|'unknown')
"""
from __future__ import annotations


class PhaseBaseError(Exception):
    """Base class for phase taxonomy (allows isinstance checks)."""
    pass

class PhaseRecoverableError(PhaseBaseError):
    """Transient/retry-eligible or external dependency issue.

    Examples: temporary provider outage, rate limit, partial data fetch.
    """
    pass

class PhaseAbortError(PhaseBaseError):
    """Clean early exit (precondition not satisfied, nothing to process)."""
    pass

class PhaseFatalError(PhaseBaseError):
    """Unexpected internal failure indicating a code defect or invariant breach."""
    pass


def classify_exception(exc: BaseException) -> str:
    if isinstance(exc, PhaseRecoverableError):
        return 'recoverable'
    if isinstance(exc, PhaseAbortError):
        return 'abort'
    if isinstance(exc, PhaseFatalError):
        return 'fatal'
    return 'unknown'

__all__ = [
    'PhaseRecoverableError', 'PhaseAbortError', 'PhaseFatalError', 'PhaseBaseError','classify_exception'
]
