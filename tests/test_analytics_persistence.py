import os, json, gzip
from src.analytics.vol_surface import build_surface
from src.analytics.risk_agg import build_risk


def _sample_opts_for_interp():
    # Provide sparse buckets so interpolation fills gaps
    # Buckets default: -20,-10,-5,0,5,10,20 -> use strikes to hit -20 and 10 only
    base_under = 100.0
    # moneyness -20% => strike 80, +10% => strike 110
    return [
        {'index':'TEST','expiry':'2025-10-30','strike':80,'underlying':base_under,'iv':0.25,'delta':0.4,'gamma':0.01,'vega':0.1,'theta':-0.02,'rho':0.03},
        {'index':'TEST','expiry':'2025-10-30','strike':110,'underlying':base_under,'iv':0.35,'delta':0.45,'gamma':0.011,'vega':0.11,'theta':-0.021,'rho':0.031},
    ]


def test_vol_surface_interpolation_and_persistence(tmp_path, monkeypatch):
    monkeypatch.setenv('G6_VOL_SURFACE','1')
    monkeypatch.setenv('G6_VOL_SURFACE_INTERPOLATE','1')
    monkeypatch.setenv('G6_VOL_SURFACE_PERSIST','1')
    monkeypatch.setenv('G6_ANALYTICS_COMPRESS','1')
    monkeypatch.setenv('G6_ANALYTICS_DIR', str(tmp_path))
    surf = build_surface(_sample_opts_for_interp())
    assert surf and surf['meta']['interpolated'] is True
    assert surf['meta']['persisted'] is True
    path = surf['meta']['persist_path']
    assert path.endswith('.json.gz')
    assert (tmp_path / path.split('/')[-1]).exists()
    # Ensure at least one interpolated row (source=='interp') present besides the 2 raw rows
    raw = [r for r in surf['data'] if r.get('source')=='raw']
    interp = [r for r in surf['data'] if r.get('source')=='interp']
    assert len(raw) == 2
    assert len(interp) >= 1


def test_risk_agg_persistence_and_notionals(tmp_path, monkeypatch):
    monkeypatch.setenv('G6_RISK_AGG','1')
    monkeypatch.setenv('G6_RISK_AGG_PERSIST','1')
    monkeypatch.setenv('G6_ANALYTICS_COMPRESS','1')
    monkeypatch.setenv('G6_ANALYTICS_DIR', str(tmp_path))
    monkeypatch.setenv('G6_CONTRACT_MULTIPLIER_DEFAULT','50')
    risk = build_risk(_sample_opts_for_interp())
    assert risk and risk['meta']['persisted'] is True
    path = risk['meta']['persist_path']
    assert path.endswith('.json.gz')
    assert (tmp_path / path.split('/')[-1]).exists()
    # notionals present and scaled (delta ~0.4+0.45 aggregated ~0.85 * 50 = 42.5)
    # find row bucket containing one of the strikes; just check any row has non-zero notionals
    assert any(r.get('notionals',{}).get('delta',0) > 10 for r in risk['data'])
