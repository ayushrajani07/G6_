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
| scripts/start_all_enhanced_.ps1 | REMOVED | Orphan variant (trailing underscore), no references | Deleted (2025-10-05) |  | DONE |
| scripts/terminal_dashboard.py | REMOVED | Superseded by `summary_view.py` | Deleted (2025-10-01) |  | DONE |
| scripts/run_live.py | REMOVED | Replaced by `run_orchestrator_loop.py` | Deleted (2025-10-01) |  | DONE |
| scripts/benchmark_cycles.py | DEPRECATE | Legacy benchmarking; duplication with bench_* suite | Stub updated (2025-10-05) emits banner; remove after 2025-10-31 |  | 2025-10-31 |
| bench_aggregate.py / bench_diff.py / bench_verify.py | REMOVED | Consolidated into bench_tools.py subcommands | Deleted (2025-10-05) |  | DONE |
| bench_trend.py / bench_report.py | KEEP | Referenced in tests (`test_benchmark_anomaly`) | None |  | n/a |
| scripts/panel_updater.py | REMOVED | Superseded by unified summary PanelsWriter | Deleted (2025-10-01); start scripts invoke summary_view directly |  | DONE |
| scripts/mock_live_updates.py | REMOVED | No references; optional demo server | Deleted (2025-10-05); doc updated with replacement snippet |  | DONE |
| start_live_dashboard_v2.ps1 | DEPRECATE -> REMOVE | Duplicate launcher; canonical is `scripts/start_live_dashboard.ps1` | Added deprecation shim chaining to canonical; remove after next release |  | R+1 |
| start_all.ps1 / start_all_enhanced.ps1 | REMOVED | Superseded by Windows auto-resolve flow | Replaced by `scripts/auto_stack.ps1` (invoked via `auto_resolve_stack.py` at launcher start) |  | DONE (2025-10-11) |
| start_panels_flow.ps1 | REMOVED | Panels flow duplicative now that tasks exist | Deleted (2025-10-05); docs will reference tasks instead |  | DONE |
| plot_weekday_overlays.py / weekday_overlay.py / generate_overlay_layout_samples.py | MONITOR | Overlays feature niche; confirm active usage | Add usage metric or doc pointer; re-eval next wave |  | Next wave |
| diagnose_expiries.py / expiry_matrix.py / sanitize_csv_expiries.py | KEEP | Operational troubleshooting (expiry correctness critical) | Add doc index linking these |  | 2 weeks |
| inspect_options_snapshot.py | MONITOR | Debug-only snapshot inspector | Consider integrating into a unified debug CLI |  | Next wave |
| quick_* scripts (quick_cycle.py, quick_import_test.py, quick_provider_check.py) | REMOVED | Ad-hoc smoke utilities replaced by dev_smoke | Deleted (2025-10-05) – dev_smoke subcommands canonical |  | DONE |
| gen_env_docs.py / check_env_doc_governance.py | KEEP | Tested governance | None |  | n/a |
| gen_metrics_docs.py / gen_metrics_glossary.py | KEEP | Metrics doc pipeline | None |  | n/a |
| legacy_import_audit.py | KEEP | Enforces deprecation policy; covered by tests | None |  | n/a |
| run_orchestrator_loop.py | KEEP | Canonical orchestrator runner | Possibly rename to `orchestrator.py run` future CLI |  | n/a |
| launch_platform.py | REMOVED | Overlapping entry flow duplicate of orchestrator & g6_run.py | Deleted (2025-10-05) |  | DONE |
| g6_run.py | KEEP | Remaining custom runner (subject to future CLI unification) | None now; evaluate orchestrator CLI merge later |  | n/a |

## 2. Environment Variables & Flags

| Item | Current Use | Issue | Proposed Change | Category |
|------|-------------|-------|-----------------|----------|
| G6_SUMMARY_PANELS_MODE | Toggle panels vs plain summary | Adds branch logic & user cognitive load | Auto-detect panels dir / env; remove flag | SIMPLIFY |
| G6_SUPPRESS_DEPRECATED_RUN_LIVE / G6_SUPPRESS_BENCHMARK_DEPRECATED / G6_SUPPRESS_DEPRECATED_WARNINGS | Multiple suppression envs | Fragmented, inconsistent | Consolidated into `G6_SUPPRESS_DEPRECATIONS` (DONE 2025-10-05; legacy aliases auto-mapped, removal scheduled R+1) | SIMPLIFY |
| Legacy --enhanced flag (run_orchestrator_loop.py) | REMOVED | No-op retention | Removed (2025-10-05); docs updated to drop flag | REMOVE |
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
- Delete: start_all_enhanced_.ps1 (DONE 2025-10-05)
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
## 10. Consolidated Cleanup Status (Absorbed Documents)

This section unifies prior separate docs: `docs/cleanup.md`, `docs/CLEANUP_PROPOSALS.md`, `docs/CLEANUP_FINAL_REPORT.md` scaffold, and `docs/clean.md` into this single canonical plan. Those standalone files will be removed after this update.

### 10.1 Inventory & Classification Snapshot
- Candidate-remove scripts deleted this wave: benchmark wrappers, mock_live_updates, start_panels_flow, terminal_dashboard, run_live, launch_platform.
- Remaining candidate-remove scripts under evaluation: overlay sample generators, select bench tools (trend/report) pending usage verification.
- Temp/debug scripts slated for archival next wave: files prefixed `temp_`, `debug_`.

### 10.2 KPI Baselines (Interim)
| KPI | Current | Target | Notes |
|-----|---------|--------|-------|
| total_python_files | TBD (inventory script run pending) | -15% Wave B | Snapshot after archival phase |
| temp_debug_files | >10 | -90% Wave A | Archive or delete low-value scratch scripts |
| unique_env_vars (G6_*) | TBD | -10% deprecated removal | After suppression consolidation |
| duplicate_logic_segments | TBD | -20% Wave B | SSE/security & summary unification delivered |
| flaky_test_incidents | TBD | -50% Wave C | Need flake tracker harness |

### 10.3 Quality Gates (Latest Recorded)
| Gate | Baseline | Current | Drift | Pass? | Notes |
|------|----------|---------|-------|-------|-------|
| Coverage (%) | 51.86 | 52.76 | +0.90 | Y | Recovered after deletions + stabilization |
| Dead Code (new items) | 0 | 0 | 0 | Y | Enforced via dead_code_scan.py |
| Orphan Tests | 0 | 0 | 0 | Y | Maintained |
| Env Missing Vars | 0 | 0 | 0 | Y | All placeholders documented |
| Docs Index Missing | 0 | 0 | 0 | Y | Stable |

### 10.4 Completed Consolidations
| Area | Before | After | Benefit |
|------|--------|-------|---------|
| SSE logic | Scattered handlers | Shared module + tests | Reduced duplication |
| Benchmarking | Multiple wrappers | `bench_tools.py` subcommands | Single surface, easier evolution |
| Orchestrator flags | Legacy `--enhanced` | Removed | Simpler CLI, less confusion |
| Deprecation suppression | Fragmented flags | (In progress) unified upcoming | Consistent user guidance |

### 10.5 Pending High-Value Actions
1. (COMPLETED) Suppression env var unification (`G6_SUPPRESS_DEPRECATIONS`).
2. Enhancement doc archival → `docs/features_history.md` (COMPLETED).
3. Metrics catalog regeneration post `perf_cache` alias removal (COMPLETED).
4. Coverage recovery plan (target +2% net after pruning & added focused tests). (IN PROGRESS)
5. Dead code scan integration into CI with drift alert. (COMPLETED: `scripts/dead_code_scan.py`, optional pytest gate via `G6_RUN_DEAD_CODE_SCAN=1`, budget env `G6_DEAD_CODE_BUDGET`)
6. Env docs refresh to replace remaining 'needs docs' placeholders (COMPLETED 2025-10-05).

### 10.6 Risk Register (Active)
| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| Suppression env confusion during transition | Medium | Low | Dual-read + deprecation warning window |
| Missed external dependency on deleted scripts | Low | Medium | Monitor issue reports; quick stub re-intro if critical |
| Coverage floor breach after large deletions | High | Low | Temporary ratchet disable + add focused tests |

### 10.7 Archival Strategy
- Move absorbed docs to `archive/2025-10-05/` for historical lookup (commit artifact only) or delete if fully superseded.
- Keep only `CLEANUP_PLAN.md` as living governance doc.

### 10.8 Execution Tracking Addendum
A structured table (to be appended) will log: item, PR/commit hash, date, delta (files removed/added), and follow-up tasks creation. Placeholder until automation script emits markdown fragment.

---
## 11. Final Report Path (Future)
When cleanup wave concludes, promote sections 10.x into a summarized executive report appended here (instead of separate FINAL_REPORT file). Metrics deltas will be auto-inserted by governance tooling.

## 12. Wave Wrap-Up (Summary)
**Scope Executed:** Script pruning, benchmarking consolidation, suppression env unification, metrics alias removal, documentation consolidation, dead code scan integration, flake stabilization, env catalog completion.

**Key Outcomes:**
- Script surface reduced significantly (legacy launchers & quick_* utilities removed).
- Unified suppression (`G6_SUPPRESS_DEPRECATIONS`) with automatic legacy mapping.
- Metrics catalog regenerated (57 metrics) after alias retirements; gating warnings preserved.
- Coverage stabilized above 52% despite deletions; quality gates all green.
- Dead code governance operational (`scripts/dead_code_scan.py` + optional pytest gate).
- Documentation noise reduced: enhancement one-offs archived; env var placeholders eliminated.
- Flaky multi-test run incident mitigated via thread cleanup autouse fixture.

**Technical Debt Retired:** perf_cache alias, deprecated run flags, multi bench wrappers, fragmented suppression env vars, unused start scripts.

**Remaining Focus (Next Wave Candidates):**
1. Panels bridge + summary unification (single process architecture).
2. Coverage +2–3% targeted uplift (SummaryEnv edge cases, metrics gating predicates, resilience paths).
3. Evaluate pruning low-value experimental provider modules with <20% coverage.
4. Overlay feature usage telemetry before deciding monitor vs. deprecate.
5. Optional: auto-generation of dead code trend report artifact (`dead_code.json`).

### 12.1 Stream Gater / Panels Bridge Unification Progress
Progress Summary: Consolidation completed through Phase 4; gating now permanent and unconditional.

Status by Phase:
* Phase 1 COMPLETE (feature flag opt-in validated).
* Phase 2 COMPLETE: `StreamGaterPlugin` default-on (temporary opt-out present).
* Phase 3 COMPLETE (accelerated 2025-10-05): Legacy bridge script tombstoned (`scripts/status_to_panels.py`).
* Phase 4 COMPLETE (2025-10-05): Removed obsolete opt-in & opt-out code paths; flags now ignored with one-time warning.

Metrics integrated into spec & catalog: `g6_stream_append_total`, `g6_stream_skipped_total`, `g6_stream_state_persist_errors_total`, `g6_stream_conflict_total`.
Conflict metric remained 0 over observation window; dual-writer condition never observed.

Next (Phase 5 – Target 2025-10-20):
* Remove retired flag warning branch once logs show zero occurrences for 5 consecutive business days.
* Drop normalization shim / any transitional metric aliasing specific to stream metrics.
* Regenerate metrics catalog and confirm invariants without shim.
* Mark gating subsystem STABLE; relocate state persistence details to operator manual appendix.

Deferred (if signal of lingering external usage appears): extend monitoring window; do NOT resurrect old flags—use a temporary diagnostic env with a new name if absolutely required.

**Risks Monitored:** residual low-coverage deep modules (storage/influx, dashboard web app) accepted for now; flagged for targeted refactor rather than superficial test padding.

**Go/No-Go:** Wave objectives met; proceed to next wave planning.

<!-- Consolidated cleanup docs end -->

## 13. Panels Bridge + Summary Unification (Consolidated Status)

Design reference: `PANELS_BRIDGE_SUMMARY_UNIFICATION.md` (now trimmed to final-state details). Historical phased plan removed from this document to reduce noise; reference VCS history if needed.

### 13.1 Unification Progress

| Phase | Date | Action | Status | Notes |
|-------|------|--------|--------|-------|
| 1 | 2025-10-05 | Implement `StreamGaterPlugin` (flag `G6_UNIFIED_STREAM_GATER=1`) | DONE | Plugin auto-inserted after PanelsWriter; suppresses baseline indices_stream duplication. |
| 1 | 2025-10-05 | Add gating tests (cycle, bucket, corrupt state, heartbeat) | DONE | Tests: `test_stream_gater_cycle`, `test_stream_gater_bucket`, `test_stream_gater_state_corrupt`, `test_stream_gater_heartbeat`. |
| 1 | 2025-10-05 | PanelsWriter suppression of indices_stream when gater active | DONE | Prevents duplicate first-cycle entries. |
| 2 | 2025-10-05 | Default-on gater (opt-out env) + conflict metric | DONE | Introduced `G6_DISABLE_UNIFIED_GATER=1`; conflict metric active. |
| 3 | 2025-10-05 | Remove legacy bridge script & allow flag | DONE | Tombstone stub committed; docs updated. |
| 4 | 2025-10-05 | Retire opt-in & opt-out handling | DONE | Flags ignored; single warning emitted if set. |
| 5 | (target 2025-10-20) | Remove warning + cleanup shim | PENDING | Delete warning logic & normalization shim after quiet window. |

Next Tasks:
1. Monitor for any residual retired flag usage warnings (CI/prod logs).
2. Prepare Phase 5 PR: remove warning branch + normalization shim; regenerate metrics catalog.
3. Optional: Add focused unit test for `g6_stream_append_total` increment (if coverage gap identified).
4. Update Operator Manual appendix with final gating description post-shim removal.

Exit Criteria (upcoming phases):
* Phase 4: No references to opt-in flag remain; tests green; conflict metric stable.
* Phase 5: Opt-out removed; governance note updated; docs & examples free of gating flags.
