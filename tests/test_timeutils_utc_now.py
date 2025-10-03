from src.utils.timeutils import utc_now

def test_utc_now_is_timezone_aware():
    t = utc_now()
    assert t.tzinfo is not None, 'utc_now() must return tz-aware datetime'
    assert str(t.tzinfo).lower() in ('utc', 'utc+00:00', 'timezone.utc')


def test_utc_now_monotonic_increase():
    a = utc_now()
    b = utc_now()
    # Allow equality if clock resolution coarse, but ensure not reversed
    assert b >= a
