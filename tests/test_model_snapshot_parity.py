from __future__ import annotations
from src.summary.unified.model import assemble_model_snapshot

def test_model_snapshot_status_only():
    status = {
        "market": {"status": "open"},
        "loop": {"cycle": 12, "last_duration": 1.23, "success_rate": 97.5},
        "indices_detail": {
            "NIFTY": {"legs": 120, "dq": {"score_percent": 91.0, "issues_total": 0}},
            "BANKNIFTY": {"legs": 80, "dq": {"score_percent": 65.0, "issues_total": 2}},
        },
        "alerts": [ {"t": 1}, {"t":2} ],
    }
    model, diag = assemble_model_snapshot(runtime_status=status, panels_dir=None, include_panels=False)
    assert model.market_status == 'OPEN'
    assert model.cycle.number == 12
    assert len(model.indices) == 2
    # DQ groups: one green (91), one error (65 below 70)
    assert model.dq.green == 1
    assert model.dq.error == 1
    assert not diag.get('warnings')


def test_model_snapshot_dq_threshold_env_override(monkeypatch):  # type: ignore
    status = {
        "indices_detail": {
            "ONE": {"dq": {"score_percent": 72.0}},  # becomes warn if warn=90 err=60
            "TWO": {"dq": {"score_percent": 58.0}},  # below error threshold
            "THREE": {"dq": {"score_percent": 95.0}},
        }
    }
    monkeypatch.setenv('G6_DQ_WARN_THRESHOLD', '90')
    monkeypatch.setenv('G6_DQ_ERROR_THRESHOLD', '60')
    model, _ = assemble_model_snapshot(runtime_status=status, panels_dir=None, include_panels=False)
    assert model.dq.warn == 1  # ONE
    assert model.dq.error == 1  # TWO
    assert model.dq.green == 1  # THREE


def test_model_snapshot_adaptive_alerts_fallback():
    status = {"alerts": [{"a":1},{"a":2},{"a":3}]}
    model, _ = assemble_model_snapshot(runtime_status=status, panels_dir=None, include_panels=True)
    assert model.adaptive.alerts_total == 3
    assert model.provenance.get('adaptive') == 'status'
