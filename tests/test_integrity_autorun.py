import os, json, types, pathlib, sys
from src.orchestrator.context import RuntimeContext
from src.orchestrator.cycle import run_cycle

class DummyProviders:
    def get_index_data(self, idx):
        return 0.0, None

class DummyCSV: pass
class DummyInflux: pass

class DummyMetrics: pass


def test_integrity_auto_run(tmp_path, monkeypatch):
    # Provide minimal context with one index. RuntimeContext requires a config object;
    # supply an empty dict (only greeks key accessed optionally) and a schema-compliant
    # index params entry (expiry must be a date string per schema pattern, but since
    # run_cycle does not parse it we can still use a valid placeholder date).
    ctx = RuntimeContext(config={})
    ctx.index_params = {"NIFTY": {"enable": True, "expiries":["2025-12-31"], "strikes_itm":1, "strikes_otm":1}}
    ctx.providers = DummyProviders()
    ctx.csv_sink = DummyCSV()
    ctx.influx_sink = DummyInflux()
    ctx.metrics = DummyMetrics()
    # Inject a fake scripts.check_integrity module so the auto-run can succeed without the real script.
    import scripts as scripts_pkg  # use real package to avoid breaking subsequent tests
    fake_mod = types.ModuleType('scripts.check_integrity')
    def fake_main(argv=None):
        argv = argv or []
        out_path = None
        for i,a in enumerate(argv):
            if a == '--output' and i+1 < len(argv):
                out_path = argv[i+1]
        if out_path:
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, 'w', encoding='utf-8') as fh:
                json.dump({"missing_cycles":0, "ok":True}, fh)
    fake_mod.main = fake_main  # type: ignore[attr-defined]
    sys.modules['scripts.check_integrity'] = fake_mod
    # ensure logs directory under tmp path
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('G6_INTEGRITY_AUTO_RUN','1')
    monkeypatch.setenv('G6_INTEGRITY_AUTO_EVERY','1')  # every cycle
    # Create a fake events.log with a couple of cycle_start entries so integrity tool has content
    events_log = tmp_path / 'events.log'
    events_log.write_text('\n'.join([
        '{"event":"cycle_start","context":{"cycle":0}}',
        '{"event":"cycle_start","context":{"cycle":1}}'
    ]))
    # Run two cycles (modulus=1 triggers each time)
    run_cycle(ctx)  # type: ignore[arg-type]
    run_cycle(ctx)  # type: ignore[arg-type]
    out_path = tmp_path / 'logs' / 'integrity_auto.json'
    assert out_path.exists()
    data = json.loads(out_path.read_text())
    assert 'missing_cycles' in data  # basic shape assertion
