#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unified collectors for G6 Platform.
"""

import logging
import datetime
import time
from typing import Dict, Any
import json
from src.logstream.formatter import format_index


# Add this before launching the subprocess
import sys  # retained for potential future CLI usage
from src.utils.market_hours import is_market_open, get_next_market_open
from src.utils.data_quality import DataQualityChecker
from src.utils.memory_pressure import MemoryPressureManager




logger = logging.getLogger(__name__)

def run_unified_collectors(index_params, providers, csv_sink, influx_sink, metrics=None, compute_greeks: bool = False, risk_free_rate: float = 0.05, estimate_iv: bool = False, iv_max_iterations: int | None = None, iv_min: float | None = None, iv_max: float | None = None, iv_precision: float | None = None):
    """Run unified collectors for all configured indices.

    Parameters
    ----------
    index_params : dict
        Configuration parameters for indices.
    providers : Providers
        Data providers facade.
    csv_sink : CsvSink
        CSV persistence layer.
    influx_sink : InfluxSink | None
        Influx persistence layer.
    metrics : Any
        Metrics registry or None.
    compute_greeks : bool
        Whether to compute greeks locally.
    risk_free_rate : float
        Annual risk-free rate used in pricing model.
    estimate_iv : bool
        Whether to attempt IV estimation prior to greek computation.
    iv_max_iterations / iv_min / iv_max : (future use)
        iv_max_iterations / iv_min / iv_max / iv_precision : (future use)
        Forthcoming IV solver tuning knobs; currently captured for forward compatibility.
    """
    # (iv_max_iterations, iv_min, iv_max) currently unused; integration handled in later task.
    # Mark cycle in-progress (dashboard can avoid reading partial gauges)
    if metrics and hasattr(metrics, 'collection_cycle_in_progress'):
        try:
            metrics.collection_cycle_in_progress.set(1)
        except Exception:
            pass
    # Track the collection timestamp
    start_cycle_wall = time.time()
    now = datetime.datetime.now()  # local-ok
    
    # Initialize data quality checker
    data_quality = DataQualityChecker()
    
    # Track the collection timestamp
    now = datetime.datetime.now()  # local-ok
    
    # Check if equity market is open
    if not is_market_open(market_type="equity", session_type="regular"):
        next_open = get_next_market_open(market_type="equity", session_type="regular")
        wait_time = (next_open - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
        logger.info("Equity market is closed. Next market open: %s (in %.1f minutes)", 
                    next_open, wait_time/60)
        # Clear in-progress if set
        if metrics and hasattr(metrics, 'collection_cycle_in_progress'):
            try:
                metrics.collection_cycle_in_progress.set(0)
            except Exception:
                pass
        return
    
    logger.info("Equity market is open, starting collection")
    
    # Initialize greeks calculator once if needed
    greeks_calculator = None
    if compute_greeks:
        try:
            from src.analytics.option_greeks import OptionGreeks  # type: ignore
            greeks_calculator = OptionGreeks(risk_free_rate=risk_free_rate)
            logger.info(f"Greek computation enabled (r={risk_free_rate})")
        except Exception as e:
            logger.error(f"Failed to initialize OptionGreeks: {e}")
            compute_greeks = False
    if estimate_iv and not compute_greeks:
        # Need calculator for IV even if greeks disabled
        try:
            from src.analytics.option_greeks import OptionGreeks  # type: ignore
            greeks_calculator = OptionGreeks(risk_free_rate=risk_free_rate)
            logger.info(f"IV estimation enabled (r={risk_free_rate})")
        except Exception as e:
            logger.error(f"Failed to initialize OptionGreeks for IV estimation: {e}")
            estimate_iv = False

    # Initialize memory pressure manager (lazy; safe if psutil missing)
    mp_manager = None
    try:
        mp_manager = MemoryPressureManager(metrics=metrics)
    except Exception:
        logger.debug("MemoryPressureManager init failed", exc_info=True)

    # Determine concise mode (reuse provider concise flag)
    concise_mode = False
    try:
        from src.broker.kite_provider import _CONCISE as _PROV_CONCISE  # type: ignore
        concise_mode = bool(_PROV_CONCISE)
    except Exception:
        pass

    human_blocks: list[str] = []
    overall_legs_total = 0
    overall_fail_total = 0
    if concise_mode:
        today_str = datetime.datetime.now().strftime('%d-%b-%Y')  # local-ok
        header = ("\n" + "=" * 70 + f"\n        DAILY OPTIONS COLLECTION LOG — {today_str}\n" + "=" * 70 + "\n")
        logger.info(header)

    # Process each index
    for index_symbol, params in index_params.items():
        # Skip disabled indices
        if not params.get('enable', True):
            continue
        
        if not concise_mode:
            logger.info(f"Collecting data for {index_symbol}")
        else:
            logger.debug(f"Collecting data for {index_symbol}")
        
        try:
            per_index_start = time.time()
            per_index_option_count = 0
            per_index_option_processing_seconds = 0.0
            per_index_success = True
            per_index_attempts = 0  # number of expiry collection attempts
            per_index_failures = 0  # number of failed expiry collections
            # Get index price and OHLC data (instrumented)
            index_price = 0
            index_ohlc = {}
            _t0 = time.time()
            try:
                index_price, index_ohlc = providers.get_index_data(index_symbol)
                if metrics and hasattr(metrics, 'mark_api_call'):
                    metrics.mark_api_call(success=True, latency_ms=(time.time()-_t0)*1000.0)
            except Exception:
                if metrics and hasattr(metrics, 'mark_api_call'):
                    metrics.mark_api_call(success=False, latency_ms=(time.time()-_t0)*1000.0)
                raise
            
            # Get ATM strike (instrumented)
            _t0 = time.time()
            atm_strike = providers.get_ltp(index_symbol)
            if metrics and hasattr(metrics, 'mark_api_call'):
                # Treat failures inside get_ltp already caught upstream; assume success if numeric
                success_flag = isinstance(atm_strike, (int,float)) and atm_strike > 0
                metrics.mark_api_call(success=success_flag, latency_ms=(time.time()-_t0)*1000.0)
            if not concise_mode:
                logger.info(f"{index_symbol} ATM strike: {atm_strike}")
            else:
                logger.debug(f"{index_symbol} ATM strike: {atm_strike}")
            
            # Update metrics if available
            if metrics:
                try:
                    metrics.index_price.labels(index=index_symbol).set(index_price)
                    metrics.index_atm.labels(index=index_symbol).set(atm_strike)
                except:
                    logger.debug(f"Failed to update metrics for {index_symbol}")
            
            # Prepare aggregation containers
            pcr_snapshot = {}
            representative_day_width = 0
            snapshot_base_time = datetime.datetime.now()  # local-ok
            expected_expiries = params.get('expiries', ['this_week'])

            # Evaluate memory pressure once per index (can inform strategy)
            effective_strikes_otm = params.get('strikes_otm', 10)
            effective_strikes_itm = params.get('strikes_itm', 10)
            allow_per_option_metrics = True
            local_compute_greeks = compute_greeks
            local_estimate_iv = estimate_iv
            if mp_manager:
                try:
                    mp_manager.evaluate()
                    # Scaling factor applied progressively (round down)
                    scale = mp_manager.depth_scale if hasattr(mp_manager, 'depth_scale') else 1.0
                    effective_strikes_otm = max(2, int(effective_strikes_otm * scale))
                    effective_strikes_itm = max(2, int(effective_strikes_itm * scale))
                    if mp_manager.should_skip_greeks():
                        local_compute_greeks = False
                        local_estimate_iv = False
                    if mp_manager.should_slow_cycles():
                        time.sleep(0.25)
                    if mp_manager.drop_per_option_metrics():
                        allow_per_option_metrics = False
                except Exception:
                    logger.debug("Memory pressure evaluation failed", exc_info=True)

            # Prepare human summary rows if concise
            # Time, Price, ATM, Expiry, Tag, Legs, CE, PE, PCR, Range, Step
            human_rows: list[tuple[str,str,str,str,str,str,str,str,str,str,str]] = []

            # Process each expiry
            for expiry_rule in params.get('expiries', ['this_week']):
                # Count an attempt up-front; refined logic could skip if index disabled mid-loop
                per_index_attempts += 1
                try:
                    # Resolve expiry date (instrumented)
                    _t_api = time.time()
                    expiry_date = providers.resolve_expiry(index_symbol, expiry_rule)
                    if metrics and hasattr(metrics, 'mark_api_call'):
                        metrics.mark_api_call(success=bool(expiry_date), latency_ms=(time.time()-_t_api)*1000.0)
                    if not concise_mode:
                        logger.info(f"{index_symbol} {expiry_rule} expiry resolved to: {expiry_date}")
                    else:
                        logger.debug(f"{index_symbol} {expiry_rule} expiry resolved to: {expiry_date}")
                    
                    # Calculate strikes to collect
                    strikes_otm = effective_strikes_otm
                    strikes_itm = effective_strikes_itm
                    
                    strike_step = 50.0  # Default step
                    if index_symbol in ['BANKNIFTY', 'SENSEX']:
                        strike_step = 100.0
                    
                    strikes = []
                    # Add ITM strikes
                    for i in range(1, strikes_itm + 1):
                        strikes.append(float(atm_strike - (i * strike_step)))
                    
                    # Add ATM strike
                    strikes.append(float(atm_strike))
                    
                    # Add OTM strikes
                    for i in range(1, strikes_otm + 1):
                        strikes.append(float(atm_strike + (i * strike_step)))
                    
                    # Sort strikes
                    strikes.sort()
                    
                    if not concise_mode:
                        logger.info(f"Collecting {len(strikes)} strikes for {index_symbol} {expiry_rule}: {strikes}")
                    else:
                        logger.debug(f"Collecting {len(strikes)} strikes for {index_symbol} {expiry_rule}")
                    
                    # Get option instruments (instrumented)
                    _t_api = time.time()
                    instruments = providers.get_option_instruments(index_symbol, expiry_date, strikes)
                    if metrics and hasattr(metrics, 'mark_api_call'):
                        metrics.mark_api_call(success=bool(instruments), latency_ms=(time.time()-_t_api)*1000.0)
                    
                    if not instruments:
                        logger.warning(f"No option instruments found for {index_symbol} expiry {expiry_date}")
                        continue
                    
                    # Enrich instruments with quote data (including avg_price) (instrumented)
                    enrich_start = time.time()
                    enriched_data = providers.enrich_with_quotes(instruments)
                    enrich_elapsed = time.time() - enrich_start
                    if metrics and hasattr(metrics, 'mark_api_call'):
                        metrics.mark_api_call(success=bool(enriched_data), latency_ms=enrich_elapsed*1000.0)
                    
                    if not enriched_data:
                        logger.warning(f"No quote data available for {index_symbol} expiry {expiry_date}")
                        continue

                    # --- Optional IV estimation (before greek computation) ---
                    if local_estimate_iv and greeks_calculator:
                        try:
                            spot = float(index_price)
                            # Solver tuning (defaults if None)
                            solver_max_iter = iv_max_iterations or 100
                            solver_min_iv = iv_min if iv_min is not None else 0.01
                            solver_max_iv = iv_max if iv_max is not None else 5.0
                            iv_success = iv_fail = total_iter = 0
                            solver_precision = iv_precision if iv_precision is not None else 1e-5
                            option_loop_start = time.time()
                            for symbol, data in enriched_data.items():
                                try:
                                    strike = float(data.get('strike') or data.get('strike_price') or 0)
                                    if strike <= 0 or spot <= 0:
                                        continue
                                    opt_type = (data.get('instrument_type') or data.get('type') or '').upper()
                                    is_call = opt_type == 'CE'
                                    # Use last traded price if available for IV inversion
                                    market_price = float(data.get('last_price', 0))
                                    if market_price <= 0:
                                        continue
                                    existing_iv = float(data.get('iv', 0))
                                    if existing_iv <= 0:
                                        iv_result = greeks_calculator.implied_volatility(
                                            is_call=is_call,
                                            S=spot,
                                            K=strike,
                                            T=expiry_date,
                                            market_price=market_price,
                                            r=risk_free_rate,
                                            max_iterations=solver_max_iter,
                                            precision=solver_precision,
                                            min_iv=solver_min_iv,
                                            max_iv=solver_max_iv,
                                            return_iterations=True
                                        )
                                        # Defensive: support legacy float return if refactor missed
                                        if isinstance(iv_result, tuple):
                                            iv_est, iters = iv_result
                                        else:  # pragma: no cover - safety net
                                            iv_est, iters = iv_result, 0
                                        if iv_est > 0:
                                            # Clamp again defensively
                                            if iv_est < solver_min_iv:
                                                iv_est = solver_min_iv
                                            elif iv_est > solver_max_iv:
                                                iv_est = solver_max_iv
                                            data['iv'] = iv_est
                                            iv_success += 1
                                        else:
                                            iv_fail += 1
                                        total_iter += iters
                                except Exception as iv_e:
                                    logger.debug(f"IV estimation failed for {symbol}: {iv_e}")
                            # Optionally could expose metrics here (future metrics task)
                            if metrics:
                                try:
                                    if hasattr(metrics, 'iv_success'):
                                        if iv_success:
                                            metrics.iv_success.labels(index=index_symbol, expiry=expiry_rule).inc(iv_success)
                                        if iv_fail:
                                            metrics.iv_fail.labels(index=index_symbol, expiry=expiry_rule).inc(iv_fail)
                                    if hasattr(metrics, 'iv_iterations') and (iv_success + iv_fail) > 0:
                                        avg_iter = total_iter / (iv_success + iv_fail)
                                        metrics.iv_iterations.labels(index=index_symbol, expiry=expiry_rule).set(avg_iter)
                                except Exception:
                                    logger.debug("Failed updating IV estimation metrics", exc_info=True)
                        except Exception as iv_batch_e:
                            logger.error(f"IV estimation batch failed for {index_symbol} {expiry_rule}: {iv_batch_e}")

                    # --- Optional Greek computation (fills iv, delta, gamma, theta, vega, rho if zero/missing) ---
                    if local_compute_greeks and greeks_calculator:
                        try:
                            spot = float(index_price)
                            # Time to expiry handled by OptionGreeks with date
                            greeks_start = time.time()
                            for symbol, data in enriched_data.items():
                                try:
                                    strike = float(data.get('strike') or data.get('strike_price') or 0)
                                    if strike <= 0 or spot <= 0:
                                        continue
                                    # Determine option type
                                    opt_type = data.get('instrument_type') or data.get('type') or ''
                                    is_call = opt_type.upper() == 'CE'
                                    # Use provided IV if >0 else fallback guess 0.25
                                    iv = float(data.get('iv', 0))
                                    if iv <= 0:
                                        iv = 0.25
                                    # Compute greeks
                                    g = greeks_calculator.black_scholes(
                                        is_call=is_call,
                                        S=spot,
                                        K=strike,
                                        T=expiry_date,
                                        sigma=iv,
                                        r=risk_free_rate
                                    )
                                    # Populate fields only if missing or zero
                                    for k_src, k_dst in [
                                        ('delta','delta'), ('gamma','gamma'), ('theta','theta'), ('vega','vega'), ('rho','rho')
                                    ]:
                                        if float(data.get(k_dst, 0)) == 0:
                                            data[k_dst] = g.get(k_src, 0)
                                    # Ensure iv stored (percent) consistent with existing convention (raw fraction OK)
                                    if float(data.get('iv', 0)) == 0 and iv:
                                        data['iv'] = iv
                                except Exception as oge:
                                    logger.debug(f"Greek calc failed for {symbol}: {oge}")
                            per_index_option_processing_seconds += (time.time() - greeks_start)
                        except Exception as gex:
                            logger.error(f"Greek computation batch failed for {index_symbol} {expiry_rule}: {gex}")
                    
                    # Write data to storage with the index price and OHLC
                    # Use the current timestamp when writing data
                    collection_time = datetime.datetime.now()  # local-ok
                    if not concise_mode:
                        logger.info(f"Writing {len(enriched_data)} records to CSV sink")
                    else:
                        logger.debug(f"Writing {len(enriched_data)} records to CSV sink")
                    metrics_payload = csv_sink.write_options_data(
                        index_symbol,
                        expiry_date,
                        enriched_data,
                        collection_time,
                        index_price=index_price,
                        index_ohlc=index_ohlc,
                        suppress_overview=True,
                        return_metrics=True
                    )

                    # Capture PCR for aggregated snapshot
                    try:
                        if metrics_payload:
                            pcr_snapshot[metrics_payload['expiry_code']] = metrics_payload['pcr']
                            # Preference: last day_width if non-zero, else keep previous
                            if metrics_payload.get('day_width', 0):
                                representative_day_width = metrics_payload['day_width']
                            # Use earliest collection_time for consistent rounding window
                            if metrics_payload.get('timestamp') and metrics_payload['timestamp'] < snapshot_base_time:
                                snapshot_base_time = metrics_payload['timestamp']
                    except Exception as agg_e:
                        logger.debug(f"Aggregation capture failed for {index_symbol} {expiry_rule}: {agg_e}")
                    
                    # Write to InfluxDB if enabled
                    if influx_sink:
                        influx_sink.write_options_data(
                            index_symbol, 
                            expiry_date,
                            enriched_data,
                            collection_time
                        )
                    
                    # Update metrics
                    if metrics:
                        try:
                            # Count options collected
                            metrics.options_collected.labels(index=index_symbol, expiry=expiry_rule).set(len(enriched_data))
                            per_index_option_count += len(enriched_data)
                            # Increment global processed counter
                            metrics.options_processed_total.inc(len(enriched_data))
                            # Increment per-index cumulative counter
                            try:
                                metrics.index_options_processed_total.labels(index=index_symbol).inc(len(enriched_data))
                            except Exception:
                                pass
                        except Exception:
                            logger.debug(f"Failed options_collected metric for {index_symbol}")
                        try:
                            # Update PCR (Put-Call Ratio)
                            call_oi = sum(float(data.get('oi', 0)) for data in enriched_data.values() if data.get('instrument_type') == 'CE')
                            put_oi = sum(float(data.get('oi', 0)) for data in enriched_data.values() if data.get('instrument_type') == 'PE')
                            pcr = put_oi / call_oi if call_oi > 0 else 0
                            metrics.pcr.labels(index=index_symbol, expiry=expiry_rule).set(pcr)
                        except Exception:
                            logger.debug(f"Failed PCR metric for {index_symbol}")
                        try:
                            # Per-option metrics (price, volume, OI, IV & Greeks)
                            for symbol, data in enriched_data.items():
                                strike_val = data.get('strike') or data.get('strike_price') or 0
                                opt_type = (data.get('instrument_type') or data.get('type') or '').upper()
                                if strike_val and opt_type in ('CE','PE'):
                                    if not allow_per_option_metrics:
                                        continue
                                    metrics.option_price.labels(index=index_symbol, expiry=expiry_rule, strike=str(strike_val), type=opt_type).set(float(data.get('last_price', 0) or 0))
                                    metrics.option_volume.labels(index=index_symbol, expiry=expiry_rule, strike=str(strike_val), type=opt_type).set(float(data.get('volume', 0) or 0))
                                    metrics.option_oi.labels(index=index_symbol, expiry=expiry_rule, strike=str(strike_val), type=opt_type).set(float(data.get('oi', 0) or 0))
                                    metrics.option_iv.labels(index=index_symbol, expiry=expiry_rule, strike=str(strike_val), type=opt_type).set(float(data.get('iv', 0) or 0))
                                    # Greeks only if present (avoid zeros misuse)
                                    if 'delta' in data:
                                        metrics.option_delta.labels(index=index_symbol, expiry=expiry_rule, strike=str(strike_val), type=opt_type).set(float(data.get('delta') or 0))
                                    if 'gamma' in data:
                                        metrics.option_gamma.labels(index=index_symbol, expiry=expiry_rule, strike=str(strike_val), type=opt_type).set(float(data.get('gamma') or 0))
                                    if 'theta' in data:
                                        metrics.option_theta.labels(index=index_symbol, expiry=expiry_rule, strike=str(strike_val), type=opt_type).set(float(data.get('theta') or 0))
                                    if 'vega' in data:
                                        metrics.option_vega.labels(index=index_symbol, expiry=expiry_rule, strike=str(strike_val), type=opt_type).set(float(data.get('vega') or 0))
                                    if 'rho' in data:
                                        metrics.option_rho.labels(index=index_symbol, expiry=expiry_rule, strike=str(strike_val), type=opt_type).set(float(data.get('rho') or 0))
                        except Exception:
                            logger.debug(f"Failed per-option metrics for {index_symbol}", exc_info=True)
                    
                    # Log success
                    if not concise_mode:
                        logger.info(f"Successfully collected {len(enriched_data)} options for {index_symbol} {expiry_rule}")
                    else:
                        logger.debug(f"Collected {len(enriched_data)} options for {index_symbol} {expiry_rule}")
                    # Capture human row if concise
                    if concise_mode:
                        ts_local = datetime.datetime.now().strftime('%H:%M')  # local-ok
                        price_disp = f"{index_price:.2f}" if isinstance(index_price,(int,float)) else "-"
                        atm_disp = f"{int(atm_strike)}" if isinstance(atm_strike,(int,float)) else "-"
                        legs = len(enriched_data)
                        # CE / PE counts
                        ce_count = sum(1 for d in enriched_data.values() if (d.get('instrument_type') or d.get('type') or '').upper() == 'CE')
                        pe_count = sum(1 for d in enriched_data.values() if (d.get('instrument_type') or d.get('type') or '').upper() == 'PE')
                        # PCR (OI based) fallback to count ratio if OI missing
                        call_oi = sum(float(d.get('oi', 0)) for d in enriched_data.values() if (d.get('instrument_type') or d.get('type') or '').upper() == 'CE')
                        put_oi = sum(float(d.get('oi', 0)) for d in enriched_data.values() if (d.get('instrument_type') or d.get('type') or '').upper() == 'PE')
                        pcr_val = (put_oi / call_oi) if call_oi > 0 else (pe_count / ce_count if ce_count > 0 else 0)
                        if strikes:
                            rng_min = int(min(strikes)); rng_max = int(max(strikes))
                            diffs_f = [int(b-a) for a,b in zip(strikes, strikes[1:]) if b>a]
                            step_val = min(diffs_f) if diffs_f else 0
                            rng_disp = f"{rng_min}\u2013{rng_max}"  # en dash
                        else:
                            rng_disp = "-"; step_val = 0
                        tag_map = {'this_week':'This week','next_week':'Next week','this_month':'This month','next_month':'Next month'}
                        tag = tag_map.get(expiry_rule, expiry_rule) or "-"
                        human_rows.append((ts_local, price_disp, atm_disp, str(expiry_date), str(tag), str(legs), str(ce_count), str(pe_count), f"{pcr_val:.2f}", rng_disp, str(step_val)))
                    
                except Exception as e:
                    logger.error(f"Error collecting data for {index_symbol} {expiry_rule}: {e}")
                    per_index_success = False
                    per_index_failures += 1
                    if metrics:
                        try:
                            metrics.collection_errors.labels(index=index_symbol, error_type='expiry_collection').inc()
                            metrics.total_errors.inc()
                            metrics.data_errors.inc()
                        except Exception:
                            logger.debug("Failed to increment collection errors metric")
            
            # After processing all expiries for this index, write one aggregated overview snapshot
            try:
                if pcr_snapshot:
                    csv_sink.write_overview_snapshot(index_symbol, pcr_snapshot, snapshot_base_time, representative_day_width, expected_expiries=expected_expiries)
                    if influx_sink:
                        try:
                            influx_sink.write_overview_snapshot(index_symbol, pcr_snapshot, snapshot_base_time, representative_day_width, expected_expiries=expected_expiries)
                        except Exception as ie:
                            logger.debug(f"Influx overview snapshot failed for {index_symbol}: {ie}")
            except Exception as snap_e:
                logger.error(f"Failed to write aggregated overview snapshot for {index_symbol}: {snap_e}")

            # Per-index aggregate metrics + structured stream log
            if metrics:
                try:
                    elapsed_index = time.time() - per_index_start
                    if per_index_option_count > 0:
                        metrics.index_options_processed.labels(index=index_symbol).set(per_index_option_count)
                        metrics.index_avg_processing_time.labels(index=index_symbol).set(per_index_option_processing_seconds / max(per_index_option_count,1))
                        # Populate internal per-index last cycle options map for runtime status file
                        try:
                            if hasattr(metrics, '_per_index_last_cycle_options'):
                                metrics._per_index_last_cycle_options[index_symbol] = per_index_option_count
                        except Exception:
                            pass
                    else:
                        # Soft failure condition: zero options gathered across all expiries counted as failure increment for visibility
                        try:
                            metrics.collection_errors.labels(index=index_symbol, error_type='no_options').inc()
                        except Exception:
                            pass
                    metrics.index_last_collection_unixtime.labels(index=index_symbol).set(int(time.time()))
                    metrics.index_current_atm.labels(index=index_symbol).set(float(atm_strike))
                    # Principled per-cycle success using attempts/failures
                    try:
                        metrics.mark_index_cycle(index=index_symbol, attempts=per_index_attempts, failures=per_index_failures)
                    except Exception:
                        # fallback legacy behavior
                        rate = 100.0 if per_index_success else 0.0
                        metrics.index_success_rate.labels(index=index_symbol).set(rate)
                except Exception:
                    logger.debug(f"Failed index aggregate metrics for {index_symbol}")
            try:
                last_age = 0.0  # we just collected
                pcr_val = None
                try:
                    if pcr_snapshot:
                        # choose deterministic first key
                        first_key = sorted(pcr_snapshot.keys())[0]
                        pcr_val = pcr_snapshot[first_key]
                except Exception:
                    pass
                status = 'ok' if per_index_option_count > 0 and per_index_failures == 0 else 'warn' if per_index_option_count > 0 else 'bad'
                line = format_index(
                    index=index_symbol,
                    legs=per_index_option_count,
                    legs_avg=None,
                    legs_cum=None,
                    succ_pct=None,  # cycle success emitted only after mark_index_cycle; could enrich later
                    succ_avg_pct=None,
                    attempts=per_index_attempts,
                    failures=per_index_failures,
                    last_age_s=last_age,
                    pcr=pcr_val,
                    atm=atm_strike if isinstance(atm_strike,(int,float)) else None,
                    err=None if per_index_failures==0 else 'fail',
                    status=status
                )
                if concise_mode:
                    logger.debug(line)
                else:
                    logger.info(line)
                if concise_mode:
                    block_lines = [
                        "-------------------------",
                        f"INDEX: {index_symbol}",
                        "-------------------------",
                        # Aligned header with added columns
                        "Time   Price     ATM   Expiry      Tag         Legs  CE   PE   PCR   Range          Step",
                        "-------------------------------------------------------------------------------",
                    ]
                    for (t, price_disp, atm_disp, exp_str, tag, legs, ce_c, pe_c, pcr_v, rng_disp, step_v) in human_rows:
                        block_lines.append(f"{t:<6} {price_disp:>8} {atm_disp:>6} {exp_str:<11} {tag:<11} {legs:>4} {ce_c:>3} {pe_c:>3} {pcr_v:>5} {rng_disp:<14} {step_v:>4}")
                    block_lines.append("-------------------------------------------------------------------------------")
                    block_lines.append(f"{index_symbol} TOTAL LEGS: {per_index_option_count} | FAILS: {per_index_failures} | STATUS: {status.upper()}")
                    human_blocks.append("\n".join(block_lines))
                    overall_legs_total += per_index_option_count
                    overall_fail_total += per_index_failures
            except Exception:
                logger.debug("Failed to emit index stream line", exc_info=True)
        except Exception as e:
            logger.error(f"Error processing index {index_symbol}: {e}")
    
    # Update collection time metrics
    total_elapsed = time.time() - start_cycle_wall  # define early for logging fallback
    if metrics:
        try:
            collection_time = (datetime.datetime.now() - now).total_seconds()  # local-ok
            metrics.collection_duration.observe(collection_time)
            metrics.collection_cycles.inc()
            # Derived helper method marks cycle; supply per-option timing aggregate (sum across indices)
            try:
                metrics.mark_cycle(success=True, cycle_seconds=total_elapsed, options_processed=metrics._last_cycle_options or 0, option_processing_seconds=metrics._last_cycle_option_seconds or 0.0)
            except Exception:
                # Fallback to direct gauges if helper fails
                metrics.avg_cycle_time.set(total_elapsed)
                if total_elapsed > 0:
                    metrics.cycles_per_hour.set(3600.0 / total_elapsed)
            # Clear in-progress flag
            if hasattr(metrics, 'collection_cycle_in_progress'):
                try:
                    metrics.collection_cycle_in_progress.set(0)
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Failed to update collection metrics: {e}")
    # Emit accumulated human summary before structured cycle line
    if concise_mode and human_blocks:
        try:
            for blk in human_blocks:
                logger.info("\n" + blk)
            footer = ("\n" + "=" * 70 + f"\nALL INDICES TOTAL LEGS: {overall_legs_total}   |   FAILS: {overall_fail_total}   |   SYSTEM STATUS: {'GREEN' if overall_fail_total==0 else 'DEGRADED'}\n" + "=" * 70)
            logger.info(footer)
        except Exception:
            logger.debug("Failed to emit human summary footer", exc_info=True)

    # Emit cycle line(s) with new mode control: G6_CYCLE_OUTPUT={pretty|raw|both}
    # Precedence rules:
    # 1. If legacy G6_DISABLE_PRETTY_CYCLE is truthy -> force 'raw'
    # 2. Else use G6_CYCLE_OUTPUT value (default 'pretty')
    # 3. Values: 'pretty' => only human table (header+row) line(s); 'raw' => only machine CYCLE line; 'both' => both.
    try:
        from src.logstream.formatter import format_cycle, format_cycle_pretty, format_cycle_table
        import os as _os_env
        legacy_disable = _os_env.environ.get('G6_DISABLE_PRETTY_CYCLE', '0').lower() in ('1','true','yes','on')
        mode = 'raw' if legacy_disable else _os_env.environ.get('G6_CYCLE_OUTPUT', 'pretty').strip().lower()
        if mode not in ('pretty','raw','both'):
            mode = 'pretty'

        opts_total = getattr(metrics, '_last_cycle_options', 0) if metrics else 0
        opts_per_min = None
        coll_succ = None
        api_succ = None
        api_ms = None
        cpu = None; mem_mb = None
        if metrics:
            try:
                coll_succ = metrics.collection_success_rate._value.get()  # type: ignore
            except Exception:
                pass
            try:
                api_succ = metrics.api_success_rate._value.get()  # type: ignore
            except Exception:
                pass
            try:
                api_ms = metrics.api_response_time._value.get()  # type: ignore
            except Exception:
                pass
            try:
                cpu = metrics.cpu_usage_percent._value.get()  # type: ignore
                mem_mb = metrics.memory_usage_mb._value.get()  # type: ignore
            except Exception:
                pass
            try:
                opts_per_min = metrics.options_per_minute._value.get()  # type: ignore
            except Exception:
                pass

        # Build both representations lazily
        raw_line = None
        pretty_line = None
        if mode in ('raw','both'):
            try:
                raw_line = format_cycle(
                    duration_s=total_elapsed,
                    options=opts_total or 0,
                    options_per_min=opts_per_min,
                    cpu=cpu,
                    mem_mb=mem_mb,
                    api_latency_ms=api_ms,
                    api_success_pct=api_succ,
                    collection_success_pct=coll_succ,
                    indices=len(index_params or {}),
                    stall_flag=None
                )
            except Exception:
                logger.debug("Failed to format raw cycle line", exc_info=True)
        if mode in ('pretty','both') and not legacy_disable:
            try:
                header_line, value_line = format_cycle_table(
                    duration_s=total_elapsed,
                    options=opts_total or 0,
                    options_per_min=opts_per_min,
                    cpu=cpu,
                    mem_mb=mem_mb,
                    api_latency_ms=api_ms,
                    api_success_pct=api_succ,
                    collection_success_pct=coll_succ,
                    indices=len(index_params or {}),
                    stall_flag=None
                )
                # For now log both header and value every cycle; future: track last header to avoid repetition.
                pretty_line = f"{header_line}\n{value_line}"
            except Exception:
                logger.debug("Failed to format pretty cycle table", exc_info=True)

        # Emit in deterministic order: raw then pretty if both
        try:
            if raw_line:
                logger.info(raw_line)
        except Exception:
            logger.debug("Failed to emit raw cycle line", exc_info=True)
        try:
            if pretty_line:
                logger.info(pretty_line)
        except Exception:
            logger.debug("Failed to emit pretty cycle summary", exc_info=True)
    except Exception:
        logger.debug("Failed to emit cycle line(s)", exc_info=True)