import os, time
from src.metrics import isolated_metrics_registry


def _enable(window=30, allowed=2, strict=False):
    os.environ['G6_FAULT_BUDGET_ENABLE'] = '1'
    os.environ['G6_FAULT_BUDGET_WINDOW_SEC'] = str(window)
    os.environ['G6_FAULT_BUDGET_ALLOWED_BREACHES'] = str(allowed)
    if strict:
        os.environ['G6_FAULT_BUDGET_STRICT'] = '1'
    else:
        os.environ.pop('G6_FAULT_BUDGET_STRICT', None)


def _disable():
    for k in list(os.environ.keys()):
        if k.startswith('G6_FAULT_BUDGET_'):
            os.environ.pop(k, None)


def test_fault_budget_disabled():
    _disable()
    with isolated_metrics_registry() as reg:
        assert not hasattr(reg, '_fault_budget_tracker')


def test_fault_budget_basic(monkeypatch):
    _enable(window=5, allowed=2)
    with isolated_metrics_registry() as reg:
        tracker = getattr(reg, '_fault_budget_tracker', None)
        if tracker is None:
            # Fallback: explicit init (environment may have been set after SLA placeholder ordering)
            from src.metrics.fault_budget import init_fault_budget
            init_fault_budget(reg)
            tracker = getattr(reg, '_fault_budget_tracker', None)
        assert tracker is not None, 'Tracker should initialize when enabled (explicit or auto)'
        # Simulate two breach increments
        reg.cycle_sla_breach.inc()  # type: ignore[attr-defined]
        reg.mark_cycle(True, 0.1, 0, 0.0)
        reg.cycle_sla_breach.inc()  # second breach
        reg.mark_cycle(True, 0.1, 0, 0.0)
        fb = reg._fault_budget_tracker  # type: ignore[attr-defined]
        assert fb.allowed == 2
        assert len(fb.breaches) == 2
        # Third breach consumes beyond budget
        reg.cycle_sla_breach.inc()
        reg.mark_cycle(True, 0.1, 0, 0.0)
        assert len(fb.breaches) == 3  # deque keeps all within window
        # Remaining should be 0
        assert any(s.value == 0 for fam in reg.cycle_fault_budget_remaining.collect() for s in fam.samples)  # type: ignore[attr-defined]
        # Advance time beyond window to prune oldest breaches
        now = time.time()
        monkeypatch.setattr('src.metrics.fault_budget.time', type('T', (), {'time': staticmethod(lambda: now + 10)}))
        reg.mark_cycle(True, 0.1, 0, 0.0)
        # After prune, backlog should shrink (third breach still counts if within 5s of new time?)
        fb = reg._fault_budget_tracker  # refresh
        assert len(fb.breaches) <= 2
        remaining_samples = list(reg.cycle_fault_budget_remaining.collect())[0].samples  # type: ignore[attr-defined]
        # Remaining should have recovered (>0)
        assert any(s.value > 0 for s in remaining_samples)


def test_fault_budget_strict_exhaustion(monkeypatch, caplog):
    _enable(window=10, allowed=1, strict=True)
    with isolated_metrics_registry() as reg:
        caplog.set_level('ERROR')
        reg.cycle_sla_breach.inc()  # first breach
        reg.mark_cycle(True, 0.05, 0, 0.0)
        assert any('fault_budget.exhausted' in r.message for r in caplog.records)
    _disable()
