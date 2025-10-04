# Metrics Governance

This document formalizes how metrics are declared, generated, validated, and protected against drift.

## Pillars
1. Single Authoritative Spec: `metrics/spec/base.yml` contains every operational metric (name, type, labels, cardinality budget, help).
2. Deterministic Code Generation: `scripts/gen_metrics.py` produces `src/metrics/generated.py` accessor functions plus the catalog / docs helpers.
3. Cardinality Enforcement: Runtime guard tracks unique label sets per metric and exposes `g6_cardinality_series_total{metric="..."}`.
4. Warming & Zero-Gap Panels: `scripts/exercise_metrics.py` instantiates each metric (and a synthetic label set) so dashboards never start empty.
5. Drift Detection: `scripts/metrics_drift_check.py` compares spec vs live `/metrics` export. In CI we run it in strict mode (fail on extra or missing).
6. CI Gate: The Metrics Governance workflow blocks merges when spec/code diverge or generated artifacts are not committed.

## Lifecycle
| Stage | Action | Script / Mechanism |
|-------|--------|--------------------|
| Define | Add / modify metric in spec | Edit `metrics/spec/base.yml` |
| Generate | Rebuild accessors & docs | `python scripts/gen_metrics.py` (plus optional catalog/docs scripts) |
| Instrument | Use generated accessor | `from src.metrics.generated import m_my_metric` |
| Warm | Ensure a first sample exists | `python scripts/exercise_metrics.py` (part of CI) |
| Verify | Detect spec/runtime drift | `python scripts/metrics_drift_check.py --endpoint http://localhost:9108/metrics` |
| Govern | CI enforces rules | `.github/workflows/metrics-governance.yml` |

## Adding a New Metric
1. Edit `metrics/spec/base.yml`: add entry under appropriate family with `name`, `type`, `help`, `labels`, `cardinality_budget`.
2. Run generation: `python scripts/gen_metrics.py`.
3. (Optional) Update docs: `python scripts/gen_metrics_docs.py`.
4. Use the new accessor in code: `m_new_metric({'label':'value'}).inc()` or `.set()` / `.observe()` depending on type.
5. Run `python scripts/exercise_metrics.py --run-drift-check` locally (ensure a metrics server is active or let it start one) to confirm no drift.
6. Commit spec + regenerated files together. Push / open PR.

## Cardinality Budgets
Each metric's `cardinality_budget` is a governance hint. The runtime guard can be extended to enforce hard ceilings; currently it reports counts so we can set alerts later (e.g. `increase(g6_cardinality_series_total{metric="g6_api_calls_total"}[10m]) > 0` with thresholds).

## Warming Strategy
- Counters: touched by calling `.inc(0)` via accessor.
- Gauges: explicitly `.set(0)` once.
- Histograms: `.observe(0)` to create zeroed buckets.
- Labeled metrics: synthetic label value `warm` for every label key ensures a first timeseries exists but does not pollute production cardinality significantly (only one synthetic set per metric).

## Drift Detection Semantics
- Missing (in spec, absent at runtime) => always fail.
- Extra (runtime not in spec) => fail only when `G6_METRICS_STRICT=1` (enabled in CI governance workflow).
- Internal / library metrics (process_*, python_gc_...) are ignored unless `--include-internals` requested.

## CI Workflow
See `.github/workflows/metrics-governance.yml`:
1. Regenerates metrics and docs.
2. Warms metrics and runs strict drift check.
3. Fails if drift or uncommitted generated changes exist.

## Intentional Removals / Renames
If you remove a metric from the spec but old code still references it, drift will show it as extra (runtime emits, spec absent). Update code first (or simultaneously) to stop emitting; warm script will stop touching it; then drift passes.

For renames perform in one PR:
- Add new metric.
- Update code to emit new metric and stop old.
- Remove old metric entry.
- Regenerate & commit.

## Future Enhancements
- Budget breach alert rules (auto-generated) referencing series cardinality gauge.
- Spec hash embedding for quicker divergence detection.
- Panel hints within spec for richer auto dashboards.
- Hard enforcement: guard raising when budget exceeded (optional env flag).

## Panel Hints
Dashboard visualization intent now lives alongside metrics via per-metric `panels` hints.
See `METRICS_PANELS_HINTS.md` for schema and generation details. Regenerate dashboards with:
```
python scripts/gen_dashboard_from_spec.py --force --out grafana/dashboards/g6_spec_panels_dashboard.json
```

## Spec Hash Integrity
The spec file SHA-256 (first 16 hex chars) is embedded as `SPEC_HASH` constant in `src/metrics/generated.py` and exposed via the `g6_metrics_spec_hash_info{hash="<hash>"} 1` gauge.

Purpose:
- Fast visual confirmation of deployed spec version.
- CI/runtime drift detection beyond mere metric presence.

Validation:
```
python scripts/metrics_drift_check.py --check-hash --endpoint http://localhost:9108/metrics
```
Failure Modes:
| Symptom | Cause | Action |
|---------|-------|--------|
| Hash mismatch | Generated artifacts outdated | Re-run gen_metrics.py & commit |
| Metric absent | Hash metric not in spec or server not warmed | Ensure governance family present; restart process |
| Multiple hashes | Unexpected (should be one) | Investigate duplicate registration |

The governance workflow can be extended to add `--check-hash` for stronger guarantees.

### Build / Config Hash (Extended Integrity)
To detect silent drift in runtime configuration separate from metrics spec evolution, a parallel static gauge `g6_build_config_hash_info{hash="<hash>"} 1` is emitted when the metric exists in the spec. Its label value is sourced from environment variable `G6_BUILD_CONFIG_HASH` (fallback: current `SPEC_HASH` if unset) during accessor module initialization.

Use Cases:
- Detect deployment using same metrics spec but different (possibly unintended) configuration bundle.
- Surface both hashes side-by-side in dashboard (panel hint `Build/Config Hash`).

Operational Pattern:
1. Build pipeline computes stable hash of selected config inputs (e.g., concatenated normalized JSON/YAML, trimmed whitespace) -> exports to deployment manifests.
2. Runtime sets `G6_BUILD_CONFIG_HASH` env var before starting service.
3. Gauge renders allowing quick visual diff vs expected value.

Recommended Hash Input Set:
- Application runtime config files (excluding secrets; those can be redacted or replaced by placeholder tokens before hashing).
- Version-pinned dependency lock file (optional if already captured elsewhere).
- Feature flag manifest snapshot.

Example (build script pseudo):
```
export G6_BUILD_CONFIG_HASH=$(cat config/app.yml config/features.yml | sed 's/[[:space:]]//g' | sha256sum | cut -c1-16)
```

Alerting (future): Add an external validation job comparing deployed `g6_build_config_hash_info` vs expected release manifest hash – page on mismatch outside approved change window.

## Alert Rule Templating
Metrics spec entries can now declare alert hints under an `alerts:` list. Each alert object:
```
alerts:
	- alert: G6ApiErrorRateHigh
		expr: sum(rate(g6_api_calls_total{result="error"}[5m])) / clamp_min(sum(rate(g6_api_calls_total[5m])),1) > 0.05
		for: 5m
		severity: warning
		summary: "API error rate >5% (5m)"
		description: "Investigate upstream provider stability."
```
Generated via:
```
python scripts/gen_prometheus_alerts.py --out prometheus/g6_generated_alerts.yml
```
Behavior:
- Groups alerts by metric family (`<family>.generated`).
- Adds default labels: `team=g6`, `severity` (from hint or default warning).
- Preserves multi-line descriptions.

Recommended CI addition:
1. Run generator.
2. Fail if diff vs committed output (govern drift).

Roadmap Enhancements:
- Derived SLO alert patterns (burn rate windows) from gauge/counter pairs.
- Auto-threshold scaling based on cardinality budgets.
- Alert provenance injection referencing spec hash.

## Artifact Provenance (Dashboards & Alerts)
Every generated observability artifact embeds a provenance stanza binding it to the exact spec revision (by short hash):

Artifacts:
- Grafana dashboard JSON (default: `grafana/dashboards/g6_generated_spec_dashboard.json`) contains `g6_provenance`.
- Prometheus alert rules file (`prometheus/g6_generated_alerts.yml`) contains root key `x_g6_provenance`.

Structure (example fields – may extend versioned by `schema`):
```
g6_provenance / x_g6_provenance:
	schema: g6.(dashboard|alerts).provenance.v0
	generated_at_utc: 2025-01-01T12:00:00Z
	spec_path: metrics/spec/base.yml
	spec_hash: <16 hex chars>
	generator: gen_*.py
	families|groups: <count>
	panels|rules: <count>
```

Generation:
```
python scripts/gen_dashboard_from_spec.py --force
python scripts/gen_prometheus_alerts.py
```

Validation (hash comparison against current spec file):
```
python scripts/check_provenance.py \
	--spec metrics/spec/base.yml \
	--dashboard grafana/dashboards/g6_generated_spec_dashboard.json \
	--alerts prometheus/g6_generated_alerts.yml
```
Exit codes: 0 OK, 1 mismatch, 2 read/parse error.

CI Recommendation:
1. Re-run generators.
2. Run provenance check script (fail on non‑zero).
3. Fail if git diff contains changed generated artifacts (ensures committed output matches spec).

Why:
- Guarantees dashboards/alerts were regenerated after any spec edit (no stale visualizations or rules).
- Enables quick triage: spec hash shown in UI or file diff maps directly to spec commit.
- Lays groundwork for future signing or attestation (upgrade schema version without breaking clients).

Failure Modes & Actions:
| Symptom | Cause | Action |
|---------|-------|--------|
| Dashboard spec_hash mismatch | Dashboard not regenerated after spec change | Run dashboard generator & commit |
| Alerts spec_hash mismatch | Alerts file stale | Re-run alerts generator & commit |
| Missing provenance block | Generator version outdated | Re-run latest scripts / upgrade tooling |
| Multiple differing spec hashes across artifacts | Partial regeneration | Regenerate all & re-run provenance check |

Roadmap:
- Add optional GPG signature / checksum chain.
- Include git commit short SHA in provenance (when available) for richer traceability.
- Surface provenance via a lightweight HTTP endpoint for runtime introspection.

## Registry Health Diagnostics
The registry guard now emits an internal counter `g6_metric_duplicates_total{name="<metric>"}` whenever a second (or subsequent) registration attempt for the same metric name occurs. This surfaces accidental double imports or cyclic side-effect reinitializations that would otherwise be silent.

Emission Path:
- In `registry_guard._register`, if `name` already exists in `_rg_metrics` the attempt is treated as a duplicate; we increment a labeled counter (lazy-created via generated accessor) and return the existing metric instance.

Panels:
- Duplicate Registrations (5m): sum(rate(g6_metric_duplicates_total[5m])) – overall churn.
- Duplicates by Metric (5m): topk(10, sum by (name) (rate(g6_metric_duplicates_total[5m]))) – hotspots.

Operational Guidance:
- A non-zero sustained rate typically means a module with metric definitions is imported repeatedly (e.g., dynamic loader or test harness spawning multiple app contexts in a single process).
- Occasional duplicates during process start (race-y lazy imports) may be acceptable; trend should flatten after warm-up.

Alerting (future idea):
```
alert: G6MetricDuplicateSpike
expr: sum(rate(g6_metric_duplicates_total[10m])) > 1
for: 10m
labels: { severity: warning, team: g6 }
annotations:
	summary: "Duplicate metric registrations sustained >1/10m"
	description: "Investigate module import patterns or side-effectful registration calls."
```

Next Possible Enhancements:
- Track first-seen timestamp per metric and include in duplicate events (sampled log).
- Add gauge for total distinct metrics vs. baseline drift (already partly covered by cardinality guard snapshotting).
- Introduce env flag `G6_METRICS_FAIL_ON_DUP=1` to raise on duplicate in CI-only contexts.
	- IMPLEMENTED: Set `G6_METRICS_FAIL_ON_DUP=1` (any truthy value) to raise `RuntimeError` immediately on a duplicate registration attempt after incrementing the counter. Recommended for CI to catch accidental side-effect imports early.

## Cardinality Growth Alerting
Cardinality guard evaluates metric group membership growth relative to a stored baseline snapshot to surface uncontrolled expansion of metrics (often driven by unbounded labels).

New Metrics (governance family):
- `g6_cardinality_guard_offenders_total` – count of groups exceeding allowed growth.
- `g6_cardinality_guard_new_groups_total` – number of entirely new groups not present in baseline.
- `g6_cardinality_guard_last_run_epoch` – unix timestamp of last evaluation.
- `g6_cardinality_guard_allowed_growth_percent` – configured threshold used.
- `g6_cardinality_guard_growth_percent{group="..."}` – per offending group growth percent.

Environment Controls:
- `G6_CARDINALITY_BASELINE` – path to existing baseline JSON.
- `G6_CARDINALITY_SNAPSHOT` – path; if set writes new snapshot (and optionally also compares if baseline also set).
- `G6_CARDINALITY_ALLOW_GROWTH_PERCENT` – numeric percent (default 10).
- `G6_CARDINALITY_FAIL_ON_EXCESS` – when truthy, raises on any offender.

Alert (auto-generated example): `G6CardinalityOffendersDetected` triggers when offenders_total > 0 for 10m.

Operational Flow:
1. Generate initial baseline in stable environment: set `G6_CARDINALITY_SNAPSHOT=cardinality_baseline.json` and start service once.
2. Deploy baseline file with app; set `G6_CARDINALITY_BASELINE` to its path in all environments.
3. (Optional) Nightly CI can regenerate snapshot and diff to detect legitimate structural evolution; update baseline as part of planned change.

Interpreting Growth:
- High growth percent in a group often signals a new label dimension explosion (e.g., user ID, request ID). Introduce bucketing, truncation, or remove label.
- New groups appearing unexpectedly may indicate initialization ordering or a refactor relocating metrics.

Future Extensions:
- Combine growth percent with rate of new series over time for anomaly scoring.
- Enforce per-group hard ceiling separate from per-metric label budgets.
- Emit structured log for top offenders with sample label tuples.

## Import Latency Benchmarking
Cold import time of the metrics stack impacts startup latency (readiness & autoscaling). A lightweight harness `scripts/metrics_import_bench.py` measures wall-clock import latency in isolated subprocesses.

Usage:
```
python scripts/metrics_import_bench.py --runs 7 --modules src.metrics.generated src.metrics.cardinality_guard --json > import_bench.json
```
Human-readable mode (no --json) prints a concise summary with min/p50/p95/max/mean.

JSON Schema (`g6.metrics.import_bench.v0`): includes raw samples plus summary stats for trend tracking. Integrate into CI to detect regressions (e.g., >20% increase in p50 or p95 vs previous baseline artifact).

Recommended CI Gate (pseudo):
1. Run bench with fixed run count (e.g., 7).
2. Compare `p95_sec` to stored baseline (artifact or previous run) allowing small jitter (e.g., 15%).
3. Fail build on breach; instruct contributors to identify heavy imports (use `PYTHONPROFILEIMPORTTIME=1`).

Optimization Tips:
- Defer optional dependencies inside accessors instead of at module top-level.
- Avoid large YAML/JSON parsing during import; perform on first call or via lazy singleton.
- Consolidate logging configuration outside hot import paths.

Future Enhancements:
- Add `--baseline import_bench_prev.json --fail-pct 20` option to perform comparison inside script.
- Capture module-level top import offenders via `-X importtime` and parse output when `--profile` flag supplied.

## Domain Module Extraction & Grouped Metric Migration

As part of the ongoing modularization roadmap we migrated legacy side‑effect metric registration blocks for selected analytic domains into the declarative grouped spec (`GROUPED_METRIC_SPECS` in `src/metrics/spec.py`).

### Scope (Current Wave)
Migrated domains:
- Risk Aggregation (`analytics_risk_agg` group)
- Volatility Surface (`analytics_vol_surface` group)

Previously these metrics were registered imperatively inside helper functions (e.g. `init_risk_agg_metrics`, `init_vol_surface_metrics`) invoked by a central `group_registry`. Those helpers now remain only as no‑op compatibility shims and will be removed after at least one minor release with deprecation notice.

### Goals
1. Single authoritative declaration (names, labels, types, help) beside core governance metrics.
2. Uniform gating semantics expressed via `predicate` lambdas instead of scattered `if env_var` conditionals.
3. Easier drift detection & generation (future: auto panels / alerts per group).
4. Reduced risk of duplicate registrations from repeated imports.

### Gating Semantics Preservation
Environment flag behavior was preserved exactly by embedding logic inside each spec entry's `predicate`:

| Metric | Original Behavior | Predicate Form |
|--------|-------------------|----------------|
| `vol_surface_rows` | Enabled when group allowed | `group_allowed('analytics_vol_surface')` |
| `vol_surface_rows_expiry` | Requires group + `G6_VOL_SURFACE_PER_EXPIRY=1` | `group_allowed(..) and getenv('G6_VOL_SURFACE_PER_EXPIRY')=='1'` |
| `vol_surface_interpolated_fraction` | Enabled when group allowed | `group_allowed(..)` |
| `vol_surface_quality_score` | Requires group + `G6_VOL_SURFACE=1` | `group_allowed(..) and getenv('G6_VOL_SURFACE')=='1'` |
| `vol_surface_interp_seconds` | Enabled when group allowed | `group_allowed(..)` |
| Risk aggregation gauges | Enabled when group allowed | `group_allowed('analytics_risk_agg')` |

Helper symbol `group_allowed` above is conceptually `getattr(reg, '_group_allowed', lambda g: True)` used inside predicates.

### Backward Compatibility
Code importing `from src.metrics import get_metrics` continues to receive attributes dynamically attached during spec processing. Deprecated shims:
```
src/metrics/vol_surface.py:init_vol_surface_metrics  (no-op)
src/metrics/risk_agg.py:init_risk_agg_metrics        (no-op)
```
Removal Plan:
1. Release N: Keep shims (no-op) + deprecation note in docstring (done).
2. Release N+1: Emit `DeprecationWarning` if called explicitly (optional future step).
3. Release N+2: Delete shims & update import guidance.

### Adding Another Grouped Domain
1. Add `MetricDef` entries to `GROUPED_METRIC_SPECS` with `group=MetricGroup.<NAME>` and optional `predicate` for gating.
2. (Optional) Introduce new `MetricGroup` enum member if the group is new.
3. Run `python scripts/gen_metrics.py` and warm / drift check.
4. Add tests verifying presence / absence under gating permutations.
5. Update this section summarizing gating semantics.

### Testing
New/updated tests ensure:
- Per‑expiry rows & interpolated fraction metrics are absent when `G6_VOL_SURFACE_PER_EXPIRY` unset.
- They appear when flag set along with `G6_VOL_SURFACE=1`.
- Risk aggregation bucket utilization gauge present when `analytics_risk_agg` group enabled.

### Future Steps
- Migrate remaining legacy groups (scheduler, provider_failover, SLA health) into grouped specs.
- Auto‑generate dashboard panels grouped by domain using the same spec block.
- Expression templates for common analytic quality metrics (e.g., quality score trend alert).

Outcome: Domain metrics now enjoy identical governance (hash/provenance, warmability, drift detection) with reduced imperative boilerplate and clearer gating transparency.

## Counter Batching Layer

High-frequency counters (e.g., per-option enrichment, per-event churn) can incur lock contention in the Prometheus client registry. An opt-in batching layer aggregates increments and flushes them periodically.

Environment Flags:
- `G6_METRICS_BATCH=1` enables batching (default off).
- `G6_METRICS_BATCH_INTERVAL=2.0` flush interval seconds (float).
 - `G6_METRICS_BATCH_FLUSH_THRESHOLD=0` (optional) immediate flush when queue distinct key count >= threshold (>0). Acts in addition to periodic interval.

Metrics:
- `g6_metrics_batch_queue_depth` (gauge) – number of distinct (metric+label tuple) pending increments.

API:
```
from src.metrics.emitter import batch_inc
from src.metrics.generated import m_quote_enriched_total_labels

batch_inc(m_quote_enriched_total_labels, 'providerA')                 # +1
batch_inc(m_quote_enriched_total_labels, 'providerA', amount=5)       # +5
```
The helper falls back to immediate `.inc()` if batching is disabled or any internal error occurs.

Manual Flush (tests / shutdown):
```
from src.metrics.emitter import flush_now, pending_queue_size
flush_now(); size = pending_queue_size()
```

## Lifecycle Metrics Group

Purpose: Capture filesystem hygiene / retention activity for observability of storage growth controls.

Metrics (group: `lifecycle`):
- `g6_compressed_files_total{type}` – files compressed (simulated gzip in current stub).
- `g6_retention_files_deleted_total` – aged compressed artifacts removed by retention pruning.
- `g6_quarantine_scan_seconds` – latency scanning quarantine/retention directory root.

Gating:
- Enabled when `lifecycle` appears in `G6_ENABLE_METRIC_GROUPS` (not part of ALWAYS_ON to keep opt-in for lighter deployments).
- Further controlled by operational env flags (e.g., `G6_LIFECYCLE_JOB=1`, file age / extension selectors).

Job Invocation:
The lifecycle job (`run_lifecycle_once`) performs compression, retention pruning (future fuller implementation), and quarantine scan timing. Safe no-op if directories absent.

Future Enhancements:
- Implement real retention pruning counters (currently basic path) with limit telemetry.
- Add histogram for compression batch sizes.
- Alerting template: sustained zero compression despite eligible files.

### Retention Pruning Semantics (Implemented)

Retention deletes aged compressed artifacts (`*.gz`) after compression has occurred in a prior (or the same) cycle. It runs *after* compression to avoid immediately deleting newly compressed outputs.

Environment Flags (lifecycle scope):
| Env | Default | Purpose |
|-----|---------|---------|
| `G6_LIFECYCLE_JOB` | unset | Enable lifecycle maintenance when truthy ("1", "true", etc.). |
| `G6_LIFECYCLE_COMPRESSION_EXT` | `.csv` | Comma‑separated list of extensions (with or without leading dot) to compress when stale. |
| `G6_LIFECYCLE_COMPRESSION_AGE_SEC` | `86400` | Minimum age (seconds) before a matching file is eligible for compression. |
| `G6_LIFECYCLE_MAX_PER_CYCLE` | `25` | Cap of files processed (compressed) per invocation to bound latency. |
| `G6_LIFECYCLE_RETENTION_DAYS` | `0` | Retention window in days for deleting aged `*.gz` files. `0` disables deletion. |
| `G6_LIFECYCLE_RETENTION_DELETE_LIMIT` | `100` | Maximum deletions per cycle (safeguard). |
| `G6_LIFECYCLE_QUAR_DIR` | `data/quarantine` | Directory root for (lightweight) quarantine scan timing. |

Ordering inside `run_lifecycle_once`:
1. Compression (eligible stale source files -> write `.gz` then remove original source)
2. Retention prune (aged `.gz` only; respects delete limit & disabled window)
3. Quarantine scan timing (fast directory presence/latency observation)

Metric Emission Details:
- `compressed_files_total{type="option"}` increments only when at least one file compressed (batch count). Attribute presence depends on lifecycle group gating.
- `retention_files_deleted_total` increments only when ≥1 deletions occurred (no zero samples to avoid noise).
- `retention_candidates` (g6_retention_candidates) gauge set each run to the number of aged compressed artifacts eligible for deletion before applying the per-cycle delete limit.
- `retention_scan_seconds` histogram observes the latency of candidate enumeration + deletion phase.
- `quarantine_scan_seconds` observed every run (even if directory missing — yields trivial near‑zero timing).

Safety Characteristics:
- Deletion is limited by `G6_LIFECYCLE_RETENTION_DELETE_LIMIT` to prevent pathological long sweeps.
- Disabled retention (`G6_LIFECYCLE_RETENTION_DAYS=0`) short‑circuits with zero deletions and no counter increment.
- Only files ending with `.gz` are considered for deletion; non‑compressed artifacts are ignored (unless/until compressed in a future run).
- Failures (unlink errors, stat races) are swallowed to keep maintenance non‑fatal; successful deletions still counted.

Test Coverage (`tests/test_lifecycle_retention.py`):
- Deletes only aged `.csv.gz` past window while retaining fresh.
- Honors deletion cap when multiple candidates exceed limit.
- No-op (no deletion) when retention days set to 0.
- Ignores non‑`.gz` files (with compression disabled in test to isolate retention path).

Operational Examples:
Compress then retain daily (24h compress age, 7 day retention):
```
G6_ENABLE_METRIC_GROUPS=lifecycle \
G6_LIFECYCLE_JOB=1 \
G6_LIFECYCLE_COMPRESSION_EXT=.csv \
G6_LIFECYCLE_COMPRESSION_AGE_SEC=86400 \
G6_LIFECYCLE_RETENTION_DAYS=7 \
G6_LIFECYCLE_RETENTION_DELETE_LIMIT=200
```

Dry-run compression only (retention disabled):
```
G6_LIFECYCLE_JOB=1 \
G6_ENABLE_METRIC_GROUPS=lifecycle \
G6_LIFECYCLE_RETENTION_DAYS=0
```

High churn environment (tighter cycle with small per run cap):
```
G6_LIFECYCLE_JOB=1 \
G6_ENABLE_METRIC_GROUPS=lifecycle \
G6_LIFECYCLE_MAX_PER_CYCLE=10 \
G6_LIFECYCLE_RETENTION_DELETE_LIMIT=25
```

Planned Future Additions:
- Optional label stratification on `retention_files_deleted_total` (e.g., reason, tier) if multiple artifact classes emerge.
- Structured logging sample of top N skipped vs deleted to aid tuning of delete limits.

### Lifecycle Alert Scaffolding

Rule Groups (see `prometheus_rules.yml`):
- `g6_lifecycle.rules` – recording rules: deletions rate (`g6_retention_deletions_rate_5m`), efficiency ratio/percent, scan latency p95.
- `g6_lifecycle.alerts` – alert rules for efficiency degradation, candidate surge, and scan latency elevation.

Alert Patterns:
| Alert | Expr (simplified) | Rationale | Default Severity |
|-------|-------------------|-----------|------------------|
| G6RetentionEfficiencyLow | candidates > 10 AND efficiency% < 30 | Sustained under-utilization of retention window | warning |
| G6RetentionEfficiencyCritical | candidates > 25 AND efficiency% < 15 | Near-stall; backlog growing | critical |
| G6RetentionCandidateSurge | candidates > 100 | Sudden buildup independent of efficiency | info |
| G6RetentionScanLatencyHigh | scan p95 > 0.5s | Emerging IO/dir traversal contention | warning |
| G6RetentionScanLatencyCritical | scan p95 > 1.0s | Severe IO contention impacting hygiene | critical |

Tuning Guidance:
- Allow at least one full retention cycle baseline (e.g., 24–48h) and compute p95(p95_latency) before tightening thresholds.
- If candidates are naturally spiky (batch compress), consider adding `avg_over_time(g6_retention_candidates[10m])` variant for stability.
- For efficiency alerts, if delete limit intentionally constrains per cycle, adjust thresholds or add a future metric `retention_delete_limit` to join.

Future Alert Enhancements:
- Efficiency slope detection: decreasing trend over N cycles using `predict_linear` or derivative of ratio.
- Candidate backlog age layering once per-candidate age histogram or bucketization added.
- Auto-silence during maintenance windows via environment-driven annotation or silence automation.

Design Notes:
- Only counters are batched; gauges / histograms often convey real-time values or latencies where immediate emission is preferred.
- Queue key is `(accessor id, accessor function ref, label tuple)`; increments collapse per flush window.
- Background thread flushes every interval; explicit `flush_now()` used in unit tests to make assertions deterministic.
- Safe degradation: Any exception during accessor resolution logs once per signature and continues.

When to Use:
- Hot paths with many small increments (e.g., per instrument processing loops, tight event loops) where cumulative cost shows up in profiling.
- Not recommended for very low-frequency counters (overhead savings negligible) or when real-time visibility of increment is required for alerting within the flush interval.

Future Enhancements:
 - Dynamic interval backoff (shorter period when sustained high queue depth without threshold trigger).
- Per-metric opt-out (e.g., critical real-time counters) even under global batching flag.
- Observability: add cumulative dropped/failed flush counters.
 - Histogram of batch sizes & flush latency distribution.


## Quick Commands (local)
```
python scripts/gen_metrics.py
python scripts/exercise_metrics.py --run-drift-check
python scripts/metrics_drift_check.py --endpoint http://localhost:9108/metrics
```

## Troubleshooting
| Symptom | Likely Cause | Resolution |
|---------|--------------|-----------|
| Drift: missing metric | Not warmed / server not started / instrumentation absent | Ensure server running, run exercise script, implement emission |
| Drift: extra metric | Spec forgot to include or legacy metric still emitted | Add to spec OR remove legacy emission |
| Workflow fails on uncommitted changes | Forgot to commit regenerated `generated.py` or catalog | Regenerate & commit |
| Panel blank after deploy | Metric not warmed yet | Include warm script pre-flight or ensure first emission sooner |

---
Governance keeps observability disciplined and scalable—treat the spec as code.
