from __future__ import annotations

"""Helper utilities for structured phase error recording.

Maintains backward compatibility with legacy `state.errors` string tokens while
appending rich `PhaseErrorRecord` objects to `state.error_records`.
"""
import os
import re
import traceback

from .error_records import PhaseErrorRecord
from .state import ExpiryState

# Token format remains <classification>:<phase>:<message>

def add_phase_error(state: ExpiryState, phase: str, classification: str, message: str, *, detail: str | None=None, attempt: int=1, token: str | None=None, extra: dict | None=None) -> None:
    """Record a phase error in both legacy token list and structured records.

    Parameters:
      state: ExpiryState being mutated.
      phase: Logical phase name (e.g. 'fetch', 'enrich').
      classification: One of taxonomy classes (abort|recoverable|fatal|resolve_abort|...)
                      We keep original prefix tokens found in existing code for parity.
      message: Error message (already simplified by caller; avoid huge reprs).
      detail: Optional dictionary for future enrichment (kept minimal now).
      attempt: Attempt number (1-based) when the error occurred (retry aware).
      token: Override full legacy token string; if omitted we build from classification/phase/message.
    """
    try:
        # Derive token if not provided (legacy token remains UNREDACTED for backward compatibility)
        built = token or f"{classification}:{phase}:{message}"
        state.errors.append(built)
        redacted_message = message
        # Apply redaction (structured record only) if patterns provided
        patterns = os.getenv('G6_PIPELINE_REDACT_PATTERNS','')
        replacement = os.getenv('G6_PIPELINE_REDACT_REPLACEMENT','***')
        if patterns:
            try:
                for pat in [p.strip() for p in patterns.split(',') if p.strip()]:
                    try:
                        redacted_message = re.sub(pat, replacement, redacted_message)
                    except re.error:
                        # Skip invalid regex silently
                        continue
            except Exception:
                pass
        # Optional enrichment: provider names / traceback (guarded by env)
        if os.getenv('G6_PIPELINE_STRUCT_ERROR_ENRICH','').lower() in ('1','true','yes','on'):
            extra = dict(extra or {})
            # Providers: attempt minimal introspection (avoid heavy imports)
            try:
                providers = getattr(getattr(state, 'settings', None), 'providers', None) or getattr(getattr(state, 'settings', None), 'provider', None)
                if providers:
                    if isinstance(providers, (list, tuple)):
                        extra['providers'] = [getattr(p, 'name', str(p))[:40] for p in providers][:10]
                    else:
                        extra['providers'] = [getattr(providers, 'name', str(providers))[:40]]
            except Exception:
                pass
            # Traceback (short form) if classification is unexpected or fatal
            if classification in ('fatal','unknown'):
                try:
                    exc_tb = traceback.format_exc(limit=3)
                    extra['trace'] = exc_tb[-800:]
                except Exception:
                    pass
        # Basic structured record
        rec = PhaseErrorRecord(
            phase=phase,
            classification=classification,
            message=redacted_message,
            detail=detail,
            attempt=attempt,
            outcome_token=built,
            extra=extra,
        )
        state.error_records.append(rec)
        # Conditional metrics increment
        if os.getenv('G6_PIPELINE_STRUCT_ERROR_METRIC','').lower() in ('1','true','yes','on'):
            try:
                from src.metrics import get_metrics  # runtime optional import; ignore removed after typing
                reg = get_metrics()
                m = getattr(reg, 'pipeline_phase_error_records', None)
                if m is not None:
                    m.labels(phase=phase, classification=classification).inc()
            except Exception:
                pass
    except Exception:
        # Fail closed: never raise during error path instrumentation
        pass

__all__ = ["add_phase_error"]
