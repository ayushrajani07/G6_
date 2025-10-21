# G6 Analytics – Infinity v4 (Plugin-less)

This dashboard shows live analytics sourced from a FastAPI JSON service that reads today’s CSVs (refreshed ~15s). It’s plugin-less at runtime, using the Infinity datasource for HTTP JSON.

- File: `grafana/dashboards/generated/g6_analytics_infinity_v4.json`
- UID: `g6-analytics-infinity-v4`
- Port: `http://127.0.0.1:3002`

## Variables
- `offset`: Shift selection horizon in minutes ("0,+100,-100,+200,-200").
- `expiry_ns`: Expiry tag for NIFTY/SENSEX ("this_week,next_week,this_month,next_month").
- `expiry_bf`: Expiry tag for BANKNIFTY/FINNIFTY ("this_month,next_month").
- `show_op`: Toggle CE/PE and Greeks on/off (1 or 0) – controls `include_iv` and `include_greeks` flags.
- `show_index`: Toggle index overlays and index-only panels (1 or 0) – controls `include_index` and `index_pct` flags.
- `ns_visible`: Regex filter for NS series (default `NIFTY|SENSEX`).
- `bf_visible`: Regex filter for BF series (default `BANKNIFTY|FINNIFTY`).

## Panels
- IV panels (NIFTY+SENSEX and BANKNIFTY+FINNIFTY) show CE/PE IV and percent-based index overlays.
  - IV uses left axis with `percentunit`.
  - Index overlays are dashed gray on the right axis to avoid re-scaling IV.
- Index-only panels show index_price; the secondary index is on the right axis for readability.
- Greeks panels (NS and BF) include delta, theta, vega, gamma, rho for CE and PE.

## Backend contract
- Endpoint: `http://127.0.0.1:9500/api/live_csv`
- Required query params: `from_ms`, `to_ms` (epoch-ms), `limit` (optional), and flags: `include_iv`, `include_greeks`, `include_index`, `index_pct`.
- Fields served (subset): `ts`, `ce_iv`, `pe_iv`, `index_price`, `index_pct`, `ce_delta`, `pe_delta`, `ce_theta`, `pe_theta`, `ce_vega`, `pe_vega`, `ce_gamma`, `pe_gamma`, `ce_rho`, `pe_rho`.

## Import or auto-provision
- If provisioning is enabled (recommended), the dashboard will be auto-loaded from the repo path.
- Otherwise, Import via Grafana UI:
  1) Dashboards → New → Import
  2) Upload `grafana/dashboards/generated/g6_analytics_infinity_v4.json`
  3) Map the datasource placeholder `DS_INFINITY` to your Infinity datasource instance
  4) Keep UID as `g6-analytics-infinity-v4` (or change, then update any open scripts/links)

## Troubleshooting
- No data but backend is running:
  - Open FastAPI JSON: `http://127.0.0.1:9500/api/live_csv?index=NIFTY` and confirm it returns JSON with the fields above.
  - Check that Grafana variables `show_op/show_index` are set to 1 when testing.
- Time picker shows no effect:
  - Ensure queries include `from_ms=${__from}`, `to_ms=${__to}` and that the backend uses them to filter.
- Overlay scaling looks wrong:
  - Overlays are percent; ensure `index_pct` is returned and used. The panel left axis stays on IV `percentunit`.

## Open directly
- Browser: `http://127.0.0.1:3002/d/g6-analytics-infinity-v4`

