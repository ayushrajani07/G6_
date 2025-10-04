from types import SimpleNamespace
from scripts.summary.rich_diff import compute_panel_hashes

class DummyCycle(SimpleNamespace):
    pass

class DummyDomain(SimpleNamespace):
    pass

def test_header_hash_changes_with_cycle_number():
    status = {"app": {"version": "1.0"}, "indices": ["A"], "alerts": []}
    domain_v1 = DummyDomain(cycle=DummyCycle(number=1))
    h1 = compute_panel_hashes(status, domain=domain_v1)
    domain_v2 = DummyDomain(cycle=DummyCycle(number=2))
    h2 = compute_panel_hashes(status, domain=domain_v2)
    assert h1["header"] != h2["header"], "Header hash should change when cycle number changes"
