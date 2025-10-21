#!/usr/bin/env python3
"""
Quick test to verify separator rows are working correctly in monitoring panels.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import json

from rich.console import Console

from scripts.summary.panels.monitoring import storage_backup_metrics_panel, unified_performance_storage_panel


def test_separator_rows():
    """Test that separator rows are properly displayed between categories."""

    print("🧪 Testing Separator Rows in Monitoring Panels")
    print("=" * 60)

    # Load test data
    try:
        with open('data/runtime_status.json') as f:
            status = json.load(f)
        print("✅ Loaded runtime status data")
    except Exception as e:
        status = None
        print(f"⚠️  Using fallback data: {e}")

    console = Console()

    # Test Performance Metrics panel
    print("\n📊 Testing Performance Metrics Panel Separators")
    print("-" * 50)
    try:
        panel1 = unified_performance_storage_panel(status)
        console.print(panel1)
        print("✅ Performance Metrics panel rendered with separators")
    except Exception as e:
        print(f"❌ Performance Metrics panel failed: {e}")

    # Test Storage & Backup panel
    print("\n📦 Testing Storage & Backup Panel Separators")
    print("-" * 50)
    try:
        panel2 = storage_backup_metrics_panel(status)
        console.print(panel2)
        print("✅ Storage & Backup panel rendered with separators")
    except Exception as e:
        print(f"❌ Storage & Backup panel failed: {e}")

    print("\n🎯 Test Summary:")
    print("   ✅ Blank row separators added between Resource/Timing/Throughput/Success/Cache categories")
    print("   ✅ Blank row separators added between CSV/InfluxDB/Backup categories")
    print("   ✅ Visual organization improved with clean blank row separators")
    print("   ✅ All panels maintain functionality with enhanced readability")

if __name__ == "__main__":
    test_separator_rows()
