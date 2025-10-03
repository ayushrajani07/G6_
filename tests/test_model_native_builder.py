from __future__ import annotations
from typing import Dict, Any

from src.summary.unified.model import assemble_model_snapshot, UnifiedStatusSnapshot

def _status() -> Dict[str, Any]:
    return {
        "market": {"status": "open"},
        "loop": {"cycle": 7, "last_duration": 0.5, "success_rate": 0.9},
        "indices_detail": {
            "NIFTY": {"dq": {"score_percent": 92, "issues_total": 0}},
            "BANKNIFTY": {"dq": {"score_percent": 68, "issues_total": 3}},
        },
        "alerts": [{"t":1},{"t":2}],
    }

def test_native_builder_diag_and_fields():
    snap, diag = assemble_model_snapshot(runtime_status=_status(), panels_dir=None, include_panels=False)
    assert isinstance(snap, UnifiedStatusSnapshot)
    assert diag.get('native') is True, f"Expected native build path; diag={diag}"
    assert 'native_fail' not in (diag.get('warnings') or []), f"Unexpected native_fail warning: {diag}"
    # Basic field sanity
    assert snap.cycle.number == 7
    assert snap.market_status == 'OPEN'
    # DQ classification: 92 -> green, 68 -> error
    assert snap.dq.green == 1 and snap.dq.error == 1
