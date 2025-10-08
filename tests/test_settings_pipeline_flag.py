import importlib, os

def test_pipeline_v2_flag_default(monkeypatch):
    monkeypatch.delenv('G6_COLLECTOR_PIPELINE_V2', raising=False)
    settings_mod = importlib.import_module('src.collectors.settings')
    importlib.reload(settings_mod)
    s = settings_mod.CollectorSettings.load()
    assert s.pipeline_v2_flag is False


def test_pipeline_v2_flag_enabled(monkeypatch):
    monkeypatch.setenv('G6_COLLECTOR_PIPELINE_V2', '1')
    settings_mod = importlib.import_module('src.collectors.settings')
    importlib.reload(settings_mod)
    s = settings_mod.CollectorSettings.load()
    assert s.pipeline_v2_flag is True
