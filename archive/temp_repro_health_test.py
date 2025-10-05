"""Archived health endpoint reproduction harness.

Originally monkeypatched UnifiedSummaryHandler internals to dump /summary/health
payload. Retained for historical debugging context only.
"""
import json, io  # noqa: F401
from types import SimpleNamespace  # noqa: F401
from scripts.summary.unified_http import UnifiedSummaryHandler  # noqa: F401
from scripts.summary import unified_http as uh  # noqa: F401
from scripts.summary import summary_metrics as sm  # noqa: F401

def _run_demo():  # pragma: no cover
    snap = SimpleNamespace(cycle=42, status={'panel_push_meta': {'diff_stats': {'hit_ratio': 0.9, 'cycles': 10}, 'timing': {'header': {'avg_ms': 1.0}}}}, panel_hashes={'header': 'x'})
    uh.get_last_snapshot = lambda: snap  # type: ignore
    sm.snapshot = lambda: {'gauge': {'g6_summary_panel_updates_last': 1, 'g6_summary_diff_hit_ratio': 0.9, 'g6_summary_panel_churn_ratio': 0.25, 'g6_summary_panel_high_churn_streak': 2.0}}  # type: ignore
    class DummyRequest:  # noqa: D401
        def makefile(self, *a, **k):
            return io.BytesIO()
    handler = UnifiedSummaryHandler(DummyRequest(), ('127.0.0.1', 0), None)
    handler.path = '/summary/health'
    sent = {}
    handler.send_response = (lambda self, code: sent.setdefault('code', code)).__get__(handler)  # type: ignore
    handler.send_header = (lambda self, k, v: sent.setdefault('headers', {}).setdefault(k, v)).__get__(handler)  # type: ignore
    handler.end_headers = (lambda self: None).__get__(handler)  # type: ignore
    handler.wfile.write = lambda data: sent.setdefault('body', data)  # type: ignore
    handler.do_GET()
    if 'body' in sent:
        payload = json.loads(sent['body'])
        print('keys', payload.keys())
    else:
        print('No body produced')

if __name__ == '__main__':  # pragma: no cover
    print('Archived health test harness; prefer unit tests.')
    _run_demo()
