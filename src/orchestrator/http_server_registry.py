"""Central registry for catalog HTTP server instance.

Avoids stale server persistence across module reloads during tests by holding
singleton references outside the reloaded module namespace.
"""
from __future__ import annotations

import threading
from http.server import ThreadingHTTPServer

HTTP_SERVER: ThreadingHTTPServer | None = None
SERVER_THREAD: threading.Thread | None = None

__all__ = ["HTTP_SERVER", "SERVER_THREAD"]
