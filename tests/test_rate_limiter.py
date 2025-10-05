import asyncio
import time

import pytest

from src.providers.rate_limiter import TokenBucket, RateLimiterRegistry


def test_token_bucket_try_acquire_with_mock_time():
    # Mock time source we can control deterministically
    clock = {"now": 0.0}

    def mock_time():
        return clock["now"]

    # 2 tokens/sec, burst 4
    tb = TokenBucket(rate=2.0, burst=4, time_func=mock_time)

    # Immediately can take up to burst
    assert tb.try_acquire(1)
    assert tb.try_acquire(3)  # consumes all 4
    # No more tokens left
    assert not tb.try_acquire(1)

    # Advance 0.4s -> 0.8 tokens, still insufficient
    clock["now"] += 0.4
    assert not tb.try_acquire(1)

    # Advance 0.6s more -> total +1.2 tokens, should allow 1 token
    clock["now"] += 0.6
    assert tb.try_acquire(1)

    # Advance large time, should cap at burst
    clock["now"] += 10.0
    assert tb.try_acquire(4)
    assert not tb.try_acquire(1)


def test_token_bucket_async_acquire_with_mock_time():
    # Controlled time for deterministic async test executed via explicit loop
    clock = {"now": 0.0}

    def mock_time():
        return clock["now"]

    tb = TokenBucket(rate=5.0, burst=2, time_func=mock_time)

    assert tb.try_acquire(2)
    assert not tb.try_acquire(1)

    async def _run():
        async def advance_time_after(delay, amount):
            await asyncio.sleep(delay)
            clock["now"] += amount

        waiter = asyncio.create_task(tb.acquire(1))
        advancer = asyncio.create_task(advance_time_after(0.01, 0.25))
        await asyncio.gather(waiter, advancer)

    asyncio.run(_run())
    # After async acquire
    assert not tb.try_acquire(2)
    assert not tb.try_acquire(1)
    clock["now"] += 0.2
    assert tb.try_acquire(1)


def test_registry_reuses_instances():
    reg = RateLimiterRegistry()
    a1 = reg.get("kite", rate=10.0, burst=20)
    a2 = reg.get("kite", rate=10.0, burst=20)
    b = reg.get("kite", rate=5.0, burst=10)

    assert a1 is a2
    assert a1 is not b


# New Phase 1 limiter tests

def test_phase1_rate_limiter_cooldown_blocking():
    from src.broker.kite.rate_limit import RateLimiter
    rl = RateLimiter(qps=10, burst=2, consecutive_threshold=2, cooldown_seconds=1)
    # Trigger consecutive errors to open cooldown
    rl.record_rate_limit_error()
    assert not rl.cooldown_active()
    rl.record_rate_limit_error()
    assert rl.cooldown_active(), 'Cooldown should be active after threshold reached'
    # Use perf_counter for high-resolution monotonic timing (no event loop dependency)
    import time as _t
    t0 = _t.perf_counter()
    rl.acquire()  # should sleep close to cooldown_seconds (blocking path)
    t1 = _t.perf_counter()
    assert (t1 - t0) >= 0.8, f'Acquire did not block long enough; delta={(t1 - t0):.3f}'
    rl.record_success()
    assert not rl.cooldown_active(), 'Cooldown should be cleared after it expires'


def test_phase1_rate_limiter_token_refill_behavior():
    from src.broker.kite.rate_limit import RateLimiter
    rl = RateLimiter(qps=2, burst=2, consecutive_threshold=99, cooldown_seconds=1)
    # Use both burst tokens
    rl.acquire(); rl.acquire()
    t0 = time.time()
    # Next acquire should block roughly 0.5s (since refill rate 2/sec => 1 token every 0.5s)
    rl.acquire()
    delta = time.time() - t0
    assert delta >= 0.45, f'Expected ~0.5s wait, got {delta:.3f}'
