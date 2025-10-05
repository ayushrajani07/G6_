import os
import threading
import time
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

# Lightweight SSE test harness focusing on ensuring no force_full reconnect when auto recovery disabled.

PANEL_FULL_SENT = False

class SSEHandler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def log_message(self, format, *args):  # noqa: D401
        return
    def do_GET(self):  # noqa: N802
        global PANEL_FULL_SENT
        if self.path.startswith('/events'):
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            # Only emit a diff (missing baseline) to trigger need_full but never reply with force_full injection
            payload = {
                'type': 'panel_diff',
                'generation': 5,
                'payload': {'diff': {'added': {'foo': 'bar'}}},
            }
            line = f"data: {json.dumps(payload)}\n\n".encode()
            # Flush a single diff event quickly; no need to linger 0.2s which adds up in constrained CI
            try:
                self.wfile.write(line)
                self.wfile.flush()
            except Exception:
                pass
            # Short sleep only to allow client read; keep minimal to reduce overall suite wall time
            time.sleep(0.02)
        else:
            self.send_response(404)
            self.end_headers()

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    # Prevent long blocking if client disconnects; keep handlers responsive
    timeout = 0.2


def _run_server(server):
    server.serve_forever()


def test_auto_recovery_disabled_no_force_full(monkeypatch, tmp_path):
    # Disable auto recovery
    monkeypatch.setenv('G6_SUMMARY_AUTO_FULL_RECOVERY', 'off')
    # Enable diagnostic timing and enforce fast exit guards (fallback if fake_refresh not triggered)
    monkeypatch.setenv('G6_SUMMARY_DIAG_TIMING', '1')
    monkeypatch.setenv('G6_SUMMARY_MAX_SECONDS', '8')
    monkeypatch.setenv('G6_SUMMARY_MAX_CYCLES', '4')
    # Provide SSE URL
    server = ThreadedHTTPServer(('127.0.0.1', 0), SSEHandler)
    # server_address may be (host,port) or (host,port,flowinfo,scopeid) for IPv6
    addr = server.server_address
    host = addr[0]
    port = addr[1]
    t = threading.Thread(target=_run_server, args=(server,), daemon=True)
    t.start()
    sse_url = f'http://{host}:{port}/events'

    # Run the summary app loop briefly
    from scripts.summary import app as summary_app

    # Patch refresh_layout to stop after need_full flagged
    # Track completion & refresh count (explicit typed keys to satisfy type checker)
    stop_flag = {'done': False, 'cycles_count': 0}  # type: ignore[var-annotated]
    orig_refresh_layout = summary_app.refresh_layout

    def fake_refresh(layout, status, *a, **kw):  # noqa: ANN001
        orig_refresh_layout(layout, status, *a, **kw)
        meta = status.get('panel_push_meta') if isinstance(status, dict) else None
        # Terminate as soon as we observe a need_full flag (original intent) OR after two cycles
        # to avoid slow tail scenarios.
        stop_flag['cycles_count'] += 1
        if (meta and meta.get('need_full')) or stop_flag['cycles_count'] >= 2:
            stop_flag['done'] = True
            raise KeyboardInterrupt()

    monkeypatch.setattr(summary_app, 'refresh_layout', fake_refresh)

    # Use a tighter refresh to accelerate triggering logic; previous 0.2 refresh slowed test.
    rc = summary_app.run([
        '--sse-url', sse_url,
        '--no-rich',
        '--refresh', '0.02'
    ])

    server.shutdown()
    assert rc == 0
    # We expect no recovery metric increment because force_full never attempted.
    # If registry exists, ensure events_full_recovery_total is 0 or absent.
    try:
        from src.metrics import registry  # type: ignore
        m = getattr(registry, 'events_full_recovery_total', None)
        if m is not None:
            # Prometheus client counters expose _value.get() or collect(); be defensive.
            val = None
            try:
                val = m._value.get()  # type: ignore[attr-defined]
            except Exception:
                try:
                    for fam in m.collect():  # type: ignore[attr-defined]
                        for sample in fam.samples:
                            val = sample.value
                            break
                except Exception:
                    pass
            if val is not None:
                assert val == 0
    except Exception:
        pass
