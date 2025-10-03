from src.domain.models import OptionQuote, EnrichedOption, ExpirySnapshot
import datetime as dt

def test_option_quote_from_raw_basic():
    raw = {"last_price": 123.45, "volume": 10, "oi": 200, "timestamp": "2025-09-26T10:15:30Z"}
    q = OptionQuote.from_raw("NFO:ABC123CE", raw)
    assert q.symbol == "ABC123CE"
    assert q.exchange == "NFO"
    assert q.last_price == 123.45
    assert q.volume == 10 and q.oi == 200
    assert isinstance(q.timestamp, dt.datetime)


def test_enriched_option_from_quote():
    raw = {"last_price": 10, "volume": 1, "oi": 5, "timestamp": "2025-09-26T10:15:30Z"}
    q = OptionQuote.from_raw("NFO:XYZ999PE", raw)
    enriched = EnrichedOption.from_quote(q, {"iv": 25.4, "delta": 0.55, "gamma": 0.01, "theta": -5.2, "vega": 12.3})
    assert enriched.iv == 25.4
    assert enriched.delta == 0.55
    assert enriched.raw is q.raw


def test_expiry_snapshot_option_count():
    now = dt.datetime.now(dt.timezone.utc)
    q1 = OptionQuote.from_raw("NFO:A1CE", {"last_price": 1})
    q2 = OptionQuote.from_raw("NFO:A2PE", {"last_price": 2})
    snap = ExpirySnapshot(index="NIFTY", expiry_rule="this_week", expiry_date=now.date(), atm_strike=100.0, options=[q1, q2], generated_at=now)
    assert snap.option_count == 2
