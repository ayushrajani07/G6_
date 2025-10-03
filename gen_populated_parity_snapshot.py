import os, json, tempfile, pathlib, datetime as dt
from src.orchestrator.parity_harness import run_parity_cycle

BASE_INDEX = 'NIFTY'

class _MiniConfig:
    def __init__(self, base_dir: str, expiries):
        self._base_dir = base_dir
        self._index_params = {
            BASE_INDEX: {
                'enable': True,
                'expiries': expiries,
                'strikes_itm': 2,
                'strikes_otm': 2,
            }
        }
    def index_params(self): return self._index_params
    def data_dir(self): return self._base_dir
    def get(self, key, default=None):
        if key == 'greeks':
            return {'enabled': False}
        return default

# We simulate legacy/new CSV discovery by writing files in expected layout before running harness.
# Layout: <base>/g6_data/NIFTY/<expiry>/options_mock.csv
HEADER = 'strike,option_type,ltp,iv'  # minimal recognizable header

SAMPLE_ROWS = [
    '20000,CE,12.5,0.15',
    '20000,PE,10.5,0.16',
    '20100,CE,8.3,0.14',
]

def prepopulate(base_dir: str, expiries):
    g6_data = pathlib.Path(base_dir) / 'g6_data' / BASE_INDEX
    g6_data.mkdir(parents=True, exist_ok=True)
    for exp in expiries:
        d = g6_data / exp
        d.mkdir(exist_ok=True)
        with open(d / 'options_mock.csv', 'w', encoding='utf-8') as f:
            f.write(HEADER + '\n' + '\n'.join(SAMPLE_ROWS))

def main():
    os.environ['G6_USE_MOCK_PROVIDER']='1'
    os.environ['G6_FORCE_MARKET_OPEN']='1'
    # Choose two synthetic expiry codes (ISO dates forward)
    today = dt.date.today()
    expiries = [str(today + dt.timedelta(days=2)), str(today + dt.timedelta(days=9))]
    tmp = tempfile.mkdtemp(prefix='parity_pop_')
    prepopulate(tmp, expiries)
    cfg = _MiniConfig(tmp, expiries)
    snap = run_parity_cycle(cfg)
    print(json.dumps(snap, indent=2, sort_keys=True))

if __name__ == '__main__':
    main()
