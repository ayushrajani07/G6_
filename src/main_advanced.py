"""Deprecated legacy advanced entrypoint.

All functionality has been consolidated into `unified_main.py`.

Invoke instead:
    python -m src.unified_main --help
"""

def _deprecated() -> None:  # pragma: no cover
    raise RuntimeError(
        "src.main_advanced is deprecated. Use src.unified_main instead."
    )

if __name__ == "__main__":  # pragma: no cover
    _deprecated()
else:  # pragma: no cover
    _deprecated()