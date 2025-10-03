# Kite Provider Modularization Plan

(This document generated 2025-09-30; Phase 1 will extract expiry logic.)

## Current Monolith Responsibilities
1. Env/settings parsing (timeouts, TTL, concise, trace flags)
2. Credential sourcing and auth refresh
3. KiteConnect client lifecycle
4. Instrument universe fetch & caching (synthetic fallback)
5. LTP/Quote retrieval with retry & quality guard + synthetic fallback
6. Expiry discovery + caching + resolution rules
7. Option instrument selection (prefilter, indexing, filtering, fallbacks, contamination detection)
8. Synthetic generation utilities (instruments, quotes, expiries)
9. Metrics-style counters (cache hits, synthetic counts)
10. Health probe
11. Dummy provider implementation
12. TRACE diagnostic emission

## Target Package Layout (incremental)
```
src/broker/kite/
  __init__.py
  settings.py
  auth.py
  client.py
  cache.py
  instruments.py
  quotes.py
  expiries.py
  options.py
  synthetic.py
  health.py
  tracing.py
  types.py
  dummy_provider.py
```

## Phase Breakdown & Status
- Phase 1 (DONE): Extract expiry resolution (get_expiry_dates + resolve_expiry) to `expiries.py`; provider delegates.
- Phase 2 (DONE): Synthetic generators (instruments, quotes) to `synthetic.py`; fallback paths import helpers.
- Phase 3 (DONE): `settings.py` central env snapshot; replaced scattered `os.environ` lookups with `Settings` dataclass.
- Phase 4 (DONE): Introduced `ProviderState` (`state.py`) consolidating caches & counters; `KiteProvider` now holds `_state` with backward-compatible attribute exposure.
- Phase 5 (DONE): `client.py` + `auth.py` isolate KiteConnect lifecycle & auth error classification.
- Phase 6 (DONE): Extracted `option_instruments` to `options.py` with staged helpers:
    * `prefilter_option_universe` (root/name/prefix clamp + safety valve)
    * `StrikeMembership` wrapper (delegates to existing `strike_index` builder)
    * `build_preindex` (expiry,strike,type bucketization)
    * `match_options` (core accept_option loop + contamination capture)
    * `apply_expiry_fallbacks` (forward/backward strategies gated by settings)
    * `option_instruments` (public entrypoint: cache fast-path, fetch, assemble, log, cache populate)
  Provider method now thin delegator; legacy defensive bootstraps preserved for test subclasses bypassing `__init__`.
- Phase 7 (DONE): Extracted `get_ltp` & `get_quote` to `quotes.py` with parity logic:
    * Normalization + quality guard (empty/all-zero response)
    * Auth failure detection & rate-limited fallback logs
    * Synthetic fallback via `synthetic.py` utilities (ltp + quote fabrication)
    * Counters `_synthetic_quotes_used` & `_last_quotes_synthetic` updated externally via provider object
  Provider methods reduced to delegators; dummy provider unaffected except for added minimal `option_instruments` stub earlier.
- Phase 8 (DONE): Relocated `DummyKiteProvider` to `dummy_provider.py`; reconstructed `kite_provider.py` as a lean facade:
  * Removed embedded dummy class & residual monolithic fragments.
  * Added `from_env` constructor + `close()` no-op for factory compatibility.
  * Reintroduced minimal constants (`INDEX_MAPPING`, `POOL_FOR`) and concise flag handling.
  * Ensured delegation to extracted modules (expiries, options, quotes) and preserved synthetic / cache counters via `_state`.
  * All tests green post-refactor (452 passed, 23 skipped).
- Phase 9 (DONE): Centralized TRACE/diagnostic emission via `tracing.py`:
  * Added `trace`, `rate_limited_trace`, `trace_kv`, and runtime enable/disable (`set_enabled`).
  * Unified env gating: `G6_TRACE_COLLECTOR`, `G6_QUIET_MODE`, `G6_QUIET_ALLOW_TRACE` respected in one place.
  * Replaced ad-hoc TRACE emissions in `options.py` (prefilter, sample match set, summary) with structured events.
  * Added focused tests (`test_tracing.py`) covering enabled, disabled, quiet suppression, quiet override, runtime toggle (5 tests added).
  * Preserved legacy log prefix format (`TRACE <event> | ...`) for downstream scrapers while moving to structured key ordering for determinism.
  * No behavior changes for callers; only internal emission mechanics simplified. Full suite remained green (now 457 passed, 23 skipped including new tracing tests).
- Phase 10 (DONE): Final cleanup & deprecation shims in `kite_provider.py`:
  * Added runtime DeprecationWarning on instantiation (signals shift to helper-based diagnostics).
  * Introduced `provider_diagnostics()` for structured counters / cache snapshot.
  * Added property shims (`option_cache_hits`, `option_cache_misses`, `instruments_cache`, `expiry_dates_cache`, `synthetic_quotes_used`, `last_quotes_synthetic_flag`) emitting one-time DeprecationWarnings.
  * Encouraged migration away from direct internal attribute access toward stable helper API.
  * Full suite: 457 passed, 23 skipped (no regressions; only added warnings in two tests exercising instantiation).

## Post-Phase Completion (2025-10-01)
All planned phases (1–10) have been implemented in the repository. Additional hardening steps just performed:
- Added diagnostics regression tests (`test_kite_provider_diagnostics.py`) to lock in `provider_diagnostics()` contract & deprecation warning one-shot behavior.
- Introduced `src/broker/kite/health.py` with a minimal `basic_health` helper to centralize future health enrichment (latency/auth freshness) away from provider core.
- Verified module layout matches target (auth, client, expiries, options, quotes, settings, state, synthetic, tracing, types, health, dummy_provider).

### Deprecation Timeline (Proposed)
| Feature | Current Status | Planned Removal | Migration Path |
|---------|----------------|-----------------|----------------|
| Direct property access (`option_cache_hits`, etc.) | Emits one-time DeprecationWarning | Earliest 2025-11 after 2 release notes | Use `provider_diagnostics()` |
| Direct instantiation warning (`KiteProvider(...)`) | DeprecationWarning (informational) | No removal (constructor retained) | None required |
| Legacy internal caches access (`provider._state.*`) | Internal (unsupported) | N/A | Use `provider_diagnostics()` + future typed interfaces |

### Next Optional Enhancements
- Add auth freshness fields (token age / expiry delta) to `provider_diagnostics()`.
- Emit structured metrics for option cache hit ratio (expose via Prometheus if not already).
- Consider splitting synthetic generation toggles into `synthetic.py` feature flags for easier test matrix control.

### Context Manager & Diagnostics (2025-10-01 Update)
`KiteProvider` now implements `__enter__/__exit__`, allowing safe usage patterns:
```python
from src.broker.kite_provider import KiteProvider

with KiteProvider.from_env() as kp:
  ins = kp.get_instruments('NFO')
  diag = kp.provider_diagnostics()
  # ... use provider
```
Current `provider_diagnostics()` keys (stable set):
```
option_cache_size, option_cache_hits, option_cache_misses,
instruments_cached, expiry_dates_cached,
synthetic_quotes_used, last_quotes_synthetic, used_instrument_fallback,
token_age_sec, token_time_to_expiry_sec
```
`token_age_sec` / `token_time_to_expiry_sec` may be `null` (JSON) / `None` (Python) when underlying client does not expose timestamps.

This section will be pruned once documentation migrates to a permanent developer guide page.

## Safety & Testing
Add/augment tests for: expiry resolution, synthetic fallback, option selection coverage, cache hit/miss counters, contamination warnings, health states.

## Immediate Action (Phase 1)
Create expiries.py exporting:
- get_expiry_dates(provider, index_symbol)
- resolve_expiry_rule(provider, index_symbol, rule)
Then modify KiteProvider.resolve_expiry + DummyKiteProvider.resolve_expiry to delegate.

## Notes / Phase 4 Addendum
- ProviderState exposes helper methods for option cache day rollover, invalidation, and a lightweight summary.
- `KiteProvider` maintains legacy attribute names for test subclasses that bypass `__init__` (defensive guard retained in `option_instruments`).
- Subsequent phases will gradually replace direct attribute reads with `_state` usages before finally removing legacy aliases.
- No external API changes introduced so far; all phases maintain backward compatibility.
