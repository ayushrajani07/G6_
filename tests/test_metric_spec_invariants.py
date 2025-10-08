import os

from src.metrics import isolated_metrics_registry  # facade import; legacy deep path deprecated
from src.metrics.spec import METRIC_SPECS


def test_metric_spec_invariants():
    """All metrics defined in METRIC_SPECS should be registered on registry.

    Validates: attribute exists, underlying collector has expected Prometheus name,
    and if a group is declared it is reflected in _metric_groups mapping.
    """
    prev_enable = os.environ.get("G6_ENABLE_METRIC_GROUPS")
    prev_disable = os.environ.get("G6_DISABLE_METRIC_GROUPS")
    try:
        # Neutralize gating to ensure spec groups present
        if prev_enable:
            os.environ["G6_ENABLE_METRIC_GROUPS"] = ""
        if prev_disable:
            os.environ["G6_DISABLE_METRIC_GROUPS"] = ""
        with isolated_metrics_registry() as reg:
            missing = []
            name_mismatch = []
            group_mismatch = []
            for spec in METRIC_SPECS:
                if not hasattr(reg, spec.attr):
                    missing.append(spec.attr)
                    continue
                collector = getattr(reg, spec.attr)
                metric_name = getattr(collector, "_name", None)
                if metric_name != spec.name:
                    name_mismatch.append((spec.attr, metric_name, spec.name))
                if spec.group is not None:
                    actual_group = reg._metric_groups.get(spec.attr)  # type: ignore[attr-defined]
                    expected = spec.group.value
                    if actual_group != expected:
                        group_mismatch.append((spec.attr, actual_group, expected))
            assert not missing, f"Spec metrics missing: {missing}"
            assert not name_mismatch, f"Name mismatches: {name_mismatch}"
            assert not group_mismatch, f"Group mismatches: {group_mismatch}"
    finally:
        if prev_enable is not None:
            os.environ["G6_ENABLE_METRIC_GROUPS"] = prev_enable
        if prev_disable is not None:
            os.environ["G6_DISABLE_METRIC_GROUPS"] = prev_disable
