"""Alias / normalization of metric names to match canonical spec.

This module ensures that counters required by the external spec which use
`*_total` suffix exist even if earlier runtime registration produced a
non-suffixed variant (historical naming). It creates the canonical collector
when missing and leaves legacy ones in place (spec phase tolerates extras).

Idempotent: safe to call multiple times.
"""
from __future__ import annotations

import logging
from collections.abc import MutableMapping
from typing import Any, cast

from prometheus_client import REGISTRY, Counter  # type: ignore

logger = logging.getLogger(__name__)

# Mapping: (attr_name, canonical_prom_name, legacy_prom_name)
_CANONICAL_COUNTERS = [
    ("panel_diff_writes", "g6_panel_diff_writes_total", "g6_panel_diff_writes"),
    ("panel_diff_truncated", "g6_panel_diff_truncated_total", "g6_panel_diff_truncated"),
    ("panel_diff_bytes_total", "g6_panel_diff_bytes_total", "g6_panel_diff_bytes"),
    ("panels_integrity_checks", "g6_panels_integrity_checks_total", "g6_panels_integrity_checks"),
    ("panels_integrity_failures", "g6_panels_integrity_failures_total", "g6_panels_integrity_failures"),
    ("adaptive_controller_actions", "g6_adaptive_controller_actions_total", "g6_adaptive_controller_actions"),
    # Stream gater governance counters (added during panels bridge unification). These ensure
    # legacy unsuffixed variants (if any were instantiated pre-spec) are mapped to *_total.
    ("stream_append", "g6_stream_append_total", "g6_stream_append"),
    ("stream_skipped", "g6_stream_skipped_total", "g6_stream_skipped"),
    ("stream_state_persist_errors", "g6_stream_state_persist_errors_total", "g6_stream_state_persist_errors"),
    ("stream_conflict", "g6_stream_conflict_total", "g6_stream_conflict"),
]


def ensure_canonical_counters(reg: Any) -> None:  # pragma: no cover - wiring + light mutation
    """Guarantee canonical *_total counters exist and registry attributes point to them.

    Behavior:
      * If canonical counter already registered: leave as-is.
      * If only legacy (short) name exists: create canonical counter and rebind registry attribute
        (preserving legacy collector under self._legacy_metrics[attr]).
      * For labeled counters, seed an initial zero-sample so global REGISTRY.collect() surfaces
        the metric family (tests enumerate names only).
    """
    names_map = cast(MutableMapping[str, Any], getattr(REGISTRY, "_names_to_collectors", {}))
    if not hasattr(reg, '_legacy_metrics'):
        try:
            reg._legacy_metrics = {}
        except Exception:  # pragma: no cover
            pass

    for attr, canonical, legacy in _CANONICAL_COUNTERS:
        try:
            canonical_exists = canonical in names_map
            legacy_exists = legacy in names_map
        except Exception:
            canonical_exists = False
            legacy_exists = False
        # Determine metric group from attr heuristic
        group_hint = 'panel_diff' if 'panel_diff' in attr else ('panels_integrity' if 'panels_integrity' in attr else ('adaptive_controller' if 'adaptive_controller' in attr else None))
        if group_hint and hasattr(reg, 'group_allowed'):
            try:
                if not reg.group_allowed(group_hint):  # type: ignore[attr-defined]
                    continue  # Skip alias creation for disabled group
            except Exception:
                pass
        if canonical_exists:
            # Ensure an attribute referencing canonical collector exists (prefer attr name for canonical)
            existing_attr_obj = getattr(reg, attr, None)
            canon_obj = names_map.get(canonical)
            if canon_obj is not None and (existing_attr_obj is None or getattr(existing_attr_obj,'_name','')!=canonical):
                try:
                    # Preserve legacy under legacy_<attr> if it differs
                    if existing_attr_obj is not None and getattr(existing_attr_obj,'_name','')==legacy:
                        try:
                            setattr(reg, f'legacy_{attr}', existing_attr_obj)
                        except Exception:
                            pass
                    setattr(reg, attr, canon_obj)
                except Exception:
                    pass
            # Also expose attr_total alias if not present AND attr does not already end with _total
            try:
                if not attr.endswith('_total') and not hasattr(reg, f'{attr}_total'):
                    setattr(reg, f'{attr}_total', canon_obj)
            except Exception:
                pass
            continue

        # Create canonical from legacy prototype (if available) or bare counter
        existing = getattr(reg, attr, None)
        labels: list[str] = []
        doc = canonical
        if existing is not None:
            try:
                doc = getattr(existing, '_documentation', canonical)
            except Exception:  # pragma: no cover
                pass
            try:
                if hasattr(existing, '_labelnames') and existing._labelnames:  # type: ignore[attr-defined]
                    labels = list(existing._labelnames)  # type: ignore[attr-defined]
            except Exception:
                labels = []
        try:
            if labels:
                new_counter = Counter(canonical, doc, labels)
            else:
                new_counter = Counter(canonical, doc)
        except ValueError:
            # Race: another path created it after check; recover reference
            nc = names_map.get(canonical)
            new_counter = cast(Any, nc)
        except Exception:
            continue

        if not isinstance(new_counter, Counter):
            continue

        # Seed a child sample for labeled counters by mirroring one legacy sample's label values if available
        try:
            if labels:
                legacy_obj = existing
                sample_labels = None
                # Attempt to extract one concrete set of labels from legacy collector internal samples
                if legacy_obj is not None:
                    try:
                        # _samples is a generator; advance first element to inspect label dict
                        gen = legacy_obj._samples()  # type: ignore[attr-defined]
                        first = next(gen, None)
                        if first and isinstance(first, tuple) and len(first) >= 3:
                            # tuple form: (name, labels_dict, value, ...)
                            sample_labels = first[1]
                    except Exception:
                        sample_labels = None
                if sample_labels and all(k in sample_labels for k in labels):
                    new_counter.labels(**{k: sample_labels[k] for k in labels}).inc(0)
                else:
                    placeholder = {l: 'init' for l in labels}
                    new_counter.labels(**placeholder).inc(0)
            else:
                new_counter.inc(0)
        except Exception:
            pass

        # Attach canonical: if existing legacy present, shift it to legacy_<attr>
        try:
            if existing is not None and getattr(existing,'_name','')==legacy:
                try:
                    reg._legacy_metrics[attr] = existing  # type: ignore[attr-defined]
                except Exception:
                    pass
                try:
                    setattr(reg, f'legacy_{attr}', existing)
                except Exception:
                    pass
            setattr(reg, attr, new_counter)
            # Only add attr_total alias if base attr is not already suffixed with _total
            if not attr.endswith('_total') and not hasattr(reg, f'{attr}_total'):
                setattr(reg, f'{attr}_total', new_counter)
        except Exception:
            pass
        # Ensure metric group tag retained (best-effort)
        try:
            if hasattr(reg, '_metric_groups') and attr in reg._metric_groups:
                # already tagged
                pass
            else:
                grp = 'panel_diff' if 'panel_diff' in attr else ('panels_integrity' if 'panels_integrity' in attr else 'adaptive_controller')
                reg._metric_groups[attr] = reg._metric_groups.get(attr, grp)  # type: ignore[attr-defined]
        except Exception:
            pass
        try:
            logger.debug("alias.ensure_canonical", extra={
                "attr": attr,
                "canonical": canonical,
                "legacy_present": legacy_exists,
                "labels": labels,
            })
        except Exception:
            pass

__all__ = ["ensure_canonical_counters"]
