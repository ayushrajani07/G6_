import io
from scripts.summary.unified_http import UnifiedSummaryHandler
class DummyReq:
    def makefile(self, *a, **k):
        return io.BytesIO()

h = UnifiedSummaryHandler(DummyReq(), ('127.0.0.1',0), None)
print('wfile type:', type(h.wfile))
print('has __dict__?', hasattr(h.wfile, '__dict__'))
try:
    orig = h.wfile.write
    def custom(data):
        print('custom capture len', len(data))
    h.wfile.write = custom  # type: ignore
    print('rebind succeeded')
except Exception as e:
    print('rebind failed', e)
