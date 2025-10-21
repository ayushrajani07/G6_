#!/usr/bin/env python
"""Generate a lightweight SBOM (CycloneDX style subset).

Usage:
  python scripts/gen_sbom.py --format json --output sbom.json

If the cyclonedx-python-lib is installed, we will attempt to use it for a richer
spec; otherwise we fall back to a minimal JSON including name, version, licenses (best-effort),
sha256 (wheel/source hash not computed here), and dependency list from requirements.txt.

Environment:
  G6_SBOM_INCLUDE_HASH=1 to attempt hashing installed package distributions (best-effort, may be slow)
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.util
import json
import os
import sys
from typing import Any


def _read_requirements(path: str) -> list[str]:
    out: list[str] = []
    try:
        with open(path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                # Split off inline comments
                if ' #' in line:
                    line = line.split(' #',1)[0].strip()
                out.append(line)
    except Exception:
        pass
    return out


def _hash_dist(dist: object) -> str | None:
    if not dist:
        return None
    try:
        loc = getattr(dist, 'location', None)
        if not loc or not os.path.isdir(loc):
            return None
        h = hashlib.sha256()
        # Hash a limited number of files for speed
        count = 0
        for root, _dirs, files in os.walk(loc):
            for fn in files:
                if not fn.endswith(('.py', '.dist-info')):
                    continue
                fp = os.path.join(root, fn)
                try:
                    with open(fp, 'rb') as fh:
                        h.update(fh.read(4096))
                except Exception:
                    continue
                count += 1
                if count >= 50:  # cap for performance
                    break
            if count >= 50:
                break
        return h.hexdigest()
    except Exception:
        return None


def build_minimal_sbom(requirements: list[str], include_hash: bool) -> dict[str, Any]:
    components: list[dict[str, Any]] = []
    seen = set()
    for req in requirements:
        pkg = req.split('==')[0].split('>=')[0].split('<=')[0].strip()
        if not pkg or pkg in seen:
            continue
        seen.add(pkg)
        version = None
        try:
            spec = importlib.util.find_spec(pkg)
            if spec is not None and spec.loader is not None:
                mod = importlib.import_module(pkg)
                ver = getattr(mod, '__version__', None)
                if isinstance(ver, str):
                    version = ver
        except Exception:
            pass
        comp: dict[str, Any] = {
            'name': pkg,
            'version': version,
            'purl': f'pkg:pypi/{pkg}@{version}' if version else f'pkg:pypi/{pkg}'
        }
        if include_hash:
            try:
                import importlib.metadata as md  # Python 3.8+
                dist = None
                for d in md.distributions():
                    if d.metadata['Name'].lower() == pkg.lower():
                        dist = d
                        break
                if dist:
                    comp['hash_sha256_partial'] = _hash_dist(dist)
            except Exception:
                pass
        components.append(comp)
    return {
        'bomFormat': 'CycloneDX',
        'specVersion': '1.4',
        'serialNumber': 'urn:uuid:local-generated',
        'metadata': {
            # Use timezone-aware UTC now to satisfy style/lint tests (avoid deprecated naive UTC variant)
            'timestamp': (__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()),
            'tools': [{'vendor': 'G6', 'name': 'g6-sbom-gen', 'version': '0.1'}],
        },
        'components': components,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument('--requirements', default='requirements.txt')
    p.add_argument('--output', '-o', default='sbom.json')
    p.add_argument('--format', choices=['json'], default='json')
    args = p.parse_args(argv)

    reqs = _read_requirements(args.requirements)
    include_hash = os.environ.get('G6_SBOM_INCLUDE_HASH','').lower() in ('1','true','yes','on')

    # Prefer cyclonedx lib if present
    try:
        from cyclonedx.model.bom import Bom  # type: ignore
        from cyclonedx.model.component import Component, ComponentType  # type: ignore
        from cyclonedx.output import get_instance as cd_get_instance  # type: ignore
        bom = Bom()
        for r in reqs:
            pkg = r.split('==')[0].split('>=')[0].split('<=')[0].strip()
            if not pkg:
                continue
            comp = Component(name=pkg, version=None, type=ComponentType.LIBRARY)
            bom.components.add(comp)
        cd_output = cd_get_instance(bom, output_format='json')  # type: ignore
        data = json.loads(cd_output.output_as_string())
    except Exception:
        data = build_minimal_sbom(reqs, include_hash)

    try:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        print(f"SBOM written to {args.output} (components={len(data.get('components', []))})")
        return 0
    except Exception as e:
        print(f"Failed to write SBOM: {e}", file=sys.stderr)
        return 2

if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
