import os, json, tempfile, shutil
from pathlib import Path
import importlib

# We rely on snapshot_builder logic under aggregation flag


def _build_status_with_alert(level="INFO", idx=0):
    return {
        "loop": {"cycle": idx, "last_duration": 0.01},
        "interval": 1,
        "alerts": [
            {"time": f"2025-09-27T00:00:{idx:02d}Z", "level": level, "component": "Test", "message": f"m{idx}"}
        ],
    }


def test_alerts_log_max_enforced(monkeypatch, tmp_path):
    # Enable aggregation V2
    monkeypatch.setenv("G6_SUMMARY_AGG_V2", "1")
    # Very small cap
    monkeypatch.setenv("G6_SUMMARY_ALERTS_LOG_MAX", "5")

    panels_dir = tmp_path / "panels"
    panels_dir.mkdir()
    # Point data/panels to our tmp panels dir by chdir-ing (tests usually run from repo root; use monkeypatch)
    cwd = os.getcwd()
    monkeypatch.chdir(tmp_path)

    # Import (after env) to ensure flag active; if already imported in session force reload
    from scripts.summary import snapshot_builder as sb  # type: ignore
    importlib.reload(sb)

    # Pre-seed log with more than cap
    log_path = Path("data/panels/alerts_log.json")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    preseed = {"updated_at": "2025-09-27T00:00:00Z", "alerts": []}
    for i in range(7):
        preseed["alerts"].append({"time": f"2025-09-27T00:00:{i:02d}Z", "level": "INFO", "component": "Seed", "message": f"seed{i}"})
    log_path.write_text(json.dumps(preseed))

    # Build several snapshots adding distinct alerts
    for i in range(3):
        status = _build_status_with_alert(idx=10 + i)
        sb.build_frame_snapshot(status, panels_dir=str(panels_dir))

    # Read final log
    data = json.loads(log_path.read_text())
    assert isinstance(data, dict)
    alerts = data.get("alerts", [])
    assert len(alerts) <= 5, f"alerts_log size exceeded cap: {len(alerts)} > 5"
    # Ensure latest entries (by time) present (trim keeps tail)
    times = [a.get("time") for a in alerts if isinstance(a, dict)]
    # At least one of the newly added alert timestamps (10/11/12 seconds) should be retained
    assert any(any(f"00:00:{s:02d}" in (t or "") for s in (10,11,12)) for t in times), "new alerts not retained after trimming"
