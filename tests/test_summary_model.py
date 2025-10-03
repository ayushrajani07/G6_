from __future__ import annotations

from src.summary.model import SummarySnapshot, AlertEntry, IndexHealth
from src.summary.builder import build_summary_snapshot


def test_summary_snapshot_to_dict_round_trip():
    alerts = [
        {"code": "A1", "message": "Test alert", "severity": "WARN", "index": "NIFTY", "meta": {"k": 1}},
        {"code": "A2", "message": "Another", "severity": "INFO"},
    ]
    indices = {
        "NIFTY": {
            "status": "healthy",
            "last_update_epoch": 1234.5,
            "success_rate_percent": 95.0,
            "options_last_cycle": 150,
            "atm_strike": 22000,
            "iv_repr": 0.18,
            "meta": {"note": "ok"},
        },
        "BANKNIFTY": {
            "status": "degraded",
            "success_rate_percent": 80.0,
            "options_last_cycle": 75,
        },
    }

    snap = build_summary_snapshot(cycle=42, raw_alerts=alerts, raw_indices=indices, meta={"source": "unit"})
    d = snap.to_dict()  # type: ignore[assignment]

    # Basic structure checks
    assert d["cycle"] == 42
    alerts_list = list(d["alerts"])  # type: ignore[index]
    indices_list = list(d["indices"])  # type: ignore[index]
    assert len(alerts_list) == 2
    assert {a["code"] for a in alerts_list} == {"A1", "A2"}
    assert len(indices_list) == 2
    idx_map = {i["index"]: i for i in indices_list}
    assert idx_map["NIFTY"]["status"] == "healthy"
    assert idx_map["BANKNIFTY"]["status"] == "degraded"
    assert d["meta"]["source"] == "unit"  # type: ignore[index]

    # Ensure dataclass conversion stable
    # Reconstruct first alert
    first_alert = AlertEntry(**alerts_list[0])
    assert isinstance(first_alert, AlertEntry)

    # Reconstruct index health
    first_index = IndexHealth(**indices_list[0])
    assert isinstance(first_index, IndexHealth)
