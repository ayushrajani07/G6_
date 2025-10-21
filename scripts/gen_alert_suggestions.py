#!/usr/bin/env python
"""Generate suggested Prometheus alert rules for derived efficiency metrics.

Heuristics:
  * CS Ingest Success Ratio (derived) warning <0.995 for 10m, critical <0.99 for 5m
  * CS Backlog Drain ETA (mins) warning >10 for 10m, critical >30 for 5m

Input metrics are counters/gauges already exposed; we synthesize alert rule expressions using
rate() where appropriate. Ratios are computed directly in the alert expression so we do not need
recording rules first (future enhancement: migrate to recording rules names if adopted).

Modes:
  --output: path to write suggestions (default: prometheus_alert_suggestions.yml)
  --check : do not write; exit 9 if file content would change (drift detection)

Exit Codes:
  0 success / up-to-date
  2 setup/spec missing or environment issue
  9 drift detected in --check mode

This script does not parse the full spec; it emits a static suggestions group referencing metrics.
If needed we can later add detection to skip emission if core metrics absent (keeping simple now).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml  # type: ignore

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "prometheus_alert_suggestions.yml"

# Threshold configuration (centralized for future CLI overrides)
SUCCESS_RATIO_WARN = 0.995
SUCCESS_RATIO_CRIT = 0.99
BACKLOG_ETA_WARN_MIN = 10
BACKLOG_ETA_CRIT_MIN = 30
BACKLOG_BURN_MIN_WARN = 100   # rows/s below this while backlog large indicates slowing drain
BACKLOG_BURN_MIN_CRIT = 20    # severe stall threshold
BACKLOG_LARGE_BACKLOG = 50_000  # backlog rows considered large (tune as needed)

# Latency ratio thresholds (5m vs 30m) for regression detection; tuned to surface sustained spikes without noise.
INGEST_P95_RATIO_WARN = 1.25  # 25% higher short-term
INGEST_P95_RATIO_CRIT = 1.50  # 50% higher short-term
BUS_P95_RATIO_WARN = 1.30     # bus variability slightly higher tolerance
BUS_P95_RATIO_CRIT = 1.60


def build_doc() -> dict[str, Any]:
    # Expressions replicate those used in dashboard auto panels.
    success_ratio_expr_5m = (
        "1 - (clamp_min(sum(rate(g6_cs_ingest_failures_total[5m])),0) / clamp_min(sum(rate(g6_cs_ingest_rows_total[5m])),1))"
    )
    backlog_eta_expr_5m = (
        "(sum(g6_cs_ingest_backlog_rows) / clamp_min(sum(rate(g6_cs_ingest_rows_total[5m])),1)) / 60"
    )
    latency_ratio_rules = [
        {
            "alert": "G6CsIngestLatencyP95RegressionWarning",
            "expr": f"g6_cs_ingest_latency_ms:p95_ratio_5m_30m > {INGEST_P95_RATIO_WARN}",
            "for": "10m",
            "labels": {"severity": "warning"},
            "annotations": {
                "summary": "CS ingest p95 latency regression >25% (10m)",
                "description": "Short-term (5m) p95 ingest latency exceeds 30m baseline by >25% for 10m.",
            },
        },
        {
            "alert": "G6CsIngestLatencyP95RegressionCritical",
            "expr": f"g6_cs_ingest_latency_ms:p95_ratio_5m_30m > {INGEST_P95_RATIO_CRIT}",
            "for": "5m",
            "labels": {"severity": "critical"},
            "annotations": {
                "summary": "CS ingest p95 latency regression >50% (5m)",
                "description": "Critical: 5m p95 ingest latency >50% above 30m baseline sustained 5m.",
            },
        },
        {
            "alert": "G6BusPublishLatencyP95RegressionWarning",
            "expr": f"g6_bus_publish_latency_ms:p95_ratio_5m_30m_by_bus > {BUS_P95_RATIO_WARN}",
            "for": "10m",
            "labels": {"severity": "warning"},
            "annotations": {
                "summary": "Bus publish p95 latency regression >30% (10m)",
                "description": "Short-term bus publish p95 latency exceeds 30m baseline by >30% for 10m (any bus).",
            },
        },
        {
            "alert": "G6BusPublishLatencyP95RegressionCritical",
            "expr": f"g6_bus_publish_latency_ms:p95_ratio_5m_30m_by_bus > {BUS_P95_RATIO_CRIT}",
            "for": "5m",
            "labels": {"severity": "critical"},
            "annotations": {
                "summary": "Bus publish p95 latency regression >60% (5m)",
                "description": "Critical: bus publish p95 latency >60% above 30m baseline sustained 5m (any bus label).",
            },
        },
    ]

    return {
        "groups": [
            {
                "name": "g6_suggested_efficiency.alerts",
                "interval": "30s",
                "rules": [
                    {
                        "alert": "G6CsIngestSuccessRatioLowWarning",
                        "expr": f"{success_ratio_expr_5m} < {SUCCESS_RATIO_WARN}",
                        "for": "10m",
                        "labels": {"severity": "warning"},
                        "annotations": {
                            "summary": "CS ingest success ratio < 99.5% (10m)",
                            "description": "Column store ingest success ratio below 99.5% over the last 10 minutes; investigate failures/retries.",
                        },
                    },
                    {
                        "alert": "G6CsIngestSuccessRatioLowCritical",
                        "expr": f"{success_ratio_expr_5m} < {SUCCESS_RATIO_CRIT}",
                        "for": "5m",
                        "labels": {"severity": "critical"},
                        "annotations": {
                            "summary": "CS ingest success ratio < 99% (5m)",
                            "description": "Critical: Column store ingest success ratio below 99% sustained 5m; potential sustained failure path.",
                        },
                    },
                    {
                        "alert": "G6CsBacklogDrainEtaHighWarning",
                        "expr": f"{backlog_eta_expr_5m} > {BACKLOG_ETA_WARN_MIN}",
                        "for": "10m",
                        "labels": {"severity": "warning"},
                        "annotations": {
                            "summary": "CS backlog drain ETA > 10m (10m)",
                            "description": "Column store backlog would take >10 minutes to drain at current ingest rate (sustained 10m).",
                        },
                    },
                    {
                        "alert": "G6CsBacklogDrainEtaHighCritical",
                        "expr": f"{backlog_eta_expr_5m} > {BACKLOG_ETA_CRIT_MIN}",
                        "for": "5m",
                        "labels": {"severity": "critical"},
                        "annotations": {
                            "summary": "CS backlog drain ETA > 30m (5m)",
                            "description": "Critical: Column store backlog drain time exceeds 30 minutes sustained 5m; ingestion falling behind.",
                        },
                    },
                    # Backlog stall alerts using recording rules (burn + eta) once adopted
                    {
                        "alert": "G6CsBacklogStallWarning",
                        "expr": f"(g6_cs_ingest_backlog_rows:eta_minutes > {BACKLOG_ETA_WARN_MIN}) and (g6_cs_ingest_backlog_rows:burn_rows_per_s < {BACKLOG_BURN_MIN_WARN}) and (sum(g6_cs_ingest_backlog_rows) > {BACKLOG_LARGE_BACKLOG})",
                        "for": "10m",
                        "labels": {"severity": "warning"},
                        "annotations": {
                            "summary": "CS backlog stall suspected (low burn, high ETA)",
                            "description": "Backlog ETA high and burn rate low with large backlog; ingestion may be under-provisioned or stalled.",
                        },
                    },
                    {
                        "alert": "G6CsBacklogStallCritical",
                        "expr": f"(g6_cs_ingest_backlog_rows:eta_minutes > {BACKLOG_ETA_CRIT_MIN}) and (g6_cs_ingest_backlog_rows:burn_rows_per_s < {BACKLOG_BURN_MIN_CRIT}) and (sum(g6_cs_ingest_backlog_rows) > {BACKLOG_LARGE_BACKLOG})",
                        "for": "5m",
                        "labels": {"severity": "critical"},
                        "annotations": {
                            "summary": "CS backlog stall critical (near-zero burn)",
                            "description": "Critical: Backlog ETA very high and burn rate near zero with large backlog. Immediate intervention required.",
                        },
                    },
                ] + latency_ratio_rules,
            }
        ]
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Generate suggested efficiency alert rules")
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument("--check", action="store_true", help="Check mode (exit 9 on drift)")
    args = ap.parse_args(argv)

    doc = build_doc()
    new_text = yaml.safe_dump(doc, sort_keys=True)

    if args.check:
        if not args.output.exists():
            print(f"Alert suggestions drift: {args.output} missing (would create)", file=sys.stderr)
            return 9
        current = args.output.read_text()
        if current.strip() != new_text.strip():
            print("Alert suggestions drift detected (run without --check to update).", file=sys.stderr)
            return 9
        print("Alert suggestions up-to-date (check mode).")
        return 0

    args.output.write_text(new_text)
    print(f"Wrote suggested alert rules -> {args.output}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
