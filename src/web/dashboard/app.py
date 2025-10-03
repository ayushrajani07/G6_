from __future__ import annotations
import os
import time
from fastapi import FastAPI, Request, HTTPException
from fastapi.exceptions import RequestValidationError
from contextlib import asynccontextmanager
from fastapi.responses import JSONResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from .metrics_cache import MetricsCache
import pathlib
from pathlib import Path
from src.error_handling import get_error_handler, ErrorCategory, ErrorSeverity
from src.types.dashboard_types import (
    UnifiedSourceProtocol,
    MemorySnapshot,
    UnifiedStatusResponse,
    UnifiedIndicesResponse,
    UnifiedSourceStatusResponse,
)
from typing import TYPE_CHECKING, Any, Mapping, AsyncIterator, Optional, cast

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
        import json  # local import to keep module import surface minimal
        if os.path.exists(panel_path):
            with open(panel_path, 'r', encoding='utf-8') as f:
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
        import json
        if os.path.exists(panel_path):
            with open(panel_path, 'r', encoding='utf-8') as f:
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
