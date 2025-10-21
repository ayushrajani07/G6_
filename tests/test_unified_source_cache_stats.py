import json
import os
import time
from pathlib import Path

from src.data_access.unified_source import UnifiedDataSource, DataSourceConfig


def write_json(p: Path, obj) -> None:
    p.write_text(json.dumps(obj), encoding="utf-8")


def test_cache_stats_status_hits_and_misses(tmp_path, monkeypatch):
    status_file = tmp_path / "runtime_status.json"
    write_json(status_file, {"a": 1})

    cfg = DataSourceConfig(
        runtime_status_path=str(status_file),
        panels_dir=str(tmp_path),
        cache_ttl_seconds=10.0,
        watch_files=True,
        file_poll_interval=0.0,
        enable_cache_stats=True,
    )

    uds = UnifiedDataSource()
    uds.reconfigure(cfg)

    # First read -> miss + read
    d1 = uds.get_runtime_status()
    assert d1 == {"a": 1}
    stats = uds.get_cache_stats()
    assert stats["status"]["misses"] >= 1
    assert stats["status"]["reads"] >= 1

    # Second read quickly -> hit, no additional read
    d2 = uds.get_runtime_status()
    assert d2 == {"a": 1}
    stats2 = uds.get_cache_stats()
    assert stats2["status"]["hits"] >= 1
    assert stats2["status"]["reads"] == stats["status"]["reads"]

    # Update file mtime -> next read should miss and read
    time.sleep(0.01)
    write_json(status_file, {"a": 2})
    d3 = uds.get_runtime_status()
    assert d3 == {"a": 2}
    stats3 = uds.get_cache_stats()
    assert stats3["status"]["misses"] >= stats2["status"]["misses"] + 1
    assert stats3["status"]["reads"] >= stats2["status"]["reads"] + 1


def test_cache_stats_panel_and_raw(tmp_path):
    # Prepare panel file
    panel_file = tmp_path / "foo.json"
    write_json(panel_file, {"data": {"x": 1}})

    cfg = DataSourceConfig(
        runtime_status_path=str(tmp_path / "runtime_status.json"),
        panels_dir=str(tmp_path),
        cache_ttl_seconds=10.0,
        watch_files=True,
        file_poll_interval=0.0,
        enable_cache_stats=True,
    )
    uds = UnifiedDataSource()
    uds.reconfigure(cfg)

    # First reads are misses
    d = uds.get_panel_data("foo")
    assert d == {"x": 1}
    r = uds.get_panel_raw("foo")
    assert r == {"data": {"x": 1}}
    s1 = uds.get_cache_stats()
    assert s1["panel"]["misses"] >= 1 and s1["panel"]["reads"] >= 1
    assert s1["panel_raw"]["misses"] >= 1 and s1["panel_raw"]["reads"] >= 1

    # Second reads are hits
    d2 = uds.get_panel_data("foo")
    r2 = uds.get_panel_raw("foo")
    assert d2 == {"x": 1}
    assert r2 == {"data": {"x": 1}}
    s2 = uds.get_cache_stats()
    assert s2["panel"]["hits"] >= s1["panel"]["hits"] + 1
    assert s2["panel_raw"]["hits"] >= s1["panel_raw"]["hits"] + 1

    # Modify file -> cause miss + read again
    time.sleep(0.01)
    write_json(panel_file, {"data": {"x": 2}})
    d3 = uds.get_panel_data("foo")
    r3 = uds.get_panel_raw("foo")
    assert d3 == {"x": 2}
    assert r3 == {"data": {"x": 2}}
    s3 = uds.get_cache_stats()
    assert s3["panel"]["misses"] >= s2["panel"]["misses"] + 1
    assert s3["panel_raw"]["misses"] >= s2["panel_raw"]["misses"] + 1
