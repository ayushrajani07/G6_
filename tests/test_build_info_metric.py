import re
from typing import Any
from prometheus_client import REGISTRY

from src.metrics import setup_metrics_server, register_build_info  # facade import


def _scrape_metrics_text():
    # Collect all metrics exposition text from default registry
    output = []
    for collector in list(getattr(REGISTRY, '_names_to_collectors', {}).values()):  # type: ignore[attr-defined]
        try:
            for metric in collector.collect():  # noqa: PLW2901
                # Build a simple exposition style line for gauge/counter/histogram samples
                for sample in metric.samples:
                    # sample: (name, labels, value, timestamp, exemplar, info)
                    name, labels, value = sample.name, sample.labels, sample.value
                    # Only keep build info lines
                    if name == 'g6_build_info':
                        label_str = ','.join(f"{k}='{v}'" for k, v in sorted(labels.items()))
                        output.append(f"{name}{{{label_str}}} {value}")
        except Exception:  # pragma: no cover - defensive
            pass
    return '\n'.join(sorted(output))


def test_build_info_registration_idempotent():
    metrics, _ = setup_metrics_server(use_custom_registry=False, reset=True)
    register_build_info(metrics, version="1.2.3", git_commit="abc1234", config_hash="deadbeef")
    # Second call with different (changed) values should overwrite labels by emitting a new time-series with same label set
    register_build_info(metrics, version="1.2.3", git_commit="abc1234", config_hash="deadbeef")
    text = _scrape_metrics_text()
    assert "g6_build_info{" in text
    # Ensure exactly one line for build info (idempotent - same label set reused)
    lines = [l for l in text.splitlines() if l.startswith('g6_build_info{')]
    assert len(lines) == 1, f"Expected single build_info line, got: {lines}"
    assert "version='1.2.3'" in lines[0]
    assert "git_commit='abc1234'" in lines[0]
    assert "config_hash='deadbeef'" in lines[0]
    assert lines[0].endswith(' 1') or lines[0].endswith(' 1.0')


def test_build_info_defaults_unknown_on_missing_values():
    metrics, _ = setup_metrics_server(use_custom_registry=False, reset=True)
    register_build_info(metrics)  # all None
    text = _scrape_metrics_text()
    assert "version='unknown'" in text
    assert "git_commit='unknown'" in text
    assert "config_hash='unknown'" in text


def test_build_info_partial_values_fill_unknown():
    metrics, _ = setup_metrics_server(use_custom_registry=False, reset=True)
    register_build_info(metrics, version="2.0")  # others None
    text = _scrape_metrics_text()
    assert "version='2.0'" in text
    assert "git_commit='unknown'" in text
    assert "config_hash='unknown'" in text


def test_build_info_re_registration_updates_labels():
    metrics, _ = setup_metrics_server(use_custom_registry=False, reset=True)
    register_build_info(metrics, version="1.0", git_commit="aaaa", config_hash="hash1")
    register_build_info(metrics, version="1.1", git_commit="bbbb", config_hash="hash2")
    text = _scrape_metrics_text()
    # Expect only the last set of labels present (same metric name/label set cardinality replaced)
    lines = [l for l in text.splitlines() if l.startswith('g6_build_info{')]
    assert len(lines) == 1
    assert "version='1.1'" in lines[0]
    assert "git_commit='bbbb'" in lines[0]
    assert "config_hash='hash2'" in lines[0]


def test_register_build_info_safe_when_metrics_missing():
    # Passing None should be a no-op without raising.
    register_build_info(None, version="x")  # Should not raise

    class Dummy:  # missing build_info attribute
        pass

    register_build_info(Dummy(), version="x")  # type: ignore[arg-type] - intentional robustness test
