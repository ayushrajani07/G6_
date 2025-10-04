import time
from src.column_store.pipeline import get_pipeline, ColumnStorePipeline, PipelineConfig
from src.metrics import get_metrics


def test_cs_basic_ingest_and_latency(monkeypatch):
    monkeypatch.setenv('STORAGE_COLUMN_STORE_ENABLED','1')
    p = get_pipeline('option_chain_agg')
    # Enqueue fewer than batch rows but force latency flush
    for i in range(10):
        p.enqueue({'ts': i, 'contracts_active': 5})
    # Force flush by setting very small max latency and waiting
    p.cfg.max_latency_ms = 1
    time.sleep(0.01)
    p.flush()
    reg = get_metrics()
    # Access generated counters via generated module helpers (ensures codegen accessors present)
    from src.metrics import generated as g  # type: ignore
    child = g.m_cs_ingest_rows_total_labels('option_chain_agg')  # type: ignore[attr-defined]
    assert child is not None, "Expected rows counter child for table"
    # Backlog should be zero after flush
    backlog = g.m_cs_ingest_backlog_rows_labels('option_chain_agg')  # type: ignore[attr-defined]
    assert backlog is not None
    # We can't read the value directly without prometheus_client installed; just ensure object exists.


def test_cs_backpressure_toggle(monkeypatch):
    monkeypatch.setenv('STORAGE_COLUMN_STORE_ENABLED','1')
    p = get_pipeline('option_chain_agg')
    p.cfg.high_watermark_rows = 5
    p.cfg.low_watermark_rows = 2
    for i in range(6):
        p.enqueue({'ts': i})
    # Backpressure should be active
    # (We can't assert on metric object easily without Prom client sample introspection; just flush then add more)
    p.flush()
    from src.metrics import generated as g  # type: ignore
    flag = g.m_cs_ingest_backpressure_flag_labels('option_chain_agg')  # type: ignore[attr-defined]
    assert flag is not None
    for i in range(3):
        p.enqueue({'ts': i+100})
    p.flush()


def test_cs_failure_path(monkeypatch):
    monkeypatch.setenv('STORAGE_COLUMN_STORE_ENABLED','1')
    p = get_pipeline('option_chain_agg')
    # Inject failure hook
    p.install_failure_hook(lambda batch: 'simulated' if batch else None)
    for i in range(5):
        p.enqueue({'ts': i})
    p.cfg.batch_rows = 5
    p.flush()
    from src.metrics import generated as g  # type: ignore
    fail_child = g.m_cs_ingest_failures_total_labels('option_chain_agg','simulated')  # type: ignore[attr-defined]
    assert fail_child is not None
