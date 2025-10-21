"""Standardized panel builders.

This module centralizes construction of per-panel JSON payloads from the
unified StatusReader, so that scripts (bridge/updater) and UIs rely on a
single source of truth for panel shapes and derivations.
"""
from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any, cast

from src.panels.models import (
    IndicesStreamItem,
    IndicesSummaryPanel,
    LoopPanel,
    PanelsDict,
    ProviderPanel,
    ResourcesPanel,
)
from src.utils.status_reader import StatusReader


def _derive_indices_from_status(status: dict[str, Any] | None) -> list[str]:
    if not status:
        return []
    indices = status.get("indices") or status.get("symbols") or []
    if isinstance(indices, str):
        return [s.strip() for s in indices.split(",") if s.strip()]
    if isinstance(indices, list):
        return [str(s) for s in indices]
    if isinstance(indices, dict):
        return [str(k) for k in indices.keys()]
    return []


def _derive_cycle_from_status(status: dict[str, Any] | None) -> dict[str, Any]:
    d: dict[str, Any] = {"cycle": None, "last_start": None, "last_duration": None, "success_rate": None}
    if not status:
        return d
    cycle = status.get("cycle") or status.get("last_cycle")
    if isinstance(cycle, (int, float)):
        d["cycle"] = int(cycle)
    elif isinstance(cycle, dict):
        d["cycle"] = cycle.get("number")
        d["last_start"] = cycle.get("start")
        d["last_duration"] = cycle.get("duration")
        d["success_rate"] = cycle.get("success_rate")
    loop = status.get("loop") if status else None
    if isinstance(loop, dict):
        d["cycle"] = d["cycle"] or loop.get("cycle") or loop.get("number")
        d["last_start"] = d["last_start"] or loop.get("last_run") or loop.get("last_start")
        d["last_duration"] = d["last_duration"] or loop.get("last_duration")
        d["success_rate"] = d["success_rate"] or loop.get("success_rate")
    d["last_start"] = d["last_start"] or status.get("last_cycle_start")
    d["last_duration"] = d["last_duration"] or status.get("last_cycle_duration")
    return d


def build_provider_panel(reader: StatusReader, status: dict[str, Any] | None) -> ProviderPanel:
    prov_raw = reader.get_provider_data() or {}
    if (not prov_raw) and status and isinstance(status.get("provider"), dict):
        prov_raw = cast(dict[str, Any], status.get("provider"))
    prov = prov_raw if isinstance(prov_raw, dict) else {}
    out: ProviderPanel = {"name": None, "auth": None, "expiry": None, "latency_ms": None}
    try:
        if isinstance(prov, dict):
            out["name"] = prov.get("name") or prov.get("primary")
            auth = prov.get("auth") or prov.get("token") or {}
            if isinstance(auth, dict):
                out["auth"] = auth.get("valid")
                out["expiry"] = auth.get("expiry")
            out["latency_ms"] = prov.get("latency_ms")
    except Exception:
        pass
    return out


def build_resources_panel(reader: StatusReader, status: dict[str, Any] | None) -> ResourcesPanel:
    res = reader.get_resources_data() or {}
    out: ResourcesPanel = {}
    if isinstance(res, dict) and res:
        return cast(ResourcesPanel, res)
    # Fallback to psutil (matches previous script implementation)
    try:
        import psutil  # optional dependency
    except Exception:  # pragma: no cover
        psutil = None
    if psutil:
        try:
            out["cpu"] = psutil.cpu_percent(interval=None)
            proc = psutil.Process()
            out["rss"] = proc.memory_info().rss
        except Exception:
            pass
    return out


def build_loop_panel(reader: StatusReader, status: dict[str, Any] | None) -> LoopPanel:
    cy = reader.get_cycle_data() or _derive_cycle_from_status(status)
    loop_payload: LoopPanel = {}
    if isinstance(cy, dict):
        v_cycle = cy.get("cycle")
        if isinstance(v_cycle, (int, float)):
            loop_payload["cycle"] = int(v_cycle)
        v_last_start = cy.get("last_start")
        if isinstance(v_last_start, str):
            loop_payload["last_start"] = v_last_start
        v_last_duration = cy.get("last_duration")
        if isinstance(v_last_duration, (int, float)):
            loop_payload["last_duration"] = float(v_last_duration)
        v_success = cy.get("success_rate")
        if isinstance(v_success, (int, float)):
            loop_payload["success_rate"] = float(v_success)
    return loop_payload


def build_health_panel(reader: StatusReader, status: dict[str, Any] | None) -> dict[str, Any]:
    h = reader.get_health_data() or {}
    return h  # passthrough


def build_indices_summary(reader: StatusReader, status: dict[str, Any] | None) -> IndicesSummaryPanel:
    # Prefer unified indices data, but merge/fallback to runtime_status.indices_detail
    indices_detail = reader.get_indices_data() or {}
    if (not isinstance(indices_detail, dict)) or not indices_detail:
        indices_detail = {}
    # Runtime status fallback that may contain richer metrics (legs/dq)
    rs_detail: dict[str, Any] = {}
    if isinstance(status, dict):
        det = status.get("indices_detail")
        if isinstance(det, dict):
            rs_detail = det
    # Build full index list from any available source
    indices = list(indices_detail.keys()) if isinstance(indices_detail, dict) and indices_detail else (
        list(rs_detail.keys()) if isinstance(rs_detail, dict) and rs_detail else _derive_indices_from_status(status)
    )
    index_metrics: dict[str, dict[str, Any]] = {}
    for idx in indices:
        row: dict[str, Any] = {"status": "OK"}
        try:
            det_primary = indices_detail.get(idx) if isinstance(indices_detail, dict) else None
            det_fallback = rs_detail.get(idx) if isinstance(rs_detail, dict) else None
            # Legs: prefer per-expiry sum first (per-cycle), then explicit current_cycle_legs,
            # then other cumulative fallbacks. Pick from primary first, else fallback.
            def _copy_legs(src: dict[str, Any] | None) -> bool:
                if isinstance(src, dict):
                    # 1) Sum across expiries breakdown if provided (most accurate per-cycle view)
                    try:
                        ex = src.get("expiries")
                        if isinstance(ex, dict):
                            s = 0
                            got = False
                            for _ek, _ev in ex.items():
                                if isinstance(_ev, dict):
                                    _lv = _ev.get("legs")
                                    if isinstance(_lv, (int, float)):
                                        s += int(_lv)
                                        got = True
                            if got:
                                row["legs"] = s
                                return True
                    except Exception:
                        pass
                    # 2) Prefer metrics-derived current_cycle_legs if present
                    v_cyc = src.get("current_cycle_legs")
                    if isinstance(v_cyc, (int, float)):
                        row["legs"] = int(v_cyc)
                        return True
                    # 3) Other cumulative fallbacks
                    for k in ("legs", "legs_total", "options", "options_count", "count"):
                        v = src.get(k)
                        if isinstance(v, (int, float)):
                            row["legs"] = int(v)
                            return True
                return False
            if not _copy_legs(det_primary):
                _copy_legs(det_fallback)
            # DQ: copy score and issues when present from whichever has them
            def _copy_dq(src: dict[str, Any] | None) -> None:
                if isinstance(src, dict):
                    dq = src.get("dq")
                    if isinstance(dq, dict):
                        if row.get("dq_score") is None and dq.get("score_percent") is not None:
                            row["dq_score"] = dq.get("score_percent")
                        if row.get("dq_issues") is None and dq.get("issues_total") is not None:
                            row["dq_issues"] = dq.get("issues_total")
            _copy_dq(det_primary)
            _copy_dq(det_fallback)
        except Exception:
            pass
        index_metrics[str(idx)] = row
    return cast(IndicesSummaryPanel, index_metrics)


def build_indices_stream_items(reader: StatusReader, status: dict[str, Any] | None) -> list[IndicesStreamItem]:
    items: list[IndicesStreamItem] = []
    # Prefer unified indices data, but merge/fallback to runtime_status.indices_detail for richer metrics
    indices_detail = reader.get_indices_data() or {}
    if (not isinstance(indices_detail, dict)) or not indices_detail:
        indices_detail = {}
    rs_detail: dict[str, Any] = {}
    if isinstance(status, dict):
        det = status.get("indices_detail")
        if isinstance(det, dict):
            rs_detail = det
    # Build full index list from any available source
    indices = list(indices_detail.keys()) if isinstance(indices_detail, dict) and indices_detail else (
        list(rs_detail.keys()) if isinstance(rs_detail, dict) and rs_detail else _derive_indices_from_status(status)
    )
    now_ts = time.time()
    # Merge cycle info from reader with richer status-derived fields
    cy_reader = reader.get_cycle_data() or {}
    cy_status = _derive_cycle_from_status(status)
    cy: dict[str, Any] = {}
    if isinstance(cy_status, dict):
        cy.update(cy_status)
    if isinstance(cy_reader, dict):
        # Reader wins for explicit values, but keep status fields when reader lacks them
        for k, v in cy_reader.items():
            if v is not None:
                cy[k] = v
    cur_cycle = None
    try:
        cur_cycle = cy.get("cycle") if isinstance(cy, dict) else None
    except Exception:
        cur_cycle = None
    success_rate_int: int | None = None
    try:
        sr = None
        _sr_val = cy.get("success_rate") if isinstance(cy, dict) else None
        if isinstance(_sr_val, (int, float)):
            sr = float(_sr_val)
        elif isinstance(status, dict):
            _sr2 = status.get("success_rate_pct")
            if isinstance(_sr2, (int, float)):
                sr = float(_sr2)
        if sr is not None:
            success_rate_int = int(round(sr))
    except Exception:
        success_rate_int = None
    avg_sec_default: float | None = None
    try:
        _dur = cy.get("last_duration") if isinstance(cy, dict) else None
        if isinstance(_dur, (int, float)):
            avg_sec_default = float(_dur)
        elif isinstance(status, dict):
            loop = status.get("loop")
            if isinstance(loop, dict):
                _ms = loop.get("avg_cycle_ms")
                if isinstance(_ms, (int, float)):
                    avg_sec_default = float(_ms) / 1000.0
    except Exception:
        avg_sec_default = None

    for idx in indices:
        item: IndicesStreamItem = {
            "index": str(idx),
            "status": "OK",
        }
        if isinstance(cur_cycle, (int, float)):
            try:
                item["cycle"] = int(cur_cycle)
            except Exception:
                pass
        try:
            item["time"] = datetime.fromtimestamp(now_ts, tz=UTC).isoformat().replace("+00:00", "Z")
        except Exception:
            pass
        try:
            det_primary = indices_detail.get(idx) if isinstance(indices_detail, dict) else None
            det_fallback = rs_detail.get(idx) if isinstance(rs_detail, dict) else None
            def _copy_legs(src: dict[str, Any] | None) -> bool:
                if isinstance(src, dict):
                    # 1) Sum across expiries breakdown when available (most accurate per-cycle view)
                    try:
                        ex = src.get("expiries")
                        if isinstance(ex, dict):
                            s = 0
                            got = False
                            for _ek, _ev in ex.items():
                                if isinstance(_ev, dict):
                                    _lv = _ev.get("legs")
                                    if isinstance(_lv, (int, float)):
                                        s += int(_lv)
                                        got = True
                            if got:
                                item["legs"] = s
                                return True
                    except Exception:
                        pass
                    # 2) Prefer metrics-derived current_cycle_legs if present
                    v_cyc = src.get("current_cycle_legs")
                    if isinstance(v_cyc, (int, float)):
                        item["legs"] = int(v_cyc)
                        return True
                    # 3) Other cumulative fallbacks
                    for k in ("legs", "legs_total", "options", "options_count", "count"):
                        v = src.get(k)
                        if isinstance(v, (int, float)):
                            item["legs"] = int(v)
                            return True
                return False
            if not _copy_legs(det_primary):
                _copy_legs(det_fallback)
        except Exception:
            pass
        # Note: avg_sec_default already float if set
        if isinstance(avg_sec_default, (int, float)):
            item["avg"] = round(float(avg_sec_default), 3)
        if isinstance(success_rate_int, int):
            item["success"] = success_rate_int
        # Compute status and reason via shared helper.
        # IMPORTANT: If you change thresholds/logic, update src/panels/helpers.py
        # and accompanying tests (tests/test_panels_helpers.py) to keep behavior consistent.
        try:
            from .helpers import compute_status_and_reason  # local import to avoid cycles
            legs_val = item.get("legs")
            st, reason = compute_status_and_reason(success_pct=success_rate_int, legs=legs_val, style='panels')
            item["status"] = st
            if reason:
                item["status_reason"] = reason
        except Exception:
            pass
        det_primary = None
        det_fallback = None
        try:
            det_primary = indices_detail.get(idx) if isinstance(indices_detail, dict) else None
            det_fallback = rs_detail.get(idx) if isinstance(rs_detail, dict) else None
            def _copy_dq(src: dict[str, Any] | None) -> None:
                if isinstance(src, dict):
                    maybe = src.get("dq")
                    if isinstance(maybe, dict):
                        sc = maybe.get("score_percent")
                        if sc is not None and item.get("dq_score") is None:
                            item["dq_score"] = sc
                        it = maybe.get("issues_total")
                        if it is not None and item.get("dq_issues") is None:
                            item["dq_issues"] = it
                        # Propagate recent issue labels if present from runtime status
                        labels = maybe.get("last_issues")
                        if isinstance(labels, list) and labels and item.get("dq_labels") is None:
                            # Truncate and sanitize to short strings
                            try:
                                cleaned = []
                                for s in labels[:5]:
                                    if not isinstance(s, str):
                                        s = str(s)
                                    cleaned.append(s[:160])
                                item["dq_labels"] = cleaned
                            except Exception:
                                item["dq_labels"] = labels
            _copy_dq(det_primary)
            _copy_dq(det_fallback)
        except Exception:
            pass
        items.append(item)
    return items


def build_panels(reader: StatusReader, status: dict[str, Any] | None) -> PanelsDict:
    panels: PanelsDict = {}
    # provider
    prov = build_provider_panel(reader, status)
    if any(v is not None for v in prov.values()):
        panels["provider"] = prov
    # resources
    panels["resources"] = build_resources_panel(reader, status)
    # sinks (if present in status)
    if isinstance(status, dict):
        sinks_obj = status.get("sinks")
        if isinstance(sinks_obj, dict):
            panels["sinks"] = cast(dict[str, Any], sinks_obj)
    # health
    h = build_health_panel(reader, status)
    if isinstance(h, dict) and h:
        panels["health"] = h
    # loop
    lp = build_loop_panel(reader, status)
    if lp:
        panels["loop"] = lp
    # indices summary
    idx_summary = build_indices_summary(reader, status)
    if idx_summary:
        panels["indices"] = idx_summary
    # Adaptive / detail mode exposure (lightweight panel)
    try:
        if isinstance(status, dict):
            odm = status.get("option_detail_mode")
            odm_str = status.get("option_detail_mode_str")
            bw = status.get("option_detail_band_window")
            mc = status.get("option_detail_mode_change_count")
            lcc = status.get("option_detail_last_change_cycle")
            lca = status.get("option_detail_last_change_age_sec")
            if odm is not None or odm_str is not None:
                panels["adaptive"] = {
                    "detail_mode": odm,
                    "detail_mode_str": odm_str,
                    "band_window": bw,
                    "mode_change_count": mc,
                    "last_change_cycle": lcc,
                    "last_change_age_sec": lca,
                }
            # Adaptive analytics alerts aggregation (lightweight panel)
            try:
                alerts = status.get("adaptive_alerts")
                if isinstance(alerts, list) and alerts:
                    # Count by type and collect most recent entries (preserve order)
                    counts: dict[str, int] = {}
                    recent: list[dict[str, Any]] = []
                    for a in alerts[-50:]:  # safety cap
                        if not isinstance(a, dict):
                            continue
                        t = a.get("type") or "unknown"
                        try:
                            counts[t] = counts.get(t, 0) + 1
                        except Exception:
                            pass
                        # Shallow sanitized copy (truncate message length)
                        msg = a.get("message")
                        if isinstance(msg, str) and len(msg) > 300:
                            msg = msg[:300] + "…"
                        recent.append({
                            "type": t,
                            "message": msg,
                        })
                    last_alert: dict[str, Any] | None = None
                    try:
                        last_raw = alerts[-1]
                        if isinstance(last_raw, dict):
                            lt = last_raw.get("type") or "unknown"
                            lm = last_raw.get("message")
                            if isinstance(lm, str) and len(lm) > 300:
                                lm = lm[:300] + "…"
                            last_alert = {"type": lt, "message": lm}
                    except Exception:
                        last_alert = None
                    panel_obj = {
                        "total": sum(counts.values()),
                        "by_type": counts,
                        "recent": recent[-10:],  # front-end only needs a short tail
                        "last": last_alert,
                    }
                    # Include follow-ups recent enriched alerts (dedicated ring buffer) if available
                    try:
                        import os  # local import to avoid global dependency if unused

                        from src.adaptive import followups as _followups
                        limit = int(os.getenv('G6_FOLLOWUPS_PANEL_LIMIT','20') or 20)
                        panel_obj['followups_recent'] = [
                            {
                                'type': fa.get('type'),
                                'index': fa.get('index'),
                                'severity': fa.get('severity'),
                                'value': fa.get('interpolated_fraction') or fa.get('drift_pct') or fa.get('utilization'),
                                'sign': fa.get('sign'),
                                'ts': fa.get('ts'),
                            }
                            for fa in _followups.get_recent_alerts(limit)
                        ]
                    except Exception:
                        pass
                    try:
                        from src.adaptive import severity as _severity  # lazy import to avoid cycles
                        if _severity.enabled():
                            # Recompute with severity enrichment (alerts already enriched at source)
                            sev_counts, by_type_sev = _severity.aggregate(alerts[-200:])  # cap for safety
                            panel_obj["severity_counts"] = sev_counts
                            # Inject meta (active threshold rules + decay/min_streak parameters) for operator transparency
                            try:
                                meta: dict[str, Any] = {}
                                # Extract loaded rules (effective warn/critical thresholds per type)
                                if hasattr(_severity, "_RULES_CACHE"):
                                    rules_cache = _severity._RULES_CACHE
                                    if not rules_cache and hasattr(_severity, "load_rules"):
                                        try:
                                            _severity.load_rules()  # populate cache
                                            rules_cache = _severity._RULES_CACHE
                                        except Exception:  # pragma: no cover
                                            rules_cache = {}
                                    rules_cache = rules_cache or {}
                                    if isinstance(rules_cache, dict) and rules_cache:
                                        meta["rules"] = rules_cache
                                # Fallback: offer public helper if exposed
                                elif hasattr(_severity, "load_rules"):
                                    try:
                                        meta["rules"] = _severity.load_rules()
                                    except Exception:
                                        pass
                                # Decay + streak parameters (read via env utility if available)
                                try:
                                    import os
                                    decay_cycles = int(os.getenv("G6_ADAPTIVE_ALERT_SEVERITY_DECAY_CYCLES", "0") or 0)
                                    min_streak = int(os.getenv("G6_ADAPTIVE_ALERT_SEVERITY_MIN_STREAK", "1") or 1)
                                    meta["decay_cycles"] = decay_cycles
                                    meta["min_streak"] = min_streak
                                    # Palette exposure (Phase 3)
                                    palette = {}
                                    for _lvl, _env in (
                                        ("info", "G6_ADAPTIVE_ALERT_COLOR_INFO"),
                                        ("warn", "G6_ADAPTIVE_ALERT_COLOR_WARN"),
                                        ("critical", "G6_ADAPTIVE_ALERT_COLOR_CRITICAL"),
                                    ):
                                        val = os.getenv(_env)
                                        if val:
                                            palette[_lvl] = val
                                    if palette:
                                        meta["palette"] = palette
                                except Exception:
                                    pass
                                # Active severity counts snapshot (controller feedback surface)
                                try:
                                    if hasattr(_severity, 'get_active_severity_counts'):
                                        try:
                                            meta['active_counts'] = _severity.get_active_severity_counts()
                                        except Exception:
                                            pass
                                except Exception:
                                    pass
                                if meta:
                                    panel_obj["severity_meta"] = meta
                            except Exception:
                                pass
                            # Enhance per-type severity entries with current active severity & resolved flag summary if available
                            enhanced_by_type: dict[str, Any] = {}
                            for _t, _entry in by_type_sev.items():
                                e = dict(_entry)
                                # If active severity state tracked in severity module, attempt to reflect it
                                try:
                                    st_map = getattr(_severity, "_DECAY_STATE", {})
                                    if isinstance(st_map, dict) and _t in st_map:
                                        st_state = st_map.get(_t) or {}
                                        active_now = st_state.get("active")
                                        if active_now:
                                            e["active_severity"] = active_now
                                        lcc = st_state.get("last_change_cycle")
                                        if lcc is not None:
                                            e["last_change_cycle"] = lcc
                                except Exception:
                                    pass
                                enhanced_by_type[_t] = e
                            panel_obj["by_type_severity"] = enhanced_by_type
                            # Derive resolved count (alerts marked resolved in recent tail)
                            try:
                                resolved_ct = 0
                                for a in alerts[-200:]:
                                    if isinstance(a, dict) and a.get("resolved"):
                                        resolved_ct += 1
                                if resolved_ct:
                                    panel_obj["resolved_total"] = resolved_ct
                            except Exception:
                                pass
                    except Exception:
                        pass
                    panels["adaptive_alerts"] = panel_obj
            except Exception:
                pass
    except Exception:
        pass
    return panels
