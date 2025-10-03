"""Token provider abstraction layer.

Current providers:
 - kite: Real KiteConnect based provider (browser + manual flows)
 - fake: Lightweight test/dummy provider for headless tests

Environment overrides:
  G6_TOKEN_PROVIDER = kite|fake (default kite)
  G6_TOKEN_HEADLESS=1 to force headless (no browser / interactive flows)
"""

from typing import Type, Dict, Optional, Callable

from .base import TokenProvider
from .fake import FakeTokenProvider

_KiteProviderClass: Optional[Type[TokenProvider]]
try:  # Optional import: kite provider may have heavier deps
    from .kite import KiteTokenProvider as _KiteProviderClass  # pragma: no cover
except Exception:  # pragma: no cover - missing optional deps
    _KiteProviderClass = None

ProviderFactory = Callable[[], TokenProvider]

PROVIDER_REGISTRY: Dict[str, ProviderFactory] = {}

if _KiteProviderClass is not None:
    def _kite_factory(cls: Type[TokenProvider] = _KiteProviderClass) -> TokenProvider:  # default binds non-None
        return cls()
    PROVIDER_REGISTRY['kite'] = _kite_factory

def _fake_factory() -> TokenProvider:
    return FakeTokenProvider()

PROVIDER_REGISTRY['fake'] = _fake_factory

def get_provider(name: str) -> TokenProvider:
    name_l = name.lower()
    try:
        factory = PROVIDER_REGISTRY[name_l]
    except KeyError:
        raise ValueError(f"Unknown token provider '{name}'. Available: {sorted(PROVIDER_REGISTRY)}") from None
    return factory()
