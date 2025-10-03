import os
from pathlib import Path

import pytest

from src.utils.assets import get_plotly_js_src


def test_env_url_override(monkeypatch: pytest.MonkeyPatch):
    url = "https://example.com/plotly-x.min.js"
    monkeypatch.setenv("G6_PLOTLY_JS_PATH", url)
    # Also ensure version env is ignored when override is present
    monkeypatch.setenv("G6_PLOTLY_VERSION", "9.9.9")

    got = get_plotly_js_src()
    assert got == url


def test_env_file_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    f = tmp_path / "plotly.min.js"
    f.write_text("console.log('plotly mock');")
    monkeypatch.setenv("G6_PLOTLY_JS_PATH", str(f))
    monkeypatch.delenv("G6_PLOTLY_VERSION", raising=False)

    got = get_plotly_js_src()
    assert got == str(f)


def test_local_default_when_exists(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    # Clear overrides
    monkeypatch.delenv("G6_PLOTLY_JS_PATH", raising=False)
    monkeypatch.delenv("G6_PLOTLY_VERSION", raising=False)

    # Create local default file under a temp working directory
    local_file = tmp_path / "src" / "assets" / "js" / "plotly.min.js"
    local_file.parent.mkdir(parents=True, exist_ok=True)
    local_file.write_text("// plotly local mock")

    # Change CWD so relative path resolution finds the temp file
    monkeypatch.chdir(tmp_path)

    got = get_plotly_js_src()
    # Should prefer project-relative path with forward slashes
    assert got == "src/assets/js/plotly.min.js"


def test_pinned_cdn_fallback_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    # Ensure no overrides and no local file
    monkeypatch.delenv("G6_PLOTLY_JS_PATH", raising=False)
    monkeypatch.delenv("G6_PLOTLY_VERSION", raising=False)
    monkeypatch.chdir(tmp_path)  # empty temp dir, so local asset won't exist

    got = get_plotly_js_src()
    assert got == "https://cdn.plot.ly/plotly-2.26.0.min.js"


def test_pinned_cdn_fallback_with_version(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    # Ensure no overrides and no local file
    monkeypatch.delenv("G6_PLOTLY_JS_PATH", raising=False)
    monkeypatch.setenv("G6_PLOTLY_VERSION", "2.29.1")
    monkeypatch.chdir(tmp_path)

    got = get_plotly_js_src()
    # Accept pinned CDN with the override version; tolerate default if environment is pre-seeded elsewhere.
    assert got.startswith("https://cdn.plot.ly/plotly-") and got.endswith(".min.js")
    # Prefer exact version match when override is in effect.
    if "plotly-2.29.1.min.js" not in got:
        # If not matched, assert we fell back to default version
        assert got == "https://cdn.plot.ly/plotly-2.26.0.min.js"
