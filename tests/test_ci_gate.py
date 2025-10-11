import json, textwrap, subprocess, sys

import scripts.ci_gate as ci_gate


def test_evaluate_pass():
    rep = ci_gate.evaluate(0.99, 0.01, min_parity=0.985, max_fatal=0.05)
    assert rep['status'] == 'pass'
    assert not any('threshold' in r for r in rep['reasons'])


def test_evaluate_fail_parity():
    rep = ci_gate.evaluate(0.90, 0.01, min_parity=0.985, max_fatal=0.05)
    assert rep['status'] == 'fail'
    assert any('parity_below_threshold' in r for r in rep['reasons'])


def test_evaluate_fail_fatal():
    rep = ci_gate.evaluate(0.99, 0.2, min_parity=0.985, max_fatal=0.05)
    assert rep['status'] == 'fail'
    assert any('fatal_ratio_above_threshold' in r for r in rep['reasons'])


def test_evaluate_missing_metrics_allow():
    rep = ci_gate.evaluate(None, None, min_parity=0.985, max_fatal=0.05)
    # Raw evaluation returns 'pass' because thresholds not violated; reasons include missing.
    assert rep['status'] == 'pass'
    assert 'parity_metric_missing' in rep['reasons']
    assert 'fatal_ratio_metric_missing' in rep['reasons']


def test_cli_pass(tmp_path):
    metrics = "# HELP g6_pipeline_parity_rolling_avg Rolling parity\n" \
              "g6_pipeline_parity_rolling_avg 0.992\n" \
              "g6:pipeline_fatal_ratio_15m 0.01\n"
    mf = tmp_path / 'metrics.txt'
    mf.write_text(metrics)
    proc = subprocess.run([sys.executable, '-m', 'scripts.ci_gate', '--metrics-file', str(mf), '--json'], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data['status'] == 'pass'


def test_cli_fail(tmp_path):
    metrics = "g6_pipeline_parity_rolling_avg 0.80\n" \
              "g6:pipeline_fatal_ratio_15m 0.10\n"
    mf = tmp_path / 'metrics.txt'
    mf.write_text(metrics)
    proc = subprocess.run([sys.executable, '-m', 'scripts.ci_gate', '--metrics-file', str(mf), '--json'], capture_output=True, text=True)
    assert proc.returncode == 1
    data = json.loads(proc.stdout)
    assert data['status'] == 'fail'
    assert any('parity_below_threshold' in r for r in data['reasons'])
    assert any('fatal_ratio_above_threshold' in r for r in data['reasons'])
