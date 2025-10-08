"""Conformance test for docs/metrics_spec.yaml.

Phase A Governance Rules:
  * Every metric listed in the YAML spec must exist after importing src.metrics
    (creating a MetricsRegistry()) with matching type and label keys.
  * Extra runtime metrics are allowed (no failure on superset).
  * Aliases that map to already declared Prometheus names should be omitted from YAML.

Failure Messaging Goals:
  * Provide precise guidance: missing metrics, type mismatches, label deltas.
  * Keep output stable/deterministic for CI diffing.
"""
from __future__ import annotations

import pathlib
import os
import inspect
import pytest
from typing import Any

import yaml  # type: ignore
import prometheus_client  # type: ignore

# Import package; registry variable exported in __all__ (may be None if init failed)
import src.metrics as metrics_pkg  # type: ignore

SPEC_PATH = pathlib.Path(__file__).resolve().parent.parent / 'docs' / 'metrics_spec.yaml'


def load_spec() -> list[dict[str, Any]]:
    data = yaml.safe_load(SPEC_PATH.read_text(encoding='utf-8'))
    if isinstance(data, list):
        return data  # top-level list format
    if isinstance(data, dict) and 'metrics' in data and isinstance(data['metrics'], list):
        return data['metrics']
    raise AssertionError(f"Unsupported spec structure: {type(data)}")


def _collector_family(metric_obj) -> str:
    # Prometheus python client types: Counter, Gauge, Summary, Histogram
    # Use class name lower-case mapping for human readable comparison.
    cls_name = metric_obj.__class__.__name__.lower()
    if 'counter' in cls_name:
        return 'counter'
    if 'gauge' in cls_name:
        return 'gauge'
    if 'summary' in cls_name:
        return 'summary'
    if 'histogram' in cls_name:
        return 'histogram'
    # Some wrappers (e.g., _MultiProcessCollector) might layer — fallback to repr sniff.
    r = repr(metric_obj).lower()
    for key in ('counter', 'gauge', 'summary', 'histogram'):
        if key in r:
            return key
    return 'unknown'


def _labels_from_collector(metric_obj) -> list[str]:
    # prometheus_client stores labelnames on _labelnames for Gauge/Counter/etc.
    try:
        names = list(getattr(metric_obj, '_labelnames', []))
    except Exception:
        names = []
    # Exclude internal 'quantile' for summaries and 'le' for histograms — those are sample labels.
    return [n for n in names if n not in {'quantile', 'le'}]


@pytest.mark.skipif(os.getenv('G6_EGRESS_FROZEN','').lower() in {'1','true','yes','on'}, reason='panel diff egress frozen affects spec surface')
def test_metrics_spec_conformance():  # noqa: C901 (intentional thoroughness)
    spec_metrics = load_spec()
    # Acquire registry (import side effect initializes metrics). If missing, fail early.
    reg = getattr(metrics_pkg, 'registry', None)
    if reg is None:
        # Eager singleton may be disabled under pytest; force initialization
        try:
            get_singleton = getattr(metrics_pkg, 'get_metrics_singleton', None)
            if callable(get_singleton):
                reg = get_singleton()
        except Exception:
            pass
    assert reg is not None, "metrics registry not initialized / exported (attempted lazy init)"

    # Build index: prometheus metric name -> object (first match wins)
    # Metrics registered via spec.py are attributes on registry with their attr names.
    name_to_obj: dict[str, Any] = {}
    for attr, value in vars(reg).items():
        if attr.startswith('_'):
            continue
        # Filter for prometheus client core metric types
        mod = inspect.getmodule(value)
        if mod and mod.__name__.startswith('prometheus_client'):
            # Attempt to get the canonical metric name
            prom_name = getattr(value, '_name', None)
            if not prom_name:
                # Some wrappers use ._metric._name
                prom_name = getattr(getattr(value, '_metric', object()), '_name', None)
            if prom_name:
                name_to_obj.setdefault(prom_name, value)

    # Supplement with internal registry collectors (covers *_total canonical counters
    # that may not be bound to public attributes due to legacy alias overshadowing).
    try:  # pragma: no cover - defensive
        from prometheus_client import REGISTRY as _R
        internal = getattr(_R, '_names_to_collectors', {})
        for cname, collector in internal.items():
            if cname.startswith('g6_'):
                name_to_obj.setdefault(cname, collector)
    except Exception:
        pass

    missing: list[str] = []
    type_mismatch: list[str] = []
    label_mismatch: list[str] = []

    flag = os.getenv('G6_VOL_SURFACE_PER_EXPIRY') == '1'
    for entry in spec_metrics:
        name = entry['name']
        expected_type = entry['type']
        expected_labels = entry.get('labels') or []

        obj = name_to_obj.get(name)
        if obj is None and (not flag) and name in {'g6_vol_surface_rows_expiry'}:
            # Skip optional env-gated metric when flag disabled
            continue
        if obj is None:
            missing.append(name)
            continue

        actual_type = _collector_family(obj)
        if actual_type != expected_type:
            type_mismatch.append(f"{name}: expected {expected_type} got {actual_type}")

        actual_labels = _labels_from_collector(obj)
        if list(expected_labels) != list(actual_labels):
            label_mismatch.append(
                f"{name}: expected labels {expected_labels} got {actual_labels}"
            )

    msgs = []
    if missing:
        msgs.append("Missing metrics: " + ", ".join(sorted(missing)))
    if type_mismatch:
        msgs.append("Type mismatches: " + "; ".join(sorted(type_mismatch)))
    if label_mismatch:
        msgs.append("Label mismatches: " + "; ".join(sorted(label_mismatch)))

    if msgs:
        raise AssertionError("Spec conformance failures:\n" + "\n".join(msgs))


if __name__ == '__main__':  # Manual debug helper
    try:
        test_metrics_spec_conformance()
        print("All spec metrics present and conformant.")
    except AssertionError as e:
        print(str(e))
        raise
