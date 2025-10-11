import yaml
import re
from pathlib import Path

RULES = Path("prometheus_rules.yml")
ALERT_NAME = "BenchP95RegressionHigh"
EXPR_PATTERN = re.compile(r"g6_bench_delta_p95_pct\s*>\s*g6_bench_p95_regression_threshold_pct.*g6_bench_p95_regression_threshold_pct\s*>?=\s*0")


def _load_rules():
    with RULES.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_bench_p95_regression_alert_present():
    doc = _load_rules()
    for group in doc.get("groups", []):
        for rule in group.get("rules", []):
            if rule.get("alert") == ALERT_NAME:
                expr = rule.get("expr", "")
                assert EXPR_PATTERN.search(expr), f"Expression mismatch: {expr}"
                # Duration expectation: for: 5m
                assert rule.get("for") == "5m", "Alert should use for: 5m"
                return
    assert False, f"Alert {ALERT_NAME} not found in prometheus_rules.yml"
