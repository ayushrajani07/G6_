import os
from types import SimpleNamespace
from src.orchestrator.context import RuntimeContext  # type: ignore

def test_run_loop_respects_max_cycles(monkeypatch, tmp_path):
    # Import after setting env to ensure code picks up variable when run
    monkeypatch.setenv('G6_LOOP_MAX_CYCLES', '3')
    # Build a fake ctx with shutdown flag
    # Build minimal RuntimeContext; construct with dummy values if required by implementation
    # If RuntimeContext has required init signature, adapt here.
    try:
        ctx = RuntimeContext()  # type: ignore[call-arg]
    except Exception:
        # Fallback: fabricate object with expected attributes
        ctx = SimpleNamespace(shutdown=False)
    executed = {'count': 0}
    def cycle_fn(c):
        executed['count'] += 1
    from src.orchestrator.loop import run_loop
    run_loop(ctx, cycle_fn=cycle_fn, interval=0.0)  # type: ignore[arg-type]
    assert executed['count'] == 3


def test_run_orchestrator_loop_script_integration(monkeypatch):
    # Provide minimal env and config assumptions; bootstrap_runtime may need a config file.
    # If config path missing we skip (environment dependent). We just validate cycles env mapping.
    monkeypatch.setenv('G6_LOOP_MAX_CYCLES', '2')
    # Provide dummy modules to satisfy bootstrap import chain if heavy.
    # Instead of executing full script, ensure parse_args + ensure_env mapping path works.
    import scripts.run_orchestrator_loop as rol
    # Simulate argument parsing for cycles override
    ns = rol.parse_args(['--cycles','5'])
    # Clear env so ensure_env sets it
    monkeypatch.delenv('G6_LOOP_MAX_CYCLES', raising=False)
    rol.ensure_env(ns)
    assert os.environ.get('G6_LOOP_MAX_CYCLES') == '5'
