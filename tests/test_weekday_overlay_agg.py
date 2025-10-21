import csv
from pathlib import Path

from scripts.weekday_overlay import update_weekday_master, WEEKDAY_NAMES


def _write_daily_csv(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["timestamp", "ce", "pe", "avg_ce", "avg_pe"])
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _read_master_one(path: Path):
    import csv as _csv
    with path.open("r", newline="", encoding="utf-8") as f:
        r = list(_csv.DictReader(f))
    assert len(r) == 1
    return r[0]


def test_weekday_overlay_update_mean_and_ema(tmp_path):
    base = tmp_path / "data" / "g6_data"
    out = tmp_path / "out"
    index = "NIFTY"
    expiry_tag = "this_week"
    offset = "ATM"
    trade_date_str = "2025-01-02"  # Thursday
    # First run: two duplicate rows for same timestamp (should be averaged once internally)
    daily_file = base / index / expiry_tag / offset / f"{trade_date_str}.csv"
    rows1 = [
        {"timestamp": f"{trade_date_str}T09:20:00", "ce": 100, "pe": 110, "avg_ce": 50, "avg_pe": 60},
        {"timestamp": f"{trade_date_str}T09:20:00", "ce": 100, "pe": 110, "avg_ce": 50, "avg_pe": 60},
    ]
    _write_daily_csv(daily_file, rows1)

    from datetime import date
    trade_date = date.fromisoformat(trade_date_str)
    weekday_name = WEEKDAY_NAMES[trade_date.weekday()]

    # Run with alpha=0.5
    updated = update_weekday_master(str(base), str(out), index, trade_date, alpha=0.5)
    assert updated == 1  # one timestamp bucket updated

    master_path = out / index / expiry_tag / offset / f"{weekday_name.upper()}.csv"
    assert master_path.exists()
    rec1 = _read_master_one(master_path)
    # tp = 100+110 = 210; avg_tp = 50+60 = 110
    assert int(rec1["counter"]) == 1
    assert abs(float(rec1["tp_mean"]) - 210.0) < 1e-6
    assert abs(float(rec1["tp_ema"]) - 210.0) < 1e-6
    assert abs(float(rec1["avg_tp_mean"]) - 110.0) < 1e-6
    assert abs(float(rec1["avg_tp_ema"]) - 110.0) < 1e-6

    # Second run: change values for same timestamp; counters should increment and means/EMAs update accordingly
    rows2 = [
        {"timestamp": f"{trade_date_str}T09:20:00", "ce": 130, "pe": 170, "avg_ce": 60, "avg_pe": 80},
    ]
    _write_daily_csv(daily_file, rows2)

    updated2 = update_weekday_master(str(base), str(out), index, trade_date, alpha=0.5)
    assert updated2 == 1

    rec2 = _read_master_one(master_path)
    # New tp = 300, avg_tp = 140, counters become 2.
    # mean_new = mean_old + (x - mean_old)/n =>
    # tp_mean: 210 + (300-210)/2 = 255; avg_tp_mean: 110 + (140-110)/2 = 125
    # ema_new (alpha=0.5): 0.5*x + 0.5*old => tp_ema: 255; avg_tp_ema: 125
    assert int(rec2["counter"]) == 2
    assert abs(float(rec2["tp_mean"]) - 255.0) < 1e-6
    assert abs(float(rec2["tp_ema"]) - 255.0) < 1e-6
    assert abs(float(rec2["avg_tp_mean"]) - 125.0) < 1e-6
    assert abs(float(rec2["avg_tp_ema"]) - 125.0) < 1e-6
