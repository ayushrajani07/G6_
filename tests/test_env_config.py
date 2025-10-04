from __future__ import annotations
import os
from scripts.summary.env_config import SummaryEnv, load_summary_env


def _build_env(extra: dict[str,str]):
    base = {
        "G6_SUMMARY_REFRESH_SEC": "10",
        "G6_SUMMARY_META_REFRESH_SEC": "3",
        "G6_SUMMARY_RES_REFRESH_SEC": "7",
        "G6_PANELS_DIR": "data/panels",
        "G6_UNIFIED_HTTP": "on",
        "G6_UNIFIED_HTTP_PORT": "9400",
        "G6_SSE_HTTP": "1",
        "G6_SSE_HTTP_PORT": "9410",
        "G6_SUMMARY_METRICS_HTTP": "true",
        "G6_METRICS_HTTP_PORT": "9500",
        "G6_RESYNC_HTTP_PORT": "9600",
        "G6_SUMMARY_CURATED_MODE": "yes",
        "G6_SUMMARY_PLAIN_DIFF": "0",
        "G6_SUMMARY_ALT_SCREEN": "off",
        "G6_SUMMARY_AUTO_FULL_RECOVERY": "on",
        "G6_SUMMARY_SSE_TIMEOUT": "55",
        "G6_SUMMARY_DOSSIER_INTERVAL_SEC": "9",
        "G6_SUMMARY_THRESH_OVERRIDES": '{"dq.warn":82, "dq.error":68}',
        "G6_PROVIDER_LAT_WARN_MS": "410",
        "G6_PROVIDER_LAT_ERR_MS": "900",
        "G6_MEMORY_LEVEL1_MB": "210",
        "G6_MEMORY_LEVEL2_MB": "320",
        "G6_OUTPUT_SINKS": "stdout,logging,panels",
        "G6_PANEL_CLIP": "70",
        "G6_PANEL_MIN_COL_W": "38",
        "G6_PANEL_W_MARKET": "80",
        "G6_PANEL_H_MARKET": "6",
    }
    base.update(extra)
    return base


def test_basic_parsing_and_defaults():
    env_map = _build_env({})
    cfg = SummaryEnv.from_environ(env_map)
    assert cfg.refresh_unified_sec == 10
    assert cfg.refresh_meta_sec == 3
    assert cfg.refresh_res_sec == 7
    assert cfg.unified_http_enabled is True
    assert cfg.unified_http_port == 9400
    assert cfg.sse_http_enabled is True
    assert cfg.metrics_http_enabled is True
    assert cfg.metrics_http_port == 9500
    assert cfg.resync_http_port == 9600
    assert cfg.curated_mode is True
    # plain_diff suppression now always on (legacy G6_SUMMARY_PLAIN_DIFF removed)
    assert cfg.plain_diff_enabled is True
    assert cfg.alt_screen is False
    assert cfg.auto_full_recovery is True
    assert cfg.client_sse_timeout_sec == 55
    assert cfg.dossier_interval_sec == 9
    assert cfg.threshold_overrides.get('dq.warn') == 82
    assert cfg.threshold_overrides.get('dq.error') == 68
    assert cfg.provider_latency_warn_ms == 410
    assert cfg.provider_latency_err_ms == 900
    assert cfg.memory_level1_mb == 210
    assert cfg.memory_level2_mb == 320
    assert 'market' in cfg.panel_w_overrides
    assert cfg.panel_w_overrides['market'] == 80
    assert cfg.panel_h_overrides['market'] == 6


def test_unified_master_compatibility():
    # unified absent -> fall back to master
    env_map = _build_env({"G6_SUMMARY_REFRESH_SEC": "", "G6_MASTER_REFRESH_SEC": "12"})
    cfg = SummaryEnv.from_environ(env_map)
    assert cfg.refresh_unified_sec == 12
    # both absent -> default 15 meta/res
    env_map2 = _build_env({"G6_SUMMARY_REFRESH_SEC": "", "G6_MASTER_REFRESH_SEC": ""})
    del env_map2["G6_SUMMARY_REFRESH_SEC"]
    del env_map2["G6_MASTER_REFRESH_SEC"]
    cfg2 = SummaryEnv.from_environ(env_map2)
    assert cfg2.refresh_meta_sec == 15
    assert cfg2.refresh_res_sec == 15


def test_bool_parsing_variants():
    env_map = _build_env({"G6_UNIFIED_HTTP": "TRUE", "G6_SSE_HTTP": "Yes"})
    cfg = SummaryEnv.from_environ(env_map)
    assert cfg.unified_http_enabled is True
    assert cfg.sse_http_enabled is True
    env_map2 = _build_env({"G6_UNIFIED_HTTP": "off", "G6_SSE_HTTP": "0"})
    cfg2 = SummaryEnv.from_environ(env_map2)
    assert cfg2.unified_http_enabled is False
    assert cfg2.sse_http_enabled is False


def test_list_parsing_and_defaults():
    env_map = _build_env({"G6_SUMMARY_SSE_TYPES": "panel_full,panel_diff,panel_meta"})
    cfg = SummaryEnv.from_environ(env_map)
    assert cfg.client_sse_types == ["panel_full", "panel_diff", "panel_meta"]
    env_map2 = _build_env({"G6_SUMMARY_SSE_TYPES": ""})
    cfg2 = SummaryEnv.from_environ(env_map2)
    # falls back to default list when blank
    assert cfg2.client_sse_types == ["panel_full", "panel_diff"]


def test_cached_loader_idempotence(monkeypatch):
    monkeypatch.setenv("G6_SUMMARY_REFRESH_SEC", "21")
    cfg1 = load_summary_env(force_reload=True)
    assert cfg1.refresh_unified_sec == 21
    monkeypatch.setenv("G6_SUMMARY_REFRESH_SEC", "22")
    # Without force_reload still returns cached 21
    cfg2 = load_summary_env()
    assert cfg2.refresh_unified_sec == 21
    # With force_reload we get updated value
    cfg3 = load_summary_env(force_reload=True)
    assert cfg3.refresh_unified_sec == 22


def test_invalid_numeric_fallbacks():
    env_map = _build_env({"G6_SUMMARY_REFRESH_SEC": "not_a_number"})
    cfg = SummaryEnv.from_environ(env_map)
    # unified invalid -> None, defaults flow to meta/res (15)
    assert cfg.refresh_unified_sec is None
    assert cfg.refresh_meta_sec == 15
    assert cfg.refresh_res_sec == 15


def test_threshold_override_json_malformed():
    env_map = _build_env({"G6_SUMMARY_THRESH_OVERRIDES": "{"})  # malformed
    cfg = SummaryEnv.from_environ(env_map)
    assert cfg.threshold_overrides == {}
