from pathlib import Path

from src.utils.status_reader import get_status_reader


def test_status_reader_missing_file(tmp_path: Path):
    p = tmp_path / "no_such_status.json"
    r = get_status_reader(str(p))
    assert r.exists() is False
    assert r.get_raw_status() == {}
    assert r.get_status_age_seconds() is None


def test_status_reader_malformed_json(tmp_path: Path):
    p = tmp_path / "bad.json"
    # Write intentionally malformed JSON (unclosed string)
    p.write_text('{"bad": ', encoding="utf-8")
    r = get_status_reader(str(p))
    # Malformed should be handled gracefully and return empty dict
    obj = r.get_raw_status()
    assert isinstance(obj, dict)
    assert obj == {}
