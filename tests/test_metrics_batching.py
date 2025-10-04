import os, time
import importlib

from src.metrics.generated import m_quote_enriched_total_labels

def _collect_samples(counter):
    samples = []
    for fam in counter.collect():  # type: ignore[attr-defined]
        for s in fam.samples:
            if s.name.endswith('_total'):
                samples.append((s.labels, s.value))
    return samples


def test_batching_enabled_flush(monkeypatch):
    monkeypatch.setenv('G6_METRICS_BATCH','1')
    monkeypatch.setenv('G6_METRICS_BATCH_INTERVAL','5')  # long interval so we control flush
    # Reload emitter to apply env
    import src.metrics.emitter as emitter
    importlib.reload(emitter)
    from src.metrics.emitter import batch_inc, flush_now, pending_queue_size
    # Batch a few increments
    batch_inc(m_quote_enriched_total_labels, 'provA', amount=3)
    batch_inc(m_quote_enriched_total_labels, 'provA', amount=2)
    # Not flushed yet; underlying counter should be absent or zero
    lbl = m_quote_enriched_total_labels('provA')
    before = 0
    try:
        before = lbl._value.get()  # type: ignore[attr-defined]
    except Exception:
        before = 0
    assert pending_queue_size() == 1
    assert before == 0
    flush_now()
    # After flush value should reflect 5
    after = lbl._value.get()  # type: ignore[attr-defined]
    assert after == before + 5


def test_batching_disabled_fallback(monkeypatch):
    monkeypatch.setenv('G6_METRICS_BATCH','0')
    import src.metrics.emitter as emitter
    importlib.reload(emitter)
    from src.metrics.emitter import batch_inc, pending_queue_size
    lbl = m_quote_enriched_total_labels('provB')
    try:
        base = lbl._value.get()  # type: ignore[attr-defined]
    except Exception:
        base = 0
    batch_inc(m_quote_enriched_total_labels, 'provB', amount=4)
    # Immediate reflect (no queue)
    new_val = lbl._value.get()  # type: ignore[attr-defined]
    assert new_val == base + 4
    assert pending_queue_size() == 0
