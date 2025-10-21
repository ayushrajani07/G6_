"""Collector pipeline abstraction (Phase 4.1 Action #2).

This module introduces a minimal, backward-compatible pipeline interface that
wraps the current monolithic logic in `unified_collectors` into composable
phases. The goal is *structural* – no behavior change – enabling future
injection of alternate processors, better unit testing, and per-phase metrics.

Activation: set environment variable `G6_PIPELINE_COLLECTOR=1` (integration to
be added in `run_cycle`).

Design Principles:
- Thin abstractions (avoid premature generalization)
- Pure data inputs/outputs; side-effects (persistence, metrics) isolated
- Graceful degradation if any phase raises (error propagation via Result flags)

Future Extensions (not implemented now):
- Parallel expiry processing (thread / async)
- Event bus hooks per phase
- Retry wrappers / circuit breakers per phase
- Structured per-expiry Result object persisted to diagnostics store
"""
from __future__ import annotations

import datetime
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol

from src.utils.expiry_service import build_expiry_service

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------------
# Data Contracts
# ----------------------------------------------------------------------------
@dataclass
class ExpiryWorkItem:
    index: str
    expiry_rule: str
    expiry_date: datetime.date | datetime.datetime | Any  # unresolved until resolve phase
    strikes: list[float]
    index_price: float
    atm_strike: float

@dataclass
class EnrichedExpiry:
    work: ExpiryWorkItem
    instruments: list[dict[str, Any]]
    enriched: dict[str, dict[str, Any]]

@dataclass
class PersistOutcome:
    option_count: int
    pcr: float | None
    failed: bool
    day_width: int | None = None
    snapshot_timestamp: datetime.datetime | None = None
    expiry_code: str | None = None  # mirrors metrics_payload['expiry_code'] from legacy path

# ----------------------------------------------------------------------------
# Phase Protocols
# ----------------------------------------------------------------------------
class ExpiryResolver(Protocol):
    def resolve(self, wi: ExpiryWorkItem) -> ExpiryWorkItem: ...

class InstrumentFetcher(Protocol):
    def fetch(self, wi: ExpiryWorkItem) -> list[dict[str, Any]]: ...

class QuoteEnricher(Protocol):
    def enrich(self, wi: ExpiryWorkItem, instruments: list[dict[str, Any]]) -> dict[str, dict[str, Any]]: ...

class AnalyticsBlock(Protocol):
    def apply(self, ee: EnrichedExpiry) -> None: ...

class PersistenceBlock(Protocol):
    def persist(self, ee: EnrichedExpiry) -> PersistOutcome: ...

# ----------------------------------------------------------------------------
# Default Adapters (bridge existing providers / sinks)
# ----------------------------------------------------------------------------
class ProvidersAdapter:
    """Adapter over the existing providers facade used in unified collectors."""
    def __init__(self, providers, metrics=None):
        self.providers = providers
        self.metrics = metrics

    def resolve(self, wi: ExpiryWorkItem) -> ExpiryWorkItem:  # ExpiryResolver
        expiry_date = self.providers.resolve_expiry(wi.index, wi.expiry_rule)
        wi.expiry_date = expiry_date
        # Optional deep trace for debugging (e.g. SENSEX monthly mismatch)
        try:
            import os
            if os.getenv('G6_TRACE_EXPIRY_PIPELINE','').lower() in ('1','true','yes','on'):
                logger.warning(
                    "TRACE_PIPELINE_RESOLVE index=%s rule=%s resolved=%s", wi.index, wi.expiry_rule, getattr(expiry_date,'isoformat',lambda:expiry_date)()
                )
        except Exception:
            pass
        return wi

    def fetch(self, wi: ExpiryWorkItem) -> list[dict[str, Any]]:  # InstrumentFetcher
        return self.providers.get_option_instruments(wi.index, wi.expiry_date, wi.strikes)

    def enrich(self, wi: ExpiryWorkItem, instruments: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:  # QuoteEnricher
        return self.providers.enrich_with_quotes(instruments)

class NoOpAnalytics(AnalyticsBlock):
    def apply(self, ee: EnrichedExpiry) -> None:  # pragma: no cover - trivial
        return None

class IVEstimationBlock(AnalyticsBlock):
    """Estimate IV for options lacking iv (lightweight subset of legacy logic)."""
    def __init__(self, greeks_calculator, risk_free_rate: float, max_iter: int = 100, iv_min: float = 0.01, iv_max: float = 5.0, precision: float = 1e-5):
        self.g = greeks_calculator
        self.r = risk_free_rate
        self.max_iter = max_iter
        self.iv_min = iv_min
        self.iv_max = iv_max
        self.precision = precision

    def apply(self, ee: EnrichedExpiry) -> None:  # pragma: no cover (covered indirectly)
        if not self.g:
            return
        spot = float(ee.work.index_price or 0)
        if spot <= 0:
            # best-effort: try provider ATM fallback later
            return
        for symbol, data in ee.enriched.items():
            try:
                if float(data.get('iv', 0)) > 0:
                    continue
                strike = float(data.get('strike') or data.get('strike_price') or 0)
                if strike <= 0:
                    continue
                market_price = float(data.get('last_price', 0))
                if market_price <= 0:
                    continue
                opt_type = (data.get('instrument_type') or data.get('type') or '').upper()
                is_call = opt_type == 'CE'
                iv_res = self.g.implied_volatility(
                    is_call=is_call, S=spot, K=strike, T=ee.work.expiry_date, market_price=market_price,
                    r=self.r, max_iterations=self.max_iter, precision=self.precision,
                    min_iv=self.iv_min, max_iv=self.iv_max, return_iterations=False
                )
                if isinstance(iv_res, (int,float)) and iv_res > 0:
                    if iv_res < self.iv_min: iv_res = self.iv_min
                    elif iv_res > self.iv_max: iv_res = self.iv_max
                    data['iv'] = iv_res
            except Exception:
                continue

class GreeksBlock(AnalyticsBlock):
    """Compute Greeks (delta, gamma, theta, vega, rho) if missing."""
    def __init__(self, greeks_calculator, risk_free_rate: float):
        self.g = greeks_calculator
        self.r = risk_free_rate

    def apply(self, ee: EnrichedExpiry) -> None:  # pragma: no cover
        if not self.g:
            return
        spot = float(ee.work.index_price or 0)
        if spot <= 0:
            return
        for symbol, data in ee.enriched.items():
            try:
                strike = float(data.get('strike') or data.get('strike_price') or 0)
                if strike <= 0:
                    continue
                opt_type = (data.get('instrument_type') or data.get('type') or '').upper()
                is_call = opt_type == 'CE'
                iv_raw = float(data.get('iv', 0))
                iv_fraction = iv_raw/100.0 if iv_raw > 1.5 else (iv_raw if iv_raw>0 else 0.25)
                if iv_fraction <= 0:
                    iv_fraction = 0.25
                greeks = self.g.black_scholes(is_call=is_call, S=spot, K=strike, T=ee.work.expiry_date, sigma=iv_fraction, r=self.r)
                for k_src,k_dst in [('delta','delta'),('gamma','gamma'),('theta','theta'),('vega','vega'),('rho','rho')]:
                    if float(data.get(k_dst,0)) == 0:
                        data[k_dst] = greeks.get(k_src,0)
                if float(data.get('iv',0)) == 0 and iv_fraction:
                    data['iv'] = iv_fraction
            except Exception:
                continue

class CsvPersistAdapter(PersistenceBlock):
    def __init__(self, csv_sink, influx_sink=None, metrics=None):
        self.csv = csv_sink
        self.influx = influx_sink
        self.metrics = metrics

    def persist(self, ee: EnrichedExpiry) -> PersistOutcome:
        try:
            metrics_payload = self.csv.write_options_data(
                ee.work.index,
                ee.work.expiry_date,
                ee.enriched,
                datetime.datetime.now(datetime.UTC),
                index_price=ee.work.index_price,
                index_ohlc={},
                suppress_overview=True,
                return_metrics=True,
                expiry_rule_tag=ee.work.expiry_rule,
            )
        except Exception as e:  # pragma: no cover (reuses upstream error handling eventually)
            logger.error("CSV persistence failed in pipeline: %s", e)
            return PersistOutcome(option_count=0, pcr=None, failed=True)
        # Optional influx write
        if self.influx:
            try:
                self.influx.write_options_data(
                    ee.work.index,
                    ee.work.expiry_date,
                    ee.enriched,
                    datetime.datetime.now(datetime.UTC),
                )
            except Exception as e:  # pragma: no cover
                logger.debug("Influx persistence failed in pipeline: %s", e)
        pcr = None
        day_width = None
        ts = None
        expiry_code = None
        try:
            if metrics_payload:
                pcr = metrics_payload.get("pcr")
                day_width = metrics_payload.get("day_width")
                ts = metrics_payload.get("timestamp")
                expiry_code = metrics_payload.get("expiry_code")
        except Exception:
            pass
        return PersistOutcome(option_count=len(ee.enriched), pcr=pcr, failed=False, day_width=day_width, snapshot_timestamp=ts, expiry_code=expiry_code)

# ----------------------------------------------------------------------------
# Pipeline Orchestrator
# ----------------------------------------------------------------------------
class CollectorPipeline:
    def __init__(
        self,
        resolver: ExpiryResolver,
        fetcher: InstrumentFetcher,
        enricher: QuoteEnricher,
        analytics: Iterable[AnalyticsBlock],
        persistence: PersistenceBlock,
    ) -> None:
        self.resolver = resolver
        self.fetcher = fetcher
        self.enricher = enricher
        self.analytics = list(analytics)
        self.persistence = persistence

    def run_expiry(self, wi: ExpiryWorkItem) -> tuple[EnrichedExpiry | None, PersistOutcome | None]:
        try:
            wi = self.resolver.resolve(wi)
            instruments = self.fetcher.fetch(wi)
            if not instruments:
                logger.warning("Pipeline: no instruments for %s %s", wi.index, wi.expiry_rule)
                return None, None
            enriched = self.enricher.enrich(wi, instruments)
            if not enriched:
                logger.warning("Pipeline: no enriched quotes for %s %s", wi.index, wi.expiry_rule)
                return None, None
            ee = EnrichedExpiry(work=wi, instruments=instruments, enriched=enriched)
            for block in self.analytics:
                try:
                    block.apply(ee)
                except Exception as ab:  # pragma: no cover
                    logger.debug("Analytics block failure: %s", ab)
            outcome = self.persistence.persist(ee)
            return ee, outcome
        except Exception as e:
            logger.error("Pipeline expiry failure %s %s: %s", wi.index, wi.expiry_rule, e)
            return None, None

# Convenience factory to bridge existing provider + csv sinks without analytics
# (analytics integration with IV/Greeks can be added incrementally later)
def build_default_pipeline(
    providers,
    csv_sink,
    influx_sink=None,
    metrics=None,
    compute_greeks: bool = False,
    estimate_iv: bool = False,
    risk_free_rate: float = 0.05,
    iv_max_iterations: int = 100,
    iv_min: float = 0.01,
    iv_max: float = 5.0,
    iv_precision: float = 1e-5,
) -> CollectorPipeline:
    adapter = ProvidersAdapter(providers, metrics=metrics)
    # Optional ExpiryService use (feature flagged)
    expiry_service = build_expiry_service()
    if expiry_service:
        class ServiceResolver:
            def resolve(self, wi: ExpiryWorkItem) -> ExpiryWorkItem:  # type: ignore
                try:
                    # Acquire candidate list from provider if available else fallback to adapter
                    cands = []
                    try:
                        if hasattr(providers, 'get_expiry_dates'):
                            cands = providers.get_expiry_dates(wi.index)
                    except Exception:  # pragma: no cover
                        cands = []
                    if not cands:
                        # fallback to provider resolution for this rule only
                        return adapter.resolve(wi)
                    wi.expiry_date = expiry_service.select(wi.expiry_rule, cands)
                    return wi
                except Exception:
                    return adapter.resolve(wi)
        resolver = ServiceResolver()
    else:
        resolver = adapter
    persist = CsvPersistAdapter(csv_sink, influx_sink=influx_sink, metrics=metrics)
    analytics: list[AnalyticsBlock] = []
    greeks_calculator = None
    if compute_greeks or estimate_iv:
        try:  # lazy import to avoid overhead when disabled
            from src.analytics.option_greeks import OptionGreeks  # type: ignore
            greeks_calculator = OptionGreeks(risk_free_rate=risk_free_rate)
        except Exception as e:  # pragma: no cover
            logger.debug("Greeks calculator init failed: %s", e)
            greeks_calculator = None
    if estimate_iv and greeks_calculator:
        analytics.append(IVEstimationBlock(greeks_calculator, risk_free_rate, max_iter=iv_max_iterations, iv_min=iv_min, iv_max=iv_max, precision=iv_precision))
    if compute_greeks and greeks_calculator:
        analytics.append(GreeksBlock(greeks_calculator, risk_free_rate))
    if not analytics:
        analytics.append(NoOpAnalytics())
    return CollectorPipeline(
        resolver=resolver,
        fetcher=adapter,
        enricher=adapter,
        analytics=analytics,
        persistence=persist,
    )
