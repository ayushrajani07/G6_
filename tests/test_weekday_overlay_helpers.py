from datetime import date

from scripts.weekday_overlay import _parse_time_key, _hhmmss_to_seconds, _normalize_indices


def test_parse_time_key_variants():
    assert _parse_time_key("2024-10-10T09:15:30") == "09:15:30"
    assert _parse_time_key("2024-10-10 15:30:00") == "15:30:00"
    assert _parse_time_key("09:45:05") == "09:45:05"
    assert _parse_time_key("") == ""


def test_hhmmss_to_seconds():
    assert _hhmmss_to_seconds("00:00:00") == 0
    assert _hhmmss_to_seconds("01:00:00") == 3600
    assert _hhmmss_to_seconds("09:15:30") == 9 * 3600 + 15 * 60 + 30
    assert _hhmmss_to_seconds("bad") == -1


essential = ["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"]


def test_normalize_indices_defaults_and_unknowns():
    # None -> defaults
    assert _normalize_indices(None) == essential
    # Empty -> defaults
    assert _normalize_indices([]) == essential
    # Known mix with case and commas
    assert _normalize_indices(["nifty,banknifty", "FINNIFTY"]) == [
        "NIFTY",
        "BANKNIFTY",
        "FINNIFTY",
    ]
    # Unknowns are ignored
    assert _normalize_indices(["FOO", "BAR"]) == essential
