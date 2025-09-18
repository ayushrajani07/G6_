import json
import pytest
from src.schema.runtime_status_validator import validate_runtime_status

pytestmark = pytest.mark.optional

def test_runtime_status_schema_valid(run_mock_cycle):
    status = run_mock_cycle(cycles=2, interval=2)
    # Basic assurance we received a dict-like structure
    assert isinstance(status, dict)
    errors = validate_runtime_status(status)
    if errors:
        pytest.fail("Schema validation errors: " + ", ".join(errors))


def test_runtime_status_schema_negative_guard():
    # Construct a minimal invalid object to ensure validator catches issues
    bad = {"timestamp": "2024-01-01T00:00:00", "cycle": -1, "elapsed": -0.1, "interval": -5, "sleep_sec": -1, "indices": [1,2], "indices_info": {"NIFTY": {"ltp": "bad", "options": "also bad"}}}
    errors = validate_runtime_status(bad)
    # Expect multiple distinct errors (not asserting exact list for forward compatibility)
    assert any("timestamp" in e for e in errors)
    assert any("cycle" in e for e in errors)
    assert any("indices entries" in e for e in errors)
    assert any("ltp" in e for e in errors)
    assert any("options" in e for e in errors)
