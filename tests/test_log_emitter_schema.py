import logging
import os
import re

import pytest

from src.observability.log_emitter import log_event, EVENT_RE


def test_event_schema_valid_accepts(caplog):
    caplog.set_level(logging.INFO)
    log_event("expiry.resolve.ok", index="NIFTY", rule="near")
    assert any("expiry.resolve.ok" in r.message for r in caplog.records)


@pytest.mark.parametrize("bad", [
    "expiry",  # too short
    "foo.bar.ok",  # domain not allowed
    "expiry.RESOLVE.ok",  # uppercase
    "expiry.resolve..ok",  # empty segment
])
def test_event_schema_invalid_rejects(bad, caplog, monkeypatch):
    monkeypatch.setenv('PYTEST_CURRENT_TEST', '1')
    with pytest.raises(ValueError):
        log_event(bad, test=1)


def test_regex_compiles():
    assert EVENT_RE.match("expiry.prefilter.applied")
    assert not EVENT_RE.match("provider..double")
