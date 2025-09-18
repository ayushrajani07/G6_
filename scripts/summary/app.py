from __future__ import annotations
import os
import argparse
import time
from collections import deque
from typing import Any, Dict, Optional, List

from scripts.summary.layout import build_layout, refresh_layout
from scripts.summary.derive import derive_cycle
from scripts.summary_view import StatusCache, plain_fallback

def _get_output_lazy():
    class _O:
        def info(self, msg: str, **kw: Any) -> None:
            try:
                print(msg)
            except Exception:
                pass
        def error(self, msg: str, **kw: Any) -> None:
            try:
                import sys as _sys
                print(msg, file=_sys.stderr)
            except Exception:
                pass
    return _O()


def compute_cadence_defaults() -> Dict[str, float]:
    """
    Returns effective refresh intervals (seconds) for meta/status and resource polling.
    Uses unified knob G6_SUMMARY_REFRESH_SEC when set; otherwise defaults to 15s.
    Per-knob overrides: G6_SUMMARY_META_REFRESH_SEC, G6_SUMMARY_RES_REFRESH_SEC.
    Ensures each value is at least 1.0.
    """
    unified = os.getenv("G6_SUMMARY_REFRESH_SEC")
    if unified is not None and unified.strip() != "":
        try:
            unified_v = max(1.0, float(unified))
        except Exception:
            # On invalid unified value, fall back to legacy default 15s
            unified_v = 15.0
    else:
        # Default refresh cadence if not set: 15s (as per tests and docs)
        unified_v = 15.0
    meta = max(1.0, float(os.getenv("G6_SUMMARY_META_REFRESH_SEC", str(unified_v))))
    res = max(1.0, float(os.getenv("G6_SUMMARY_RES_REFRESH_SEC", str(unified_v))))
    return {"meta": meta, "res": res}


def run(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="G6 Summarizer View")
    parser.add_argument("--status-file", default=os.getenv("G6_STATUS_FILE", "data/runtime_status.json"))
    parser.add_argument("--metrics-url", default=os.getenv("G6_METRICS_URL", "http://127.0.0.1:9108/metrics"))
    parser.add_argument("--refresh", type=float, default=0.5, help="UI frame refresh seconds (visual)")
    parser.add_argument("--no-rich", action="store_true", help="Disable rich UI and print plain text")
    parser.add_argument("--compact", action="store_true", help="Compact layout with fewer details")
    parser.add_argument("--low-contrast", action="store_true", help="Use neutral borders/colors")
    parser.add_argument("--panels", choices=["auto", "on", "off"], default=os.getenv("G6_SUMMARY_PANELS_MODE", "auto"), help="Prefer data/panels JSON (on/off/auto)")
    args = parser.parse_args(argv)

    mode = os.getenv("G6_SUMMARY_MODE", "").strip().lower()
    if mode in ("condensed", "compact") and not args.compact:
        args.compact = True
    elif mode in ("expanded", "full") and args.compact:
        args.compact = False

    out = _get_output_lazy()
    cache = StatusCache(args.status_file)

    # Apply panels mode override early for downstream helpers
    try:
        mode = (args.panels or "auto").strip().lower()
        os.environ["G6_SUMMARY_PANELS_MODE"] = mode
        if mode == "on":
            os.environ["G6_SUMMARY_READ_PANELS"] = "true"
        elif mode == "off":
            os.environ["G6_SUMMARY_READ_PANELS"] = "false"
    except Exception:
        pass

    status = cache.refresh()

    # Plain fallback
    try:
        import rich  # noqa: F401
        RICH_AVAILABLE = True
    except Exception:
        RICH_AVAILABLE = False
    if not RICH_AVAILABLE or args.no_rich:
        print(plain_fallback(status, args.status_file, args.metrics_url))
        return 0

    from rich.console import Console  # type: ignore
    from rich.live import Live  # type: ignore

    try:
        # Enable ANSI VT processing on Windows and force terminal control sequences
        try:
            os.system("")
        except Exception:
            pass
        console = Console(force_terminal=True)
        try:
            console.clear()
        except Exception:
            pass
        window: deque[float] = deque(maxlen=120)
        def compute_roll() -> Dict[str, Any]:
            if not window:
                return {"avg": None, "p95": None}
            vals = list(window)
            vals_sorted = sorted(vals)
            p95_idx = max(0, int(0.95 * (len(vals_sorted) - 1)))
            return {"avg": sum(vals) / len(vals), "p95": vals_sorted[p95_idx]}
        # Refresh cadence: unified knob with per-knob overrides
        cad = compute_cadence_defaults()
        meta_refresh = cad["meta"]
        res_refresh = cad["res"]
        last_meta = 0.0
        last_res = 0.0
        last_status: Dict[str, Any] | None = status
        last_cycle_id: Any = None

        layout = build_layout(status, args.status_file, args.metrics_url, rolling=compute_roll(), compact=bool(args.compact), low_contrast=bool(args.low_contrast))
        fps = max(1, int(round(1.0 / max(0.1, args.refresh))))
        # Avoid alternate screen on Windows to reduce flicker; keep updates modest
        with Live(layout, console=console, screen=False, refresh_per_second=min(5, fps), redirect_stdout=False, redirect_stderr=False) as live:
            while True:
                now = time.time()
                if now - last_meta >= meta_refresh:
                    cur = cache.refresh()
                    if cur is not None:
                        try:
                            cy = derive_cycle(cur)
                            cur_cycle = cy.get("cycle") or cy.get("count") or cur.get("cycle")
                        except Exception:
                            cur_cycle = None
                        if last_status is None:
                            last_status = cur
                        if cur_cycle is not None and cur_cycle != last_cycle_id:
                            last_status = cur
                            last_cycle_id = cur_cycle
                    last_meta = now

                interval = None
                try:
                    if last_status:
                        interval = last_status.get("interval")
                        if interval is None:
                            loop = last_status.get("loop") if isinstance(last_status, dict) else None
                            if isinstance(loop, dict):
                                interval = loop.get("target_interval")
                except Exception:
                    interval = None

                effective_status = dict(last_status or {}) if last_status else {}
                if now - last_res >= res_refresh:
                    try:
                        latest = cache.refresh()
                        if latest and isinstance(latest, dict) and isinstance(effective_status, dict):
                            if "resources" in latest:
                                effective_status["resources"] = latest.get("resources")
                    except Exception:
                        pass
                    last_res = now
                try:
                    from scripts.summary.derive import derive_cycle as _dc
                    cy = _dc(effective_status)
                    ld = cy.get("last_duration")
                    if isinstance(ld, (int, float)):
                        window.append(float(ld))
                except Exception:
                    pass

                refresh_layout(layout, effective_status, args.status_file, args.metrics_url, rolling=compute_roll(), compact=bool(args.compact), low_contrast=bool(args.low_contrast))
                live.update(layout, refresh=True)
                time.sleep(max(0.1, args.refresh))
    except KeyboardInterrupt:
        out.info("Summarizer stopped by user", scope="summary_view")
        return 0
    except Exception as e:
        out.error(f"Summarizer error: {e}", scope="summary_view")
        print(plain_fallback(status, args.status_file, args.metrics_url))
        return 2
