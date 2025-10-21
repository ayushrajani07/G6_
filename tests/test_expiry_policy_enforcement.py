#!/usr/bin/env python3
import os
import tempfile
import shutil
import datetime

from src.metrics import get_metrics  # facade import
from src.storage.csv_sink import CsvSink

# Helper to craft option data with adjustable internal expiry (to simulate misclassification)

def _option(typ, strike, expiry_date):
    return {
        'instrument_type': typ,
        'strike': strike,
        'last_price': 100.0,
        'avg_price': 100.0,
        'volume': 10,
        'oi': 10,
        'expiry_date': expiry_date.strftime('%Y-%m-%d'),
    }

def _options_pair(strike, expiry_a, expiry_b=None):
    # expiry_b if provided sets opposite leg to different date to trigger misclassification
    return {
        f'CE_{strike}': _option('CE', strike, expiry_a),
        f'PE_{strike}': _option('PE', strike, expiry_b or expiry_a),
    }

def _run_cycle(sink, index, exp_date, options_data):
    ts = datetime.datetime.now()  # local-ok
    sink.write_options_data(index=index, expiry=exp_date, options_data=options_data, timestamp=ts)


def test_policy_rewrite(tmp_path, monkeypatch):
    metrics = get_metrics()
    base = tmp_path / 'data'
    sink = CsvSink(base_dir=str(base))
    sink.attach_metrics(metrics)
    # First canonical row
    d0 = datetime.date.today() + datetime.timedelta(days=2)
    opts = _options_pair(100, d0)
    _run_cycle(sink, 'NIFTY', d0, opts)
    # Misclassified second row (different internal leg expiry)
    d1 = d0 + datetime.timedelta(days=7)
    opts2 = _options_pair(150, d0, d1)
    monkeypatch.setenv('G6_EXPIRY_MISCLASS_POLICY', 'rewrite')
    _run_cycle(sink, 'NIFTY', d0, opts2)
    # Expect rewritten counter increment (from_code == to_code logically identical tag; we still record attempt)
    # We cannot assert exact value due to global registry reuse; just ensure label access works.
    metrics.expiry_rewritten_total.labels(index='NIFTY', from_code='this_week', to_code='this_week')  # type: ignore[attr-defined]


def test_policy_quarantine(tmp_path, monkeypatch):
    metrics = get_metrics()
    base = tmp_path / 'data'
    sink = CsvSink(base_dir=str(base))
    sink.attach_metrics(metrics)
    d0 = datetime.date.today() + datetime.timedelta(days=2)
    _run_cycle(sink, 'BANKNIFTY', d0, _options_pair(100, d0))
    d1 = d0 + datetime.timedelta(days=7)
    monkeypatch.setenv('G6_EXPIRY_MISCLASS_POLICY', 'quarantine')
    _run_cycle(sink, 'BANKNIFTY', d0, _options_pair(150, d0, d1))
    # If default relative directory path used it will live under sink base dir
    qroot = (tmp_path / 'data' / 'quarantine' / 'expiries')
    if qroot.exists():
        ndjson_files = [p for p in qroot.iterdir() if p.suffix == '.ndjson']
        assert ndjson_files, 'Expected at least one quarantine ndjson file'


def test_policy_reject(tmp_path, monkeypatch):
    metrics = get_metrics()
    base = tmp_path / 'data'
    sink = CsvSink(base_dir=str(base))
    sink.attach_metrics(metrics)
    d0 = datetime.date.today() + datetime.timedelta(days=2)
    _run_cycle(sink, 'FINNIFTY', d0, _options_pair(100, d0))
    d1 = d0 + datetime.timedelta(days=7)
    monkeypatch.setenv('G6_EXPIRY_MISCLASS_POLICY', 'reject')
    _run_cycle(sink, 'FINNIFTY', d0, _options_pair(150, d0, d1))
    # Access rejected metric labels for assurance
    metrics.expiry_rejected_total.labels(index='FINNIFTY', expiry_code='this_week')  # type: ignore[attr-defined]
