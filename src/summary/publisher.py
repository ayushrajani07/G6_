from __future__ import annotations
"""
Lightweight publisher for Summary View panels.

This module provides best-effort helpers to emit per-panel JSON snapshots via
the OutputRouter 'panels' sink. It's designed to be safe to call from the
collection loop: failures are swallowed, and missing metrics simply result in
fewer fields being published.

Enable with environment:
  - G6_ENABLE_PANEL_PUBLISH=true     # turn on publishing
  - G6_PANELS_DIR=data/panels        # optional, where JSON files are written
  - G6_OUTPUT_SINKS includes 'panels' (auto-added if not present when enabled)

Consumers: scripts/summary/* panels read these JSONs when enabled (mode 'on' or 'auto').
"""
import os
from typing import Any, Dict, Iterable, Mapping, Optional
from .resilience import safe_update, safe_append


def _truthy(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _ensure_panels_sink_active() -> Optional[Any]:
    """Ensure the OutputRouter is configured with a panels sink.

    Returns the router instance, or None if OutputRouter unavailable.
    """
    try:
        from src.utils.output import get_output  # type: ignore
    except Exception:
        return None
    sinks_env = os.getenv("G6_OUTPUT_SINKS", "stdout,logging")
    tokens = [t.strip().lower() for t in sinks_env.split(",") if t.strip()]
    if "panels" not in tokens:
        tokens.append("panels")
        os.environ["G6_OUTPUT_SINKS"] = ",".join(tokens)
        # Set default panels dir if missing
        os.environ.setdefault("G6_PANELS_DIR", os.path.join("data", "panels"))
        # Rebuild router to include panels sink
        return get_output(reset=True)
    return get_output(reset=False)


def publish_cycle_panels(
    *,
    indices: Iterable[str],
    cycle: int,
    elapsed_sec: float,
    interval_sec: Optional[float],
    success_rate_pct: Optional[float],
    metrics: Optional[Any] = None,
    csv_sink: Optional[Any] = None,
    influx_sink: Optional[Any] = None,
    providers: Optional[Any] = None,
) -> None:
    """Publish a snapshot to the per-panel JSON files.

    All arguments are best-effort; pass what you have. Safe no-op unless
    G6_ENABLE_PANEL_PUBLISH is truthy.
    """
    if not _truthy("G6_ENABLE_PANEL_PUBLISH", default=False):
        return
    router = _ensure_panels_sink_active()
    if router is None:
        return

    # Loop panel (guarded)
    loop_payload: Dict[str, Any] = {
        "cycle": cycle,
        "last_start": None,  # unknown here
        "last_duration": round(float(elapsed_sec), 3),
    }
    if success_rate_pct is not None:
        loop_payload["success_rate"] = success_rate_pct
    if interval_sec is not None:
        loop_payload["avg"] = float(elapsed_sec)  # crude running avg not available
        loop_payload["p95"] = None
    safe_update(router, "loop", loop_payload)

    # Provider panel
    prov_name = None
    latency = None
    try:
        if providers and getattr(providers, "primary_provider", None) is not None:
            prov_name = type(providers.primary_provider).__name__
    except Exception:
        pass
    try:
        if metrics and hasattr(metrics, "_api_latency_ema"):
            latency = getattr(metrics, "_api_latency_ema")
    except Exception:
        pass
    payload = {k: v for k, v in {"name": prov_name, "latency_ms": latency}.items() if v is not None}
    if payload:
        safe_update(router, "provider", payload)

    # Resources panel
    rss = None
    cpu = None
    try:
        if metrics and hasattr(metrics, "memory_usage_mb") and hasattr(metrics.memory_usage_mb, "_value"):
            mem_mb = metrics.memory_usage_mb._value.get()  # type: ignore[attr-defined]
            if isinstance(mem_mb, (int, float)):
                rss = int(float(mem_mb) * 1024 * 1024)
    except Exception:
        pass
    try:
        if metrics and hasattr(metrics, "cpu_usage_percent") and hasattr(metrics.cpu_usage_percent, "_value"):
            cpu = metrics.cpu_usage_percent._value.get()  # type: ignore[attr-defined]
    except Exception:
        pass
    payload = {k: v for k, v in {"cpu": cpu, "rss": rss}.items() if v is not None}
    if payload:
        safe_update(router, "resources", payload)

    # Sinks panel
    sinks_payload: Dict[str, Dict[str, Any]] = {}
    try:
        if csv_sink is not None:
            ts = getattr(csv_sink, "last_write_ts", None)
            sinks_payload["csv_sink"] = {"last_write": ts.isoformat() if hasattr(ts, "isoformat") else (str(ts) if ts else None)}
    except Exception:
        pass
    try:
        if influx_sink is not None:
            ts = getattr(influx_sink, "last_write_ts", None)
            sinks_payload["influx_sink"] = {"last_write": ts.isoformat() if hasattr(ts, "isoformat") else (str(ts) if ts else None)}
    except Exception:
        pass
    if sinks_payload:
        safe_update(router, "sinks", sinks_payload)

    # Indices summary and live stream
    per_index_last: Mapping[str, Any] | None = None
    try:
        if metrics and hasattr(metrics, "_per_index_last_cycle_options"):
            per_index_last = getattr(metrics, "_per_index_last_cycle_options")
    except Exception:
        per_index_last = None

    # Summary metrics panel
    index_metrics: Dict[str, Dict[str, Any]] = {}
    for idx in indices:
        legs = None
        try:
            if per_index_last and idx in per_index_last:
                legs = per_index_last.get(idx)
        except Exception:
            legs = None
        fails = 0  # unknown: assume 0 unless we have an error flag
        status = "OK" if (isinstance(legs, (int, float)) and legs is not None and legs >= 0) else "WARN"
        index_metrics[str(idx)] = {"legs": legs, "fails": fails, "status": status}
    if index_metrics:
        safe_update(router, "indices", index_metrics)

    # Stream panel: one item per index
    sr_int = None
    try:
        if success_rate_pct is not None:
            sr_int = int(round(success_rate_pct))
    except Exception:
        sr_int = None
    for idx in indices:
        legs = None
        try:
            if per_index_last and idx in per_index_last:
                legs = per_index_last.get(idx)
        except Exception:
            legs = None
        item = {
            "index": idx,
            "legs": legs,
            "avg": round(float(elapsed_sec), 3),
            "success": sr_int,
            "status": "OK" if sr_int is None or sr_int >= 95 else ("WARN" if sr_int >= 80 else "ERROR"),
            "cycle": cycle,
        }
        safe_append(router, "indices_stream", item, cap=50, kind="stream")
