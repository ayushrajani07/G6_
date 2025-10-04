from src.metrics.safe_emit import safe_emit, _seen_first_failure, _emitter_name
from src.metrics import generated as m

def test_safe_emit_failure_counters_and_once(monkeypatch):
    _seen_first_failure.clear()

    @safe_emit
    def failing():  # pragma: no cover - raises intentionally
        raise RuntimeError("boom")

    for _ in range(3):
        failing()

    ident = _emitter_name(failing, None)
    # Access labeled children directly to force creation and read value
    fail_child = m.m_emission_failures_total_labels(ident)  # type: ignore[attr-defined]
    once_child = m.m_emission_failure_once_total_labels(ident)  # type: ignore[attr-defined]
    assert fail_child is not None and fail_child._value.get() == 3  # type: ignore[attr-defined]
    assert once_child is not None and once_child._value.get() == 1  # type: ignore[attr-defined]

def test_safe_emit_emitter_override():
    _seen_first_failure.clear()

    @safe_emit(emitter="groupA")
    def failing2():
        raise ValueError("x")

    failing2(); failing2()
    fail_child = m.m_emission_failures_total_labels('groupA')  # type: ignore[attr-defined]
    once_child = m.m_emission_failure_once_total_labels('groupA')  # type: ignore[attr-defined]
    assert fail_child is not None and fail_child._value.get() == 2  # type: ignore[attr-defined]
    assert once_child is not None and once_child._value.get() == 1  # type: ignore[attr-defined]
