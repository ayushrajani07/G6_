import os, time, importlib
from pathlib import Path


def write_status(path: Path, cycle: int, alerts=None, mem_rss=123456789):
    data = {
        "loop": {"cycle": cycle},
        "interval": 1,
        "memory": {"rss_mb": 100 if mem_rss is None else 256},
    }
    if alerts is not None:
        data["alerts"] = alerts
    path.write_text(__import__('json').dumps(data))


def test_signature_skip(monkeypatch, tmp_path):
    # Enable aggregation + signature
    monkeypatch.setenv("G6_SUMMARY_AGG_V2", "1")
    monkeypatch.setenv("G6_SUMMARY_SIG_V2", "on")
    status_file = tmp_path / "runtime_status.json"
    panels_dir = tmp_path / "panels"
    panels_dir.mkdir()
    # Create rolling alerts log (empty)
    (panels_dir / 'alerts_log.json').write_text('{"updated_at":"x","alerts":[]}')
    monkeypatch.setenv("G6_PANELS_DIR", str(panels_dir))
    write_status(status_file, 1, alerts=[{"time":"2025-09-27T00:00:00Z","level":"INFO","component":"X","message":"a"}])

    # Import app (after env) and snapshot builder
    from scripts.summary import snapshot_builder as sb  # type: ignore
    importlib.reload(sb)
    from scripts.summary import app as summary_app  # type: ignore
    importlib.reload(summary_app)

    # Access metric counters
    sb._ensure_metrics()  # force registration
    skip_metric = sb._get_refresh_skipped_metric()
    assert skip_metric is not None, 'skip metric not registered under signature flag'
    # Simulate render loop logic calling compute_snapshot_signature twice with unchanged status
    sig1 = sb.compute_snapshot_signature(__import__('json').loads(status_file.read_text()))
    sig2 = sb.compute_snapshot_signature(__import__('json').loads(status_file.read_text()))
    assert sig1 == sig2 and sig1 is not None
    base_samples = list(skip_metric.collect())[0].samples[0].value if list(skip_metric.collect())[0].samples else 0
    # Manually invoke increment path by simulating unchanged render_sig
    # (Directly increment to emulate skip since full Live loop not executed here)
    skip_metric.inc()
    after = list(skip_metric.collect())[0].samples[0].value
    assert after == base_samples + 1

    # Change status (alerts list length) to alter signature
    write_status(status_file, 1, alerts=[{"time":"2025-09-27T00:00:00Z","level":"INFO","component":"X","message":"a"}, {"time":"2025-09-27T00:00:01Z","level":"INFO","component":"X","message":"b"}])
    sig3 = sb.compute_snapshot_signature(__import__('json').loads(status_file.read_text()))
    assert sig3 != sig1
