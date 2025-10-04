from __future__ import annotations
import http.client, time

# Tests for security hardening round 2 (per-IP rate limiting, UA allow list, request id echo).
# These use the legacy separate SSE server path because it is simpler to exercise multiple
# connection attempts rapidly. Unified server reuses the same helpers.

def test_sse_rate_limit_and_ua_filter(monkeypatch):
    monkeypatch.setenv('G6_SSE_HTTP','1')
    # Allow only user-agents containing 'GoodClient'
    monkeypatch.setenv('G6_SSE_UA_ALLOW','GoodClient')
    # Per-IP connect rate: 2 connections per 60s window
    monkeypatch.setenv('G6_SSE_IP_CONNECT_RATE','2/60')

    from scripts.summary.plugins.sse import SSEPublisher
    from scripts.summary.unified_loop import UnifiedLoop

    pub = SSEPublisher(diff=True)
    loop = UnifiedLoop([pub], panels_dir='data/panels', refresh=0.1)

    import threading
    t = threading.Thread(target=lambda: loop.run(cycles=35), daemon=True)
    t.start()
    time.sleep(0.4)

    # First two connections succeed
    headers = {'User-Agent':'GoodClientTest/1.0', 'X-Request-ID':'abc123'}
    c1 = http.client.HTTPConnection('127.0.0.1', 9320, timeout=3)
    c1.request('GET','/summary/events', headers=headers)
    r1 = c1.getresponse(); assert r1.status == 200
    # Verify X-Request-ID echoed back
    assert r1.getheader('X-Request-ID') == 'abc123'

    c2 = http.client.HTTPConnection('127.0.0.1', 9320, timeout=3)
    c2.request('GET','/summary/events', headers=headers)
    r2 = c2.getresponse(); assert r2.status == 200

    # Third immediate connection should be rate limited (429)
    c3 = http.client.HTTPConnection('127.0.0.1', 9320, timeout=3)
    c3.request('GET','/summary/events', headers=headers)
    r3 = c3.getresponse(); assert r3.status == 429

    c1.close(); c2.close(); c3.close()

    # UA forbidden case
    bad = http.client.HTTPConnection('127.0.0.1', 9320, timeout=3)
    bad.request('GET','/summary/events', headers={'User-Agent':'OtherBot/2.0'})
    rb = bad.getresponse(); assert rb.status == 403
    bad.close()
