from typing import Dict, Any
from src.panels.factory import build_indices_stream_items
from src.utils.status_reader import StatusReader


class DummyReader(StatusReader):
    def __init__(self, indices_detail=None, cycle=None):  # type: ignore[no-untyped-def]
        # Intentionally do not call super().__init__ to avoid external deps
        self._indices_detail = indices_detail or {}
        self._cycle = cycle or {"cycle": 1, "last_duration": 1.0}

    def get_indices_data(self) -> Dict[str, Any]:
        return self._indices_detail

    def get_cycle_data(self) -> Dict[str, Any]:
        return self._cycle


def _status(indices_detail: Dict[str, Any] | None = None):
    return {"indices_detail": indices_detail or {}}


def test_legs_precedence_expiries_sum_overrides_current_cycle():
    reader = DummyReader(indices_detail={
        "NIFTY": {
            "current_cycle_legs": 10,
            "expiries": {
                "2025-09-25": {"legs": 7},
                "2025-10-02": {"legs": 9},
            }
        }
    })
    items = build_indices_stream_items(reader, _status(reader.get_indices_data()))
    nifty = next(i for i in items if i.get("index") == "NIFTY")
    assert nifty.get("legs") == 16  # 7 + 9


def test_legs_precedence_current_cycle_when_no_expiries():
    reader = DummyReader(indices_detail={
        "BANKNIFTY": {
            "current_cycle_legs": 12,
        }
    })
    items = build_indices_stream_items(reader, _status(reader.get_indices_data()))
    bn = next(i for i in items if i.get("index") == "BANKNIFTY")
    assert bn.get("legs") == 12


def test_legs_precedence_cumulative_fallback_when_no_specifics():
    reader = DummyReader(indices_detail={
        "FINNIFTY": {
            "legs_total": 25,
        }
    })
    items = build_indices_stream_items(reader, _status(reader.get_indices_data()))
    fn = next(i for i in items if i.get("index") == "FINNIFTY")
    assert fn.get("legs") == 25
