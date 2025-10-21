"""Summary builder (Phase 2).

Pure transformation helpers converting raw runtime structures into the
`SummarySnapshot` domain model. This isolates presentation layers from
collection/adaptive logic.
"""
from __future__ import annotations

import time
from collections.abc import Iterable
from typing import Any

from .model import AlertEntry, IndexHealth, SummarySnapshot

__all__ = ["build_summary_snapshot"]

def build_summary_snapshot(
    *,
    cycle: int | None,
    raw_alerts: Iterable[dict[str, Any]] | None,
    raw_indices: dict[str, dict[str, Any]] | None,
    meta: dict[str, Any] | None = None,
) -> SummarySnapshot:
    """Construct a SummarySnapshot from untyped raw inputs.

    Parameters
    ----------
    cycle : int | None
        Current cycle number (if tracked) else None.
    raw_alerts : iterable of dict
        Each dict should contain at least 'code' and 'message'; optional 'severity', 'index', 'meta'.
    raw_indices : mapping index -> dict of fields (atm, iv, status, success_rate, options_last_cycle, last_update_epoch).
    meta : optional mapping of extra metadata.
    """
    alert_entries: list[AlertEntry] = []
    for a in (raw_alerts or []):
        if not isinstance(a, dict):
            continue
        code = str(a.get('code', 'UNKNOWN'))
        msg = str(a.get('message', ''))
        severity = str(a.get('severity', 'INFO'))
        alert_entries.append(
            AlertEntry(
                code=code,
                message=msg,
                severity=severity,
                index=a.get('index'),
                meta={k: v for k, v in a.get('meta', {}).items()} if isinstance(a.get('meta'), dict) else {},
            )
        )

    index_entries: list[IndexHealth] = []
    now = time.time()
    for name, spec in (raw_indices or {}).items():
        if not isinstance(spec, dict):
            continue
        status = str(spec.get('status', 'unknown'))
        idx_health = IndexHealth(
            index=name,
            status=status,
            last_update_epoch=float(spec.get('last_update_epoch', now)),
            success_rate_percent=(
                float(spec['success_rate_percent']) if isinstance(spec.get('success_rate_percent'), (int, float)) else None
            ),
            options_last_cycle=int(spec['options_last_cycle']) if isinstance(spec.get('options_last_cycle'), (int, float)) else None,
            atm_strike=float(spec['atm_strike']) if isinstance(spec.get('atm_strike'), (int, float)) else None,
            iv_repr=float(spec['iv_repr']) if isinstance(spec.get('iv_repr'), (int, float)) else None,
            meta={k: v for k, v in spec.get('meta', {}).items()} if isinstance(spec.get('meta'), dict) else {},
        )
        index_entries.append(idx_health)

    return SummarySnapshot(
        generated_epoch=time.time(),
        cycle=cycle,
        alerts=alert_entries,
        indices=index_entries,
        meta=meta or {},
    )
