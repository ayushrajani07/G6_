"""Reference Python SSE client for G6 summary stream.

Features:
- Connects to /summary/events (unified or standalone SSE server)
- Optional API token, request ID, and User-Agent headers
- Automatic reconnect with exponential backoff + jitter
- Parses SSE frames (event: <type>\n data: <json>)
- Maintains lightweight in-memory state of panels using hello/full_snapshot + panel_update/panel_diff
- Heartbeat handling (updates last_seen timestamp)
- Graceful stop via KeyboardInterrupt

Usage:
    python clients/python_sse_client.py --url http://127.0.0.1:9329/summary/events \
        --api-token secret123 --structured

Requires only stdlib (no external dependencies).
"""
from __future__ import annotations
import argparse, json, sys, time, random, urllib.request, urllib.error, io, threading
from typing import Dict, Any, Optional

class PanelState:
    def __init__(self) -> None:
        self.panels: Dict[str, Any] = {}
        self.hashes: Dict[str, str] = {}
        self.last_heartbeat: float = 0.0
        self.last_event_ts: float = 0.0
        self.schema_version: Optional[str] = None

    def apply_event(self, etype: str, data: Any) -> None:
        self.last_event_ts = time.time()
        if etype == 'hello':
            if isinstance(data, dict):
                self.hashes = data.get('panel_hashes') or {}
                self.schema_version = data.get('schema_version')
        elif etype == 'full_snapshot':
            if isinstance(data, dict):
                self.panels = data.get('panels') or {}
        elif etype == 'panel_update':
            if isinstance(data, dict):
                # data may include 'panels': {id: panel}
                panels = data.get('panels') or {}
                for k,v in panels.items():
                    self.panels[k] = v
        elif etype == 'panel_diff':
            # structured diff: panels + maybe removed (future)
            if isinstance(data, dict):
                for k,v in (data.get('panels') or {}).items():
                    self.panels[k] = v
        elif etype == 'heartbeat':
            self.last_heartbeat = time.time()
        elif etype == 'bye':
            # server shutting down
            pass
        # truncated / others ignored

class SSEClient:
    def __init__(self, url: str, api_token: Optional[str] = None, request_id: Optional[str] = None, user_agent: str = 'G6PythonClient/1.0', structured: bool = False) -> None:
        self.url = url
        self.api_token = api_token
        self.request_id = request_id
        self.user_agent = user_agent
        self.structured = structured
        self.state = PanelState()
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    # Basic SSE frame parser generator
    def _iter_events(self, stream: io.TextIOBase):
        event_type = None
        data_buf = []
        for raw in stream:
            if self._stop.is_set():
                break
            line = raw.rstrip('\n')
            if line.startswith('event:'):
                event_type = line.split(':',1)[1].strip()
            elif line.startswith('data:'):
                data_buf.append(line.split(':',1)[1].lstrip())
            elif line == '':  # frame boundary
                if event_type:
                    payload = '\n'.join(data_buf) if data_buf else ''
                    yield event_type, payload
                event_type = None
                data_buf = []
        # flush (incomplete frame ignored)

    def _open(self):
        headers = {}
        if self.api_token:
            headers['X-API-Token'] = self.api_token
        if self.request_id:
            headers['X-Request-ID'] = self.request_id
        headers['User-Agent'] = self.user_agent
        req = urllib.request.Request(self.url, headers=headers, method='GET')
        return urllib.request.urlopen(req, timeout=30)

    def run(self, max_backoff: float = 30.0) -> None:
        attempt = 0
        while not self._stop.is_set():
            try:
                attempt += 1
                print(f"[sse] connecting attempt={attempt} url={self.url}")
                with self._open() as resp:
                    if resp.status != 200:
                        print(f"[sse] non-200 status: {resp.status}")
                        raise RuntimeError(f"status {resp.status}")
                    print("[sse] connected")
                    attempt = 0  # reset on success
                    # Wrap binary into text
                    stream = io.TextIOWrapper(resp, encoding='utf-8', newline='\n')
                    for etype, payload in self._iter_events(stream):
                        try:
                            data = json.loads(payload) if payload else None
                        except Exception:
                            data = None
                        self.state.apply_event(etype, data)
                        if etype in ('hello','full_snapshot'):
                            print(f"[sse] {etype} received panels={len(self.state.panels)} hashes={len(self.state.hashes)}")
                        elif etype == 'panel_update':
                            print(f"[sse] update panels_now={len(self.state.panels)}")
                        elif etype == 'panel_diff':
                            print(f"[sse] diff applied panels_now={len(self.state.panels)}")
                        elif etype == 'heartbeat':
                            print("[sse] ♥ heartbeat")
                        elif etype == 'bye':
                            print("[sse] server goodbye; will reconnect")
                            break
            except KeyboardInterrupt:
                print("[sse] interrupted; stopping")
                self.stop()
            except Exception as e:
                delay = min(max_backoff, (2 ** min(attempt, 8)) + random.uniform(0, 0.5))
                print(f"[sse] error: {e}; reconnecting in {delay:.2f}s")
                time.sleep(delay)
        print("[sse] stopped")

def main() -> int:
    ap = argparse.ArgumentParser(description="G6 SSE Python reference client")
    ap.add_argument('--url', default='http://127.0.0.1:9329/summary/events')
    ap.add_argument('--api-token')
    ap.add_argument('--request-id')
    ap.add_argument('--user-agent', default='G6PythonClient/1.0')
    ap.add_argument('--structured', action='store_true', help='Expect panel_diff events (sets local flag only)')
    args = ap.parse_args()

    client = SSEClient(args.url, api_token=args.api_token, request_id=args.request_id, user_agent=args.user_agent, structured=args.structured)
    client.run()
    return 0

if __name__ == '__main__':  # pragma: no cover
    sys.exit(main())
