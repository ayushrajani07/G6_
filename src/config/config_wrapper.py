"""Configuration normalization and typed access layer.

This module provides a `ConfigWrapper` that accepts any of the currently
supported config file variants (`config.json`, `g6_config.json`, `_g6_config.json`)
and normalizes them into a consistent internal shape so the rest of the code
can rely on unified semantics without losing backward compatibility.

Normalization performed:
1. indices -> index_params translation (old schema vs new)
2. storage.influx_* flat keys -> storage.influx object
3. storage.influx.enabled / influx_enabled harmonization
4. metrics.port -> metrics.port (adds enabled=True if missing)
5. Derive data_dir from storage.csv_dir if not explicitly present.
6. Fill missing optional sub-dicts with sensible defaults.

The wrapper exposes Mapping interface so existing dict-like access works.
"""
from __future__ import annotations

import copy
from collections.abc import Iterator, MutableMapping
from typing import Any

DEFAULTS: dict[str, Any] = {
    "metrics": {"enabled": True, "port": 9108, "host": "0.0.0.0"},
    "collection": {"interval_seconds": 60},
    "orchestration": {"run_interval_sec": 60, "prometheus_port": 9108},
    "storage": {
        "csv_dir": "data/g6_data",
        # CSV buffering defaults (can be overridden via env or config)
        "csv_buffer_size": 0,
        "csv_max_open_files": 64,
        "csv_flush_interval_seconds": 2.0,
        "influx": {
            "enabled": False,
            "url": "http://localhost:8086",
            "token": "",
            "org": "g6",
            "bucket": "g6_data",
            # performance knobs (optional)
            "batch_size": 500,
            "flush_interval_seconds": 1.0,
            "max_queue_size": 10000,
            "pool_min_size": 1,
            "pool_max_size": 2,
            "max_retries": 3,
            "backoff_base": 0.25,
            "breaker_failure_threshold": 5,
            "breaker_reset_timeout": 30.0,
        },
    },
    # Feature / console toggles (new optional config layer; env & CLI still override)
    "features": {
        "analytics_startup": False,
    },
    "console": {
        "fancy_startup": False,
        "live_panel": False,
        "startup_banner": True,
    },
    # Experimental async/parallel collection flags (opt-in, default off)
    "parallel_collection": {
        "enabled": False,
        "max_workers": 8,
        "rate_limits": {
            "kite": {"cps": 0.0, "burst": 0}
        },
    },
    "index_params": {},
}


def _merge(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(a)
    for k, v in b.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _translate_indices(raw: dict[str, Any]) -> None:
    # Translate legacy 'indices' to 'index_params' if index_params missing OR empty
    if "index_params" in raw and raw.get("index_params"):
        return
    indices = raw.get("indices")
    if not isinstance(indices, dict):
        return
    translated: dict[str, Any] = {}
    for symbol, spec in indices.items():
        if not isinstance(spec, dict):
            continue
        translated[symbol] = {
            # New schema uses expiry_rules; keep original key name for internal code expecting 'expiries' or 'expiry_rules'
            "expiry_rules": spec.get("expiries") or spec.get("expiry_rules") or [],
            "expiries": spec.get("expiries") or spec.get("expiry_rules") or [],
            # Provide strike info when available
            "strikes_itm": spec.get("strikes_itm"),
            "strikes_otm": spec.get("strikes_otm"),
            # Legacy advanced schema sometimes just had strikes count under different name
            "strike_step": spec.get("strike_step"),
            # Offsets (optional)
            "offsets": spec.get("offsets", []),
            "enable": spec.get("enable", True),
        }
    raw["index_params"] = translated


def _unify_influx(raw: dict[str, Any]) -> None:
    storage = raw.setdefault("storage", {})
    influx_dict = storage.get("influx")
    # Flat schema variant: influx_enabled/url/org/bucket
    flat_enabled = storage.get("influx_enabled")
    if influx_dict is None:
        influx_dict = {
            "enabled": bool(flat_enabled) if flat_enabled is not None else False,
            "url": storage.get("influx_url", DEFAULTS["storage"]["influx"]["url"]),
            "token": storage.get("influx_token", ""),
            "org": storage.get("influx_org", DEFAULTS["storage"]["influx"]["org"]),
            "bucket": storage.get("influx_bucket", DEFAULTS["storage"]["influx"]["bucket"]),
        }
    else:
        # Ensure required keys / defaults
        influx_dict.setdefault("enabled", bool(flat_enabled) if flat_enabled is not None else influx_dict.get("enabled", False))
        influx_dict.setdefault("url", DEFAULTS["storage"]["influx"]["url"])
        influx_dict.setdefault("token", "")
        influx_dict.setdefault("org", DEFAULTS["storage"]["influx"]["org"])
        influx_dict.setdefault("bucket", DEFAULTS["storage"]["influx"]["bucket"])
    storage["influx"] = influx_dict


def _derive_data_dir(raw: dict[str, Any]) -> None:
    if "data_dir" in raw and raw["data_dir"]:
        return
    storage = raw.get("storage", {})
    csv_dir = storage.get("csv_dir")
    if csv_dir:
        raw["data_dir"] = csv_dir
    else:
        raw["data_dir"] = DEFAULTS["storage"]["csv_dir"]


def _parse_version(ver: Any) -> tuple[int, int]:
    try:
        s = str(ver)
        parts = s.split('.')
        major = int(parts[0]) if parts and parts[0].isdigit() else 0
        minor = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        return (major, minor)
    except Exception:
        return (0, 0)


def normalize(raw: dict[str, Any]) -> dict[str, Any]:
    """Return a new normalized config dictionary without mutating input."""
    work = _merge(DEFAULTS, raw)
    ver = _parse_version(work.get("schema_version"))
    # Skip legacy translations if schema already versioned sufficiently
    if ver < (1, 1):
        _translate_indices(work)
    if ver < (1, 2):
        _unify_influx(work)
    _derive_data_dir(work)
    # Metrics: ensure enabled key exists
    metrics = work.setdefault("metrics", {})
    metrics.setdefault("enabled", True)
    metrics.setdefault("port", DEFAULTS["metrics"]["port"])
    metrics.setdefault("host", DEFAULTS["metrics"]["host"])
    return work


class ConfigWrapper(MutableMapping):
    """Dict-like wrapper exposing normalized configuration.

    Supports standard mapping operations so existing code using dict semantics
    continues to work. Original (raw) and normalized (data) retained.
    """

    def __init__(self, raw: dict[str, Any]):
        self.raw = copy.deepcopy(raw)
        self.data = normalize(raw)

    # Mapping protocol
    def __getitem__(self, key: str) -> Any:  # type: ignore[override]
        return self.data[key]

    def __setitem__(self, key: str, value: Any) -> None:  # type: ignore[override]
        self.data[key] = value

    def __delitem__(self, key: str) -> None:  # type: ignore[override]
        del self.data[key]

    def __iter__(self) -> Iterator:  # type: ignore[override]
        return iter(self.data)

    def __len__(self) -> int:  # type: ignore[override]
        return len(self.data)

    # Convenience helpers
    def collection_interval(self) -> int:
        return (
            self.data.get("collection", {}).get("interval_seconds")
            or self.data.get("orchestration", {}).get("run_interval_sec", 60)
        )

    def metrics_port(self) -> int:
        return self.data.get("metrics", {}).get("port") or self.data.get("orchestration", {}).get("prometheus_port", 9108)

    def influx_enabled(self) -> bool:
        return bool(self.data.get("storage", {}).get("influx", {}).get("enabled"))

    def influx_config(self) -> dict[str, Any]:
        return self.data.get("storage", {}).get("influx", {})

    def index_params(self) -> dict[str, Any]:
        return self.data.get("index_params", {})

    def data_dir(self) -> str:
        val = self.data.get("data_dir")
        if isinstance(val, str):
            return val
        return str(val) if val is not None else DEFAULTS["storage"]["csv_dir"]

    def raw_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self.raw)


__all__ = ["ConfigWrapper", "normalize"]
