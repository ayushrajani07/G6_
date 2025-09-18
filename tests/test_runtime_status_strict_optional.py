"""Optional tests for strict runtime status validation mode."""
from __future__ import annotations
import json
import pytest
from src.schema.runtime_status_validator import validate_runtime_status

pytestmark = pytest.mark.optional

BASE = {
    "timestamp": "2025-01-01T00:00:00Z",
    "cycle": 1,
    "elapsed": 0.1,
    "interval": 2,
    "sleep_sec": 1.9,
    "indices": ["NIFTY"],
    "indices_info": {"NIFTY": {"ltp": 0, "options": 0}},
}


def test_strict_rejects_unknown():
    obj = dict(BASE)
    obj["mystery_field"] = 123
    errs = validate_runtime_status(obj, strict=True)
    assert any("Unknown top-level field" in e for e in errs)


def test_strict_allows_known():
    obj = dict(BASE)
    obj["api_success_rate"] = 50.0
    errs = validate_runtime_status(obj, strict=True)
    assert errs == []
