# src/broker/kite_instruments.py
from __future__ import annotations

import json
import os
from pathlib import Path


def load_instruments() -> list[dict]:
    """
    Loads the instrument master from a JSON file.
    Expects path in env KITE_INSTRUMENTS_JSON or defaults to data/instruments.json
    """
    path = os.getenv("KITE_INSTRUMENTS_JSON", "data/instruments.json")
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"Instrument file not found: {p}")
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)
