#!/usr/bin/env python
"""
Direct raw probe of kiteconnect instruments API.

Goals:
 1. Verify that credentials (API key + access token) are present and usable.
 2. Detect kiteconnect library version and Python runtime (possible 3.13 compat issue).
 3. Fetch full instruments list (kc.instruments()).
 4. Fetch NFO-only list (kc.instruments('NFO')).
 5. If full list non‑empty but NFO empty, derive an NFO subset manually and report.
 6. Emit a concise JSON summary at the end for automated parsing.

Environment variables used (any of these aliases accepted):
  KITE_API_KEY / KITE_APIKEY
  KITE_ACCESS_TOKEN / KITE_ACCESSTOKEN

Optional CLI overrides:
  --api-key YOUR_KEY --access-token YOUR_TOKEN

Exit codes:
  0 = success (even if lists empty; emptiness reported in summary)
  2 = missing credentials
  3 = import failure
  4 = API construction or token set failure

Usage examples:
  python scripts/raw_kite_probe.py
  python scripts/raw_kite_probe.py --api-key XYZ --access-token ABC
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from typing import Any


# Lightweight .env loader (avoids new dependency). Only parses KEY=VALUE lines.
def _load_dotenv_if_present(dotenv_path: str = '.env') -> None:
    if not os.path.exists(dotenv_path):
        return
    try:
        with open(dotenv_path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' not in line:
                    continue
                k, v = line.split('=', 1)
                k = k.strip()
                # Strip optional surrounding quotes in value
                v = v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
    except Exception:
        # Silent: probe will show missing vars anyway
        pass


def _read_env_multi(*names: str) -> str | None:
    for n in names:
        v = os.environ.get(n)
        if v:
            return v
    return None


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument('--api-key', dest='api_key')
    p.add_argument('--access-token', dest='access_token')
    p.add_argument('--timeout', type=float, default=10.0, help='(Unused placeholder if future direct HTTP probe added)')
    return p.parse_args()


def safe_len(obj: Any) -> int | None:
    try:
        return len(obj)  # type: ignore[arg-type]
    except Exception:
        return None


def summarize_first_entry(label: str, data: Any) -> dict[str, Any]:
    if not isinstance(data, list) or not data:
        return {f'{label.lower()}_first': None}
    first = data[0]
    if isinstance(first, dict):
        return {f'{label.lower()}_first_keys': sorted(list(first.keys()))[:16]}
    return {f'{label.lower()}_first_type': type(first).__name__}


def main() -> int:
    ns = parse_args()

    # First pass: read environment
    api_key = ns.api_key or _read_env_multi('KITE_API_KEY', 'KITE_APIKEY')
    access_token = ns.access_token or _read_env_multi('KITE_ACCESS_TOKEN', 'KITE_ACCESSTOKEN')

    # If missing, try to source from .env then re-evaluate
    if (not api_key or not access_token):
        _load_dotenv_if_present('.env')
        if not api_key:
            api_key = _read_env_multi('KITE_API_KEY', 'KITE_APIKEY')
        if not access_token:
            access_token = _read_env_multi('KITE_ACCESS_TOKEN', 'KITE_ACCESSTOKEN')

    result: dict[str, Any] = {
        'python_version': sys.version,
        'api_key_present': bool(api_key),
        'access_token_present': bool(access_token),
        'kiteconnect_import_ok': False,
        'kiteconnect_version': None,
        'construct_ok': False,
        'set_token_ok': False,
        'full_instruments_len': None,
        'nfo_instruments_len': None,
        'derived_nfo_len': None,
        'derived_nfo_method': None,
        'warnings': [],
        'errors': [],
    }

    if not api_key or not access_token:
        result['errors'].append('MISSING_CREDENTIALS')
        print(json.dumps(result, indent=2))
        return 2

    try:
        import kiteconnect  # type: ignore
        from kiteconnect import KiteConnect  # type: ignore
        result['kiteconnect_import_ok'] = True
        result['kiteconnect_version'] = getattr(kiteconnect, '__version__', None)
    except Exception as e:  # pragma: no cover - diagnostic path
        result['errors'].append(f'IMPORT_FAIL:{e.__class__.__name__}')
        result['import_traceback'] = traceback.format_exc(limit=4)
        print(json.dumps(result, indent=2))
        return 3

    # Construct client
    try:
        kc = KiteConnect(api_key=api_key)
        result['construct_ok'] = True
    except Exception as e:  # pragma: no cover
        result['errors'].append(f'CLIENT_CONSTRUCT_FAIL:{e.__class__.__name__}')
        result['construct_traceback'] = traceback.format_exc(limit=6)
        print(json.dumps(result, indent=2))
        return 4

    # Set access token
    try:
        kc.set_access_token(access_token)
        result['set_token_ok'] = True
    except Exception as e:  # pragma: no cover
        result['errors'].append(f'SET_TOKEN_FAIL:{e.__class__.__name__}')
        result['set_token_traceback'] = traceback.format_exc(limit=6)
        print(json.dumps(result, indent=2))
        return 4

    def attempt(label: str, *args) -> Any:
        try:
            data = kc.instruments(*args)
            ln = safe_len(data)
            result[f'{label.lower()}_instruments_len'] = ln
            result.update(summarize_first_entry(label, data))
            return data
        except Exception as e:  # pragma: no cover
            result['errors'].append(f'{label}_CALL_FAIL:{e.__class__.__name__}')
            result[f'{label.lower()}_traceback'] = traceback.format_exc(limit=6)
            return None

    full = attempt('full')  # kc.instruments()
    nfo = attempt('nfo', 'NFO')  # kc.instruments('NFO')

    # Fallback derivation if needed
    if isinstance(full, list) and full and (not isinstance(nfo, list) or not nfo):
        # Heuristic filters: segment contains 'NFO' OR exchange == 'NFO'
        derived: list[Any] = []
        for inst in full:
            if not isinstance(inst, dict):
                continue
            seg = str(inst.get('segment', ''))
            exch = str(inst.get('exchange', ''))
            if 'NFO' in seg.upper() or exch.upper() == 'NFO':
                derived.append(inst)
        result['derived_nfo_len'] = len(derived)
        result['derived_nfo_method'] = 'segment|exchange filter from full list'
        if len(derived) == 0:
            result['warnings'].append('Derived NFO subset empty although full list non-empty')
        else:
            # Add first derived keys for visibility
            result.update(summarize_first_entry('derived_nfo', derived))
            if result.get('nfo_instruments_len') in (0, None):
                result['warnings'].append('NFO direct call empty but derived subset non-empty')

    # High-level classification
    classification: str
    if not isinstance(full, list) or not full:
        classification = 'NO_FULL_LIST'  # root problem
    elif isinstance(full, list) and full and (result.get('nfo_instruments_len') in (0, None)):
        if result.get('derived_nfo_len'):
            classification = 'NFO_SEGMENT_EMPTY_DERIVED_AVAILABLE'
        else:
            classification = 'NFO_SEGMENT_EMPTY_NO_DERIVED'
    else:
        classification = 'OK'
    result['classification'] = classification

    # Terminal hints
    hints: list[str] = []
    if classification == 'NO_FULL_LIST':
        hints.append('Check access token validity / entitlements; consider regenerating token.')
        hints.append('Verify kiteconnect compatibility with this Python version (3.13 may not yet be fully supported).')
    if classification.startswith('NFO_SEGMENT_EMPTY'):
        hints.append('Provider layer can fallback to manual filter on full list; implement if not already.')
    if 'IMPORT_FAIL' in ''.join(result['errors']):
        hints.append('Reinstall kiteconnect: pip install --upgrade --force-reinstall kiteconnect')
    result['hints'] = hints

    # Final sanitation: ensure all values JSON serializable (avoid module objects)
    def _sanitize(o: Any):
        if isinstance(o, (str, int, float, bool)) or o is None:
            return o
        if isinstance(o, (list, tuple)):
            return [_sanitize(i) for i in o]
        if isinstance(o, dict):
            return {str(k): _sanitize(v) for k, v in o.items()}
        # fallback to repr string
        return repr(o)

    print(json.dumps(_sanitize(result), indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':  # pragma: no cover
    sys.exit(main())
