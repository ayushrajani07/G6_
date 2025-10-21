"""FastAPI WebSocket broadcast service for G6 runtime status.

Endpoints:
  GET /status        -> latest JSON status (from status file)
  WS  /ws            -> push updates when file changes

Environment / Config:
  STATUS_FILE (env)  -> path to runtime status file (default: data/runtime_status.json)
  POLL_INTERVAL      -> seconds between file mtime polls (float, default 1.0)
  HOST, PORT         -> uvicorn host/port (defaults 127.0.0.1:8765 if not provided via CLI)

Run:
  uvicorn src.console.ws_service:app --reload --port 8765
  # or specify file
  STATUS_FILE=data/runtime_status.json uvicorn src.console.ws_service:app --port 8765

Design:
  - Single background task polls mtime.
  - On change, loads JSON and broadcasts to connected WebSocket clients.
  - Maintains last payload; sends immediately on new connection.
  - JSON parsing errors are ignored (atomic replace normally prevents partial reads).
"""
from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

STATUS_FILE = os.environ.get("STATUS_FILE", "data/runtime_status.json")
POLL_INTERVAL = float(os.environ.get("POLL_INTERVAL", "1.0"))

@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[override]
    # Startup: begin background watch loop
    try:
        await broadcaster.start()
    except Exception:
        pass
    yield
    # Shutdown: nothing special; background task will end with process
    # (could add cancellation if needed in future)

app = FastAPI(title="G6 Runtime Status WebSocket Service", version="1.0.0", lifespan=lifespan)

class StatusBroadcaster:
    def __init__(self, path: str):
        self.path = path
        self.clients: set[WebSocket] = set()
        self._last_mtime: float = 0.0
        self._last_payload: dict | None = None
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    async def start(self):
        if self._task is None:
            self._task = asyncio.create_task(self._watch_loop())

    async def register(self, ws: WebSocket):
        await ws.accept()
        async with self._lock:
            if self._last_payload is not None:
                await ws.send_json(self._last_payload)
        self.clients.add(ws)

    async def unregister(self, ws: WebSocket):
        self.clients.discard(ws)

    async def broadcast(self, payload: dict):
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    async def _watch_loop(self):
        while True:
            try:
                mtime = os.path.getmtime(self.path)
                if mtime != self._last_mtime:
                    self._last_mtime = mtime
                    try:
                        with open(self.path) as f:
                            payload = json.load(f)
                        async with self._lock:
                            self._last_payload = payload
                        await self.broadcast(payload)
                    except (FileNotFoundError, json.JSONDecodeError):
                        pass
                    except Exception:
                        pass
            except FileNotFoundError:
                pass
            await asyncio.sleep(POLL_INTERVAL)

broadcaster = StatusBroadcaster(STATUS_FILE)

@app.get("/status")
async def get_status():
    if broadcaster._last_payload is not None:
        return JSONResponse(broadcaster._last_payload)
    try:
        with open(STATUS_FILE) as f:
            payload = json.load(f)
        return JSONResponse(payload)
    except Exception:
        return JSONResponse({"error": "status unavailable"}, status_code=503)

@app.websocket("/ws")
async def ws_status(ws: WebSocket):
    await broadcaster.register(ws)
    try:
        while True:
            # Keep connection alive; we don't expect client messages yet.
            await ws.receive_text()
    except WebSocketDisconnect:
        await broadcaster.unregister(ws)
    except Exception:
        await broadcaster.unregister(ws)

# Optional: simple root
@app.get("/")
async def root():
    return {"service": "g6-status", "status_file": STATUS_FILE, "clients": len(broadcaster.clients)}
