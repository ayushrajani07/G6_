# G6 Comprehensive Architecture & Operations Guide

> This document is the authoritative deep-dive for the G6 Options Data Collection & Analytics Platform. It complements (not replaces) the top-level `README.md` and focused docs under `docs/`.

---
## 1. High-Level Purpose
G6 ingests live option chain data for configured Indian index derivatives (NIFTY, BANKNIFTY, FINNIFTY, etc.), normalizes & enriches them (IV estimation, Greeks, PCR, masks), persists structured snapshots (CSV + optional InfluxDB), and exposes rich Prometheus metrics for observability. It is designed for:
- Deterministic minute (or custom) collection cycles
- Extensible analytics stack (PCR, Greeks, breadth, participants, spreads)
- Progressive degradation under memory / API stress
- Low-friction ops for a single operator but scalable to small teams

---
## 2. Runtime Architecture Overview
```
+------------------+        +------------------+        +-------------------+
|  Config Loader   |  -->  |  Orchestrator    |  -->  |   Collectors       |
|  (JSON + ENV)    |        | (unified_main)   |        | (per index/expiry) |
+------------------+        +------------------+        +-------------------+
          |                          |                           |
          v                          v                           v
+------------------+        +------------------+        +-------------------+
|  Health Monitor  |  -->  |  Metrics/Prom     |  -->  |  Storage Sinks     |
|  (components)    |        |  (exporter)      |        |  (CSV / Influx)    |
+------------------+        +------------------+        +-------------------+
          |                          |                           |
          v                          v                           v
+------------------+        +------------------+        +-------------------+
|  Analytics Layer |  -->  |  Live Panels      |  -->  |  Downstream (Graf) |
|  (Greeks, PCR)   |        |  (startup/live)   |        |  Dashboards        |
+------------------+        +------------------+        +-------------------+
```
Key runtime phases per cycle:
1. Config & environment precedence resolution
2. Health initialization & provider readiness check
3. (Optional) Startup analytics & fancy banner rendering
4. Collection cycle dispatch (parallel/sequential depending on implementation)
5. Per-index expiry resolution & strike list generation
6. Option chain fetch -> enrichment -> analytics (IV & Greeks) -> validation
7. Persistence to sinks (CSV / Influx)
8. Metrics update & live panel refresh
9. Sleep until next interval or graceful shutdown if `--run-once`

---
## 3. Detailed Component Inventory
| Layer | Path(s) | Responsibilities |
|-------|---------|------------------|
| Entry / Orchestration | `src/unified_main.py` | CLI parsing, feature toggles, startup banner, main loop, graceful shutdown |
| Config System | `src/config/config_loader.py`, `src/config/config_wrapper.py`, `src/config/validator.py` | Load + merge + validate JSON config, fallback defaults, environment overrides |
| Providers Facade | `src/collectors/providers_interface.py`, `src/broker/kite_provider.py` | Uniform interface for underlying API provider(s); expiry resolution; instrument metadata |
| Collectors | `src/collectors/unified_collectors.py`, `src/collectors/enhanced_collector.py` | Minute-cycle orchestration, option fetching, pipeline coordination |
| Analytics Core | `src/analytics/option_chain.py`, `src/analytics/option_greeks.py`, `src/analytics/market_breadth.py` | PCR computation, max pain, IV & Greeks, breadth metrics |
| Storage | `src/storage/csv_sink.py`, `src/storage/influx_sink.py` | Idempotent writes, schema evolution, path partitioning |
| Metrics | `src/metrics/metrics.py` | Prometheus metric registration & update helpers, memory pressure adaptation |
| Health / Monitoring | `src/health/monitor.py`, `src/health/health_checker.py` | Component status, readiness gating, periodic checks |
| Console Experience | `src/logstream/pretty_startup.py`, `src/logstream/live_panel.py` | Startup panel & per-cycle status panel with ASCII/Unicode fallbacks |
| Utilities | `src/utils/*` | Time, symbol, resilience, market hours, rate limiting, circuit breaker, logging utilities |
| Tools / Ops Scripts | `src/tools/*.py`, `scripts/*.py` | Token management, config creation, diagnostics, overlays generation, memory watchdog |
| Web (Deprecated) | `src/web/dashboard/*` | Legacy dashboard (retained for reference; superseded by Grafana) |

---
## 4. Data & Logic Flow (Per Cycle)
```
[Start Cycle]
  -> Check market hours & global circuit breakers
  -> For each enabled index:
        Resolve expiries (rule normalization: this_week, next_week, this_month, next_month)
        Determine ATM strike; build strike universe (ATM ± configured ITM/OTM counts)
        Fetch raw option quotes (batch or per-strike)
        Validate & sanitize (remove stale / zero OI anomalies)
        (Optional) Estimate IV for unresolved contracts (Newton-Raphson)
        (Optional) Compute Greeks using estimated/resolved IV
        Aggregate PCR per expiry + completeness masks
        Persist per-option rows (CSV/Influx) & overview snapshot
        Update per-index metrics (success, timings, counts)
  -> Global metrics & live panel update
  -> Sleep until next interval
[End Cycle]
```
Error Handling / Resilience:
- Circuit breaker & retry wrappers in `utils/resilience.py`
- Memory pressure triggers gauge adjustments (dropping high-cardinality metrics first)
- Partial failures recorded per index without aborting entire cycle unless global invariants violated

---
## 5. File & Script Justification
| Script/File | Why It Exists | Operational Justification |
|-------------|---------------|---------------------------|
| `scripts/diagnose_expiries.py` | Debug expiry rule resolution | Quickly validate weekly/monthly mapping without full run |
| `scripts/generate_overlay_layout_samples.py` | Sample overlay generation | Data artifact preview for visual workflows |
| `scripts/inspect_options_snapshot.py` | Inspect raw snapshot | Open a single cycle capture for QA |
| `scripts/memory_watchdog.ps1` | Windows memory guard | Proactive restart or logging for memory leaks |
| `scripts/plot_weekday_overlays.py` | Visualization helper | Exploratory analytics on weekday option overlays |
| `scripts/quick_provider_check.py` | Smoke provider connectivity | Fast readiness check before full orchestration |
| `scripts/dev_tools.py summary` | Terminal summary | Preferred entrypoint for live view |
| `scripts/start_all.ps1` | Convenience orchestrator | One-shot start Prometheus + Grafana + platform |
| `src/tools/token_manager.py` | Manage auth tokens | Centralizes refresh logic to avoid scattered scripts |
| `src/tools/check_kite_file.py` | Validate instruments file | Prevent mismatches between provider metadata & runtime |
| `src/tools/create_config.py` | Scaffold config | Fast onboarding for new environment |
| `src/utils/memory_pressure.py` | Adaptive scaling logic | Keeps process healthy under load |
| `src/utils/circuit_breaker.py` | Failure containment | Avoid cascading provider errors |
| `src/logstream/live_panel.py` | Runtime situational awareness | Replaces legacy ad-hoc printouts with structured view |

---
## 6. Configuration & Feature Toggles
Precedence (highest first): CLI > Environment Variables > JSON Config > Defaults.
Core toggle domains:
- Analytics Startup (`features.analytics_startup` / `--analytics`)
- Fancy Banner (`G6_FANCY_CONSOLE` / `console.fancy_startup`)
- Live Panel (`G6_LIVE_PANEL` / `console.live_panel`)
- ASCII Enforcement (`G6_FORCE_ASCII` / `G6_FORCE_UNICODE` / `console.force_ascii`)
- Concise Logging (`G6_CONCISE_LOGS`, `G6_VERBOSE_CONSOLE`, `G6_DISABLE_MINIMAL_CONSOLE`)
- Greeks & IV (`greeks.enabled`, `greeks.estimate_iv`)

Example holistic config block:
```json
{
  "features": { "analytics_startup": true },
  "console": { "fancy_startup": true, "live_panel": true, "force_ascii": true },
  "greeks": { "enabled": true, "estimate_iv": true, "risk_free_rate": 0.055 },
  "index_params": { "NIFTY": { "expiries": ["this_week","next_week"], "strikes_itm": 10, "strikes_otm": 10, "enable": true } }
}
```
Further detail: see `docs/CONFIG_FEATURE_TOGGLES.md`.

---
## 7. Metrics & Dashboards
Prometheus exporter is embedded (see `src/metrics/metrics.py`). Grafana can be provisioned using the JSON dashboards under `grafana/` (if present) and Prometheus rules in root (`prometheus_rules.yml`).

Dashboard Layers:
1. Collection Health (cycle duration, success rate, last timestamp)
2. Index Detail (PCR, processed counts, ATM strike drift)
3. Resource & Pressure (memory levels, scaling actions)
4. Greeks / IV Quality (IV solve success %, avg iterations, percentile latencies if extended)
5. Storage Throughput (CSV / Influx write counts & errors)

Recording Rules (selected):
- `g6_memory_pressure_is_level`, `g6_memory_pressure_transition` (state machine helpers)
- Derivations of time since last success, upgrade/downgrade rates

Alert Examples:
- Collection stalled: `time() - g6_last_success_cycle_unixtime > 180` (pending implementation of rule convenience wrappers)
- Memory critical: `g6_memory_pressure_level >= 3`
- IV failure surge: `increase(g6_iv_estimation_failure_total[10m]) > 50`

---
## 8. Storage Schema Evolution Strategy
Principles:
- Backwards additive: new columns appended; old not repurposed
- Overview table masks preserve interpretability (bit flags rather than expanding dynamic columns)
- Influx measurement separation: `option_data` vs `options_overview` for cardinality control
- Rho addition followed existing naming pattern to avoid ambiguous side (ce_/pe_ prefixes in some aggregations)

CSV Partitioning Layout (example):
```
<data_root>/<INDEX>/<EXPIRY_KEY>/<STRIKE_BUCKET>/<DATE>.csv
```
Overview rows appended to aggregated file per index/day (or separate directory for clarity).

---
## 9. Error Handling & Resilience Patterns
| Pattern | Location | Purpose |
|---------|----------|---------|
| Retry with backoff | `utils/resilience.py` | Tolerate transient provider/network issues |
| Circuit breaker | `utils/circuit_breaker.py` | Avoid hammering failing upstreams |
| Memory pressure scaling | `utils/memory_pressure.py` | Drop high-cardinality metrics first |
| Data quality validation | `utils/data_quality.py` | Filter or flag anomalous quotes |
| Health checks registry | `health/health_checker.py` | Standardize component readiness |

Escalation Outcomes:
- Level 1: disable per-option latency-heavy metrics
- Level 2: suspend Greeks computation
- Level 3: reduce strike depth / expiry breadth (planned extension)

---
## 10. Console Panels & UX
Startup Panel (Fancy): Multi-line status (version, indices, readiness, components, checks, metrics meta). Falls back to simple banner if:
- `G6_DISABLE_STARTUP_BANNER=1`
- Build error occurs
- Not a TTY (depending on implementation) and config disallows forced display

Live Panel: Periodic summary (cycle time, throughput, success %, memory, CPU, API latency). NA values imply missing bridging of per-index state (roadmap item).

ASCII Mode: Windows console encoding issues mitigated by forced ASCII via config or `G6_FORCE_ASCII=1`. Unicode allowed if `G6_FORCE_UNICODE=1`.

---
## 11. Operational Run Modes
| Mode | How | Use Case |
|------|-----|----------|
| Continuous | `python -m src.unified_main` | Production / long-run collector |
| Single Cycle | `--run-once` | Diagnostics, smoke test, CI check |
| Analytics Startup Only | Enable `features.analytics_startup` + maybe `--run-once` | Quick analytics snapshot without continuous collection |
| Dummy Provider (if available) | Adjust provider config | Offline testing without live API quota |

---
## 12. Onboarding a New Index
Steps:
1. Add entry to `index_params` with expiries & strike depth
2. Confirm provider supports symbol mapping (update `symbol_utils` if needed)
3. Run `--run-once` to verify sample collection
4. Validate overview PCR & masks populate
5. Add to Grafana dashboard variable (if templated)

---
## 13. Security & Secrets Handling
- Tokens never checked in: ignored via `.gitignore` (`*token*.json` etc.)
- Use environment variables or separate secrets file outside repo root
- Avoid logging raw auth headers (sanitizer strips non-ASCII + sensitive patterns planned)

---
## 14. Testing Strategy
Existing tests in `tests/` target time utilities, metrics API rate calculations, memory pressure behaviors. Recommended additions:
- Expiry resolution table-driven tests
- IV solver convergence edge cases
- Data quality filter scenarios (zero/negative OI, stale timestamps)
- Console panel rendering snapshot tests (ASCII vs Unicode)

---
## 15. Deployment & Observability Stack
| Component | Default | Notes |
|-----------|---------|-------|
| Prometheus | `prometheus.yml` | Scrape exporter endpoint (port configured in metrics module) |
| Grafana | Provision dashboards from `grafana/` | Recording & alert rules support visualizations |
| Alerting | `alertmanager.yml` (if used) | Wire to email/ChatOps for staleness & memory pressure |

---
## 16. Known Limitations
- Per-index state not fully integrated into live panel (shows NA in some fields)
- Memory pressure tier 3 (strike depth scaling) not yet implemented
- No persistence compaction / archival rotation logic currently
- Multi-provider fallback not finalized (single primary provider assumed)
- Web dashboard code around but deprecated—may confuse new operators

---
## 17. Roadmap (Prioritized)
| Priority | Item | Rationale |
|----------|------|-----------|
| High | Live panel per-index wiring | Close observability gap without Grafana |
| High | Automated data retention / pruning | Prevent unbounded disk growth |
| High | Robust expiry calendar service | Handle exchange holidays / special expiries |
| Medium | Vol surface interpolation module | Advanced analytics layer |
| Medium | Alertpack (prebuilt Prom alerts) | Faster operational readiness |
| Medium | CI pipeline with lint + tests | Quality gate for contributions |
| Low | Strike depth adaptive scaling (tier 3) | Memory resilience completeness |
| Low | Multi-provider abstraction | Redundancy & failover |

---
## 18. Glossary
| Term | Meaning |
|------|---------|
| PCR | Put/Call Ratio: total put OI / total call OI per expiry |
| ATM Strike | Closest listed strike to underlying spot price |
| IV | Implied Volatility derived from option premium & BS model |
| Greeks | Sensitivities (Delta, Gamma, Theta, Vega, Rho) computed from BS |
| Mask Bits | Bitwise flags representing expected vs collected expiries |
| Overview Snapshot | Aggregated single-row summary per index per cycle |

---
## 19. Change Log (Doc)
- 2025-09-16: Initial comprehensive architecture guide authored.

---
## 20. Quick Reference Cheat Sheet
| Action | Command |
|--------|---------|
| Single test cycle | `python -m src.unified_main --run-once` |
| Fancy banner + analytics | `set G6_FANCY_CONSOLE=1` (or PowerShell `$env:G6_FANCY_CONSOLE=1`) then run main |
| Enable Greeks & IV | Set in config `greeks.enabled=true` + `estimate_iv=true` |
| View metrics (curl) | `curl http://localhost:<port>/metrics` |
| Add new index | Edit `config/g6_config.json` -> restart process |
| Tail logs (PowerShell) | `Get-Content g6_platform.log -Wait` |

---
End of document.
