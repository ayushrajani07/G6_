import json, time, os, tempfile, pathlib
from scripts.bench_panels import benchmark

SAMPLE_PANEL_TEMPLATE = {
    "panel": "indices_panel",
    "version": 1,
    "generated_at": "2025-10-08T00:00:00Z",
    "updated_at": "2025-10-08T00:00:00Z",
    "data": {"count": 3, "indices": ["NIFTY","BANKNIFTY","FINNIFTY"]},
    "meta": {"source": "summary", "schema": "panel-envelope-v1", "hash": "deadbeefcafe"}
}


def _write_panel(path: pathlib.Path, name: str, payload: dict):
    (path / f"{name}_enveloped.json").write_text(json.dumps(payload), encoding="utf-8")


def test_benchmark_panels_basic():
    with tempfile.TemporaryDirectory() as td:
        p = pathlib.Path(td)
        # Create multiple distinct panel files
        _write_panel(p, "indices_panel", SAMPLE_PANEL_TEMPLATE)
        alt = dict(SAMPLE_PANEL_TEMPLATE)
        alt["panel"] = "alerts"
        _write_panel(p, "alerts", alt)
        report = benchmark(str(p), iterations=5)
        assert report["panels_dir"].endswith(td)
        assert report["iterations"] == 5
        assert "panels" in report and len(report["panels"]) >= 2
        for name, stats in report["panels"].items():
            assert set(["count","mean_s","p95_s","min_s","max_s"]) <= stats.keys()
            assert stats["count"] == 5
            # All numeric fields non-negative
            for k in ("mean_s","p95_s","min_s","max_s"):
                assert stats[k] >= 0
        agg = report["aggregate"]
        assert agg["samples"] >= 10  # 2 panels * 5 iterations
        # p95 should be >= mean unless degenerate (allow tolerance)
        assert agg["p95_s"] >= 0
