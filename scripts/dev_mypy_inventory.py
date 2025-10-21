"""Utility to summarize mypy_full.txt output.

Generates:
 - Top offending files by error count (printed)
 - JSON inventory with per-file counts and error code tallies: mypy_inventory.json

Assumes a prior run:  python -m mypy . > mypy_full.txt 2>&1
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

MYPY_OUTPUT_PATH = Path("mypy_full.txt")
INVENTORY_PATH = Path("mypy_inventory.json")

FILE_LINE_RE = re.compile(r"^(?P<file>[^:]+):(?P<line>\d+): (?P<rest>.*)$")
CODE_RE = re.compile(r"\[([a-z0-9_-]+)\]")

if not MYPY_OUTPUT_PATH.exists():
    raise SystemExit("mypy_full.txt not found – run the mypy sweep first.")

per_file_counts: Counter[str] = Counter()
per_code_counts: Counter[str] = Counter()
per_file_codes: dict[str, Counter[str]] = defaultdict(Counter)

for raw in MYPY_OUTPUT_PATH.read_text(errors="ignore").splitlines():
    m = FILE_LINE_RE.match(raw)
    if not m:
        continue
    file = m.group("file")
    per_file_counts[file] += 1
    # Extract first error code if present (there can be multiple; we grab all)
    for code in CODE_RE.findall(raw):
        per_code_counts[code] += 1
        per_file_codes[file][code] += 1

TOP_N = 40
print(f"Top files by error count (first {TOP_N}):")
for file, count in per_file_counts.most_common(TOP_N):
    print(f"{count:4d}  {file}")

summary = {
    "total_errors": int(sum(per_file_counts.values())),
    "total_files_with_errors": len(per_file_counts),
    "top_files": [{"file": f, "count": c} for f, c in per_file_counts.most_common(200)],
    "top_error_codes": [{"code": c, "count": n} for c, n in per_code_counts.most_common(50)],
    "files": {
        f: {
            "count": c,
            "codes": dict(per_file_codes[f]),
        }
        for f, c in per_file_counts.items()
    },
}
INVENTORY_PATH.write_text(json.dumps(summary, indent=2))
print(f"\nWrote inventory JSON -> {INVENTORY_PATH}")
