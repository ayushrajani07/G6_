from src.collector.settings import CollectorSettings, get_collector_settings
import os

def test_collector_settings_defaults(monkeypatch):
    # Clear relevant env
    keys = [k for k in os.environ if k.startswith('G6_')]
    for k in keys:
        monkeypatch.delenv(k, raising=False)
    s = CollectorSettings.from_env({})
    assert s.min_volume == 0
    assert s.min_oi == 0
    assert s.volume_percentile == 0.0
    assert s.salvage_enabled is False
    assert s.retry_on_empty is True  # default True
    assert s.pipeline_v2_flag is False


def test_collector_settings_parsing(monkeypatch):
    monkeypatch.setenv('G6_FILTER_MIN_VOLUME','123')
    monkeypatch.setenv('G6_FILTER_MIN_OI','456')
    monkeypatch.setenv('G6_FILTER_VOLUME_PERCENTILE','0.85')
    monkeypatch.setenv('G6_FOREIGN_EXPIRY_SALVAGE','1')
    monkeypatch.setenv('G6_DOMAIN_MODELS','true')
    monkeypatch.setenv('G6_TRACE_COLLECTOR','yes')
    monkeypatch.setenv('G6_COLLECTOR_RETRY_ON_EMPTY','0')
    monkeypatch.setenv('G6_COLLECTOR_PIPELINE_V2','1')
    monkeypatch.setenv('G6_COLLECTOR_LOG_LEVEL_OVERRIDES','fetch=DEBUG,resolve=INFO')
    s = get_collector_settings(force_reload=True)
    assert s.min_volume == 123
    assert s.min_oi == 456
    assert abs(s.volume_percentile - 0.85) < 1e-9
    assert s.salvage_enabled is True
    assert s.domain_models is True
    assert s.trace_enabled is True
    assert s.retry_on_empty is False
    assert s.pipeline_v2_flag is True
    assert s.log_level_overrides.get('fetch') == 'DEBUG'
    assert s.log_level_overrides.get('resolve') == 'INFO'
