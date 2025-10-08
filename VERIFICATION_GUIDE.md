# Provider & System Health Verification Guide

Date: 2025-10-04
Scope: Validating the `g6_provider_system_health` Grafana dashboard, generated metrics instrumentation, batching, and fallback/expiry behaviors.

Governance Note: For end-to-end specification, generation, warming, and CI drift enforcement details, see `METRICS_GOVERNANCE.md`.

---
## 1. Environment Preconditions
Ensure:
- Prometheus is scraping the Python process (confirm by opening the /metrics endpoint).
- Grafana has provisioned `grafana/dashboards/g6_provider_system_health.json`.
- Python deps installed (`requirements.txt`).

Optional env vars:
- `G6_PROVIDER_METRICS_DEBUG=1` – verbose enrichment debug logs.
- `G6_METRICS_BATCH=1` – enable batched counter emission.
- `G6_METRICS_BATCH_INTERVAL=1.0` – adjust batch flush seconds.
- `G6_TRACE_EXPIRY_SELECTION=1` – detailed expiry selection trace.

---
## 2. Start Core Simulation
Use VS Code tasks:
1. Run: `Smoke: Start Simulator` (background)
2. Run: `Smoke: Summary Demo` OR `Smoke: Summary (panels mode)`

Expected early metrics (within ~2 scrapes):
- `g6_api_calls_total` increments (endpoint="get_quote", result="success").
- `g6_quote_enriched_total` rising.
- `g6_api_response_latency_ms_bucket` buckets present.
- Exactly one non‑zero `g6_provider_mode{mode=...}`.

If batching enabled, initial counter rise may lag up to the flush interval.

---
## 3. Trigger Zero Price Fallbacks
Goal: increment `g6_index_zero_price_fallback_total{path="quote"}` or `{path="ltp"}`.

Methods:
A. Modify mock provider to return `last_price=0` for an index (e.g. NIFTY) in `get_quote` once.
B. Force LTP fallback by making `get_quote` raise so LTP path executes, returning `last_price=0`.

Validation PromQL:
```
increase(g6_index_zero_price_fallback_total[10m])
sum by (index,path) (increase(g6_index_zero_price_fallback_total[6h]))
```
Dashboard: "Index Zero Price Fallbacks (1h)" & timeseries panels show increments.

---
## 4. Trigger Expiry Resolution Failures
Metric: `g6_expiry_resolve_fail_total{index,rule,reason}`.

Scenarios:
1. Unknown rule:
```python
from src.collectors.providers_interface import Providers
p = Providers(primary_provider=object())  # lacks get_expiry_dates
try:
    p.resolve_expiry('NIFTY', 'not_a_rule')
except Exception: pass
```
Expect reason `no_method` then `unknown_rule` if method present but rule invalid.

2. Empty future expiries:
```python
class Stub: 
    def get_expiry_dates(self, index): return []
p = Providers(primary_provider=Stub())
try: p.resolve_expiry('NIFTY','this_week')
except Exception: pass
```
Expect reason `empty_future`.

PromQL checks:
```
sum by (reason) (increase(g6_expiry_resolve_fail_total[10m]))
```
Dashboard: "Expiry Failures by Reason" timeseries shows lines for triggered reasons.

---
## 5. Validate Quote Enrichment Panels
Increase number of option instruments in the simulator to boost rates.
PromQL:
```
sum(rate(g6_quote_enriched_total[5m]))
sum by (provider) (rate(g6_quote_enriched_total[5m]))
```
Dashboard: Enriched Quotes Rate, Enrichment Throughput by Provider populate.

Missing Volume/OI / Avg Price fallback:
```
sum(rate(g6_quote_missing_volume_oi_total[10m]))
sum(rate(g6_quote_avg_price_fallback_total[10m]))
```

---
## 6. Exercise Batching
Enable batching:
```
$env:G6_METRICS_BATCH = '1'
$env:G6_METRICS_BATCH_INTERVAL = '1.5'
```
Restart simulator tasks.

Observation:
- Rate panels stable.
- Raw increase stats (e.g. 5m sum) may update after flush boundary.

To confirm batching effect: capture /metrics immediately after a burst -> counters possibly unchanged; re-check after interval -> incremented.

---
## 7. API Error Path
Induce errors by injecting an exception in provider `get_quote` every Nth call.
Expect `g6_api_calls_total{result="error"}` > 0.
PromQL:
```
sum by (endpoint,result) (rate(g6_api_calls_total[5m]))
```
Dashboard: "API Error Rate (5m)" & stacked calls timeseries reflect errors.

---
## 8. Latency Distribution Stress
Add `time.sleep(0.25)` inside `get_quote` temporarily.
Check:
```
histogram_quantile(0.95, sum by (le) (rate(g6_api_response_latency_ms_bucket[5m])))
```
Dashboard: p95/p99 climb; bucket rates show >200ms buckets non-zero.

---
## 9. Cardinality Guard Sanity
Attempt adding >5 distinct provider names (if possible). Further new label sets should not appear.
PromQL:
```
count(sum by (provider) (g6_quote_enriched_total))
```
Expect value <= budget (5).

---
## 10. Panel Population Checklist
| Panel | Trigger | Verified When |
|-------|---------|---------------|
| Active Provider Mode | Simulator start | Single non-zero mode series |
| API Success % | Calls flowing | Gauge near 100% (unless errors induced) |
| p95 / p99 Latency | Histogram samples | Non-zero values after delay injection |
| Enrichment Throughput | Enrichment running | Lines per provider |
| Zero Price Fallbacks | Forced zero price | Stat & timeseries increment |
| Expiry Failures | Resolve failures | Reason lines visible |
| Success vs Error | Introduced errors | Separate success/error series |
| Batching Note | Always | Text visible |
| 12h Fallback / Failures | Long window activity | Counters accumulate |

---
## 11. Troubleshooting
| Symptom | Cause | Action |
|---------|-------|--------|
| All panels blank | Scrape misconfig | Verify Prometheus target /metrics reachable |
| Fallback panels empty | Price not zeroed | Re-check provider override executed |
| Expiry failures absent | Rule path not hit | Ensure stub or bad rule actually used |
| Error rate stays 0 | Exceptions swallowed early | Verify error path increments metrics |
| Counters delayed | Batching on | Lower interval or disable batching |

---
## 12. Success Criteria
1. Each new panel shows realistic non-zero data after its scenario.
2. No runaway label growth (budgets respected).
3. Latency and enrichment panels respond to induced changes.
4. Fallback & expiry failure panels increment in controlled tests.
5. Post-test removal of instrumentation restores baseline metrics stability.
6. Grafana dashboard generation verify mode passes (no unintended semantic drift) after regeneration.

---
## 13. Cleanup
- Revert temporary sleeps / forced exceptions.
- Unset batching & debug env vars if not desired in production.
- Commit only intentional code changes (exclude local debug edits).
 - If dashboards were modified intentionally run generation with `--verify` once more to ensure a clean baseline.

---
## 15. Dashboard Drift Verification (Added)

Use the modular generator drift guard to ensure committed Grafana JSON matches current spec & synthesis rules.

Commands (PowerShell):
```powershell
python scripts/gen_dashboards_modular.py --output grafana/dashboards/generated --verify
```

Exit Codes:
| Code | Meaning |
|------|---------|
| 0 | No drift (semantic & hash clean) |
| 6 | Drift detected (added/removed/changed panels or spec hash mismatch) |

Set `G6_DASHBOARD_DIFF_VERBOSE=1` to emit JSON detail blocks between `DRIFT_DETAILS_BEGIN` / `DRIFT_DETAILS_END` containing arrays of changed, added, and removed panel titles for each dashboard slug. This aids rapid code review triage.

Typical CI Pattern:
1. Run verify (expect drift=6) immediately after modifying `metrics/spec/base.yml` or generator logic.
2. Regenerate dashboards without `--verify` to update JSON.
3. Re-run verify (expect 0) before commit.

If a spec change should not alter dashboards (unexpected drift), inspect verbose details and confirm panel metadata vs semantic signature components. Metadata-only changes (e.g., `g6_meta` additions) are excluded from the signature and will not produce drift.

---
## 14. Future Enhancements
- Add batch queue depth gauge.
- Automated spec-vs-scrape drift CI check.
- Alert rules: elevated fallback or expiry failure rates.

### Update: Batch & Cardinality Metrics Implemented
The following have now been added and are visible on the Provider & System Health dashboard:

| Metric | Panel Title | Purpose |
|--------|-------------|---------|
| `g6_metrics_batch_queue_depth` | Batch Queue Depth | Real-time size of pending batched counter increments (should return to 0 post-flush). |
| `g6_cardinality_series_total{metric="..."}` | Cardinality Series Count (Top), Max Series Count, Unique Series Tracked | Observes unique label sets per metric to spot drift / explosion early. |

Drift Check Script:
Run:
```
python scripts/metrics_drift_check.py --endpoint http://localhost:9108/metrics --verbose
```
Set `G6_METRICS_STRICT=1` to fail build on undeclared extra runtime metrics.

---
**End of Guide**
