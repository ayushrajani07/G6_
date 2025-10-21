"""Phase 1: Collector context & types.

This introduces a stable typed context object that future phases will pass
through pipeline functions. For Phase 1 we deliberately avoid moving logic
out of `unified_collectors.py`; we only define structures and (optionally)
lightweight helpers. No behavioral changes expected.
"""
from __future__ import annotations

import datetime
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CollectorConfig:
    """Parsed configuration subset required by collector modules.

    In Phase 1 this is a thin placeholder. Future phases may expand this with
    strike depth defaults, adaptive thresholds, synthetic strategy toggles, etc.
    """
    raw: Mapping[str, Any]

    def get_index(self, symbol: str) -> Mapping[str, Any]:  # convenience
        return self.raw.get(symbol, {})


@dataclass
class MetricsSink:
    """Opaque metrics sink wrapper.

    We don't rely on concrete Prometheus client types here to keep coupling low.
    Attributes are accessed reflectively (mirroring current code style).
    """
    impl: Any

    def __getattr__(self, item: str) -> Any:  # passthrough (best-effort)
        return getattr(self.impl, item)


@dataclass
class CollectorContext:
    env: Mapping[str, str]
    now: datetime.datetime
    indices: list[str]
    config: CollectorConfig
    logger: logging.Logger
    metrics: Any | None = None
    debug: bool = False
    # Phase 1: allow attaching transient state dictionaries (mutable) for legacy code interop.
    state: dict[str, Any] = field(default_factory=dict)

    def child(self, **overrides: Any) -> CollectorContext:
        """Create a shallow-override derivative context.
        Safe because `config` and other heavy objects are shared (immutable contract).
        """
        data: dict[str, Any] = {
            'env': self.env,
            'now': self.now,
            'indices': self.indices,
            'config': self.config,
            'logger': self.logger,
            'metrics': self.metrics,
            'debug': self.debug,
            'state': self.state,
        }
        data.update(overrides)
        return CollectorContext(**data)


# Helper for building a default context from existing runtime inputs (Phase 1 only)

def build_collector_context(index_params: Mapping[str, Any], metrics: Any | None, *, debug: bool = False) -> CollectorContext:
    import os
    return CollectorContext(
        env=dict(os.environ),
        now=datetime.datetime.now(datetime.UTC),
        indices=list(index_params.keys()),
        config=CollectorConfig(raw=index_params),
        logger=logging.getLogger('collectors.context'),
        metrics=metrics,
        debug=debug,
    )
