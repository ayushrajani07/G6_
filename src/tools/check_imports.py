#!/usr/bin/env python3
"""
Check imports for G6 Platform
Verifies that all modules can be imported correctly.
"""
# Add this before launching the subprocess
import importlib
import os  # noqa: F401  (kept for potential future dynamic discovery, but no path mutation)
import sys


def test_import(module_name):
    """Test importing a module."""
    try:
        module = importlib.import_module(module_name)
        print(f"✓ {module_name} imported successfully")
        return True
    except Exception as e:
        print(f"✗ {module_name} import failed: {e}")
        return False

def main():
    """Test imports for key modules."""
    print("=== Testing G6 Platform Module Imports ===")

    modules = [
        # Core / bootstrap
        "src.config.config_loader",
        "src.metrics.metrics",

        # Broker
        "src.broker.kite_provider",

        # Collectors & interfaces
        "src.collectors.providers_interface",
        "src.collectors.unified_collectors",

        # Storage backends
        "src.storage.csv_sink",
        "src.storage.influx_sink",

        # (Legacy) main script retained for compatibility
        "src.main",
    ]

    success = 0
    failed = 0

    for module in modules:
        if test_import(module):
            success += 1
        else:
            failed += 1

    print(f"\nResults: {success} modules imported successfully, {failed} failed")

    return 1 if failed > 0 else 0

if __name__ == "__main__":
    sys.exit(main())
