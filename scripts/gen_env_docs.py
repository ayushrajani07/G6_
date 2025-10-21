#!/usr/bin/env python3
"""Generate Markdown docs for environment variables from the registry.

Writes docs/ENVIRONMENT.md.
"""
from __future__ import annotations

import os
import sys


def _ensure_sys_path() -> None:
    try:
        from src.utils.path_utils import ensure_src_in_path
        ensure_src_in_path()
    except Exception:
        here = os.path.dirname(os.path.abspath(__file__))
        root = os.path.dirname(here)
        src_dir = os.path.join(root, "src")
        if src_dir not in sys.path:
            sys.path.insert(0, src_dir)
        if root not in sys.path:
            sys.path.insert(0, root)


def main() -> int:
    _ensure_sys_path()
    try:
        from src.config.env_docs import generate_markdown  # type: ignore
    except Exception as e:
        print(f"Failed to import env docs generator: {e}")
        return 1
    md = generate_markdown()
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    out_dir = os.path.join(root, "docs")
    os.makedirs(out_dir, exist_ok=True)
    out_file = os.path.join(out_dir, "ENVIRONMENT.md")
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"Wrote {out_file} ({len(md)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
