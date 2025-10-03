import os
import importlib
import sys

from typing import Dict, Any


def _reset_module():
    if 'src.adaptive.severity' in sys.modules:
        del sys.modules['src.adaptive.severity']
    return importlib.import_module('src.adaptive.severity')


def enrich(sev_mod, t: str, cycle: int, **fields: Any) -> Dict[str, Any]:
    alert = {"type": t, "cycle": cycle, **fields}
    return sev_mod.enrich_alert(alert)


def test_decay_critical_to_warn_to_info():
    os.environ['G6_ADAPTIVE_ALERT_SEVERITY'] = '1'
    os.environ['G6_ADAPTIVE_ALERT_SEVERITY_DECAY_CYCLES'] = '2'
    os.environ['G6_ADAPTIVE_ALERT_SEVERITY_MIN_STREAK'] = '1'
    sev = _reset_module()

    # Fire two cycles with critical interpolation_high (fraction >=0.70)
    a1 = enrich(sev, 'interpolation_high', 10, interpolated_fraction=0.75)
    assert a1['severity'] == 'critical'
    a2 = enrich(sev, 'interpolation_high', 11, interpolated_fraction=0.80)
    assert a2['severity'] == 'critical'

    # Jump forward 2 cycles without new alerts -> decay critical->warn (gap >=2)
    a3 = enrich(sev, 'interpolation_high', 13, interpolated_fraction=0.0)  # metric low so raw classify=>info
    # active_severity should have decayed only one step (critical->warn) because gap=2 meets threshold once
    assert a3.get('active_severity') in ('warn', 'info')  # in case raw classification bumps
    # Provide another gap to decay warn->info
    a4 = enrich(sev, 'interpolation_high', 15, interpolated_fraction=0.0)
    assert a4.get('active_severity') == 'info'
    # Since previous was elevated and now info with no new event raising severity, resolved flag expected
    assert a4.get('resolved') is True


def test_decay_bucket_util_low_inverted():
    os.environ['G6_ADAPTIVE_ALERT_SEVERITY'] = '1'
    os.environ['G6_ADAPTIVE_ALERT_SEVERITY_DECAY_CYCLES'] = '1'
    sev = _reset_module()

    # Trigger warn (utilization between critical and warn)
    a1 = enrich(sev, 'bucket_util_low', 20, utilization=0.65)
    assert a1['severity'] == 'warn'
    # Next cycle no alert for utilization healthy (>= warn => info)
    a2 = enrich(sev, 'bucket_util_low', 21, utilization=0.90)
    # Active severity may still reflect previous warn before decay threshold satisfied (decay after 1 cycle) -> now should decay to info
    assert a2.get('active_severity') == 'info'
    assert a2.get('resolved') is True


def test_no_decay_when_disabled():
    os.environ['G6_ADAPTIVE_ALERT_SEVERITY'] = '1'
    os.environ['G6_ADAPTIVE_ALERT_SEVERITY_DECAY_CYCLES'] = '0'
    sev = _reset_module()
    a1 = enrich(sev, 'risk_delta_drift', 30, drift_pct=0.11)  # critical
    assert a1['severity'] == 'critical'
    # Advance cycles with low drift but decay disabled -> active should remain info OR classification result only; no resolved flag since decay off
    a2 = enrich(sev, 'risk_delta_drift', 40, drift_pct=0.0)
    # decay off means active severity tracks classification only (which is info) but should not set resolved because no decay path
    assert 'resolved' not in a2


def test_resolved_flag_only_on_decay():
    os.environ['G6_ADAPTIVE_ALERT_SEVERITY'] = '1'
    os.environ['G6_ADAPTIVE_ALERT_SEVERITY_DECAY_CYCLES'] = '2'
    sev = _reset_module()
    # Trigger warn
    a1 = enrich(sev, 'interpolation_high', 100, interpolated_fraction=0.55)
    assert a1['severity'] == 'warn'
    # Gap less than decay threshold -> no decay yet
    a2 = enrich(sev, 'interpolation_high', 101, interpolated_fraction=0.10)
    assert a2.get('resolved') is None
    # Gap reaching threshold -> should decay warn->info and set resolved
    a3 = enrich(sev, 'interpolation_high', 103, interpolated_fraction=0.10)
    assert a3.get('active_severity') == 'info'
    assert a3.get('resolved') is True
