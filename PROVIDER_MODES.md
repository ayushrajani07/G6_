Provider Modes & Fallback Behavior
=================================

Overview
--------
The platform supports multiple provider "modes" to keep the orchestrator and collectors running even when the real market data provider (e.g. Kite) is unavailable or only partially configured. This document explains each mode, how the system transitions between them, and what functionality / limitations apply.

Modes Summary
------------
1. Real Provider (Kite / Primary)
   - Source: `src/providers/factory.py:create_provider` returns a fully–featured provider (e.g. `KiteProvider`).
   - Capabilities: index LTP, ATM strike, option instruments, quotes, expiry resolution, complete calendar.
   - Requirements: Valid credentials in environment (.env) + dependencies installed (kiteconnect, etc.).
   - Indicators: Log lines showing successful auth / token validation and non-synthetic prices per index.

2. Composite / Adapter Provider
   - Source: Factory may compose multiple underlying providers (e.g. mock + kite) for resilience.
   - Capabilities: Same interface surface; gracefully degrades if one delegate missing.
   - Indicators: Logs referencing `composite_provider` selection and selective fallback of API calls.

3. Fallback Providers Shim (Resilience Layer)
   - Source: Defined inside `src/orchestrator/components.py` when optional imports fail. Constructs a minimal `Providers` object exposing only a subset of methods (`get_index_data`, `get_atm_strike`, `get_ltp`).
   - Capabilities: Provides basic index price access (may use simple deterministic placeholder values) allowing downstream strike building logic to execute.
   - Limitations: Does NOT implement `resolve_expiry`, `get_option_instruments`, real quote fetching, or corporate actions.
   - Indicators: Log messages like `Using fallback Providers shim` and uniform or smoothly increasing index prices.

4. Minimal Primary Provider (Factory Lambda None Case)
   - Source: If the optional import block downgraded `create_provider` to a lambda returning None, a late re-import in `components.py` attempts recovery (mirrors CsvSink recovery). Until recovery, collectors may see `providers=None` (guarded early return with `no_providers` summary entries).

Automatic Recovery Logic
------------------------
`components.py` performs a second-chance import for two critical factory constructs:

* CsvSink: If it degraded to a plain `object`, we re-import the real class.
* create_provider: If it remains a lambda sentinel (`<lambda>` name), we attempt to import the real factory. Success is logged.

Expiry Resolution Short-Circuit
-------------------------------
Because fallback providers may lack `resolve_expiry`, `unified_collectors._resolve_expiry` now short-circuits when an expiry rule is already an ISO date literal (YYYY-MM-DD). This eliminates noisy errors when driving synthetic or partially populated datasets that already supply explicit expiry dates in configuration.

How To Force Real Provider Mode
-------------------------------
1. Install provider dependencies (example):
   - kiteconnect
2. Set required credentials in `.env` (example keys):
   - KITE_API_KEY=your_key
   - KITE_API_SECRET=your_secret
   - (If using a refresh/token flow ensure the access token bootstrap logic is satisfied.)
3. (Optional) Clear any stale placeholder state:
   - Remove or ignore legacy placeholder runtime_status files if present.
4. Restart the orchestrator script (`scripts/run_orchestrator_loop.py`) so that component bootstrap runs with the restored factory and credentials.

Diagnosing Current Mode
-----------------------
Check logs at startup:
* If you see `Recovered real create_provider` followed by provider-specific initialization logs — you are in Real Provider mode.
* If you see repeated `resolve_expiry` debug lines with explicit ISO dates and no provider errors — you are likely in Fallback Providers (with ISO short-circuit working) or Real mode with simple date rules.
* If strikes build successfully but all option instrument fetches return empty and index prices are constant/patterned — you are still in Fallback Providers mode.

Limitations & Next Steps
------------------------
* Fallback mode does not currently simulate an options chain; only index & strike scaffolding logic can be exercised.
* Consider adding a MockOptionChain provider to enable local end‑to‑end analytics without external connectivity.
* Metrics labeling could include a provider_mode gauge (TODO) to surface mode transitions in Prometheus.

Change Log Context
------------------
These resilience layers were introduced to stabilize the orchestrator startup sequence, avoid crashes during optional import failures, and allow iterative development of collection logic without blocking on external provider availability.

Glossary
--------
ATM Strike: The nearest strike to current LTP used as center for building a symmetric strike grid.
Expiry Rule: A semantic token like `this_week`, `next_week`, or a literal ISO date `2025-10-31` describing target expiry.
Synthetic Quotes (Removed): Prior deterministic placeholder quote generation mechanism eliminated to avoid silent fabricated data. Any remaining placeholder index prices exist only for basic liveness during startup and are not emitted as option quotes.

---
For questions or to extend provider capabilities, see `src/providers/` and `src/orchestrator/components.py`.