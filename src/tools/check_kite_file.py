#!/usr/bin/env python3
"""
Check KiteProvider file contents
"""

import os
import sys


def main():
    """Check KiteProvider file."""
    kite_file = os.path.join("src", "broker", "kite_provider.py")

    print(f"Checking file: {kite_file}")

    if not os.path.exists(kite_file):
        print(f"ERROR: File does not exist: {kite_file}")
        return 1

    with open(kite_file) as f:
        contents = f.read()

    print(f"File size: {len(contents)} bytes")
    print("\nFirst 500 characters:")
    print("-" * 50)
    print(contents[:500])
    print("-" * 50)
    print("\nCheck if 'class KiteProvider' is present...")

    if "class KiteProvider" in contents:
        print("✅ Found 'class KiteProvider'")
    else:
        print("❌ Did NOT find 'class KiteProvider'")

    return 0

if __name__ == "__main__":
    sys.exit(main())
