import os, json, tempfile, time
from pathlib import Path

from src.metrics import get_metrics  # facade import
from src.adaptive.alerts import record_interpolation_fraction, record_risk_delta, record_bucket_util
from src.orchestrator.status_writer import write_runtime_status

class DummyProviders:
    primary_provider=None
    def get_ltp(self, idx): return 100.0
    def get_index_data(self, idx): return 100.0, None
class DummySink: ...


def _status(path: Path, metrics):
    write_runtime_status(
        path=str(path), cycle=metrics.__dict__.get('_adaptive_cycle_counter',0), elapsed=0.02,
        interval=1.0, index_params={'NIFTY': {}}, providers=DummyProviders(), csv_sink=DummySink(), influx_sink=DummySink(),
        metrics=metrics, readiness_ok=True, readiness_reason='', health_monitor=None)
    return json.load(open(path,'r',encoding='utf-8'))


def test_interpolation_guard_alert():
    os.environ['G6_INTERP_FRACTION_ALERT_THRESHOLD']='0.5'
    os.environ['G6_INTERP_FRACTION_ALERT_STREAK']='3'
    m = get_metrics()
    # Feed fractions: two below threshold should reset, then 3 above triggers alert
    record_interpolation_fraction('global', 0.4)
    record_interpolation_fraction('global', 0.55)
    record_interpolation_fraction('global', 0.60)
    # 3rd consecutive above threshold should trigger alert immediately
    alert = record_interpolation_fraction('global', 0.61)
    assert alert is not None and alert['type']=='interpolation_high'


def test_risk_delta_drift_alert():
    os.environ['G6_RISK_DELTA_DRIFT_PCT']='20'
    os.environ['G6_RISK_DELTA_DRIFT_WINDOW']='4'
    os.environ['G6_RISK_DELTA_STABLE_ROW_TOLERANCE']='0.05'
    m = get_metrics()
    # Simulate window of 4 builds with stable rows and growing delta
    record_risk_delta(1000.0, 200)
    record_risk_delta(1050.0, 202)  # within tolerance
    record_risk_delta(1100.0, 198)
    alert = record_risk_delta(1300.0, 199)  # ~30% increase from 1000 baseline -> alert
    assert alert is not None and alert['type']=='risk_delta_drift'


def test_bucket_util_low_streak_alert():
    os.environ['G6_RISK_BUCKET_UTIL_MIN']='0.7'
    os.environ['G6_RISK_BUCKET_UTIL_STREAK']='3'
    m = get_metrics()
    record_bucket_util(0.8)
    record_bucket_util(0.65)
    record_bucket_util(0.60)
    alert = record_bucket_util(0.55)
    assert alert is not None and alert['type']=='bucket_util_low'


def test_status_writer_includes_adaptive_alerts():
    # Trigger one interpolation alert to ensure status contains alerts list
    os.environ['G6_INTERP_FRACTION_ALERT_THRESHOLD']='0.5'
    os.environ['G6_INTERP_FRACTION_ALERT_STREAK']='2'
    m = get_metrics()
    record_interpolation_fraction('global', 0.6)  # streak 1
    record_interpolation_fraction('global', 0.65)  # streak 2 -> alert
    with tempfile.TemporaryDirectory() as d:
        p = Path(d)/'status.json'
        obj = _status(p, m)
        assert 'adaptive_alerts' in obj
        assert any(a.get('type')=='interpolation_high' for a in obj['adaptive_alerts'])
