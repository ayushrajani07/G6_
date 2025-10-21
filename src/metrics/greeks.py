"""Greek metrics extraction module.

Provides a function to initialize greek-related option metrics formerly
implemented inside `MetricsRegistry._init_greek_metrics` without changing
metric names, labels or grouping semantics.
"""
from collections.abc import Sequence

from prometheus_client import Gauge


def init_greek_metrics(registry, greek_names: Sequence[str] = ('delta','theta','gamma','vega','rho','iv')) -> None:
    """Attach greek option metrics to the provided registry instance.

    Parameters
    ----------
    registry : MetricsRegistry-like
        Instance expected to expose `_metric_groups` dict for grouping bookkeeping.
    greek_names : sequence of str
        Iterable of greek metric suffixes to register (default canonical set).
    """
    for greek in greek_names:
        metric_name = f"option_{greek}"
        if hasattr(registry, metric_name):  # idempotent guard
            continue
        g = Gauge(
            f'g6_option_{greek}',
            f'Option {greek}',
            ['index', 'expiry', 'strike', 'type']
        )
        setattr(registry, metric_name, g)
        try:
            registry._metric_groups[metric_name] = 'greeks'
        except Exception:
            pass
