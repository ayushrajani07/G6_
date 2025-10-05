import time, types
import os
from importlib import import_module

sse_shared = import_module('scripts.summary.sse_shared')

class DummyHandler:
    def __init__(self, ip='1.2.3.4', headers=None):
        self.client_address=(ip,12345)
        self.headers=headers or {}
        self._written=[]
        self.wfile=types.SimpleNamespace(write=lambda b: self._written.append(b), flush=lambda: None)
        self._responses=[]
    def send_response(self, code):
        self._responses.append(code)
    def send_header(self, k,v):
        pass
    def end_headers(self):
        pass


def test_auth_failure_sets_401():
    cfg = sse_shared.SecurityConfig(token_required='secret', allow_ips=set(), rate_spec='', ua_allow='', allow_origin=None)
    h = DummyHandler(headers={'X-API-Token':'wrong'})
    code = sse_shared.enforce_auth_and_rate(h, cfg, ip_conn_window={})
    assert code == 401
    assert 401 in h._responses


def test_ip_allow_rejects_unlisted():
    cfg = sse_shared.SecurityConfig(token_required=None, allow_ips={'9.9.9.9'}, rate_spec='', ua_allow='', allow_origin=None)
    h = DummyHandler(ip='1.1.1.1')
    code = sse_shared.enforce_auth_and_rate(h, cfg, ip_conn_window={})
    assert code == 403


def test_user_agent_allow_enforced():
    cfg = sse_shared.SecurityConfig(token_required=None, allow_ips=set(), rate_spec='', ua_allow='GoodClient', allow_origin=None)
    h = DummyHandler(headers={'User-Agent':'BadClient/1.0'})
    code = sse_shared.enforce_auth_and_rate(h, cfg, ip_conn_window={})
    assert code == 403


def test_rate_limiting_blocks_after_threshold(monkeypatch):
    cfg = sse_shared.SecurityConfig(token_required=None, allow_ips=set(), rate_spec='2:1', ua_allow='', allow_origin=None)
    ip_window={}
    h1 = DummyHandler()
    h2 = DummyHandler()
    handlers=[h1,h2]
    # First two attempts allowed
    assert sse_shared.enforce_auth_and_rate(h1, cfg, ip_conn_window=ip_window, handlers_ref=handlers) is None
    assert sse_shared.enforce_auth_and_rate(h2, cfg, ip_conn_window=ip_window, handlers_ref=handlers) is None
    # Third attempt should rate limit
    h3 = DummyHandler()
    handlers.append(h3)
    code = sse_shared.enforce_auth_and_rate(h3, cfg, ip_conn_window=ip_window, handlers_ref=handlers)
    assert code == 429
