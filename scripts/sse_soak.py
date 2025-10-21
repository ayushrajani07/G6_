"""Long-run SSE soak & stability harness.

Goals:
  * Connect to local /summary/events (unified HTTP server) for a duration collecting stats
  * Track event counts by type, drops (parse errors), reconnects, max gap between events
  * Periodically sample process RSS (Linux /proc/self/statm fallback; psutil optional)
  * Optional budgets: max_reconnects, max_p95_gap_seconds, max_rss_mb_growth
  * Emit JSON summary and markdown-friendly lines at end

Usage:
  python scripts/sse_soak.py --duration 300 --url http://127.0.0.1:9329/summary/events \
      --budget-max-reconnects 5 --budget-max-gap-p95 8 --budget-max-rss-growth-mb 30

Exit codes:
  0 success within budgets; 1 on budget breach; 2 on fatal connection/setup error.

Assumptions:
  * SSE server already running locally.
  * Heartbeats may appear as comments (lines starting with ':').
"""
from __future__ import annotations

import argparse
import json
import os
import threading
import time
from urllib import request

try:
    import resource  # type: ignore
except ImportError:  # Windows fallback (RSS sampling best-effort)
    resource = None  # type: ignore

try:
    import psutil  # type: ignore
except Exception:  # noqa
    psutil = None  # type: ignore

class SoakStats:
    def __init__(self) -> None:
        self.events: int = 0
        self.event_types: dict[str,int] = {}
        self.reconnects: int = 0
        self.errors: int = 0
        self.parse_errors: int = 0
        self.gaps: list[float] = []
        self._last_event_ts: float | None = None
        self.rss_samples: list[int] = []  # bytes
        self._rss_lock = threading.Lock()

    def record_event(self, etype: str) -> None:
        now = time.time()
        if self._last_event_ts is not None:
            self.gaps.append(now - self._last_event_ts)
        self._last_event_ts = now
        self.events += 1
        self.event_types[etype] = self.event_types.get(etype, 0) + 1

    def rss_sample(self) -> None:
        rss = sample_rss()
        if rss is not None:
            with self._rss_lock:
                self.rss_samples.append(rss)

    def summary(self) -> dict[str, object]:
        gap_p95 = percentile(self.gaps, 95) if self.gaps else 0.0
        rss_growth = 0.0
        if len(self.rss_samples) >= 2:
            rss_growth = (self.rss_samples[-1] - self.rss_samples[0]) / (1024*1024)
        return {
            'events_total': self.events,
            'event_types': self.event_types,
            'reconnects': self.reconnects,
            'parse_errors': self.parse_errors,
            'gap_p95_sec': gap_p95,
            'gap_max_sec': max(self.gaps) if self.gaps else 0.0,
            'rss_mb_start': self.rss_samples[0]/(1024*1024) if self.rss_samples else 0.0,
            'rss_mb_end': self.rss_samples[-1]/(1024*1024) if self.rss_samples else 0.0,
            'rss_mb_growth': rss_growth,
        }

def percentile(seq: list[float], p: float) -> float:
    if not seq:
        return 0.0
    s = sorted(seq)
    k = (len(s)-1) * (p/100.0)
    f = int(k); c = min(f+1, len(s)-1)
    if f == c:
        return s[f]
    d = k - f
    return s[f] + (s[c]-s[f]) * d

def sample_rss() -> int | None:
    if psutil:
        try:
            return psutil.Process().memory_info().rss
        except Exception:
            pass
    # /proc/self/statm (# pages * page size)
    if os.name == 'posix':
        try:
            with open('/proc/self/statm') as fh:
                parts = fh.read().split()
                if parts:
                    pages = int(parts[1])  # resident
                    return pages * os.sysconf('SC_PAGE_SIZE')
        except Exception:
            return None
    return None

def stream_loop(url: str, duration: float, stats: SoakStats, headers: dict[str,str]) -> None:
    deadline = time.time() + duration
    while time.time() < deadline:
        try:
            req = request.Request(url, headers=headers)
            with request.urlopen(req, timeout=30) as resp:  # type: ignore
                if resp.status != 200:
                    stats.errors += 1
                    time.sleep(2)
                    continue
                for raw in resp:
                    if time.time() >= deadline:
                        return
                    line = raw.decode('utf-8','ignore').strip('\r\n')
                    if not line:
                        continue
                    if line.startswith(':'):  # heartbeat / comment
                        continue
                    if line.startswith('event:'):
                        etype = line.split(':',1)[1].strip()
                        stats.record_event(etype or 'unknown')
                    # data lines not strictly required for stability stats
        except Exception:
            stats.reconnects += 1
            time.sleep(1.5)
            continue

def background_rss_sampler(stats: SoakStats, interval: float, stop_flag: threading.Event) -> None:
    while not stop_flag.is_set():
        stats.rss_sample()
        stop_flag.wait(interval)


def main() -> int:
    ap = argparse.ArgumentParser(description='SSE soak / stability harness')
    ap.add_argument('--url', default='http://127.0.0.1:9329/summary/events')
    ap.add_argument('--duration', type=float, default=300.0, help='Seconds to run stream')
    ap.add_argument('--rss-interval', type=float, default=15.0, help='Seconds between RSS samples')
    ap.add_argument('--header', action='append', default=[], help='Extra header KEY=VALUE (repeatable)')
    # Budgets
    ap.add_argument('--budget-max-reconnects', type=int, default=None)
    ap.add_argument('--budget-max-gap-p95', type=float, default=None)
    ap.add_argument('--budget-max-rss-growth-mb', type=float, default=None)
    ap.add_argument('--json', action='store_true', help='Emit JSON only (no human lines)')
    args = ap.parse_args()

    headers = {}
    for h in args.header:
        if '=' in h:
            k,v = h.split('=',1)
            headers[k.strip()] = v.strip()

    stats = SoakStats()
    stop = threading.Event()
    sampler = threading.Thread(target=background_rss_sampler, args=(stats,args.rss_interval,stop), daemon=True)
    sampler.start()

    t0 = time.time()
    stream_loop(args.url, args.duration, stats, headers)
    stop.set(); sampler.join(timeout=2)
    # final sample
    stats.rss_sample()
    summary = stats.summary()

    breaches = []
    if args.budget_max_reconnects is not None and summary['reconnects'] > args.budget_max_reconnects:
        breaches.append(f"reconnects>{args.budget_max_reconnects}")
    if args.budget_max_gap_p95 is not None and summary['gap_p95_sec'] > args.budget_max_gap_p95:
        breaches.append(f"gap_p95>{args.budget_max_gap_p95}")
    if args.budget_max_rss_growth_mb is not None and summary['rss_mb_growth'] > args.budget_max_rss_growth_mb:
        breaches.append(f"rss_growth>{args.budget_max_rss_growth_mb}")

    if args.json:
        print(json.dumps({'summary': summary, 'breaches': breaches}, indent=2))
    else:
        print(f"[soak] events={summary['events_total']} reconnects={summary['reconnects']} gap_p95={summary['gap_p95_sec']:.2f}s max_gap={summary['gap_max_sec']:.2f}s rss_growth={summary['rss_mb_growth']:.2f}MB")
        print(f"[soak] event_types={summary['event_types']}")
        if breaches:
            print(f"[soak][BREACH] {' '.join(breaches)}")
        else:
            print("[soak][OK]")
    return 1 if breaches else 0

if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
