from __future__ import annotations

"""Shadow Gating Controller (Phase 4 – initial dry-run implementation)

Purpose:
    Evaluate structural parity over a rolling window and emit a promotion decision
    without altering authoritative pipeline output. This module is intentionally
    lightweight and side-effect free (no metrics emission yet) so it can soak.

Modes (environment-driven upstream; this module only interprets string):
    off    : Return decision with promote=False, reason='disabled'.
    dryrun : Compute rolling stats; never promote (promote=False) but include
             hypothetical outcome fields.
    promote (future): Will allow promote=True when thresholds satisfied (not yet).

Inputs:
    index (str)          : Index symbol.
    rule (str)           : Expiry rule.
    meta (Mapping)       : Shadow state.meta containing parity_hash_v2, diff fields.
    store (WindowStore)  : Rolling window storage abstraction (in-memory dict).
    config (GatingConfig): Threshold configuration.

Outputs (decision dict):
    {
      'mode': 'off'|'dryrun'|...,   # effective mode
      'promote': bool,              # always False for off/dryrun in this version
      'parity_ok_ratio': float,     # ratio over window (0..1) or None if insufficient
      'window_size': int,           # number of samples considered
      'diff_count': int,            # current cycle diff count
      'protected_diff': bool,       # diff touches protected field (expiry_date/instrument_count)
      'reason': str,                # short token for decision rationale
    }

Window Semantics:
    Each (index, rule) key maintains a deque of last N boolean parity_ok flags.
    A sample is considered parity_ok when diff_count == 0.

Extensibility:
    - Future version will incorporate synthetic fallback / salvage usage or
      coverage thresholds as additional guardrails.
    - Promotion hysteresis (min consecutive ok) can be layered on later.
"""
import os
from collections import defaultdict, deque
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

DEFAULT_PROTECTED_FIELDS = ("expiry_date", "instrument_count")

@dataclass
class GatingConfig:
    window: int = 200
    parity_target: float = 0.99          # Full promotion target
    canary_target: float = 0.97          # Canary observation threshold (lower)
    min_samples: int = 30                # Minimum samples before any canary/promo
    ok_hysteresis: int = 10              # Consecutive ok samples required for promotion
    fail_hysteresis: int = 5             # Consecutive fail samples to revoke canary/promo
    mode: str = "off"  # off | dryrun | canary | promote
    canary_indices: tuple[str, ...] = ()  # explicit allowlist (beats pct)
    canary_pct: float = 1.0  # fraction (0-1] of indices allowed when allowlist absent
    rollback_protected_threshold: int = 999999  # high default (disabled)
    rollback_churn_ratio: float = 2.0           # >1 disables; set <=1 to enable
    protected_fields: tuple[str,...] = DEFAULT_PROTECTED_FIELDS
    churn_window: int = -1                      # -1 => use parity window

class WindowStore:
    """In-memory rolling window store keyed by (index, rule).

    Tracks boolean parity_ok samples plus lightweight consecutive ok/fail counters
    (not derived each time to keep O(1) updates even for large windows).
    """
    def __init__(self) -> None:
        self._data: dict[tuple[str,str], deque[bool]] = defaultdict(lambda: deque(maxlen=200))
        self._ok_streak: dict[tuple[str,str], int] = defaultdict(int)
        self._fail_streak: dict[tuple[str,str], int] = defaultdict(int)
        self._protected: dict[tuple[str,str], deque[bool]] = defaultdict(lambda: deque(maxlen=200))
        self._hashes: dict[tuple[str,str], deque[str]] = defaultdict(lambda: deque(maxlen=200))
        self._hashes_churn: dict[tuple[str,str], deque[str]] = defaultdict(lambda: deque(maxlen=200))

    def update(self, index: str, rule: str, ok: bool, window: int, *, protected: bool, parity_hash: str | None, churn_window: int | None = None) -> None:
        key = (index, rule)
        dq = self._data[key]
        if dq.maxlen != window:  # resize preserving history
            ndq: deque[bool] = deque(dq, maxlen=window)
            self._data[key] = dq = ndq
            # resize companion deques
            self._protected[key] = deque(self._protected.get(key, deque()), maxlen=window)
            self._hashes[key] = deque(self._hashes.get(key, deque()), maxlen=window)
        if churn_window and churn_window > 0:
            chdq = self._hashes_churn[key]
            if chdq.maxlen != churn_window:
                self._hashes_churn[key] = deque(chdq, maxlen=churn_window)
        dq.append(ok)
        self._protected[key].append(protected)
        if parity_hash is not None:
            self._hashes[key].append(parity_hash)
            if churn_window and churn_window > 0:
                self._hashes_churn[key].append(parity_hash)
        # streak accounting
        if ok:
            self._ok_streak[key] += 1
            self._fail_streak[key] = 0
        else:
            self._fail_streak[key] += 1
            self._ok_streak[key] = 0

    def stats(self, index: str, rule: str) -> tuple[int, float]:
        dq = self._data.get((index, rule))
        if not dq:
            return 0, 0.0
        total = len(dq)
        if total == 0:
            return 0, 0.0
        ok_ratio = sum(1 for v in dq if v) / total
        return total, ok_ratio

    def streaks(self, index: str, rule: str) -> tuple[int, int]:
        key = (index, rule)
        return self._ok_streak.get(key, 0), self._fail_streak.get(key, 0)

    def protected_counts(self, index: str, rule: str) -> int:
        dq = self._protected.get((index, rule))
        if not dq:
            return 0
        return sum(1 for v in dq if v)

    def hash_churn(self, index: str, rule: str) -> tuple[int, int, float]:
        dq = self._hashes.get((index, rule))
        if not dq:
            return 0, 0, 0.0
        total = len(dq)
        if total == 0:
            return 0, 0, 0.0
        distinct: set[str] = set(dq)
        distinct_count = len(distinct)
        churn_ratio = distinct_count / total if total else 0.0
        return total, distinct_count, churn_ratio

    def hash_churn_windowed(self, index: str, rule: str) -> tuple[int, int, float]:
        dq = self._hashes_churn.get((index, rule))
        if not dq:
            return 0,0,0.0
        total = len(dq)
        if total == 0:
            return 0,0,0.0
        distinct = set(dq)
        return total, len(distinct), (len(distinct)/total if total else 0.0)

# Single module-level store (test can reset by re-instantiating)
_WINDOW_STORE = WindowStore()

def load_config_from_env() -> GatingConfig:
    def _f(name: str, default: float) -> float:
        try:
            raw = os.getenv(name)
            if raw is None:
                return default
            val = float(raw)
            if 0 <= val <= 1 or name.endswith("WINDOW"):
                return val
            return default
        except Exception:
            return default
    def _i(name: str, default: int) -> int:
        try:
            raw = os.getenv(name)
            if raw is None:
                return default
            val = int(raw)
            if val > 0:
                return val
            return default
        except Exception:
            return default
    mode = (os.getenv("G6_SHADOW_GATE_MODE") or "off").strip().lower()
    raw_list = (os.getenv('G6_SHADOW_CANARY_INDICES') or '').strip()
    canary_indices: tuple[str,...] = tuple(x.strip() for x in raw_list.split(',') if x.strip()) if raw_list else ()
    def _pct(name: str, default: float) -> float:
        try:
            raw = os.getenv(name)
            if raw is None:
                return default
            v = float(raw)
            if 0 < v <= 1:
                return v
            return default
        except Exception:
            return default
    # Extend protected fields via env (comma separated list)
    extra_protected_raw = os.getenv('G6_SHADOW_PROTECTED_FIELDS','').strip()
    if extra_protected_raw:
        extra = tuple(sorted({f.strip() for f in extra_protected_raw.split(',') if f.strip()}))
        protected_fields = tuple(sorted(set(DEFAULT_PROTECTED_FIELDS).union(extra)))
    else:
        protected_fields = DEFAULT_PROTECTED_FIELDS
    return GatingConfig(
        window=_i("G6_SHADOW_PARITY_WINDOW", 200),
        parity_target=_f("G6_SHADOW_PARITY_OK_TARGET", 0.99),
        canary_target=_f("G6_SHADOW_PARITY_CANARY_TARGET", 0.97),
        min_samples=_i("G6_SHADOW_PARITY_MIN_SAMPLES", 30),
        ok_hysteresis=_i("G6_SHADOW_PARITY_OK_STREAK", 10),
        fail_hysteresis=_i("G6_SHADOW_PARITY_FAIL_STREAK", 5),
        mode=mode if mode in ("off","dryrun","canary","promote") else "off",
        canary_indices=canary_indices,
        canary_pct=_pct('G6_SHADOW_CANARY_PCT', 1.0),
        rollback_protected_threshold=_i("G6_SHADOW_ROLLBACK_PROTECTED_THRESHOLD", 999999),
        rollback_churn_ratio=_f("G6_SHADOW_ROLLBACK_CHURN_RATIO", 2.0),
        protected_fields=protected_fields,
        churn_window=_i("G6_SHADOW_CHURN_WINDOW", -1),
    )

def decide(index: str, rule: str, meta: Mapping[str, Any], *, config: GatingConfig | None = None, store: WindowStore | None = None) -> dict[str, Any]:
    if config is None:
        config = load_config_from_env()
    if store is None:
        store = _WINDOW_STORE
    mode = config.mode
    diff_count = int(meta.get('parity_diff_count') or 0)
    diff_fields = tuple(meta.get('parity_diff_fields') or ())
    protected_diff = any(f in diff_fields for f in config.protected_fields)
    parity_ok = diff_count == 0
    # Update rolling window only when mode != off (could also update always; conservative for now)
    parity_hash = meta.get('parity_hash_v2') if isinstance(meta.get('parity_hash_v2'), str) else None
    if mode in ("dryrun","canary","promote"):
        churn_win = config.churn_window if config.churn_window and config.churn_window > 0 else None
        store.update(index, rule, parity_ok, config.window, protected=protected_diff, parity_hash=parity_hash, churn_window=churn_win)
    window_size, ratio = store.stats(index, rule)
    ok_streak, fail_streak = store.streaks(index, rule)
    protected_in_window = store.protected_counts(index, rule)
    _hash_total, hash_distinct, hash_churn_ratio = store.hash_churn(index, rule)
    churn_window_size = None
    if config.churn_window and config.churn_window > 0:
        c_tot, c_distinct, c_ratio = store.hash_churn_windowed(index, rule)
        hash_distinct = c_distinct
        hash_churn_ratio = c_ratio
        churn_window_size = c_tot
    decision: dict[str, Any] = {
        'mode': mode,
        'promote': False,
        'canary': False,
        'parity_ok_ratio': ratio if window_size else None,
        'window_size': window_size,
        'diff_count': diff_count,
        'protected_diff': protected_diff,
        'ok_streak': ok_streak,
        'fail_streak': fail_streak,
        'protected_in_window': protected_in_window,
        'hash_distinct': hash_distinct,
        'hash_churn_ratio': hash_churn_ratio if window_size else None,
        'churn_window_size': churn_window_size,
        'reason': 'disabled' if mode == 'off' else 'observing',
    }
    if mode == 'off':
        return decision
    if window_size < config.min_samples:
        # Force demote has highest precedence even before sample sufficiency (operational override)
        if os.getenv('G6_SHADOW_FORCE_DEMOTE','').lower() in ('1','true','on','yes'):
            decision['reason'] = 'forced_demote'
            decision['promote'] = False
            decision['canary'] = False
            return decision
        # Allow immediate protected blocking / rollback signaling even before min sample threshold
        if mode == 'promote':
            if protected_in_window >= config.rollback_protected_threshold and config.rollback_protected_threshold < 999999:
                decision['reason'] = 'rollback_protected'
                decision['promote'] = False
                decision['canary'] = False
                return decision
            if protected_diff or protected_in_window > 0:
                decision['reason'] = 'protected_block'
                decision['promote'] = False
                decision['canary'] = False
                return decision
        decision['reason'] = 'insufficient_samples'
        return decision
    # Churn rollback guard (before canary evaluation). Enabled when threshold <=1.
    hash_churn_val: float = float(decision['hash_churn_ratio']) if isinstance(decision['hash_churn_ratio'], (int,float)) else 0.0
    if (mode in ('canary','promote','dryrun') and window_size >= config.min_samples
        and (decision['hash_churn_ratio'] is not None)
        and config.rollback_churn_ratio <= 1.0
        and hash_churn_val >= config.rollback_churn_ratio):
        decision['reason'] = 'rollback_churn'
        decision['canary'] = False
        decision['promote'] = False
        if mode == 'dryrun':  # observational rollback indicator
            return decision
        # For canary/promote treat as hard rollback
        return decision
    # Canary eligibility gating (applies to canary/promote modes; dryrun always observes)
    if mode in ('canary','promote'):
        allowed = True
        if config.canary_indices:
            allowed = index in config.canary_indices
        else:
            # Hash-based deterministic sampling using first 4 hex chars of parity hash (if present) to pick subset
            if config.canary_pct < 1.0:
                try:
                    ph = str(meta.get('parity_hash_v2') or '')
                    hseg = ph[:4] or '0'
                    bucket = int(hseg, 16) / 0xFFFF
                    allowed = bucket <= config.canary_pct
                except Exception:
                    allowed = False
        if not allowed:
            decision['reason'] = 'canary_excluded'
            return decision
    # Canary evaluation (applies to canary & promote modes)
    # Canary evaluation: allow activation in canary mode even if protected diff present (blocks only promotion)
    if ratio >= config.canary_target and (mode == 'canary' or not protected_diff):
        decision['canary'] = True
    # Early exit for dryrun mode (only observational, still can show canary boolean)
    if mode == 'dryrun':
        decision['reason'] = 'dryrun_no_promo'
        return decision
    # Rollback guard: excessive protected diffs in rolling window
    if protected_in_window >= config.rollback_protected_threshold and config.rollback_protected_threshold < 999999:
        decision['reason'] = 'rollback_protected'
        decision['canary'] = False
        decision['promote'] = False
        return decision
    if mode == 'canary':
        # Remain in canary unless fail hysteresis reached or protected diff appears
        if not decision['canary']:
            decision['reason'] = 'below_canary_target'
        else:
            if fail_streak >= config.fail_hysteresis:
                decision['canary'] = False
                decision['reason'] = 'fail_hysteresis'
            else:
                decision['reason'] = 'canary_active'
        return decision
    # Promotion mode logic with hysteresis
    if mode == 'promote':
        # Explicit force demote override takes precedence over all other reasons once samples sufficient
        force_demote = os.getenv('G6_SHADOW_FORCE_DEMOTE','').lower() in ('1','true','on','yes')
        if force_demote:
            decision['reason'] = 'forced_demote'
            decision['promote'] = False
            decision['canary'] = False
            return decision
        if protected_diff:
            decision['reason'] = 'protected_block'
            return decision
        if protected_in_window >= config.rollback_protected_threshold and config.rollback_protected_threshold < 999999:
            decision['reason'] = 'rollback_protected'
            return decision
        if not decision['canary']:
            decision['reason'] = 'below_canary_target'
            return decision
        # Check full parity target + consecutive ok streak
        if ratio >= config.parity_target and ok_streak >= config.ok_hysteresis:
            decision['promote'] = True
            decision['reason'] = 'parity_target_met'
            if os.getenv('G6_SHADOW_AUTHORITATIVE','').lower() in ('1','true','on','yes'):
                decision['authoritative'] = True
            return decision
        if fail_streak >= config.fail_hysteresis:
            decision['reason'] = 'fail_hysteresis'
            return decision
        decision['reason'] = 'waiting_hysteresis'
        return decision
    return decision

__all__ = ["GatingConfig", "WindowStore", "decide", "load_config_from_env"]
