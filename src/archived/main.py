"""Deprecated legacy entrypoint.

This module has been superseded by the orchestrator runner script
(`scripts/run_orchestrator_loop.py`). The intermediate unified_main module
has also been removed (2025-09-28).

Use instead:
    python scripts/run_orchestrator_loop.py --config config/g6_config.json --interval 60

We keep this lightweight stub to avoid breaking external references, but it
raises immediately on import or execution to surface the deprecation early.
"""

from __future__ import annotations


def _deprecated() -> None:
    raise RuntimeError(
        "src.main is deprecated. Use scripts/run_orchestrator_loop.py instead (unified_main removed)."
    )


if __name__ == "__main__":  # pragma: no cover
    _deprecated()
else:
    _deprecated()
