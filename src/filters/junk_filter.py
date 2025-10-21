#!/usr/bin/env python3
"""Reusable Junk Filter logic extracted from CsvSink.

Behavior Parity Goals:
- Replicates threshold + stale detection + whitelist logic.
- External side-effects (metrics, logging, summary emission) delegated via callbacks.

Usage:
    cfg = JunkFilterConfig.from_env(os.environ)
    jf = JunkFilter(cfg, callbacks=JunkFilterCallbacks(...))
    skip, meta = jf.should_skip(index, expiry_code, offset, call_data, put_data, row_ts)

Returned tuple:
    (skip: bool, meta: JunkDecision)

Where JunkDecision contains category ('threshold'|'stale'), first_time flag, and counters snapshot if summary triggered.
"""
from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass
class JunkFilterConfig:
    enabled: bool = False
    min_total_oi: int = 0
    min_total_vol: int = 0
    min_leg_oi: int = 0
    min_leg_vol: int = 0
    stale_threshold: int = 0
    whitelist: set[str] = field(default_factory=set)
    summary_interval: int = 0  # seconds; 0 => disabled
    debug: bool = False

    @staticmethod
    def from_env(env: Mapping[str, str]) -> JunkFilterConfig:
        def _ival(key: str, default: int = 0) -> int:
            try:
                return int(env.get(key, str(default)) or default)
            except Exception:
                return default
        whitelist_raw = env.get('G6_CSV_JUNK_WHITELIST','').strip()
        whitelist: set[str] = set()
        if whitelist_raw:
            for tok in whitelist_raw.split(','):
                tok = tok.strip()
                if tok:
                    whitelist.add(tok)
        # Determine enable flag (auto if any thresholds/stale >0)
        j_enable_env = (env.get('G6_CSV_JUNK_ENABLE','auto') or 'auto').lower()
        thresholds_present = any((_ival('G6_CSV_JUNK_MIN_TOTAL_OI'), _ival('G6_CSV_JUNK_MIN_TOTAL_VOL'),
                                  _ival('G6_CSV_JUNK_MIN_LEG_OI'), _ival('G6_CSV_JUNK_MIN_LEG_VOL'),
                                  _ival('G6_CSV_JUNK_STALE_THRESHOLD')))
        if j_enable_env in ('1','true','yes','on'):
            enabled = True
        elif j_enable_env in ('0','false','no','off'):
            enabled = False
        else:
            enabled = thresholds_present
        return JunkFilterConfig(
            enabled=enabled,
            min_total_oi=max(0,_ival('G6_CSV_JUNK_MIN_TOTAL_OI')),
            min_total_vol=max(0,_ival('G6_CSV_JUNK_MIN_TOTAL_VOL')),
            min_leg_oi=max(0,_ival('G6_CSV_JUNK_MIN_LEG_OI')),
            min_leg_vol=max(0,_ival('G6_CSV_JUNK_MIN_LEG_VOL')),
            stale_threshold=max(0,_ival('G6_CSV_JUNK_STALE_THRESHOLD')),
            whitelist=whitelist,
            summary_interval=max(0,_ival('G6_CSV_JUNK_SUMMARY_INTERVAL')),
            debug=(env.get('G6_CSV_JUNK_DEBUG','0').lower() in ('1','true','yes','on')),
        )

@dataclass
class JunkDecision:
    skip: bool
    category: str | None = None  # 'threshold' or 'stale'
    first_time: bool = False
    summary_emitted: bool = False
    summary_snapshot: dict[str, int] | None = None

@dataclass
class JunkFilterCallbacks:
    log_info: Callable[[str], None] = lambda msg: None
    log_debug: Callable[[str], None] = lambda msg: None

class JunkFilter:
    def __init__(self, config: JunkFilterConfig, callbacks: JunkFilterCallbacks | None = None):
        self.cfg = config
        self.cb = callbacks or JunkFilterCallbacks()
        # State
        self._stale_map: dict[tuple[str, str, int], tuple[tuple[float, float], int]] = {}
        self._stale_touch: dict[tuple[str, str, int], float] = {}
        self._stale_last_prune: float = 0.0
        self._skip_keys: set[tuple[str, str, int, str]] = set()
        # Separate counters and last-summary timestamp to avoid mixed-typed dict
        self._stats_counts: dict[str, int] = {"threshold": 0, "stale": 0, "total": 0}
        self._last_summary: float = time.time()
        if self.cfg.enabled:
            self.cb.log_info(
                f"CSV_JUNK_INIT enabled={self.cfg.enabled} total_oi>={self.cfg.min_total_oi} total_vol>={self.cfg.min_total_vol} "
                f"leg_oi>={self.cfg.min_leg_oi} leg_vol>={self.cfg.min_leg_vol} stale_threshold={self.cfg.stale_threshold} "
                f"whitelist={len(self.cfg.whitelist)} summary_interval={self.cfg.summary_interval}"
            )

    def should_skip(self, index: str, expiry_code: str, offset: int, call_data: dict[str,Any] | None, put_data: dict[str,Any] | None, row_ts: str) -> tuple[bool, JunkDecision]:
        if not self.cfg.enabled:
            return False, JunkDecision(skip=False)
        pattern_tokens = {f"{index}:{expiry_code}", f"{index}:*", f"*:{expiry_code}", '*'}
        if self.cfg.debug:
            self.cb.log_info(f"CSV_JUNK_DEBUG phase=pre_whitelist index={index} expiry_code={expiry_code} patterns={pattern_tokens} whitelist={self.cfg.whitelist} intersect={self.cfg.whitelist.intersection(pattern_tokens)} enabled={self.cfg.enabled}")
        if self.cfg.whitelist.intersection(pattern_tokens):
            return False, JunkDecision(skip=False)
        ce_oi = int((call_data or {}).get('oi', 0))
        pe_oi = int((put_data or {}).get('oi', 0))
        ce_vol = int((call_data or {}).get('volume', 0))
        pe_vol = int((put_data or {}).get('volume', 0))
        total_oi = ce_oi + pe_oi
        total_vol = ce_vol + pe_vol
        junk_threshold = False
        if self.cfg.min_total_oi > 0 and total_oi < self.cfg.min_total_oi:
            junk_threshold = True
        if self.cfg.min_total_vol > 0 and total_vol < self.cfg.min_total_vol:
            junk_threshold = True
        if self.cfg.min_leg_oi > 0 and (ce_oi < self.cfg.min_leg_oi or pe_oi < self.cfg.min_leg_oi):
            junk_threshold = True
        if self.cfg.min_leg_vol > 0 and (ce_vol < self.cfg.min_leg_vol or pe_vol < self.cfg.min_leg_vol):
            junk_threshold = True
        junk_stale = False
        now_ts = time.time()
        if not junk_threshold and self.cfg.stale_threshold > 0:
            sig_key = (index, expiry_code, offset)
            ce_price = float((call_data or {}).get('last_price', 0) or 0.0)
            pe_price = float((put_data or {}).get('last_price', 0) or 0.0)
            price_sig = (round(ce_price, 4), round(pe_price, 4))
            prev = self._stale_map.get(sig_key)
            if prev is None:
                count = 1
            else:
                prev_sig, prev_count = prev
                count = prev_count + 1 if prev_sig == price_sig else 1
            self._stale_map[sig_key] = (price_sig, count)
            self._stale_touch[sig_key] = now_ts
            if len(self._stale_touch) > 5000 and (now_ts - self._stale_last_prune) > 300:
                cutoff = now_ts - 3600
                removed = 0
                for k, ts_k in list(self._stale_touch.items()):
                    if ts_k < cutoff:
                        self._stale_touch.pop(k, None)
                        self._stale_map.pop(k, None)
                        removed += 1
                self._stale_last_prune = now_ts
                if removed and self.cfg.debug:
                    self.cb.log_info(f"CSV_JUNK_DEBUG phase=prune stale_keys_removed={removed} remaining={len(self._stale_touch)}")
            if count > self.cfg.stale_threshold:
                junk_stale = True
        junk = junk_threshold or junk_stale
        if not junk:
            return False, JunkDecision(skip=False)
        category = 'threshold' if junk_threshold else 'stale'
        skip_key = (index, expiry_code, offset, row_ts)
        first_time = skip_key not in self._skip_keys
        if first_time:
            self._skip_keys.add(skip_key)
        self._stats_counts['total'] += 1
        self._stats_counts[category] += 1
        summary_emitted = False
        snapshot: dict[str, int] | None = None
        if self.cfg.summary_interval > 0 and (now_ts - self._last_summary) >= self.cfg.summary_interval:
            summary_emitted = True
            snapshot = {
                'window': int(self.cfg.summary_interval),
                'total': self._stats_counts['total'],
                'threshold': self._stats_counts['threshold'],
                'stale': self._stats_counts['stale'],
            }
            self._last_summary = now_ts
            self._stats_counts['total'] = 0
            self._stats_counts['threshold'] = 0
            self._stats_counts['stale'] = 0
        if self.cfg.debug:
            self.cb.log_info(f"CSV_JUNK_DEBUG phase=post_skip index={index} expiry_code={expiry_code} offset={offset} category={category} first_time={first_time}")
        return True, JunkDecision(skip=True, category=category, first_time=first_time, summary_emitted=summary_emitted, summary_snapshot=snapshot)
