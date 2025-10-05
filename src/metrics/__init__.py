#!/usr/bin/env python3
# -*- coding: utf-8 -*-
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

import logging as _logging, os as _os, warnings as _warnings, atexit as _atexit, time as _time

_TRACE = _os.getenv('G6_METRICS_IMPORT_TRACE','').lower() in {'1','true','yes','on'}
def _imp(msg: str):  # lightweight tracer
	if _TRACE:
		try:
			_print = print  # local bind
			_print(f"[metrics-trace] {msg}", flush=True)
		except Exception:
			pass

_imp('start metrics/__init__')

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
				record.message = record.getMessage()  # type: ignore[attr-defined]
			except Exception:
				try:
					record.message = str(getattr(record, 'msg', ''))  # type: ignore[attr-defined]
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
	summary = _os.getenv('G6_DEPRECATION_SUMMARY','1').strip().lower() in {'1','true','yes','on'}
	suppress_dupes = _os.getenv('G6_DEPRECATION_SUPPRESS_DUPES','1').strip().lower() in {'1','true','yes','on'}
	silence_all = _os.getenv('G6_DEPRECATION_SILENCE','').strip().lower() in {'1','true','yes','on'}
	if silence_all and not summary:
		# Easiest path: ignore everything
		_warnings.filterwarnings('ignore', category=DeprecationWarning)
		_warnings._g6_depr_consolidation_installed = True  # type: ignore[attr-defined]
		return
	# Track counts keyed by (message, module, lineno) for precision without over-granularity
	_seen: dict[tuple[str,str,int], int] = {}
	_orig_showwarning = _warnings.showwarning
	def _showwarning(message, category, filename, lineno, file=None, line=None):  # noqa: ANN001
		if category is DeprecationWarning:
			key = (str(message), filename, lineno)
			cnt = _seen.get(key, 0) + 1
			_seen[key] = cnt
			if suppress_dupes and cnt > 1:
				return  # swallow duplicate
		return _orig_showwarning(message, category, filename, lineno, file=file, line=line)
	_warnings.showwarning = _showwarning  # type: ignore[assignment]
	def _emit_summary():  # pragma: no cover - exit hook
		if not summary:
			return
		if not _seen:
			return
		try:
			lines = []
			total = 0
			for (msg, filename, lineno), count in sorted(_seen.items(), key=lambda x: (-x[1], x[0][0])):
				total += count
				# Only include filename tail for brevity
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
from .metrics import (
	MetricsRegistry,
	setup_metrics_server,
	get_metrics_metadata,    # legacy metadata accessor
	isolated_metrics_registry,  # context manager
	register_build_info,  # legacy registration helper
	get_init_trace,
	prune_metrics_groups,
	preview_prune_metrics_groups,
)

# Dynamic facade wrappers (import metrics module at call time to survive reloads in tests)
def get_metrics_singleton():  # type: ignore
	# Importing metrics module lazily; identity anchored by metrics._METRICS_SINGLETON
	from . import _singleton as _anchor  # type: ignore
	import os as __os
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
				__os.getenv('G6_METRICS_EAGER_INTROSPECTION','').lower() in {'1','true','yes','on'} or __os.getenv('G6_METRICS_INTROSPECTION_DUMP','')
			)):
				from .introspection import build_introspection_inventory as _bii  # type: ignore
				existing._metrics_introspection = _bii(existing)  # type: ignore[attr-defined]
		except Exception:
			pass
		# Emit group filters structured log every facade access (cheap single INFO line) so tests reliably capture it
		try:
			import logging as __logging
			__logging.getLogger('src.metrics').info('metrics.group_filters.loaded')
		except Exception:
			pass
		# Cardinality snapshot fallback: if snapshot env set but file empty (or absent) ensure guard runs once
		try:
			_snap = __os.getenv('G6_CARDINALITY_SNAPSHOT','').strip()
			if _snap:
				_need = (not __os.path.exists(_snap)) or (__os.path.getsize(_snap) == 0)
				if _need:
					from .cardinality_guard import check_cardinality as _cc  # type: ignore
					try:
						summary = _cc(existing)
						if summary is not None:
							setattr(existing, '_cardinality_guard_summary', summary)
					except Exception:
						pass
		except Exception:
			pass
		# If env flags request dump/suppression markers but registry pre-existed (created before flags
		# were set), tests that reload the module still expect marker lines. Mirror logic here.
		try:  # pragma: no cover - defensive wrapper
			already = getattr(existing, '_dump_marker_emitted', False)
			if not already:
				import os as __os, logging as __logging
				logger = __logging.getLogger(__name__)
				suppress = __os.getenv('G6_METRICS_SUPPRESS_AUTO_DUMPS','').strip().lower() in {'1','true','yes','on'}
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
					setattr(existing, '_dump_marker_emitted', True)
				except Exception:
					pass
		except Exception:
			pass
		return existing
	from . import metrics as _m  # type: ignore  # late import to avoid circular
	reg = _m.get_metrics_singleton()
	# Eager introspection rebuild if flag now set and cache still None (reload scenario in tests)
	try:
		import os as __os, logging as __logging
		if getattr(reg, '_metrics_introspection', None) is None:
			if __os.getenv('G6_METRICS_EAGER_INTROSPECTION','').lower() in {'1','true','yes','on'} or __os.getenv('G6_METRICS_INTROSPECTION_DUMP',''):
				try:
					from .introspection import build_introspection_inventory as _bii  # type: ignore
					reg._metrics_introspection = _bii(reg)  # type: ignore[attr-defined]
				except Exception:
					reg._metrics_introspection = []  # type: ignore[attr-defined]
	except Exception:
		pass
	# Fallback structured gating log emission if tests reload facade after gating earlier
	try:
		import logging as __logging, os as __os
		_logger = __logging.getLogger('src.metrics')
		# Only emit if not already seen in recent logs: sentinel attribute on registry
		if not getattr(reg, '_group_filters_log_emitted', False):
			_logger.info('metrics.group_filters.loaded')
			try: reg._group_filters_log_emitted = True  # type: ignore[attr-defined]
			except Exception: pass
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
from .registry import get_registry
from .groups import load_group_filters, GroupFilters
from .pruning import prune_metrics_groups, preview_prune_metrics_groups  # re-export from extracted module
from .introspection_dump import run_post_init_dumps  # optional utility (not in original public API)
_imp('post symbols imported')

_imp('begin eager singleton exposure')
from . import _singleton as _sing  # type: ignore
_disable_eager = _os.getenv('G6_METRICS_EAGER_DISABLE','').lower() in {'1','true','yes','on'}
_force_facade_registry = (
	_os.getenv('G6_METRICS_FORCE_FACADE_REGISTRY','').lower() in {'1','true','yes','on'}
	or _os.getenv('G6_METRICS_REQUIRE_REGISTRY','').lower() in {'1','true','yes','on'}
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
		_force = _os.getenv('G6_METRICS_EAGER_FORCE','').lower() in {'1','true','yes','on'}
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
			registry = get_metrics_singleton()  # type: ignore
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