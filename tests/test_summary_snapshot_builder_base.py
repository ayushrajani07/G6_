import os
import json
import importlib

def _reload_builder_with_flag(monkeypatch, value: str):
    monkeypatch.setenv('G6_SUMMARY_AGG_V2', value)
    import scripts.summary.snapshot_builder as sb
    importlib.reload(sb)
    return sb


def test_snapshot_builder_basic(tmp_path, monkeypatch):
    # Force flag off here to preserve original expectation of raw alerts only (no synthetic/log relocation path)
    sb = _reload_builder_with_flag(monkeypatch, '0')
    # Provide a minimal status structure
    status = {
        "loop": {"cycle": 42, "last_duration": 0.123},
        "interval": 60,
        "indices_detail": {
            "NIFTY": {"dq": {"score_percent": 98.5}, "status": "OK", "age": 2.0},
            "BANKNIFTY": {"dq": {"score_percent": 87.0}, "status": "WARN", "age": 5.0},
        },
        "alerts": [
            {"level": "warn", "msg": "lag"},
            {"level": "error", "msg": "dq"},
        ],
        "memory": {"rss_mb": 512},
    }

    panels_dir = tmp_path / "panels"
    panels_dir.mkdir()

    # Add an index only present in stream to test enrichment
    indices_stream = [
        {"index": "FINNIFTY", "dq_score": 75.0, "status": "OK", "time": "2025-01-01T00:00:00Z"}
    ]
    (panels_dir / "indices_stream.json").write_text(json.dumps(indices_stream))

    snap = sb.build_frame_snapshot(status, panels_dir=str(panels_dir))
    d = sb.snapshot_to_dict(snap)

    assert d["cycle"]["cycle"] == 42
    names = {i["name"] for i in d["indices"]}
    assert {"NIFTY", "BANKNIFTY", "FINNIFTY"}.issubset(names)
    # Alerts aggregated
    assert d["alerts"]["total"] == 2
    assert d["memory"]["rss_mb"] == 512
    assert d["raw_status_present"] is True
    assert d["panels_mode"] is True


def test_snapshot_builder_missing_files(monkeypatch):
    sb = _reload_builder_with_flag(monkeypatch, '0')
    snap = sb.build_frame_snapshot(None, panels_dir=None)
    d = sb.snapshot_to_dict(snap)
    assert d["raw_status_present"] is False
    assert d["indices"] == []
    assert d["alerts"]["total"] == 0
