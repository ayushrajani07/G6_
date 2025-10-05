import runpy
import os
import sys
from pathlib import Path
import importlib.util


def _import_benchmark_module():
    spec = importlib.util.spec_from_file_location("_bench_mod", Path('scripts') / 'benchmark_cycles.py')
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    assert spec and spec.loader
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


def test_benchmark_cycles_deprecation_info(caplog, tmp_path, monkeypatch):
    caplog.set_level("INFO")
    # Legacy per-script suppression removed; rely on unified suppress if needed
    mod = _import_benchmark_module()
    result = mod.run_benchmark(1, 0.1)  # type: ignore[attr-defined]
    assert result['cycles'] == 1
    msgs = "\n".join(m for _,_,m in caplog.record_tuples)
    # Updated deprecation banner text (2025-10-05 cleanup)
    assert 'benchmark_cycles.py -> use bench_tools.py' in msgs


def test_expiry_matrix_runs_without_legacy_fallback(monkeypatch):
    # Should execute without needing suppression var; legacy path removed
    # Force mock provider so the script does not attempt real broker auth
    monkeypatch.setenv('G6_USE_MOCK_PROVIDER', '1')
    runpy.run_path(str(Path('scripts') / 'expiry_matrix.py'), run_name='__main__')
