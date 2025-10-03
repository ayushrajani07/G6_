import json
import os
from pathlib import Path

from src.utils.build_info import compute_config_hash, compute_version, compute_git_commit, gather_build_info, auto_register_build_info
from src.metrics import setup_metrics_server  # facade import


def test_compute_config_hash_stable(tmp_path):
    cfg = {"b": 2, "a": {"z": 1, "y": 2}}
    h1 = compute_config_hash(cfg)
    # Reordered dict should produce same hash
    cfg_reordered = {"a": {"y": 2, "z": 1}, "b": 2}
    h2 = compute_config_hash(cfg_reordered)
    assert h1 == h2
    assert len(h1) == 16


def test_compute_version_env_override(monkeypatch):
    monkeypatch.setenv('G6_VERSION', '9.9.9-test')
    assert compute_version() == '9.9.9-test'


def test_compute_git_commit_env_override(monkeypatch):
    monkeypatch.setenv('G6_GIT_COMMIT', 'abcdef1234567890')
    assert compute_git_commit().startswith('abcdef1')


def test_gather_build_info_tuple(monkeypatch):
    monkeypatch.setenv('G6_VERSION', '1.0.1')
    monkeypatch.setenv('G6_GIT_COMMIT', '1234567')
    cfg = {"x": 1}
    v, gc, ch = gather_build_info(cfg)
    assert v == '1.0.1'
    assert gc.startswith('1234567')
    assert len(ch) == 16


def test_auto_register_build_info_integration(monkeypatch):
    metrics, _ = setup_metrics_server(reset=True)
    cfg = {"k": 1}
    auto_register_build_info(metrics, cfg)
    # Inspect registry for g6_build_info metric sample
    from prometheus_client import REGISTRY
    found = False
    for collector in list(getattr(REGISTRY, '_names_to_collectors', {}).values()):  # type: ignore[attr-defined]
        for metric in collector.collect():
            for sample in metric.samples:
                if sample.name == 'g6_build_info':
                    found = True
                    assert 'version' in sample.labels
                    assert 'git_commit' in sample.labels
                    assert 'config_hash' in sample.labels
    assert found
