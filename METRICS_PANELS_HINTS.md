# Metrics Panel Hints Schema

Panel hints let the metrics spec drive richer, intent-aware dashboard generation.
They live inline with each metric entry under a `panels:` list.

## Supported Keys (per hint object)
| Key | Required | Description |
|-----|----------|-------------|
| `title` | Yes | Panel title text. |
| `promql` | Yes | Prometheus query expression. |
| `kind` | No | Semantic tag (e.g., `rate_total`, `latency_p95`). Not interpreted by generator but kept in `g6_meta`. |
| `panel_type` | No | Grafana panel type override (`stat`, `timeseries`, `table`, etc.). Default: heuristic. |
| `span` | No | Panel width (1–24). Default: 6. Height fixed at 5 for compact grid. |
| `unit` | No | Grafana fieldConfig unit (e.g., `ms`, `percent`). |

## Example (Excerpt)
```yaml
- name: g6_api_response_latency_ms
  type: histogram
  ...
  panels:
    - kind: latency_p95
      title: API Latency p95 (5m)
      promql: |
        histogram_quantile(0.95, sum by (le) (rate(g6_api_response_latency_ms_bucket[5m])))
      unit: ms
    - kind: latency_rate
      title: API Latency Bucket Rates
      promql: |
        sum by (le) (rate(g6_api_response_latency_ms_bucket[5m]))
      panel_type: timeseries
```

## Generation Behavior
1. For each metric with `panels`, the generator creates one panel per hint in order.
2. Metrics without hints fall back to heuristic panels based on type:
   - counter -> stat panel with `sum(rate(metric[5m]))`
   - gauge   -> stat panel with raw value
   - histogram -> timeseries of bucket rates
3. Panels wrap to a new row when cumulative width reaches 24.
4. A row header is inserted per family: `Family: <family_name>`.

## Embedded Metadata
Each hint-derived panel contains a `g6_meta` stanza:
```json
"g6_meta": {"kind": "latency_p95", "base_metric": "g6_api_response_latency_ms"}
```
Useful for diffing, programmatic modifications, or future selective regeneration.

## Design Rationale
- Keeps observable intent (p95, error rate, breakdown) close to the metric definition.
- Minimizes manual JSON dashboard drift—regeneration is deterministic.
- Allows incremental enrichment: start with heuristics, add hints only where custom queries matter.

## Extensibility Ideas
Future hint keys we could introduce:
- `thresholds`: Provide alert or visual threshold lines.
- `legend`: Override legend format.
- `transform`: Simple post-query transformations (rate/window selection hints) before panel build.
- `alert`: Embed alert rule template for separate rule generation.

## Workflow
1. Add/update `panels` under metric in `metrics/spec/base.yml`.
2. Run generator:
   ```
   python scripts/gen_dashboard_from_spec.py --force --out grafana/dashboards/g6_spec_panels_dashboard.json
   ```
3. Load new dashboard in Grafana (provision file or import manually).
4. Iterate as required—commit spec + regenerated dashboard.

## Caveats
- Generator does not de-duplicate identical queries across hints.
- Histogram quantile hints must explicitly use `histogram_quantile`; no auto generation today.
- Units are passed verbatim; ensure they match Grafana's recognized unit strings.

## Troubleshooting
| Issue | Cause | Fix |
|-------|-------|-----|
| Missing panel | Hint lacks `title` or `promql` | Add required keys |
| Wrong panel type | Heuristic fallback used | Set `panel_type` explicitly |
| Layout awkward | Adjust `span` sizes to balance 24-column grid |
| Old panels lingering | Forgot `--force` or removed hints but reused output file | Regenerate with `--force` |

## Spec Hash Panel
If `g6_metrics_spec_hash_info` is present the generator will produce a table panel (kind: `spec_hash`) showing the current spec hash label. Use it to quickly confirm the expected spec is live in each environment.

---
Panel hints unify metric semantics and visualization intent—treat them as first-class config alongside the metric itself.
