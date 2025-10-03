from __future__ import annotations

import pytest

try:
    from fastapi.testclient import TestClient  # type: ignore
except Exception:  # pragma: no cover
    TestClient = None  # type: ignore
FASTAPI_AVAILABLE = TestClient is not None


@pytest.mark.skipif(not FASTAPI_AVAILABLE, reason="fastapi test client not available")
def test_unified_source_status_endpoint_imports():
    # Import the app and ensure endpoint exists and returns a dict
    from src.web.dashboard.app import app  # type: ignore
    assert TestClient is not None  # for type checkers
    client = TestClient(app)  # type: ignore[call-arg]
    resp = client.get("/api/unified/source-status")
    # Service may return 503 if no unified source; allow 200/503 as acceptable
    assert resp.status_code in (200, 503)
    if resp.status_code == 200:
        data = resp.json()
        assert isinstance(data, dict)
        # Expected keys when present
        for k in ("runtime_status", "panels", "metrics"):
            assert k in data
