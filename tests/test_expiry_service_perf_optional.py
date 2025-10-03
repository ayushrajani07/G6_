import os
import time
import datetime as dt
import pytest

from src.utils.expiry_rules import select_expiry as legacy_select
from src.utils.expiry_service import ExpiryService


pytestmark = pytest.mark.skipif(
    os.getenv("G6_ENABLE_PERF_TESTS", "0") not in {"1","true"},
    reason="Set G6_ENABLE_PERF_TESTS=1 to run performance micro-benchmarks"
)


def test_expiry_service_perf_parity():
    today = dt.date(2025, 1, 15)
    svc = ExpiryService(today=today)
    candidates = [today + dt.timedelta(days=i) for i in range(1, 90)]
    rules = ["this_week", "next_week", "this_month", "next_month"]

    # Warmup
    for r in rules:
        svc.select(r, candidates)
        legacy_select(candidates, r, today=today)

    iterations = 2000
    t0 = time.perf_counter()
    for _ in range(iterations):
        for r in rules:
            svc.select(r, candidates)
    t_service = time.perf_counter() - t0

    t0 = time.perf_counter()
    for _ in range(iterations):
        for r in rules:
            legacy_select(candidates, r, today=today)
    t_legacy = time.perf_counter() - t0

    # Allow service to be up to 1.5x legacy (tiny absolute times expected)
    assert t_service <= t_legacy * 1.5, f"ExpiryService slower than expected: service={t_service:.6f}s legacy={t_legacy:.6f}s"
