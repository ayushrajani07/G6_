import logging, json
from io import StringIO

def test_all_summaries_once(monkeypatch, tmp_path):
    # Enable human + JSON variants for all summaries
    for flag in (
        'G6_SETTINGS_SUMMARY_HUMAN','G6_PROVIDER_SUMMARY_HUMAN','G6_METRICS_SUMMARY_HUMAN','G6_ORCH_SUMMARY_HUMAN',
        'G6_SETTINGS_SUMMARY_JSON','G6_PROVIDER_SUMMARY_JSON','G6_METRICS_SUMMARY_JSON','G6_ORCH_SUMMARY_JSON',
        'G6_ENV_DEPRECATIONS_SUMMARY_JSON'
    ):
        monkeypatch.setenv(flag, '1')
    monkeypatch.setenv('G6_FORCE_NEW_REGISTRY','1')  # ensure fresh metrics registry

    cfg = {
        'version': '2.0', 'application': 'integration',
        'metrics': {'port': 9108, 'host': '127.0.0.1'},
        'collection': {'interval_seconds': 1},
        'storage': {'csv_dir': str(tmp_path / 'csv')},
        'indices': {
            'NIFTY': {'enable': True, 'strikes_itm': 1, 'strikes_otm': 1, 'expiries': ['2025-12-31']},
        },
        'features': {'analytics_startup': False},
        'console': {'fancy_startup': False, 'live_panel': False, 'startup_banner': False, 'force_ascii': True, 'runtime_status_file': ''},
    }
    cfg_path = tmp_path / 'config.json'
    cfg_path.write_text(json.dumps(cfg))

    # Capture relevant loggers BEFORE imports that may emit
    targeted = [
        'src.orchestrator.bootstrap',
        'src.collector.settings',
        'src.broker.kite_provider',
        'src.metrics.metrics',
        'src.observability.startup_summaries',
    ]
    loggers = [logging.getLogger(n) for n in targeted]
    originals = [(lg, lg.level) for lg in loggers]
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    for lg,_lvl in originals:
        lg.setLevel(logging.INFO)
        lg.addHandler(handler)

    try:
        # Reset dispatcher internal state (preserve registry so env.deprecations emitter stays registered)
        import importlib, sys
        import src.observability.startup_summaries as ss  # type: ignore
        ss._reset_startup_summaries_state(clear_registry=False)  # type: ignore

        # Reload key modules to clear one-shot sentinels via module re-import side effects
        for mod_name in [
            'src.collector.settings',
            'src.broker.kite_provider',
            # NOTE: avoid deprecated deep import; metrics module will be reloaded lazily via facade if needed
            'src.orchestrator.bootstrap',
        ]:
            try:
                if mod_name in sys.modules:
                    importlib.reload(sys.modules[mod_name])
                else:
                    importlib.import_module(mod_name)
            except Exception:
                pass

        # Clear metrics summary sentinel post-reload to force emission under this capture
        try:
            from src.metrics import _reset_metrics_summary_state  # type: ignore
            _reset_metrics_summary_state()
        except Exception:
            pass
        # Clear settings summary sentinel + singleton
        try:
            import src.collector.settings as _cs  # type: ignore
            if '_G6_SETTINGS_SUMMARY_EMITTED' in _cs.__dict__:
                del _cs.__dict__['_G6_SETTINGS_SUMMARY_EMITTED']
            if getattr(_cs, '_settings_singleton', None) is not None:
                try: _cs._settings_singleton = None  # type: ignore
                except Exception: pass
        except Exception:
            pass
        # Clear provider summary sentinel
        try:
            import src.broker.kite_provider as _kp  # type: ignore
            if '_KITE_PROVIDER_SUMMARY_EMITTED' in _kp.__dict__:
                del _kp.__dict__['_KITE_PROVIDER_SUMMARY_EMITTED']
                # Explicitly instantiate provider to emit summary under capture (even if orchestrator chooses mock path) + reset helper
            try:
                _kp.KiteProvider(api_key=None, access_token=None)
            except Exception:
                pass
        except Exception:
            pass
            # Helper-based reset (ensures deterministic emission even if earlier tests instantiated provider)
            try:
                from src.broker.kite.startup_summary import _reset_provider_summary_state  # type: ignore
                import src.broker.kite_provider as _kp2  # type: ignore
                _reset_provider_summary_state()
                try:
                    _kp2.KiteProvider(api_key=None, access_token=None)
                except Exception:
                    pass
            except Exception:
                pass
        # Clear orchestrator summary sentinel
        try:
            import src.orchestrator.bootstrap as _ob  # type: ignore
            if '_G6_ORCH_SUMMARY_EMITTED' in _ob.__dict__:
                del _ob.__dict__['_G6_ORCH_SUMMARY_EMITTED']
        except Exception:
            pass

        # Execute bootstrap (emits orchestrator + collector + provider summaries)
        from src.orchestrator import bootstrap  # type: ignore
        bootstrap.bootstrap_runtime(str(cfg_path))

        # Force metrics registry init to emit metrics summary
        try:
            from src.metrics import MetricsRegistry  # type: ignore
            MetricsRegistry()
        except Exception:
            pass

        # Force env deprecations emission explicitly (even when zero)
        ss._force_emit_env_deprecations_summary()  # type: ignore

        # Emit any remaining registered summaries + composite hash
        ss.emit_all_summaries()  # type: ignore
    finally:
        for lg,lvl in originals:
            lg.removeHandler(handler)
            lg.setLevel(lvl)

    out = stream.getvalue()

    def _count_structured(token: str) -> int:
        c = 0
        for line in out.splitlines():
            if not line.strip().startswith(token):
                continue
            remainder = line.strip()[len(token):].strip()
            if '=' in remainder:
                c += 1
        return c

    for token in ['collector.settings.summary','provider.kite.summary','metrics.registry.summary','orchestrator.summary','env.deprecations.summary']:
        assert _count_structured(token) == 1, f"missing or duplicate structured line for {token}:\n{out}"

    # Ensure at least JSON variants for core four (env deprecations optional already counted via structured)
    assert out.count('.summary.json') >= 4
    assert 'startup.summaries.hash' in out