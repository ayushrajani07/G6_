#!/usr/bin/env python3
"""CI gate for Grafana dashboards.

Steps:
 1) Generate dashboards with verify (fail on drift)
 2) Validate spec-to-dashboard coverage (fail if uncovered)
 3) Build manifest only (sanity check JSON + required fields)

Exit codes:
 0 success; non-zero on any failure.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable


def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd or ROOT, text=True, capture_output=True)


def main() -> int:
    steps = [
        [PY, "scripts/gen_dashboards_modular.py", "--output", "grafana/dashboards/generated", "--verify"],
        [PY, "scripts/validate_spec_panel_coverage.py"],
        [PY, "scripts/package_dashboards.py", "--out", "dist", "--manifest-only"],
    ]
    for i, cmd in enumerate(steps, 1):
        print(f"[ci-dash] step {i}: {' '.join(cmd)}")
        r = run(cmd)
        if r.returncode != 0:
            print(r.stdout)
            print(r.stderr, file=sys.stderr)
            print(f"[ci-dash] step {i} failed (exit {r.returncode})", file=sys.stderr)
            return r.returncode
        else:
            # brief stdout echo (truncated)
            out = (r.stdout or "").strip().splitlines()
            print("[ci-dash] ok:", out[-1] if out else "<no output>")
    print("[ci-dash] all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
