import math
import os
from src.utils.normalization import normalize_price, sanitize_option_fields


def test_normalize_price_paise_to_rupees_plausible():
    # Large price that becomes plausible when divided by 100
    # 550000 -> 5500 which is < 0.35 * 20050 (~7017)
    p = normalize_price(550000, strike=20050, index_price=20050)
    assert 500 < p < 7000


def test_normalize_price_equals_oi_drops():
    # price ~ oi within 2% should drop to 0 (likely mis-mapped)
    p = normalize_price(10010, strike=20000, oi=10000)
    assert p == 0.0


def test_normalize_price_clamps_vs_strike(monkeypatch):
    # Use a value below paise-threshold to avoid /100 path, but above 0.35*strike
    # 8000 > 0.35*20000 (=7000) -> clamp to 0
    # Also raise paise threshold high to prevent divide-by-100 branch
    monkeypatch.setenv('G6_PRICE_PAISE_THRESHOLD', '1e9')
    monkeypatch.setenv('G6_PRICE_MAX_STRIKE_FRAC', '0.35')
    p = normalize_price(8000, strike=20000)
    assert p == 0.0


def test_sanitize_option_fields_coercions():
    rec = {
        'strike': '20050',
        'last_price': '550000',
        'avg_price': '545000',
        'volume': '1000',
        'oi': '2000',
    }
    out = sanitize_option_fields(rec, index_price=20050)
    assert isinstance(out['volume'], int)
    assert isinstance(out['oi'], int)
    assert out['last_price'] > 0 and out['avg_price'] > 0