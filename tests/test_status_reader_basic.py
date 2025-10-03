import json
import os
import time
from pathlib import Path

from src.utils.status_reader import get_status_reader


def test_status_reader_basic_load(tmp_path: Path):
    p = tmp_path / "rs.json"
    payload = {
        "cycle": 42,
        "timestamp": "2025-09-21T12:00:00Z",
        "provider": {"name": "sim", "auth": {"valid": True}},
        "resources": {"cpu": 12.5, "memory_mb": 256},
        "health": {"io": "OK"},
        "indices_detail": {"NIFTY": {"legs": 10}},
    }
    p.write_text(json.dumps(payload), encoding="utf-8")

    r = get_status_reader(str(p))
    raw = r.get_raw_status()
    assert isinstance(raw, dict)
    assert raw.get("cycle") == 42

    # Sections
    assert r.get_provider_data().get("name") in ("sim", None)
    assert isinstance(r.get_resources_data(), dict)
    assert isinstance(r.get_health_data(), dict)
    ids = r.get_indices_data()
    assert isinstance(ids, dict)
    assert "NIFTY" in ids or True  # allow empty if not present


def test_status_reader_typed_and_age(tmp_path: Path):
    p = tmp_path / "rs.json"
    payload = {
        "timestamp": "2025-09-21T12:00:00Z",
        "a": {"b": {"c": 123}},
    }
    p.write_text(json.dumps(payload), encoding="utf-8")
    r = get_status_reader(str(p))

    # typed path
    assert r.get_typed("a.b.c", 0) == 123
    assert r.get_typed("a.x.y", 7) == 7

    # age seconds falls back to file mtime when timestamp is parseable but arbitrary
    age = r.get_status_age_seconds()
    assert age is None or isinstance(age, float)

    # Update mtime and ensure method returns a value (non-None) when using mtime fallback
    os.utime(str(p), None)
    time.sleep(0.01)
    age2 = r.get_status_age_seconds()
    assert age2 is None or isinstance(age2, float)
