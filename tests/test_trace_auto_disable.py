import os
import re
import contextlib
from io import StringIO

from src.collectors.unified_collectors import run_unified_collectors


class DummyProviders:
    def resolve_expiry(self, index, rule):
        import datetime as dt
        # just return today + 7 days to simulate a future expiry
        return dt.date.today() + dt.timedelta(days=7)

    def get_expiry_dates(self, index):  # not used in new path
        return []

    def build_index_price(self, index):  # potential helper if pipeline expects
        return 100.0


def _make_index_params():
    # minimal structure consistent with what run_unified_collectors iterates
    return {
        'NIFTY': {
            'enabled': True,
            'expiries': ['this_week'],
            'strike_cfg': {'n_itm': 1, 'n_otm': 1},
        }
    }


def test_trace_auto_disable(monkeypatch):
    # Ensure trace flags start enabled
    monkeypatch.setenv('G6_TRACE_COLLECTOR', '1')
    monkeypatch.setenv('G6_TRACE_EXPIRY_SELECTION', '1')
    monkeypatch.setenv('G6_TRACE_EXPIRY_PIPELINE', '1')
    monkeypatch.setenv('G6_CSV_VERBOSE', '1')
    monkeypatch.setenv('G6_TRACE_AUTO_DISABLE', '1')

    providers = DummyProviders()

    # Capture logs (TRACE lines should appear pre-disable; we only assert env flip afterward)
    buf = StringIO()
    import logging
    h = logging.StreamHandler(buf)
    root = logging.getLogger()
    root.addHandler(h)
    prev_level = root.level
    root.setLevel(logging.INFO)
    try:
        run_unified_collectors(_make_index_params(), providers, csv_sink=None, influx_sink=None, metrics=None)
    finally:
        root.setLevel(prev_level)
        root.removeHandler(h)

    # After one cycle, flags should be rewritten to '0'
    for flag in ['G6_TRACE_COLLECTOR','G6_TRACE_EXPIRY_SELECTION','G6_TRACE_EXPIRY_PIPELINE','G6_CSV_VERBOSE']:
        assert os.environ.get(flag,'0') == '0', f"{flag} not disabled"

    # Ensure we emitted the control log line
    log_value = buf.getvalue()
    assert 'trace_auto_disable: disabled' in log_value
