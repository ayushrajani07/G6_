# G6 Development Guidelines & Future Enhancements

> Audience: Contributors & maintainers. This document catalogs architectural weak links, development precautions, and prioritized enhancement recommendations.

---
## 1. Architectural Weak Links (Current)
| Area | Weakness | Risk | Notes |
|------|----------|------|-------|
| Live Panel State | Incomplete per-index wiring (NA fields) | Operator confusion / reduced at-a-glance insight | Implement structured state export post-cycle |
| Memory Pressure Tier 3 | Unimplemented dynamic strike/expiry contraction | Potential OOM if upstream symbol set expands | Design scaling heuristics tied to pressure progression |
| Data Retention | No built-in pruning | Disk exhaustion over long horizon | Add retention policy engine or external cron recipe |
| Provider Abstraction | Single provider assumption | Vendor lock-in / failover gap | Introduce provider registry & fallback sequencing |
| Web Dashboard Code | Deprecated remnants | Codebase noise & user confusion | Plan removal or isolation into legacy branch |
| IV Solver Bounds | Static bounds & iterations | Divergence for exotic market regimes | Adaptive bounds based on underlying realized vol |
| Error Taxonomy | Ad-hoc error_type labels | Inconsistent metrics correlation | Central enum & mapping layer |
| Config Validation Depth | Basic type/shape checks | Runtime surprises on new nested sections | Strengthen schema (jsonschema or pydantic) |
| Logging Sanitization | Partial ASCII fallback | Possible leakage of structured sensitive tokens | Add pattern-based redaction layer |
| Parallelism Strategy | Potential underutilization / overfetch | Reduced throughput in high-latency scenarios | Evaluate async or batched parallel fetch |
| Retry Logic | Generic backoff | Suboptimal under burst provider rate limits | Implement jitter + rate-limit aware delays |

---
## 2. Development Precautions
1. Backwards Compatibility: Never repurpose existing CSV column names; append new ones.
2. Metrics Stability: Avoid renaming existing Prometheus metrics; add new labels only if cardinality impact reviewed.
3. Cardinality Control: Gate any new per-option metric behind memory pressure awareness; test with large strike universes.
4. Config Evolution: Update `validator.py` and `README_COMPREHENSIVE.md` together; document defaults explicitly.
5. Error Handling: Wrap provider calls with resilience utilities; never allow an exception in one index to abort the whole cycle unless integrity-critical.
6. Timezone Consistency: Use UTC internally where possible; if local exchange time is needed, centralize conversion.
7. Performance Profiling: Add lightweight timing gauges before introducing heavier analytics (e.g., surfaces, spread builders).
8. Dependency Hygiene: Pin versions for critical numeric libs to avoid drift-induced calculation divergence.
9. Testing Scope: For numerical routines (IV, Greeks), add regression fixtures; verify solver iteration counts remain within historical norms.
10. Logging Discipline: Prefer structured context summarization rather than dumping large JSON blocks per cycle.
11. Security: Keep token paths / secrets out of repo; ensure new scripts respect `.gitignore` patterns.
12. Windows Compatibility: Preserve ASCII fallback logic; test ANSI color toggles; avoid hardcoding POSIX-only paths.
13. Resource Cleanup: Any new thread or async loop must have graceful shutdown integration.

---
## 3. Coding Standards (Lightweight)
- Language: Python 3.11+; prefer type hints (PEP 484) in new/modified modules.
- Style: Black-compatible formatting; meaningful docstrings for public functions.
- Imports: Group standard lib / third-party / local; avoid wildcard imports.
- Error Messages: Action-oriented ("Retrying fetch..."), include index & expiry context.
- Logging Levels: DEBUG (verbose internals), INFO (cycle summaries), WARNING (recoverable anomalies), ERROR (data loss risk), CRITICAL (process viability).

---
## 4. Tests & Quality Gates
Minimum additions for new feature:
| Category | Requirement |
|----------|------------|
| Unit Tests | Core logic & edge cases covered |
| Regression | Numerical outputs stable (IV/Greeks) |
| Performance (optional) | Measurement for latency-sensitive additions |
| Lint | Run ruff/flake8 (add CI) |

Suggested future: GitHub Actions workflow executing: install deps → run pytest (with `--maxfail=1`) → export coverage badge.

---
## 5. Future Enhancements (Detailed)
| Category | Enhancement | Description | Benefit |
|----------|------------|-------------|---------|
| Observability | Per-index live panel state export | Structured state bridging to panel | Faster operator feedback |
| Storage | Retention & Compaction Service | Age-based rollups & archival | Disk sustainability |
| Analytics | Vol Surface Builder | Interpolate arbitrage-free surface | Advanced modeling |
| Analytics | Spread & Strategy Simulator | Evaluate multi-leg strategy Greeks & P/L | User value add |
| Reliability | Multi-Provider Fallback | Retry alt provider on failures | Higher availability |
| Resilience | Adaptive IV Solver Bounds | Dynamic bounds from realized vol stats | Fewer solver failures |
| Config | Rich Schema Validation | jsonschema or pydantic based enforcement | Earlier failure detection |
| Security | Log Redaction Filters | Mask token-like patterns | Lower leakage risk |
| Performance | Async Collection Layer | Non-blocking I/O for API calls | Lower cycle duration |
| Alerts | Packaged Alert Rules | Deployable default alert set | Faster production readiness |
| Compression | Automatic Old CSV Compression | ZIP or parquet conversion | Reduce footprint |
| CLI | Subcommand Interface | `g6 collect`, `g6 analyze`, etc. | More discoverable UX |
| Docs | Architecture Diagrams (mermaid) | Auto-generated diagrams in docs | Clarity for new devs |
| Metrics | Derived Volatility Drift | Track shift from previous cycle | Surface instability |
| Memory | Tier 3 Strike Depth Scaling | Drop far OTM dynamically | Prevent OOM |
| Testing | Synthetic Market Generator | Deterministic chains for tests | Stable reproducibility |

---
## 6. Contribution Workflow (Proposed)
1. Branch naming: `feat/`, `fix/`, `doc/`, `ops/` prefixes.
2. Open PR with concise summary & risk assessment.
3. Ensure tests green; add/update docs.
4. Tag reviewers with domain expertise (analytics / storage / infra).
5. Squash merge preserving meaningful commit message.

---
## 7. Release & Versioning
Adopt semantic versioning (semver):
- MAJOR: Backwards-incompatible CSV/metric changes
- MINOR: Additive features, new metrics, new columns
- PATCH: Bug fixes, performance improvements

Tag example: `v0.2.0` after adding live panel per-index wiring.

---
## 8. Risk Mitigation Strategies
| Risk | Mitigation |
|------|-----------|
| Provider API outage | Implement multi-provider fallback & exponential backoff |
| Disk saturation | Automate retention + monitoring of disk usage metrics |
| Memory leak in solver | Periodic memory sampling + pressure-based restart triggers |
| Incorrect Greeks due to model drift | Add sanity bounds; cross-validate vs external library tests |
| High cardinality explosion | Guard new labels; dynamic disabling under pressure |

---
## 9. Decommission / Cleanup Plan
If future architecture replaces current collectors:
1. Freeze current branch (tag `legacy-collector`)
2. Migrate metrics to compatibility layer
3. Provide migration script for CSV -> new format (if needed)
4. Remove deprecated code after one minor version cycle

---
## 10. Open Questions (To Decide)
| Topic | Question |
|-------|----------|
| Persistence | Move to Parquet for columnar efficiency? |
| Analytics | Introduce SABR / local vol modeling? |
| Scaling | Horizontal sharding by index vs vertical scaling? |
| Security | Vault integration for tokens? |
| CLI | Should we create a `g6` console entry point? |

---
## 11. Tracking & Documentation Discipline
- Every new metric: update `docs/METRICS.md`.
- Every new toggle: update `docs/CONFIG_FEATURE_TOGGLES.md` + `README_COMPREHENSIVE.md`.
- Every schema change: increment MIGRATION.md log.

---
## 12. Documentation Debt Register
| Area | Gap | Planned Fix |
|------|-----|-------------|
| Live panel | Lacks per-index data mapping | After state export implementation |
| Memory pressure | No diagram of tier transitions | Add mermaid state diagram |
| Solver | Missing iterative convergence explanation | Add section in analytics doc |

---
## 13. Exit Criteria for v1.0.0
- Full live panel data parity with metrics
- Automated retention & compression
- Multi-provider fallback live
- CI with coverage & lint
- Alert rule pack shipped
- Comprehensive operator & developer docs (this set) stable

---
## 14. Appendix: Decision Log Template
Maintain a `DECISIONS.md` with entries:
```
Date | Area | Decision | Alternatives | Rationale | Impact
```

---
End of guidelines.
