"""SSE load / throughput harness.

Purpose:
    Simulate N concurrent clients consuming the /summary/events SSE endpoint and
    report:
      * Time to first event (hello)
      * Time to full_snapshot
      * Aggregate events received (per type)
      * Per-connection events/sec (steady state)
      * Dropped / parse errors

Usage (PowerShell examples):
    # Basic 10 clients for 15s
    python scripts/summary/bench_sse.py --clients 10 --duration 15

    # Auth token + custom host/port, limit to panel_update events only
    $env:G6_SSE_API_TOKEN='secret'; \
      python scripts/summary/bench_sse.py -H 127.0.0.1 -p 9320 -t secret --clients 25 --duration 30

    # JSON output for CI dashboards
    python scripts/summary/bench_sse.py --clients 5 --json > bench_out.json

Implementation Notes:
    * Uses threading + requests streaming for simplicity (requests is ubiquitous).
      If dependency footprint is a concern, we can add a fallback urllib client.
    * Focus is observability vs. perfect precision; timing uses perf_counter.
    * Designed to run against a locally running unified loop with SSE HTTP enabled.
    * Does NOT start the loop itself; compose with existing scripts / tasks.

Exit Code:
    0 on success collecting at least one full_snapshot across all clients.
    1 if no client reached full_snapshot.

Future Enhancements (Phase follow-up):
    - Async variant (httpx + trio) for higher concurrency scaling.
    - Latency percentiles for panel_update events.
    - Optional pprof-like CPU sampling around harness window.
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import sys
import threading
import time
from dataclasses import dataclass, field

try:
    import requests  # type: ignore
except Exception:  # pragma: no cover
    print("requests library required for bench_sse harness (pip install requests)", file=sys.stderr)
    raise

@dataclass
class ClientStats:
    id: int
    hello_at: float | None = None
    snapshot_at: float | None = None
    events: int = 0
    by_type: dict[str,int] = field(default_factory=dict)
    parse_errors: int = 0
    last_event_at: float | None = None
    stop: bool = False

    def record(self, etype: str, now: float) -> None:
        self.events += 1
        self.by_type[etype] = self.by_type.get(etype, 0) + 1
        self.last_event_at = now
        if etype == 'hello' and self.hello_at is None:
            self.hello_at = now
        elif etype == 'full_snapshot' and self.snapshot_at is None:
            self.snapshot_at = now


_EVENT_PREFIX = 'event:'
_DATA_PREFIX = 'data:'

def _parse_event_lines(lines: list[str]) -> tuple[str, str] | None:
    etype = None
    data_lines: list[str] = []
    for ln in lines:
        if ln.startswith(_EVENT_PREFIX):
            etype = ln[len(_EVENT_PREFIX):].strip()
        elif ln.startswith(_DATA_PREFIX):
            data_lines.append(ln[len(_DATA_PREFIX):].strip())
    if not etype:
        return None
    return etype, '\n'.join(data_lines)

def _client_worker(
    idx: int,
    url: str,
    token: str | None,
    stats: ClientStats,
    stop_time: float,
    qerr: queue.Queue[str],
) -> None:
    headers = {'Accept': 'text/event-stream'}
    if token:
        headers['X-API-Token'] = token
    try:
        with requests.get(url, headers=headers, stream=True, timeout=10) as resp:
            if resp.status_code != 200:
                qerr.put(f"client {idx} non-200 status {resp.status_code}")
                return
            buf: list[str] = []
            for raw in resp.iter_lines(decode_unicode=True):
                if stats.stop or time.time() >= stop_time:
                    break
                if raw is None:
                    continue
                line = raw.strip('\n')
                if not line:  # event boundary
                    if buf:
                        evt = _parse_event_lines(buf)
                        buf.clear()
                        if not evt:
                            stats.parse_errors += 1
                            continue
                        etype, payload = evt
                        now = time.perf_counter()
                        stats.record(etype, now)
                    continue
                buf.append(line)
    except Exception as e:  # pragma: no cover - network issues
        qerr.put(f"client {idx} error: {e}")


def run_bench(url: str, clients: int, duration: float, token: str | None) -> dict:
    start_perf = time.perf_counter()
    stop_time = time.time() + duration
    stats: list[ClientStats] = [ClientStats(i) for i in range(clients)]
    qerr: queue.Queue[str] = queue.Queue()
    threads: list[threading.Thread] = []
    for s in stats:
        t = threading.Thread(target=_client_worker, args=(s.id, url, token, s, stop_time, qerr), daemon=True)
        t.start()
        threads.append(t)
    # Monitor
    while time.time() < stop_time and any(t.is_alive() for t in threads):
        time.sleep(0.25)
    # Signal stop & join
    for s in stats:
        s.stop = True
    for t in threads:
        t.join(timeout=2)
    errors = []
    # PERF203: draining a queue typically uses try/except; producers are joined, so this is safe
    while not qerr.empty():  # noqa: PERF203
        try:
            errors.append(qerr.get_nowait())
        except Exception:  # noqa: PERF203
            break
    # Aggregate
    agg_events = sum(s.events for s in stats)
    full_snapshots = sum(1 for s in stats if s.snapshot_at is not None)
    first_hello = min((s.hello_at for s in stats if s.hello_at is not None), default=None)
    first_snapshot = min((s.snapshot_at for s in stats if s.snapshot_at is not None), default=None)
    elapsed_perf = time.perf_counter() - start_perf
    steady_window = max(0.001, elapsed_perf - 2.0)  # discount first 2s ramp where possible
    per_conn_eps = [ (s.events / steady_window) for s in stats if s.events > 0 ]
    result = {
        'url': url,
        'clients': clients,
        'duration_requested_sec': duration,
        'elapsed_sec': elapsed_perf,
        'aggregate_events': agg_events,
        'events_per_sec_total': agg_events / elapsed_perf if elapsed_perf else 0.0,
        'median_events_per_sec_conn': (sorted(per_conn_eps)[len(per_conn_eps)//2] if per_conn_eps else 0.0),
        'first_hello_latency_sec': (first_hello - start_perf) if first_hello else None,
        'first_full_snapshot_latency_sec': (first_snapshot - start_perf) if first_snapshot else None,
        'full_snapshot_clients': full_snapshots,
        'by_type_total': _merge_dicts([s.by_type for s in stats]),
        'parse_errors_total': sum(s.parse_errors for s in stats),
        'connection_errors': errors,
    }
    return result


def _merge_dicts(dicts: list[dict[str,int]]) -> dict[str,int]:
    out: dict[str,int] = {}
    for d in dicts:
        for k,v in d.items():
            out[k] = out.get(k,0)+v
    return out


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="SSE load / throughput harness")
    ap.add_argument('-H', '--host', default='127.0.0.1', help='SSE host (default 127.0.0.1)')
    ap.add_argument('-p', '--port', type=int, default=int(os.getenv('G6_SSE_HTTP_PORT','9320')), help='SSE port')
    ap.add_argument('--path', default='/summary/events', help='SSE path (default /summary/events)')
    ap.add_argument('-c', '--clients', type=int, default=5, help='Concurrent client connections')
    ap.add_argument('-d', '--duration', type=int, default=15, help='Duration seconds (wall)')
    ap.add_argument('-t', '--token', default=os.getenv('G6_SSE_API_TOKEN'), help='Auth token (X-API-Token header)')
    ap.add_argument('--json', action='store_true', help='Emit JSON only (machine readable)')
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    ns = _parse_args(argv)
    url = f"http://{ns.host}:{ns.port}{ns.path}"
    res = run_bench(url, ns.clients, float(ns.duration), ns.token)
    # Basic success criteria: at least one client got full snapshot
    success = res.get('full_snapshot_clients', 0) > 0
    if ns.json:
        print(json.dumps(res, indent=2, sort_keys=True))
    else:
        print("SSE Bench Result:")
        for k,v in res.items():
            print(f"  {k}: {v}")
        if not success:
            print("\nWARNING: No client received a full_snapshot event.", file=sys.stderr)
    return 0 if success else 1

if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
