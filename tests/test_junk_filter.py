import os
import time
from src.filters.junk_filter import JunkFilterConfig, JunkFilter, JunkFilterCallbacks

class DummyLogger:
    def __init__(self):
        self.messages = []
    def info(self, m):
        self.messages.append(("info", m))
    def debug(self, m):
        self.messages.append(("debug", m))

def _make(cfg_env: dict):
    cfg = JunkFilterConfig.from_env(cfg_env)
    logger = DummyLogger()
    jf = JunkFilter(cfg, JunkFilterCallbacks(log_info=logger.info, log_debug=logger.debug))
    return jf, logger

def test_threshold_skip_total_oi():
    env = {
        'G6_CSV_JUNK_MIN_TOTAL_OI': '100',
        'G6_CSV_JUNK_ENABLE': 'auto'
    }
    jf, _ = _make(env)
    skip, decision = jf.should_skip('NIFTY','this_week',0, {'oi':10}, {'oi':20}, 't1')
    assert skip and decision.category == 'threshold'
    skip2, decision2 = jf.should_skip('NIFTY','this_week',0, {'oi':10}, {'oi':20}, 't1')
    # Second time same ts still skip but first_time False
    assert skip2 and not decision2.first_time

def test_whitelist_allows():
    env = {
        'G6_CSV_JUNK_MIN_TOTAL_OI': '100',
        'G6_CSV_JUNK_ENABLE': 'auto',
        'G6_CSV_JUNK_WHITELIST': 'NIFTY:this_week'
    }
    jf, _ = _make(env)
    skip, decision = jf.should_skip('NIFTY','this_week',0, {'oi':10}, {'oi':20}, 't1')
    assert not skip

def test_stale_detection():
    env = {
        'G6_CSV_JUNK_STALE_THRESHOLD': '2',
        'G6_CSV_JUNK_ENABLE': 'auto'
    }
    jf, _ = _make(env)
    # Provide identical prices to trip stale after threshold
    last_skip = False
    last_decision = None
    for i in range(3):
        last_skip, last_decision = jf.should_skip('NIFTY','this_week',0, {'last_price':1.23}, {'last_price':2.34}, f't{i}')
    assert last_skip and last_decision and last_decision.category == 'stale'

def test_summary_emission(monkeypatch):
    env = {
        'G6_CSV_JUNK_MIN_TOTAL_OI': '100',
        'G6_CSV_JUNK_ENABLE': 'auto',
        'G6_CSV_JUNK_SUMMARY_INTERVAL': '1'
    }
    jf, _ = _make(env)
    # Two skips separated by simulated time to trigger summary
    skip, decision = jf.should_skip('NIFTY','this_week',0, {'oi':10}, {'oi':20}, 't1')
    assert skip
    # fast-forward time
    orig_time = time.time
    monkeypatch.setattr('src.filters.junk_filter.time.time', lambda: orig_time() + 2)
    skip2, decision2 = jf.should_skip('NIFTY','this_week',1, {'oi':5}, {'oi':5}, 't2')
    assert skip2
    assert decision2.summary_emitted
