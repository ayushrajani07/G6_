import json
from types import SimpleNamespace
from scripts.summary.unified_http import UnifiedSummaryHandler
from http.server import BaseHTTPRequestHandler

# We'll simulate minimal environment by monkeypatching get_last_snapshot and metrics snapshot

def test_health_endpoint_enhanced(monkeypatch):
    class DummySnap(SimpleNamespace):
        pass
    snap = DummySnap(cycle=42, status={'panel_push_meta': {'diff_stats': {'hit_ratio': 0.9, 'cycles': 10}, 'timing': {'header': {'avg_ms': 1.0}}}}, panel_hashes={'header':'x'})
    monkeypatch.setenv('G6_UNIFIED_HTTP_PORT', '0')
    from scripts.summary import unified_http as uh
    monkeypatch.setattr(uh, 'get_last_snapshot', lambda: snap)
    # metrics snapshot fake
    fake_metrics = {
        'gauge': {
            'g6_summary_panel_updates_last': 1,
            'g6_summary_diff_hit_ratio': 0.9,
            'g6_summary_panel_churn_ratio': 0.25,
            'g6_summary_panel_high_churn_streak': 2.0,
        }
    }
    from scripts.summary import summary_metrics as sm
    monkeypatch.setattr(sm, 'snapshot', lambda: fake_metrics)

    # Build a fake handler instance
    class DummyRequest:
        def makefile(self, *_, **__):
            from io import BytesIO
            return BytesIO()

    handler = UnifiedSummaryHandler(DummyRequest(), ('127.0.0.1', 0), None)  # type: ignore[arg-type]
    handler.path = '/summary/health'
    # monkeypatch methods to capture output
    sent = {}
    def _send_response(self, code):
        sent['code'] = code
    def _send_header(self, k,v):
        sent.setdefault('headers', {})[k]=v
    def _end(self):
        pass
    def _write(self, data):
        sent['body'] = data
    handler.send_response = _send_response.__get__(handler)
    handler.send_header = _send_header.__get__(handler)
    handler.end_headers = _end.__get__(handler)
    handler.wfile.write = _write  # type: ignore

    handler.do_GET()
    assert sent['code'] == 200
    body = json.loads(sent['body'])
    assert body['cycle'] == 42
    assert 'diff' in body and 'hit_ratio' in body
    assert body['panel_updates_last'] == 1
    # New churn fields
    assert 'churn_ratio' in body and body['churn_ratio'] == 0.25
    assert 'high_churn_streak' in body and body['high_churn_streak'] == 2.0
