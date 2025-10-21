import csv
from datetime import date
from pathlib import Path

from scripts.weekday_overlay import _parse_time_key, update_weekday_master


def test_parse_time_key_variants():
    assert _parse_time_key("2025-01-02T09:15:30") == "09:15:30"
    assert _parse_time_key("2025-01-02 09:15:30") == "09:15:30"
    assert _parse_time_key("09:15:30") == "09:15:30"
    assert _parse_time_key("") == ""


def test_update_writes_new_schema(tmp_path: Path):
    base = tmp_path / "data/g6_data/NIFTY/this_week/0"
    base.mkdir(parents=True)
    d = date(2025, 1, 2)
    day_csv = base / f"{d:%Y-%m-%d}.csv"
    with open(day_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "timestamp", "ce", "pe", "avg_ce", "avg_pe",
            "ce_iv", "pe_iv",
        ])
        w.writeheader()
        w.writerow({
            "timestamp": f"{d:%Y-%m-%d} 09:15:30",
            "ce": "10",
            "pe": "20",
            "avg_ce": "8",
            "avg_pe": "16",
            "ce_iv": "12.5",
            "pe_iv": "13.5",
        })

    out_root = tmp_path / "data/weekday_master"
    issues: list[dict] = []
    updated = update_weekday_master(
        base_dir=str(tmp_path / "data/g6_data"),
        out_root=str(out_root),
        index="NIFTY",
        trade_date=d,
        alpha=0.5,
        issues=issues,
        backup=False,
        market_open="09:15:30",
        market_close="15:30:00",
    )
    assert updated > 0

    # Monday=MONDAY etc; Jan 2, 2025 is THURSDAY
    master = out_root / "NIFTY/this_week/0/THURSDAY.csv"
    assert master.exists()
    rows = list(csv.DictReader(open(master)))
    assert rows and rows[0]["tp_mean"] and rows[0]["avg_tp_ema"]
    # metric extras should exist even if defaulted
    assert "ce_iv_mean" in rows[0] and "pe_iv_ema" in rows[0]
