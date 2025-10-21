from __future__ import annotations

from pathlib import Path
import tempfile
import time
import json

from src.utils.csv_cache import get_last_row_csv, read_json_cached


def test_get_last_row_csv_updates_on_mtime():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "sample.csv"
        # Initial write
        p.write_text("a,b\n1,2\n", encoding="utf-8")
        row1 = get_last_row_csv(p)
        assert row1 == {"a": "1", "b": "2"}

        # Rewriting with new last row should update after mtime changes
        time.sleep(1.1)  # ensure mtime tick (Windows granularity)
        p.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
        row2 = get_last_row_csv(p)
        assert row2 == {"a": "3", "b": "4"}


def test_read_json_cached_updates_on_mtime():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "d.json"
        p.write_text(json.dumps({"x": 1}), encoding="utf-8")
        d1 = read_json_cached(p)
        assert d1.get("x") == 1

        time.sleep(1.1)
        p.write_text(json.dumps({"x": 2, "y": 3}), encoding="utf-8")
        d2 = read_json_cached(p)
        assert d2.get("x") == 2 and d2.get("y") == 3
