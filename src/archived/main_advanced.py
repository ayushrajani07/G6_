"""Deprecated legacy advanced entrypoint.

All functionality has been consolidated into the orchestrator runner script.
The unified_main module has been removed (2025-09-28).

Invoke instead:
    python scripts/run_orchestrator_loop.py --config config/g6_config.json --interval 60
"""

def _deprecated() -> None:  # pragma: no cover
    raise RuntimeError(
        "src.main_advanced is deprecated. Use scripts/run_orchestrator_loop.py instead (unified_main removed)."
    )

if __name__ == "__main__":  # pragma: no cover
    _deprecated()
else:  # pragma: no cover
    _deprecated()
