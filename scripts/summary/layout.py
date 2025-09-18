from __future__ import annotations
from typing import Any, Dict, Optional

from scripts.summary.env import _env_true, _env_min_col_width, panel_height
from scripts.summary.derive import derive_indices
from scripts.summary.data_source import _use_panels_json, _read_panel_json


def build_layout(status: Dict[str, Any] | None, status_file: str, metrics_url: Optional[str], rolling: Optional[Dict[str, Any]] = None, *, compact: bool = False, low_contrast: bool = False) -> Any:
    from rich.console import Group as _Group  # type: ignore
    from rich.layout import Layout  # type: ignore
    from rich.panel import Panel  # type: ignore
    from scripts.summary.panels.indices import indices_panel
    from scripts.summary.panels.analytics import analytics_panel
    from scripts.summary.panels.alerts import alerts_panel
    from scripts.summary.panels.links import links_panel
    from scripts.summary.panels.system import health_panel
    from scripts.summary.panels.storage import sinks_panel

    indices = derive_indices(status)
    version = ""
    if status:
        if isinstance(status.get("app"), dict) and status["app"].get("version"):
            version = str(status["app"]["version"])
        elif status.get("version"):
            version = str(status.get("version"))
    interval = None
    if status:
        interval = status.get("interval")
        if interval is None:
            loop = status.get("loop") if isinstance(status, dict) else None
            if isinstance(loop, dict):
                interval = loop.get("target_interval")

    layout = Layout()
    # Header + body only; no footer strip in this layout
    header_size = panel_height("header") or 4
    body_min = panel_height("body") or 6
    layout.split_column(
        Layout(name="header", size=header_size),
        Layout(name="body", ratio=1, minimum_size=body_min),
    )
    # Body 3-column grid with fixed width ratios: 45% | 30% | 25%
    layout["body"].split_row(
        Layout(name="colL", ratio=45, minimum_size=_env_min_col_width()),
        Layout(name="colM", ratio=30, minimum_size=_env_min_col_width()),
        Layout(name="colR", ratio=25, minimum_size=_env_min_col_width()),
    )
    # Left column: Indices (70% height) + Analytics (30%)
    layout["colL"].split_column(
        Layout(name="indices", ratio=7, minimum_size=6),
        Layout(name="analytics", ratio=3, minimum_size=4),
    )
    # Middle column: Performance & Storage (full body height)
    layout["colM"].split_column(
        Layout(name="perfstore", ratio=10, minimum_size=6),
    )
    # Right column: Alerts (70%) + Links (30%)
    layout["colR"].split_column(
        Layout(name="alerts", ratio=7, minimum_size=6),
        Layout(name="links", ratio=3, minimum_size=4),
    )

    # Header (moved to panels.header)
    from scripts.summary.panels.header import header_panel  # type: ignore
    layout["header"].update(header_panel("", "", indices, low_contrast=low_contrast, status=status, interval=interval))

    # Panels
    layout["indices"].update(indices_panel(status, compact=compact, low_contrast=low_contrast, loop_for_footer=rolling))
    layout["analytics"].update(analytics_panel(status, compact=compact, low_contrast=low_contrast))
    layout["alerts"].update(alerts_panel(status, compact=compact, low_contrast=low_contrast))
    layout["links"].update(links_panel(status_file, metrics_url, low_contrast=low_contrast))

    perf_children = []
    # Add children with simple de-duplication by title to avoid accidental duplicates
    _child_titles = set()
    hp = health_panel(status, low_contrast=low_contrast, compact=compact)
    try:
        t = getattr(hp, "title", None) or getattr(hp, "renderable", None)
        key = str(t)
    except Exception:
        key = "health"
    if key not in _child_titles:
        perf_children.append(hp)
        _child_titles.add(key)
    sp = sinks_panel(status, low_contrast=low_contrast)
    try:
        t2 = getattr(sp, "title", None) or getattr(sp, "renderable", None)
        key2 = str(t2)
    except Exception:
        key2 = "sinks"
    if key2 not in _child_titles:
        perf_children.append(sp)
        _child_titles.add(key2)
    layout["perfstore"].update(Panel(_Group(*perf_children), title="Performance & Storage", border_style=("white" if low_contrast else "white"), expand=True))

    return layout


def refresh_layout(layout: Any, status: Dict[str, Any] | None, status_file: str, metrics_url: Optional[str], rolling: Optional[Dict[str, Any]] = None, *, compact: bool = False, low_contrast: bool = False) -> None:
    """
    Update an existing Layout with new panels for the given status without recreating the Layout object.
    This helps Rich.Live keep a stable frame height and prevents line-creep when screen=False.
    """
    from rich.console import Group as _Group  # type: ignore
    from rich.panel import Panel  # type: ignore
    from scripts.summary.panels.header import header_panel  # type: ignore
    from scripts.summary.panels.indices import indices_panel
    from scripts.summary.panels.analytics import analytics_panel
    from scripts.summary.panels.alerts import alerts_panel
    from scripts.summary.panels.links import links_panel
    from scripts.summary.panels.system import health_panel
    from scripts.summary.panels.storage import sinks_panel

    indices = derive_indices(status)
    version = ""
    if status:
        if isinstance(status.get("app"), dict) and status["app"].get("version"):
            version = str(status["app"]["version"])
        elif status.get("version"):
            version = str(status.get("version"))
    interval = None
    if status:
        interval = status.get("interval")
        if interval is None:
            loop = status.get("loop") if isinstance(status, dict) else None
            if isinstance(loop, dict):
                interval = loop.get("target_interval")

    layout["header"].update(header_panel("", version, indices, low_contrast=low_contrast, status=status, interval=interval))

    layout["indices"].update(indices_panel(status, compact=compact, low_contrast=low_contrast, loop_for_footer=rolling))
    layout["analytics"].update(analytics_panel(status, compact=compact, low_contrast=low_contrast))
    layout["alerts"].update(alerts_panel(status, compact=compact, low_contrast=low_contrast))
    layout["links"].update(links_panel(status_file, metrics_url, low_contrast=low_contrast))

    perf_children = []
    _child_titles = set()
    hp = health_panel(status, low_contrast=low_contrast, compact=compact)
    try:
        t = getattr(hp, "title", None) or getattr(hp, "renderable", None)
        key = str(t)
    except Exception:
        key = "health"
    if key not in _child_titles:
        perf_children.append(hp)
        _child_titles.add(key)
    sp = sinks_panel(status, low_contrast=low_contrast)
    try:
        t2 = getattr(sp, "title", None) or getattr(sp, "renderable", None)
        key2 = str(t2)
    except Exception:
        key2 = "sinks"
    if key2 not in _child_titles:
        perf_children.append(sp)
        _child_titles.add(key2)
    layout["perfstore"].update(Panel(_Group(*perf_children), title="Performance & Storage", border_style=("white" if low_contrast else "white"), expand=True))
