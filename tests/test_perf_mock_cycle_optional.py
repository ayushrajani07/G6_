import time
import pytest

pytestmark = [pytest.mark.optional, pytest.mark.perf]


def test_mock_cycle_perf_baseline(run_mock_cycle):
    start = time.time()
    data = run_mock_cycle(cycles=2, interval=2)
    elapsed = time.time() - start
    # Tightened ceiling after readiness probe skip + internal cycle limiter.
    # Expect under 8s for two short cycles (interval=2) including startup.
    assert elapsed < 8, f"Perf regression: 2 mock cycles took {elapsed:.2f}s"
    # Basic sanity that cycle progressed
    assert data.get('cycle', -1) >= 1
