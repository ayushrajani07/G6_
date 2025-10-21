"""Memory pressure adaptive degradation strategies.

Defines tiers and actions to reduce memory footprint gracefully instead of hard killing processes.
"""
from __future__ import annotations

try:
    import psutil  # type: ignore
except Exception as e:  # pragma: no cover
    psutil = None  # fallback; sampling will no-op
    try:
        from src.error_handling import handle_api_error
        handle_api_error(e, component="utils.memory_pressure.import_psutil")
    except Exception:
        pass
import logging
import os
import time
from dataclasses import dataclass

try:
    from src.collectors.env_adapter import get_int as _env_get_int  # type: ignore
    from src.collectors.env_adapter import get_str as _env_get_str
except Exception:  # pragma: no cover
    def _env_get_int(name: str, default: int) -> int:
        try:
            v = os.getenv(name)
            if v is None or str(v).strip() == "":
                return default
            return int(str(v).strip())
        except Exception:
            return default
    def _env_get_str(name: str, default: str = "") -> str:
        try:
            v = os.getenv(name)
            return default if v is None else v
        except Exception:
            return default

logger = logging.getLogger(__name__)

@dataclass
class PressureTier:
    name: str
    level: int  # 0 normal, 1 elevated, 2 high, 3 critical
    threshold_mb: float
    actions: list[str]  # symbolic action names

DEFAULT_TIERS = [
    PressureTier('normal', 0, 0, []),
    PressureTier('elevated', 1, 0.70, ['shrink_cache']),
    PressureTier('high', 2, 0.80, ['shrink_cache','reduce_depth','skip_greeks','slow_cycles']),
    PressureTier('critical', 3, 0.90, ['shrink_cache','reduce_depth','skip_greeks','slow_cycles','drop_per_option_metrics'])
]

class MemoryPressureManager:
    def __init__(self,
                 metrics=None,
                 total_physical_mb: float | None = None,
                 tiers: list[PressureTier] | None = None,
                 sample_interval: int = 10,
                 smoothing_alpha: float = 0.4):
        self.metrics = metrics
        self.process = psutil.Process() if psutil else None
        self.total_physical_mb = total_physical_mb or ((psutil.virtual_memory().total / (1024*1024)) if psutil else 0)
        self.tiers = tiers or self._load_tiers_from_env()
        self.sample_interval = sample_interval
        self.smoothing_alpha = smoothing_alpha
        self._ema = None
        # Hysteresis tracking
        self._last_level_change_ts = time.time()
        self._stable_below_start = None
        self.recovery_seconds = _env_get_int('G6_MEMORY_PRESSURE_RECOVERY_SECONDS', 60)
        self.current_level = 0
        self.active_flags = {
            'reduce_depth': False,
            'skip_greeks': False,
            'slow_cycles': False,
            'drop_per_option_metrics': False
        }
        self.last_actions = []
        # Adaptive scaling state
        self.depth_scale = 1.0
        self._seconds_in_level_start = time.time()
        self._downgrade_pending = False
        self.rollback_cooldown = _env_get_int('G6_MEMORY_ROLLBACK_COOLDOWN', 120)
        self._last_downgrade_ts = None
        self._greeks_disabled_ts = None
        self.greeks_enabled = True
        self.per_option_metrics_enabled = True
        self.atm_metric_window = _env_get_int('G6_OPTION_METRIC_ATM_WINDOW', 3)

    def sample(self):
        if not self.process:
            return 0.0, 0.0
        rss_mb = self.process.memory_info().rss / (1024*1024)
        frac = rss_mb / self.total_physical_mb if self.total_physical_mb else 0
        if self._ema is None:
            self._ema = frac
        else:
            self._ema = self.smoothing_alpha * frac + (1 - self.smoothing_alpha) * self._ema
        return rss_mb, self._ema

    def evaluate(self):
        rss_mb, frac_ema = self.sample()
        # Determine raw tier by highest threshold crossed
        raw = self.tiers[0]
        for tier in self.tiers:
            if tier.threshold_mb == 0 and tier.level == 0:
                raw = tier
            else:
                if frac_ema >= tier.threshold_mb:
                    raw = tier
        chosen = raw
        # Hysteresis: only downgrade after sustained recovery
        if raw.level < self.current_level:
            # Must stay below the next lower tier's threshold for recovery_seconds
            # Determine threshold for target downgrade level (raw.level)
            if self._stable_below_start is None:
                self._stable_below_start = time.time()
            elapsed = time.time() - self._stable_below_start
            if elapsed < self.recovery_seconds:
                chosen = [t for t in self.tiers if t.level == self.current_level][0]
            else:
                logger.info(f"Memory pressure downgrade allowed after {elapsed:.0f}s stable below thresholds -> {raw.name}")
                self._stable_below_start = None
        else:
            # Upgrade or same level resets stable counter
            self._stable_below_start = None

        # Mark downgrade pending if raw lower but hysteresis hold
        self._downgrade_pending = raw.level < self.current_level and chosen.level == self.current_level
        if chosen.level != self.current_level:
            logger.warning(f"Memory pressure transition {self.current_level} -> {chosen.level} ({chosen.name}) rss={rss_mb:.1f}MB ema%={frac_ema*100:.1f}")
            prev_level = self.current_level
            self.current_level = chosen.level
            self._last_level_change_ts = time.time()
            self._seconds_in_level_start = self._last_level_change_ts
            if self.current_level < prev_level:
                self._last_downgrade_ts = self._last_level_change_ts
                # Attempt rollback enabling features gradually
                self._maybe_enable_features()
            self.apply_actions(chosen)
        if self.metrics:
            try:
                self.metrics.memory_pressure_level.set(self.current_level)
                # Seconds in level
                self.metrics.memory_pressure_seconds_in_level.set(time.time() - self._seconds_in_level_start)
                self.metrics.memory_pressure_downgrade_pending.set(1 if self._downgrade_pending else 0)
                self.metrics.memory_depth_scale.set(self.depth_scale)
                self.metrics.memory_per_option_metrics_enabled.set(1 if self.per_option_metrics_enabled else 0)
                self.metrics.memory_greeks_enabled.set(1 if self.greeks_enabled else 0)
            except Exception as _e:
                try:
                    from src.error_handling import handle_api_error
                    handle_api_error(_e, component="utils.memory_pressure.metrics_set", context={"stage": "evaluate"})
                except Exception:
                    pass
        return chosen

    def apply_actions(self, tier: PressureTier):
        self.last_actions = tier.actions
        for action in tier.actions:
            if action == 'shrink_cache':
                self._do_shrink_cache()
            elif action == 'reduce_depth':
                self.active_flags['reduce_depth'] = True
            elif action == 'skip_greeks':
                self.active_flags['skip_greeks'] = True
            elif action == 'slow_cycles':
                self.active_flags['slow_cycles'] = True
            elif action == 'drop_per_option_metrics':
                self.active_flags['drop_per_option_metrics'] = True
            if self.metrics:
                try:
                    self.metrics.memory_pressure_actions.labels(action=action, tier=str(tier.level)).inc()
                except Exception as _e:
                    try:
                        from src.error_handling import handle_api_error
                        handle_api_error(_e, component="utils.memory_pressure.metrics_inc", context={"action": action, "tier": str(tier.level)})
                    except Exception:
                        pass
        # Compute depth scale (progressive) based on current level and EMA fraction if available
        self._compute_depth_scale()
        # Apply permanent disable flags
        if self.active_flags['skip_greeks']:
            self.greeks_enabled = False
            if self._greeks_disabled_ts is None:
                self._greeks_disabled_ts = time.time()
        if self.active_flags['drop_per_option_metrics']:
            self.per_option_metrics_enabled = False

    def _do_shrink_cache(self):
        # Attempt to purge registered caches via MemoryManager emergency path
        try:
            from src.utils.memory_manager import get_memory_manager  # type: ignore
            mm = get_memory_manager()
            attempted = mm.emergency_cleanup(reason=f"pressure-level-{self.current_level}")
            logger.info("Shrink cache invoked; purge_attempts=%s", attempted)
        except Exception as _e:
            # Fallback minimal log when MemoryManager not available
            logger.info("Shrink cache action invoked (no MemoryManager available)")
            try:
                from src.error_handling import handle_api_error
                handle_api_error(_e, component="utils.memory_pressure.shrink_cache")
            except Exception:
                pass

    def _compute_depth_scale(self):
        # Map level to scale; if high/critical compute gradient from EMA fraction
        base = 1.0
        if self.current_level == 0:
            base = 1.0
        elif self.current_level == 1:
            base = 0.85
        elif self.current_level == 2:
            base = 0.6
        elif self.current_level == 3:
            base = 0.4
        # Further reduce if EMA extremely high (>95%)
        # (ema fraction approximated by self._ema)
        if self._ema and self._ema > 0.95:
            base *= 0.8
        self.depth_scale = max(0.2, min(1.0, base))

    def effective_strike_window(self):
        # ATM window shrinks with level
        if self.current_level <=1:
            return self.atm_metric_window
        if self.current_level ==2:
            return max(1, int(self.atm_metric_window/2))
        return 1  # critical

    def _maybe_enable_features(self):
        now = time.time()
        # Re-enable Greeks after downgrade if previously disabled and cooldown elapsed
        if not self.greeks_enabled and self._greeks_disabled_ts and (now - self._greeks_disabled_ts) > self.rollback_cooldown:
            self.greeks_enabled = True
            self.active_flags['skip_greeks'] = False
            logger.info("Re-enabled Greeks/IV after cooldown")
        # Re-enable per-option metrics after longer cooldown (2x rollback)
        if not self.per_option_metrics_enabled and self._last_downgrade_ts and (now - self._last_downgrade_ts) > (2 * self.rollback_cooldown):
            self.per_option_metrics_enabled = True
            self.active_flags['drop_per_option_metrics'] = False
            logger.info("Re-enabled per-option metrics after extended cooldown")

    def _load_tiers_from_env(self):
        raw = _env_get_str('G6_MEMORY_PRESSURE_TIERS', '')
        if not raw:
            return DEFAULT_TIERS
        try:
            import json
            data = json.loads(raw)
            tiers = []
            for entry in data:
                tiers.append(PressureTier(
                    name=entry['name'],
                    level=int(entry['level']),
                    threshold_mb=float(entry['threshold']),
                    actions=list(entry.get('actions', []))
                ))
            # Basic validation ensures level uniqueness
            levels = {t.level for t in tiers}
            if len(levels) != len(tiers):
                raise ValueError('Duplicate tier levels')
            return tiers
        except Exception as e:
            logger.error(f"Failed parsing G6_MEMORY_PRESSURE_TIERS; using defaults: {e}")
            try:
                from src.error_handling import handle_data_error
                handle_data_error(e, component="utils.memory_pressure.load_tiers", context={"env": "G6_MEMORY_PRESSURE_TIERS"})
            except Exception:
                pass
            return DEFAULT_TIERS

    # Hooks for collector loop to query
    def should_skip_greeks(self):
        return self.active_flags['skip_greeks'] or not self.greeks_enabled
    def should_reduce_depth(self):
        return self.active_flags['reduce_depth']
    def should_slow_cycles(self):
        return self.active_flags['slow_cycles']
    def drop_per_option_metrics(self):
        return self.active_flags['drop_per_option_metrics'] or not self.per_option_metrics_enabled
