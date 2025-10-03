import pytest
from importlib import reload

def invoke_scan():
    import src.orchestrator.bootstrap as b  # noqa: F401
    reload(b)
    # call helper explicitly for deterministic path
    b.run_env_deprecation_scan()

@pytest.mark.parametrize("allowlist,should_raise", [
    ("", True),
    ("G6_METRICS_ENABLE", False),
])
def test_strict_mode_enforcement(monkeypatch, allowlist, should_raise):
    # Precondition: ensure deprecated variable present
    monkeypatch.setenv('G6_METRICS_ENABLE', '1')  # deprecated (alias)
    monkeypatch.setenv('G6_ENV_DEPRECATION_STRICT', '1')
    if allowlist:
        monkeypatch.setenv('G6_ENV_DEPRECATION_ALLOW', allowlist)
    # Invoke scan helper (raises if violation)
    if should_raise:
        with pytest.raises(RuntimeError):
            invoke_scan()
    else:
        invoke_scan()  # should not raise
