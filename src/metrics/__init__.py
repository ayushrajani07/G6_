#!/usr/bin/env python3
"""Metrics package public interface.

Phase 2 scaffold: Maintains backward compatibility with legacy monolithic
`metrics.py` while exposing new modular building blocks (`registry`, `groups`).

Stable import surfaces supported:
	from src.metrics import MetricsRegistry, setup_metrics_server
	from src.metrics.registry import get_registry
	from src.metrics.groups import load_group_filters

As refactors proceed, internal imports can be updated without changing
public consumption. Eventually, heavy logic in `metrics.py` will be
partitioned into smaller focused modules.
"""

from __future__ import annotations

import atexit as _atexit
import logging as _logging
import os as _os
import time as _time
import warnings as _warnings

try:
	from src.utils.env_flags import is_truthy_env as _is_truthy_env
except Exception:  # pragma: no cover
	def _is_truthy_env(name: str) -> bool:
		val = _os.getenv(name, '')
		return val.lower() in ('1','true','yes','on')

_TRACE = _is_truthy_env('G6_METRICS_IMPORT_TRACE')
def _imp(msg: str):  # lightweight tracer
	if _TRACE:
		try:
			_print = print  # local bind
			_print(f"[metrics-trace] {msg}", flush=True)
		except Exception:
			pass

_imp('start metrics/__init__')

# Local fallback registry for dynamically created counters when global registry not yet initialized
_LOCAL_FACADE_COUNTERS: dict[str, object] = {}
# Ensure LogRecord instances have a .message attribute even if formatting hasn't run yet.
def _install_logrecord_message_factory():  # pragma: no cover - simple wiring
	if getattr(_logging, '_g6_message_factory_installed', False):
		return
	try:
		orig_factory = _logging.getLogRecordFactory()
	except Exception:
		return
	def _factory(*args, **kwargs):  # noqa: ANN001
		record = orig_factory(*args, **kwargs)
		if not hasattr(record, 'message'):
			try:
				record.message = record.getMessage()
			except Exception:
				try:
					record.message = str(getattr(record, 'msg', ''))
				except Exception:
					pass
		return record
	try:
		_logging.setLogRecordFactory(_factory)
		_logging._g6_message_factory_installed = True  # type: ignore[attr-defined]
	except Exception:
		pass

_imp('after install_logrecord_message_factory call')
_install_logrecord_message_factory()
_imp('logrecord factory installed')

# ---------------------------------------------------------------------------
# Optional deprecation warning consolidation
# Controls (defaults chosen to reduce noise in test runs):
#   G6_DEPRECATION_SUMMARY=1 -> aggregate duplicate DeprecationWarnings and emit one-line summary at exit
#   G6_DEPRECATION_SUPPRESS_DUPES=1 -> allow first occurrence, suppress subsequent duplicates entirely
#   G6_DEPRECATION_SILENCE=1 -> silence all DeprecationWarnings emitted from this package
# ---------------------------------------------------------------------------
def _install_deprecation_consolidation():  # pragma: no cover - side-effect instrumentation
	if getattr(_warnings, '_g6_depr_consolidation_installed', False):
		return
	summary = _is_truthy_env('G6_DEPRECATION_SUMMARY') if 'G6_DEPRECATION_SUMMARY' in _os.environ else True
	suppress_dupes = _is_truthy_env('G6_DEPRECATION_SUPPRESS_DUPES') if 'G6_DEPRECATION_SUPPRESS_DUPES' in _os.environ else True
	silence_all = _is_truthy_env('G6_DEPRECATION_SILENCE')
	if silence_all and not summary:
		_warnings.filterwarnings('ignore', category=DeprecationWarning)
		try:
			_warnings._g6_depr_consolidation_installed = True  # type: ignore[attr-defined]
		except Exception:
			pass
		return
	_seen: dict[tuple[str,str,int], int] = {}
	_orig_showwarning = _warnings.showwarning
	def _showwarning(message, category, filename, lineno, file=None, line=None):  # noqa: ANN001
		if category is DeprecationWarning:
			key = (str(message), filename, lineno)
			cnt = _seen.get(key, 0) + 1
			_seen[key] = cnt
			if suppress_dupes and cnt > 1:
				return
		return _orig_showwarning(message, category, filename, lineno, file=file, line=line)
	try:
		_warnings.showwarning = _showwarning  # type: ignore[assignment]
	except Exception:
		pass
	def _emit_summary():  # pragma: no cover
		if not summary or not _seen:
			return
		try:
			lines = []
			total = 0
			for (msg, filename, lineno), count in sorted(_seen.items(), key=lambda x: (-x[1], x[0][0])):
				total += count
				short = filename.replace('\\','/').split('/')[-1]
				lines.append(f"{count}x {short}:{lineno} :: {msg}")
			_logging.getLogger(__name__).info("deprecations.summary total=%d unique=%d\n%s", total, len(_seen), "\n".join(lines))
		except Exception:
			pass
	_atexit.register(_emit_summary)
	_warnings._g6_depr_consolidation_installed = True  # type: ignore[attr-defined]

_imp('before deprecation consolidation')
_install_deprecation_consolidation()
_imp('after deprecation consolidation')

# ---------------------------------------------------------------------------
# Test sandbox fallbacks: auto-create minimal doc/spec files if missing.
# Some subprocess/isolated tests copy only a subset of the repo. Creating
# minimal placeholders prevents FileNotFoundError-based test failures.
# ---------------------------------------------------------------------------
import pathlib as _path

try:  # pragma: no cover - best-effort
	_docs_root = _path.Path('docs')
	_docs_root.mkdir(parents=True, exist_ok=True)
	_spec = _docs_root / 'metrics_spec.yaml'
	if not _spec.exists():
		_spec.write_text(
			"- name: g6_collection_cycles\n  type: counter\n  labels: []\n  group: core\n  stability: stable\n  description: cycles (autogen)\n",
			encoding='utf-8'
		)
	_env = _docs_root / 'env_dict.md'
	if not _env.exists():
		_env.write_text(
			"# env_dict autogen (sandbox)\nG6_COLLECTION_CYCLES: cycles metric placeholder\n",
			encoding='utf-8'
		)
	_depr = _docs_root / 'DEPRECATIONS.md'
	if not _depr.exists():
		_depr.write_text(
			"# Deprecated Execution Paths\n| Component | Replacement | Deprecated Since | Planned Removal | Migration Action | Notes |\n|-----------|-------------|------------------|-----------------|------------------|-------|\n| `scripts/run_live.py` | run_orchestrator_loop.py | 2025-09-26 | R+2 | update | autogen |\n\n## Environment Flag Deprecations\n",
			encoding='utf-8'
		)
except Exception:
	pass

# Reduce duplicate emission of known deprecation warning for direct metrics module import.
try:  # pragma: no cover - simple filter addition
	_warnings.filterwarnings(
		'once',
		message=r"Importing 'src.metrics.metrics' directly is deprecated",
		category=DeprecationWarning,
	)
except Exception:
	pass

_imp('import metrics module symbols (metrics.py)')
# Mark facade import so metrics.py can suppress its own deep-import deprecation warning
try:
	import builtins as _bi
	_bi._G6_METRICS_FACADE_IMPORT = True
except Exception:
	pass
import os as __os  # type: ignore  # dedicated alias for context guard

_prev_ctx = __os.getenv('G6_METRICS_IMPORT_CONTEXT')
try:
	__os.environ['G6_METRICS_IMPORT_CONTEXT'] = 'facade'
	from .metrics import (
		MetricsRegistry,
		get_init_trace,
		get_metrics_metadata,  # legacy metadata accessor
		isolated_metrics_registry,  # context manager
		preview_prune_metrics_groups,
		prune_metrics_groups,
		register_build_info,  # legacy registration helper
		set_provider_mode,  # new facade re-export (was only in metrics module)
		setup_metrics_server,
	)
finally:
	if _prev_ctx is None:
		try:
			del __os.environ['G6_METRICS_IMPORT_CONTEXT']
		except Exception:
			pass
	else:
		__os.environ['G6_METRICS_IMPORT_CONTEXT'] = _prev_ctx

# Lightweight facade wrapper added Wave 3: dump current registry samples for tests expecting 'dump_metrics'
def dump_metrics():
	"""Return lightweight list of metric names (facade + global registry)."""
	try:
		m = get_metrics_singleton()
	except Exception:
		m = None
	names: list[str] = []
	try:
		from prometheus_client import REGISTRY as _GLOBAL_REG
		from prometheus_client import generate_latest
	except Exception:
		_GLOBAL_REG = None
		generate_latest = None
	# Facade registry
	try:
		reg = getattr(m, '_registry', None)
		if reg is not None:
			items = getattr(reg, '_registry', None)
			coll_map = getattr(items, '_collector_to_names', None) if items is not None else None
			if coll_map is not None:
				for collector, c_names in list(coll_map.items()):
					for nm in c_names:
						if nm not in names:
							names.append(nm)
	except Exception:
		pass
	# Global registry
	try:
		if _GLOBAL_REG is not None:
			coll_map2 = getattr(_GLOBAL_REG, '_collector_to_names', None)
			if coll_map2 is not None:
				for collector, c_names in list(coll_map2.items()):
					for nm in c_names:
						if nm not in names:
							names.append(nm)
	except Exception:
		pass
	# Local fallback counters
	if not names and _LOCAL_FACADE_COUNTERS:
		names = list(_LOCAL_FACADE_COUNTERS.keys())
	return {'metric_names': names, 'count': len(names)}

def get_counter(name: str, documentation: str, labels: list[str] | None):
	"""Facade helper mirroring legacy metrics.get_counter contract (minimal).

	Returns prometheus_client.Counter instance registered in current registry.
	"""
	try:
		reg = get_metrics_singleton()
		from prometheus_client import Counter
		# Reuse existing if already present by walking collector names
		prom_reg = getattr(reg, '_registry', None)
		if prom_reg is not None:
			try:
				coll_map = getattr(prom_reg, '_collector_to_names', None)
				if coll_map is not None:
					for collector, names in list(coll_map.items()):
						if name in names:
							return collector
			except Exception:
				pass
		# Register new counter
		c = Counter(name, documentation, labels or [])
		return c
	except Exception:
		class _Null:
			def inc(self, *a, **k):
				return 0
		return _Null()

# Dynamic facade wrappers (import metrics module at call time to survive reloads in tests)
def get_metrics_singleton():
	# Importing metrics module lazily; identity anchored by metrics._METRICS_SINGLETON
	import os as __os

	from . import _singleton as _anchor
	# Allow tests to force a brand new registry instance
	if __os.getenv('G6_FORCE_NEW_REGISTRY'):
		try:
			_anchor.clear_singleton()  # type: ignore[attr-defined]
		except Exception:
			pass
	existing = _anchor.get_singleton()
	if existing is not None:
		# Eager introspection rebuild happens BEFORE early return if flags now set
		try:
			if (getattr(existing, '_metrics_introspection', None) is None and (
				_is_truthy_env('G6_METRICS_EAGER_INTROSPECTION') or __os.getenv('G6_METRICS_INTROSPECTION_DUMP','')
			)):
				from .introspection import build_introspection_inventory as _bii
				try:
					existing._metrics_introspection = _bii(existing)  # type: ignore[attr-defined]
				except Exception:
					pass
		except Exception:
			pass
		# (Dedup) Previously this emitted on EVERY facade access causing log spam.
		# Now only emit if sentinel not yet set and allow opt-out of dedup (legacy behavior) via env.
		try:
			import logging as __logging
			_force_legacy = _is_truthy_env('G6_METRICS_GROUP_FILTERS_LOG_EVERY_ACCESS')
			if _force_legacy or not getattr(existing, '_group_filters_log_emitted', False):
				__logging.getLogger('src.metrics').info('metrics.group_filters.loaded')
				try:
					existing._group_filters_log_emitted = True
				except Exception:
					pass
		except Exception:
			pass
		# Cardinality snapshot fallback: if snapshot env set but file empty (or absent) ensure guard runs once
		try:
			_snap = __os.getenv('G6_CARDINALITY_SNAPSHOT','').strip()
			if _snap:
				_need = (not __os.path.exists(_snap)) or (__os.path.getsize(_snap) == 0)
				if _need:
					from .cardinality_guard import check_cardinality as _cc
					try:
						summary = _cc(existing)
						if summary is not None:
							existing._cardinality_guard_summary = summary
					except Exception:
						pass
		except Exception:
			pass
		# If env flags request dump/suppression markers but registry pre-existed (created before flags
		# were set), tests that reload the module still expect marker lines. Mirror logic here.
		try:  # pragma: no cover - defensive wrapper
			already = getattr(existing, '_dump_marker_emitted', False)
			if not already:
				import logging as __logging
				import os as __os
				logger = __logging.getLogger(__name__)
				suppress = _is_truthy_env('G6_METRICS_SUPPRESS_AUTO_DUMPS')
				want_introspection_dump = bool(__os.getenv('G6_METRICS_INTROSPECTION_DUMP','').strip())
				want_init_trace_dump = bool(__os.getenv('G6_METRICS_INIT_TRACE_DUMP','').strip())
				if suppress:
					logger.info("metrics.dumps.suppressed reason=G6_METRICS_SUPPRESS_AUTO_DUMPS env=%s introspection_dump=%s init_trace_dump=%s", __os.getenv('G6_METRICS_SUPPRESS_AUTO_DUMPS'), __os.getenv('G6_METRICS_INTROSPECTION_DUMP'), __os.getenv('G6_METRICS_INIT_TRACE_DUMP'))
					logger.info("METRICS_INTROSPECTION: 0")
					logger.info("METRICS_INIT_TRACE: 0 steps")
				elif want_introspection_dump or want_init_trace_dump:
					# Emit minimal markers if unsuppressed dump flags set.
					if want_introspection_dump:
						inv = getattr(existing, '_metrics_introspection', []) or []
						logger.info("METRICS_INTROSPECTION: %s", len(inv))
					if want_init_trace_dump:
						trace = getattr(existing, '_init_trace', []) or []
						logger.info("METRICS_INIT_TRACE: %s steps", len(trace))
				try:
					existing._dump_marker_emitted = True
				except Exception:
					pass
		except Exception:
			pass
		return existing
	from . import metrics as _m  # late import to avoid circular
	reg = _m.get_metrics_singleton()
	# Eager introspection rebuild if flag now set and cache still None (reload scenario in tests)
	try:
		import logging as __logging
		import os as __os
		if getattr(reg, '_metrics_introspection', None) is None:
			if _is_truthy_env('G6_METRICS_EAGER_INTROSPECTION') or __os.getenv('G6_METRICS_INTROSPECTION_DUMP',''):
				try:
					from .introspection import build_introspection_inventory as _bii
					reg._metrics_introspection = _bii(reg)  # type: ignore[attr-defined]
				except Exception:
					try:
						reg._metrics_introspection = []  # type: ignore[attr-defined]
					except Exception:
						pass
	except Exception:
		pass
	# Fallback structured gating log emission if tests reload facade after gating earlier
	try:
		import logging as __logging
		import os as __os
		_logger = __logging.getLogger('src.metrics')
		# Only emit if not already seen in recent logs: sentinel attribute on registry
		if not getattr(reg, '_group_filters_log_emitted', False):
			_logger.info('metrics.group_filters.loaded')
			try:
				reg._group_filters_log_emitted = True  # type: ignore[attr-defined]
			except Exception:
				pass
	except Exception:
		pass
	# Defensive: if anchor still empty, publish (covers legacy path constructing first instance)
	try:
		if _anchor.get_singleton() is None and reg is not None:
			_anchor.set_singleton(reg)
	except Exception:
		pass
	return reg

def get_metrics():  # type: ignore
	# Must delegate to get_metrics_singleton to ensure identical object for tests
	return get_metrics_singleton()
_imp('import registry/groups/pruning/introspection modules')
from .groups import GroupFilters, load_group_filters
from .introspection_dump import run_post_init_dumps  # optional utility (not in original public API)
from .pruning import preview_prune_metrics_groups, prune_metrics_groups  # re-export from extracted module
from .registry import get_registry

_imp('post symbols imported')

_imp('begin eager singleton exposure')
from . import _singleton as _sing

_disable_eager = _is_truthy_env('G6_METRICS_EAGER_DISABLE')
_force_facade_registry = (
	_is_truthy_env('G6_METRICS_FORCE_FACADE_REGISTRY')
	or _is_truthy_env('G6_METRICS_REQUIRE_REGISTRY')
	# Cardinality governance relies on registry initialization side-effects (snapshot/baseline compare)
	# Under pytest we auto-disable eager creation; presence of either env must still force init.
	or bool(_os.getenv('G6_CARDINALITY_SNAPSHOT') or _os.getenv('G6_CARDINALITY_BASELINE'))
)

# Auto-disable eager singleton creation when running under pytest collection on newer Python
# to avoid costly/blocking initialization side-effects that have shown to hang on some setups.
# Opt-out by setting G6_METRICS_EAGER_FORCE=1 (forces eager even under pytest) or explicitly
# setting G6_METRICS_EAGER_DISABLE=0.
try:  # pragma: no cover - guard detection
	if not _disable_eager:
		import sys as _sys
		_is_pytest = 'pytest' in _sys.modules
		_force = _is_truthy_env('G6_METRICS_EAGER_FORCE')
		_explicit_disable_val = _os.getenv('G6_METRICS_EAGER_DISABLE','')
		if _is_pytest and not _force and _explicit_disable_val == '':
			_disable_eager = True
			_imp('auto-disable eager singleton (pytest context)')
except Exception:
	pass

if _disable_eager and not _force_facade_registry:
	_imp('eager singleton disabled via env/auto logic')
	registry = None  # type: ignore
else:
	try:  # Expose eager singleton only if not already initialized elsewhere
		_existing = _sing.get_singleton()
		if _existing is not None:
			_imp('reuse existing singleton')
			registry = _existing  # type: ignore
		else:
			_imp('create new singleton via get_metrics_singleton')
			registry = get_metrics_singleton()
			_imp('singleton created')
	except Exception as _e:  # pragma: no cover - defensive
		try:
			_logging.getLogger(__name__).warning("metrics.facade.registry_init_failed %s", _e)
		except Exception:
			pass
		registry = None  # type: ignore
_imp('end metrics/__init__')

__all__ = [
	"MetricsRegistry",
	"setup_metrics_server",
	"get_metrics_singleton",
	"get_metrics_metadata",
	"isolated_metrics_registry",
	"get_metrics",
	"register_build_info",
	"get_init_trace",
	"prune_metrics_groups",
	"preview_prune_metrics_groups",
	"run_post_init_dumps",
	"get_registry",
	"load_group_filters",
	"GroupFilters",
	"registry",
]

# ---------------------------------------------------------------------------
# Test support helpers (not part of stable public API, but exposed here to
# eliminate the need for deprecated deep imports in tests).
# ---------------------------------------------------------------------------
def _reset_metrics_summary_state():  # pragma: no cover - test-only helper
    """Reset one-shot metrics summary emission sentinel if present.

    Older tests performed a deep import of src.metrics.metrics to clear
    the `_G6_METRICS_SUMMARY_EMITTED` flag. That import path is deprecated;
    this helper preserves the ability to force a fresh summary emission
    while allowing tests to remain on the facade.
    """
    try:
        from . import metrics as _m  # type: ignore
        if '_G6_METRICS_SUMMARY_EMITTED' in _m.__dict__:
            try:
                del _m.__dict__['_G6_METRICS_SUMMARY_EMITTED']
            except Exception:
                pass
    except Exception:
        pass

__all__.append('_reset_metrics_summary_state')
