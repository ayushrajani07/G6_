import os
from contextlib import contextmanager
from src.metrics import setup_metrics_server  # facade import
from src.adaptive.controller import record_controller_action, set_detail_mode

@contextmanager
def _isolated_env(**env):
    old = {k: os.environ.get(k) for k in env}
    try:
        for k,v in env.items():
            if v is None and k in os.environ:
                del os.environ[k]
            elif v is not None:
                os.environ[k] = str(v)
        yield
    finally:
        for k,v in old.items():
            if v is None and k in os.environ:
                del os.environ[k]
            elif v is not None:
                os.environ[k] = v


def test_adaptive_metrics_registration_and_update(tmp_path):
    # Enable group and controller flag
    with _isolated_env(G6_DISABLE_METRIC_GROUPS='', G6_ENABLE_METRIC_GROUPS='adaptive_controller', G6_ADAPTIVE_CONTROLLER='1'):
        metrics, _ = setup_metrics_server(reset=True)
        # Metrics should be present
        assert getattr(metrics, 'adaptive_controller_actions', None) is not None
        assert getattr(metrics, 'option_detail_mode', None) is not None
        # Emit some actions
        record_controller_action('sla_breach_streak','demote')
        record_controller_action('recovery','promote')
        set_detail_mode('NIFTY', 1)
        # We cannot easily read current value from the Gauge without internal access; rely on no exceptions


def test_adaptive_metrics_gated_by_group(tmp_path):
    # Disable the group explicitly
    with _isolated_env(G6_DISABLE_METRIC_GROUPS='adaptive_controller', G6_ADAPTIVE_CONTROLLER='1'):
        metrics, _ = setup_metrics_server(reset=True)
        assert getattr(metrics, 'adaptive_controller_actions', None) is None
        assert getattr(metrics, 'option_detail_mode', None) is None
