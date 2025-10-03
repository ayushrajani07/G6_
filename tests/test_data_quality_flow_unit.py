import datetime as dt

from src.collectors.modules.data_quality_flow import apply_data_quality


class DummyDQ:
    def __init__(self, opt_issues=None, cons_issues=None, raise_opts=False, raise_cons=False):
        self.opt_issues = opt_issues or []
        self.cons_issues = cons_issues or []
        self.raise_opts = raise_opts
        self.raise_cons = raise_cons
    def validate_options_data(self, data):
        if self.raise_opts:
            raise RuntimeError("opt fail")
        return {}, list(self.opt_issues)
    def check_expiry_consistency(self, data, index_price=None, expiry_rule=None):
        if self.raise_cons:
            raise RuntimeError("cons fail")
        return list(self.cons_issues)


def run_option_quality(dq, options_data):
    return dq.validate_options_data(options_data)


def run_expiry_consistency(dq, options_data, index_price, expiry_rule):
    return dq.check_expiry_consistency(options_data, index_price=index_price, expiry_rule=expiry_rule)


def test_dq_no_issues():
    dq = DummyDQ()
    rec = {}
    enriched = {'A': {'x':1}}
    apply_data_quality(dq, True, enriched,
        index_symbol='NIFTY', expiry_rule='this_week', index_price=100.0,
        expiry_rec=rec, run_option_quality=run_option_quality, run_expiry_consistency=run_expiry_consistency)
    assert 'dq_issues' not in rec and 'dq_consistency' not in rec


def test_dq_option_issues():
    dq = DummyDQ(opt_issues=['bad_bid','bad_oi'])
    rec = {}
    enriched = {'A': {'x':1}}
    apply_data_quality(dq, True, enriched,
        index_symbol='NIFTY', expiry_rule='this_week', index_price=100.0,
        expiry_rec=rec, run_option_quality=run_option_quality, run_expiry_consistency=run_expiry_consistency)
    assert rec.get('dq_issues') == ['bad_bid','bad_oi']


def test_dq_consistency_issues():
    dq = DummyDQ(cons_issues=['price_outlier'])
    rec = {}
    enriched = {'A': {'x':1}}
    apply_data_quality(dq, True, enriched,
        index_symbol='NIFTY', expiry_rule='this_week', index_price=100.0,
        expiry_rec=rec, run_option_quality=run_option_quality, run_expiry_consistency=run_expiry_consistency)
    assert rec.get('dq_consistency') == ['price_outlier']


def test_dq_exceptions_do_not_raise():
    dq = DummyDQ(raise_opts=True, raise_cons=True)
    rec = {}
    enriched = {'A': {'x':1}}
    apply_data_quality(dq, True, enriched,
        index_symbol='NIFTY', expiry_rule='this_week', index_price=100.0,
        expiry_rec=rec, run_option_quality=run_option_quality, run_expiry_consistency=run_expiry_consistency)
    # No keys should be added because both paths failed
    assert rec == {}
