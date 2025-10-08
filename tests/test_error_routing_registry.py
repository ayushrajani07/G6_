from src.errors.error_routing import route_error, ERROR_REGISTRY, register_error, unregister_error
import time

class DummyLogger:
    def __init__(self):
        self.events = []
    def debug(self, m): self.events.append(('debug', m))
    def info(self, m): self.events.append(('info', m))
    def warning(self, m): self.events.append(('warning', m))
    def error(self, m): self.events.append(('error', m))
    def critical(self, m): self.events.append(('critical', m))

def test_registered_route_increments_and_logs(monkeypatch):
    logger = DummyLogger()
    class DummyMetric:
        def __init__(self): self.count = 0
        def labels(self, **lbls): return self
        def inc(self, n: int = 1): self.count += n
    class DummyMetrics:
        csv_mixed_expiry_dropped = DummyMetric()
    metrics = DummyMetrics()
    result = route_error('csv.mixed_expiry.prune', logger, metrics, index='NIFTY', dropped=5)
    assert result['registered']
    assert metrics.csv_mixed_expiry_dropped.count == 1
    assert any('csv.mixed_expiry.prune' in e[1] for e in logger.events)


def test_unregistered_route_falls_back_debug():
    logger = DummyLogger()
    result = route_error('unknown.code.example', logger)
    assert not result['registered']
    assert any(e[0]=='debug' and 'UNREGISTERED_ERROR' in e[1] for e in logger.events)


def test_escalation_env(monkeypatch):
    # Add temp entry with escalate env flag
    ERROR_REGISTRY['temp.test.escalate'] = {'log_level': 'info', 'escalate_env': 'TEST_ESCALATE_FLAG'}
    logger = DummyLogger()
    monkeypatch.setenv('TEST_ESCALATE_FLAG','1')
    result = route_error('temp.test.escalate', logger)
    # Should escalate from info -> warning
    assert result['log_level'] == 'warning'
    assert any(e[0]=='warning' for e in logger.events)
    # cleanup
    ERROR_REGISTRY.pop('temp.test.escalate', None)


def test_severity_and_throttling(monkeypatch):
    # Register a throttled route
    register_error('temp.test.throttle', log_level='warning', throttle_sec=1.0)
    logger = DummyLogger()
    r1 = route_error('temp.test.throttle', logger, foo='bar')
    r2 = route_error('temp.test.throttle', logger, foo='bar')  # should throttle
    assert r1['registered'] and r2['registered']
    assert r1['severity'] == 'medium'
    assert r2['throttled'] is True
    # Wait for throttle window expire
    time.sleep(1.05)
    r3 = route_error('temp.test.throttle', logger)
    assert r3['throttled'] is False
    unregister_error('temp.test.throttle')


def test_dynamic_registration_and_serialization():
    complex_obj = {'a': 1, 'b': [1,2,3]}
    register_error('temp.test.serialize', log_level='info', metric=None)
    logger = DummyLogger()
    r = route_error('temp.test.serialize', logger, complex=complex_obj)
    assert r['registered']
    # Ensure a log entry exists
    assert any('temp.test.serialize' in e[1] for e in logger.events)
    unregister_error('temp.test.serialize')
