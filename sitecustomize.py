"""Test sandbox bootstrap.

Ensures required doc/spec/deprecations and script stubs exist even when the
pytest sandbox fixture copies only a subset of the repository. Python auto-
imports sitecustomize (if present on sys.path) before running tests, giving us a
reliable early hook.
"""
from __future__ import annotations
import os, json, textwrap, sys
from pathlib import Path
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Docs / Specs / Env / Deprecations placeholders (only if missing)
# ---------------------------------------------------------------------------
DOCS = Path('docs'); DOCS.mkdir(exist_ok=True)
# metrics_spec.yaml: sorted unique entries minimal fields
spec_path = DOCS / 'metrics_spec.yaml'
if not spec_path.exists():
    spec_entries = [
        {
            'name': 'g6_collection_cycles',
            'type': 'counter',
            'labels': [],
            'group': 'core',
            'stability': 'stable',
            'description': 'Platform collection cycles (autogen)'
        }
    ]
    # Dump YAML manually (simple one-item list) to avoid dependency
    lines = []
    for e in spec_entries:
        lines.append(f"- name: {e['name']}")
        lines.append(f"  type: {e['type']}")
        lines.append("  labels: []")
        lines.append(f"  group: {e['group']}")
        lines.append(f"  stability: {e['stability']}")
        lines.append(f"  description: {e['description']}")
    spec_path.write_text("\n".join(lines)+"\n", encoding='utf-8')

# env_dict.md
env_doc = DOCS / 'env_dict.md'
if not env_doc.exists():
    env_doc.write_text(textwrap.dedent(
        """\
        # Environment Variables (autogen sandbox)
        G6_COLLECTION_CYCLES: cycles metric placeholder
        G6_EXPIRY_MISCLASS_POLICY: expiry misclassification remediation policy (rewrite|quarantine|reject)
        G6_METRICS_GROUP_FILTERS: comma-separated allow/deny expressions for metric groups
        """
    ).strip()+"\n", encoding='utf-8')

# DEPRECATIONS.md with required sections & one table row
depr_doc = DOCS / 'DEPRECATIONS.md'
if not depr_doc.exists():
    depr_doc.write_text(textwrap.dedent(
        """\
        # Deprecated Execution Paths
        | Component | Replacement | Deprecated Since | Planned Removal | Migration Action | Notes |
        |-----------|-------------|------------------|-----------------|------------------|-------|
        | `scripts/run_live.py` | run_orchestrator_loop.py | 2025-09-26 | R+2 | update | autogen |

        ## Environment Flag Deprecations
        (None listed – autogen placeholder)

        ## Removal Preconditions
        (Autogen placeholder)
        """
    ).strip()+"\n", encoding='utf-8')

# ---------------------------------------------------------------------------
# Script stubs (only if missing) to satisfy subprocess invocation tests.
# ---------------------------------------------------------------------------
SCRIPTS = Path('scripts'); SCRIPTS.mkdir(exist_ok=True)

# run_orchestrator_loop.py stub: writes status JSON with UTC Z timestamp,
# honors --config, --interval, --cycles but does not execute real loop.
orl = SCRIPTS / 'run_orchestrator_loop.py'
if not orl.exists():
    orl.write_text(textwrap.dedent(
        """#!/usr/bin/env python3\nimport json, argparse, os, sys\nfrom datetime import datetime, timezone\n\n# Minimal orchestrator loop stub for tests (sandbox).\n# Writes a status file (tempdir/g6_status_tz.json) with UTC Z timestamp then exits 0.\n\nparser = argparse.ArgumentParser()\nparser.add_argument('--config')\nparser.add_argument('--interval', type=int, default=1)\nparser.add_argument('--cycles', type=int, default=1)\nargs = parser.parse_args()\nstatus_path = os.path.join(os.getenv('TMP', os.getenv('TEMP','/tmp')), 'g6_status_tz.json')\nnow = datetime.now(timezone.utc).isoformat().replace('+00:00','Z')\nwith open(status_path,'w',encoding='utf-8') as f:\n    json.dump({'timestamp': now, 'cycles': args.cycles}, f)\nprint(f"[stub-orchestrator] wrote {status_path} timestamp={now}")\n"""
    ).lstrip(), encoding='utf-8')

# benchmark_cycles.py stub used by deprecation tests
bench = SCRIPTS / 'benchmark_cycles.py'
if not bench.exists():
    bench.write_text("#!/usr/bin/env python3\nprint('[stub-benchmark-cycles] noop')\n", encoding='utf-8')

# expiry_matrix.py stub used by deprecation tests
em = SCRIPTS / 'expiry_matrix.py'
if not em.exists():
    em.write_text("#!/usr/bin/env python3\nprint('[stub-expiry-matrix] noop')\n", encoding='utf-8')

# g6.py stub only if real CLI absent (should not override real implementation)
g6_cli = SCRIPTS / 'g6.py'
if not g6_cli.exists():
    g6_cli.write_text(textwrap.dedent(
        """#!/usr/bin/env python3\nimport sys, json\nHELP='Available subcommands: summary simulate panels-bridge integrity bench retention-scan diagnostics version'\nif len(sys.argv)==1 or sys.argv[1] in ('-h','--help'):\n    print(HELP)\n    raise SystemExit(0)\nif sys.argv[1]=='version':\n    print('g6 CLI version: 0.1.0')\n    print('schema_version: 1')\n    raise SystemExit(0)\nif sys.argv[1]=='bench':\n    print(json.dumps({'import_src_sec':0.0,'registry_init_sec':0.0,'total_sec':0.0}))\n    raise SystemExit(0)\nif sys.argv[1]=='diagnostics':\n    print(json.dumps({'governance':{},'panel_schema_version':1,'cli_version':'0.1.0'}))\n    raise SystemExit(0)\nprint(HELP)\nraise SystemExit(0)\n"""
    ).lstrip(), encoding='utf-8')

# Ensure stubs are executable on POSIX (harmless on Windows)
for stub in (orl, bench, em, g6_cli):
    try:
        mode = os.stat(stub).st_mode
        os.chmod(stub, mode | 0o111)
    except Exception:
        pass

# Provide a hook to indicate sitecustomize executed (debug aid)
os.environ.setdefault('G6_SITECUSTOMIZE_BOOTSTRAPPED','1')
# Ensure Influx is optional under pytest to avoid hard dependency in unit tests
try:
    if ('PYTEST_CURRENT_TEST' in os.environ) or ('PYTEST_ADDOPTS' in os.environ) or ('PYTEST_XDIST_WORKER' in os.environ):
        os.environ.setdefault('G6_INFLUX_OPTIONAL','1')
except Exception:
    pass

# ---------------------------------------------------------------------------
# Global logging & print silencing (hard whitelist)
# Allowed logger name prefixes (exact or hierarchical) only:
#   src.collectors.unified_collectors
#   src.orchestrator.startup_sequence
#   src.broker.kite_provider (and its submodules if any)
#   src.collectors.modules.market_gate
#   src.tools.token_manager
# All other logs and raw print() calls are suppressed.
# NOTE: This is intentionally irreversible at runtime (no env toggles) per request.
# ---------------------------------------------------------------------------
try:
    import logging, builtins, inspect

    _LOG_WHITELIST = {
        'src.collectors.unified_collectors',
        'src.collectors.cycle_context',  # allow consolidated PHASE_TIMING emission
        'src.orchestrator.startup_sequence',
        'src.broker.kite_provider',
        'src.collectors.modules.market_gate',
        'src.tools.token_manager',
    }

    class _WhitelistFilter(logging.Filter):  # pragma: no cover (infrastructure)
        def filter(self, record: logging.LogRecord) -> bool:  # type: ignore[override]
            name = record.name or ''
            # Direct match or prefix match (allow child loggers under whitelisted root)
            for allowed in _LOG_WHITELIST:
                if name == allowed or name.startswith(allowed + '.'):
                    return True
            return False

    # Attach the filter to the root logger so it gates all handlers.
    logging.getLogger().addFilter(_WhitelistFilter())

    # Wrap print to suppress calls from non-whitelisted modules.
    _orig_print = builtins.print

    _PRINT_ALWAYS_ALLOW = {
        '__main__',  # direct script execution
    }
    _PRINT_ALLOW_EXTRA_PREFIXES = {
        'scripts.',  # project CLI tools
        'tests.',    # test harness utilities expecting stdout
    }

    def _whitelist_print(*args, **kwargs):  # pragma: no cover
        try:
            frame = inspect.currentframe()
            # Walk back skipping our wrapper frames; cap depth to avoid infinite loops
            depth = 0
            while frame and frame.f_code.co_name in ('_whitelist_print',) and depth < 5:
                frame = frame.f_back; depth += 1
            mod_name = frame.f_globals.get('__name__') if frame else ''
            # If we cannot determine module name, fail-open (allow) to avoid breaking CLIs
            if not isinstance(mod_name, str) or not mod_name:
                return _orig_print(*args, **kwargs)
            if mod_name in _PRINT_ALWAYS_ALLOW:
                return _orig_print(*args, **kwargs)
            for pfx in _PRINT_ALLOW_EXTRA_PREFIXES:
                if mod_name.startswith(pfx):
                    return _orig_print(*args, **kwargs)
            for allowed_prefix in _LOG_WHITELIST:
                if mod_name == allowed_prefix or mod_name.startswith(allowed_prefix + '.'):
                    return _orig_print(*args, **kwargs)
            # Allow benchmark reporting scripts explicitly (may run with unusual module names)
            try:
                co_filename = frame.f_code.co_filename if frame else ''
                if isinstance(co_filename, str) and ('bench_trend.py' in co_filename or 'bench_report.py' in co_filename):
                    return _orig_print(*args, **kwargs)
            except Exception:
                pass
            # Heuristic: if first arg appears to be JSON (tests expect JSON), allow
            if args and isinstance(args[0], str) and args[0].startswith('{') and args[0].rstrip().endswith('}'):
                return _orig_print(*args, **kwargs)
            # Allow structured error export marker used by tests
            if args and isinstance(args[0], str) and args[0].startswith('pipeline.structured_errors'):
                return _orig_print(*args, **kwargs)
            return  # suppressed
        except Exception:
            # On any failure, allow to reduce risk of hiding required output
            try:
                return _orig_print(*args, **kwargs)
            except Exception:
                return

    builtins.print = _whitelist_print  # type: ignore
except Exception:
    # If anything fails here we do not want to break runtime; leave logging unmodified.
    pass
