"""Collectors package facade.

Historically exported `run_unified_collectors` which some tests replace by
stubbing `src.collectors.unified_collectors` with only a subset of helper
functions (e.g. `_resolve_expiry`, `_enrich_quotes`). The previous strict import
raised ImportError when the stub lacked `run_unified_collectors`, preventing the
shadow pipeline tests from executing.

We degrade gracefully: attempt to import the symbol, but fall back to a no-op
placeholder if absent so downstream unit tests that directly exercise
`pipeline.shadow` (using only helper functions) can proceed. This keeps runtime
behavior identical in production where the real symbol exists while improving
test resilience.
"""

from .providers_interface import Providers  # noqa: F401

try:  # pragma: no cover - trivial defensive shim
	from .unified_collectors import run_unified_collectors  # type: ignore  # noqa: F401
except Exception:  # pragma: no cover
	def run_unified_collectors(*_a, **_k):  # type: ignore
		raise RuntimeError("run_unified_collectors not available in this test/stub context")

__all__ = ["Providers", "run_unified_collectors"]
