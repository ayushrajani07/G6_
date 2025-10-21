"""Quality reporting and lightweight CSV validation helpers for overlays.

This module stays dependency-light and can be safely imported from scripts.
"""
from __future__ import annotations

import csv
import json
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any


def validate_csv_header(path: Path | str, required_columns: Sequence[str]) -> tuple[bool, Sequence[str]]:
    """Quickly validate that a CSV file contains the required header columns.

    Returns (ok, header_columns). Any exception results in (False, []).
    """
    try:
        p = Path(path)
        if not p.exists() or p.stat().st_size == 0:
            return False, []
        with p.open('r', newline='') as f:
            reader = csv.reader(f)
            header = next(reader, [])
            if not header:
                return False, []
            header_lower = [h.strip() for h in header]
            ok = all(req in header_lower for req in required_columns)
            return ok, header_lower
    except Exception:
        return False, []


def _iso_utc(dt: datetime) -> str:
    try:
        return dt.astimezone(UTC).isoformat().replace('+00:00', 'Z')
    except Exception:
        return dt.isoformat()


def write_quality_report(output_root: str | Path, trade_date: date, weekday_name: str, run_summary: dict[str, Any]) -> Path:
    """Write or append a per-date quality report JSON under <output_root>/_quality/.

    Structure:
      {
        "date": "YYYY-MM-DD",
        "weekday": "Monday",
        "generated_utc": "...",
        "runs": [ run_summary, ... ]
      }
    """
    out_dir = Path(output_root) / "_quality"
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / f"overlay_quality_{trade_date:%Y-%m-%d}.json"

    payload: dict[str, Any] = {
        "date": f"{trade_date:%Y-%m-%d}",
        "weekday": weekday_name,
        "generated_utc": _iso_utc(datetime.now(UTC)),
        "runs": []
    }

    # If report exists, try to load and extend
    if report_path.exists():
        try:
            existing = json.loads(report_path.read_text(encoding='utf-8'))
            if isinstance(existing, dict) and "runs" in existing and isinstance(existing["runs"], list):
                payload = existing
        except Exception:
            # If corrupted, we will overwrite with a fresh structure
            pass

    # Attach a simple severity mapping so downstream consumers can act on it
    issues = run_summary.get('issues', []) or []
    severity_map: dict[str, str] = {}
    # Basic rules: parse/read/missing roots are critical; missing daily CSV is warning; others info
    critical_types = {"parse_master_error", "read_error", "missing_index_root"}
    warning_types = {"missing_daily_csv"}
    for iss in issues:
        it = str(iss.get('type', 'unknown'))
        if it in critical_types:
            severity_map[it] = 'critical'
        elif it in warning_types:
            severity_map[it] = 'warning'
        else:
            # default informational
            severity_map.setdefault(it, 'info')
    # Compute counts
    counts: dict[str, int] = {}
    for iss in issues:
        it = str(iss.get('type', 'unknown'))
        counts[it] = counts.get(it, 0) + 1
    run_summary['severity_map'] = severity_map
    run_summary['issue_counts'] = counts

    payload.setdefault("runs", []).append(run_summary)

    report_path.write_text(json.dumps(payload, indent=2), encoding='utf-8')
    return report_path
