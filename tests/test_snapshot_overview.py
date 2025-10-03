import datetime as dt

from src.domain.models import OptionQuote, ExpirySnapshot, OverviewSnapshot


def make_option(symbol: str) -> OptionQuote:
    return OptionQuote(
        symbol=symbol,
        exchange="NSE",
        last_price=100.0,
        volume=10,
        oi=5,
        timestamp=dt.datetime.now(dt.timezone.utc),
        raw={"ltp": 100.0},
    )


def test_overview_snapshot_basic_counts_and_fields():
    now = dt.datetime.now(dt.timezone.utc)
    snap1 = ExpirySnapshot(
        index="NIFTY",
        expiry_rule="WEEKLY",
        expiry_date=now.date(),
        atm_strike=20000,
        options=[make_option("NIFTY24SEP20000CE"), make_option("NIFTY24SEP20000PE")],
        generated_at=now,
    )
    snap2 = ExpirySnapshot(
        index="BANKNIFTY",
        expiry_rule="WEEKLY",
        expiry_date=now.date(),
        atm_strike=45000,
        options=[make_option("BANKNIFTY24SEP45000CE")],
        generated_at=now,
    )

    overview = OverviewSnapshot.from_expiry_snapshots([snap1, snap2])
    data = overview.as_dict()

    assert data["total_indices"] == 2
    assert data["total_expiries"] == 2
    assert data["total_options"] == snap1.option_count + snap2.option_count
    # PCR: puts=1 calls=2 -> 0.5
    assert data["put_call_ratio"] == 0.5
    # max pain placeholder: average of atm strikes (20000 + 45000)/2
    assert data["max_pain_strike"] == (20000 + 45000) / 2
    assert data["generated_at"].endswith("Z")


def test_overview_snapshot_empty_list():
    overview = OverviewSnapshot.from_expiry_snapshots([])
    data = overview.as_dict()
    assert data["total_indices"] == 0
    assert data["total_expiries"] == 0
    assert data["total_options"] == 0
    assert data["put_call_ratio"] is None
    assert data["max_pain_strike"] is None
