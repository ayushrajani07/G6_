#!/usr/bin/env python3
"""Print a matrix of expiry dates for key indices and rules.

For each index and rule (this_week, next_week, this_month, next_month),
print the resolved expiry date and days-to-expiry in brackets.

Usage (PowerShell):
  python scripts/expiry_matrix.py

Environment:
  - Set G6_USE_MOCK_PROVIDER=1 to use synthetic provider without network.
"""
from __future__ import annotations

import datetime as _dt
import os

from src.collectors.providers_interface import Providers
from src.config.loader import load_config  # canonical loader

# Provider initialization: prefer orchestrator components if available; fallback to legacy unified_main init_providers.
from src.orchestrator.components import init_providers  # type: ignore

INDICES = ["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX", "MIDCPNIFTY"]
RULES = ["this_week", "next_week", "this_month", "next_month"]


def _fmt_date_with_dte(d: _dt.date, today: _dt.date) -> str:
    dte = (d - today).days
    return f"{d.isoformat()} ({dte})"


def main() -> None:
    # Prefer existing config if present; fallback to default wrapper
    cfg_path = os.environ.get("G6_CONFIG_PATH", "config/g6_config.json")
    try:
        config = load_config(cfg_path)
    except Exception:
        # If config loader fails, create a default in-memory wrapper
        from src.config.config_wrapper import ConfigWrapper
        config = ConfigWrapper({})

    providers: Providers = init_providers(config)

    today = _dt.date.today()
    # Build header row
    header = ["INDEX"] + [r for r in RULES]
    rows = []
    for idx in INDICES:
        row = [idx]
        for rule in RULES:
            try:
                d = providers.resolve_expiry(idx, rule)
                cell = _fmt_date_with_dte(d, today)
            except Exception as e:
                cell = f"ERR: {e.__class__.__name__}"
            row.append(cell)
        rows.append(row)

    # Pretty print as a simple fixed-width table
    col_widths = [max(len(str(cell)) for cell in col) for col in zip(header, *rows, strict=False)]
    def print_row(r):
        print("  ".join(str(c).ljust(w) for c, w in zip(r, col_widths, strict=False)))

    print_row(header)
    print("  ".join("-" * w for w in col_widths))
    for r in rows:
        print_row(r)


if __name__ == "__main__":
    main()
