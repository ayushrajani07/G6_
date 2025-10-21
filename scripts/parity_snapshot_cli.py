#!/usr/bin/env python3
"""Parity Snapshot CLI (Wave 4 – W4-14)

Generates a JSON snapshot summarizing parity score and alert/category diffs.

Usage (examples):
  python scripts/parity_snapshot_cli.py --legacy legacy.json --pipeline pipeline.json --pretty
  python scripts/parity_snapshot_cli.py --pipeline pipeline.json --rolling-window 10 --extended
  python scripts/parity_snapshot_cli.py --pipeline pipeline.json --weights index_count:0.4,option_count:0.2,alerts:0.4

Exit codes:
 0 success
 1 invalid arguments / IO error / compute failure

Schema (baseline):
{
  "generated_at": ISO8601 str,
  "parity": { compute_parity_score(..) fields },
  "rolling": { "window": int, "avg": float|None, "count": int },
  "alerts": {
     "categories": { name: {"legacy":int,"pipeline":int,"delta":int} },
     "sym_diff": [ list of alert tokens if simple list form ],
     "union_count": int,
     "sym_diff_count": int
  }
}
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from src.collectors.pipeline.parity import compute_parity_score, record_parity_score

# ---------------- Helpers -----------------

def _load_json(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Input file not found: {path}")
    with p.open('r', encoding='utf-8') as f:
        obj: Any = json.load(f)
        return cast(dict[str, Any], obj)


def _parse_weights(raw: str | None) -> dict[str,float] | None:
    if not raw:
        return None
    out: dict[str,float] = {}
    for part in raw.split(','):
        part = part.strip()
        if not part:
            continue
        if ':' not in part:
            raise ValueError(f"Invalid weight fragment (expected comp:weight): {part}")
        k, v = part.split(':',1)
        try:
            out[k.strip()] = float(v)
        except Exception:
            raise ValueError(f"Invalid weight value for component {k}: {v}")
    return out


def _extract_alert_categories(root: dict[str, Any] | None) -> dict[str,int]:
    if not root or not isinstance(root, dict):
        return {}
    alerts_block = root.get('alerts')
    if isinstance(alerts_block, dict):
        cats = alerts_block.get('categories')
        if isinstance(cats, dict):
            out: dict[str,int] = {}
            for k,v in cats.items():
                try:
                    out[str(k)] = int(v)
                except Exception:
                    continue
            return out
    # fallback: treat alerts as list of tokens
    seq = alerts_block if isinstance(alerts_block, (list, tuple, set)) else []
    tokens = set()
    for item in seq:
        if isinstance(item, str):
            tokens.add(item)
        elif isinstance(item, dict):
            for key in ('alert','name','type'):
                val = item.get(key) if isinstance(item, dict) else None
                if isinstance(val, str):
                    tokens.add(val)
                    break
    return {t:1 for t in tokens}


def _simple_alert_token_set(root: dict[str,Any] | None) -> set[str]:
    if not root or not isinstance(root, dict):
        return set()
    alerts_block = root.get('alerts')
    out = set()
    if isinstance(alerts_block, (list, tuple, set)):
        for item in alerts_block:
            if isinstance(item, str):
                out.add(item)
            elif isinstance(item, dict):
                for k in ('alert','name','type'):
                    v = item.get(k)
                    if isinstance(v, str):
                        out.add(v)
                        break
    return out


def build_snapshot(legacy: dict[str,Any] | None, pipeline: dict[str,Any] | None, *, weights: dict[str,float] | None, rolling_window: int) -> dict[str,Any]:
    parity_obj = compute_parity_score(legacy, pipeline, weights=weights)

    # Rolling score simulation (does not persist across runs; single insertion)
    rolling_info: dict[str, Any] = {"window": rolling_window, "avg": None, "count": 0}
    score_val = parity_obj.get('score')
    if rolling_window > 1 and isinstance(score_val, (int, float)):
        # Set env for this call only
        os.environ['G6_PARITY_ROLLING_WINDOW'] = str(rolling_window)
        rec = record_parity_score(float(score_val))
        # Normalize to expected keys and basic types
        rolling_info = {
            "window": int(rec.get("window", rolling_window)),
            "avg": rec.get("avg"),
            "count": int(rec.get("count", 0)),
        }

    # Alert categories & diff
    cats_a = _extract_alert_categories(legacy)
    cats_b = _extract_alert_categories(pipeline)
    cat_names = sorted(set(cats_a) | set(cats_b))
    categories: dict[str, dict[str,int]] = {}
    for name in cat_names:
        a = cats_a.get(name,0)
        b = cats_b.get(name,0)
        categories[name] = {"legacy": a, "pipeline": b, "delta": b - a}

    # Symmetric diff for simple token list forms (informational)
    tokens_a = _simple_alert_token_set(legacy)
    tokens_b = _simple_alert_token_set(pipeline)
    sym = sorted(tokens_a ^ tokens_b)
    union_count = len(tokens_a | tokens_b)

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "parity": parity_obj,
        "rolling": rolling_info,
        "alerts": {
            "categories": categories,
            "sym_diff": sym,
            "sym_diff_count": len(sym),
            "union_count": union_count,
        },
    }

# ---------------- CLI -----------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate parity snapshot JSON")
    p.add_argument('--legacy', help='Legacy baseline JSON file')
    p.add_argument('--pipeline', help='Pipeline JSON file')
    p.add_argument('--output', help='Output file (writes JSON instead of stdout)')
    p.add_argument('--weights', help='Component weights override (comp:weight,...)')
    p.add_argument('--extended', action='store_true', help='Enable extended strike coverage component')
    p.add_argument('--shape', action='store_true', help='Enable strike shape distribution component')
    p.add_argument('--cov-var', action='store_true', help='Enable strike coverage variance component')
    p.add_argument('--rolling-window', type=int, default=0, help='Simulate rolling parity window size (>=2 to compute avg)')
    p.add_argument('--pretty', action='store_true', help='Pretty-print JSON output')
    p.add_argument('--version-only', action='store_true', help='Emit only version & score fields')
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        weights = _parse_weights(args.weights)
        if args.extended:
            os.environ['G6_PARITY_EXTENDED'] = '1'
        if args.shape:
            os.environ['G6_PARITY_STRIKE_SHAPE'] = '1'
        if args.cov_var:
            os.environ['G6_PARITY_STRIKE_COV_VAR'] = '1'
        legacy = _load_json(args.legacy)
        pipeline = _load_json(args.pipeline)
        snap = build_snapshot(legacy, pipeline, weights=weights, rolling_window=args.rolling_window)
        if args.version_only:
            out_obj = {
                'generated_at': snap['generated_at'],
                'version': snap['parity'].get('version'),
                'score': snap['parity'].get('score'),
            }
        else:
            out_obj = snap
        text = json.dumps(out_obj, indent=2 if args.pretty else None, sort_keys=args.pretty)
        if args.output:
            Path(args.output).write_text(text + ('\n' if not text.endswith('\n') else ''), encoding='utf-8')
        else:
            print(text)
        return 0
    except Exception as e:
        print(f"ERROR: {e}", flush=True)
        return 1

if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
