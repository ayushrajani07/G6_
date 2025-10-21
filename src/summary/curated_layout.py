"""Curated adaptive terminal layout for always-on summary view.

Feature gate: G6_SUMMARY_CURATED_MODE=1

Design goals:
 - Deterministic ordering with adaptive pruning based on terminal height.
 - Blocks declare importance score, min and max line counts, and optional shrink step.
 - Core invariants: header + cycle timing never removed. Critical alerts force alerts block presence.

This module is intentionally framework-light to minimize coupling. It is consumed by
scripts/summary/app (indirectly via summary_view integration) when the env flag is set.

Public API:
 - CuratedLayout.render(state: SummaryState, term_cols: int, term_rows: int) -> str
 - collect_state(...) helper to extract a lean state subset from status + panels

Tests should cover pruning rules and critical alert retention.
"""
from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

TRUE_SET = {"1","true","yes","on"}

def env_true(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in TRUE_SET

@dataclass
class Block:
    key: str
    importance: int
    lines: list[str]
    shrinkable: bool = False
    # shrink() should mutate lines to a more compact representation (<= previous lines)
    shrink: Callable[[Block], None] | None = None

    def current_height(self) -> int:
        return len(self.lines)

@dataclass
class SummaryState:
    # Minimal typed subset used for curated layout summarization
    run_id: str | None = None
    version: str | None = None
    market_state: str = "?"
    market_extra: str = ""
    cycle_number: int | None = None
    cycle_last_duration_ms: float | None = None
    cycle_p95_ms: float | None = None
    cycle_interval: float | None = None
    sla_ms: float | None = None
    sla_breach_streak: int = 0
    misses: int = 0
    on_time_pct: float | None = None
    next_run_in: float | None = None
    indices: list[dict[str, Any]] = field(default_factory=list)  # each: {name, dq, rows, ok_pct, change_pct}
    provider: dict[str, Any] = field(default_factory=dict)
    influx: dict[str, Any] = field(default_factory=dict)
    dq_score: float | None = None
    dq_warn: float | None = None
    dq_err: float | None = None
    card_active: int | None = None
    card_budget: int | None = None
    card_disabled: int | None = None
    atm_window: int | None = None
    emit_rate: float | None = None
    rss_mb: float | None = None
    mem_tier: str | None = None
    headroom_pct: float | None = None
    cpu_pct: float | None = None
    rollback_in: int | None = None
    alerts_counts: dict[str,int] = field(default_factory=dict)  # keys: info,warn,critical
    alerts_types: int = 0
    alerts_resolved: int = 0
    adaptive_mode: str | None = None
    demote_in: int | None = None
    promote_in: int | None = None
    adaptive_reasons: list[str] = field(default_factory=list)
    vol_surface: dict[str, Any] = field(default_factory=dict)  # {cov, interp, atm_iv}
    risk: dict[str, Any] = field(default_factory=dict)  # {delta, vega, drift}
    followups: list[dict[str, Any]] = field(default_factory=list)
    heartbeat: dict[str, Any] = field(default_factory=dict)  # {last_event_s, metrics_age_s, p95_spark: str}

# -------- state collection (lightweight, defensive) --------

def collect_state(status: dict[str, Any] | None) -> SummaryState:
    st = SummaryState()
    if not isinstance(status, dict):
        return st
    # Basic identity
    st.run_id = status.get("run_id") or status.get("run") or None
    st.version = status.get("version")
    # Market
    market = status.get("market") or {}
    if isinstance(market, dict):
        st.market_state = str(market.get("status", "?")).upper() or "?"
        # optional next open textual hint
        nxt = market.get("next_open_hms") or market.get("next_open")
        if nxt:
            st.market_extra = str(nxt)
    # Cycle
    loop = status.get("loop") or {}
    if isinstance(loop, dict):
        st.cycle_number = loop.get("cycle") or loop.get("number")
        st.cycle_last_duration_ms = _coerce_ms(loop.get("last_duration"))
        p95 = loop.get("p95_ms") or loop.get("latency_p95_ms")
        if isinstance(p95, (int, float)):
            st.cycle_p95_ms = float(p95)
        st.cycle_interval = _to_float(loop.get("interval"))
        st.next_run_in = _to_float(loop.get("next_run_in_sec"))
        st.misses = int(loop.get("missed_cycles", 0))
        st.on_time_pct = _to_float(loop.get("on_time_percent"))
    # SLA meta
    sla = status.get("sla") or {}
    if isinstance(sla, dict):
        st.sla_ms = _to_float(sla.get("target_ms"))
        st.sla_breach_streak = int(sla.get("breach_streak", 0))
    # Indices
    indices = status.get("indices_detail") or {}
    if isinstance(indices, dict):
        for name, info in indices.items():
            if not isinstance(info, dict):
                continue
            st.indices.append({
                "name": name,
                "dq": info.get("dq", {}).get("score_percent"),
                "rows": info.get("rows"),
                "ok_pct": info.get("success_percent"),
                "change_pct": info.get("pct_change"),
            })
    # Provider (simplified)
    prov = status.get("provider") or {}
    if isinstance(prov, dict):
        st.provider = {
            "lat_p95": prov.get("latency_p95_ms") or prov.get("latency_ms"),
            "err_pct": prov.get("error_percent"),
            "cb": prov.get("circuit_breaker_state"),
        }
    infl = status.get("influx") or {}
    if isinstance(infl, dict):
        st.influx = {
            "p95": infl.get("write_p95_ms"),
            "q": infl.get("queue"),
            "drop": infl.get("dropped"),
        }
    # DQ / cardinality
    dq = status.get("dq") or {}
    if isinstance(dq, dict):
        st.dq_score = _to_float(dq.get("score_percent"))
        st.dq_warn = _to_float(dq.get("warn_threshold"))
        st.dq_err = _to_float(dq.get("error_threshold"))
    card = status.get("cardinality") or {}
    if isinstance(card, dict):
        st.card_active = card.get("active_series")
        st.card_budget = card.get("budget")
        st.card_disabled = card.get("disabled_events")
        st.atm_window = card.get("atm_window")
        st.emit_rate = card.get("emit_rate_per_sec")
    # Resources
    res = status.get("resources") or {}
    if isinstance(res, dict):
        st.rss_mb = _to_float(res.get("rss_mb"))
        st.cpu_pct = _to_float(res.get("cpu_percent"))
        st.mem_tier = res.get("mem_tier")
        st.headroom_pct = _to_float(res.get("headroom_percent"))
        st.rollback_in = res.get("rollback_in")
    # Alerts / adaptive
    al = status.get("alerts_meta") or {}
    if isinstance(al, dict):
        st.alerts_counts = al.get("severity_counts", {}) or {}
        st.alerts_types = al.get("active_types", 0)
        st.alerts_resolved = al.get("resolved_recent", 0)
    adap = status.get("adaptive") or {}
    if isinstance(adap, dict):
        st.adaptive_mode = adap.get("detail_mode")
        st.demote_in = adap.get("demote_in")
        st.promote_in = adap.get("promote_in")
        reasons = adap.get("reasons") or []
        if isinstance(reasons, list):
            st.adaptive_reasons = [str(r) for r in reasons][:4]
    # Analytics
    vs = status.get("vol_surface") or {}
    if isinstance(vs, dict):
        st.vol_surface = {
            "cov": vs.get("coverage_pct"),
            "interp": vs.get("interp_fraction"),
            "atm_iv": vs.get("atm_iv"),
        }
    rk = status.get("risk_agg") or {}
    if isinstance(rk, dict):
        st.risk = {
            "delta": rk.get("delta_notional"),
            "vega": rk.get("vega_notional"),
            "drift": rk.get("drift_pct"),
        }
    # Follow-ups
    fu = status.get("followups_recent") or []
    if isinstance(fu, list):
        st.followups = fu[:5]
    # Heartbeat / latencies
    hb = status.get("heartbeat") or {}
    if isinstance(hb, dict):
        st.heartbeat = {
            "last_event_s": hb.get("last_event_seconds"),
            "metrics_age_s": hb.get("metrics_age_seconds"),
            "p95_spark": hb.get("latency_p95_spark"),
        }
    return st

# -------- rendering helpers --------

def _coerce_ms(v: Any) -> float | None:
    if isinstance(v, (int, float)):
        return float(v) * (1000.0 if v < 50 else 1.0)  # heuristic if seconds given
    return None

def _to_float(v: Any) -> float | None:
    try:
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str) and v.strip():
            return float(v)
    except Exception:
        return None
    return None

# Formatting helpers

def _fmt_pct(v: Any) -> str:
    if isinstance(v, (int,float)):
        return f"{v:.1f}%"
    return "?"

def _fmt_ms(v: Any) -> str:
    if isinstance(v, (int,float)):
        return f"{v:.0f}ms"
    return "?"

def _fmt_num(v: Any) -> str:
    if isinstance(v, (int,float)):
        if abs(v) >= 1_000_000:
            return f"{v/1_000_000:.1f}M"
        if abs(v) >= 1000:
            return f"{v/1000:.1f}K"
        return f"{v:.0f}"
    return "?"

def _fmt_delta(v: Any) -> str:
    if isinstance(v, (int,float)):
        sign = "+" if v>=0 else ""
        return f"{sign}{v:.2f}%"
    return "?"

# -------- block builders --------

def build_header(st: SummaryState) -> Block:
    parts = []
    parts.append(f"RUN {str(st.run_id)[:6] if st.run_id else '-'}")
    if st.version:
        parts.append(f"v{st.version}")
    parts.append(f"MARKET:{st.market_state}")
    if st.market_state != "OPEN" and st.market_extra:
        parts.append(st.market_extra)
    parts.append(f"CYCLE:{st.cycle_number if st.cycle_number is not None else '-'}")
    if st.adaptive_mode:
        parts.append(f"MODE:{st.adaptive_mode}")
    line = " ".join(parts)
    return Block(key="header", importance=100, lines=[line], shrinkable=False)

def build_cycle(st: SummaryState) -> Block:
    line1 = f"CYC t={_fmt_ms(st.cycle_last_duration_ms)} p95={_fmt_ms(st.cycle_p95_ms)} SLA={_fmt_ms(st.sla_ms)} streak={st.sla_breach_streak} miss={st.misses}"
    line2 = f"ON={_fmt_pct(st.on_time_pct)} next={(f'{st.next_run_in:.1f}s' if isinstance(st.next_run_in,(int,float)) else '?')} interval={(f'{st.cycle_interval:.0f}s' if st.cycle_interval else '?')}"
    blk = Block(key="cycle", importance=95, lines=[line1, line2], shrinkable=True)
    def _shrink(b: Block):
        if len(b.lines) > 1:
            b.lines = [f"CYC {_fmt_ms(st.cycle_last_duration_ms)}/{_fmt_ms(st.cycle_p95_ms)} SLA streak={st.sla_breach_streak} miss={st.misses} on={_fmt_pct(st.on_time_pct)}"]
    blk.shrink = _shrink
    return blk

def build_indices(st: SummaryState) -> Block:
    # Build compact inline entries
    entries = []
    for idx in st.indices[:4]:  # initial limit; shrink may reduce further
        name = idx.get("name") or "?"
        change = _fmt_delta(idx.get("change_pct"))
        rows = _fmt_num(idx.get("rows"))
        ok = _fmt_pct(idx.get("ok_pct"))
        entries.append(f"{name} {change} r={rows} ok={ok}")
    line = "  ".join(entries) if entries else "IDX none"
    blk = Block(key="indices", importance=90, lines=[f"IDX {line}"], shrinkable=True)
    def _shrink(b: Block):
        if st.indices:
            first = st.indices[0]
            b.lines = [f"IDX {first.get('name','?')} {_fmt_delta(first.get('change_pct'))} r={_fmt_num(first.get('rows'))} ok={_fmt_pct(first.get('ok_pct'))}"]
    blk.shrink = _shrink
    return blk

def build_provider(st: SummaryState) -> Block:
    kite = st.provider
    inf = st.influx
    line = f"PROV p95={_fmt_ms(kite.get('lat_p95'))} err={_fmt_pct(kite.get('err_pct'))} cb={kite.get('cb') or '-'} | INF p95={_fmt_ms(inf.get('p95'))} q={_fmt_num(inf.get('q'))} drop={_fmt_num(inf.get('drop'))}"
    blk = Block(key="provider", importance=80, lines=[line], shrinkable=True)
    def _shrink(b: Block):
        b.lines = [f"NET p95={_fmt_ms(kite.get('lat_p95'))} err={_fmt_pct(kite.get('err_pct'))} | inf p95={_fmt_ms(inf.get('p95'))}"]
    blk.shrink = _shrink
    return blk

def build_dq_card(st: SummaryState) -> Block:
    line = f"DQ {_fmt_pct(st.dq_score)} warn={_fmt_pct(st.dq_warn)} err={_fmt_pct(st.dq_err)} | CARD {(_fmt_num(st.card_active) + '/' + _fmt_num(st.card_budget)) if st.card_active is not None and st.card_budget is not None else '?'} dis={_fmt_num(st.card_disabled)} atm={_fmt_num(st.atm_window)} rate={_fmt_num(st.emit_rate)}/s"
    blk = Block(key="dq_card", importance=75, lines=[line], shrinkable=True)
    def _shrink(b: Block):
        b.lines = [f"DQ {_fmt_pct(st.dq_score)} | CARD {(_fmt_num(st.card_active) + '/' + _fmt_num(st.card_budget)) if st.card_active is not None and st.card_budget is not None else '?'}"]
    blk.shrink = _shrink
    return blk

def build_memory(st: SummaryState) -> Block:
    line = f"MEM {(_fmt_num(st.rss_mb)+'MB') if st.rss_mb is not None else '?'} tier={st.mem_tier or '-'} head={_fmt_pct(st.headroom_pct)} cpu={_fmt_pct(st.cpu_pct)} rollback_in={(st.rollback_in if st.rollback_in is not None else '-')}"
    blk = Block(key="memory", importance=70, lines=[line], shrinkable=True)
    def _shrink(b: Block):
        b.lines = [f"MEM {(_fmt_num(st.rss_mb)+'MB') if st.rss_mb is not None else '?'} {st.mem_tier or '-'} head={_fmt_pct(st.headroom_pct)}"]
    blk.shrink = _shrink
    return blk

def build_alerts(st: SummaryState) -> Block:
    cts = st.alerts_counts or {}
    line1 = f"ALERTS i/w/c={_fmt_num(cts.get('info',0))}/{_fmt_num(cts.get('warn',0))}/{_fmt_num(cts.get('critical',0))} types={_fmt_num(st.alerts_types)} resolved={_fmt_num(st.alerts_resolved)}"
    reasons = ",".join(st.adaptive_reasons[:2]) if st.adaptive_reasons else "none"
    line2 = f"ADAPT mode={st.adaptive_mode or '-'} demote_in={st.demote_in} promote_in={st.promote_in} reasons:{reasons}"
    blk = Block(key="alerts", importance=85, lines=[line1, line2], shrinkable=True)
    def _shrink(b: Block):
        b.lines = [f"ALRT i/w/c={_fmt_num(cts.get('info',0))}/{_fmt_num(cts.get('warn',0))}/{_fmt_num(cts.get('critical',0))} mode={st.adaptive_mode or '-'}"]
    blk.shrink = _shrink
    return blk

def build_analytics(st: SummaryState) -> Block:
    vs = st.vol_surface or {}
    rk = st.risk or {}
    line = f"AN vol_cov={_fmt_pct(vs.get('cov'))} interp={_fmt_pct(vs.get('interp'))} atm_iv={_fmt_pct(vs.get('atm_iv'))} | risk Δ={_fmt_num(rk.get('delta'))} vega={_fmt_num(rk.get('vega'))} drift={_fmt_pct(rk.get('drift'))}"
    blk = Block(key="analytics", importance=45, lines=[line], shrinkable=True)
    def _shrink(b: Block):
        b.lines = [f"VOL {_fmt_pct(vs.get('cov'))} interp={_fmt_pct(vs.get('interp'))}"]
    blk.shrink = _shrink
    return blk

def build_followups(st: SummaryState) -> Block:
    if not st.followups:
        line = "FUP none"
    else:
        parts = []
        for f in st.followups[:2]:
            if isinstance(f, dict):
                t = f.get('type') or '?'
                streak = f.get('streak')
                parts.append(f"{t}({streak})" if streak is not None else t)
        line = "FUP " + ",".join(parts)
    return Block(key="followups", importance=40, lines=[line], shrinkable=False)

def build_heartbeat(st: SummaryState) -> Block:
    hb = st.heartbeat or {}
    line = f"HB evt={_fmt_num(hb.get('last_event_s'))}s metrics={_fmt_num(hb.get('metrics_age_s'))} p95:{hb.get('p95_spark') or '-'}"
    return Block(key="heartbeat", importance=60, lines=[line], shrinkable=True)

# -------- pruning engine --------

def _critical_alert_active(st: SummaryState) -> bool:
    try:
        val = st.alerts_counts.get('critical') if st.alerts_counts else 0
        if val is None:
            val = 0
        return int(val) > 0
    except Exception:
        return False

class CuratedLayout:
    def __init__(self):
        pass

    def build_blocks(self, st: SummaryState) -> list[Block]:
        blocks: list[Block] = []
        # Earlier heuristic auto-hid empty blocks when curated mode active even if explicit hide flag unset.
        # This prevented tests from seeing 'FUP none' after unsetting G6_SUMMARY_HIDE_EMPTY_BLOCKS.
        # New rule: only hide when explicit env set true (no implicit curated-mode auto hide).
        hide_empty = env_true('G6_SUMMARY_HIDE_EMPTY_BLOCKS')
        # Header & core always present
        blocks.append(build_header(st))
        blocks.append(build_cycle(st))
        blocks.append(build_indices(st))
        blocks.append(build_provider(st))
        blocks.append(build_dq_card(st))
        blocks.append(build_memory(st))
        blocks.append(build_alerts(st))
        # Analytics optional suppression: treat as empty if all tracked fields None/unknown
        an_empty = False
        if hide_empty:
            vs = st.vol_surface or {}
            rk = st.risk or {}
            vs_vals = [vs.get('cov'), vs.get('interp'), vs.get('atm_iv')]
            rk_vals = [rk.get('delta'), rk.get('vega'), rk.get('drift')]
            # consider unknown if value is None or not a (int/float)
            def _all_unknown(vals):
                return all((v is None) or (not isinstance(v, (int,float))) for v in vals)
            if _all_unknown(vs_vals) and _all_unknown(rk_vals):
                an_empty = True
        if not (hide_empty and an_empty):
            blocks.append(build_analytics(st))
        # Followups optional suppression (none or only string 'none')
        fu_empty = False
        if hide_empty:
            fu_empty = (not st.followups)
        if not (hide_empty and fu_empty):
            blocks.append(build_followups(st))
        blocks.append(build_heartbeat(st))
        return blocks

    def render(self, st: SummaryState, term_cols: int | None = None, term_rows: int | None = None) -> str:
        if term_cols is None or term_rows is None:
            try:
                size = shutil.get_terminal_size()
                term_cols = term_cols or size.columns
                term_rows = term_rows or size.lines
            except Exception:
                term_cols = term_cols or 100
                term_rows = term_rows or 30
        # Reserve 0 lines for padding; future: help footer
        available = max(5, term_rows - 0)
        blocks = self.build_blocks(st)
        # Sort by importance descending
        blocks.sort(key=lambda b: b.importance, reverse=True)
        # First pass: shrink lower-importance blocks before dropping
        def total_height():
            return sum(b.current_height() for b in blocks)
        # Shrink loop
        changed = True
        while changed and total_height() > available:
            changed = False
            # consider shrinkable blocks from lowest importance upward (reverse order of sorted list)
            for b in sorted(blocks, key=lambda x: x.importance):
                if total_height() <= available:
                    break
                if b.shrinkable and b.shrink is not None and b.current_height() > 1:
                    b.shrink(b)
                    changed = True
        # Drop loop (never drop header or cycle; keep alerts if critical present)
        protected_keys = {"header", "cycle"}
        if _critical_alert_active(st):
            protected_keys.add("alerts")
        # Drop from lowest importance
        dropped = True
        while dropped and total_height() > available:
            dropped = False
            for b in sorted(blocks, key=lambda x: x.importance):
                if b.key in protected_keys:
                    continue
                # Always drop analytics first when constrained
                if b.key == "analytics" or True:
                    blocks.remove(b)
                    dropped = True
                    if total_height() <= available:
                        break
        # Final assembly
        return "\n".join([ln for b in blocks for ln in b.lines])

__all__ = ["CuratedLayout", "collect_state", "SummaryState"]
