import os
import json
import logging
from contextlib import contextmanager

import pytest

from src.broker.kite_provider import kite_provider_factory, ProviderRecoverableError, ProviderFatalError  # type: ignore

@contextmanager
def capture_logs(*logger_names: str):
    loggers = [logging.getLogger(n) for n in logger_names]
    saved = [(lg, lg.level) for lg in loggers]
    stream: list[str] = []

    class ListHandler(logging.Handler):
        def emit(self, record):  # type: ignore[override]
            try:
                stream.append(record.getMessage())
            except Exception:
                pass

    handlers = []
    for lg in loggers:
        lg.setLevel(logging.INFO)
        h = ListHandler()
        lg.addHandler(h)
        handlers.append((lg, h))
    try:
        yield stream
    finally:
        for lg, h in handlers:
            lg.removeHandler(h)
        for lg, lvl in saved:
            lg.setLevel(lvl)


def _extract_events(lines):
    events = []
    for ln in lines:
        if 'provider.kite.' in ln:
            try:
                events.append(json.loads(ln))
            except Exception:
                pass
    return events


def test_structured_event_emitted_for_ltp(monkeypatch):
    monkeypatch.setenv('G6_PROVIDER_EVENTS', '1')
    # Build provider (no real client expected) and call get_ltp which will execute instrumentation
    prov = kite_provider_factory(api_key='k', access_token='t')
    # Capture both facade logger and provider_events module logger
    with capture_logs('src.broker.kite_provider', 'src.broker.kite.provider_events') as lines:
        try:
            prov.get_ltp(['NSE:FOO'])  # may fail if client absent; still want event
        except Exception:
            pass
    events = _extract_events(lines)
    assert any(e.get('event','').startswith('provider.kite.quotes.ltp') for e in events), f"No ltp event found in {events}"


def test_error_classification_recoverable(monkeypatch):
    monkeypatch.setenv('G6_PROVIDER_EVENTS', '1')
    prov = kite_provider_factory(api_key='k', access_token='t')

    # Force an exception with transient signature to test classification
    def fake_impl(self, instruments):
        raise RuntimeError('temporary rate limit exceeded')

    monkeypatch.setattr('src.broker.kite.quotes.get_ltp', fake_impl)
    with capture_logs('src.broker.kite_provider', 'src.broker.kite.provider_events') as lines:
        with pytest.raises(ProviderRecoverableError):
            prov.get_ltp(['NSE:BAR'])
    events = _extract_events(lines)
    # Look for an error outcome event with error_class ProviderRecoverableError
    err_events = [e for e in events if e.get('outcome') == 'error']
    assert any(e.get('error_class') == 'ProviderRecoverableError' for e in err_events), err_events


def test_error_classification_fatal(monkeypatch):
    monkeypatch.setenv('G6_PROVIDER_EVENTS', '1')
    prov = kite_provider_factory(api_key='k', access_token='t')

    def fake_impl(self, instruments):
        raise RuntimeError('unmapped catastrophic failure')

    monkeypatch.setattr('src.broker.kite.quotes.get_ltp', fake_impl)
    with capture_logs('src.broker.kite_provider', 'src.broker.kite.provider_events') as lines:
        with pytest.raises(ProviderFatalError):
            prov.get_ltp(['NSE:BAZ'])
    events = _extract_events(lines)
    err_events = [e for e in events if e.get('outcome') == 'error']
    assert any(e.get('error_class') == 'ProviderFatalError' for e in err_events), err_events
