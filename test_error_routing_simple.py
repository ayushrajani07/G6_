#!/usr/bin/env python3
"""
Simple test script to demonstrate the error routing system.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from src.error_handling import (
    get_error_handler, 
    handle_collector_error,
    handle_provider_error,
    handle_data_collection_error,
    handle_api_error,
    handle_critical_error,
    handle_ui_error,
    initialize_error_handler
)

def test_error_routing_core():
    """Test the core error routing functionality."""
    print("🔧 Initializing error handling system...")
    handler = initialize_error_handler("logs/test_error_routing.log")
    
    print("\n📊 Testing Error Routing System")
    print("=" * 50)
    
    # Test collector errors (should go to indices panel)
    print("\n🔌 Generating Collector Errors (→ Indices Panel):")
    
    try:
        raise ConnectionError("Provider API timeout")
    except Exception as e:
        handle_provider_error(e, "provider_client", "NIFTY", {"endpoint": "/api/data"})
        print("  • Provider API timeout error")
    
    try:
        raise ValueError("Invalid data format in response")
    except Exception as e:
        handle_data_collection_error(e, "data_parser", "BANKNIFTY", "options", {"raw_data": "corrupted"})
        print("  • Data parsing error")
        
    try:
        raise RuntimeError("Collector thread crashed")
    except Exception as e:
        handle_collector_error(e, "unified_collector", "FINNIFTY", cycle=123)
        print("  • Collector crash error")
    
    # Test other errors (should go to alerts panel)
    print("\n🚨 Generating Other Errors (→ Alerts Panel):")
    
    try:
        raise MemoryError("Out of memory")
    except Exception as e:
        handle_critical_error(e, "memory_manager", {"memory_used": "500MB"})
        print("  • Critical memory error")
        
    try:
        raise FileNotFoundError("Config file missing")
    except Exception as e:
        handle_api_error(e, "config_loader", {"file": "config.json"})
        print("  • Configuration error")
        
    try:
        raise Exception("Panel rendering failed")
    except Exception as e:
        handle_ui_error(e, "rich_panel", {"panel_type": "analytics"})
        print("  • UI rendering error")
    
    # Show routing results
    print("\n📈 Error Routing Results:")
    print("-" * 30)
    
    indices_errors = handler.get_errors_for_indices_panel()
    alerts_errors = handler.get_errors_for_alerts_panel()
    
    print(f"Indices Panel Errors: {len(indices_errors)}")
    for error in indices_errors:
        print(f"  • {error['index']}: {error['description']}")
    
    print(f"\nAlerts Panel Errors: {len(alerts_errors)}")
    for error in alerts_errors:
        print(f"  • {error['component']}: {error['message']}")
    
    # Summary
    summary = handler.get_error_summary()
    print(f"\n📊 Summary:")
    print(f"  Total Errors: {summary['total_errors']}")
    print(f"  By Category: {summary['by_category']}")
    print(f"  By Severity: {summary['by_severity']}")
    
    print("\n✅ Error routing test completed!")

if __name__ == "__main__":
    test_error_routing_core()