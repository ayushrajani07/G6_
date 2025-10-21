"""Orchestrator startup sequence pipeline.

Implements ordered initialization / validation steps BEFORE the main loop:

1. Basic system check (python version, writable dirs, essential env)
2. Metrics & storage health (Prometheus metrics server reachable? Influx config sanity)
3. Kite auth validation (token freshness) with optional interactive refresh hook
4. Expiry resolution (build mapping for indices) using providers facade
5. Expiry matrix print (index x expiry_tag -> resolved date)
6. Market hours gating message (inside vs outside trading window)

Environment Behavior:
    This sequence is ALWAYS executed (no skip flags). Only `G6_FORCE_MARKET_OPEN=1` can
    alter market-hours messaging for testing.

Design Notes:
  - Non-fatal errors are logged; sequence continues unless a critical prerequisite
    (e.g., required directory not writable) fails.
  - Interactive token refresh is stubbed (prints guidance) to avoid blocking
    unattended runs; can be extended to open a browser / run a CLI auth helper.
"""
from __future__ import annotations

import logging
import os
import socket
import sys

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Step 1: Basic system check
# ---------------------------------------------------------------------------

def basic_system_check(ctx) -> bool:
    ok = True
    py_ver = sys.version.split()[0]
    logger.info("[startup] Python version=%s", py_ver)
    # Writable data directory (from config if available)
    data_dir = None
    try:
        if hasattr(ctx, 'config') and hasattr(ctx.config, 'data_dir'):
            data_dir = ctx.config.data_dir()
        else:
            data_dir = os.path.join('data','g6_data')
        os.makedirs(data_dir, exist_ok=True)
        test_file = os.path.join(data_dir, '.startup_write_test')
        with open(test_file, 'w') as f: f.write('ok')
        os.remove(test_file)
    except Exception as e:
        ok = False
        logger.error("[startup] Data directory not writable (%s): %s", data_dir, e)
    # Essential env (optional advisory list)
    for var in ['G6_VERSION','G6_GIT_COMMIT']:
        if os.getenv(var):
            logger.debug("[startup] env %s=%s", var, os.getenv(var))
    return ok

# ---------------------------------------------------------------------------
# Step 2: Metrics / storage health sanity
# ---------------------------------------------------------------------------

def metrics_and_storage_health(ctx) -> None:
    # Prometheus server reachability (best effort): attempt connect if host/port known
    try:
        m = getattr(ctx, 'config', None)
        if m and hasattr(m, 'raw'):
            host = m.raw.get('metrics',{}).get('host','127.0.0.1')
            port = int(m.raw.get('metrics',{}).get('port',9108))
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.3)
                if s.connect_ex((host, port)) == 0:
                    logger.info("[startup] metrics server reachable at %s:%s", host, port)
                else:
                    logger.warning("[startup] metrics server not reachable yet (%s:%s) — may still be starting", host, port)
    except Exception:
        logger.debug("[startup] metrics reachability probe failed", exc_info=True)
    # Influx configuration sanity (do NOT attempt auth here)
    try:
        raw = ctx.config.raw if hasattr(ctx.config,'raw') else {}
        influx_cfg = raw.get('influx', {}) or raw.get('storage',{}).get('influx',{})
        if influx_cfg.get('enable'):
            missing = [k for k in ['url','org','bucket','token'] if not influx_cfg.get(k)]
            if missing:
                logger.warning("[startup] Influx enabled but missing fields: %s", ','.join(missing))
            else:
                logger.info("[startup] Influx config present (bucket=%s)", influx_cfg.get('bucket'))
    except Exception:
        logger.debug("[startup] influx config probe failed", exc_info=True)

# ---------------------------------------------------------------------------
# Step 3: Kite auth validation (stub logic; extend with real SDK integration)
# ---------------------------------------------------------------------------

def kite_auth_validation(ctx) -> None:
    """Validate (and if needed refresh) Kite access token using token_manager helpers.

    Behavior:
      1. Attempt to load .env (best-effort; no hard dependency on python-dotenv)
      2. If API key/secret missing -> log advisory & return (non-fatal)
      3. If access token present & validates -> success log and return
      4. Else attempt automated browser-based acquisition (non-interactive fallback only)
      5. If still invalid -> advise user to run `python -m src.tools.token_manager`

    Non-blocking: we disable interactive/manual CLI prompts here to avoid
    orchestrator startup hanging in headless / service contexts. Users can run
    the token manager tool separately for guided/manual flows.
    """
    try:
        from src.tools import token_manager as tm  # local import; optional deps inside
    except Exception:
        logger.debug("[startup] token_manager module unavailable; skipping Kite auth validation", exc_info=True)
        return
    # Load .env if possible (logs internally)
    try:
        tm.load_env_vars()
    except Exception:  # pragma: no cover - defensive
        logger.debug("[startup] .env load attempt failed", exc_info=True)
    api_key = os.getenv("KITE_API_KEY")
    api_secret = os.getenv("KITE_API_SECRET")
    if not api_key or not api_secret:
        logger.info("[startup] Kite API key/secret not set (.env missing or incomplete); skipping auth validation")
        logger.info("[startup] Provide KITE_API_KEY & KITE_API_SECRET (see .env.example) for live collectors")
        return
    access_token = os.getenv("KITE_ACCESS_TOKEN")
    if access_token:
        try:
            if tm._kite_validate_token(api_key, access_token):  # internal helper adequate here
                logger.info("[startup] Existing Kite access token valid")
                return
            else:
                logger.warning("[startup] Existing Kite access token invalid; attempting automated refresh")
        except Exception:  # pragma: no cover
            logger.debug("[startup] Unexpected error during token validation; proceeding to refresh", exc_info=True)
    else:
        logger.info("[startup] No Kite access token present; attempting automated acquisition")
    # Attempt automated (browser) acquisition WITHOUT interactive manual prompts to avoid blocking
    try:
        acquired = tm.acquire_or_refresh_token(auto_open_browser=True, interactive=False, validate_after=True)
    except Exception as e:  # noqa: BLE001
        logger.debug("[startup] acquire_or_refresh_token raised; treating as failure: %s", e, exc_info=True)
        acquired = False
    if acquired:
        logger.info("[startup] Kite access token acquired/refreshed successfully")
    else:
        logger.warning("[startup] Automated Kite token acquisition failed or skipped (headless/manual needed)")
        logger.warning("[startup] Run: python -m src.tools.token_manager  (for guided refresh flows)")

# ---------------------------------------------------------------------------
# Step 4 + 5: Expiry resolution & matrix print
# ---------------------------------------------------------------------------

def resolve_expiries(ctx) -> dict[str, dict[str,str]]:
    """Build mapping index -> { expiry_tag: resolved_date } using provider raw expiries.

    New authoritative behavior (2025-09 refactor):
      * For logical rule tokens (this_week, next_week, this_month, next_month) call
        Providers.resolve_expiry so that ONLY the provider's raw list drives the
        mapping (no synthetic sequential placeholders).
      * Explicit ISO dates (YYYY-MM-DD) are passed through unchanged.
      * Any other token -> 'UNKNOWN'.

    Compatibility:
      * A legacy placeholder path can be forced via G6_STARTUP_LEGACY_PLACEHOLDERS=1
        (intended for temporary diff / regression comparison).
      * Previous env G6_EXPIRY_RULE_RESOLUTION is ignored here (rule engine removed);
        we log once if it is set to highlight deprecation.
    """
    mapping: dict[str, dict[str,str]] = {}
    index_params = getattr(ctx, 'index_params', None)
    if not index_params and hasattr(ctx, 'config') and hasattr(ctx.config, 'raw'):
        raw = ctx.config.raw
        index_params = raw.get('index_params') or raw.get('indices')
    if not isinstance(index_params, dict) or not index_params:
        logger.warning("[startup] No index_params available; cannot resolve expiries")
        return mapping

    providers = getattr(ctx, 'providers', None)
    if not providers:
        logger.warning("[startup] ctx.providers missing; cannot perform provider-based expiry resolution")
        return mapping

    legacy_mode = os.getenv('G6_STARTUP_LEGACY_PLACEHOLDERS','').lower() in {'1','true','yes','on'}
    if os.getenv('G6_EXPIRY_RULE_RESOLUTION'):
        logger.info("[startup] G6_EXPIRY_RULE_RESOLUTION env is deprecated; provider-based resolution always used")

    RULE_TAGS = {'this_week','next_week','this_month','next_month'}
    trace = os.getenv('G6_STARTUP_EXPIRY_TRACE','').lower() in {'1','true','yes','on'}

    # Optional: legacy placeholder function (only if explicitly requested)
    def _legacy_placeholder(tag: str):  # pragma: no cover - transitional
        from datetime import date, timedelta
        today = date.today()
        tag_offsets = {'this_week':0,'next_week':7,'this_month':2,'next_month':32}
        base = today + timedelta(days=tag_offsets[tag])
        while base.weekday() >= 5:
            base += timedelta(days=1)
        return base.isoformat()

    for index, cfg in index_params.items():
        tags = cfg.get('expiries') if isinstance(cfg, dict) else []
        row: dict[str,str] = {}
        # Trace raw provider expiries if requested (best effort)
        if trace:
            try:
                raw_list = None
                pp = getattr(providers, 'primary_provider', None)
                if pp and hasattr(pp, 'get_expiry_dates'):
                    raw_list = list(pp.get_expiry_dates(index))
                if raw_list:
                    logger.info("[startup] raw_expiries index=%s count=%d sample=%s", index, len(raw_list), raw_list[:8])
            except Exception:  # pragma: no cover - diagnostic only
                logger.debug("[startup] raw expiry trace failed for %s", index, exc_info=True)
        for tag in tags or []:
            iso: str
            if not isinstance(tag, str):
                row[str(tag)] = 'UNKNOWN'
                continue
            if len(tag) == 10 and tag[4] == '-' and tag[7] == '-':  # explicit ISO
                row[tag] = tag
                continue
            if tag in RULE_TAGS:
                if legacy_mode:
                    try:
                        row[tag] = _legacy_placeholder(tag)
                        continue
                    except Exception:
                        row[tag] = 'UNKNOWN'
                        continue
                try:
                    resolved = providers.resolve_expiry(index, tag)
                    # providers.resolve_expiry returns a date object
                    if hasattr(resolved, 'isoformat'):
                        iso = resolved.isoformat()
                    else:  # unexpected type; attempt string coercion
                        iso = str(resolved)
                    row[tag] = iso
                except Exception as e:  # noqa: BLE001
                    logger.warning("[startup] expiry resolution failed index=%s tag=%s err=%s", index, tag, e)
                    # Fallback: attempt legacy placeholder if available, else UNKNOWN
                    if not legacy_mode:
                        try:
                            row[tag] = _legacy_placeholder(tag)
                            continue
                        except Exception:
                            pass
                    row[tag] = 'UNKNOWN'
                continue
            # Unknown token category
            row[tag] = 'UNKNOWN'
        mapping[index] = row
    return mapping

def print_expiry_matrix(mapping: dict[str, dict[str,str]]) -> None:
    if not mapping:
        return
    # Compute column widths
    tags = sorted({t for rows in mapping.values() for t in rows.keys()})
    header = ['INDEX'] + tags
    col_w = {h: max(len(h), 10) for h in header}
    for idx, row in mapping.items():
        col_w['INDEX'] = max(col_w['INDEX'], len(idx))
        for t, v in row.items():
            col_w[t] = max(col_w.get(t,len(t)), len(v))
    def fmt_row(cells):
        return ' | '.join(str(c).ljust(col_w[h]) for c, h in zip(cells, header, strict=False))
    logger.info("[startup] Expiry Matrix:")
    logger.info(fmt_row(header))
    logger.info('-+-'.join('-'*col_w[h] for h in header))
    for idx in sorted(mapping.keys()):
        row = mapping[idx]
        logger.info(fmt_row([idx] + [row.get(t,'') for t in tags]))

# ---------------------------------------------------------------------------
# Step 6: Market hours gating
# ---------------------------------------------------------------------------

def market_hours_message(ctx) -> None:
    try:
        from src.utils.market_hours import is_market_open, seconds_until_market_open  # type: ignore
    except Exception:
        logger.debug("[startup] market hours helpers unavailable", exc_info=True)
        return
    force_open = os.getenv('G6_FORCE_MARKET_OPEN') in ('1','true','yes','on')
    if force_open:
        logger.info("[startup] Forcing inside market hours (G6_FORCE_MARKET_OPEN=1)")
        return
    try:
        if is_market_open():
            logger.info("[startup] Inside market hours; collectors will start")
        else:
            secs = seconds_until_market_open()
            if secs is not None and secs > 0:
                mins = int(secs // 60)
                logger.info("[startup] Market closed; next open in ~%d min (%d sec)", mins, int(secs))
            else:
                logger.info("[startup] Market closed; next open time unknown")
    except Exception:
        logger.debug("[startup] market hours probe failed", exc_info=True)

# ---------------------------------------------------------------------------
# Orchestrator entry integration
# ---------------------------------------------------------------------------

def run_startup_sequence(ctx) -> None:
    logger.info("[startup] Beginning startup sequence...")
    if not basic_system_check(ctx):
        logger.warning("[startup] Basic system check reported issues; continuing cautiously")
    metrics_and_storage_health(ctx)
    kite_auth_validation(ctx)
    mapping = resolve_expiries(ctx)
    print_expiry_matrix(mapping)
    market_hours_message(ctx)
    logger.info("[startup] Startup sequence complete")

__all__ = [
    'run_startup_sequence',
]
