# Grafana Dashboard Generation (Modular Generator)

Date: 2025-10-05
Status: Phase D/E/F complete (metadata enrichment, new focused dashboards, enhanced drift diff).

## Overview
The modular generator (`scripts/gen_dashboards_modular.py`) produces deterministic, provision-ready Grafana dashboards from the governed Prometheus metrics spec (`metrics/spec/base.yml`). It replaces ad‑hoc hand edited JSON and enables:

- Reproducible dashboards (content hash & semantic diff guard)
- Enforced mapping from metric families -> dashboard plans
- Auto-synthesis of common panels (rates, histogram quantiles, limited label splits)
- Cross-metric efficiency diagnostics (diff bytes per write, ingest bytes per row, backlog drain ETA)
- Governance & provenance metadata embedding for both dashboards and individual panels

## Dashboard Plans
Plans define which metric families appear together. Default plans (at time of writing):
`provider_ingestion`, `bus_stream`, `emission_pipeline`, `panels_summary`, `column_store`, `governance`, `option_chain`, `system_overview`, `panels_efficiency`, `lifecycle_storage`, `health_core`, `bus_health`, `system_overview_minimal`.

Each plan (`DashboardPlan`) has: `slug`, `title`, `families`, `description`, optional `tags`.

## Panel Synthesis Pipeline
1. Load spec metrics: name, kind (counter|gauge|histogram), labels, inline panel hints (`panels:`), alerts.
2. For each dashboard plan:
   - Select metrics whose `family` in plan.families.
   - Convert explicit spec panels first.
   - Synthesize auto panels:
     * Counter: rate(5m) if no explicit rate panel
     * Histogram: p95/p99 panels using recording rule series (`<metric>:p95_5m`, etc.)
     * Gauge with labels: TopK (5) panel if absent
     * Limited label splits (<=2 labels) auto-generated for counter/gauge (rate or sum by label)
   - Add placeholder panel if still empty for a metric.
   - Append cross-metric efficiency panels (select dashboards only).
   - Group & cap (core vs efficiency) with safety limits (24 core, 12 efficiency).
   - Insert alerts overview table (aggregated spec alerts) if any alerts for included metrics.
   - For governance plan, insert recording rule usage summary table.
3. Layout pass groups wide/table panels first, then two-column core, then efficiency section (optional header).
4. Stable IDs assigned using `sha256(plan.slug + semantic_panel_signature)` (first 8 hex -> int id, first 16 hex -> `panel_uuid`).

## Metadata (g6_meta)
Dashboard-level:
| Field | Meaning |
|-------|---------|
| `spec_hash` | First 16 hex chars of spec file SHA256 (strict drift key) |
| `families` | Families included by plan |
| `placeholder_panels` | True if every non-table panel was auto/placeholder |
| `description` | Plan description (human) |
| `enriched` | Always true (marker for post-Phase A) |
| `alerts_panel` / `alerts_count` | Whether aggregated alerts table inserted |
| `generator_version` | Semantic version of generation logic (bumped on material changes) |

Panel-level (enriched Phase E):
| Field | Example | Description |
|-------|---------|-------------|
| `panel_uuid` | `9ab3f1c2d4e5f607` | Stable 64-bit (hex16) identity prefix for traceability |
| `metric` | `g6_bus_events_published_total` | Base metric (if applicable) |
| `family` | `bus` | Metric family from spec |
| `kind` | `counter` | Metric type |
| `source` | `spec` / `auto_rate` / `auto_hist_quantile` / `auto_topk` / `auto_label_split` / `placeholder` / `cross_metric` / `alerts_aggregate` / `governance_summary` | Generation origin |
| `split_label` | `bus` | Present for label-split auto panels |
| `group` | `efficiency` | Present for efficiency diagnostics grouping |
| `group_header` | `true` | Only on the efficiency header table |
| `alerts_count` | integer | Only on alerts overview table |
| `migrated_percent` | 87.5 | Governance rule migration percent (governance dashboard) |

## Semantic Panel Signature
Used for deterministic IDs and drift diff. Components hashed:
`{type, title, sorted target PromQL exprs, datasource.type, field unit}`.
Ignored: layout (`gridPos`), internal `id`, `panel_uuid`, ordering.

## Drift Detection (`--verify`)
`python scripts/gen_dashboards_modular.py --verify` compares freshly synthesized dashboards with existing files:
- Fails (exit 6) if:
  * Dashboard missing
  * Spec hash mismatch
  * Panels added/removed/changed (semantic signature)
Outputs tokens like: `changed:governance:2`, `added:bus_health:1`, `removed:system_overview:1`.

Verbose Mode: set `G6_DASHBOARD_DIFF_VERBOSE=1` to emit JSON lines between `DRIFT_DETAILS_BEGIN/END` containing arrays of `changed_titles`, `added_titles`, `removed_titles` per slug.

## Partial Regeneration (`--only`)
Use `--only <slug[,slug2]>` to regenerate a subset without touching other dashboard JSON files. Skipped dashboards retain their existing JSON; manifest still lists all dashboards with `panel_count=0` for skipped ones (explicit signal of omission). This accelerates local iteration for a single plan while keeping CI semantics consistent.

Example:
```powershell
python scripts/gen_dashboards_modular.py --output grafana/dashboards/generated --only bus_health,system_overview_minimal
```
Follow with a full run (without `--only`) before commit to restore panel counts in manifest.

## Panel Inventory Export
Script: `scripts/export_dashboard_inventory.py`

Exports a governance-friendly panel inventory with columns:
`slug,title,metric,source,panel_uuid`

Examples:
```powershell
python scripts/export_dashboard_inventory.py --format csv --out panels.csv
python scripts/export_dashboard_inventory.py --format jsonl --filter-source spec > spec_panels.jsonl
```

Filtering:
`--filter-source spec,auto_rate` restricts output to specified `g6_meta.source` values.

Use Cases:
* Governance audits (ensure all spec metrics have at least one visualization)
* Panel rename impact analysis (stable `panel_uuid` allows diffing inventories)
* CI coverage gate (future): diff against previous inventory to detect accidental panel removals.

Exit codes: 0 success, 2 invalid format, 3 no dashboards/panels found.

## Inventory Diff
Script: `scripts/diff_dashboard_inventory.py`

Compare two inventories (previous vs current) keyed by `panel_uuid` to classify:
* Added: present only in current
* Removed: present only in previous
* Renamed: same `panel_uuid` but title changed

Example workflow (PowerShell):
```powershell
python scripts/export_dashboard_inventory.py --format csv --out inv_prev.csv
# make changes / regenerate
python scripts/export_dashboard_inventory.py --format csv --out inv_curr.csv
python scripts/diff_dashboard_inventory.py inv_prev.csv inv_curr.csv --json-out diff.json
```

Exit codes: 0 (no differences), 7 (differences). Use in CI to guard accidental panel removal or unexpected rename churn.
`--json-out` provides machine-readable arrays `added`, `removed`, `renamed` (each renamed entry contains `panel_uuid`, `old_title`, `new_title`, `slug`).

## Environment Flags
| Flag | Purpose |
|------|---------|
| `G6_DASHBOARD_DIFF_VERBOSE=1` | Enable verbose drift title output |
| `G6_DASHBOARD_DENSE=1` | Compact certain panel heights for higher info density |
| `G6_EGRESS_FROZEN=1` | Does NOT disable Grafana generation (only non-Prometheus diff egress) |

## Generator Versioning
`g6_meta.generator_version` increments when semantics that could trigger broad drift change. Current: `phaseDEF-1` (added new plans + metadata enrichment + verbose drift).

## Adding a New Dashboard Plan
1. Append a `DashboardPlan` to `DEFAULT_PLANS` (avoid slug collision).
2. Regenerate (`--verify` first to see expected drift).
3. Commit JSON + updated manifest.
4. (Optional) Add plan description to README or this doc if widely used.

## Adding Metric Panels via Spec
Add under metric in `metrics/spec/base.yml`:
```yaml
panels:
  - title: Foo Rate (5m)
    promql: sum(rate(g6_foo_total[5m]))
    unit: short
    panel_type: timeseries
```
Regenerate. If rate already auto-generated you may see a `changed:` drift token (different signature). Remove competing auto by providing explicit equivalent panel.

## Efficiency Panels Source Logic
Injected only for slugs: `panels_efficiency`, `column_store`, `lifecycle_storage`.
Panel ordering uses a fixed prefix rank map for stable diff-friendly layout.

## Governance Summary Panel
Inserted only in `governance` slug; summarizes migration from inline histogram quantiles to recording rule references. Aids tracking technical debt payoff.

## Manifest (`grafana/dashboards/generated/manifest.json`)
Fields: `spec_hash`, `generated_at_unix`, `count`, per dashboard: `slug`, `uid`, `families`, `panel_count`.
Use it for provisioning automation or lightweight health checks comparing expected dashboard count & spec hash.

## FAQ
| Question | Answer |
|----------|--------|
| Why not store panel layout in spec? | Layout heuristics evolve; separation keeps spec focused on metric intent while generator handles presentation. |
| Why SHA256 first 8 hex for panel id? | Fits Grafana's numeric id expectations while providing stable collision-resistant mapping (2^32 space). |
| How to ignore transient drift in CI? | Run verify before committing; only commit JSON after deliberate regeneration. For temporary allowance set a CI variable to skip verify step (not recommended long term). |
| Can I generate only one dashboard? | Not yet; future flag `--only <slug>` planned. |
| Do metadata changes cause semantic drift? | No—semantic signature excludes metadata so ops-only annotation changes won't force JSON churn. |

## Roadmap (Generator)
- `--only <slug>` generation flag
- Declarative external plan YAML ingestion (already supported via `--plan`, expand docs)
- Alert rule embedding preview mode
- Optional per-dashboard custom time range & refresh overrides via plan extension
- Panel inventory export (CSV / JSONL) for provenance audits

---
End of document.
