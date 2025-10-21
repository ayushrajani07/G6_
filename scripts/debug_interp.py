import os

from src.adaptive.alerts import record_interpolation_fraction
from src.metrics import get_metrics

os.environ['G6_INTERP_FRACTION_ALERT_THRESHOLD']='0.5'
os.environ['G6_INTERP_FRACTION_ALERT_STREAK']='3'

m = get_metrics()
fractions=[0.4,0.55,0.60,0.61]
for f in fractions:
    alert = record_interpolation_fraction('global', f)
    streaks = getattr(m, '_interp_streak', {})
    print(f"fraction={f} streak={streaks.get('global')} alert={alert}")
