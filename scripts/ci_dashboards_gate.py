#!/usr/bin/env python3
"""CI gate for Grafana dashboards.

Steps:
 1) Generate dashboards with verify (fail on drift)
 2) Validate spec-to-dashboard coverage (fail if uncovered)
 3) Build manifest only (sanity check JSON + required fields)
 4) Inventory diff (prev vs curr) – non-fatal by default; set G6_INV_DIFF_STRICT=1 to fail on change

Exit codes:
 0 success; non-zero on any failure (or on inventory diff when strict is enabled).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
DIST = ROOT / "dist"
GEN_DIR = ROOT / "grafana" / "dashboards" / "generated"


def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd or ROOT, text=True, capture_output=True)


def _git(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *cmd], cwd=ROOT, text=True, capture_output=True)


def _ensure_dist() -> None:
    DIST.mkdir(parents=True, exist_ok=True)


def _resolve_prev_ref() -> str | None:
    # Prefer merge-base with origin/<base> on PRs; fallback to HEAD~1
    base = os.environ.get("GITHUB_BASE_REF")
    if base:
        mb = _git(["merge-base", "HEAD", f"origin/{base}"])
        if mb.returncode == 0:
            ref = (mb.stdout or "").strip()
            if ref:
                return ref
    # Fallback
    return "HEAD~1"


def _extract_prev_dashboards(prev_ref: str, out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    ls = _git(["ls-tree", "-r", "--name-only", prev_ref, "--", "grafana/dashboards/generated"])
    if ls.returncode != 0:
        return 0
    files = [ln.strip() for ln in (ls.stdout or "").splitlines() if ln.strip().endswith(".json")]
    count = 0
    for rel in files:
        show = _git(["show", f"{prev_ref}:{rel}"])
        if show.returncode != 0:
            continue
        dest = out_dir / Path(rel).name
        dest.write_text(show.stdout, encoding="utf-8")
        count += 1
    return count


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
    # Step 4: Inventory diff (prev vs curr). Non-fatal unless strict.
    strict = os.environ.get("G6_INV_DIFF_STRICT", "0") in ("1", "true", "yes")
    _ensure_dist()
    prev_ref = _resolve_prev_ref()
    prev_dir = DIST / "_prev_dashboards"
    if not GEN_DIR.exists():
        print("[ci-dash] inventory diff: no current generated dashboards; skipping")
        print("[ci-dash] all checks passed")
        return 0
    prev_count = _extract_prev_dashboards(prev_ref or "HEAD~1", prev_dir)
    if prev_count == 0:
        print("[ci-dash] inventory diff: no previous dashboards found; skipping")
        print("[ci-dash] all checks passed")
        return 0
    inv_prev = DIST / "inventory_prev.csv"
    inv_curr = DIST / "inventory_curr.csv"
    diff_json = DIST / "inventory_diff.json"
    print("[ci-dash] step 4a: export previous inventory")
    r1 = run([PY, "scripts/export_dashboard_inventory.py", "--dir", str(prev_dir), "--format", "csv", "--out", str(inv_prev)])
    if r1.returncode != 0:
        print(r1.stdout)
        print(r1.stderr, file=sys.stderr)
        if strict:
            print("[ci-dash] inventory export (prev) failed", file=sys.stderr)
            return r1.returncode
        print("[ci-dash] inventory export (prev) failed; skipping diff")
        print("[ci-dash] all checks passed")
        return 0
    print("[ci-dash] step 4b: export current inventory")
    r2 = run([PY, "scripts/export_dashboard_inventory.py", "--dir", str(GEN_DIR), "--format", "csv", "--out", str(inv_curr)])
    if r2.returncode != 0:
        print(r2.stdout)
        print(r2.stderr, file=sys.stderr)
        if strict:
            print("[ci-dash] inventory export (curr) failed", file=sys.stderr)
            return r2.returncode
        print("[ci-dash] inventory export (curr) failed; skipping diff")
        print("[ci-dash] all checks passed")
        return 0
    print("[ci-dash] step 4c: diff inventories")
    r3 = run([PY, "scripts/diff_dashboard_inventory.py", str(inv_prev), str(inv_curr), "--json-out", str(diff_json)])
    sys.stdout.write(r3.stdout)
    sys.stderr.write(r3.stderr)
    if r3.returncode not in (0, 7):
        if strict:
            print("[ci-dash] inventory diff failed (unexpected error)", file=sys.stderr)
            return r3.returncode
        print("[ci-dash] inventory diff errored; skipping enforcement")
        print("[ci-dash] all checks passed")
        return 0
    if r3.returncode == 7:
        msg = "[ci-dash] inventory differences detected"
        if strict:
            print(msg + " (strict) -> failing gate", file=sys.stderr)
            return 7
        else:
            print(msg + " (non-strict) -> allowing")
    print("[ci-dash] all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
