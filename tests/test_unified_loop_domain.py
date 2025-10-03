import os
import json
import tempfile
from scripts.summary.unified_loop import UnifiedLoop
from scripts.summary.plugins.base import OutputPlugin, SummarySnapshot

class CapturePlugin(OutputPlugin):
    name = "capture"
    def __init__(self):
        self.snapshots = []
    def setup(self, context):
        pass
    def process(self, snap: SummarySnapshot):
        self.snapshots.append(snap)
        # Stop after first cycle
        raise KeyboardInterrupt()
    def teardown(self):
        pass


def test_unified_loop_builds_domain(tmp_path):
    status_path = tmp_path / "status.json"
    status_data = {
        "cycle": {"number": 11},
        "indices": ["NIFTY"],
        "alerts": {"total": 1},
        "resources": {"cpu_pct": 2.0, "memory_mb": 32.0},
    }
    status_path.write_text(json.dumps(status_data), encoding='utf-8')
    os.environ['G6_SUMMARY_STATUS_FILE'] = str(status_path)
    cap = CapturePlugin()
    loop = UnifiedLoop(plugins=[cap], panels_dir=str(tmp_path), refresh=0.01)
    try:
        loop.run(cycles=5)
    except KeyboardInterrupt:
        pass
    # Ensure at least one snapshot captured
    assert cap.snapshots
    snap = cap.snapshots[0]
    assert snap.domain is not None
    assert snap.domain.cycle.number == 11
    assert snap.derived.get('indices_count') == 1
