"""Validate runbook (or generic external) links embedded in Grafana dashboard JSON files.

Usage (basic):
  python scripts/validate_runbook_links.py --dash-dir grafana/dashboards --base-domain https://runbooks.example.com

The script crawls dashboard JSON files, extracts:
 - Panel.links[].url
 - Markdown content links in text panels (rudimentary markdown link regex)
Then filters links containing the provided --base-domain (unless --all-links passed) and performs HTTP HEAD (fallback GET) to verify 2xx/3xx status.

Exit code is non-zero if any failing links are found (suitable for CI gating).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterable

LINK_RE = re.compile(r"\[[^\]]+\]\((https?://[^)]+)\)")

# Some dashboards may have self-signed endpoints in test; allow disabling cert verification.
CTX = ssl.create_default_context()

def extract_links(dashboard_json: dict) -> Iterable[tuple[str,str]]:
    panels = dashboard_json.get('panels') or []
    for p in panels:
        pid = str(p.get('id','?'))
        # direct panel links array
        for link in p.get('links', []) or []:
            url = link.get('url') or ''
            if url:
                yield (f"panel:{pid}", url)
        # markdown text panel
        if p.get('type') == 'text':
            opts = p.get('options') or {}
            content = opts.get('content') or ''
            for m in LINK_RE.finditer(content):
                yield (f"panel:{pid}:md", m.group(1))

    # also check top-level links if used (rare)
    for l in dashboard_json.get('links', []) or []:
        url = l.get('url') or ''
        if url:
            yield ("top", url)

def check_url(url: str, timeout: float = 5.0) -> tuple[bool,int|None,str|None]:
    req = urllib.request.Request(url, method='HEAD')
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as resp:
            return True, resp.status, None
    except urllib.error.HTTPError as e:
        # some servers disallow HEAD; try GET quickly
        if e.code in (405, 400):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, method='GET'), timeout=timeout, context=CTX) as resp2:
                    return True, resp2.status, None
            except Exception as e2:  # noqa: BLE001
                return False, getattr(e2, 'status', None), str(e2)
        return False, e.code, str(e)
    except Exception as e:  # noqa: BLE001
        return False, None, str(e)

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--dash-dir', default='grafana/dashboards', help='Directory containing dashboard JSON files')
    ap.add_argument('--base-domain', default='', help='Filter only links containing this substring (domain)')
    ap.add_argument('--all-links', action='store_true', help='Validate all extracted links regardless of domain filter')
    ap.add_argument('--fail-fast', action='store_true', help='Exit on first failure')
    ap.add_argument('--insecure', action='store_true', help='Skip TLS verification (NOT for production)')
    args = ap.parse_args()

    if args.insecure:
        global CTX  # noqa: PLW0603
        CTX = ssl._create_unverified_context()  # type: ignore[attr-defined]

    dash_path = pathlib.Path(args.dash_dir)
    if not dash_path.is_dir():
        print(f"Dashboard directory not found: {dash_path}", file=sys.stderr)
    return 2

    failures: list[str] = []
    checked = 0
    start = time.time()
    for file in sorted(dash_path.glob('*.json')):
        try:
            data = json.loads(file.read_text(encoding='utf-8'))
        except Exception as e:  # noqa: BLE001
            failures.append(f"{file.name}: JSON parse error: {e}")
            if args.fail_fast:
                break
            continue
        for origin, url in extract_links(data):
            if not args.all_links and args.base_domain and args.base_domain not in url:
                continue
            ok, status, err = check_url(url)
            checked += 1
            if not ok:
                failures.append(f"{file.name}:{origin} -> {url} FAILED status={status} err={err}")
                if args.fail_fast:
                    break
        if failures and args.fail_fast:
            break

    duration = time.time() - start
    if failures:
        print(f"Runbook link validation FAILED ({len(failures)} failures) in {duration:.2f}s")
        for f in failures:
            print(f" - {f}")
    return 1
    print(f"Runbook link validation OK ({checked} links checked) in {duration:.2f}s")
    return 0

if __name__ == '__main__':  # pragma: no cover
    sys.exit(main())
