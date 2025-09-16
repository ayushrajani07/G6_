import datetime
from src.utils.timeutils import round_timestamp


def test_round_timestamp_nearest():
    base = datetime.datetime(2025, 9, 14, 10, 5, 14, 999999)
    r = round_timestamp(base, step_seconds=30, strategy='nearest')
    assert r.second == 0 and r.minute == 5

    base2 = datetime.datetime(2025, 9, 14, 10, 5, 16)
    r2 = round_timestamp(base2, step_seconds=30, strategy='nearest')
    assert r2.second == 30 and r2.minute == 5


def test_round_timestamp_floor():
    base = datetime.datetime(2025, 9, 14, 10, 5, 44)
    r = round_timestamp(base, step_seconds=30, strategy='floor')
    assert r.second == 30


def test_round_timestamp_ceil():
    base = datetime.datetime(2025, 9, 14, 10, 5, 1)
    r = round_timestamp(base, step_seconds=30, strategy='ceil')
    assert r.second == 30
    base2 = datetime.datetime(2025, 9, 14, 10, 5, 31)
    r2 = round_timestamp(base2, step_seconds=30, strategy='ceil')
    assert r2.second == 0 and r2.minute == 6
