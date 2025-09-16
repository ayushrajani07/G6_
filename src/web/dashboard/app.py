from __future__ import annotations
import os
import time
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from .metrics_cache import MetricsCache
import pathlib

LOG_PATH = os.environ.get("G6_LOG_FILE", "logs/g6_platform.log")

METRICS_ENDPOINT = os.environ.get("G6_METRICS_ENDPOINT", "http://localhost:9108/metrics")

app = FastAPI(title="G6 Dashboard", version="0.1.0")
cache = MetricsCache(METRICS_ENDPOINT, interval=5.0, timeout=1.5)

templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), 'templates'))
app.mount('/static', StaticFiles(directory=os.path.join(os.path.dirname(__file__), 'static')), name='static')

@app.on_event("startup")
def _startup():
    cache.start()

@app.get('/health')
async def health():
    snap = cache.snapshot()
    status = 'stale' if (snap and snap.stale) else 'ok'
    return {"status": status, "age": snap.age_seconds if snap else None}

@app.get('/metrics/json')
async def metrics_json():
    snap = cache.snapshot()
    if not snap:
        return JSONResponse({"error": "no data yet"}, status_code=503)
    m = snap.raw
    def first(name, default=None):
        samples = m.get(name)
        if not samples:
            return default
        return samples[0].value
    # Build per-index aggregates
    indices = {}
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

@app.get('/', response_class=HTMLResponse)
async def overview(request: Request):
    snap = cache.snapshot()
    return templates.TemplateResponse('overview.html', {
        'request': request,
        'snapshot': snap,
    })

@app.get('/metrics/fragment', response_class=HTMLResponse)
async def metrics_fragment(request: Request):
    """Return an HTML fragment for HTMX updates (core + indices tables)."""
    snap = cache.snapshot()
    return templates.TemplateResponse('_metrics_fragment.html', {
        'request': request,
        'snapshot': snap,
    })

@app.get('/stream/fragment', response_class=HTMLResponse)
async def stream_fragment(request: Request):
    """Return rolling stream style table (legs, averages, success%, status, recent error)."""
    snap = cache.snapshot()
    return templates.TemplateResponse('_stream_fragment.html', {
        'request': request,
        'snapshot': snap,
    })

@app.get('/footer/fragment', response_class=HTMLResponse)
async def footer_fragment(request: Request):
    snap = cache.snapshot()
    return templates.TemplateResponse('_footer_fragment.html', {
        'request': request,
        'snapshot': snap,
    })

@app.get('/storage/fragment', response_class=HTMLResponse)
async def storage_fragment(request: Request):
    snap = cache.snapshot()
    return templates.TemplateResponse('_storage_fragment.html', {
        'request': request,
        'snapshot': snap,
    })

@app.get('/errors/fragment', response_class=HTMLResponse)
async def errors_fragment(request: Request):
    snap = cache.snapshot()
    return templates.TemplateResponse('_errors_fragment.html', {
        'request': request,
        'snapshot': snap,
    })

def _tail_log(path: str, max_lines: int = 120):
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
        return [f"(failed reading log: {e})"]

@app.get('/logs/fragment', response_class=HTMLResponse)
async def logs_fragment(request: Request, lines: int = 60):
    entries = _tail_log(LOG_PATH, max_lines=lines)
    return templates.TemplateResponse('_logs_fragment.html', {
        'request': request,
        'lines': entries,
    })

@app.get('/metrics/raw')
async def metrics_raw():
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

DEBUG_MODE = os.environ.get('G6_DASHBOARD_DEBUG') == '1'

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
    async def debug_metric_names():
        """Return all metric names with sample counts."""
        snap = cache.snapshot()
        if not snap:
            raise HTTPException(status_code=503, detail='no snapshot yet')
        data = {name: len(samples) for name, samples in sorted(snap.raw.items())}
        return {'ts': snap.ts, 'age_seconds': snap.age_seconds, 'count': len(data), 'metrics': data}

    @app.get('/debug/missing')
    async def debug_missing():
        snap = cache.snapshot()
        if not snap:
            raise HTTPException(status_code=503, detail='no snapshot yet')
        present = set(snap.raw.keys())
        missing = [m for m in _EXPECTED_CORE if m not in present]
        return {'missing_core_metrics': missing, 'present_core': list(present & set(_EXPECTED_CORE))}

    @app.get('/debug/indices')
    async def debug_indices():
        snap = cache.snapshot()
        if not snap:
            raise HTTPException(status_code=503, detail='no snapshot yet')
        rows = snap.stream_rows or []
        return {'rows': rows, 'count': len(rows)}

    @app.get('/debug/raw/{metric_name}')
    async def debug_raw_metric(metric_name: str):
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
