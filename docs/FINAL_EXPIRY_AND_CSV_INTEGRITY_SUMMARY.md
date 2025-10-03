# G6 Expiry Resolution & CSV Integrity Final Summary

Date: 2025-09-25
Status: Complete (all remediation and hardening tasks implemented)

---
## 1. Objectives

| Theme | Goal |
|-------|------|
| Instrument Acceptance | Restore non-zero option universe after normalization failures |
| Diagnostics | Provide high-signal traces for expiry & strike mismatches |
| Performance | Eliminate repeated full-instrument fetches per cycle |
| Expiry Semantics | Centralize & enforce logical expiry tagging (this_week/next_week/etc.) |
| Data Integrity | Remove duplication, mixed-expiry contamination, and invalid expiry rows |
| Config Governance | Honor per-index allowed expiry tags |
| Historical Hygiene | Clean legacy CSV rows with stray / dummy expiry_date values |

---
## 2. Implemented Changes (Chronological Layers)

1. Normalization & Recovery
   - Unified expiry comparison (date-only) to fix zero accepted NIFTY options.
   - Added TRACE sampling (expiry_diag, strike_diag) for early anomaly detection.
2. Control & Observability
   - Added `--once` mode for deterministic single-cycle debugging.
   - Summarized distinct expiries & strike coverage at startup.
3. Performance & Structure
   - Daily prefetch of full instrument universe (cached on disk + in-memory) before analytics.
   - Single authoritative `select_expiry` rule path; removed duplicate resolver branches.
   - Startup expiry matrix printed once (concise view of near-term schedule per index).
4. CSV Sink Enhancements
   - Added lock sentinel (`.lock`) for best-effort atomic append.
   - Duplicate row suppression keyed by (file, offset, timestamp).
   - Batched write mode (optional via env) with threshold-based flush.
5. Expiry Governance
   - Propagated collector-chosen `expiry_rule_tag` into sink (bypassing heuristic when provided).
   - Enforced per-index configured expiry tags—skips disallowed weekly/monthly outputs.
6. Mixed-Expiry & Schema Hardening
   - Pruned option legs whose embedded expiry != resolved target.
   - Forced canonical `expiry_date` column (no per-row drift allowed).
   - Logged mismatch tallies and sample offenders (CSV_EXPIRY_META_MISMATCH, CSV_MIXED_EXPIRY_PRUNE).
   - Advisory when not all configured expiries observed yet for a day.
7. Invalid Expiry Defense
   - Collector now supplies authoritative `allowed_expiry_dates` set from provider to sink.
   - Sink rejects rows whose final `expiry_date` not in that set (CSV_SKIP_INVALID_EXPIRY).
8. Historical Remediation
   - Added `scripts/sanitize_csv_expiries.py` supporting:
     - Dominant-mode pruning (keep most frequent expiry_date per file).
     - Whitelist mode (explicit list or provider lookup).
     - Backups, dry-run, min-row gating.

---
## 3. Key Files & Responsibilities

| File | Responsibility |
|------|----------------|
| `src/utils/expiry_rules.py` | Canonical expiry selection logic |
| `src/broker/kite_provider.py` | Instrument universe & expiry dates retrieval (now cache-aware) |
| `src/storage/csv_sink.py` | Persistence with enforcement (tags, duplication, mixed-expiry pruning, whitelist check) |
| `scripts/sanitize_csv_expiries.py` | Post-hoc cleanup of legacy CSV contamination |
| `src/unified_collectors.py` | Attaches `expiry_rule_tag` & `allowed_expiry_dates` before writing |

---
## 4. Data Integrity Contract (Final State)

| Stage | Validation / Guarantee |
|-------|------------------------|
| Instrument Acceptance | Only instruments whose normalised expiry & strike align with rule-set enter chain |
| Expiry Resolution | Single path yields (exp_date, logical_tag) pair |
| Mixed-Expiry Guard | Rows from foreign expiries dropped pre-grouping |
| Canonicalization | Every persisted row carries the same `expiry_date` for a given (index, expiry_tag, date file) |
| Whitelist Enforcement | `expiry_date` must be in provider-derived allowed set |
| Config Tag Enforcement | If tag supplied, must be in configured list for index |
| Deduplication | Same timestamp row per (file, offset) suppressed |
| Schema Hygiene | Invalid instrument types / zero strikes filtered |

---
## 5. Operational Runbook

| Task | Command / Action |
|------|------------------|
| Single diagnostic cycle | `python scripts/run_orchestrator_loop.py --config config/g6_config.json --interval 60 --cycles 1 --log-level TRACE` |
| Full run (normal) | `python scripts/run_orchestrator_loop.py --config config/g6_config.json --interval 60` |
| Sanitize legacy CSVs (dry-run) | `python scripts/sanitize_csv_expiries.py --dry-run --verbose` |
| Sanitize with provider whitelist | `python scripts/sanitize_csv_expiries.py --use-provider` |
| Enforce specific expiry whitelist | `python scripts/sanitize_csv_expiries.py --allowed YYYY-MM-DD,YYYY-MM-DD` |

---
## 6. Metrics / Log Keys (Add as needed)

| Event / Metric | Purpose |
|----------------|---------|
| `CSV_MIXED_EXPIRY_PRUNE` | Count mixed-leg drops before persistence |
| `CSV_EXPIRY_META_MISMATCH` | Residual per-row leg metadata drift |
| `CSV_SKIP_INVALID_EXPIRY` | Skipped write due to whitelist exclusion |
| `csv_mixed_expiry_dropped` (metric) | Aggregate of pruned instruments |
| `csv_skipped_disallowed` (metric) | Disallowed config tag attempts |
| `zero_option_rows_total` | Zero-value row incidence (optional skip) |

(Consider adding `csv_invalid_expiry_skipped` and `csv_sanitizer_rows_removed` for full lifecycle coverage.)

---
## 7. Residual Risks & Future Enhancements

| Area | Suggestion |
|------|------------|
| Provider Drift | Cache expiry list with TTL & diff log when set changes intra-day |
| Quarantine | Instead of silent skip, write invalid rows to `data/g6_data/_quarantine/` for audit |
| Metrics Coverage | Add Prometheus counters for sanitizer removals |
| Parallel Sanitization | ThreadPool / process pool for large historical backfills |
| Integrity Audit | Periodic job verifying each (index, expiry_tag, date) has exactly one unique `expiry_date` |

---
## 8. Summary Outcome
All targeted integrity defects (duplicate rows, mixed-expiry contamination, stray dummy expiry_date values) are now prevented prospectively and remediable retrospectively. The pipeline enforces a clear contract around expiry semantics, with layered guards and diagnostics enabling rapid detection of regressions.

System is stable; future work is incremental (observability polish & audit tooling).

---
## 9. Quick Validation Checklist
- [x] New cycle produces only configured expiry tags per index.
- [x] No new rows written with disallowed or foreign expiry_date.
- [x] Sanitizer dry-run reports expected removals (legacy contamination only).
- [x] Tests pass (112 passed / 10 skipped at last run).

---
**End of Report**
