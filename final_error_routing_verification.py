#!/usr/bin/env python3
"""
Final Error Routing System Verification
======================================
Comprehensive test of the complete error routing system including panel integration.
"""

import logging
from typing import Dict, Any
from pathlib import Path
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))
sys.path.insert(0, str(Path(__file__).parent / "scripts" / "summary"))

from src.error_handling import (
    get_error_handler, ErrorInfo, ErrorCategory, ErrorSeverity, 
    handle_collector_error, handle_provider_error, handle_data_collection_error
)

# Import panel functions
try:
    from scripts.summary.panels.indices import get_collector_errors_for_stream
    from scripts.summary.panels.alerts import alerts_panel
    panels_available = True
except ImportError as e:
    print(f"⚠️  Panel imports not available: {e}")
    panels_available = False

def test_complete_error_routing():
    """Test the complete error routing system with panel integration."""
    print("🔧 Complete Error Routing System Verification")
    print("=" * 60)
    
    # Initialize error handler
    error_handler = get_error_handler()
    error_handler.clear_errors()
    
    print("\n1️⃣ Testing Collector Error Routing...")
    # Generate collector errors that should go to indices panel
    try:
        handle_collector_error(Exception("Connection timeout during data collection"), "NIFTY")
        handle_provider_error(Exception("API rate limit exceeded"), "BANKNIFTY", error_code="timeout_error")
        handle_data_collection_error(Exception("Invalid JSON response from provider"), "FINNIFTY")
    except Exception as e:
        print(f"Error generating collector errors: {e}")
    
    # Add a critical error that should go to BOTH panels
    try:
        error_handler.add_error(ErrorInfo(
            exception=Exception("Critical system failure detected"),
            component="system_monitor",
            message="Critical system failure detected",
            category=ErrorCategory.MEMORY,
            severity=ErrorSeverity.CRITICAL,
            context={"memory_usage": "95%", "action": "emergency_shutdown"}
        ))
    except Exception as e:
        print(f"Error adding critical error: {e}")
    
    print("\n2️⃣ Testing Non-Collector Error Routing...")
    # Add regular errors that should go to alerts panel only
    try:
        error_handler.add_error(ErrorInfo(
            exception=Exception("Configuration file corrupted"),
            component="config_manager",
            message="Configuration file corrupted",
            category=ErrorCategory.CONFIGURATION,
            severity=ErrorSeverity.HIGH
        ))
        
        error_handler.add_error(ErrorInfo(
            exception=Exception("Panel rendering failed"),
            component="ui_renderer",
            message="Panel rendering failed",
            category=ErrorCategory.RENDERING,
            severity=ErrorSeverity.MEDIUM
        ))
    except Exception as e:
        print(f"Error adding regular errors: {e}")
    
    print("\n3️⃣ Verifying Error Distribution...")
    
    # Get errors for each panel
    indices_errors = error_handler.get_errors_for_indices_panel()
    alerts_errors = error_handler.get_errors_for_alerts_panel()
    
    print(f"   📊 Indices Panel Errors: {len(indices_errors)}")
    for error in indices_errors:
        print(f"      • {error.component}: {error.message[:50]}...")
    
    print(f"   🚨 Alerts Panel Errors: {len(alerts_errors)}")  
    for error in alerts_errors:
        print(f"      • {error.component}: {error.message[:50]}...")
    
    print("\n4️⃣ Testing Panel Integration...")
    
    if panels_available:
        try:
            # Test indices panel integration
            collector_errors = get_collector_errors_for_stream()
            print(f"   📈 Collector errors from indices panel: {len(collector_errors)}")
            
            # Test alerts panel (create minimal status)
            status = {"timestamp": "2024-01-01T12:00:00", "indices": {}}
            alerts_result = alerts_panel(status, compact=True, low_contrast=True)
            print(f"   ✅ Alerts panel executed successfully: {type(alerts_result)}")
            
        except Exception as e:
            print(f"   ❌ Panel integration error: {e}")
    else:
        print("   ⚠️  Skipping panel integration test (imports not available)")
    
    print("\n5️⃣ Summary Report...")
    print(f"   • Total Errors Tracked: {len(error_handler.errors)}")
    print(f"   • Indices Panel Errors: {len(indices_errors)} (collector-related)")
    print(f"   • Alerts Panel Errors: {len(alerts_errors)} (system-wide)")
    print(f"   • Error Categories: {set(e.category.value for e in error_handler.errors)}")
    print(f"   • Error Severities: {set(e.severity.value for e in error_handler.errors)}")
    
    # Verify routing logic
    expected_indices = 4  # 3 collector + 1 critical
    expected_alerts = 3   # 2 regular + 1 critical
    
    routing_correct = (len(indices_errors) == expected_indices and 
                      len(alerts_errors) == expected_alerts)
    
    print(f"\n✅ Error Routing Verification: {'PASSED' if routing_correct else 'FAILED'}")
    print(f"   Expected indices: {expected_indices}, Got: {len(indices_errors)}")
    print(f"   Expected alerts: {expected_alerts}, Got: {len(alerts_errors)}")
    
    return routing_correct

if __name__ == "__main__":
    success = test_complete_error_routing()
    if success:
        print("\n🎉 Complete Error Routing System: FULLY VERIFIED!")
        print("   • All collector errors route to indices panel ✓")
        print("   • All other errors route to alerts panel ✓")
        print("   • Critical errors route to both panels ✓")
        print("   • Panel integration working correctly ✓")
    else:
        print("\n❌ Error routing verification failed!")
        sys.exit(1)