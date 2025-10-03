"""Assets helper for resolving client-side libraries (like plotly.js).

Usage:
- get_plotly_js_src(): returns a script src suitable for embedding in HTML.
  Resolution order:
    1) Env var G6_PLOTLY_JS_PATH (absolute path or URL)
    2) Local default at 'src/assets/js/plotly.min.js' if exists
    3) Pinned CDN URL (versioned) as a last resort
"""
from __future__ import annotations

import os
from pathlib import Path


def get_plotly_js_src() -> str:
    override = os.environ.get("G6_PLOTLY_JS_PATH", "").strip()
    if override:
        # Allow both file paths and URLs; caller just embeds in <script src>
        # If it's a file path, prefer relative href from project root if possible
        return override
    # Check local default
    local_path = Path("src/assets/js/plotly.min.js")
    if local_path.exists():
        # Use a project-relative path so HTML can be opened directly in a browser
        return str(local_path).replace("\\", "/")
    # Fallback to pinned CDN
    version = os.environ.get("G6_PLOTLY_VERSION", "2.26.0").strip() or "2.26.0"
    return f"https://cdn.plot.ly/plotly-{version}.min.js"
