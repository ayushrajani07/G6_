import os
import json
import datetime as dt
from pathlib import Path

from src.utils.expiry_service import load_holiday_calendar, build_expiry_service, ExpiryService


def test_load_holiday_calendar(tmp_path: Path):
    data = ["2025-12-25", "2025-01-01", "bad", 123]
    f = tmp_path / "holidays.json"
    f.write_text(json.dumps(data))
    holidays = load_holiday_calendar(str(f))
    assert dt.date(2025,12,25) in holidays and dt.date(2025,1,1) in holidays
    assert len(holidays) == 2


def test_build_expiry_service_flag_disabled(monkeypatch):
    monkeypatch.delenv("G6_EXPIRY_SERVICE", raising=False)
    svc = build_expiry_service()
    assert svc is None


def test_build_expiry_service_enabled_with_holidays(monkeypatch, tmp_path: Path):
    holi = tmp_path / "holidays.json"
    holi.write_text(json.dumps(["2025-06-05"]))
    monkeypatch.setenv("G6_EXPIRY_SERVICE", "1")
    monkeypatch.setenv("G6_HOLIDAYS_FILE", str(holi))
    svc = build_expiry_service()
    assert isinstance(svc, ExpiryService)
    # Ensure holiday filtered out
    today = dt.date(2025,6,1)
    svc.today = today
    cands = [dt.date(2025,6,5), dt.date(2025,6,12)]
    picked = svc.select("this_week", cands)
    assert picked == dt.date(2025,6,12)
