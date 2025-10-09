# Grafana setup

This repository ships generated dashboards and provisioning files.

- Generated dashboards live under `grafana/dashboards/generated/` (with `manifest.json`).
- Provisioning is defined in `grafana/provisioning/dashboards/dashboards.yml`.

Quick start:
- Start Grafana with provisioning enabled. Ensure the working directory is the repo root so the relative path in the provider resolves to `grafana/dashboards/generated`.
- Alternatively, adjust `options.path` to an absolute path for your environment.

Governance:
- Run the modular generator with verify before committing: `python scripts/gen_dashboards_modular.py --verify` (non-zero on drift).
- Regenerate dashboards if needed and commit updated JSON and `manifest.json`.
- Recording rules can be checked with `python scripts/gen_recording_rules.py --check`.
 - Spec-to-panels coverage: run `python scripts/validate_spec_panel_coverage.py --allow-partial --list-missing` (fails with exit 11 on uncovered spec panels).
 - PromQL lint:
   - Validate dashboard PromQL via promtool:
     - Basic: `python scripts/lint_dashboard_promql.py`
     - Strict (require promtool): `python scripts/lint_dashboard_promql.py --require-promtool`
     - If promtool isn't on PATH, point to it: `python scripts/lint_dashboard_promql.py --require-promtool --promtool "C:\\Prometheus\\prometheus-3.5.0.windows-amd64\\promtool.exe"`
     - By default, Grafana-templated expressions containing `$` (e.g., `$__interval`, `$metric`) are skipped to avoid promtool parse errors. Use `--include-templated` to attempt linting them.

 Windows promtool setup tips:
 - Install Prometheus bundle (includes promtool) and add its folder to PATH, e.g. `C:\\Prometheus\\prometheus-<VERSION>.windows-amd64`.
 - One-session PATH update (PowerShell): `$env:Path += ";C:\\Prometheus\\prometheus-<VERSION>.windows-amd64"`
 - Verify: `promtool --version`
# G6 Grafana Dashboard Bundle

This directory contains a curated, provisionable bundle of Grafana dashboards covering core runtime health, events streaming integrity, diff write efficiency, adaptive alerting, memory pressure adaptation, and navigation.

## Dashboards

| UID | File | Purpose |
|-----|------|---------|
| g6-core-ops-001 | dashboards/g6_core_ops.json | Condensed operational heartbeat & integrity highlights |
| g6-core-ovw-001 | dashboards/g6_core_overview.json | Detailed cycles, success %, resource and latency overview |
| g6-obsv-001 | dashboards/g6_observability.json | Broad platform observability (API, cycles, index drilldowns) |
| g6-memory-001 | dashboards/g6_memory_adaptation.json | Memory pressure state, actions & feature adaptations |
| g6-events-001 | dashboards/g6_events_stream.json | Events stream diff integrity & recovery signals |
| g6-diff-eff-001 | dashboards/g6_panel_diff_efficiency.json | Panel diff vs full efficiency, bytes saved, drop context |
| g6-alerts-001 | dashboards/g6_adaptive_alerts.json | Alert rule surfacing & stability indicators |
| g6-master-001 | dashboards/g6_master_index.json | Navigation & top KPIs launcher |
| g6-lifecycle-001 | dashboards/g6_lifecycle_hygiene.json | Filesystem hygiene: compression, retention deletions, quarantine scan latency |

Additional legacy / specialized dashboards remain in `dashboards/`.

## Provisioning

A provisioning definition is provided at `provisioning/dashboards/g6_dashboards_provider.yaml`.
It expects dashboards to be mounted/placed at:

```
/var/lib/grafana/dashboards/g6
```

You can either:
1. Copy the `dashboards/` directory into that path inside the Grafana container/pod.
2. Mount this repo path into the container at the expected location.

Example (Docker Compose snippet):

```yaml
grafana:
  image: grafana/grafana:10.3.0
  volumes:
    - ./grafana/dashboards:/var/lib/grafana/dashboards/g6:ro
    - ./grafana/provisioning/dashboards:/etc/grafana/provisioning/dashboards:ro
```

Grafana will auto-load or update every 30s (`updateIntervalSeconds: 30`).

## Datasource Variable

Each dashboard declares a datasource variable `DS_PROM` (Prometheus). If provisioning already binds a default Prometheus instance, no change is required. To switch environments, change the dashboard variable once within the UI (or override via JSON patch in automation).

## Conventions

- Time Range: Default `now-6h` across dashboards.
- Refresh: `30s` (adjust in UI for high-churn debugging).
- Percent Units: Instant percentage values use 0–100 with `percent`; ratios 0–1 use `percentunit`.
- UIDs: `g6-<domain>-<nnn>` to keep stable links while allowing future revisions (e.g. `g6-events-002`).
- Row Descriptions: Provide scanning context without opening every panel.
- Alert Surfacing: Derived alert metrics (e.g. `g6_events_dropped_diffs_alert`) shown as binary stats for at-a-glance triage.

## Derived / Recording Rule Dependencies

Some panels rely on recording rules defined in `prometheus_rules.yml` (e.g. `g6:api_latency_p95_5m`, `g6:freshness_minutes`, `g6_events_dropped_generation_mismatch_10m`, `g6_panel_diff_write_savings_ratio`). Ensure those rules are loaded in Prometheus; otherwise panels may show `N/A`.

### Aggregated Health Score (New)

Recording rule: `g6:aggregated_health_score` (range 0–1; displayed as percent in dashboards).

Formula & weights:

```
( ErrorsInverse * 0.25 ) + ( API Success Rate * 0.25 ) + ( Collection Success Rate * 0.20 ) + ( Backlog Headroom * 0.15 ) + ( NeedFull Absence * 0.15 )
```

Where:
- ErrorsInverse = `1 - clamp_max(sum(rate(g6_total_errors_total[5m]))/5, 1)` (assumes >5 errors/s over 5m saturates penalty)
- API Success Rate = `clamp_max(g6_api_success_rate_percent/100, 1)`
- Collection Success Rate = `clamp_max(g6_collection_success_rate_percent/100, 1)`
- Backlog Headroom = `1 - clamp_max(g6_events_backlog_current / clamp_min(g6_events_backlog_highwater,1), 1)`
- NeedFull Absence = `1 - clamp_max(g6_events_need_full_active, 1)`

Alert Thresholds:
- Warning: < 0.85 for 10m (`G6HealthScoreDegraded`)
- Critical: < 0.70 for 5m (`G6HealthScoreCritical`)

Operational Notes:
- Brief dips during intentional recoveries (forced full baseline) are expected; alerts require sustained low score.
- Backlog headroom & need_full absence protect against silent diff rejection scenarios even when success rates look healthy.
- Adjust component weights by editing the recording rule; ensure documentation is updated in this section when changed.

## Recommended Triage Flow

1. Master Index → check top KPIs & whether any integrity / memory pressure flags are non-green.
2. Adaptive Alerts → confirm which alerts (if any) are active; note spikes or flapping patterns.
3. Events & Diff Integrity → inspect mismatch drops, episodes, recovery cadence, backlog pressure.
4. Panel Diff Efficiency → validate that savings ratio remains within expected band; investigate spikes in full writes.
5. Memory Adaptation → correlate pressure transitions with any efficiency degradation.
6. Core Ops / Overview → deep dive into cycle latency, error distribution, resource trends.

## Versioning Strategy

- Increment the `version` field only when structural/panel changes occur (Grafana uses this for state diff).
- For purely textual description edits, version bump optional.

## Extending

When adding a new dashboard:
- Follow file naming `g6_<domain>.json`.
- Assign a new incremental UID suffix `<nnn>` while preserving prior ones for links.
- Include `__inputs` / `__requires` for easier manual import.
- Reuse `DS_PROM` variable and default time range.

## Validation Checklist

- [ ] Panels load without `N/A` (verify Prometheus has required series).
- [ ] Alert stat tiles flip to `ALERT` on synthetic rule trigger tests.
- [ ] Navigation links function (same domain base path in Grafana).

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| All panels show `N/A` | Datasource variable not bound | Re-select Prometheus in variable dropdown |
| Alert tiles always 0 | Prometheus rules not loaded | Load `prometheus_rules.yml` into server config & reload |
| Backlog utilization 0 while events flowing | `g6_events_backlog_highwater` absent | Verify event bus metrics registration path |
| Savings ratio flat | Diff path disabled or only full writes | Inspect publisher diff logic / recent errors |

## License / Attribution

Internal dashboards; adjust for external distribution by removing environment-specific expressions if needed.

---
Generated as part of the unified push-based observability enhancement initiative.

## Lifecycle Hygiene Dashboard (g6-lifecycle-001)

Focus: Filesystem lifecycle efficiency & latency: compression throughput, retention pruning effectiveness, candidate backlog, and scan latency health with integrated runbook access.

### Key Panels & Layout
Row: Overview
- Compressed Files (5m rate) – Rolling compression operations rate; watch for sustained drops (possible worker starvation).
- Retention Deletions (5m rate) – Actual prune deletions; compare with candidate backlog to assess sufficiency.
- Compression by Type (timeseries) – Breakdown if multiple compression types emerge (future‑proofing).

Rows: Lifecycle Activity & Latency
- Quarantine Scan Seconds (avg) – Average duration of quarantine scan operations; unexpected rises often correlate with directory bloat.
- Retention Deletions (timeseries) – Visual trend of deletion velocity (distinct from stat tile value).
- Retention Candidates (current) – Gauge of backlog pressure; should oscillate not monotonically rise.
- Retention Scan Latency Avg / p95 – Mean vs p95 separation helps identify emerging long-tail slowness.

Ratios & Efficiency
- Deletion Efficiency % (5m) = deletions rate / candidates (bounded) * 100; primary signal for retention keeping pace.
- Deletions per Candidate (5m) – Complementary ratio (0–1) for small backlogs; redundancy aids intuitive reading when candidate scale changes.

Alert Tiles Row
- Binary stat panels (value 0/1) for each lifecycle alert rule: Efficiency Low, Efficiency Critical, Candidate Surge, Scan Latency High, Scan Latency Critical, plus aggregate sum.
- Color thresholds align with alert severity; descriptions supply first-triage hints.

Runbooks Panel
Markdown table enumerating scenarios, alert indicator environment variable names (metric rule names), first investigative steps, and deep runbook links.

### Recording / Alert Rule Dependencies
Relies on lifecycle recording & alert groups defined in `prometheus_rules.yml` (group: `g6_lifecycle.alerts`). Ensure those rules are loaded; otherwise alert tiles remain 0.

### Operational Interpretation
1. Rising `g6_retention_candidates` with flat deletions implies insufficient delete quota or blocked IO.
2. Efficiency % < 25% consistently → impending storage pressure; consider temporarily lifting deletion cap.
3. Scan latency p95 growth without avg growth hints at pathological directories (deep nesting / cold storage tier).
4. Candidate Surge + High Scan Latency together often precede efficiency degradation (scan cycles not finishing quickly enough to feed deletions selection logic).

### Runbook Link Strategy
- Each alert stat panel includes a `links` array pointing to the specific runbook anchor.
- A consolidated Runbooks markdown panel provides tabular overview for paging / doc search.
- When internal domain finalizes, globally search/replace `runbooks.example.com`.

### Contribution Guidelines (Lifecycle Dashboard)
When adding or modifying panels:
1. Increment `version` only if panel structure (add/remove/reposition) or expressions change.
2. Maintain explicit `gridPos` for deterministic diffs (avoid Grafana auto-layout churn in Git).
3. Keep alert panel IDs stable (11–16) so external documentation or screenshots remain valid.
4. If introducing new retention metrics (e.g., candidate age histogram), group them logically beneath existing latency section and bump version.
5. Add short `description` fields instead of verbose titles; keep titles concise.
6. Update this README section with any new ratios or semantics (e.g., if adding “Delete Limit Utilization %”).

### Potential Future Enhancements
- Candidate Age Distribution (histogram visualization) for backlog aging risk.
- Delete Limit Utilization panel (observed deletions vs configured cap).
- Rolling 24h Retention Effectiveness (area under efficiency % threshold) indicator.
- Automated runbook link validator (script to assert 200 responses in CI for runbook URLs).

### Quick Sanity Checklist (Post-Change)
- [ ] New metric visible in Prometheus (`/api/v1/series`) before dashboard import.
- [ ] Panel expression returns data over `now-6h`.
- [ ] Alert tiles behave under synthetic load (use rule evaluation delay or test environment to force conditions).
- [ ] Runbook links open directly to anchor (browser hash).
- [ ] No overlapping `gridPos` rectangles in modified region.

