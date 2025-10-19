#!/usr/bin/env python
"""Diff two dashboard panel inventory files.

Supports CSV or JSONL inputs (auto-detected by file extension).
Key identity: panel_uuid. Renames are detected when the same panel_uuid has a different title.

Output: human-readable summary + optional machine JSON (--json-out).

Exit codes:
 0  no differences
 7  differences detected
 2  input error

Fields expected: slug,title,metric,source,panel_uuid
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

_FIELDS = ["slug", "title", "metric", "source", "panel_uuid"]


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Diff dashboard panel inventories")
    p.add_argument("prev", type=Path, help="Previous inventory (CSV or JSONL)")
    p.add_argument("curr", type=Path, help="Current inventory (CSV or JSONL)")
    p.add_argument("--json-out", type=Path, help="Optional JSON file with structured diff result")
    # Default behavior: fail (exit 7) when differences are present. Allow opting out.
    try:
        action = argparse.BooleanOptionalAction  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover - fallback for very old Python
        action = None  # type: ignore[assignment]
    if action is not None:
        p.add_argument(
            "--fail-on-change",
            action=action,
            default=True,
            help="Exit 7 when differences present (default true)",
        )
    else:
        p.add_argument("--fail-on-change", action="store_true", help="Exit 7 when differences present (default)")
    return p.parse_args(argv)


def load_inventory(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    ext = path.suffix.lower()
    rows: list[dict[str, Any]] = []
    text_lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    if ext == ".jsonl":
        for line in text_lines:
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if isinstance(obj, dict):
                rows.append(obj)
    else:  # assume CSV
        import io

        reader = csv.DictReader(io.StringIO("\n".join(text_lines)))
        # DictReader yields dict[str, str]; treat generically
        rows.extend(dict(r) for r in reader)
    inv: dict[str, dict[str, Any]] = {}
    for r in rows:
        pu = r.get("panel_uuid")
        if not pu or not isinstance(pu, str):
            continue
        inv[pu] = r
    return inv


def diff(
    prev: dict[str, dict[str, Any]],
    curr: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    added: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    renamed: list[dict[str, Any]] = []
    for uuid, row in curr.items():
        if uuid not in prev:
            added.append(row)
    for uuid, row in prev.items():
        if uuid not in curr:
            removed.append(row)
    for uuid, row in curr.items():
        if uuid in prev:
            old_title = prev[uuid].get("title")
            new_title = row.get("title")
            if isinstance(old_title, str) and isinstance(new_title, str) and old_title != new_title:
                renamed.append(
                    {
                        "panel_uuid": uuid,
                        "old_title": old_title,
                        "new_title": new_title,
                        "slug": row.get("slug") or prev[uuid].get("slug"),
                    }
                )
    return added, removed, renamed


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    try:
        prev = load_inventory(args.prev)
        curr = load_inventory(args.curr)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    added, removed, renamed = diff(prev, curr)
    if not (added or removed or renamed):
        print("No differences")
        if args.json_out:
            args.json_out.write_text(
                json.dumps({"added": [], "removed": [], "renamed": []}, indent=2, sort_keys=True)
            )
        return 0
    print("Inventory Differences Detected:")
    if added:
        print(f"  Added ({len(added)}):")
        for r in added[:20]:
            print(f"    + {r.get('panel_uuid')} {r.get('slug')} :: {r.get('title')}")
        if len(added) > 20:
            print(f"    ... {len(added)-20} more")
    if removed:
        print(f"  Removed ({len(removed)}):")
        for r in removed[:20]:
            print(f"    - {r.get('panel_uuid')} {r.get('slug')} :: {r.get('title')}")
        if len(removed) > 20:
            print(f"    ... {len(removed)-20} more")
    if renamed:
        print(f"  Renamed ({len(renamed)}):")
        for r in renamed[:20]:
            print(f"    ~ {r['panel_uuid']} {r['slug']} :: '{r['old_title']}' -> '{r['new_title']}'")
        if len(renamed) > 20:
            print(f"    ... {len(renamed)-20} more")
    if args.json_out:
        args.json_out.write_text(
            json.dumps(
                {
                    "added": added,
                    "removed": removed,
                    "renamed": renamed,
                },
                indent=2,
                sort_keys=True,
            )
        )
    # Default: fail (7) when differences present; allow --no-fail-on-change to return 0
    return 7 if getattr(args, "fail_on_change", True) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
