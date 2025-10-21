#!/usr/bin/env python
from __future__ import annotations

"""
Compatibility shim for the modular dashboards generator.

This module delegates all logic to scripts/gen_dashboards_modular_recovery.py
to ensure a single, clean implementation while keeping the historical entrypoint
name stable for callers and docs.
"""

import sys
from collections.abc import Callable, Sequence
from typing import cast

# Support running as a script (python scripts/...) and as a module (python -m scripts...).
try:  # absolute when run as a plain script
    import gen_dashboards_modular_recovery as _impl  # type: ignore
except Exception:  # pragma: no cover - fallback for "python -m scripts.gen_dashboards_modular"
    from . import gen_dashboards_modular_recovery as _impl  # type: ignore


def main(argv: Sequence[str] | None = None) -> int:
    impl_main = cast(Callable[[Sequence[str]], int], _impl.main)
    return impl_main(sys.argv[1:] if argv is None else argv)


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main(sys.argv[1:]))
