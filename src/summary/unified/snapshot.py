"""Tombstone stub for removed legacy assembler.

All functionality moved to `src.summary.unified.model`. This file will be
deleted in a future release; do not rely on its presence.

Historical context: prior versions exposed `assemble_unified_snapshot` here. It
has been removed in favor of the versioned model pipeline
`assemble_model_snapshot` for stability and evolvability.
"""

from __future__ import annotations

_MSG = (
    "assemble_unified_snapshot removed: use src.summary.unified.model.assemble_model_snapshot"
)

def __getattr__(name: str):  # pragma: no cover
    if name == 'assemble_unified_snapshot':
        raise ImportError(_MSG)
    raise AttributeError(name)

# Explicitly empty public API (legacy names intentionally absent)
__all__: list[str] = []
