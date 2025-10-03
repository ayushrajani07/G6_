from src.collectors.modules.coverage_core import compute_index_coverage


def test_coverage_core_basic():
    expiries = [
        {"rule": "this_week", "options": 10, "strike_coverage": 0.5, "field_coverage": 0.8},
        {"rule": "next_week", "options": 0, "strike_coverage": None, "field_coverage": 0.6},
        {"rule": "far", "options": 5, "strike_coverage": 0.7, "field_coverage": 0.9},
    ]
    roll = compute_index_coverage("NIFTY", expiries)
    assert roll["options_total"] == 15
    # Expiries with options: 2 (10 + 5 > 0)
    assert roll["expiries_with_options"] == 2
    # Average strike coverage: (0.5 + 0.7)/2 = 0.6
    assert abs(roll["strike_coverage_avg"] - 0.6) < 1e-12
    # Average field coverage: (0.8 + 0.6 + 0.9)/3 = 0.7666.. (we included 0.6 even though options=0)
    assert abs(roll["field_coverage_avg"] - ((0.8 + 0.6 + 0.9)/3)) < 1e-12
    assert roll["status"] == "OK"


def test_coverage_core_empty():
    roll = compute_index_coverage("BANKNIFTY", [])
    assert roll["options_total"] == 0
    assert roll["strike_coverage_avg"] is None
    assert roll["field_coverage_avg"] is None
    assert roll["status"] == "EMPTY"