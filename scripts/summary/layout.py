from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - import only for type checkers
    from rich.layout import Layout

from scripts.summary.derive import derive_indices
from scripts.summary.env import _env_min_col_width, panel_height


def build_layout(
    status: dict[str, Any] | None,
    status_file: str,
    metrics_url: str | None,
    rolling: dict[str, Any] | None = None,
    *,
    compact: bool = False,
    low_contrast: bool = False,
) -> Layout:
    from rich.layout import Layout

    from scripts.summary.panels.alerts import alerts_panel
    from scripts.summary.panels.analytics import analytics_panel
    from scripts.summary.panels.indices import indices_panel
    from scripts.summary.panels.links import links_panel

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
    # Body 3-column grid with adjusted width ratios: 50% | 20% | 30%
    # (Reduced Performance & Storage by 10%, added 5% each to Indices+Analytics and Alerts)
    layout["body"].split_row(
        Layout(name="colL", ratio=50, minimum_size=_env_min_col_width()),
        Layout(name="colM", ratio=20, minimum_size=_env_min_col_width()),
        Layout(name="colR", ratio=30, minimum_size=_env_min_col_width()),
    )
    # Left column: Indices (70% height) + Analytics (30%)
    layout["colL"].split_column(
        Layout(name="indices", ratio=7, minimum_size=6),
        Layout(name="analytics", ratio=3, minimum_size=4),
    )
    # Middle column: Performance & Storage (60%) + Storage & Backup (40%)
    layout["colM"].split_column(
        Layout(name="perfstore", ratio=6, minimum_size=6),
        Layout(name="storage", ratio=4, minimum_size=4),
    )
    # Right column: Alerts (70%) + Links (30%)
    layout["colR"].split_column(
        Layout(name="alerts", ratio=7, minimum_size=6),
        Layout(name="links", ratio=3, minimum_size=4),
    )

    # Header (moved to panels.header)
    from scripts.summary.panels.header import header_panel
    layout["header"].update(
        header_panel(
            "",
            version,
            indices,
            low_contrast=low_contrast,
            status=status,
            interval=interval,
        )
    )

    # Panels
    layout["indices"].update(
        indices_panel(
            status,
            compact=compact,
            low_contrast=low_contrast,
            loop_for_footer=rolling,
        )
    )
    layout["analytics"].update(
        analytics_panel(status, compact=compact, low_contrast=low_contrast)
    )
    layout["alerts"].update(alerts_panel(status, compact=compact, low_contrast=low_contrast))
    layout["links"].update(links_panel(status_file, metrics_url, low_contrast=low_contrast))

    # Import monitoring panels
    from scripts.summary.panels.monitoring import storage_backup_metrics_panel, unified_performance_storage_panel

    # Performance & Storage panel (top panel)
    layout["perfstore"].update(
        unified_performance_storage_panel(
            status,
            low_contrast=low_contrast,
            compact=compact,
            show_title=True,
        )
    )

    # Storage & Backup Metrics panel (bottom panel)
    layout["storage"].update(
        storage_backup_metrics_panel(
            status,
            low_contrast=low_contrast,
            compact=compact,
            show_title=True,
        )
    )

    return layout


def refresh_layout(
    layout: Any,
    status: dict[str, Any] | None,
    status_file: str,
    metrics_url: str | None,
    rolling: dict[str, Any] | None = None,
    *,
    compact: bool = False,
    low_contrast: bool = False,
) -> None:
    """
    Update an existing Layout with new panels for the given status without recreating the Layout object.
    This helps Rich.Live keep a stable frame height and prevents line-creep when screen=False.
    """
    from scripts.summary.panels.alerts import alerts_panel
    from scripts.summary.panels.analytics import analytics_panel
    from scripts.summary.panels.header import header_panel
    from scripts.summary.panels.indices import indices_panel
    from scripts.summary.panels.links import links_panel

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

    layout["header"].update(
        header_panel(
            "",
            version,
            indices,
            low_contrast=low_contrast,
            status=status,
            interval=interval,
        )
    )

    layout["indices"].update(
        indices_panel(
            status,
            compact=compact,
            low_contrast=low_contrast,
            loop_for_footer=rolling,
        )
    )
    layout["analytics"].update(
        analytics_panel(status, compact=compact, low_contrast=low_contrast)
    )
    layout["alerts"].update(alerts_panel(status, compact=compact, low_contrast=low_contrast))
    layout["links"].update(links_panel(status_file, metrics_url, low_contrast=low_contrast))

    # Import monitoring panels
    from scripts.summary.panels.monitoring import storage_backup_metrics_panel, unified_performance_storage_panel

    # Performance & Storage panel (top panel)
    layout["perfstore"].update(
        unified_performance_storage_panel(
            status,
            low_contrast=low_contrast,
            compact=compact,
            show_title=True,
        )
    )

    # Storage & Backup Metrics panel (bottom panel)
    layout["storage"].update(
        storage_backup_metrics_panel(
            status,
            low_contrast=low_contrast,
            compact=compact,
            show_title=True,
        )
    )


def update_single_panel(
    layout: Any,
    panel_key: str,
    status: dict[str, Any] | None,
    status_file: str,
    metrics_url: str | None,
    *,
    compact: bool = False,
    low_contrast: bool = False,
    rolling: dict[str, Any] | None = None,
) -> None:
    """Update only a single panel region (if recognized) with fresh content.

    Panel keys: header, indices, analytics, alerts, links, perfstore, storage
    Unknown keys are ignored silently (defensive).
    """
    from scripts.summary.panels.alerts import alerts_panel
    from scripts.summary.panels.analytics import analytics_panel
    from scripts.summary.panels.header import header_panel
    from scripts.summary.panels.indices import indices_panel
    from scripts.summary.panels.links import links_panel
    from scripts.summary.panels.monitoring import storage_backup_metrics_panel, unified_performance_storage_panel

    if panel_key == 'header':
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
        layout["header"].update(
            header_panel(
                "",
                version,
                indices,
                low_contrast=low_contrast,
                status=status,
                interval=interval,
            )
        )
    elif panel_key == 'indices':
        layout["indices"].update(
            indices_panel(
                status,
                compact=compact,
                low_contrast=low_contrast,
                loop_for_footer=rolling,
            )
        )
    elif panel_key == 'analytics':
        layout["analytics"].update(analytics_panel(status, compact=compact, low_contrast=low_contrast))
    elif panel_key == 'alerts':
        layout["alerts"].update(alerts_panel(status, compact=compact, low_contrast=low_contrast))
    elif panel_key == 'links':
        layout["links"].update(links_panel(status_file, metrics_url, low_contrast=low_contrast))
    elif panel_key == 'perfstore':
        layout["perfstore"].update(
            unified_performance_storage_panel(
                status,
                low_contrast=low_contrast,
                compact=compact,
                show_title=True,
            )
        )
    elif panel_key == 'storage':
        layout["storage"].update(
            storage_backup_metrics_panel(
                status,
                low_contrast=low_contrast,
                compact=compact,
                show_title=True,
            )
        )
    else:
        return
