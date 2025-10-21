#!/usr/bin/env python3
"""
Create default configuration file for G6 Platform
"""

import json
import sys
from pathlib import Path


def main():
    """Create configuration file."""
    config = {
        "storage": {
            "csv_dir": "data/g6_data",
            "influx_enabled": False
        },
        "orchestration": {
            "run_interval_sec": 60,
            "prometheus_port": 9108
        },
        "index_params": {
            "NIFTY": {
                "strike_step": 50,
                "expiry_rules": ["this_week", "next_week"],
                "offsets": [-5, -4, -3, -2, -1, 0, 1, 2, 3, 4, 5]
            },
            "BANKNIFTY": {
                "strike_step": 100,
                "expiry_rules": ["this_week", "next_week"],
                "offsets": [-3, -2, -1, 0, 1, 2, 3]
            },
            "FINNIFTY": {
                "strike_step": 50,
                "expiry_rules": ["this_week"],
                "offsets": [-3, -2, -1, 0, 1, 2, 3]
            },
            "SENSEX": {
                "strike_step": 100,
                "expiry_rules": ["this_week"],
                "offsets": [-2, -1, 0, 1, 2]
            }
        }
    }

    # Create config directory
    config_dir = Path("config")
    config_dir.mkdir(exist_ok=True)

    # Write config file
    config_file = config_dir / "g6_config.json"
    with open(config_file, 'w') as f:
        json.dump(config, f, indent=2)

    print(f"Configuration file created at: {config_file.absolute()}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
