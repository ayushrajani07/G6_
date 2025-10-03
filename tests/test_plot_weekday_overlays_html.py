import os
from pathlib import Path

import importlib


def run_plot_script(monkeypatch, tmp_path: Path, layout: str):
    # Ensure a deterministic Plotly bundle URL via env so we can assert it
    env_plotly_url = "https://example.com/plotly-2.x.min.js"
    monkeypatch.setenv("G6_PLOTLY_JS_PATH", env_plotly_url)

    out_file = tmp_path / f"overlays_{layout}.html"
    # Import the plotting script as a module
    mod = importlib.import_module("scripts.plot_weekday_overlays")
    # Build argv for the script
    argv = [
        "plot_weekday_overlays.py",
        "--live-root",
        "data/g6_data",
        "--weekday-root",
        "data/weekday_master",
        "--index",
        "NIFTY",
        "--expiry-tag",
        "this_week",
        "--offset",
        "ATM",
        "--output",
        str(out_file),
        "--layout",
        layout,
        "--theme",
        "dark",
        "--live-endpoint",
        "http://127.0.0.1:12345/live",
        "--live-interval-ms",
        "1234",
        "--enable-zscore",
        "--enable-bands",
        "--bands-multiplier",
        "1.5",
    ]
    # Patch argv and run main
    monkeypatch.setenv("PYTHONWARNINGS", "ignore")
    monkeypatch.setenv("G6_OVERLAY_VIS_MEMORY_LIMIT_MB", "256")
    monkeypatch.setenv("G6_OVERLAY_VIS_CHUNK_SIZE", "1024")
    monkeypatch.setenv("G6_TIME_TOLERANCE_SECONDS", "0")

    # Deprecated panels env removed; ensure absence
    monkeypatch.delenv("G6_SUMMARY_PANELS_MODE", raising=False)

    # Use monkeypatch to set sys.argv
    monkeypatch.setenv("_PYTEST_RUN", "1")
    import sys
    old_argv = sys.argv
    try:
        sys.argv = argv
        mod.main()
    finally:
        sys.argv = old_argv

    assert out_file.exists(), f"Expected output HTML not found: {out_file}"
    html = out_file.read_text(encoding="utf-8")
    return html, env_plotly_url


def assert_common_wiring(html: str, env_plotly_url: str):
    # Theme CSS included
    assert "src/assets/css/overlay_themes.css" in html
    # Live updates JS included
    assert "src/assets/js/overlay_live_updates.js" in html
    # Plotly bundle tag comes from env override
    assert env_plotly_url in html
    # Client config JSON contains endpoint, interval, and theme
    assert '"endpoint": "http://127.0.0.1:12345/live"' in html
    assert '"intervalMs": 1234' in html
    assert '"theme": "dark"' in html


def test_plot_weekday_overlays_by_index_html_wiring(monkeypatch, tmp_path):
    html, env_url = run_plot_script(monkeypatch, tmp_path, layout="by-index")
    assert_common_wiring(html, env_url)
    # Basic sanity: page title and header present
    assert "Weekday Overlays" in html


def test_plot_weekday_overlays_grid_html_wiring(monkeypatch, tmp_path):
    html, env_url = run_plot_script(monkeypatch, tmp_path, layout="grid")
    assert_common_wiring(html, env_url)
    # Grid-specific UI bits present
    assert "Filters:" in html
    assert "panel-grid" in html


def test_plot_weekday_overlays_tabs_html_wiring(monkeypatch, tmp_path):
    html, env_url = run_plot_script(monkeypatch, tmp_path, layout="tabs")
    assert_common_wiring(html, env_url)
    # Tabs-specific markers
    assert "class='tabs'" in html or 'class="tabs"' in html
    # first tab gets 'tab active' class; accept either quoting style
    assert "class='tab " in html or 'class="tab ' in html
    assert "class='tab-content'" in html or 'class="tab-content"' in html


def test_plot_weekday_overlays_split_html_wiring(monkeypatch, tmp_path):
    html, env_url = run_plot_script(monkeypatch, tmp_path, layout="split")
    assert_common_wiring(html, env_url)
    # Split layout markers
    assert "split-grid" in html
    # Sync script includes plotly_relayout usage
    assert "plotly_relayout" in html
