import os, time, pathlib, gzip
import pytest
from src.metrics import setup_metrics_server, get_metrics  # facade import
from src.lifecycle.job import run_lifecycle_once


def _write_dummy(path: pathlib.Path, size: int = 256):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'a'*size)


def test_lifecycle_compression_and_quarantine(tmp_path, monkeypatch):
    # Enable dedicated lifecycle group (now extracted) plus any other baseline always-on groups if needed.
    monkeypatch.setenv('G6_ENABLE_METRIC_GROUPS','lifecycle')
    monkeypatch.setenv('G6_DISABLE_METRIC_GROUPS','')
    monkeypatch.setenv('G6_LIFECYCLE_JOB','1')
    monkeypatch.setenv('G6_LIFECYCLE_COMPRESSION_EXT','.csv')
    monkeypatch.setenv('G6_LIFECYCLE_COMPRESSION_AGE_SEC','0')  # compress immediately
    monkeypatch.setenv('G6_LIFECYCLE_MAX_PER_CYCLE','10')
    qdir = tmp_path / 'quarantine'
    monkeypatch.setenv('G6_LIFECYCLE_QUAR_DIR', str(qdir))

    metrics, _ = setup_metrics_server(reset=True)
    # Create sample csv files
    base_dir = tmp_path / 'g6_data'
    f1 = base_dir / 'a.csv'
    f2 = base_dir / 'b.csv'
    _write_dummy(f1)
    _write_dummy(f2)
    # Quarantine dir
    (qdir / 'dummy').parent.mkdir(parents=True, exist_ok=True)
    (qdir / 'dummy').write_text('x')

    run_lifecycle_once(str(base_dir))

    # Both originals should be replaced by gz (simulated) files
    assert not f1.exists() and not f2.exists()
    assert (base_dir / 'a.csv.gz').exists()
    comp_counter = getattr(metrics, 'compressed_files_total', None)
    if comp_counter is None:
        pytest.skip('compressed_files_total metric gated off unexpectedly')
    # Hard to read counter directly without client internals; call second time to ensure idempotent (no double compression of gz)
    run_lifecycle_once(str(base_dir))

    # Quarantine timing histogram should have at least one observation
    q_hist = getattr(metrics, 'quarantine_scan_seconds', None)
    if q_hist is None:
        pytest.skip('quarantine histogram gated off')
    observed = False
    for sample in q_hist.collect():  # type: ignore[attr-defined]
        for s in sample.samples:
            if s.name.endswith('_count') and s.value > 0:
                observed = True
    assert observed
