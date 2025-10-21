#!/usr/bin/env python3
"""Error taxonomy for pipeline phases.

Provides explicit exception classes consumed by the pipeline executor and
PhaseLogger to distinguish control flow outcomes.

Hierarchy:
  PipelineError (base)
    PhaseAbortError        -> Expected early termination (skip remainder, not an error)
    PhaseRecoverableError  -> Non-fatal issue; pipeline stops this expiry but overall run continues
    PhaseFatalError        -> Serious issue; may trigger broader alerting (still caught per-expiry)

Guidance:
- Use PhaseAbortError when a phase determines downstream phases are irrelevant (e.g., empty strikes after mandatory filter).
- Use PhaseRecoverableError for conditions that should not escalate but invalidate this expiry's data (bad enrichment source, etc.).
- Use PhaseFatalError for unexpected invariants or integrity failures requiring operator visibility.

These are intentionally light so they can be extended with richer context later.
"""
from __future__ import annotations


class PipelineError(Exception):
    """Base class for pipeline-specific errors."""
    pass

class PhaseAbortError(PipelineError):
    """Abort remaining phases for this expiry (expected control flow)."""
    pass

class PhaseRecoverableError(PipelineError):
    """Recoverable non-fatal issue; stop processing this expiry only."""
    pass

class PhaseFatalError(PipelineError):
    """Serious invariant breach; captured but logged at ERROR severity."""
    pass
