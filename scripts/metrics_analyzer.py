#!/usr/bin/env python3
"""G6 Metrics Supply Chain Analyzer

This script analyzes the complete metrics flow from data collection to display,
specifically focusing on legs metrics (current cycle vs cumulative).

Usage:
    python scripts/metrics_analyzer.py [--runtime-status] [--panels] [--live-metrics]

The script maps out:
1. Collector metrics: _per_index_last_cycle_options (current cycle legs)
2. Runtime status: indices_detail[index]["legs"] (cumulative legs)
3. Panel data: indices_stream.json legs field
4. Live metrics server: prometheus metrics endpoint

This helps organize the complete supply chain for proper legs display:
- First number: Current cycle legs (from metrics._per_index_last_cycle_options)
- Number in brackets: Average legs per cycle (cumulative / total_cycles)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import requests

# Add project root to path before local imports
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data_access.unified_source import DataSourceConfig, UnifiedDataSource  # noqa: E402


def analyze_runtime_status(status_file: str = "data/runtime_status.json") -> dict[str, Any]:
    """Analyze runtime status data structure for legs metrics using UnifiedDataSource."""
    print("🔍 ANALYZING RUNTIME STATUS STRUCTURE")
    print("=" * 60)

    try:
        # Use a single UnifiedDataSource and configure all key paths to keep instance coherent
        uds = UnifiedDataSource()
        uds.reconfigure(DataSourceConfig(
            runtime_status_path=status_file,
            panels_dir=os.environ.get('G6_PANELS_DIR', 'data/panels'),
            metrics_url=os.environ.get('G6_METRICS_URL', 'http://127.0.0.1:9108/metrics')
        ))
        status = uds.get_runtime_status()

        # Extract cycle info
        cycle_info = status.get("loop", {})
        cycle_count = cycle_info.get("cycle", 0)

        print(f"Current Cycle: {cycle_count}")
        print(f"Last Duration: {cycle_info.get('last_duration', 'N/A')} seconds")
        print(f"Success Rate: {cycle_info.get('success_rate', 'N/A')}%")
        print()

        # Analyze indices detail (cumulative legs)
        print("📊 INDICES DETAIL (Cumulative Legs):")
        indices_detail = status.get("indices_detail", {})
        cumulative_data = {}

        for index, details in indices_detail.items():
            legs = details.get("legs", 0)
            avg_per_cycle = legs / cycle_count if cycle_count > 0 else 0
            cumulative_data[index] = {
                "cumulative_legs": legs,
                "avg_per_cycle": round(avg_per_cycle, 1)
            }
            print(f"  {index}: {legs:,} legs total ({avg_per_cycle:.1f} avg/cycle)")

        # Check if metrics data is available in status
        print("\n🎯 CURRENT CYCLE METRICS:")
        metrics = status.get("metrics", {})
        if metrics:
            print("  Found metrics section in runtime status:")
            for index in ["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"]:
                if index in metrics:
                    legs_current = metrics[index].get("legs")
                    print(f"    {index}: {legs_current} legs (current cycle)")
                else:
                    print(f"    {index}: No current cycle data found")
        else:
            print("  ❌ No metrics section found in runtime status")
            print("  ⚠️  Current cycle legs not available in runtime_status.json")

        return {
            "cycle_count": cycle_count,
            "cumulative_data": cumulative_data,
            "has_current_cycle_metrics": bool(metrics)
        }

    except FileNotFoundError:
        print(f"❌ Runtime status file not found: {status_file}")
        return {}
    except json.JSONDecodeError as e:
        print(f"❌ JSON decode error: {e}")
        return {}
    except Exception as e:
        print(f"❌ Error analyzing runtime status: {e}")
        return {}

def analyze_panel_data(panels_dir: str = "data/panels") -> dict[str, Any]:
    """Analyze panel JSON files for legs metrics using UnifiedDataSource."""
    print("\n🔍 ANALYZING PANEL DATA STRUCTURE")
    print("=" * 60)

    # Initialize data source with provided panels_dir
    uds = UnifiedDataSource()
    uds.reconfigure(DataSourceConfig(panels_dir=panels_dir))

    # Fetch raw indices_stream panel
    stream_data = uds.get_panel_raw('indices_stream')
    if not stream_data:
        # Surface a helpful message based on directory existence
        if not Path(panels_dir).exists():
            print(f"❌ Panels directory not found: {panels_dir}")
        else:
            print("❌ indices_stream.json not found or empty")
        return {}

    try:
        print("📈 INDICES STREAM DATA:")
        print(f"  Updated: {stream_data.get('updated_at', 'N/A')}")
        print(f"  Kind: {stream_data.get('kind', 'N/A')}")

        data_items = stream_data.get("data", [])
        if isinstance(data_items, list) and len(data_items) > 0:
            print(f"  Stream items: {len(data_items)}")
            print("\n  📊 CURRENT STREAM LEGS DATA:")

            stream_legs = {}
            for item in data_items[:4]:  # Show first 4 items
                index = item.get("index", "UNKNOWN")
                legs = item.get("legs")
                cycle = item.get("cycle")
                status = item.get("status", "N/A")

                stream_legs[index] = legs
                print(f"    {index}: {legs} legs (cycle {cycle}, status: {status})")

            return {"stream_legs": stream_legs, "stream_items": len(data_items)}
        else:
            print("  ❌ No data items in stream")
            return {}
    except Exception as e:
        print(f"❌ Error reading indices_stream panel via UnifiedDataSource: {e}")
        return {}

def analyze_live_metrics(metrics_url: str = "http://127.0.0.1:9108/metrics") -> dict[str, Any]:
    """Analyze live metrics for legs data using UnifiedDataSource when possible.

    Attempts JSON endpoint via UnifiedDataSource; falls back to Prometheus text scrape.
    """
    print("\n🔍 ANALYZING LIVE METRICS SERVER")
    print("=" * 60)
    # First try JSON via UnifiedDataSource
    uds = UnifiedDataSource()
    uds.reconfigure(DataSourceConfig(metrics_url=metrics_url))
    try:
        m = uds.get_metrics_data() or {}
        current_cycle_data: dict[str, int] = {}
        if m:
            # Accept several shapes: {indices: {INDEX: {legs: N}}} or flat list
            inds = m.get('indices') if isinstance(m, dict) else None
            if isinstance(inds, dict):
                for k, v in inds.items():
                    if isinstance(v, dict) and 'legs' in v:
                        try:
                            current_cycle_data[str(k)] = int(v.get('legs') or 0)
                        except Exception:
                            pass
            elif isinstance(inds, list):
                for item in inds:
                    if isinstance(item, dict):
                        name = str(item.get('index') or item.get('idx') or '')
                        if name:
                            try:
                                current_cycle_data[name] = int(item.get('legs') or 0)
                            except Exception:
                                pass
        if current_cycle_data:
            print("✅ Retrieved metrics via JSON endpoint")
            for index, legs in current_cycle_data.items():
                print(f"  {index}: {legs} legs (current cycle from metrics JSON)")
            return {"metrics_available": True, "current_cycle_data": current_cycle_data, "relevant_metrics_count": None}
    except Exception:
        pass

    # Fallback to Prometheus text scraping
    try:
        response = requests.get(metrics_url, timeout=5)
        if response.status_code != 200:
            print(f"❌ Metrics server returned {response.status_code}")
            return {"metrics_available": False}

        metrics_text = response.text
        print(f"✅ Connected to metrics server: {metrics_url}")

        relevant_metrics = []
        current_cycle_data = {}
        for line in metrics_text.split('\n'):
            if line.startswith('#') or not line.strip():
                continue
            if any(keyword in line.lower() for keyword in ['index', 'options', 'legs', 'cycle']):
                relevant_metrics.append(line.strip())
                if 'g6_index_options_processed{' in line:
                    try:
                        parts = line.split()
                        if len(parts) >= 2:
                            metric_part = parts[0]
                            value = parts[1]
                            if 'index="' in metric_part:
                                start = metric_part.find('index="') + 7
                                end = metric_part.find('"', start)
                                index_name = metric_part[start:end]
                                current_cycle_data[index_name] = int(float(value))
                    except Exception:
                        pass

        print("📊 CURRENT CYCLE OPTIONS (from Prometheus):")
        if current_cycle_data:
            for index, legs in current_cycle_data.items():
                print(f"  {index}: {legs} legs (current cycle from metrics)")
        else:
            print("  ❌ No current cycle options data found in metrics")

        print(f"\n🎯 RELEVANT METRICS FOUND: {len(relevant_metrics)}")
        if relevant_metrics:
            print("  Sample metrics:")
            for metric in relevant_metrics[:5]:
                print(f"    {metric}")

        return {
            "metrics_available": True,
            "current_cycle_data": current_cycle_data,
            "relevant_metrics_count": len(relevant_metrics)
        }
    except requests.exceptions.RequestException as e:
        print(f"❌ Cannot connect to metrics server: {e}")
        return {"metrics_available": False}
    except Exception as e:
        print(f"❌ Error analyzing metrics: {e}")
        return {"metrics_available": False}

def check_data_flow_consistency(
    runtime_data: dict[str, Any],
    panel_data: dict[str, Any],
    metrics_data: dict[str, Any],
) -> None:
    """Check consistency between different data sources."""
    print("\n🔍 DATA FLOW CONSISTENCY CHECK")
    print("=" * 60)

    # Get runtime cumulative data
    cumulative_data = runtime_data.get("cumulative_data", {})
    # cycle_count kept for future analysis if needed
    # cycle_count = runtime_data.get("cycle_count", 0)

    # Get stream data
    stream_legs = panel_data.get("stream_legs", {})

    # Get current cycle data from metrics
    current_cycle_data = metrics_data.get("current_cycle_data", {})

    print("📊 COMPARISON TABLE:")
    print(f"{'Index':<12} {'Cumulative':<12} {'Stream':<12} {'Current Cycle':<15} {'Avg/Cycle':<10}")
    print("-" * 70)

    indices = set(cumulative_data.keys()) | set(stream_legs.keys()) | set(current_cycle_data.keys())

    for index in sorted(indices):
        cumulative = cumulative_data.get(index, {}).get("cumulative_legs", "N/A")
        stream = stream_legs.get(index, "N/A")
        current_cycle = current_cycle_data.get(index, "N/A")
        avg_cycle = cumulative_data.get(index, {}).get("avg_per_cycle", "N/A")

        print(f"{index:<12} {str(cumulative):<12} {str(stream):<12} {str(current_cycle):<15} {str(avg_cycle):<10}")

    # Analysis
    print("\n🎯 ANALYSIS:")

    # Check if stream matches cumulative
    cumulative_stream_match = True
    for index in cumulative_data.keys():
        if index in stream_legs:
            if cumulative_data[index]["cumulative_legs"] != stream_legs[index]:
                cumulative_stream_match = False
                break

    if cumulative_stream_match:
        print("✅ Stream legs data matches cumulative legs (as expected)")
    else:
        print("⚠️  Stream legs data doesn't match cumulative legs")

    # Check availability of current cycle data
    if current_cycle_data:
        print("✅ Current cycle legs data available from metrics server")
        print("💡 RECOMMENDATION: Use metrics server data for current cycle legs")
    else:
        print("❌ Current cycle legs data NOT available")
        print("💡 RECOMMENDATION: Need to access metrics._per_index_last_cycle_options directly")

def generate_implementation_recommendation() -> None:
    """Generate recommendations for implementing proper legs display."""
    print("\n🎯 IMPLEMENTATION RECOMMENDATIONS")
    print("=" * 60)

    print("📋 TO DISPLAY LEGS AS: current_cycle_legs (average_per_cycle)")
    print()
    print("1️⃣  CURRENT CYCLE LEGS (First Number):")
    print("   Source: metrics._per_index_last_cycle_options[index]")
    print("   Location: Available in unified_collectors.py")
    print("   Access: Direct from metrics object or via metrics server")
    print()
    print("2️⃣  AVERAGE PER CYCLE (Number in Brackets):")
    print("   Formula: cumulative_legs ÷ total_cycles")
    print("   Source: indices_detail[index]['legs'] ÷ loop['cycle']")
    print("   Location: Available in runtime_status.json")
    print()
    print("🔧 IMPLEMENTATION OPTIONS:")
    print()
    print("Option A: Access metrics object directly")
    print("   - Modify indices panel to access metrics._per_index_last_cycle_options")
    print("   - Requires passing metrics object to panel function")
    print()
    print("Option B: Enhance unified PanelsWriter")
    print("   - Extend PanelsWriter to include current cycle legs in indices stream")
    print("   - Access metrics data inside unified loop and enrich panel rows")
    print()
    print("Option C: Enhance runtime status publisher")
    print("   - Add current cycle legs to runtime_status.json structure")
    print("   - Modify status writing to include metrics data")
    print()
    print("✅ RECOMMENDED: Option B - Enhance unified PanelsWriter (panel_updater removed)")
    print("   Reasons:")
    print("   - Keeps display logic separate from collection logic")
    print("   - Maintains existing panel JSON structure")
    print("   - Provides live updates every 5 seconds")
    print("   - No changes to core collection system needed")

def main() -> int:
    """Main analyzer function."""
    parser = argparse.ArgumentParser(description="Analyze G6 metrics supply chain for legs display")
    parser.add_argument("--runtime-status", action="store_true", help="Analyze runtime status structure")
    parser.add_argument("--panels", action="store_true", help="Analyze panel data structure")
    parser.add_argument("--live-metrics", action="store_true", help="Analyze live metrics server")
    parser.add_argument("--all", action="store_true", help="Run all analyses")

    args = parser.parse_args()

    if not any([args.runtime_status, args.panels, args.live_metrics, args.all]):
        args.all = True  # Default to all if no specific option

    print("🚀 G6 METRICS SUPPLY CHAIN ANALYZER")
    print("=" * 60)
    print("Analyzing legs metrics flow: collection → processing → storage → display")
    print()

    runtime_data = {}
    panel_data = {}
    metrics_data = {}

    if args.all or args.runtime_status:
        runtime_data = analyze_runtime_status()

    if args.all or args.panels:
        panel_data = analyze_panel_data()

    if args.all or args.live_metrics:
        metrics_data = analyze_live_metrics()

    if args.all:
        check_data_flow_consistency(runtime_data, panel_data, metrics_data)
        generate_implementation_recommendation()

    print("\n✅ ANALYSIS COMPLETE")
    return 0

if __name__ == '__main__':
    sys.exit(main())
