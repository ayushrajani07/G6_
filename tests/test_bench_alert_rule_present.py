from pathlib import Path
import re, yaml

ALERT_FILE = Path('prometheus_alerts.yml')


def test_bench_p95_alert_rule_present():
    text = ALERT_FILE.read_text(encoding='utf-8')
    assert 'BenchP95RegressionHigh' in text, 'Alert name missing'
    # Load YAML and inspect structure
    data = yaml.safe_load(text)
    found = False
    for grp in data.get('groups', []):
        for rule in grp.get('rules', []):
            if rule.get('alert') == 'BenchP95RegressionHigh':
                expr = rule.get('expr','')
                assert 'g6_bench_delta_p95_pct' in expr
                assert 'g6_bench_p95_regression_threshold_pct' in expr
                found = True
    assert found, 'BenchP95RegressionHigh rule not found in parsed YAML'
