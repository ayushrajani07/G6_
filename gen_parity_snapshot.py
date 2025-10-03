import os, json, tempfile, pathlib
from src.orchestrator.parity_harness import run_parity_cycle

class _MiniConfig:
    def __init__(self, base_dir: str):
        self._base_dir = base_dir
        self._index_params = {
            'NIFTY': {
                'enable': True,
                'expiries': ['this_week'],
                'strikes_itm': 2,
                'strikes_otm': 2,
            }
        }
    def index_params(self):
        return self._index_params
    def data_dir(self):
        return self._base_dir
    def get(self, key, default=None):
        if key == 'greeks':
            return {'enabled': False}
        return default

def main():
    os.environ['G6_USE_MOCK_PROVIDER']='1'
    os.environ['G6_FORCE_MARKET_OPEN']='1'
    tmp = tempfile.mkdtemp(prefix='parity_gold_')
    cfg = _MiniConfig(tmp)
    snap = run_parity_cycle(cfg)
    print(json.dumps(snap, indent=2, sort_keys=True))

if __name__ == '__main__':
    main()
