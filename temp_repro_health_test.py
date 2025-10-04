import json, io
from types import SimpleNamespace
from scripts.summary.unified_http import UnifiedSummaryHandler
from scripts.summary import unified_http as uh
# monkeypatch get_last_snapshot
snap = SimpleNamespace(cycle=42, status={'panel_push_meta': {'diff_stats': {'hit_ratio': 0.9, 'cycles': 10}, 'timing': {'header': {'avg_ms': 1.0}}}}, panel_hashes={'header':'x'})
uh.get_last_snapshot = lambda: snap
from scripts.summary import summary_metrics as sm
sm.snapshot = lambda: {'gauge': {'g6_summary_panel_updates_last':1,'g6_summary_diff_hit_ratio':0.9,'g6_summary_panel_churn_ratio':0.25,'g6_summary_panel_high_churn_streak':2.0}}
class DummyRequest:
    def makefile(self, *a, **k):
        return io.BytesIO()
handler = UnifiedSummaryHandler(DummyRequest(), ('127.0.0.1',0), None)
handler.path = '/summary/health'
sent = {}
handler.send_response = (lambda self, code: sent.setdefault('code', code)).__get__(handler)
handler.send_header = (lambda self,k,v: sent.setdefault('headers',{}).__setitem__(k,v)).__get__(handler)
handler.end_headers = (lambda self: None).__get__(handler)
# monkeypatch wfile.write
try:
    handler.wfile.write = lambda data: sent.setdefault('body', data)
    print('patched write OK')
except Exception as e:
    print('patch write failed', e)
handler.do_GET()
print('sent keys:', sent.keys())
if 'body' in sent:
    print('body len', len(sent['body']))
    print('json keys', json.loads(sent['body']).keys())
else:
    print('NO BODY')
