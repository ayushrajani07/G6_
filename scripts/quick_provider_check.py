import os, sys, json
from src.utils.bootstrap import bootstrap
from src.broker.kite_provider import KiteProvider, DummyKiteProvider

os.environ.setdefault('KITE_API_KEY','dummy')
os.environ.setdefault('KITE_ACCESS_TOKEN','dummy')

try:
    boot = bootstrap(enable_metrics=True, log_level="WARNING")
    kp = KiteProvider.from_env()
    instruments=[('NSE','NIFTY 50')]
    q = kp.get_quote(instruments)
    l = kp.get_ltp(instruments)
    print('REAL_PROVIDER', True)
    # Defensive: some providers may return raw bytes; convert if needed
    if isinstance(q, (bytes, bytearray)):
        try:
            q = json.loads(q.decode('utf-8'))
        except Exception:
            q = {"_raw_bytes_len": len(q)}
    if isinstance(l, (bytes, bytearray)):
        try:
            l = json.loads(l.decode('utf-8'))
        except Exception:
            l = {"_raw_bytes_len": len(l)}
    if hasattr(q, 'keys'):
        print('QUOTE_KEYS', list(q.keys())[:3])
        print('QUOTE_SAMPLE', list(q.values())[:1])
    else:
        print('QUOTE_OBJ_TYPE', type(q))
    if isinstance(l, memoryview):
        try:
            l = l.tobytes()
            l = json.loads(l.decode('utf-8'))
        except Exception:
            l = {"_raw_memoryview_len": len(l)}
    if hasattr(l, 'keys'):
        print('LTP_KEYS', list(l.keys())[:3])
    else:
        print('LTP_OBJ_TYPE', type(l))
except Exception as e:
    print('KiteProvider init failed (expected with dummy creds):', e)
    dp = DummyKiteProvider()
    instruments=[('NSE','NIFTY 50')]
    try:
        dummy_quote = dp.get_quote(instruments)
        print('DUMMY_QUOTE', dummy_quote)
    except Exception as ie:
        print('DUMMY_QUOTE_ERROR', ie)
