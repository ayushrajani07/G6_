"""(Deprecated) Parity Harness for Unified Collectors.

Historical snapshot hashing and structural parity comparisons have been retired.
This module is now a thin compatibility shim so existing imports do not break.
`capture_parity_snapshot` now returns a reduced, order-normalized structure WITHOUT
embedding a hash, and `snapshot_hash` is retained as an alias that raises a
DeprecationWarning if invoked.

Removal rationale:
    * Pipeline vs legacy hashes diverged intentionally as architectures evolved.
    * Tests shifted to execution success / shape sanity instead of strict hash parity.
    * Retaining hash logic risked brittle drift failures and unnecessary maintenance.
"""
from __future__ import annotations

from typing import Any

from src.utils.deprecations import emit_deprecation  # type: ignore

# Public API -----------------------------------------------------------------
__all__ = ["capture_parity_snapshot", "snapshot_hash"]


def _stable_sorted_symbols(symbols: list[str]) -> list[str]:
    try:
        return sorted(symbols)
    except Exception:
        return list(symbols)


def snapshot_hash(struct: dict[str, Any]) -> str:  # pragma: no cover - legacy shim
    emit_deprecation(
        'parity_harness-snapshot_hash',
        'snapshot_hash is deprecated and returns a constant placeholder; remove calls.'
    )
    return 'deprecated-parity-hash'


def capture_parity_snapshot(unified_result: dict[str, Any]) -> dict[str, Any]:
    """Derive a parity snapshot from unified_collectors run_unified_collectors result.

    Expected input contract (subset used):
      unified_result = {
        'indices_struct_entry': {  # OR list if multi-index future
            'index': str,
            'expiries': [ { 'rule': .., 'expiry_date': .., 'status': .., 'options': int, 'strike_coverage': ?, 'field_coverage': ?, } ],
            'option_count': int,
            'status': str,
            ...
        },
        'pcr_snapshot': { expiry_code: value, ... } (if available)
      }
    The harness normalizes ordering and extracts only parity-relevant fields.
    """
    snapshot: dict[str, Any] = {
        'version': 4,  # v4: hash removed, module deprecated
        'indices': [],
        'meta': {'deprecated': True},
    }
    # Support both single-index and list future form
    indices_entries = []
    if 'indices_struct_entry' in unified_result:
        indices_entries = [unified_result['indices_struct_entry']]
    elif 'indices_struct' in unified_result:
        indices_entries = unified_result.get('indices_struct', [])
    elif 'indices' in unified_result and isinstance(unified_result.get('indices'), list):
        # Legacy shape fallback (pre modular summary naming)
        indices_entries = unified_result.get('indices', [])  # type: ignore[assignment]

    for entry in indices_entries:
        index_name = entry.get('index')
        expiries_out: list[dict[str, Any]] = []
        for e in entry.get('expiries', []):
            expiries_out.append({
                'rule': e.get('rule'),
                'expiry_date': e.get('expiry_date'),
                'status': e.get('status'),
                'options': e.get('options'),
                'strike_cov': e.get('strike_coverage'),
                'field_cov': e.get('field_coverage'),
                'partial_reason': e.get('partial_reason'),
            })
        # Sort expiries deterministically by (expiry_date, rule)
        expiries_out.sort(key=lambda r: (r.get('expiry_date') or '', r.get('rule') or ''))
        index_snapshot = {
            'index': index_name,
            'status': entry.get('status'),
            'option_count': entry.get('option_count'),
            'failures': entry.get('failures'),
            'attempts': entry.get('attempts'),
            'expiries': expiries_out,
        }
        snapshot['indices'].append(index_snapshot)

    # Sort indices alphabetically for determinism
    snapshot['indices'].sort(key=lambda r: r.get('index') or '')

    # Capture pcr snapshot (already a dict). Sort keys.
    pcr = unified_result.get('pcr_snapshot') or {}
    if isinstance(pcr, dict):
        snapshot['pcr'] = {k: pcr[k] for k in sorted(pcr.keys())}
    else:
        snapshot['pcr'] = {}

    # Attach snapshot_summary derived aggregates (alerts + partial_reason totals) if present
    snap_summary = unified_result.get('snapshot_summary')
    if isinstance(snap_summary, dict):
        # Alerts summary fields (prefixed alert_*) copied verbatim if numeric
        for k, v in snap_summary.items():
            if k.startswith('alert_') and isinstance(v, (int, float)):
                snapshot.setdefault('alerts', {})[k] = v
        pr_tot = snap_summary.get('partial_reason_totals')
        if isinstance(pr_tot, dict):
            # Normalize stable ordering
            snapshot['partial_reason_totals'] = {k: pr_tot[k] for k in sorted(pr_tot.keys())}
        # Optional grouped partial reasons (additive; env gate to allow rollback)
        if snap_summary.get('partial_reason_groups') and (
            str(__import__('os').environ.get('G6_PARITY_INCLUDE_REASON_GROUPS','1')).lower() in ('1','true','yes','on')
        ):
            groups = snap_summary.get('partial_reason_groups') or {}
            if isinstance(groups, dict):
                # Flatten group totals for parity diff (stable ordering by group name)
                flattened = {g: (groups.get(g) or {}).get('total', 0) for g in sorted(groups.keys())}
                snapshot['partial_reason_group_totals'] = flattened
                order = snap_summary.get('partial_reason_group_order') or []
                if isinstance(order, list):
                    snapshot['partial_reason_group_order'] = [o for o in order if o in groups]
    # Backfill a composite alerts_total if alerts present
    if 'alerts' in snapshot and isinstance(snapshot['alerts'], dict):
        snapshot['alerts_total'] = int(sum(v for v in snapshot['alerts'].values() if isinstance(v,(int,float))))
    # Derive simple strike coverage averages (if available on indices) for parity insight
    strike_avgs = []
    field_avgs = []
    for idx in unified_result.get('indices', []):
        sca = idx.get('strike_coverage_avg')
        fca = idx.get('field_coverage_avg')
        if isinstance(sca, (int, float)):
            strike_avgs.append(float(sca))
        if isinstance(fca, (int, float)):
            field_avgs.append(float(fca))
    if strike_avgs:
        snapshot['strike_coverage_avg_mean'] = sum(strike_avgs)/len(strike_avgs)
    if field_avgs:
        snapshot['field_coverage_avg_mean'] = sum(field_avgs)/len(field_avgs)
    # No hash attached (deprecated). Provide sentinel for downstream tolerant code.
    snapshot['hash'] = 'deprecated-parity-hash'
    return snapshot
