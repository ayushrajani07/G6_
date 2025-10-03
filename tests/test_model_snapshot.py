from __future__ import annotations
import os
from typing import Dict, Any

from src.summary.unified.model import assemble_model_snapshot, UnifiedStatusSnapshot


def _minimal_status() -> Dict[str, Any]:
    return {
        "market": {"status": "open"},
        "loop": {"cycle": 42, "last_duration": 0.12, "success_rate": 0.98},
        "indices_detail": {
            "NIFTY": {"dq": {"score_percent": 91, "issues_total": 0}},
            "BANKNIFTY": {"dq": {"score_percent": 76, "issues_total": 2}},
        },
        "alerts": [ {"type": "iv_crush"} ],
    }


def test_assemble_model_snapshot_basic(tmp_path):
    status = _minimal_status()
    snap, diag = assemble_model_snapshot(runtime_status=status, panels_dir=None, include_panels=False)
    assert isinstance(snap, UnifiedStatusSnapshot)
    assert snap.market_status.lower() == "open"
    assert snap.cycle.number == 42
    assert len(snap.indices) == 2
    # DQ classification: with defaults 91 -> green, 76 -> warn
    assert snap.dq.green == 1 and snap.dq.warn == 1
    assert "warnings" in diag


def test_assemble_model_snapshot_with_panels_override(tmp_path):
    # Create fake panels dir with indices.json
    pdir = tmp_path / "panels"
    pdir.mkdir()
    (pdir / "indices.json").write_text('{"NIFTY": {"dq_score": 50}}')
    status = _minimal_status()
    snap, _ = assemble_model_snapshot(runtime_status=status, panels_dir=str(pdir), include_panels=True)
    # Panel dq_score=50 should override status (score_percent 91) for that index
    names = {i.name: i.dq_score for i in snap.indices}
    assert names.get("NIFTY") == 50


def test_assemble_model_snapshot_in_memory_panels():
    status = _minimal_status()
    in_mem = {"indices": {"NIFTY": {"dq_score": 33}}}
    snap, _ = assemble_model_snapshot(runtime_status=status, panels_dir=None, include_panels=True, in_memory_panels=in_mem)  # type: ignore[arg-type]
    names = {i.name: i.dq_score for i in snap.indices}
    assert names.get("NIFTY") == 33
