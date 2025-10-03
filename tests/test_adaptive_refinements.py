import os, json, tempfile, time
from pathlib import Path
from src.orchestrator.status_writer import write_runtime_status
from src.metrics.cardinality_manager import get_cardinality_manager

class DummyProviders:
    primary_provider=None
    def get_ltp(self, idx): return 100.0
    def get_index_data(self, idx): return 100.0, None
class DummySink: ...
class DummyMetrics:
    def __init__(self):
        # simulate transitions full->band->agg to populate metadata
        self._adaptive_current_mode = 0
        self.runtime_status_writes = type('C', (), {'inc': lambda self: None})()
        self.runtime_status_last_write_unixtime = type('G', (), {'set': lambda self, v: None})()


def _emit_status(path: Path, metrics):
    write_runtime_status(
        path=str(path),
        cycle=metrics.__dict__.get('_adaptive_cycle_counter',0),
        elapsed=0.05,
        interval=1.0,
        index_params={'NIFTY': {}},
        providers=DummyProviders(),
        csv_sink=DummySink(), influx_sink=DummySink(), metrics=metrics,
        readiness_ok=True, readiness_reason='', health_monitor=None)


def test_hysteresis_metadata_exposed():
    from src.adaptive.logic import evaluate_and_apply
    with tempfile.TemporaryDirectory() as d:
        p = Path(d)/'status.json'
        # enable controller
        os.environ['G6_ADAPTIVE_CONTROLLER']='1'
        m = DummyMetrics()
        # simulate some cycles
        for _ in range(5):
            evaluate_and_apply(['NIFTY'])
        # Force demote path via synthetic pressure (set memory pressure level attr)
        setattr(m, 'memory_pressure_level', None)  # not used directly
        # direct state manip not needed; evaluate_and_apply already populates metrics singleton
    from src.metrics import get_metrics  # facade import
    gm = get_metrics()
    # ensure mode set
    _emit_status(p, gm)
    obj = json.load(open(p,'r',encoding='utf-8'))
    assert 'option_detail_mode_change_count' in obj
    assert 'option_detail_last_change_cycle' in obj


def test_band_window_rejection_counter():
    os.environ['G6_ADAPTIVE_CONTROLLER']='1'
    os.environ['G6_DETAIL_MODE_BAND_ATM_WINDOW']='2'
    from src.metrics import get_metrics  # facade import
    m = get_metrics()
    m._adaptive_current_mode = 1  # band  # type: ignore[attr-defined]
    cm = get_cardinality_manager()
    cm.set_metrics(m)
    # Accept near ATM
    assert cm.should_emit('NIFTY','2025-10-30',100, 'CE', atm_strike=100, value=1.0)
    # Reject far
    assert not cm.should_emit('NIFTY','2025-10-30',110, 'CE', atm_strike=100, value=1.0)
    # Collect counter
    found = False
    if hasattr(m,'option_detail_band_rejections'):
        for fam in m.option_detail_band_rejections.collect():  # type: ignore[attr-defined]
            for s in fam.samples:
                if s.name == 'g6_option_detail_band_rejections_total' and s.labels.get('index')=='NIFTY':
                    found = True
    assert found, 'band rejection counter not incremented'


def test_config_override_band_window(monkeypatch):
    # Clear env so config path is used
    if 'G6_DETAIL_MODE_BAND_ATM_WINDOW' in os.environ:
        del os.environ['G6_DETAIL_MODE_BAND_ATM_WINDOW']
    # monkeypatch config loader
    def fake_get_loaded_config():
        return {'adaptive': {'detail_mode': {'band_window': 4}}}
    import src.metrics.cardinality_manager as cm_mod
    monkeypatch.setattr(cm_mod, 'get_loaded_config', lambda : {'adaptive': {'detail_mode': {'band_window': 4}}}, raising=False)
    from src.metrics import get_metrics  # facade import
    m = get_metrics()
    m._adaptive_current_mode = 1  # type: ignore[attr-defined]
    cm = get_cardinality_manager()
    cm.set_metrics(m)
    # far strike 5 beyond ATM with window 4 -> reject
    assert not cm.should_emit('NIFTY','2025-10-30',105,'CE', atm_strike=100, value=1.0)
