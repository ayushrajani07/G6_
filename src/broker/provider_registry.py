"""Provider registry (Phase A7 Step 11 scaffold).

Purpose:
  Centralize provider discovery, lazy construction, and selection logic.
  Initial scope targets a single concrete provider (KiteProvider) but
  establishes an interface for future providers (e.g., AltProvider).

Design Goals:
  - Simple global registry with explicit register / get operations.
  - Lazy instantiation: store factory callables, not instances, unless
    eager flag is passed.
  - Environment-driven default selection via G6_PROVIDER (case-insensitive).
  - Introspection helpers for diagnostics & tests.
  - Minimal surface: avoid over-engineering until a second provider ships.

Environment Variables:
  G6_PROVIDER=<name>  Select provider by canonical name (registered key).
                       Falls back to default if unset or unknown.

Public API:
  register_provider(name: str, factory: Callable[[], Any], *, default=False)
  get_provider(name: str | None = None) -> Any
  set_default(name: str) -> None
  list_providers() -> list[str]
  reset_registry() -> None (test helper)
  get_active_name() -> str | None

Error Handling:
  - Unknown provider lookup returns None (callers may raise custom errors).
  - Duplicate registration overwrites previous factory but logs a warning.

Thread Safety:
  - Simple RLock around mutations; read operations acquire the lock briefly.

Future Enhancements (Deferred):
  - Per-provider capability metadata (e.g., supports_options, supports_ltp).
  - Health / diagnostics pass-through (aggregate call).
  - Pluggable entry-point loading (pkg_resources / importlib.metadata).
"""
from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable, Mapping
from typing import Any

logger = logging.getLogger(__name__)

_LOCK = threading.RLock()
_FACTORIES: dict[str, Callable[[], Any]] = {}
_SINGLETONS: dict[str, Any] = {}
_CAPS: dict[str, dict[str, bool]] = {}  # capability metadata per provider
_DEFAULT: str | None = None
_ACTIVE: str | None = None  # last requested provider name (resolved)


def register_provider(
    name: str,
    factory: Callable[[], Any],
    *,
    default: bool = False,
    eager: bool = False,
    capabilities: Mapping[str, bool] | None = None,
) -> None:
    """Register a provider factory under a canonical lowercase name.

    If eager=True the instance is constructed immediately and stored; otherwise
    construction is deferred until first get_provider() call for that name.
    """
    key = name.strip().lower()
    if not key:
        raise ValueError("provider name cannot be empty")
    with _LOCK:
        if key in _FACTORIES:
            try:
                logger.warning("provider_registry.duplicate_registration name=%s (overwriting)", key)
            except Exception:
                pass
        _FACTORIES[key] = factory
        if capabilities is not None:
            _CAPS[key] = {k: bool(v) for k,v in capabilities.items()}
        elif key not in _CAPS:
            _CAPS[key] = {}
        if default or _DEFAULT is None:
            # First registration becomes default unless explicitly skipped
            _set_default_no_lock(key)
        if eager:
            try:
                _SINGLETONS[key] = factory()
            except Exception as e:  # pragma: no cover
                try:
                    logger.error("provider_registry.eager_init_failed name=%s err=%s", key, e)
                except Exception:
                    pass


def _set_default_no_lock(name: str) -> None:
    global _DEFAULT  # noqa: PLW0603
    _DEFAULT = name


def set_default(name: str) -> None:
    key = name.strip().lower()
    with _LOCK:
        if key not in _FACTORIES:
            raise KeyError(f"unknown provider: {name}")
        _set_default_no_lock(key)


def list_providers() -> list[str]:
    with _LOCK:
        return sorted(_FACTORIES.keys())


def get_active_name() -> str | None:
    with _LOCK:
        return _ACTIVE


def get_provider(name: str | None = None, *, fresh: bool = False) -> Any:
    """Return a provider instance.

    Resolution precedence:
      1. Explicit name argument (if provided)
      2. Environment variable G6_PROVIDER
      3. Default provider (first registered or last set_default)

    If fresh=True a new instance is constructed (does not replace cached singleton).
    Otherwise a cached singleton is reused (created lazily).
    """
    global _ACTIVE  # noqa: PLW0603
    with _LOCK:
        # Resolve name precedence
        candidate = name.strip().lower() if name else None
        if candidate is None:
            env_provider = os.getenv('G6_PROVIDER', '').strip().lower()
            candidate = env_provider or _DEFAULT
        if candidate is None:
            return None
        factory = _FACTORIES.get(candidate)
        if factory is None:
            try:
                logger.warning("provider_registry.unknown_provider name=%s", candidate)
            except Exception:
                pass
            return None
        if fresh:
            try:
                inst = factory()
            except Exception as e:  # pragma: no cover
                try: logger.error("provider_registry.factory_error name=%s err=%s", candidate, e)
                except Exception: pass
                return None
            _ACTIVE = candidate
            return inst
        # cached path
        inst = _SINGLETONS.get(candidate)
        if inst is None:
            try:
                inst = factory()
                _SINGLETONS[candidate] = inst
            except Exception as e:  # pragma: no cover
                try: logger.error("provider_registry.factory_error name=%s err=%s", candidate, e)
                except Exception: pass
                return None
        _ACTIVE = candidate
        return inst


def reset_registry() -> None:  # test helper
    global _FACTORIES, _SINGLETONS, _DEFAULT, _ACTIVE, _CAPS  # noqa: PLW0603
    with _LOCK:
        _FACTORIES = {}
        _SINGLETONS = {}
        _DEFAULT = None
        _ACTIVE = None
        _CAPS = {}


# --- Capabilities Accessors ----------------------------------------------
def get_capabilities(name: str | None = None) -> dict[str, bool]:
    """Return capabilities dict for provider (empty dict if unknown).

    Name resolution mimics get_provider precedence if name omitted.
    """
    with _LOCK:
        if name:
            return dict(_CAPS.get(name.strip().lower(), {}))
        # derive from active or default
        target = _ACTIVE or _DEFAULT
        return dict(_CAPS.get(target, {})) if target else {}


def provider_supports(capability: str, name: str | None = None) -> bool:
    caps = get_capabilities(name)
    return bool(caps.get(capability, False))


# --- Auto-registration for KiteProvider (best-effort) ---------------------
try:  # pragma: no cover - import guard
    from src.provider.config import get_provider_config

    from .kite_provider import KiteProvider
    register_provider(
        'kite',
    lambda: KiteProvider.from_provider_config(get_provider_config()),
        default=True,
        eager=False,
        capabilities={
            'quotes': True,
            'ltp': True,
            'options': True,
            'instruments': True,
            'expiries': True,
        },
    )
except Exception:
    pass

__all__ = [
    'register_provider','get_provider','set_default','list_providers','reset_registry','get_active_name'
]
