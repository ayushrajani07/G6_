# G6 Cleanup Plan (Wave: Codebase Pruning & Simplification)

Date: 2025-09-30
Owner (proposed): Core Maintainers
Status: Draft (to be iterated and checked into main after validation)

## Legend / Categories
- REMOVE (immediate): No external references (tests/tasks), superseded; safe to delete now.
- DEPRECATE (grace): Provide banner + warning for 1 release; schedule removal (target: +2 weeks or next tagged release).
- CONSOLIDATE: Merge overlapping functionality; keep one canonical entrypoint.
- SIMPLIFY / REFAC: Streamline feature flags, environment variables, or scripts.
- ARCHIVE: Move historical docs/scripts into `archive/2025-<date>` (kept for posterity, not active surface).
- KEEP (core): Actively used / strategic.
- MONITOR: Re‑evaluate after telemetry or usage logging is added.

## 1. Scripts Inventory Actions

| Script / Group | Category | Rationale | Action Steps | Owner | Target Date |
|----------------|----------|-----------|--------------|-------|-------------|
| scripts/start_all_enhanced_.ps1 | REMOVE | Orphan variant (trailing underscore), no references | Delete file |  | ASAP |
| scripts/terminal_dashboard.py | REMOVED | Superseded by `summary_view.py` | Deleted (2025-10-01) |  | DONE |
| scripts/run_live.py | REMOVED | Replaced by `run_orchestrator_loop.py` | Deleted (2025-10-01) |  | DONE |
| scripts/benchmark_cycles.py | DEPRECATE | Legacy benchmarking; duplication with bench_* suite | Replace body with stub delegating or warning; plan removal |  | +1 release |
| bench_aggregate.py / bench_diff.py / bench_verify.py | CONSOLIDATE | Fragmented bench utilities; only trend/report used in tests | Merge into `bench_tools.py`; keep thin wrappers (deprecated) |  | 2 weeks |
| bench_trend.py / bench_report.py | KEEP | Referenced in tests (`test_benchmark_anomaly`) | None |  | n/a |
| scripts/panel_updater.py | REMOVED | Superseded by unified summary PanelsWriter | Deleted (2025-10-01); start scripts invoke summary_view directly |  | DONE |
| scripts/mock_live_updates.py | REMOVE or ARCHIVE | No references beyond self-doc; optional dev nicety | Move to `examples/` or delete |  | 2 weeks |
| start_live_dashboard_v2.ps1 | DEPRECATE -> REMOVE | Duplicate launcher; canonical is `scripts/start_live_dashboard.ps1` | Added deprecation shim chaining to canonical; remove after next release |  | R+1 |
| start_all.ps1 / start_all_enhanced.ps1 | CONSOLIDATE | Overlapping orchestrator start bundles | Provide single unified `start_platform.ps1` |  | 2 weeks |
| start_panels_flow.ps1 | CONSOLIDATE | Panels flow duplicative now that tasks exist | Fold into docs (How to run panels) |  | 2 weeks |
| plot_weekday_overlays.py / weekday_overlay.py / generate_overlay_layout_samples.py | MONITOR | Overlays feature niche; confirm active usage | Add usage metric or doc pointer; re-eval next wave |  | Next wave |
| diagnose_expiries.py / expiry_matrix.py / sanitize_csv_expiries.py | KEEP | Operational troubleshooting (expiry correctness critical) | Add doc index linking these |  | 2 weeks |
| inspect_options_snapshot.py | MONITOR | Debug-only snapshot inspector | Consider integrating into a unified debug CLI |  | Next wave |
| quick_* scripts (quick_cycle.py, quick_import_test.py, quick_provider_check.py) | CONSOLIDATE | Ad-hoc smoke utilities | Offer a single `dev_smoke.py` with subcommands |  | 1 month |
| gen_env_docs.py / check_env_doc_governance.py | KEEP | Tested governance | None |  | n/a |
| gen_metrics_docs.py / gen_metrics_glossary.py | KEEP | Metrics doc pipeline | None |  | n/a |
| legacy_import_audit.py | KEEP | Enforces deprecation policy; covered by tests | None |  | n/a |
| run_orchestrator_loop.py | KEEP | Canonical orchestrator runner | Possibly rename to `orchestrator.py run` future CLI |  | n/a |
| launch_platform.py / g6_run.py | CONSOLIDATE | Overlapping entry flows | Evaluate merging into orchestrator CLI |  | 1 month |

## 2. Environment Variables & Flags

| Item | Current Use | Issue | Proposed Change | Category |
|------|-------------|-------|-----------------|----------|
| G6_SUMMARY_PANELS_MODE | Toggle panels vs plain summary | Adds branch logic & user cognitive load | Auto-detect panels dir / env; remove flag | SIMPLIFY |
| G6_SUPPRESS_DEPRECATED_RUN_LIVE / G6_SUPPRESS_BENCHMARK_DEPRECATED / G6_SUPPRESS_DEPRECATED_WARNINGS | Multiple suppression envs | Fragmented, inconsistent | Consolidate into `G6_SUPPRESS_DEPRECATIONS` (comma modes optional) | SIMPLIFY |
| Legacy --enhanced flag (run_orchestrator_loop.py) | No-op retention | Dead path presently | Remove parser arg + adjust tests | REMOVE |
| Panels bridge separate loop (status_to_panels + summary mode) | Two processes | Potential consolidation | Combine into single process with optional thread/plugin | CONSOLIDATE (future) |

## 3. Documentation Rationalization

| Doc File | Status | Action |
|----------|--------|--------|
| README.md / README_COMPREHENSIVE.md / README_web_dashboard.md | Overlapping | (DONE 2025-10-01) Unified into single canonical `README.md`; legacy files now archival stubs slated for removal R+1 | CONSOLIDATED |
| DEPRECATIONS.md | Active | Add table with planned removal dates (populate from this plan) | REFAC |
| Enhancement one-offs (FOOTER_*.md, PANEL_*_ENHANCEMENT.md, ALERTS_PANEL_ENHANCEMENT.md) | Historical | Merge summaries into `docs/features_history.md`; archive originals | ARCHIVE |
| WAVE_3_SUMMARY.md / WAVE4_TRACKING.md / LONG_TERM_TODO.md | Planning artifacts | Convert to ROADMAP.md + GitHub issues | ARCHIVE + CONSOLIDATE |
| MIGRATION.md | Validate relevance | Keep if migration path still needed; otherwise mark legacy | MONITOR |

## 4. Feature Surface Review

| Feature | Complexity Cost | Usage / Value | Decision | Notes |
|---------|-----------------|---------------|----------|-------|
| Dual dashboards (terminal_dashboard vs summary_view) | Redundant maintenance | summary_view primary | Remove legacy | Terminal path stub then delete |
| Multi bench scripts | Code duplication | Low external necessity | Consolidate | Provide one CLI with subcommands |
| Panels mode flag | Branch complexity | Auto-detect possible | Simplify | Remove flag after implementing detection |
| Numerous quick_* scripts | CLI clutter | Dev convenience | Consolidate | Provide help listing subcommands |
| Manual panel updater script | Stale | Not used | Remove | Confirm absence in docs |
| Overlay sample generators | Niche | Possibly used for docs | Monitor | Add usage metric (invocation counter) |

## 5. Execution Timeline (Suggested Phases)

Phase 1 (Immediate: PR1)
- Delete: start_all_enhanced_.ps1
- Add deprecation stubs: terminal_dashboard.py, run_live.py, benchmark_cycles.py
- Create DEPRECATIONS schedule table
- Prepare consolidated README draft (not yet remove others)

Phase 2 (Week 2)
- Consolidate bench_* scripts
- Remove wrappers or mark them deprecated
- Consolidate suppression env vars
- Remove no-op --enhanced flag + update tests

Phase 3 (Week 3)
- Panels mode auto-detect implementation; remove G6_SUMMARY_PANELS_MODE usage
- Consolidate quick_* into dev_smoke.py
- Archive enhancement MDs, create features_history.md

Phase 4 (Week 4)
- Merge launch_platform/g6_run into orchestrator CLI plan
- Evaluate panels bridge + summary unification design
- Archive planning docs to ROADMAP.md

## 6. Risk & Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| Hidden external automation depending on deprecated scripts | Break external workflows | Release notes + stub period with exit code 0 + warning (first phase) |
| Tests failing after script removal | CI noise | Grep tests before deletion; replace imports with new CLI pathways |
| Users relying on env suppression variants | Unexpected warning noise | Provide combined env var while still honoring legacy for one release |
| Over-aggressive doc consolidation losing context | Knowledge loss | Archive originals in /archive with commit references |

## 7. Metrics / Success Criteria
- Reduction in scripts/ count by ~30–40% (baseline N, target N-?).
- Zero deprecated script warnings after grace period in normal dev workflows.
- Simplified README (single authoritative) accepted & linked from docs index.
- Fewer CI governance exceptions (no legacy flag test scaffolding).

## 8. Open Questions
- Any external consumers of bench_aggregate/diff/verify via automation? (Need stakeholder confirmation)
- Panels bridge performance concerns if unified (needs profiling before merge)
- Overlays feature roadmap: keep or spin out?

## 9. Tracking Table (Populate During Execution)
Will be appended as PRs merge; include PR IDs, dates, and follow-up tasks.

---
Generated initial plan. Update sections with stakeholders and confirm Phase 1 scope before implementation.
