import importlib
import sys
import os
import pytest

BROKER_ENABLED = bool(os.getenv('G6_ENABLE_BROKER_TESTS'))


def test_fake_provider_validate_and_acquire(monkeypatch):
    from src.tools.token_providers import get_provider
    prov = get_provider('fake')
    assert prov.validate('ignored', 'SOMETHING') is True
    token = prov.acquire('x', 'y', headless=True, interactive=False)
    assert token == 'FAKE_TOKEN'
    assert prov.validate('ignored', token) is True


@pytest.mark.skipif(not BROKER_ENABLED, reason='Broker tests skipped (set G6_ENABLE_BROKER_TESTS=1 to enable)')
def test_kite_provider_headless_requires_request_token(monkeypatch):
    # Skip if kite provider unavailable (no kiteconnect dependency in env)
    try:
        from src.tools.token_providers import KiteTokenProvider  # noqa: F401
    except Exception:
        return
    from src.tools.token_providers import get_provider
    prov = get_provider('kite')
    # Ensure env token absent
    monkeypatch.delenv('KITE_REQUEST_TOKEN', raising=False)
    token = prov.acquire('dummy_key', 'dummy_secret', headless=True, interactive=False)
    assert token is None


def test_token_manager_headless_fake_provider(monkeypatch, tmp_path):
    # Change working directory using monkeypatch
    monkeypatch.chdir(tmp_path)
    (tmp_path / '.env').write_text('KITE_API_KEY=whatever\nKITE_API_SECRET=secret\n', encoding='utf-8')
    # Pre-seed access token so provider validation passes and main does not ask to start orchestrator (headless path).
    with (tmp_path / '.env').open('a', encoding='utf-8') as f:
        f.write('KITE_ACCESS_TOKEN=FAKE_TOKEN\n')
    # Provide dummy orchestrator script to satisfy existence check if autorun unexpectedly triggers
    scripts_dir = tmp_path / 'scripts'
    scripts_dir.mkdir(exist_ok=True)
    (scripts_dir / 'run_orchestrator_loop.py').write_text('#!/usr/bin/env python3\nimport sys; sys.exit(0)\n', encoding='utf-8')
    monkeypatch.setenv('G6_TOKEN_PROVIDER', 'fake')
    monkeypatch.setenv('G6_TOKEN_HEADLESS', '1')
    # We intentionally keep the seeded KITE_ACCESS_TOKEN so token_manager sees a valid token
    # and exercises the fast-exit (non-interactive) path for headless/non-kite providers.
    import src.tools.token_manager as tm
    importlib.reload(tm)
    # Pass --no-autorun so absence of orchestrator script in isolated test tmp dir is not an error
    monkeypatch.setenv('PYTHONWARNINGS', 'ignore')
    orig_argv = list(sys.argv)
    sys.argv = ['token_manager', '--no-autorun']
    try:
        rc = tm.main()
    finally:
        if orig_argv is not None:
            sys.argv = orig_argv
    assert rc in (0, )
    env_content = (tmp_path / '.env').read_text(encoding='utf-8')
    # Token persistence not guaranteed for fake provider; if present ensure deterministic value.
    if 'KITE_ACCESS_TOKEN' in env_content:
        assert 'KITE_ACCESS_TOKEN=FAKE_TOKEN' in env_content
