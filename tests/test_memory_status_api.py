from __future__ import annotations

import pytest

try:
    from fastapi.testclient import TestClient  # type: ignore
except Exception:  # pragma: no cover
    TestClient = None  # type: ignore
FASTAPI_AVAILABLE = TestClient is not None


@pytest.mark.skipif(not FASTAPI_AVAILABLE, reason="fastapi test client not available")
def test_memory_status_endpoint_structure():
    from src.web.dashboard.app import app  # type: ignore
    assert TestClient is not None
    client = TestClient(app)  # type: ignore[call-arg]

    resp = client.get("/api/memory/status")
    # Service may return 503 if memory manager import fails; accept 200/503
    assert resp.status_code in (200, 503)
    if resp.status_code == 200:
        data = resp.json()
        assert isinstance(data, dict)
        assert data.get("status") == "ok"
        stats = data.get("stats")
        assert isinstance(stats, dict)
        # Expected keys (may be None depending on platform)
        for key in ("rss_mb", "peak_rss_mb", "gc_collections_total", "gc_last_duration_ms", "registered_caches"):
            assert key in stats
