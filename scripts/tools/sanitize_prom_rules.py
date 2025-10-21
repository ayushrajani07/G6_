#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from typing import Any


def load_yaml(path: str) -> dict[str, Any]:
    try:
        import yaml  # type: ignore
    except Exception as e:  # noqa: BLE001
        print(f"pyyaml not installed: {e}")
        sys.exit(2)
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}


def dump_yaml(obj: dict[str, Any], path: str) -> None:
    try:
        import yaml  # type: ignore
    except Exception as e:  # noqa: BLE001
        print(f"pyyaml not installed: {e}")
        sys.exit(2)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(obj, f, default_flow_style=False, sort_keys=False)


def sanitize(groups: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int, int]:
    out_groups: list[dict[str, Any]] = []
    removed = 0
    total = 0
    for g in groups or []:
        rules = g.get("rules") or []
        seen: set[str] = set()
        new_rules: list[dict[str, Any]] = []
        for r in rules:
            total += 1
            rec = r.get("record")
            if rec and rec in seen:
                # drop duplicates; keep first occurrence
                removed += 1
                continue
            if rec:
                seen.add(rec)
            new_rules.append(r)
        new_g = dict(g)
        new_g["rules"] = new_rules
        out_groups.append(new_g)
    return out_groups, total, removed


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("Usage: sanitize_prom_rules.py <input.yml> <output.yml>")
        return 2
    src = os.path.abspath(argv[0])
    dst = os.path.abspath(argv[1])
    data = load_yaml(src)
    groups, total, removed = sanitize(data.get("groups") or [])
    data["groups"] = groups
    dump_yaml(data, dst)
    print(f"Sanitized rules: total={total} removed_dupes={removed} -> {dst}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
