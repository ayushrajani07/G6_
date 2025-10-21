from __future__ import annotations

import logging
from typing import Any

from src.error_handling import handle_ui_error
from src.utils.panel_error_utils import centralized_panel_error_handler, safe_panel_execute


@centralized_panel_error_handler("analytics_panel")
def analytics_panel(status: dict[str, Any] | None, *, compact: bool = False, low_contrast: bool = False) -> Any:
    """Analytics panel with comprehensive error handling."""
    return safe_panel_execute(
        _create_analytics_panel, status, compact, low_contrast,
        error_msg="Analytics - Error Loading Data"
    )

def _create_analytics_panel(status: dict[str, Any] | None, compact: bool, low_contrast: bool) -> Any:
    """Internal implementation for analytics panel."""
    from rich import box
    from rich.console import Group
    from rich.panel import Panel
    from rich.table import Table

    from scripts.summary.data_source import _read_panel_json, _use_panels_json
    from scripts.summary.derive import clip

    def format_price(val: Any) -> str:
        """Format price values nicely with error handling."""
        try:
            if isinstance(val, (int, float)) and not (val != val):  # Check for NaN
                return f"{val:,.0f}" if val >= 1000 else f"{val:.2f}"
            return str(val) if val is not None else "—"
        except Exception as e:
            handle_ui_error(e, component="analytics_panel", context={"op": "format_price"})
            logging.warning(f"Error formatting price {val}: {e}")
            return "—"

    def get_pcr_sentiment(pcr: Any) -> str:
        """Get PCR sentiment description with error handling."""
        try:
            if not isinstance(pcr, (int, float)) or (pcr != pcr):  # Check for NaN
                return "Unknown"
            if pcr < 0.7:
                return "Bullish (Call Heavy)"
            elif pcr > 1.3:
                return "Bearish (Put Heavy)"
            else:
                return "Neutral"
        except Exception as e:
            handle_ui_error(e, component="analytics_panel", context={"op": "pcr_sentiment"})
            logging.warning(f"Error determining PCR sentiment for {pcr}: {e}")
            return "Unknown"

    # Get analytics data with error handling
    data = None
    try:
        if _use_panels_json():
            pj = _read_panel_json("analytics")
            if isinstance(pj, dict):
                data = pj
    except Exception as e:
        handle_ui_error(
            e,
            component="analytics_panel",
            context={"op": "read_panels_json"},
        )
        logging.warning(f"Error reading panels JSON for analytics: {e}")

    try:
        # Avoid mixing sources: if panels mode is ON, do not fall back to status
        if data is None and not _use_panels_json():
            data = (status or {}).get("analytics") if status else None
    except Exception as e:
        handle_ui_error(
            e,
            component="analytics_panel",
            context={"op": "extract_analytics"},
        )
        logging.warning(f"Error extracting analytics from status: {e}")
        data = None

    # Get indices data for LTP context with error handling
    indices: dict[str, dict[str, Any]] = {}
    try:
        indices = (status or {}).get("indices", {}) if status else {}
        if not isinstance(indices, dict):
            indices = {}
    except Exception as e:
        handle_ui_error(
            e,
            component="analytics_panel",
            context={"op": "extract_indices"},
        )
        logging.warning(f"Error extracting indices data: {e}")
        indices = {}

    tbl = Table(box=box.SIMPLE_HEAD)
    tbl.add_column("Index", style="bold")
    tbl.add_column("LTP")
    tbl.add_column("Max Pain")
    tbl.add_column("Distance")
    tbl.add_column("PCR")

    shown = 0
    max_rows = 3 if compact else 6

    if isinstance(data, dict):
        try:
            max_pain_data = data.get("max_pain", {})
            global_pcr = data.get("pcr")

            # Show per-index analytics with error handling
            if isinstance(max_pain_data, dict):
                for idx_name, max_pain in max_pain_data.items():
                    if shown >= max_rows:
                        break

                    try:
                        # Get current LTP with error handling
                        idx_info = indices.get(idx_name, {})
                        ltp = idx_info.get("ltp") if isinstance(idx_info, dict) else None

                        # Calculate distance from max pain with error handling
                        distance = "—"
                        try:
                            if isinstance(ltp, (int, float)) and isinstance(max_pain, (int, float)) and max_pain > 0:
                                dist_pct = ((ltp - max_pain) / max_pain) * 100
                                distance = f"{dist_pct:+.1f}%"
                        except (ZeroDivisionError, OverflowError, ValueError) as e:
                            handle_ui_error(
                                e,
                                component="analytics_panel",
                                context={"op": "distance", "index": str(idx_name)},
                            )
                            logging.warning(f"Error calculating distance for {idx_name}: {e}")
                            distance = "—"

                        # Use global PCR for all indices (typically market-wide)
                        pcr_display = "—"
                        try:
                            if isinstance(global_pcr, (int, float)) and not (global_pcr != global_pcr):  # NaN check
                                pcr_display = f"{global_pcr:.2f}"
                        except (ValueError, OverflowError) as e:
                            handle_ui_error(
                                e,
                                component="analytics_panel",
                                context={"op": "format_pcr"},
                            )
                            logging.warning(f"Error formatting PCR: {e}")

                        tbl.add_row(
                            clip(str(idx_name)) if idx_name else "—",
                            format_price(ltp) if ltp is not None else "—",
                            format_price(max_pain),
                            distance,
                            pcr_display
                        )
                        shown += 1

                    except Exception as e:
                        handle_ui_error(
                            e,
                            component="analytics_panel",
                            context={"op": "row", "index": str(idx_name)},
                        )
                        logging.warning(f"Error processing analytics row for {idx_name}: {e}")
                        # Add error row to maintain table structure
                        tbl.add_row("—", "—", "—", "—", "—")
                        shown += 1

            # If no max pain data but have global PCR
            elif isinstance(global_pcr, (int, float)) and shown == 0:
                try:
                    # Show major indices with PCR
                    major_indices = ["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"]
                    for idx_name in major_indices:
                        if shown >= max_rows:
                            break
                        if idx_name in indices:
                            try:
                                idx_info = indices[idx_name]
                                ltp = idx_info.get("ltp") if isinstance(idx_info, dict) else None
                                tbl.add_row(
                                    idx_name,
                                    format_price(ltp) if ltp is not None else "—",
                                    "—",
                                    "—",
                                    f"{global_pcr:.2f}"
                                )
                                shown += 1
                            except Exception as e:
                                handle_ui_error(
                                    e,
                                    component="analytics_panel",
                                    context={"op": "major_index", "index": idx_name},
                                )
                                logging.warning(f"Error processing major index {idx_name}: {e}")
                                tbl.add_row("—", "—", "—", "—", "—")
                                shown += 1
                except Exception as e:
                    handle_ui_error(
                        e,
                        component="analytics_panel",
                        context={"op": "major_indices"},
                    )
                    logging.warning(f"Error processing major indices section: {e}")

        except Exception as e:
            handle_ui_error(
                e,
                component="analytics_panel",
                context={"op": "process_data"},
            )
            logging.error(f"Error processing analytics data: {e}")
            # Add error indication row
            tbl.add_row("Error", "—", "—", "—", "—")
            shown += 1

    # Fill empty rows
    while shown < max_rows:
        tbl.add_row("—", "—", "—", "—", "—")
        shown += 1

    # Footer with PCR sentiment with error handling
    footer = Table.grid()
    try:
        if isinstance(data, dict) and isinstance(data.get("pcr"), (int, float)):
            pcr = data["pcr"]
            if not (pcr != pcr):  # NaN check
                sentiment = get_pcr_sentiment(pcr)
                try:
                    footer.add_row(f"[dim]Market Sentiment: {sentiment} | PCR: {pcr:.3f}[/dim]")
                except (ValueError, OverflowError) as e:
                    logging.warning(f"Error formatting PCR footer: {e}")
                    footer.add_row(f"[dim]Market Sentiment: {sentiment} | PCR: N/A[/dim]")
            else:
                footer.add_row("[dim]Market analytics data not available (invalid PCR)[/dim]")
        else:
            footer.add_row("[dim]Market analytics data not available[/dim]")
    except Exception as e:
        handle_ui_error(e, component="analytics_panel", context={"op": "footer"})
        logging.warning(f"Error creating analytics footer: {e}")
        footer.add_row("[dim]Analytics footer error[/dim]")

    return Panel(
        Group(tbl, footer),
        title="Analytics",
        border_style=("white" if low_contrast else "yellow"),
        expand=True
    )
