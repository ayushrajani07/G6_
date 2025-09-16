"""Runtime bootstrap utilities for G6 Platform.

Centralizes common startup concerns so entrypoints remain thin:
- sys.path assurance
- dotenv/environment loading (optional if python-dotenv installed)
- logging initialization
- configuration load & normalization (ConfigWrapper)
- metrics server startup (optional toggle)

It returns a BootContext containing references to commonly used
subsystems so callers can wire collectors without repeating boilerplate.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Tuple
import logging
import os
import json

from .path_utils import ensure_sys_path, resolve_path
from .logging_utils import setup_logging
from src.config.config_wrapper import ConfigWrapper
from src.metrics.metrics import setup_metrics_server

try:  # optional dependency
    from dotenv import load_dotenv  # type: ignore
    _HAVE_DOTENV = True
except Exception:  # pragma: no cover
    _HAVE_DOTENV = False


@dataclass
class BootContext:
    config: ConfigWrapper
    metrics: Any
    stop_metrics: Any
    log_file: str
    config_path: str


def load_raw_config(path: str) -> dict:
    if not os.path.exists(path):
        # Minimal default; unified_main has richer create_default_config but for early boot we keep lean
        return {"storage": {"csv_dir": "data/g6_data"}}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception as e:  # pragma: no cover - fallback path
        logging.error("Bootstrap config load failed (%s): %s", path, e)
        return {"storage": {"csv_dir": "data/g6_data"}}


def bootstrap(
    config_path: str = "config/config.json",
    log_level: str = "INFO",
    log_file: str = "logs/g6_platform.log",
    enable_metrics: bool = True,
    metrics_reset: bool = False,
    metrics_use_custom_registry: bool | None = None,
) -> BootContext:
    """Perform startup sequence and return BootContext.

    Parameters
    ----------
    config_path: path to the JSON config file (canonical: config/config.json)
    log_level: desired logging level
    log_file: path to log file (will ensure parent directory exists)
    enable_metrics: disable if caller wants to manage metrics manually
    """
    ensure_sys_path()

    # Logging
    setup_logging(log_level, log_file)

    # Env loading
    if _HAVE_DOTENV:
        try:
            load_dotenv()  # type: ignore
            logging.debug("Environment variables loaded from .env")
        except Exception as e:  # pragma: no cover
            logging.warning("dotenv load failed: %s", e)

    # Config
    raw = load_raw_config(config_path)
    config = ConfigWrapper(raw)

    # Metrics
    metrics = None
    stop = lambda: None
    if enable_metrics and config.get("metrics", {}).get("enabled", True):  # type: ignore[index]
        port = config.metrics_port()
        metrics, stop = setup_metrics_server(port=port, reset=metrics_reset, use_custom_registry=metrics_use_custom_registry)

    return BootContext(
        config=config,
        metrics=metrics,
        stop_metrics=stop,
        log_file=log_file,
        config_path=config_path,
    )

__all__ = ["bootstrap", "BootContext"]
