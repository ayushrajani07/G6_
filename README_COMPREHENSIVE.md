## Archived: Comprehensive Architecture & Operations Guide (Stub)

This file has been consolidated into the unified `README.md`.

Rationale:
* Remove duplication & drift risk
* Single onboarding & operations surface
* Easier maintenance of deprecation / migration notes

Canonical source: see top-level `README.md`.

History / diff review:
```
This file was consolidated into the canonical `README.md` on 2025-10-01.
It will be deleted in a subsequent cleanup commit after confirming no external automation references it.
See `README.md` for all architecture, operations, and dashboard documentation.

Historical git history preserved; run:
	git log -- README_COMPREHENSIVE.md
if you need prior revision context.
```

Deprecation Timeline: First archived 2025-10-01 (Release R). Planned removal after R+1 unless external references still point here.

If you reached this file via an outdated link, update bookmarks / docs to reference the canonical README instead.
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
| Continuous | `python scripts/run_orchestrator_loop.py --config config/g6_config.json --interval 60` | Production / long-run collector |
| Single Cycle | `--run-once` | Diagnostics, smoke test, CI check |
| Analytics Startup Only | Enable `features.analytics_startup` + maybe `--run-once` | Quick analytics snapshot without continuous collection |

---
## 12. New Developer-Facing Knobs (2025-09)

### MetricsAdapter dependency injection
For deterministic tests and custom wiring, `MetricsAdapter` now accepts an optional `processor` instance:

- `MetricsAdapter(processor=stub)` uses your instance directly, skipping Prometheus wiring.
- `get_metrics_adapter(processor=stub)` seeds the singleton with your instance on first call.

Production behavior is unchanged when you don’t pass a processor.

### Panels meta control
Panel commits write a `.meta.json` file with the last transaction by default. Configure via:

- `G6_PANELS_ALWAYS_META=1` (default): meta is written on every commit.
- `G6_PANELS_ALWAYS_META=0`: disable meta emission.

The meta payload includes `last_txn_id`, `committed_at` (ISO time), and the list of committed panel names.
| Dummy Provider (if available) | Adjust provider config | Offline testing without live API quota |

Provider Factory (New):
- Primary provider is now created via a simple factory that maps `providers.primary.type` to an implementation.
- Supported types: `kite` (env fallback), `dummy` (offline).
- Usage inside code: `from src.providers.factory import create_provider`; `provider = create_provider(ptype, config)`.
- The orchestrator (`unified_main.py`) already uses the factory; existing direct imports remain compatible.

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
## 16.1 Authentication / Tokens (Updated 2025-09)

Token lifecycle management now supports pluggable providers and headless automation.

### Providers
Located in `src/tools/token_providers/`:

| Name | Purpose | Notes |
|------|---------|-------|
| kite | Real Kite Connect login & token exchange | Browser (Flask) + manual + headless with env `KITE_REQUEST_TOKEN` |
| fake | Deterministic test token | Always returns `FAKE_TOKEN`; no network, good for CI |

Select provider (precedence): CLI `--provider` > env `G6_TOKEN_PROVIDER` > default `kite`.

### Headless Mode
Enable with `--headless` or env `G6_TOKEN_HEADLESS=1`.

Behavior by provider:
- kite: Requires `KITE_REQUEST_TOKEN`; exchanges directly for `KITE_ACCESS_TOKEN` (no browser). Missing request token = fast failure.
- fake: Always succeeds, returns deterministic token.

### Provider Interface
```
validate(api_key: str, access_token: str) -> bool
acquire(api_key: str, api_secret: str, headless: bool = False, interactive: bool = True) -> Optional[str]
```

### Environment Variables
| Variable | Purpose |
|----------|---------|
| KITE_API_KEY | Kite API key |
| KITE_API_SECRET | Kite API secret |
| KITE_ACCESS_TOKEN | Persisted access token (auto-updated) |
| KITE_REQUEST_TOKEN | One-time request token for headless kite flow |
| G6_TOKEN_PROVIDER | Provider (`kite` or `fake`) |
| G6_TOKEN_HEADLESS | `1` forces headless mode |

### Examples (PowerShell)
Headless fake:
```
$env:KITE_API_KEY='dummy'; $env:KITE_API_SECRET='dummy'; $env:G6_TOKEN_PROVIDER='fake'; $env:G6_TOKEN_HEADLESS='1'
python -m src.tools.token_manager --no-autorun
```

Headless kite:
```
$env:KITE_API_KEY='real'; $env:KITE_API_SECRET='real_secret'
$env:KITE_REQUEST_TOKEN='abcd1234'; $env:G6_TOKEN_HEADLESS='1'
python -m src.tools.token_manager --no-autorun
```

### Fallback UX
If provider=`kite` and not headless, legacy interactive menu remains as fallback after provider acquisition failure. Non-kite or headless paths do not offer the menu.

### Fast-Exit Behavior (Non-Interactive)
When a valid token is already present and you disable autorun via `--no-autorun` (or omit autorun flows) the manager will:
- Immediately exit 0 without prompting if either headless mode is active OR the selected provider is not `kite`.
- Only show the "Start G6 Platform now?" prompt for the interactive kite provider path.
This makes CI and scripted headless runs deterministic (no stdin reads). Tests rely on this fast-exit path (`tests/test_token_providers.py`).

### Tests
See `tests/test_token_providers.py` for fake provider validation and headless kite failure path.

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
- 2025-09-28: Token provider abstraction (`kite`, `fake`), headless mode, and non-interactive fast-exit for headless/non-kite providers when autorun disabled.
- 2025-09-16: Initial comprehensive architecture guide authored.

---
## 20. Quick Reference Cheat Sheet
| Action | Command |
|--------|---------|
| Single test cycle | `python scripts/run_orchestrator_loop.py --config config/g6_config.json --interval 60 --cycles 1` |
| Fancy banner + analytics | `set G6_FANCY_CONSOLE=1` (or PowerShell `$env:G6_FANCY_CONSOLE=1`) then run main |
| Enable Greeks & IV | Set in config `greeks.enabled=true` + `estimate_iv=true` |
| View metrics (curl) | `curl http://localhost:<port>/metrics` |
| Add new index | Edit `config/g6_config.json` -> restart process |
| Tail logs (PowerShell) | `Get-Content g6_platform.log -Wait` |

---
End of document.
