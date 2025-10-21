#!/usr/bin/env python3
import os
import json
import datetime

from src.metrics import get_metrics  # facade import
from src.storage.csv_sink import CsvSink
from src.events import event_log


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
    return {
        f'CE_{strike}': _option('CE', strike, expiry_a),
        f'PE_{strike}': _option('PE', strike, expiry_b or expiry_a),
    }


def _run_cycle(sink, index, exp_date, options_data, **kw):
    ts = datetime.datetime.now()  # local-ok
    # Adapt to current CsvSink API: write_options_data(index, expiry, options_data, timestamp, ...)
    sink.write_options_data(index, exp_date, options_data, ts, **kw)


def test_quarantine_pending_and_summary(tmp_path, monkeypatch):
    metrics = get_metrics()
    base = tmp_path / 'data'
    sink = CsvSink(base_dir=str(base))
    sink.attach_metrics(metrics)
    # speed up summary emission
    monkeypatch.setenv('G6_EXPIRY_SUMMARY_INTERVAL_SEC', '1')
    # Configure policy + quarantine dir BEFORE first row so cached policy is correct
    qdir = base / 'quarantine' / 'expiries'
    monkeypatch.setenv('G6_EXPIRY_MISCLASS_POLICY', 'quarantine')
    monkeypatch.setenv('G6_EXPIRY_QUARANTINE_DIR', str(qdir))
    d0 = datetime.date.today() + datetime.timedelta(days=2)
    # Establish canonical mapping for (index,'this_week') with expiry_date d0
    _run_cycle(sink, 'SENSEX', d0, _options_pair(100, d0), expiry_rule_tag='this_week')
    # Trigger misclassification by changing the top-level expiry date while keeping the same logical tag
    alt_date = d0 + datetime.timedelta(days=7)
    for k in range(3):
        pair = _options_pair(150 + k*50, alt_date)
        _run_cycle(sink, 'SENSEX', alt_date, pair, expiry_rule_tag='this_week')
    # Pending gauge label presence
    metrics.expiry_quarantine_pending.labels(date=datetime.date.today().isoformat())  # type: ignore[attr-defined]
    # Validate quarantine file schema
    ndjson_files = [p for p in qdir.glob('*.ndjson')]
    assert ndjson_files, 'expected quarantine ndjson file present'
    sample_line = None
    with open(ndjson_files[0], 'r', encoding='utf-8') as fh:
        for ln in fh:
            if ln.strip():
                sample_line = ln
                break
    assert sample_line, 'expected at least one quarantine record line'
    obj = json.loads(sample_line)
    # Basic required keys
    for key in ['ts','index','original_expiry_code','canonical_expiry_code','reason','row']:
        assert key in obj
    assert obj['reason'] == 'expiry_misclassification'
    # Force summary emission by calling internal helper
    sink._update_expiry_daily_stats('quarantined')  # noqa: SLF001 allowed in test for coverage
    recent = event_log.get_recent_events(limit=20)
    assert any(ev.get('event') == 'expiry_quarantine_summary' for ev in recent), 'expected summary event emitted'
