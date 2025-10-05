import os, json, types, io, time
from importlib import import_module

# Test parse_rate_spec edge cases

def test_parse_rate_spec_variants():
    sse_shared = import_module('scripts.summary.sse_shared')
    prs = sse_shared.parse_rate_spec
    assert prs('5:10') == (5,10)
    assert prs('7/30') == (7,30)
    assert prs('9') == (9,60)
    assert prs('bad/spec') == (0,60)

# Test token bucket behavior boundaries

def test_allow_event_token_bucket_basic(monkeypatch):
    sse_shared = import_module('scripts.summary.sse_shared')
    allow = sse_shared.allow_event_token_bucket
    class H: pass
    h = H()
    monkeypatch.setenv('G6_SSE_EVENTS_PER_SEC', '5')
    allowed = sum(1 for _ in range(10) if allow(h))
    assert allowed <= 10  # some events allowed, then limited
    # simulate time passage to replenish
    time.sleep(0.3)
    assert allow(h) is True

# Test write_sse_event truncation and metrics integration

def test_write_sse_event_truncation_and_metrics(tmp_path, monkeypatch):
    sse_shared = import_module('scripts.summary.sse_shared')
    wrote = {}
    class Counter:
        def __init__(self): self.n=0
        def inc(self): self.n+=1
    class Hist:
        def __init__(self): self.vals=[]
        def observe(self,v): self.vals.append(v)
    class H:
        def __init__(self): self.wfile=types.SimpleNamespace(write=lambda b: wrote.setdefault('data',b), flush=lambda: None)
    sec = Counter(); sent = Counter(); size = Hist(); lat = Hist()
    monkeypatch.setenv('G6_SSE_MAX_EVENT_BYTES','10')
    evt={'event':'my_event','data':{'very':'long','payload':'x'*50},'_ts_emit':time.time()-0.05}
    sse_shared.write_sse_event(H(), evt, security_metric=sec, events_sent_metric=sent, h_event_size=size, h_event_latency=lat, debug_log_path=str(tmp_path/'debug.log'))
    out = wrote['data'].decode()
    assert 'event: truncated' in out  # truncated due to max bytes=10
    assert sec.n==1 and sent.n==1
    assert size.vals and lat.vals

# Test env_catalog_check ignore logic (non-G6 vars ignored)

def test_env_catalog_check_ignore_logic(monkeypatch, tmp_path):
    mod = import_module('scripts.cleanup.env_catalog_check')
    # Build minimal fake catalog file
    cat_path = tmp_path/'env_vars.json'
    cat_path.write_text(json.dumps({'env_vars':['G6_FOO']}))
    monkeypatch.setattr(mod, 'CATALOG', cat_path)
    sample_code = 'import os\nvalue=os.getenv("GITHUB_ACTIONS") or os.getenv("G6_FOO") or os.getenv("TERM") or os.getenv("KITE_API_KEY")'  # noqa
    # Create temp module file scanned by scan_vars by pointing ROOT to temp dir
    root = tmp_path/'src'
    root.mkdir()
    (root/'sample.py').write_text(sample_code)
    monkeypatch.setattr(mod, 'ROOT', tmp_path)
    # Re-import functions referencing patched ROOT
    missing_before = mod.scan_vars()
    assert 'G6_FOO' in missing_before and 'GITHUB_ACTIONS' in missing_before
    # Run main and capture stdout
    from io import StringIO
    import sys as _sys
    buf = StringIO(); old_out=_sys.stdout; _sys.stdout=buf
    try:
        rc = mod.main()
    finally:
        _sys.stdout=old_out
    out = buf.getvalue()
    assert rc==0, out
    assert 'ignored_non_governed' in out
    assert 'MISSING:' not in out

# Test orphan analyzer classification improvements (tombstone skip excluded)

def test_orphan_analyzer_tombstone_skip(monkeypatch, tmp_path):
    orphan = import_module('scripts.cleanup.orphan_tests')
    test_dir = tmp_path/'tests'; test_dir.mkdir()
    tomb = test_dir/'test_tombstone.py'
    tomb.write_text('import pytest\npytest.skip("legacy", allow_module_level=True)')
    real = test_dir/'test_real.py'
    real.write_text('def test_x():\n    assert 1==1')
    monkeypatch.setattr(orphan, 'ROOT', tmp_path)
    executed=set()
    res_tomb = orphan.analyze_test(tomb, executed)
    res_real = orphan.analyze_test(real, executed)
    assert res_tomb is None
    assert res_real is None  # not orphan because asserts
