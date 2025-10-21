"""Option chain aggregated metrics computation.

Provides low-cardinality distribution metrics over option chain snapshots.

Activation & Provider Resolution:
    * Disabled when env G6_OPTION_CHAIN_AGG_DISABLED in ("1","true","True").
    * Provider injection via env G6_OPTION_CHAIN_PROVIDER of the form
             `package.module:attr` or `package.module:Factory` returning an object.
    * Provider contract (any of):
             - get_option_chain_snapshot() -> iterable[dict] or pandas.DataFrame
                 Expected columns/keys (if DataFrame or dict rows):
                        strike, expiry, type ("CE"/"PE"), oi, volume_24h, iv, spread_bps,
                        underlying (spot), dte_days (optional), mny (optional)
             - fetch_option_chain(index_symbol, expiry_date, strike_range, strike_step=None)
                 Combined with get_atm_strike(index_symbol) to derive moneyness & DTE.
    * If provider missing or fails, fallback synthetic pseudo-random snapshot (logged once).

Buckets:
    Moneyness (mny): deep_itm, itm, atm, otm, deep_otm
    DTE (dte): ultra_short, short, medium, long, leap

Function `aggregate_once()` performs one snapshot aggregation.
"""
from __future__ import annotations

import importlib
import logging
import os
import random
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from . import generated as m  # generated metric accessors

logger = logging.getLogger(__name__)

MNY_BUCKETS = [
    ("deep_itm", -10.0, -0.20),  # value <= upper
    ("itm", -0.20, -0.05),
    ("atm", -0.05, 0.05),
    ("otm", 0.05, 0.20),
    ("deep_otm", 0.20, 10.0),   # value > lower
]

DTE_BUCKETS = [
    ("ultra_short", 0, 1),
    ("short", 1, 7),
    ("medium", 7, 30),
    ("long", 30, 90),
    ("leap", 90, 10000),
]

@dataclass
class ContractRow:
    mny: float   # normalized moneyness, e.g. (strike - spot)/spot
    dte: float   # days to expiry
    oi: float
    volume_24h: float
    iv: float    # annualized implied volatility (0-5 plausible band)
    spread_bps: float  # bid-ask spread in bps of mid


def _bucket_mny(v: float) -> str:
    for name, lo, hi in MNY_BUCKETS:
        # deep_itm uses v <= hi, others inclusive lower (<name> up to hi)
        if name == "deep_itm" and v <= hi:
            return name
        if lo <= v < hi:
            return name
    return "deep_otm"


def _bucket_dte(v: float) -> str:
    for name, lo, hi in DTE_BUCKETS:
        if lo <= v < hi:
            return name
    return "leap"


_PROVIDER: Any | None = None
_PROVIDER_ERROR_LOGGED = False

def _load_provider() -> Any | None:
    global _PROVIDER, _PROVIDER_ERROR_LOGGED
    if _PROVIDER is not None:
        return _PROVIDER
    spec = os.getenv("G6_OPTION_CHAIN_PROVIDER")
    if not spec:
        return None
    try:
        if ':' in spec:
            mod_name, attr = spec.split(':', 1)
        else:
            mod_name, attr = spec, None
        mod = importlib.import_module(mod_name)
        obj = getattr(mod, attr) if attr else mod
        if callable(obj):  # factory
            obj = obj()
        _PROVIDER = obj
    except Exception as e:  # pragma: no cover - defensive
        if not _PROVIDER_ERROR_LOGGED:
            logger.warning("Option chain provider load failed (%s): %s", spec, e)
            _PROVIDER_ERROR_LOGGED = True
        _PROVIDER = None
    return _PROVIDER

def _provider_snapshot() -> Iterable[ContractRow] | None:
    provider = _load_provider()
    if not provider:
        return None
    # Strategy 1: direct snapshot method
    try:
        if hasattr(provider, 'get_option_chain_snapshot'):
            snap = provider.get_option_chain_snapshot()
            return _normalize_snapshot(snap)
    except Exception as e:  # pragma: no cover
        logger.debug("provider get_option_chain_snapshot failed: %s", e)
    # Strategy 2: derive minimal chain using ATM + narrow range if fetch_option_chain present
    try:
        if hasattr(provider, 'fetch_option_chain'):
            # Attempt ATM discovery
            atm = 0.0
            if hasattr(provider, 'get_atm_strike'):
                try:
                    atm = float(provider.get_atm_strike())
                except Exception:
                    atm = 0.0
            width = max(atm * 0.1, 50) if atm > 0 else 100
            import datetime as _dt
            expiry = _dt.date.today() + _dt.timedelta(days=7)
            df = provider.fetch_option_chain('NIFTY', expiry, (atm-width, atm+width))  # type: ignore
            return _normalize_snapshot(df)
    except Exception as e:  # pragma: no cover
        logger.debug("provider fetch_option_chain snapshot path failed: %s", e)
    return None

def _normalize_snapshot(obj: Any) -> Iterable[ContractRow]:  # pragma: no cover - data shape normalization
    rows: list[ContractRow] = []
    try:
        if hasattr(obj, 'iterrows'):
            for _i, r in obj.iterrows():  # type: ignore[attr-defined]
                try:
                    strike = float(r.get('strike', 0))
                    underlying = float(r.get('underlying', 0) or r.get('spot', 0) or 0)
                    if underlying <= 0:
                        # attempt midpoint reconstruction from call/put OI/volume not feasible; keep 0 -> will map deep buckets
                        underlying = strike if strike > 0 else 100.0
                    mny_val = r.get('mny')
                    if mny_val is None:
                        mny_val = ((strike / underlying) - 1.0)
                    dte_days = r.get('dte_days')
                    if dte_days is None:
                        # expiry may exist as datetime/date
                        exp = r.get('expiry')
                        import datetime as _dt
                        if isinstance(exp, (_dt.date, _dt.datetime)):
                            # Use timezone-aware UTC date for determinism (replaces naive utcnow())
                            try:
                                # Use timezone-aware UTC (utcnow deprecated) – rely on datetime.UTC (py311+) fallback to timezone.utc
                                try:
                                    base_date = _dt.datetime.now(_dt.UTC).date()  # type: ignore[attr-defined]
                                except Exception:
                                    base_date = _dt.datetime.now(_dt.UTC).date()
                            except Exception:  # pragma: no cover - extreme fallback
                                base_date = _dt.date.today()
                            exp_date = exp.date() if isinstance(exp, _dt.datetime) else exp
                            dte_days = max((exp_date - base_date).days, 0)
                        else:
                            dte_days = 7
                    rows.append(ContractRow(
                        mny=float(mny_val),
                        dte=float(dte_days),
                        oi=float(r.get('oi', r.get('oi_call', 0)) or 0),
                        volume_24h=float(r.get('volume_24h', r.get('volume', 0)) or 0),
                        iv=float(r.get('iv', 0) or 0),
                        spread_bps=float(r.get('spread_bps', 0) or 0),
                    ))
                except Exception:
                    continue
            return rows
    except Exception:
        pass
    # Assume iterable of dicts
    try:
        for r in obj:
            try:
                strike = float(r.get('strike', 0))
                underlying = float(r.get('underlying', 0) or r.get('spot', 0) or strike or 100.0)
                mny_val = r.get('mny')
                if mny_val is None and underlying > 0:
                    mny_val = ((strike / underlying) - 1.0)
                dte_days = r.get('dte_days')
                if dte_days is None:
                    dte_days = 7
                rows.append(ContractRow(
                    mny=float(mny_val or 0),
                    dte=float(dte_days),
                    oi=float(r.get('oi', 0) or 0),
                    volume_24h=float(r.get('volume_24h', 0) or 0),
                    iv=float(r.get('iv', 0) or 0),
                    spread_bps=float(r.get('spread_bps', 0) or 0),
                ))
            except Exception:
                continue
        return rows
    except Exception:
        return []

def _fetch_contract_snapshot() -> Iterable[ContractRow]:  # fallback synthetic for testing & absence
    # Placeholder synthetic data; replace with real feed.
    sample = []
    spot = 100.0
    for _ in range(500):
        strike = random.uniform(50, 150)
        mny = (strike - spot) / spot
        dte = random.choice([0.5, 2, 10, 45, 120])
        sample.append(ContractRow(
            mny=mny,
            dte=dte,
            oi=random.uniform(10, 1000),
            volume_24h=random.uniform(5, 500),
            iv=random.uniform(0.1, 1.2),
            spread_bps=random.uniform(10, 400),
        ))
    return sample


def aggregate_once() -> None:
    if os.getenv("G6_OPTION_CHAIN_AGG_DISABLED", "0") in ("1", "true", "True"):
        return
    provider_rows = _provider_snapshot()
    if provider_rows is not None:
        rows = list(provider_rows)
        if not rows:  # fallback if provider returned empty
            rows = list(_fetch_contract_snapshot())
    else:
        rows = list(_fetch_contract_snapshot())
    # Accumulators keyed by (mny_bucket, dte_bucket)
    buckets: dict[tuple[str,str], dict[str, float]] = {}
    for r in rows:
        mny_b = _bucket_mny(r.mny)
        dte_b = _bucket_dte(r.dte)
        key = (mny_b, dte_b)
        acc = buckets.setdefault(key, {"contracts":0, "oi":0.0, "vol":0.0, "iv_sum":0.0, "spread_sum":0.0})
        acc["contracts"] += 1
        acc["oi"] += r.oi
        acc["vol"] += r.volume_24h
        acc["iv_sum"] += r.iv
        acc["spread_sum"] += r.spread_bps
    # Publish metrics
    for (mny_b, dte_b), acc in buckets.items():
        # Contracts active
        try:
            m.m_option_contracts_active_labels(mny_b, dte_b).set(acc["contracts"])  # type: ignore[attr-defined]
            m.m_option_open_interest_labels(mny_b, dte_b).set(acc["oi"])  # type: ignore[attr-defined]
            m.m_option_volume_24h_labels(mny_b, dte_b).set(acc["vol"])  # type: ignore[attr-defined]
            # Means
            if acc["contracts"] > 0:
                m.m_option_iv_mean_labels(mny_b, dte_b).set(acc["iv_sum"] / acc["contracts"])  # type: ignore[attr-defined]
                m.m_option_spread_bps_mean_labels(mny_b, dte_b).set(acc["spread_sum"] / acc["contracts"])  # type: ignore[attr-defined]
        except Exception:
            pass

__all__ = ["aggregate_once"]
