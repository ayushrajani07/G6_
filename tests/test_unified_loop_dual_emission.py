import time
from typing import Any

from scripts.summary.unified_loop import UnifiedLoop
from scripts.summary.plugins.base import SummarySnapshot, OutputPlugin

# Minimal fake plugin to capture snapshot for assertion
class CapturePlugin:
    name = "capture"
    def __init__(self):
        self.snaps: list[SummarySnapshot] = []
    def setup(self, context):  # pragma: no cover - trivial
        pass
    def process(self, snap: SummarySnapshot):
        self.snaps.append(snap)
    def teardown(self):  # pragma: no cover - trivial
        pass


def test_dual_emission_model_present(monkeypatch, tmp_path):
    # Create a minimal runtime_status file
    status_file = tmp_path / "runtime_status.json"
    status_file.write_text("{\n  \"market\": {\"status\": \"open\"}, \n  \"loop\": {\"cycle\": 1}, \n  \"provider\": {\"name\": \"dummy\"}\n}")
    monkeypatch.setenv("G6_SUMMARY_STATUS_FILE", str(status_file))

    cap = CapturePlugin()
    loop = UnifiedLoop(plugins=[cap], panels_dir=str(tmp_path), refresh=0.01)
    loop.run(cycles=1)

    assert cap.snaps, "No snapshot captured"
    snap = cap.snaps[-1]
    # Dual emission: model should be populated
    assert getattr(snap, 'model', None) is not None, "snapshot.model not populated"
    model = snap.model  # type: ignore[assignment]
    assert model is not None
    # Basic invariants
    assert model.market_status in {"OPEN", "?"}
    assert model.schema_version >= 1
