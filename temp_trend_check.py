import os,time,json
os.environ['G6_ADAPTIVE_ALERT_SEVERITY']='1'
os.environ['G6_ADAPTIVE_CONTROLLER']='1'
os.environ['G6_ADAPTIVE_CONTROLLER_SEVERITY']='1'
os.environ['G6_ADAPTIVE_SEVERITY_TREND_SMOOTH']='1'
os.environ['G6_ADAPTIVE_SEVERITY_TREND_WINDOW']='5'
os.environ['G6_ADAPTIVE_ALERT_SEVERITY_RULES']='{"risk_delta_drift":{"warn":0.04,"critical":0.08}}'
from src.adaptive import severity, logic
for c in range(5):
    severity.enrich_alert({'type':'risk_delta_drift','drift_pct':0.05,'cycle':c})
    logic.evaluate_and_apply(['NIFTY'])
    time.sleep(0.01)
print('direct', severity.get_trend_stats())
