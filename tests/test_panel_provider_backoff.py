"""Test provider failure backoff logic in panel_registry."""
from __future__ import annotations
from types import SimpleNamespace
from scripts.summary.panel_registry import build_all_panels, DEFAULT_PANEL_PROVIDERS
from scripts.summary.domain import build_domain_snapshot

class FailingProvider:
    key = "failing_demo"
    def __init__(self):
        self.calls = 0
    def build(self, snapshot):
        self.calls += 1
        raise RuntimeError("boom")


def test_provider_backoff(monkeypatch):
    # Inject failing provider at end
    failing = FailingProvider()
    # Convert to list then reassign tuple with failing provider appended
    extended = tuple(list(DEFAULT_PANEL_PROVIDERS) + [failing])
    monkeypatch.setattr('scripts.summary.panel_registry.DEFAULT_PANEL_PROVIDERS', extended)
    status = {"indices": ["X"], "alerts": {"total": 0}}
    domain = build_domain_snapshot(status)
    # Trigger failures more than threshold (3)
    panels = []
    for _ in range(4):  # exceed threshold of 3
        panels = build_all_panels(domain)
    # Last panel for failing provider should indicate cooldown after threshold
    failing_panels = [p for p in panels if p.key == 'failing_demo']
    assert failing_panels, "Failing provider panel not emitted"
    meta = failing_panels[-1].meta or {}
    # After 4 attempts, threshold should have been crossed (failures>=3) OR cooldown suppression active
    assert (meta.get('failures', 0) >= 3) or meta.get('cooldown'), meta
