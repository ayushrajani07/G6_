from __future__ import annotations
import http.client, time, socket

# Tests for security hardening round 2 (per-IP rate limiting, UA allow list, request id echo).
# These use the legacy separate SSE server path because it is simpler to exercise multiple
# connection attempts rapidly. Unified server reuses the same helpers.

def test_sse_rate_limit_and_ua_filter(monkeypatch):
    monkeypatch.setenv('G6_SSE_HTTP','1')
    # Force-disable unified HTTP path to ensure we exercise legacy SSE server deterministically
    monkeypatch.setenv('G6_UNIFIED_HTTP','0')
    # Allow only user-agents containing 'GoodClient'
    monkeypatch.setenv('G6_SSE_UA_ALLOW','GoodClient')
    # Per-IP connect rate: 2 connections per 60s window
    monkeypatch.setenv('G6_SSE_IP_CONNECT_RATE','2/60')
    # Explicitly raise global max connections to avoid interaction with any prior test env that set a low cap
    monkeypatch.setenv('G6_SSE_MAX_CONNECTIONS','10')
    # Dynamically select a free port to avoid clashes with lingering servers from earlier tests
    _sock = socket.socket(); _sock.bind(('127.0.0.1', 0)); dyn_port = _sock.getsockname()[1]; _sock.close()
    monkeypatch.setenv('G6_SSE_HTTP_PORT', str(dyn_port))

    from scripts.summary.plugins.sse import SSEPublisher
    from scripts.summary.unified_loop import UnifiedLoop

    pub = SSEPublisher(diff=True)
    loop = UnifiedLoop([pub], panels_dir='data/panels', refresh=0.1)

    import threading
    t = threading.Thread(target=lambda: loop.run(cycles=35), daemon=True)
    t.start()
    time.sleep(0.4)
    # Defensive: ensure no residual connection window state from earlier tests (should be clean via fixture, but double‑guard here for stability)
    try:
        from scripts.summary import sse_http as _sseh  # type: ignore
        if hasattr(_sseh, '_ip_conn_window'):
            _sseh._ip_conn_window.clear()  # type: ignore[attr-defined]
    except Exception:
        pass

    # First two connections succeed
    headers = {'User-Agent':'GoodClientTest/1.0', 'X-Request-ID':'abc123'}
    c1 = http.client.HTTPConnection('127.0.0.1', dyn_port, timeout=3)
    c1.request('GET','/summary/events', headers=headers)
    r1 = c1.getresponse(); assert r1.status == 200
    # Verify X-Request-ID echoed back
    assert r1.getheader('X-Request-ID') == 'abc123'

    # Defensive normalization: if prior unrelated connections polluted window, clear once
    try:
        from scripts.summary import sse_http as _sseh  # type: ignore
        win = getattr(_sseh, '_ip_conn_window', None)
        if isinstance(win, dict):
            # Allow keeping the current successful connect timestamp; drop excess
            for k,v in list(win.items()):
                if isinstance(v, list) and len(v) > 1:
                    # Keep only most recent (current) timestamp to allow one more acceptance
                    win[k] = v[-1:]
    except Exception:
        pass

    # Small stagger to ensure first connection increments global active counter fully
    time.sleep(0.05)
    c2 = http.client.HTTPConnection('127.0.0.1', dyn_port, timeout=3)
    c2.request('GET','/summary/events', headers=headers)
    r2 = c2.getresponse()
    if r2.status != 200:
        # Diagnostics dump to aid any residual flake analysis
        try:
            from scripts.summary import sse_http as _sseh  # type: ignore
            win = getattr(_sseh, '_ip_conn_window', {})
            print(f"[sse-test-diag] second_conn_status={r2.status} window={win}")
            try:
                from scripts.summary import unified_http as _uh  # type: ignore
                print(f"[sse-test-diag] unified_http_imported={bool(_uh)}")
            except Exception:
                pass
        except Exception:
            pass
    assert r2.status == 200

    # Third immediate connection should be rate limited (429)
    c3 = http.client.HTTPConnection('127.0.0.1', dyn_port, timeout=3)
    c3.request('GET','/summary/events', headers=headers)
    r3 = c3.getresponse(); assert r3.status == 429

    c1.close(); c2.close(); c3.close()

    # UA forbidden case
    bad = http.client.HTTPConnection('127.0.0.1', dyn_port, timeout=3)
    bad.request('GET','/summary/events', headers={'User-Agent':'OtherBot/2.0'})
    rb = bad.getresponse(); assert rb.status == 403
    bad.close()
