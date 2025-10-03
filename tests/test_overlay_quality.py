import json
from pathlib import Path
from datetime import date
import io
import csv

from src.utils.overlay_quality import write_quality_report, validate_csv_header


def test_write_quality_report_appends(tmp_path: Path):
    out_root = tmp_path / "weekday_master"
    out_root.mkdir(parents=True, exist_ok=True)
    run1 = {"indices": ["NIFTY"], "total_updates": 10, "issues": []}
    run2 = {
        "indices": ["NIFTY"],
        "total_updates": 5,
        "issues": [
            {"type": "missing_daily_csv", "index": "NIFTY"},
            {"type": "parse_master_error", "index": "NIFTY"}
        ]
    }

    # First write
    p1 = write_quality_report(out_root, date.fromisoformat("2025-09-23"), "Tuesday", run1)
    assert p1.exists()
    data1 = json.loads(p1.read_text())
    assert data1["date"] == "2025-09-23"
    assert data1["weekday"] == "Tuesday"
    assert len(data1["runs"]) == 1
    assert data1["runs"][0]["total_updates"] == 10

    # Append second run
    p2 = write_quality_report(out_root, date.fromisoformat("2025-09-23"), "Tuesday", run2)
    assert p2 == p1
    data2 = json.loads(p2.read_text())
    assert len(data2["runs"]) == 2
    r2 = data2["runs"][1]
    assert r2["total_updates"] == 5
    # Severity mapping and counts
    sev = r2.get("severity_map", {})
    assert sev.get("missing_daily_csv") == "warning"
    assert sev.get("parse_master_error") == "critical"
    counts = r2.get("issue_counts", {})
    assert counts.get("missing_daily_csv") == 1
    assert counts.get("parse_master_error") == 1


def test_validate_csv_header_ok(tmp_path: Path):
    csv_path = tmp_path / "ok.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp", "ce", "pe"])  # header
        w.writerow(["2025-09-23T09:15:00Z", "1.0", "2.0"])  # one data row
    ok, header = validate_csv_header(csv_path, ["timestamp"])
    assert ok is True
    assert "timestamp" in header


def test_validate_csv_header_missing(tmp_path: Path):
    csv_path = tmp_path / "bad.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time", "value"])  # wrong header
        w.writerow(["09:15", "3.0"])  # one data row
    ok, header = validate_csv_header(csv_path, ["timestamp"])  # timestamp required
    assert ok is False
    assert header != []
