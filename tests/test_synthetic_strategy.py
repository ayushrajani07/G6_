from src.synthetic.strategy import build_synthetic_index_context, synthesize_index_price, build_synthetic_quotes


def test_build_synthetic_index_context_basic():
    ctx = build_synthetic_index_context("nifty")
    assert ctx.symbol == "NIFTY"
    assert ctx.step > 0
    assert ctx.base_price > 10000
    # ATM should be multiple of step
    assert (ctx.atm / ctx.step) == round(ctx.atm / ctx.step)


def test_synthesize_index_price_when_invalid():
    price, atm, used = synthesize_index_price("NIFTY", 0, 0)
    assert used is True
    assert price > 0 and atm > 0


def test_synthesize_index_price_when_valid_passthrough():
    price, atm, used = synthesize_index_price("BANKNIFTY", 54000, 54000)
    assert used is False
    assert price == 54000 and atm == 54000


def test_build_synthetic_quotes_structure():
    instruments = [
        {"tradingsymbol": "NIFTY25SEP24800CE", "exchange": "NFO", "strike": 24800, "instrument_type": "CE"},
        {"tradingsymbol": "NIFTY25SEP24800PE", "exchange": "NFO", "strike": 24800, "instrument_type": "PE"},
    ]
    quotes = build_synthetic_quotes(instruments)
    assert len(quotes) == 2
    for v in quotes.values():
        assert v.get("synthetic_quote") is True
        assert "ohlc" in v and isinstance(v["ohlc"], dict)


# Additional multi-index ATM determinism tests

def test_multi_index_contexts():
    symbols = ["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"]
    seen = {}
    for sym in symbols:
        ctx = build_synthetic_index_context(sym)
        assert ctx.symbol == sym
        assert ctx.step > 0
        # ATM multiple of step
        assert (ctx.atm / ctx.step) == round(ctx.atm / ctx.step)
        seen[sym] = ctx.atm
    # Ensure diversity across indices (no accidental uniformization)
    assert len({v for v in seen.values()}) == len(symbols)


def test_build_synthetic_quotes_deterministic_fields():
    instruments = [
        {"tradingsymbol": "NIFTY25SEP24800CE", "exchange": "NFO", "strike": 24800, "instrument_type": "CE"},
        {"tradingsymbol": "NIFTY25SEP24800PE", "exchange": "NFO", "strike": 24800, "instrument_type": "PE"},
    ]
    q1 = build_synthetic_quotes(instruments)
    q2 = build_synthetic_quotes(instruments)
    # Keys identical and stable
    assert set(q1.keys()) == set(q2.keys())
    for k in q1:
        a, b = q1[k], q2[k]
        # Timestamp may differ; zero out before structural comparison
        for rec in (a, b):
            assert rec["synthetic_quote"] is True
            assert rec["last_price"] == 0.0
            assert rec["volume"] == 0
            assert rec["oi"] == 0
            assert rec["ohlc"] == {"open":0,"high":0,"low":0,"close":0}
