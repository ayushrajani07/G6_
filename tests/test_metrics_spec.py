import os, json, yaml, importlib, pytest
from pathlib import Path
from prometheus_client import REGISTRY

# Minimal bootstrap: import metrics module to register core metrics
# Assumption: importing src.metrics.metrics triggers registration logic
metrics_module = importlib.import_module('src.metrics.metrics')  # noqa: F401
# Force metrics singleton instantiation (registers groups & cache metrics deterministically)
try:  # noqa: SIM105
    if hasattr(metrics_module, 'get_metrics_singleton'):
        metrics_module.get_metrics_singleton()
except Exception:  # pragma: no cover
    pass
# Ensure integrity monitor metrics (panels_integrity_*) are registered if spec references them.
try:  # noqa: SIM105
    importlib.import_module('src.panels.integrity_monitor')  # side effect: defines registration helper
except Exception:  # pragma: no cover
    pass

SPEC_PATH = Path('docs/metrics_spec.yaml')


def _collect_runtime_metric_names() -> set[str]:
    names = set()
    for fam in REGISTRY.collect():  # type: ignore[attr-defined]
        if fam.name.startswith('g6_'):
            names.add(fam.name)
    # Include canonical *_total counters that may have zero samples (not emitted yet) but are registered.
    try:
        internal = getattr(REGISTRY, '_names_to_collectors', {})
        for key, collector in internal.items():
            if key.startswith('g6_') and key.endswith('_total'):
                names.add(key)
    except Exception:
        pass
    return names


def test_metrics_spec_file_exists():
    assert SPEC_PATH.exists(), f"Missing metrics spec file: {SPEC_PATH}"


@pytest.mark.skipif(os.getenv('G6_EGRESS_FROZEN','').lower() in {'1','true','yes','on'}, reason='panel diff egress frozen affects spec surface')
def test_all_spec_metrics_present():
    """Each metric defined in metrics_spec.yaml must exist in runtime registry.

    Extra runtime metrics are tolerated (spec grows over time). This is Phase A guardrail.
    """
    spec_data = yaml.safe_load(SPEC_PATH.read_text(encoding='utf-8')) or []
    spec_names = {entry['name'] for entry in spec_data if 'name' in entry}
    runtime_names = _collect_runtime_metric_names()

    # Treat env-gated per-expiry vol surface metrics as optional unless flag enabled
    flag = os.getenv('G6_VOL_SURFACE_PER_EXPIRY') == '1'
    missing = []
    for name in sorted(spec_names - runtime_names):
        if (not flag) and name in { 'g6_vol_surface_rows_expiry' }:
            # Optional in absence of flag; documentation lists it but gating controls registration
            continue
        missing.append(name)
    assert not missing, (
        "Spec metrics missing from runtime registry (import side effects incomplete or name drift):\n" +
        "\n".join(missing)
    )


def test_metrics_spec_sorted_unique():
    raw_lines = SPEC_PATH.read_text(encoding='utf-8').splitlines()
    # Collect names in order they appear
    spec_data = yaml.safe_load(SPEC_PATH.read_text(encoding='utf-8')) or []
    names = [e['name'] for e in spec_data if 'name' in e]
    assert names == sorted(names), "Metric names in spec must be sorted alphabetically for deterministic diffs"
    assert len(names) == len(set(names)), "Duplicate metric names found in spec"


def test_metrics_spec_fields_minimal():
    spec_data = yaml.safe_load(SPEC_PATH.read_text(encoding='utf-8')) or []
    REQUIRED = {'name', 'type', 'labels', 'group', 'stability', 'description'}
    for entry in spec_data:
        missing = REQUIRED - set(entry.keys())
        assert not missing, f"Entry {entry.get('name')} missing required fields: {missing}"
        # Basic field shape checks
        assert isinstance(entry['name'], str) and entry['name'].startswith('g6_')
        assert entry['type'] in {'counter', 'gauge', 'histogram', 'summary'}
        assert isinstance(entry['labels'], list)
        assert entry['stability'] in {'experimental', 'beta', 'stable', 'deprecated'}
        assert isinstance(entry['description'], str) and entry['description'].strip(), "Description must be non-empty"
