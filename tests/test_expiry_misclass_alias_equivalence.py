import datetime as dt
from src.storage.csv_sink import CsvSink


def _make_option(strike):
    return {'strike': strike, 'instrument_type': 'CE', 'last_price': 1.0, 'volume': 1, 'oi': 1, 'avg_price': 1.0}


def test_alias_equivalence_skip_vs_policy_reject(tmp_path, monkeypatch):
    monkeypatch.setenv('G6_EXPIRY_MISCLASS_DETECT','1')
    # Scenario 1: legacy skip flag
    base1 = tmp_path / 's1'; base1.mkdir()
    sink1 = CsvSink(base_dir=str(base1))
    # First write establishes canonical mapping (2025-10-02). Provide two instruments (CE+PE style simplified)
    opts = {'A': _make_option(100), 'B': {'strike':100,'instrument_type':'PE','last_price':1.0,'volume':1,'oi':1,'avg_price':1.0}}
    t0 = dt.datetime(2025,10,1,12,0,0)
    monkeypatch.setenv('G6_EXPIRY_MISCLASS_SKIP','1')
    # Force logical tag so heuristic distance does not produce distinct expiry_code values
    sink1.write_options_data('NIFTY', dt.date(2025,10,2), opts, t0, expiry_rule_tag='this_week')
    # Conflicting date expected to be skipped (reject behavior)
    sink1.write_options_data('NIFTY', dt.date(2025,10,9), opts, t0+dt.timedelta(minutes=1), expiry_rule_tag='this_week')
    # Collect overview & option data artifacts (exclude overview from option scan)
    ov_file1 = base1 / 'overview' / 'NIFTY' / f"{t0.strftime('%Y-%m-%d')}.csv"
    assert ov_file1.exists(), 'overview file missing in scenario1'
    ov_lines1 = ov_file1.read_text().splitlines()
    # Expect two overview rows (header + 2 rows) because we invoke write twice; second write still emits overview row even though option data skipped
    assert len(ov_lines1) == 3, f'scenario1 overview expected 3 lines (header+2 rows) got {len(ov_lines1)}'
    option_files1 = [p for p in base1.rglob('*.csv') if 'overview' not in p.parts]
    # Allow possibility of stray directory creation for conflicting date prior to remediation skip; enforce that only one file has 2 lines (header+row)
    data_file_line_counts = {p: len(p.read_text().splitlines()) for p in option_files1}
    # Exactly one file should have 2 lines (persisted first write). Others (if any) should be empty or single-header (<=1 line)
    two_line_files = [p for p,c in data_file_line_counts.items() if c == 2]
    assert len(two_line_files) == 1, f"scenario1 expected exactly one data-bearing file (2 lines); counts={data_file_line_counts}"
    assert all(c <= 2 for c in data_file_line_counts.values()), f"scenario1 unexpected extra data rows: {data_file_line_counts}"

    # Scenario 2: explicit policy=reject
    base2 = tmp_path / 's2'; base2.mkdir()
    monkeypatch.delenv('G6_EXPIRY_MISCLASS_SKIP', raising=False)
    monkeypatch.setenv('G6_EXPIRY_MISCLASS_POLICY','reject')
    sink2 = CsvSink(base_dir=str(base2))
    sink2.write_options_data('NIFTY', dt.date(2025,10,2), opts, t0, expiry_rule_tag='this_week')
    sink2.write_options_data('NIFTY', dt.date(2025,10,9), opts, t0+dt.timedelta(minutes=1), expiry_rule_tag='this_week')
    ov_file2 = base2 / 'overview' / 'NIFTY' / f"{t0.strftime('%Y-%m-%d')}.csv"
    assert ov_file2.exists(), 'overview file missing in scenario2'
    ov_lines2 = ov_file2.read_text().splitlines()
    assert len(ov_lines2) == 3, f'scenario2 overview expected 3 lines got {len(ov_lines2)}'
    option_files2 = [p for p in base2.rglob('*.csv') if 'overview' not in p.parts]
    data_file_line_counts2 = {p: len(p.read_text().splitlines()) for p in option_files2}
    two_line_files2 = [p for p,c in data_file_line_counts2.items() if c == 2]
    assert len(two_line_files2) == 1, f"scenario2 expected exactly one data-bearing file (2 lines); counts={data_file_line_counts2}"
    assert all(c <= 2 for c in data_file_line_counts2.values()), f"scenario2 unexpected extra data rows: {data_file_line_counts2}"

    # Equivalence assertions: overview behavior & option suppression identical
    assert ov_lines1[0] == ov_lines2[0], 'headers differ'
    assert ov_lines1[1:] == ov_lines2[1:], 'overview rows differ between alias and policy=reject'
