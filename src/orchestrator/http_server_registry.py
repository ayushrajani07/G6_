"""Central registry for catalog HTTP server instance.

Avoids stale server persistence across module reloads during tests by holding
singleton references outside the reloaded module namespace.
"""
from __future__ import annotations
from typing import Optional
import threading
from http.server import ThreadingHTTPServer

HTTP_SERVER: Optional[ThreadingHTTPServer] = None
SERVER_THREAD: Optional[threading.Thread] = None

__all__ = ["HTTP_SERVER", "SERVER_THREAD"]
