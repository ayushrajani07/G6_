"""Spec minimum fallback extraction.

Provides ensure_spec_minimum(registry) which was previously
MetricsRegistry._ensure_spec_minimum. Behavior and logging preserved.
"""
from __future__ import annotations

import logging
import os

from prometheus_client import REGISTRY

logger = logging.getLogger(__name__)

_SPEC_REQUIRED = [
    ('cache','root_cache_hits','g6_root_cache_hits','Root symbol cache hits','counter'),
    ('cache','root_cache_misses','g6_root_cache_misses','Root symbol cache misses','counter'),
    ('cache','root_cache_hit_ratio','g6_root_cache_hit_ratio','Root symbol cache hit ratio (0-1)','gauge'),
    ('panels_integrity','panels_integrity_ok','g6_panels_integrity_ok','Panels integrity OK (1/0)','gauge'),
    ('panels_integrity','panels_integrity_mismatches','g6_panels_integrity_mismatches','Cumulative panel hash mismatches','counter'),
]

def ensure_spec_minimum(registry) -> None:
    try:
        from prometheus_client import Counter as _C  # type: ignore
        from prometheus_client import Gauge as _G
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("Spec minimum import failed; prometheus_client missing? %s", e)
        return
    strict = os.getenv('G6_METRICS_STRICT_EXCEPTIONS','').lower() in {'1','true','yes','on'}
    for grp, attr, name, help_txt, kind in _SPEC_REQUIRED:
        if hasattr(registry, attr):
            continue
        ctor = _C if kind == 'counter' else _G
        inst = None
        try:
            inst = ctor(name, help_txt)
        except ValueError:
            try:
                names_map = getattr(REGISTRY, '_names_to_collectors', {})
                inst = names_map.get(name)
            except Exception as e:  # pragma: no cover
                logger.debug("Spec minimum lookup failed for %s: %s", name, e)
                inst = None
        except Exception as e:
            logger.error("Spec minimum creation failed for %s: %s", name, e, exc_info=True)
            if strict:
                raise
            inst = None
        if inst is not None:
            setattr(registry, attr, inst)
            try:
                registry._metric_groups[attr] = grp  # type: ignore[attr-defined]
            except Exception:
                pass
