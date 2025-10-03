from src.web.dashboard.diff_merge import merge_panel_diff


def test_full_replacement_creates_panel():
    panels = {}
    event = {"panel": "provider", "op": "full", "data": {"name": "kite"}}
    out = merge_panel_diff(panels, event)
    assert out["provider"] == {"name": "kite"}
    assert panels == {}  # immutability


def test_diff_merge_adds_and_updates():
    base = {"provider": {"name": "kite", "latency_ms": 10}}
    event = {"panel": "provider", "op": "diff", "data": {"latency_ms": 12, "auth": {"valid": True}}}
    out = merge_panel_diff(base, event)
    assert out["provider"]["latency_ms"] == 12
    assert out["provider"]["auth"] == {"valid": True}
    assert base["provider"]["latency_ms"] == 10  # original unchanged


def test_diff_nested_merge_and_remove():
    base = {"resources": {"cpu": {"pct": 40, "cores": 8}, "rss_mb": 512}}
    event = {"panel": "resources", "op": "diff", "data": {"cpu": {"pct": 55}, "rss_mb": {"__remove__": True}}}
    out = merge_panel_diff(base, event)
    assert out["resources"]["cpu"] == {"pct": 55, "cores": 8}
    assert "rss_mb" not in out["resources"]


def test_diff_list_replacement():
    base = {"indices": {"rows": [1,2,3]}}
    event = {"panel": "indices", "op": "diff", "data": {"rows": [1,2,3,4]}}
    out = merge_panel_diff(base, event)
    assert out["indices"]["rows"] == [1,2,3,4]


def test_diff_new_panel_created():
    base = {"adaptive": {"alerts": 1}}
    event = {"panel": "dq", "op": "diff", "data": {"green": 2, "warn": 1}}
    out = merge_panel_diff(base, event)
    assert out["dq"] == {"green": 2, "warn": 1}
    assert "adaptive" in out


def test_invalid_event_raises():
    try:
        merge_panel_diff({}, {"op": "diff", "data": {}})
    except ValueError:
        pass
    else:
        assert False, "Expected ValueError for missing panel"
    try:
        merge_panel_diff({}, {"panel": "p", "op": "noop", "data": {}})
    except ValueError:
        pass
    else:
        assert False, "Expected ValueError for invalid op"
    try:
        merge_panel_diff({}, {"panel": "p", "op": "diff", "data": 1})
    except ValueError:
        pass
    else:
        assert False, "Expected ValueError for non-mapping diff payload"
