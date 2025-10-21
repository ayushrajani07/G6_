#!/usr/bin/env python
"""Auto-resolve Observability Stack Launcher (standalone)

Responsibilities:
- Detect running Prometheus, Grafana, and InfluxDB on localhost.
- Auto-resolve ports within small ranges (Grafana: 3000-3010, Influx: 8086-8096, Prometheus: 9090-9100)
- Validate health endpoints with sensible fallbacks:
  * Grafana: /api/health == 200
  * InfluxDB: /health == 200 or /ping in {200, 204}; also accept 401/403 (auth guarded). As a last resort, consider TCP connect + owner behavior (approx) as reachable.
  * Prometheus: /-/ready == 200 (fallback /api/v1/status/runtimeinfo == 200)
- If not all services found:
    * On Windows, attempt to run scripts/auto_stack.ps1 to auto-start the stack.
  * Re-check health after the attempt.
- Export G6_INFLUX_URL to match the detected scheme/port for downstream code.
- Print a concise confirmation summary and return result to caller.

This module is intentionally self-contained (stdlib only) and safe to import.
"""
from __future__ import annotations

import os
import socket
import ssl
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent

@dataclass
class ServiceStatus:
    ok: bool
    url: str | None
    details: str = ""

@dataclass
class StackSummary:
    prometheus: ServiceStatus
    grafana: ServiceStatus
    influx: ServiceStatus


def _tcp_check(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _http_get(url: str, timeout: float = 1.5, insecure: bool = True) -> tuple[int, bytes]:
    """Minimal HTTP(S) GET using stdlib with optional insecure TLS."""
    import urllib.request
    ctx = None
    if url.startswith("https") and insecure:
        ctx = ssl.SSLContext()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:  # type: ignore[arg-type]
            return resp.getcode(), resp.read()
    except Exception as e:
        # Try to capture HTTP error codes
        if hasattr(e, 'code'):
            return int(e.code), b""
        return -1, b""


def _detect_grafana(hosts=("localhost","127.0.0.1"), ports=range(3000, 3011)) -> ServiceStatus:
    for p in ports:
        for h in hosts:
            if not _tcp_check(h, p, 0.5):
                continue
            code, _ = _http_get(f"http://{h}:{p}/api/health", 1.5)
            if code == 200:
                return ServiceStatus(True, f"http://{h}:{p}")
    return ServiceStatus(False, None, details="Grafana not healthy on 3000-3010")


def _detect_influx(hosts=("localhost","127.0.0.1"), ports=range(8086, 8097)) -> ServiceStatus:
    schemes = ("http", "https")
    for p in ports:
        for h in hosts:
            # Try /health and /ping across http/https; accept 200 or 401/403; ping accepts 204
            for scheme in schemes:
                base = f"{scheme}://{h}:{p}"
                code, _ = _http_get(f"{base}/health", 1.2, insecure=True)
                if code in (200, 401, 403):
                    os.environ["G6_INFLUX_URL"] = base
                    return ServiceStatus(True, base)
                code2, _ = _http_get(f"{base}/ping", 1.2, insecure=True)
                if code2 in (200, 204, 401, 403):
                    os.environ["G6_INFLUX_URL"] = base
                    return ServiceStatus(True, base)
            # Last resort: raw TCP reachable -> tentatively OK (owner unknown in pure Python)
            if _tcp_check(h, p, 0.5):
                base = f"http://{h}:{p}"
                os.environ["G6_INFLUX_URL"] = base
                return ServiceStatus(True, base, details="TCP only (health gated)")
    return ServiceStatus(False, None, details="Influx not reachable on 8086-8096")


def _detect_prometheus(hosts=("localhost","127.0.0.1"), ports=range(9090, 9101)) -> ServiceStatus:
    # First honor an explicit env override if present (useful for custom runs)
    env_url = os.environ.get("G6_PROM_URL")
    if env_url:
        try:
            code, _ = _http_get(f"{env_url}/-/ready", 1.2)
            if code == 200:
                return ServiceStatus(True, env_url)
            code2, _ = _http_get(f"{env_url}/api/v1/status/runtimeinfo", 1.2)
            if code2 == 200:
                return ServiceStatus(True, env_url)
        except Exception:
            pass
    # Scan common local ports (matches auto_stack.ps1 behavior which may choose next free port)
    for p in ports:
        for h in hosts:
            if not _tcp_check(h, p, 0.5):
                continue
            # Prefer /-/ready then fallback runtimeinfo
            code, _ = _http_get(f"http://{h}:{p}/-/ready", 1.2)
            if code == 200:
                return ServiceStatus(True, f"http://{h}:{p}")
            code2, _ = _http_get(f"http://{h}:{p}/api/v1/status/runtimeinfo", 1.2)
            if code2 == 200:
                return ServiceStatus(True, f"http://{h}:{p}")
    return ServiceStatus(False, None, details="Prometheus not ready on 9090-9100")


def _is_windows() -> bool:
    return os.name == "nt"


def _attempt_ps_autostart(timeout_sec: float = 45.0) -> None:
    ps1 = _SCRIPT_DIR / "auto_stack.ps1"
    if not ps1.exists():
        return
    # Issue a minimal auto-resolve attempt; rely on script's built-in discovery and health checks
    cmd = [
        "powershell", "-ExecutionPolicy", "Bypass", "-File", str(ps1)
    ]
    try:
        # Surface env override for visibility in logs
        if os.environ.get("G6_INFLUXD_EXE"):
            print(f"[auto-resolve] Using G6_INFLUXD_EXE={os.environ['G6_INFLUXD_EXE']}")
        subprocess.run(cmd, cwd=str(_PROJECT_ROOT), timeout=timeout_sec, check=False)
    except Exception:
        # Ignore launcher failures; we'll re-check health below
        pass


def ensure_stack(auto_start: bool = True) -> StackSummary:
    # First pass detection
    prom = _detect_prometheus()
    graf = _detect_grafana()
    infl = _detect_influx()

    need_start = auto_start and (not prom.ok or not graf.ok or not infl.ok)
    if need_start and _is_windows():
        _attempt_ps_autostart()
        # Short backoff + retry window
        for _ in range(8):
            time.sleep(1.0)
            prom = prom if prom.ok else _detect_prometheus()
            graf = graf if graf.ok else _detect_grafana()
            infl = infl if infl.ok else _detect_influx()
            if prom.ok and graf.ok and infl.ok:
                break

    # Final export guard for Influx URL
    if infl.ok and infl.url:
        os.environ["G6_INFLUX_URL"] = infl.url

    return StackSummary(prometheus=prom, grafana=graf, influx=infl)


def print_summary(summary: StackSummary) -> None:
    print("\n--- Observability Stack Summary ---")
    p = summary.prometheus
    g = summary.grafana
    i = summary.influx
    print(f"Prometheus: {'OK' if p.ok else 'DOWN'}  url={p.url or '-'}")
    print(f"Grafana:    {'OK' if g.ok else 'DOWN'}  url={g.url or '-'}")
    print(f"InfluxDB:   {'OK' if i.ok else 'DOWN'}  url={i.url or '-'}")
    print("-----------------------------------\n")


def main(argv: list[str]) -> int:
    auto = True
    if "--no-autostart" in argv:
        auto = False
    summary = ensure_stack(auto_start=auto)
    print_summary(summary)
    # Influx is mandatory
    if not summary.influx.ok:
        print("ERROR: InfluxDB is mandatory and is not reachable.", file=sys.stderr)
        return 3
    return 0

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
