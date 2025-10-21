import datetime
import logging

from src.broker.kite_provider import KiteProvider
from src.utils.bootstrap import bootstrap

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s %(message)s')

INDEXES = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"]
RULES = ["this_week", "next_week", "this_month", "next_month"]


def main() -> None:
    # Use bootstrap to ensure environment and metrics alignment
    boot = bootstrap(enable_metrics=False)  # metrics not required for diagnostic
    kp = KiteProvider(api_key="dummy", access_token="dummy")
    print("\nExpiry Resolution Diagnostic\n" + "="*34)
    today = datetime.date.today()
    print(f"Today: {today}")
    for idx in INDEXES:
        print(f"\nIndex: {idx}")
        for rule in RULES:
            try:
                dt = kp.resolve_expiry(idx, rule)
                source = "fallback" if kp._used_fallback else "primary"
                print(f"  {rule:11s} -> {dt}  ({source})")
            except Exception as e:
                print(f"  {rule:11s} -> ERROR: {e}")
    kp.close()

if __name__ == "__main__":
    main()
