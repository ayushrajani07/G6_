import os
import importlib
from datetime import datetime
import pytest

# Feature removed: cardinality suppression was deprecated/removed from CsvSink.
# Skip this entire module to keep the test suite aligned with current behavior.
pytest.skip("Cardinality suppression feature removed from CsvSink", allow_module_level=True)

from src.storage.csv_sink import CsvSink


def test_cardinality_activation_and_deactivation(monkeypatch):
    sink = CsvSink(base_dir='data/g6_data_test')
    # Force threshold small for test
    sink.cardinality_max_strikes = 5

    # 1. Below threshold -> no suppression
    assert sink._test_eval_suppression('NIFTY','this_week', 3) is False
    # 2. Exactly threshold -> still no suppression
    assert sink._test_eval_suppression('NIFTY','this_week', 5) is False
    # 3. Above threshold -> suppression activates
    assert sink._test_eval_suppression('NIFTY','this_week', 6) is True
    # 4. Still above threshold -> stays suppressed
    assert sink._test_eval_suppression('NIFTY','this_week', 7) is True
    # 5. Drop to threshold -> deactivates
    assert sink._test_eval_suppression('NIFTY','this_week', 5) is False


def test_cardinality_chatter_hysteresis_like(monkeypatch):
    sink = CsvSink(base_dir='data/g6_data_test2')
    sink.cardinality_max_strikes = 10
    # Activate
    assert sink._test_eval_suppression('BANKNIFTY','this_month', 11) is True
    # Slight dip but still above -> remains
    assert sink._test_eval_suppression('BANKNIFTY','this_month', 12) is True
    # Go exactly to threshold -> clears
    assert sink._test_eval_suppression('BANKNIFTY','this_month', 10) is False
    # Jump above again -> re-activate
    assert sink._test_eval_suppression('BANKNIFTY','this_month', 15) is True
