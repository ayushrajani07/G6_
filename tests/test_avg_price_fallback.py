import pytest

class DummyProvider:
    def __init__(self, quote_map):
        self._quote_map = quote_map
    def get_quote(self, instruments):
        # instruments list of (exchange,symbol)
        out = {}
        for ex,sym in instruments:
            key = f"{ex}:{sym}"
            out[key] = self._quote_map.get(key, {})
        return out

@pytest.mark.parametrize("high,low,last,expected", [
    (110.0, 90.0, 100.0, (110+90+2*100)/4.0),  # weighted formula
    (110.0, 90.0, 0.0, (110+90)/2.0),          # fallback to midpoint without last
])
def test_avg_price_fallback(high, low, last, expected):
    from src.collectors.providers_interface import ProvidersInterface  # type: ignore
    # Build instrument
    inst = [{
        'tradingsymbol': 'OPTTEST',
        'exchange': 'NFO',
        'instrument_type': 'CE',
        'strike': 100,
    }]
    quote = {
        'last_price': last,
        'volume': 0,
        'oi': 0,
        'ohlc': {'high': high, 'low': low},
        # average_price intentionally missing / zero
        'average_price': 0,
    }
    provider = DummyProvider({'NFO:OPTTEST': quote})
    class Wrap:
        def __init__(self, p):
            self.primary_provider = p
            self.logger = __import__('logging').getLogger('test')
    wrapper = Wrap(provider)
    pi = ProvidersInterface(wrapper.primary_provider)  # reuse provider directly
    # Monkey patch expected attributes used in enrich_with_quotes
    pi.logger = wrapper.logger
    enriched = pi.enrich_with_quotes(inst)
    assert 'OPTTEST' in enriched
    data = enriched['OPTTEST']
    assert pytest.approx(data['avg_price'], rel=1e-6) == expected
    assert data.get('avg_price_fallback_used') is True
