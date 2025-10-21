from __future__ import annotations

from typing import Any


class PersistResult:
    """Structured result representing outcome of persistence and metrics emission.

    Attributes
    ----------
    option_count : int
        Number of option records processed/persisted.
    pcr : float | None
        Put-call ratio if available from metrics payload.
    metrics_payload : dict
        Raw payload returned by sink (expiry_code, timestamp, etc.).
    failed : bool
        True if persistence failed (CSV or other fatal sink path).
    """
    __slots__ = ("option_count","pcr","metrics_payload","failed")

    def __init__(self, option_count: int = 0, pcr: float | None = None, metrics_payload: dict[str, Any] | None = None, failed: bool = False):
        self.option_count = option_count
        self.pcr = pcr
        self.metrics_payload = metrics_payload or {}
        self.failed = failed

    def __repr__(self) -> str:  # helpful for debugging/logging
        return (f"PersistResult(option_count={self.option_count}, pcr={self.pcr}, failed={self.failed}, "
                f"keys={list(self.metrics_payload.keys())})")
