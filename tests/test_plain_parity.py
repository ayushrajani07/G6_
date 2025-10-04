import io, sys, pytest
from scripts.summary.domain import build_domain_snapshot
from scripts.summary.plain_renderer import PlainRenderer
from scripts.summary.plugins.base import SummarySnapshot

SAMPLE_STATUS = {
    "indices": ["NIFTY", "BANKNIFTY"],
    "alerts": {"total": 2, "severity_counts": {"critical": 1, "warn": 1}},
    "loop": {"cycle": 5, "last_duration": 0.42},
    "resources": {"cpu_pct": 12.5, "memory_mb": 256},
    "app": {"version": "1.0.0"},
}


def normalize_lines(text: str):
    return [l.strip() for l in text.splitlines() if l.strip()]


def test_plain_renderer_basic_tokens():
    # Directly test PlainRenderer output without legacy fallback dependency
    renderer = PlainRenderer()
    domain = build_domain_snapshot(SAMPLE_STATUS, ts_read=0.0)
    snap = SummarySnapshot(
        status=SAMPLE_STATUS,
        derived={},
        panels={},
        ts_read=0.0,
        ts_built=0.0,
        cycle=5,
        errors=[],
        model=None,
        domain=domain,
    )
    buf = io.StringIO()
    old_stdout = sys.stdout
    try:
        sys.stdout = buf
        renderer.process(snap)
    finally:
        sys.stdout = old_stdout
    new_txt = buf.getvalue()
    new_lines = normalize_lines(new_txt)
    assert any("Indices" in l for l in new_lines)
    assert "NIFTY" in new_txt
    assert any(l.lower().startswith("cycle:") for l in new_lines)


@pytest.mark.skip(reason="Legacy plain_fallback parity test removed (summary_view deleted)")
def test_legacy_plain_fallback_deprecated():  # pragma: no cover - intentionally skipped
    assert True
