import os, time, pathlib
import pytest
from src.lifecycle.job import run_lifecycle_once
from src.metrics import setup_metrics_server

# Helper to set mtime in the past
_def_now = time.time()

def _backdate(path: pathlib.Path, days: float):
    ts = _def_now - days * 86400 - 10  # ensure strictly older
    os.utime(path, (ts, ts))

@pytest.fixture(autouse=True)
def _fixed_now(monkeypatch):
    # Freeze time.time() used inside lifecycle job for deterministic cutoff behavior
    monkeypatch.setenv('G6_LIFECYCLE_JOB','1')
    base_now = _def_now
    class _T:
        @staticmethod
        def time():
            return base_now
    monkeypatch.setattr('time.time', _T.time)
    yield

@pytest.fixture
def lifecycle_env(monkeypatch):
    monkeypatch.setenv('G6_ENABLE_METRIC_GROUPS','lifecycle')
    monkeypatch.setenv('G6_DISABLE_METRIC_GROUPS','')
    monkeypatch.setenv('G6_LIFECYCLE_COMPRESSION_EXT','.csv')
    monkeypatch.setenv('G6_LIFECYCLE_COMPRESSION_AGE_SEC','0')
    monkeypatch.setenv('G6_LIFECYCLE_MAX_PER_CYCLE','100')
    return monkeypatch


def test_retention_deletes_aged_gz(tmp_path, lifecycle_env):
    monkeypatch = lifecycle_env
    # retention: delete >1 day old
    monkeypatch.setenv('G6_LIFECYCLE_RETENTION_DAYS','1')
    monkeypatch.setenv('G6_LIFECYCLE_RETENTION_DELETE_LIMIT','100')
    metrics, _ = setup_metrics_server(reset=True)
    # Create gz files: two old, one fresh
    old1 = tmp_path / 'a.csv.gz'; old1.write_bytes(b'x')
    old2 = tmp_path / 'b.csv.gz'; old2.write_bytes(b'y')
    fresh = tmp_path / 'c.csv.gz'; fresh.write_bytes(b'z')
    _backdate(old1, 2)
    _backdate(old2, 3)
    # fresh keeps default _def_now timestamp
    run_lifecycle_once(str(tmp_path))
    # Expect old deleted, fresh kept
    assert not old1.exists() and not old2.exists()
    assert fresh.exists()
    counter = getattr(metrics, 'retention_files_deleted', None)
    assert counter is not None, 'retention metric missing'
    # New metrics: candidates gauge & scan histogram should exist
    assert hasattr(metrics, 'retention_candidates'), 'retention_candidates gauge missing'
    assert hasattr(metrics, 'retention_scan_seconds'), 'retention_scan_seconds histogram missing'


def test_retention_respects_limit(tmp_path, lifecycle_env):
    monkeypatch = lifecycle_env
    monkeypatch.setenv('G6_LIFECYCLE_RETENTION_DAYS','1')
    monkeypatch.setenv('G6_LIFECYCLE_RETENTION_DELETE_LIMIT','1')
    metrics, _ = setup_metrics_server(reset=True)
    old1 = tmp_path / 'd.csv.gz'; old1.write_bytes(b'x')
    old2 = tmp_path / 'e.csv.gz'; old2.write_bytes(b'y')
    _backdate(old1, 2)
    _backdate(old2, 2)
    run_lifecycle_once(str(tmp_path))
    # Only one should be deleted due to limit
    remaining = sum(1 for p in [old1, old2] if p.exists())
    assert remaining == 1


def test_retention_disabled_days_zero(tmp_path, lifecycle_env):
    monkeypatch = lifecycle_env
    monkeypatch.setenv('G6_LIFECYCLE_RETENTION_DAYS','0')
    metrics, _ = setup_metrics_server(reset=True)
    f = tmp_path / 'x.csv.gz'; f.write_bytes(b'x')
    _backdate(f, 10)
    run_lifecycle_once(str(tmp_path))
    assert f.exists(), 'File should not be deleted when retention disabled'


def test_retention_ignores_non_gz(tmp_path, lifecycle_env):
    """Verify retention does not delete non-gz files (and we disable compression so file persists)."""
    monkeypatch = lifecycle_env
    monkeypatch.setenv('G6_LIFECYCLE_RETENTION_DAYS','1')
    # Disable compression by using an extension that won't match .csv
    monkeypatch.setenv('G6_LIFECYCLE_COMPRESSION_EXT','.foo')
    metrics, _ = setup_metrics_server(reset=True)
    fplain = tmp_path / 'plain.csv'; fplain.write_bytes(b'x')
    _backdate(fplain, 5)
    run_lifecycle_once(str(tmp_path))
    assert fplain.exists(), 'Non-gz file must be untouched'
