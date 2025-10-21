from __future__ import annotations

import asyncio
import csv
import os
import pathlib
import time
import zlib
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.error_handling import ErrorCategory, ErrorSeverity, get_error_handler
from src.types.dashboard_types import (
    MemorySnapshot,
    UnifiedIndicesResponse,
    UnifiedSourceProtocol,
    UnifiedSourceStatusResponse,
    UnifiedStatusResponse,
)

from .metrics_cache import MetricsCache


def _load_unified_source() -> UnifiedSourceProtocol | None:
    """Attempt to import unified data source, return None if unavailable.

    Uses a runtime import guarded by broad exception handling so the dashboard
    can operate (with reduced feature set) when the unified source module or
    its dependencies are absent.
    """
    try:  # runtime import isolation
        from src.data_access.unified_source import data_source as ds  # local import; optional module
        # Cast to protocol for typed downstream usage
        return cast(UnifiedSourceProtocol, ds)
    except Exception as e:  # pragma: no cover - optional path
        get_error_handler().handle_error(
            e,
            category=ErrorCategory.CONFIGURATION,
            severity=ErrorSeverity.LOW,
            component="web.dashboard.app",
            function_name="module_import",
            message="Unified data source import failed (optional)",
            should_log=False,
        )
        return None

_unified: UnifiedSourceProtocol | None = _load_unified_source()

LOG_PATH = os.environ.get("G6_LOG_FILE", "logs/g6_platform.log")

METRICS_ENDPOINT = os.environ.get("G6_METRICS_ENDPOINT", "http://localhost:9108/metrics")
DEBUG_MODE = os.environ.get('G6_DASHBOARD_DEBUG') == '1'
# Template refresh cadence (env-driven)
CORE_REFRESH = int(os.environ.get('G6_DASHBOARD_CORE_REFRESH_SEC', '6'))
SECONDARY_REFRESH = int(os.environ.get('G6_DASHBOARD_SECONDARY_REFRESH_SEC', '12'))
# Align metrics cache polling with core refresh cadence to reduce staleness/flicker
cache = MetricsCache(METRICS_ENDPOINT, interval=float(max(1, CORE_REFRESH)), timeout=1.5)

# In-process CSV cache: path -> (mtime_ns, rows_full)
# rows_full contain parsed fields (ts, tp/avg_tp, ce/pe, index_price, ivs, greeks) so we can slice/trim per request
_CSV_CACHE: dict[Path, tuple[int, list[dict[str, Any]]]] = {}

def _load_csv_rows_full(path: Path) -> list[dict[str, Any]]:
    try:
        st = path.stat()
        mtime_ns = int(getattr(st, 'st_mtime_ns', int(st.st_mtime * 1e9)))
    except Exception:
        mtime_ns = 0
    cached = _CSV_CACHE.get(path)
    if cached and cached[0] == mtime_ns:
        return cached[1]
    rows: list[dict[str, Any]] = []
    try:
        with path.open('r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            fns = list(reader.fieldnames or [])
            have_ce = 'ce' in fns; have_pe = 'pe' in fns
            have_idx = 'index_price' in fns
            have_iv = ('ce_iv' in fns) or ('pe_iv' in fns)
            have_greeks = any(c in fns for c in (
                'ce_delta','pe_delta','ce_theta','pe_theta','ce_vega','pe_vega','ce_gamma','pe_gamma','ce_rho','pe_rho'
            ))
            for r in reader:
                ts_s = _parse_time_any(str(r.get('timestamp', '')).strip())
                ts_ms = _parse_time_epoch_ms(str(r.get('timestamp', '')).strip())
                obj: dict[str, Any] = {'time': ts_ms, 'ts': ts_ms, 'time_str': ts_s}
                for col in ('tp','avg_tp'):
                    val = r.get(col)
                    if val is None or val == '':
                        obj[col] = None
                    else:
                        try:
                            obj[col] = float(val)
                        except Exception:
                            obj[col] = None
                if have_ce:
                    try:
                        obj['ce'] = float(str(r.get('ce')))
                    except Exception:
                        obj['ce'] = None
                if have_pe:
                    try:
                        obj['pe'] = float(str(r.get('pe')))
                    except Exception:
                        obj['pe'] = None
                if have_idx:
                    try:
                        obj['index_price'] = float(str(r.get('index_price')))
                    except Exception:
                        obj['index_price'] = None
                if have_iv:
                    for col in ('ce_iv','pe_iv'):
                        v = r.get(col)
                        if v is None or v == '': obj[col] = None
                        else:
                            try: obj[col] = float(str(v))
                            except Exception: obj[col] = None
                if have_greeks:
                    for col in ('ce_delta','pe_delta','ce_theta','pe_theta','ce_vega','pe_vega','ce_gamma','pe_gamma','ce_rho','pe_rho'):
                        v = r.get(col)
                        if v is None or v == '': obj[col] = None
                        else:
                            try: obj[col] = float(str(v))
                            except Exception: obj[col] = None
                rows.append(obj)
        # Sort once and cache
        try:
            def _ts_key_val(rv: Any) -> int:
                try:
                    if rv is None:
                        return -1
                    return int(rv)
                except Exception:
                    return -1
            rows.sort(key=lambda r: _ts_key_val(r.get('ts')))
        except Exception:
            # Defensive: ignore sort errors
            pass
    except Exception:
        rows = []
    _CSV_CACHE[path] = (mtime_ns, rows)
    return rows


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Startup
    try:
        cache.start()
    except Exception as e:
        get_error_handler().handle_error(
            e,
            category=ErrorCategory.RESOURCE,
            severity=ErrorSeverity.LOW,
            component="web.dashboard.app",
            function_name="lifespan_start",
            message="Failed to start metrics cache",
            should_log=False,
        )
    yield
    # Shutdown
    try:
        cache.stop()
    except Exception as e:
        get_error_handler().handle_error(
            e,
            category=ErrorCategory.RESOURCE,
            severity=ErrorSeverity.LOW,
            component="web.dashboard.app",
            function_name="lifespan_stop",
            message="Failed to stop metrics cache",
            should_log=False,
        )


app = FastAPI(title="G6 Dashboard", version="0.1.0", lifespan=lifespan)

# Compression for JSON payloads (saves bandwidth and speeds Grafana Infinity)
try:
    app.add_middleware(GZipMiddleware, minimum_size=1024)
except Exception:
    # Defensive: if middleware import fails in minimal envs, continue without gzip
    pass

# Back-pressure: limit concurrent requests to expensive endpoints
_MAX_CONCURRENCY = int(os.environ.get("G6_LIVE_API_MAX_CONCURRENCY", "4"))
_SEM = asyncio.Semaphore(max(1, _MAX_CONCURRENCY))

# Lightweight observability
_OBS: dict[str, Any] = {
    "live_csv": {"count": 0, "errors": 0, "too_many": 0, "dur_ms_sum": 0.0, "dur_ms_max": 0.0, "in_flight": 0},
    "overlay": {"count": 0, "errors": 0, "too_many": 0, "dur_ms_sum": 0.0, "dur_ms_max": 0.0, "in_flight": 0},
}

def _obs_begin(kind: str) -> float:
    try:
        _OBS[kind]["count"] += 1
        _OBS[kind]["in_flight"] += 1
    except Exception:
        pass
    return time.perf_counter()

def _obs_end(kind: str, t0: float, *, ok: bool) -> None:
    try:
        dt_ms = (time.perf_counter() - t0) * 1000.0
        _OBS[kind]["dur_ms_sum"] += dt_ms
        if dt_ms > _OBS[kind]["dur_ms_max"]:
            _OBS[kind]["dur_ms_max"] = dt_ms
        if not ok:
            _OBS[kind]["errors"] += 1
    except Exception:
        pass
    finally:
        try:
            _OBS[kind]["in_flight"] = max(0, int(_OBS[kind]["in_flight"]) - 1)
        except Exception:
            pass

def _obs_too_many(kind: str) -> None:
    try:
        _OBS[kind]["too_many"] += 1
    except Exception:
        pass

templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), 'templates'))
app.mount('/static', StaticFiles(directory=os.path.join(os.path.dirname(__file__), 'static')), name='static')

# startup handled by lifespan above

# --------------------------- Global Exception Handlers ---------------------------
def _wants_html(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "text/html" in accept and "application/json" not in accept

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse | HTMLResponse:
    # Only route 5xx to central handler to avoid noise for expected 4xx
    if exc.status_code >= 500:
        get_error_handler().handle_error(
            exception=exc,
            category=ErrorCategory.RENDERING if _wants_html(request) else ErrorCategory.CONFIGURATION,
            severity=ErrorSeverity.MEDIUM,
            component="web.dashboard.app",
            function_name=str(request.url.path),
            message=f"HTTPException {exc.status_code}",
            should_log=False,
        )
    if _wants_html(request):
        html = f"<h3>Error {exc.status_code}</h3><p>{exc.detail}</p>"
        return HTMLResponse(html, status_code=exc.status_code)
    return JSONResponse({"error": str(exc.detail), "status_code": exc.status_code}, status_code=exc.status_code)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse | HTMLResponse:
    get_error_handler().handle_error(
        exception=exc,
        category=ErrorCategory.DATA_VALIDATION,
        severity=ErrorSeverity.LOW,
        component="web.dashboard.app",
        function_name=str(request.url.path),
        message="Request validation failed",
        should_log=False,
    )
    if _wants_html(request):
        return HTMLResponse("<h3>422 Unprocessable Entity</h3><p>Invalid request.</p>", status_code=422)
    return JSONResponse({"error": "validation_failed", "detail": exc.errors()}, status_code=422)

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse | HTMLResponse:
    get_error_handler().handle_error(
        exception=exc,
        category=ErrorCategory.RENDERING if _wants_html(request) else ErrorCategory.CONFIGURATION,
        severity=ErrorSeverity.HIGH,
        component="web.dashboard.app",
        function_name=str(request.url.path),
        message="Unhandled server error",
        should_log=False,
    )
    if _wants_html(request):
        return HTMLResponse("<h3>500 Internal Server Error</h3><p>Please try again later.</p>", status_code=500)
    return JSONResponse({"error": "internal_error"}, status_code=500)

@app.get('/health')
async def health() -> Mapping[str, Any]:
    snap = cache.snapshot()
    status = 'stale' if (snap and snap.stale) else 'ok'
    return {"status": status, "age": snap.age_seconds if snap else None}

@app.get('/metrics/json')
async def metrics_json() -> JSONResponse:
    snap = cache.snapshot()
    if not snap:
        return JSONResponse({"error": "no data yet"}, status_code=503)
    m = snap.raw
    def first(name: str, default: float | None = None) -> float | None:
        samples = m.get(name)
        if not samples:
            return default
        return samples[0].value
    # Build per-index aggregates
    indices: dict[str, dict[str, Any]] = {}
    for metric, samples in m.items():
        if metric == 'g6_index_options_processed':
            for s in samples:
                idx = s.labels.get('index')
                if not idx: continue
                indices.setdefault(idx, {}).setdefault('options_processed', s.value)
        elif metric == 'g6_index_last_collection_unixtime':
            for s in samples:
                idx = s.labels.get('index')
                if not idx: continue
                indices.setdefault(idx, {}).setdefault('last_collection', s.value)
        elif metric == 'g6_index_success_rate_percent':
            for s in samples:
                idx = s.labels.get('index')
                if not idx: continue
                indices.setdefault(idx, {}).setdefault('success_pct', s.value)
        elif metric == 'g6_put_call_ratio':
            for s in samples:
                idx = s.labels.get('index')
                exp = s.labels.get('expiry')
                if not idx or not exp: continue
                indices.setdefault(idx, {}).setdefault('pcr', {})[exp] = s.value
    payload = {
        'ts': snap.ts,
        'age_seconds': snap.age_seconds,
        'stale': snap.stale,
        'core': {
            'uptime_seconds': first('g6_uptime_seconds'),
            'avg_cycle_time': first('g6_collection_cycle_time_seconds'),
            'options_per_minute': first('g6_options_processed_per_minute'),
            'collection_success_pct': first('g6_collection_success_rate_percent'),
            'api_success_pct': first('g6_api_success_rate_percent'),
        },
        'resources': {
            'cpu_pct': first('g6_cpu_usage_percent'),
            'memory_mb': first('g6_memory_usage_mb'),
        },
        'adaptive': {
            'memory_pressure_level': first('g6_memory_pressure_level'),
            'depth_scale': first('g6_memory_depth_scale'),
        },
        'indices': [
            {
                'index': idx,
                **vals
            } for idx, vals in sorted(indices.items())
        ]
    }
    return JSONResponse(payload)

@app.get('/api/memory/status')
async def api_memory_status() -> JSONResponse:
    """Return lightweight memory stats from MemoryManager.

    Includes RSS (if available), peak RSS, total GC collections, last GC duration, and registered caches.
    """
    try:
        from src.utils.memory_manager import get_memory_manager
    except Exception as e:
        get_error_handler().handle_error(
            e,
            category=ErrorCategory.CONFIGURATION,
            severity=ErrorSeverity.LOW,
            component="web.dashboard.app",
            function_name="api_memory_status",
            message="Memory manager import failed",
            should_log=False,
        )
        raise HTTPException(status_code=503, detail='memory manager unavailable')
    try:
        mm = get_memory_manager()
        stats = mm.get_stats()
        return JSONResponse({"status": "ok", "stats": stats if isinstance(stats, dict) else {}})
    except Exception as e:
        get_error_handler().handle_error(
            e,
            category=ErrorCategory.RESOURCE,
            severity=ErrorSeverity.MEDIUM,
            component="web.dashboard.app",
            function_name="api_memory_status",
            message="Error while fetching memory status",
            should_log=False,
        )
        raise HTTPException(status_code=500, detail=f'memory status error: {e}')

@app.get('/', response_class=HTMLResponse)
async def overview(request: Request) -> HTMLResponse:
    snap = cache.snapshot()
    return templates.TemplateResponse('overview.html', {
        'request': request,
        'snapshot': snap,
        'core_refresh': CORE_REFRESH,
        'secondary_refresh': SECONDARY_REFRESH,
    })

@app.get('/metrics/fragment', response_class=HTMLResponse)
async def metrics_fragment(request: Request) -> HTMLResponse:
    """Return an HTML fragment for HTMX updates (core + indices tables)."""
    snap = cache.snapshot()
    return templates.TemplateResponse('_metrics_fragment.html', {
        'request': request,
        'snapshot': snap,
        'debug': DEBUG_MODE,
    })

@app.get('/indices/fragment', response_class=HTMLResponse)
async def indices_fragment(request: Request) -> HTMLResponse:
    """Return an HTML fragment for HTMX updates (indices-only table).

    Note: The main dashboard no longer includes an Indices panel. This route
    is retained for optional detail views and future use. Keeping it avoids
    breaking external bookmarks while we iterate on UI composition.
    """
    snap = cache.snapshot()
    return templates.TemplateResponse('_indices_fragment.html', {
        'request': request,
        'snapshot': snap,
    })

@app.get('/stream/fragment', response_class=HTMLResponse)
async def stream_fragment(request: Request) -> HTMLResponse:
    """Return rolling stream style table (legs, averages, success%, status, recent error)."""
    snap = cache.snapshot()
    return templates.TemplateResponse('_stream_fragment.html', {
        'request': request,
        'snapshot': snap,
        'debug': DEBUG_MODE,
    })

@app.get('/footer/fragment', response_class=HTMLResponse)
async def footer_fragment(request: Request) -> HTMLResponse:
    """Footer fragment using new enveloped panel (Wave 4 PoC).

    Proof-of-concept migration: attempt to load `footer_enveloped.json` emitted by
    the panel updater. Falls back to in-process metrics cache snapshot footer if
    file unavailable. This lets us validate the envelope approach without
    breaking existing behavior.
    """
    snap = cache.snapshot()
    footer_panel = None
    panels_dir = os.getenv('G6_PANELS_DIR', 'data/panels')
    panel_path = os.path.join(panels_dir, 'footer_enveloped.json')
    try:
        # Prefer cached JSON reader when available to minimize repeated disk I/O
        try:
            from pathlib import Path as _Path

            from src.utils.csv_cache import read_json_cached as _read_json_cached
            obj = _read_json_cached(_Path(panel_path)) if os.path.exists(panel_path) else None
        except Exception:
            obj = None
            import json  # fallback local import to keep import surface minimal
            if os.path.exists(panel_path):
                with open(panel_path, encoding='utf-8') as f:
                    obj = json.load(f)
        if isinstance(obj, dict) and obj.get('kind') == 'footer' and isinstance(obj.get('footer'), dict):
            footer_panel = obj
    except Exception as e:  # non-fatal; log via error handler quietly
        get_error_handler().handle_error(
            e,
            category=ErrorCategory.FILE_IO,
            severity=ErrorSeverity.LOW,
            component="web.dashboard.app",
            function_name="footer_fragment",
            message="Failed reading footer_enveloped.json (fallback to snapshot)",
            should_log=False,
        )
    return templates.TemplateResponse('_footer_fragment.html', {
        'request': request,
        'snapshot': snap,
        'footer_panel': footer_panel,
    })

@app.get('/storage/fragment', response_class=HTMLResponse)
async def storage_fragment(request: Request) -> HTMLResponse:
    """Storage fragment adopting new enveloped panel (Wave 4 incremental migration).

    Attempts to load `storage_enveloped.json` written by the panel updater.
    If present and structurally valid (kind == 'storage' and has an object
    field `storage`), it is supplied to the template as `storage_panel`.
    The template is written to prefer the enveloped form but gracefully
    falls back to legacy snapshot.storage usage. Any file read errors are
    non-fatal and silently (low severity) logged via the error handler.
    """
    snap = cache.snapshot()
    storage_panel = None
    panels_dir = os.getenv('G6_PANELS_DIR', 'data/panels')
    panel_path = os.path.join(panels_dir, 'storage_enveloped.json')
    try:
        # Prefer cached JSON reader when available to minimize repeated disk I/O
        try:
            from pathlib import Path as _Path

            from src.utils.csv_cache import read_json_cached as _read_json_cached
            obj = _read_json_cached(_Path(panel_path)) if os.path.exists(panel_path) else None
        except Exception:
            obj = None
            import json
            if os.path.exists(panel_path):
                with open(panel_path, encoding='utf-8') as f:
                    obj = json.load(f)
        if isinstance(obj, dict) and obj.get('kind') == 'storage' and isinstance(obj.get('storage'), dict):
            storage_panel = obj
    except Exception as e:  # pragma: no cover - defensive; should not break rendering
        get_error_handler().handle_error(
            e,
            category=ErrorCategory.FILE_IO,
            severity=ErrorSeverity.LOW,
            component="web.dashboard.app",
            function_name="storage_fragment",
            message="Failed reading storage_enveloped.json (fallback to snapshot)",
            should_log=False,
        )
    return templates.TemplateResponse('_storage_fragment.html', {
        'request': request,
        'snapshot': snap,
        'storage_panel': storage_panel,
    })

@app.get('/errors/fragment', response_class=HTMLResponse)
async def errors_fragment(request: Request) -> HTMLResponse:
    snap = cache.snapshot()
    return templates.TemplateResponse('_errors_fragment.html', {
        'request': request,
        'snapshot': snap,
    })

def _tail_log(path: str, max_lines: int = 120) -> list[str]:
    p = pathlib.Path(path)
    if not p.exists():
        return [f"(log file not found: {path})"]
    try:
        # Efficient tail: read last ~64KB
        with p.open('rb') as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            block = 65536
            offset = max(size - block, 0)
            f.seek(offset)
            data = f.read().decode('utf-8', errors='replace')
        lines = data.splitlines()
        return lines[-max_lines:]
    except Exception as e:
        get_error_handler().handle_error(
            e,
            category=ErrorCategory.FILE_IO,
            severity=ErrorSeverity.LOW,
            component="web.dashboard.app",
            function_name="_tail_log",
            message="Failed reading log file",
            context={"path": path},
            should_log=False,
        )
        return [f"(failed reading log: {e})"]

@app.get('/logs/fragment', response_class=HTMLResponse)
async def logs_fragment(request: Request, lines: int = 60) -> HTMLResponse:
    entries = _tail_log(LOG_PATH, max_lines=lines)
    return templates.TemplateResponse('_logs_fragment.html', {
        'request': request,
        'lines': entries,
    })

@app.get('/metrics/raw')
async def metrics_raw() -> PlainTextResponse:
    snap = cache.snapshot()
    if not snap:
        return PlainTextResponse("no data", status_code=503)
    # Reconstruct minimal raw view for debugging
    lines = []
    for name, samples in snap.raw.items():
        for s in samples:
            if s.labels:
                label_str = ','.join(f"{k}=\"{v}\"" for k,v in s.labels.items())
                lines.append(f"{name}{{{label_str}}} {s.value}")
            else:
                lines.append(f"{name} {s.value}")
    return PlainTextResponse('\n'.join(lines))

# DEBUG_MODE already defined above

# --------------------------- Memory Fragment & APIs ---------------------------
def _build_memory_snapshot() -> MemorySnapshot | None:
    """Assemble a tiny memory snapshot suitable for the memory panel.

    Reads from the memory manager API; returns None on failure.
    """
    try:
        from src.utils.memory_manager import get_memory_manager
        mm = get_memory_manager()
        stats = mm.get_stats() or {}
        snap: MemorySnapshot = {
            'rss_mb': stats.get('rss_mb'),
            'peak_rss_mb': stats.get('peak_rss_mb'),
            'gc_collections_total': stats.get('gc_collections_total'),
            'gc_last_duration_ms': stats.get('gc_last_duration_ms'),
        }
        return snap
    except Exception as e:
        get_error_handler().handle_error(
            e,
            category=ErrorCategory.RESOURCE,
            severity=ErrorSeverity.LOW,
            component="web.dashboard.app",
            function_name="_build_memory_snapshot",
            message="Failed to build memory snapshot",
            should_log=False,
        )
        return None

@app.get('/memory/fragment', response_class=HTMLResponse)
async def memory_fragment(request: Request) -> HTMLResponse:
    snap = cache.snapshot()  # consistent shape; not strictly required
    mem = _build_memory_snapshot()
    # Provide a simple struct-like object so Jinja can access snapshot.memory.*
    snapshot_obj = type('S', (), {'memory': mem}) if mem is not None else None
    return templates.TemplateResponse('_memory_fragment.html', {
        'request': request,
        'snapshot': snapshot_obj,
        'debug': DEBUG_MODE,
    })

# --------------------------- Unified JSON Endpoints ---------------------------
@app.get('/api/unified/status')
async def api_unified_status() -> JSONResponse:
    if _unified is None:
        raise HTTPException(status_code=503, detail='unified source unavailable')
    try:
        st = _unified.get_runtime_status()
        payload: UnifiedStatusResponse | dict
        if isinstance(st, dict):
            # Accept partial user-provided dict; rely on TypedDict being total=False
            payload = cast(UnifiedStatusResponse, st)
        else:
            payload = {}
        return JSONResponse(payload)
    except Exception as e:
        get_error_handler().handle_error(
            e,
            category=ErrorCategory.RESOURCE,
            severity=ErrorSeverity.MEDIUM,
            component="web.dashboard.app",
            function_name="api_unified_status",
            message="Error fetching unified runtime status",
            should_log=False,
        )
        raise HTTPException(status_code=500, detail=f'unified status error: {e}')


@app.get('/api/unified/indices')
async def api_unified_indices() -> JSONResponse:
    if _unified is None:
        raise HTTPException(status_code=503, detail='unified source unavailable')
    try:
        inds = _unified.get_indices_data()
        payload: UnifiedIndicesResponse | dict
        if isinstance(inds, dict):
            payload = cast(UnifiedIndicesResponse, inds)
        else:
            payload = {}
        return JSONResponse(payload)
    except Exception as e:
        get_error_handler().handle_error(
            e,
            category=ErrorCategory.RESOURCE,
            severity=ErrorSeverity.MEDIUM,
            component="web.dashboard.app",
            function_name="api_unified_indices",
            message="Error fetching unified indices",
            should_log=False,
        )
        raise HTTPException(status_code=500, detail=f'unified indices error: {e}')

@app.get('/api/unified/source-status')
async def api_unified_source_status() -> JSONResponse:
    if _unified is None:
        raise HTTPException(status_code=503, detail='unified source unavailable')
    try:
        st = _unified.get_source_status()
        payload: UnifiedSourceStatusResponse | dict
        if isinstance(st, dict):
            payload = cast(UnifiedSourceStatusResponse, st)
        else:
            payload = {}
        return JSONResponse(payload)
    except Exception as e:
        get_error_handler().handle_error(
            e,
            category=ErrorCategory.RESOURCE,
            severity=ErrorSeverity.MEDIUM,
            component="web.dashboard.app",
            function_name="api_unified_source_status",
            message="Error fetching unified source status",
            should_log=False,
        )
        raise HTTPException(status_code=500, detail=f'unified source-status error: {e}')

@app.post('/api/memory/gc')
async def api_memory_gc(request: Request) -> JSONResponse:
    """Trigger a GC cycle via MemoryManager. Guarded by G6_DASHBOARD_DEBUG=1."""
    if not DEBUG_MODE:
        raise HTTPException(status_code=403, detail='forbidden')
    try:
        from src.utils.memory_manager import get_memory_manager
        mm = get_memory_manager()
        # Read optional aggressive flag
        aggressive = False
        try:
            form = await request.form()
            aggressive = str(form.get('aggressive','0')).lower() in ('1','true','yes','on')
        except Exception as e:
            # Non-fatal form parse issue
            get_error_handler().handle_error(
                e,
                category=ErrorCategory.DATA_PARSING,
                severity=ErrorSeverity.LOW,
                component="web.dashboard.app",
                function_name="api_memory_gc",
                message="Failed to parse GC form",
                should_log=False,
            )
        # Use post_cycle_cleanup for consistent metrics/stats updates
        mm.post_cycle_cleanup(aggressive=aggressive)
        return JSONResponse({"status": "ok", "aggressive": aggressive, "stats": mm.get_stats()})
    except Exception as e:
        get_error_handler().handle_error(
            e,
            category=ErrorCategory.RESOURCE,
            severity=ErrorSeverity.MEDIUM,
            component="web.dashboard.app",
            function_name="api_memory_gc",
            message="Memory GC endpoint failure",
            should_log=False,
        )
        raise HTTPException(status_code=500, detail=f'memory gc error: {e}')

# --------------------------- Unified Cache Stats (JSON) ---------------------------
@app.get('/api/unified/cache-stats')
async def api_unified_cache_stats(reset: bool = False) -> JSONResponse:
    """Return UnifiedDataSource cache statistics.

    If reset=true, counters are zeroed after snapshot is taken.
    """
    if _unified is None:
        raise HTTPException(status_code=503, detail='unified source unavailable')
    try:
        # Unwrap to get the underlying object if it's a Protocol reference
        ds = _unified  # type: ignore[assignment]
        # Safely probe for get_cache_stats availability
        getter = getattr(ds, 'get_cache_stats', None)
        if not callable(getter):
            return JSONResponse({'error': 'cache stats not available'}, status_code=404)
        stats = getter(reset=reset)
        if not isinstance(stats, dict):
            stats = {}
        return JSONResponse(stats)
    except Exception as e:
        get_error_handler().handle_error(
            e,
            category=ErrorCategory.RESOURCE,
            severity=ErrorSeverity.LOW,
            component="web.dashboard.app",
            function_name="api_unified_cache_stats",
            message="Error fetching cache stats",
            should_log=False,
        )
        raise HTTPException(status_code=500, detail=f'unified cache-stats error: {e}')

# --------------------------- DEBUG ENDPOINTS (ONE-TIME DIAGNOSTIC BLOCK) ---------------------------
# DEBUG_CLEANUP_BEGIN: temporary debug/observability endpoints. Enabled only when
# G6_DASHBOARD_DEBUG=1 to keep production surface minimal.
_EXPECTED_CORE = [
    'g6_uptime_seconds', 'g6_collection_cycle_time_seconds', 'g6_options_processed_per_minute',
    'g6_collection_success_rate_percent', 'g6_api_success_rate_percent', 'g6_cpu_usage_percent',
    'g6_memory_usage_mb', 'g6_index_cycle_attempts', 'g6_index_cycle_success_percent',
    'g6_index_options_processed', 'g6_index_options_processed_total'
]

if DEBUG_MODE:
    @app.get('/debug/metrics')
    async def debug_metric_names() -> Mapping[str, Any]:
        """Return all metric names with sample counts."""
        snap = cache.snapshot()
        if not snap:
            raise HTTPException(status_code=503, detail='no snapshot yet')
        data = {name: len(samples) for name, samples in sorted(snap.raw.items())}
        return {'ts': snap.ts, 'age_seconds': snap.age_seconds, 'count': len(data), 'metrics': data}

    @app.get('/debug/missing')
    async def debug_missing() -> Mapping[str, Any]:
        snap = cache.snapshot()
        if not snap:
            raise HTTPException(status_code=503, detail='no snapshot yet')
        present = set(snap.raw.keys())
        missing = [m for m in _EXPECTED_CORE if m not in present]
        return {'missing_core_metrics': missing, 'present_core': list(present & set(_EXPECTED_CORE))}

    @app.get('/debug/indices')
    async def debug_indices() -> Mapping[str, Any]:
        snap = cache.snapshot()
        if not snap:
            raise HTTPException(status_code=503, detail='no snapshot yet')
        rows = snap.stream_rows or []
        return {'rows': rows, 'count': len(rows)}

    @app.get('/debug/raw/{metric_name}')
    async def debug_raw_metric(metric_name: str) -> PlainTextResponse:
        snap = cache.snapshot()
        if not snap:
            raise HTTPException(status_code=503, detail='no snapshot yet')
        samples = snap.raw.get(metric_name)
        if not samples:
            raise HTTPException(status_code=404, detail=f'metric {metric_name} not found')
        out = []
        for s in samples:
            if s.labels:
                label_str = ','.join(f"{k}=\"{v}\"" for k,v in s.labels.items())
                out.append(f"{metric_name}{{{label_str}}} {s.value}")
            else:
                out.append(f"{metric_name} {s.value}")
        return PlainTextResponse('\n'.join(out))

# DEBUG_CLEANUP_END

# --------------------------- Options Metadata & Weekday Overlays ---------------------------
def _project_root() -> Path:
    # src/web/dashboard/app.py -> dashboard -> web -> src -> PROJECT ROOT
    return Path(__file__).resolve().parents[3]

def _scan_options_fs(base: Path | None = None) -> dict[str, Any]:
    """Scan filesystem under data/g6_data to derive available indices/expiries/offsets.

    Returns a dict with shapes:
      {
        "root": str,
        "indices": ["NIFTY", ...],
        "matrix": { "NIFTY": { "expiry_tags": [..], "offsets": {"this_week": ["ATM", ...] } } },
      }
    """
    try:
        root = (base or _project_root()) / 'data' / 'g6_data'
        out: dict[str, Any] = {"root": str(root), "indices": [], "matrix": {}}
        if not root.exists():
            return out
        for idx_dir in sorted([p for p in root.iterdir() if p.is_dir()]):
            idx = idx_dir.name
            out["indices"].append(idx)  # indices: list[str]
            exp_tags: list[str] = []
            offsets_map: dict[str, list[str]] = {}
            for exp_dir in sorted([p for p in idx_dir.iterdir() if p.is_dir()]):
                exp = exp_dir.name
                exp_tags.append(exp)
                offs: list[str] = []
                for off_dir in sorted([p for p in exp_dir.iterdir() if p.is_dir()]):
                    offs.append(off_dir.name)
                offsets_map[exp] = offs
            out["matrix"][idx] = {"expiry_tags": exp_tags, "offsets": offsets_map}
        return out
    except Exception as e:  # pragma: no cover - defensive filesystem scan
        get_error_handler().handle_error(
            e,
            category=ErrorCategory.FILE_IO,
            severity=ErrorSeverity.LOW,
            component="web.dashboard.app",
            function_name="_scan_options_fs",
            message="Failed to scan options filesystem",
            should_log=False,
        )
        return {"root": str((base or _project_root()) / 'data' / 'g6_data'), "indices": [], "matrix": {}}


@app.get('/options', response_class=HTMLResponse)
async def options_page(request: Request) -> HTMLResponse:
    """Options metadata overview derived from filesystem (no provider required)."""
    fs_meta = _scan_options_fs()
    return templates.TemplateResponse('options.html', {
        'request': request,
        'fs': fs_meta,
    })


def _read_text_file(p: Path) -> str | None:
    try:
        return p.read_text(encoding='utf-8')
    except Exception:
        return None


@app.get('/weekday/overlays', response_class=HTMLResponse)
async def weekday_overlays_page(request: Request) -> HTMLResponse:
    """Embed a generated weekday overlays HTML if present, else show guidance."""
    base = _project_root()
    html_path = Path(os.environ.get('G6_WEEKDAY_OVERLAYS_HTML', str(base / 'weekday_overlays.html')))
    meta_path = Path(os.environ.get('G6_WEEKDAY_OVERLAYS_META', str(base / 'weekday_overlays_meta.json')))
    embedded_html = _read_text_file(html_path) if html_path.exists() else None
    meta_json = None
    if meta_path.exists():
        try:
            meta_json = meta_path.read_text(encoding='utf-8')
        except Exception:
            meta_json = None
    return templates.TemplateResponse('weekday_overlays.html', {
        'request': request,
        'html_present': embedded_html is not None,
        'embedded_html': embedded_html or '',
        'html_path': str(html_path),
        'meta_json': meta_json,
        'meta_path': str(meta_path),
    })

# --------------------------- JSON API: Weekday Overlay Curves ---------------------------
def _weekday_name_for(d: date) -> str:
    return ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"][d.weekday()]

def _parse_time_any(s: str) -> str:
    """Best-effort parse of CSV timestamp to ISO 8601 string.

    Accepts common forms like 'YYYY-MM-DD HH:MM:SS' or 'DD-MM-YYYY HH:MM:SS'.
    Returns original string if parsing fails, which Infinity can still treat as a string.
    """
    s = (s or '').strip()
    if not s:
        return s
    # Try ISO-ish quickly
    try:
        # Handle "YYYY-MM-DD HH:MM:SS" or already-ISO
        if 'T' not in s and ' ' in s:
            iso = s.replace(' ', 'T')
        else:
            iso = s
        dt = datetime.fromisoformat(iso)
        # If no timezone info, append 'Z' to help Grafana/Infinity parse reliably
        return (dt.isoformat() + ('Z' if dt.tzinfo is None else ''))
    except Exception:
        pass
    # Try day-first common format
    for fmt in ('%d-%m-%Y %H:%M:%S', '%Y-%m-%d %H:%M:%S'):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.isoformat() + 'Z'
        except Exception:
            continue
    return s

def _parse_time_epoch_ms(s: str) -> int | None:
    """Parse time and return epoch milliseconds. Assumes local timezone for naive times.

    Returns None if parsing fails.
    """
    try:
        raw = (s or '').strip()
        if not raw:
            return None
        # Normalize to ISO-ish first
        iso = raw.replace(' ', 'T') if ('T' not in raw and ' ' in raw) else raw
        dt = None
        try:
            dt = datetime.fromisoformat(iso)
        except Exception:
            pass
        if dt is None:
            for fmt in ('%d-%m-%Y %H:%M:%S', '%Y-%m-%d %H:%M:%S'):
                try:
                    dt = datetime.strptime(raw, fmt)
                    break
                except Exception:
                    continue
        if dt is None:
            return None
        if dt.tzinfo is None:
            # Treat naive as local time
            dt = dt.replace(tzinfo=datetime.now().astimezone().tzinfo)  # local-ok
        return int(dt.timestamp() * 1000)
    except Exception:
        return None

def _find_overlay_csv(root: Path, weekday: str, index: str, expiry_tag: str, offset: str) -> Path | None:
    """Locate overlay CSV in new structure first, then legacy (<Weekday>/<index>_<expiry>_<offset>.csv).

    New: <root>/<INDEX>/<EXPIRY_TAG>/<OFFSET>/<Weekday>.csv with ATM->0 fallback.
    Legacy: <root>/<Weekday>/<index>_<expiry_tag>_<offset>.csv with ATM->0 and +offset variants.
    """
    candidates: list[Path] = []
    # Final layout (preferred): <root>/<Weekday>/<INDEX>/<EXPIRY_TAG>/<OFFSET>.csv
    candidates.append(root / weekday / index / expiry_tag / f"{offset}.csv")
    if offset.upper() == 'ATM':
        candidates.append(root / weekday / index / expiry_tag / "0.csv")
    # Previous layout
    candidates.append(root / index / expiry_tag / offset / f"{weekday}.csv")
    if offset.upper() == 'ATM':
        candidates.append(root / index / expiry_tag / '0' / f"{weekday}.csv")
    # Legacy flat layout
    day_dir = root / weekday
    candidates.append(day_dir / f"{index}_{expiry_tag}_{offset}.csv")
    if offset.upper() == 'ATM':
        candidates.append(day_dir / f"{index}_{expiry_tag}_0.csv")
    if offset and offset[0].isdigit():
        candidates.append(day_dir / f"{index}_{expiry_tag}_+{offset}.csv")
    for p in candidates:
        if p.exists():
            return p
    return None

def _norm_offset_folder(offset: str) -> str:
    v = (offset or '').strip()
    if not v:
        return v
    up = v.upper()
    if up == 'ATM':
        return '0'
    # already signed +N or -N
    if up.startswith('+') or up.startswith('-'):
        return v
    # digits -> +digits
    if up.isdigit():
        return f"+{v}"
    return v

def _find_live_csv(root: Path, index: str, expiry_tag: str, offset: str, day: date) -> Path | None:
    """Locate live CSV for today's date under data/g6_data.

    Layout: <root>/<INDEX>/<expiry_tag>/<offset>/<YYYY-MM-DD>.csv with ATM->0 and unsigned +N normalization.
    """
    idx = (index or '').upper().strip()
    off = _norm_offset_folder(offset)
    ymd = day.strftime('%Y-%m-%d')
    p = root / idx / expiry_tag / off / f"{ymd}.csv"
    if p.exists():
        return p
    # Fallbacks: ATM alias -> 0 (handled), try raw offset if normalization added '+'
    if off.startswith('+') and off[1:].isdigit():
        raw = off[1:]
        q = root / idx / expiry_tag / raw / f"{ymd}.csv"
        if q.exists():
            return q
    # Try lower-case expiry dir (defensive)
    q2 = root / idx / expiry_tag.lower() / off / f"{ymd}.csv"
    if q2.exists():
        return q2
    return None

def _parse_bool_flag(v: str | None, default: bool = True) -> bool:
    if v is None:
        return default
    s = str(v).strip().lower()
    if s in ("1", "true", "t", "yes", "y", "on"):  # common truthy tokens
        return True
    if s in ("0", "false", "f", "no", "n", "off"):
        return False
    return default


@app.get('/api/live_csv')
async def api_live_csv(
    request: Request,
    index: str,
    expiry_tag: str,
    offset: str,
    date_str: str | None = None,
    limit: int | None = None,
    from_ms: int | None = None,
    to_ms: int | None = None,
    no_cache: str | None = None,
    include_avg: str | None = None,
    include_ce: str | None = None,
    include_pe: str | None = None,
    include_index: str | None = None,
    index_pct: str | None = None,
    include_iv: str | None = None,
    include_greeks: str | None = None,
    include_analytics: str | None = None,
    indices: str | None = None,
) -> JSONResponse:
    """Return today's live CSV as JSON rows for Infinity.

    Query params:
      - index: e.g., NIFTY
      - expiry_tag: e.g., this_week/this_month
      - offset: e.g., 0, ATM, +100
      - date_str: optional YYYY-MM-DD (defaults to today)
      - limit: optional positive integer to cap rows from start
    Returns array of objects with: time, tp, avg_tp (and optionally ce, pe if present).
    """
    # Clean, unified implementation using cached rows and concurrency/back-pressure
    t0 = _obs_begin("live_csv")
    acquired = False
    try:
        try:
            await asyncio.wait_for(_SEM.acquire(), timeout=0.002)
            acquired = True
        except Exception:
            _obs_too_many("live_csv")
            return JSONResponse({"error": "too_many_requests", "retry_after": 1}, status_code=429, headers={"Retry-After": "1"})

        base = _project_root() / 'data' / 'g6_data'
        day = datetime.strptime(date_str, '%Y-%m-%d').date() if (date_str and date_str.strip()) else datetime.now().date()  # local-ok

        # Determine multi-index selection if provided
        idx_list: list[str] | None = None
        if indices and str(indices).strip():
            idx_list = [s.strip().upper() for s in str(indices).split(',') if s.strip()]
        elif ',' in index:
            idx_list = [s.strip().upper() for s in index.split(',') if s.strip()]

        # Flags
        disable_cache = _parse_bool_flag(no_cache, False)
        inc_avg = _parse_bool_flag(include_avg, True)
        inc_ce = _parse_bool_flag(include_ce, True)
        inc_pe = _parse_bool_flag(include_pe, True)
        inc_index = _parse_bool_flag(include_index, True)
        inc_index_pct = _parse_bool_flag(index_pct, False)
        inc_analytics = _parse_bool_flag(include_analytics, False)
        inc_iv = _parse_bool_flag(include_iv, inc_analytics)
        inc_greeks = _parse_bool_flag(include_greeks, inc_analytics)

        def _find_with_fallback(_idx: str) -> Path | None:
            p = _find_live_csv(base, _idx, expiry_tag, offset, day)
            if p:
                return p
            if not date_str:
                from datetime import timedelta
                for delta in (1, 2, 3):
                    fallback = day - timedelta(days=delta)
                    q = _find_live_csv(base, _idx, expiry_tag, offset, fallback)
                    if q:
                        return q
            return None

        def _build_rows_for(_idx: str) -> tuple[list[dict[str, Any]], Path | None]:
            _path = _find_with_fallback(_idx)
            if not _path:
                raise HTTPException(status_code=404, detail=f"live csv not found for {_idx} {expiry_tag} {offset} {day}")
            rows_full = _load_csv_rows_full(_path)
            keep_keys = {'time','ts','time_str','tp'}
            if inc_avg: keep_keys.add('avg_tp')
            if inc_ce: keep_keys.add('ce')
            if inc_pe: keep_keys.add('pe')
            if inc_index: keep_keys.add('index_price')
            if inc_iv: keep_keys.update({'ce_iv','pe_iv'})
            if inc_greeks: keep_keys.update({'ce_delta','pe_delta','ce_theta','pe_theta','ce_vega','pe_vega','ce_gamma','pe_gamma','ce_rho','pe_rho'})

            rows_sel = [{k: r.get(k, None) for k in keep_keys} for r in rows_full]
            # Time range filter
            if from_ms is not None or to_ms is not None:
                fms = from_ms if isinstance(from_ms, int) else None
                tms = to_ms if isinstance(to_ms, int) else None
                def _in_range(v: Any) -> bool:
                    try:
                        if v is None:
                            return False
                        x = int(v)
                    except Exception:
                        return False
                    if fms is not None and x < fms:
                        return False
                    if tms is not None and x > tms:
                        return False
                    return True
                rows_sel = [r for r in rows_sel if _in_range(r.get('ts'))]

            # Derive index_pct if requested
            if inc_index_pct:
                try:
                    base_val: float | None = None
                    for r in rows_sel:
                        v = r.get('index_price')
                        if isinstance(v, (int, float)):
                            base_val = float(v)
                            break
                    if base_val and base_val != 0.0:
                        for r in rows_sel:
                            v = r.get('index_price')
                            if isinstance(v, (int, float)):
                                r['index_pct'] = (float(v) / base_val - 1.0) * 100.0
                            else:
                                r['index_pct'] = None
                    else:
                        for r in rows_sel:
                            r['index_pct'] = None
                except Exception:
                    for r in rows_sel:
                        r['index_pct'] = None

            # Limit after filtering (keep most recent N rows)
            if isinstance(limit, int) and limit > 0 and len(rows_sel) > limit:
                rows_sel = rows_sel[-limit:]
            return rows_sel, _path

        headers: dict[str, str] = {}

        if idx_list:
            groups: dict[str, list[dict[str, Any]]] = {}
            etag_hasher = zlib.crc32(b"")
            lm_ns = 0
            for idx_name in idx_list:
                rows_i, pth = _build_rows_for(idx_name)
                groups[idx_name] = rows_i
                if pth and pth.exists():
                    st = pth.stat()
                    for part in (str(pth).encode('utf-8'), str(st.st_mtime_ns).encode('ascii'), str(st.st_size).encode('ascii')):
                        etag_hasher = zlib.crc32(part, etag_hasher)
                    lm_ns = max(lm_ns, int(st.st_mtime_ns))
            etag_key = f"W/\"multi-{etag_hasher:x}-{limit}-{from_ms}-{to_ms}\""
            headers["Cache-Control"] = "public, max-age=15, must-revalidate"
            headers["ETag"] = etag_key
            if lm_ns:
                try:
                    lm = time.gmtime(lm_ns / 1_000_000_000)
                    headers["Last-Modified"] = time.strftime('%a, %d %b %Y %H:%M:%S GMT', lm)
                except Exception:
                    pass
            inm = request.headers.get('if-none-match') if isinstance(request, Request) else None
            if (not disable_cache) and inm and inm == etag_key:
                _obs_end("live_csv", t0, ok=True)
                return JSONResponse(None, status_code=304, headers=headers)
            _obs_end("live_csv", t0, ok=True)
            return JSONResponse({"indices": groups}, headers=headers)
        else:
            rows, pth = _build_rows_for(index.upper())
            etag_src = f"{index}|{expiry_tag}|{offset}|{date_str}|{limit}|{from_ms}|{to_ms}|{include_avg}|{include_ce}|{include_pe}|{include_index}|{index_pct}|{include_iv}|{include_greeks}|{include_analytics}".encode()
            h = zlib.crc32(etag_src)
            if pth and pth.exists():
                st = pth.stat()
                h = zlib.crc32(str(st.st_mtime_ns).encode('ascii'), h)
                h = zlib.crc32(str(st.st_size).encode('ascii'), h)
                try:
                    lm = time.gmtime(st.st_mtime_ns / 1_000_000_000)
                    headers["Last-Modified"] = time.strftime('%a, %d %b %Y %H:%M:%S GMT', lm)
                except Exception:
                    pass
            headers["Cache-Control"] = "public, max-age=15, must-revalidate"
            headers["ETag"] = f"W/\"{h:x}\""
            inm = request.headers.get('if-none-match') if isinstance(request, Request) else None
            if (not disable_cache) and inm and inm == headers["ETag"]:
                _obs_end("live_csv", t0, ok=True)
                return JSONResponse(None, status_code=304, headers=headers)
            _obs_end("live_csv", t0, ok=True)
            return JSONResponse(rows, headers=headers)
    except HTTPException:
        _obs_end("live_csv", t0, ok=False)
        raise
    except Exception as e:
        get_error_handler().handle_error(
            e,
            category=ErrorCategory.FILE_IO,
            severity=ErrorSeverity.LOW,
            component="web.dashboard.app",
            function_name="api_live_csv",
            message="Failed serving live CSV JSON",
            should_log=False,
        )
        _obs_end("live_csv", t0, ok=False)
        raise HTTPException(status_code=500, detail='live csv endpoint error')
    finally:
        if acquired:
            try:
                _SEM.release()
            except Exception:
                pass

@app.get('/api/overlay')
async def api_overlay(request: Request, index: str, expiry_tag: str, offset: str, weekday: str | None = None, limit: int | None = None, no_cache: str | None = None) -> JSONResponse:
    """Return static weekday overlay curves as an array of objects for Grafana JSON API/Infinity.

    Query params:
      - index: e.g., NIFTY
      - expiry_tag: e.g., this_week
      - offset: e.g., ATM or 0 or +100
      - weekday: optional (Monday..Sunday). Defaults to today's weekday (server time).
      - limit: optional max rows (positive integer)
    """
    t0 = _obs_begin("overlay")
    acquired = False
    try:
        # Concurrency guard
        try:
            await asyncio.wait_for(_SEM.acquire(), timeout=0.001)
            acquired = True
        except Exception:
            _obs_too_many("overlay")
            return JSONResponse({"error": "too_many_requests", "retry_after": 1}, status_code=429, headers={"Retry-After": "1"})

        base = _project_root() / 'data' / 'weekday_master'
        disable_cache = _parse_bool_flag(no_cache, False)

        if not weekday:
            from datetime import datetime
            weekday = _weekday_name_for(datetime.now().date())  # local-ok
        # Normalize weekday capitalization
        weekday = str(weekday).capitalize()
        path = _find_overlay_csv(base, weekday, index, expiry_tag, offset)
        if not path:
            # As a last attempt, try uppercase index
            path = _find_overlay_csv(base, weekday, index.upper(), expiry_tag, offset)
        if not path:
            raise HTTPException(status_code=404, detail=f"overlay file not found for {weekday} {index} {expiry_tag} {offset}")

        rows: list[dict[str, Any]] = []
        with path.open('r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for r in reader:
                ts = _parse_time_any(str(r.get('timestamp', '')).strip())
                obj: dict[str, Any] = {'time': ts}
                # Safe float conversions; leave None if missing
                for col in ('tp_mean','tp_ema','avg_tp_mean','avg_tp_ema'):
                    val = r.get(col)
                    if val is None or val == '':
                        obj[col] = None
                    else:
                        try:
                            obj[col] = float(val)
                        except Exception:
                            obj[col] = None
                rows.append(obj)

        if isinstance(limit, int) and limit > 0:
            rows = rows[:limit]

        # Caching headers (15s)
        headers: dict[str, str] = {"Cache-Control": "public, max-age=15, must-revalidate"}
        try:
            if path and path.exists():
                st = path.stat()
                lm = time.gmtime(st.st_mtime_ns / 1_000_000_000)
                headers["Last-Modified"] = time.strftime('%a, %d %b %Y %H:%M:%S GMT', lm)
                etag_src = f"{index}|{expiry_tag}|{offset}|{weekday}|{limit}|{st.st_mtime_ns}|{st.st_size}".encode()
                etag = zlib.crc32(etag_src)
                headers["ETag"] = f"W/\"{etag:x}\""
                inm = request.headers.get('if-none-match') if isinstance(request, Request) else None
                if (not disable_cache) and inm and inm == headers["ETag"]:
                    _obs_end("overlay", t0, ok=True)
                    return JSONResponse(None, status_code=304, headers=headers)
        except Exception:
            pass

        resp = JSONResponse(rows, headers=headers)
        _obs_end("overlay", t0, ok=True)
        return resp
    except HTTPException:
        _obs_end("overlay", t0, ok=False)
        raise
    except Exception as e:
        get_error_handler().handle_error(
            e,
            category=ErrorCategory.FILE_IO,
            severity=ErrorSeverity.LOW,
            component="web.dashboard.app",
            function_name="api_overlay",
            message="Failed serving overlay JSON",
            should_log=False,
        )
        _obs_end("overlay", t0, ok=False)
        raise HTTPException(status_code=500, detail='overlay endpoint error')
    finally:
        if acquired:
            try:
                _SEM.release()
            except Exception:
                pass


# --------------------------- JSON API: Sync Check ---------------------------
def _norm_expiry(s: str | None) -> str:
    return (s or '').strip()

def _norm_offset(s: str | None) -> str:
    v = (s or '').strip()
    if not v:
        return v
    up = v.upper()
    if up == 'ATM':
        return '0'
    # normalize +ve integers to +N
    try:
        if up.startswith('+') or up.startswith('-'):
            int(up)
            return up
        # if purely digits, prefix with '+'
        if up.isdigit():
            return f"+{up}"
    except Exception:
        pass
    return v


@app.get('/api/sync_check')
async def api_sync_check(
    expiry_tag_global: str,
    offset_global: str,
    expiry_tag_1: str, offset_1: str,
    expiry_tag_2: str, offset_2: str,
    expiry_tag_3: str, offset_3: str,
    expiry_tag_4: str, offset_4: str,
) -> JSONResponse:
    try:
        eg = _norm_expiry(expiry_tag_global)
        og = _norm_offset(offset_global)
        panels: list[dict[str, Any]] = []
        all_match = True
        for i, (et, off) in enumerate([
            (expiry_tag_1, offset_1), (expiry_tag_2, offset_2), (expiry_tag_3, offset_3), (expiry_tag_4, offset_4)
        ], start=1):
            em = _norm_expiry(et)
            om = _norm_offset(off)
            match = (em == eg) and (om == og)
            panels.append({
                'panel': i,
                'expiry_tag': em,
                'offset': om,
                'match': 1 if match else 0,
            })
            if not match:
                all_match = False
        result = [{
            'all_synced_int': 1 if all_match else 0,
            'all_synced_text': 'ALL SYNCED' if all_match else 'OUT OF SYNC',
            'details': panels,
        }]
        return JSONResponse(result)
    except Exception as e:
        get_error_handler().handle_error(
            e,
            category=ErrorCategory.CONFIGURATION,
            severity=ErrorSeverity.LOW,
            component="web.dashboard.app",
            function_name="api_sync_check",
            message="Failed serving sync check JSON",
            should_log=False,
        )
        raise HTTPException(status_code=500, detail='sync check error')


# --------------------------- API Observability Snapshot ---------------------------
@app.get('/api/_stats')
async def api_stats() -> JSONResponse:
    """Return simple counters and timing for API endpoints.

    Includes counts, errors, 429s, avg/max durations, in-flight, and concurrency limit.
    """
    out = {}
    try:
        for k, v in _OBS.items():
            cnt = float(v.get("count", 0))
            dur_sum = float(v.get("dur_ms_sum", 0.0))
            avg_ms = (dur_sum / cnt) if cnt > 0 else 0.0
            out[k] = {
                "count": int(v.get("count", 0)),
                "errors": int(v.get("errors", 0)),
                "too_many": int(v.get("too_many", 0)),
                "in_flight": int(v.get("in_flight", 0)),
                "avg_ms": round(avg_ms, 2),
                "max_ms": round(float(v.get("dur_ms_max", 0.0)), 2),
            }
    except Exception:
        pass
    out["concurrency_limit"] = max(1, _MAX_CONCURRENCY)
    return JSONResponse(out)
