import json
from pathlib import Path

import pytest

# Import the sanitizer and collector from the lint script
from scripts.lint_dashboard_promql import _sanitize_templated_expr, collect_promql_exprs


def test_sanitizer_replaces_grafana_vars():
    expr = (
        "$metric_hist:$q_5m / clamp_min($metric_hist:$q_30m, 0.001) + rate(up[$__interval]) "
        "+ $__range_s + $__interval_ms + $__rate_interval"
    )
    out = _sanitize_templated_expr(expr)
    # Recording rule suffixes normalized
    assert ":p95_5m" in out
    assert ":p95_30m" in out
    # Metric variables replaced
    assert "$metric_hist" not in out
    assert "$metric" not in out
    # Grafana time vars replaced
    assert "$__interval" not in out
    assert "$__range_s" not in out
    assert "$__interval_ms" not in out
    assert "$__rate_interval" not in out


def test_sanitizer_overlay_collapse():
    expr = (
        "(($overlay == 'fast') or ($overlay == \"ultra\")) * sum(rate(up[$__interval]))"
    )
    out = _sanitize_templated_expr(expr)
    # Overlay toggles collapsed to 0 (no dangling $overlay or boolean ops)
    assert "$overlay" not in out
    assert " or " not in out
    assert " and " not in out


def test_collect_exprs_with_sanitize(tmp_path: Path):
    # Build a minimal dashboard JSON with one templated and one plain expression
    dash = {
        "panels": [
            {
                "type": "timeseries",
                "title": "templated",
                "targets": [
                    {"expr": "$metric_hist:$q_5m"}
                ],
            },
            {
                "type": "timeseries",
                "title": "plain",
                "targets": [
                    {"expr": "sum(rate(up[5m]))"}
                ],
            },
        ]
    }
    ddir = tmp_path / "dash"
    ddir.mkdir()
    (ddir / "demo.json").write_text(json.dumps(dash))

    exprs = collect_promql_exprs(ddir, include_templated=True, sanitize_templated=True)
    # Should include sanitized templated expression (no $) and the plain one unchanged
    assert any("$" not in e and ":p95_5m" in e for e in exprs)
    assert any(e.strip() == "sum(rate(up[5m]))" for e in exprs)
