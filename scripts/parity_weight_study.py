#!/usr/bin/env python3
"""Parity Weight Study Artifact Generator (Wave 4 – W4-18)

Purpose:
  Collect empirical distributions for parity score component raw deltas across a set of
  legacy/pipeline snapshot pairs (or synthetic perturbations) and emit a JSON artifact
  summarizing stability, spread, and recommended weight adjustments.

Why:
  Default parity component weights are equal. Empirical variability & discrimination power
  differ: some components are near-saturated (always ~1.0) while others vary and better
  separate regression risk. We want weight recommendations that roughly normalize each
  component's information contribution (variance-aware) while keeping score intuitive.

Input Modes:
  1. Explicit pairs: --pairs legacyX.json:pipelineX.json (repeatable) – read real snapshots.
  2. Directory scan: --dir DIR (expects *legacy*.json / *pipeline*.json matched numerically)
  3. Synthetic: --synthetic N (generates N baseline variants applying controlled noise)

Output:
  JSON object written to stdout or --out file with schema (version=1):
  {
    "generated_at": iso8601,
    "source": {"mode": "pairs|dir|synthetic", "count": int},
    "components": {
        <name>: {
           "count": int,
           "mean": float,
           "std": float,
           "min": float,
           "max": float,
           "p50": float,
           "p90": float,
           "p95": float,
           "mean_miss": float,   # average missing incidence (0..1)
           "signal_strength": float,  # (1 - mean) for similarity components, or std for diff-like metrics
           "weight_recommendation": float
        }, ...
    },
    "weight_plan": {
        "raw": {comp: rec_weight},
        "normalized": {comp: w_norm},
        "method": "inverse_variance|variance|signal_scaled",
        "notes": "..."
    },
    "parameters": { "synthetic_noise": {...} }
  }

Method (default):
  For components expressed as similarity (current parity components, higher is better):
    - Treat variability (std) as proxy for information – components with more useful spread
      (not always 1.0) but not excessively noisy get more weight.
    - Compute preliminary weight = std / sum(std) with floor to avoid zero for stable but important components.
  Provide alternative method --method inverse-var to invert variance (classic meta-analytic weighting).

Usage Examples:
  python scripts/parity_weight_study.py --pairs l1.json:p1.json --pairs l2.json:p2.json --out study.json
  python scripts/parity_weight_study.py --synthetic 200 --noise 0.02 --out synthetic_study.json
  python scripts/parity_weight_study.py --dir data/parity_runs --method inverse-var --pretty

Limitations:
  - Assumes compute_parity_score structure stable.
  - Missing component rates incorporated but components missing >50% are down-weighted.

"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Local import (runtime path assumes repo root execution) – fallback safe if not present.
try:
    from src.collectors.pipeline.parity import compute_parity_score
except Exception:  # pragma: no cover
    compute_parity_score = None  # type: ignore

@dataclass
class Sample:
    components: dict[str, float]
    missing: list[str]

# ---------------- I/O helpers -----------------

def _load_json(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))

# ---------------- Synthetic generator -----------------

def _synthetic_pairs(n: int, *, base_components: list[str], noise: float, missing_prob: float) -> list[Sample]:
    """Generate synthetic component similarity values around 0.9..1.0 with noise.

    noise: amplitude of uniform perturbation (value = 1 - U(0, noise)).
    missing_prob: probability a component is marked missing (simulates absent data).
    """
    out: list[Sample] = []
    for _ in range(n):
        comps: dict[str, float] = {}
        missing: list[str] = []
        for name in base_components:
            if random.random() < missing_prob:
                missing.append(name)
                continue
            val = 1.0 - random.random() * noise  # similarity descending slightly
            # clamp just in case
            if val < 0: val = 0
            comps[name] = round(val, 6)
        out.append(Sample(comps, missing))
    return out

# ---------------- Study core -----------------

def _collect_samples(paths: list[tuple[str, str]]) -> list[Sample]:
    samples: list[Sample] = []
    if compute_parity_score is None:
        raise RuntimeError("compute_parity_score import failed; cannot run study")
    for legacy_path, pipeline_path in paths:
        try:
            legacy = _load_json(legacy_path)
            pipe = _load_json(pipeline_path)
            res = compute_parity_score(legacy, pipe)
            samples.append(Sample(res.get("components", {}), res.get("missing", [])))
        except Exception as e:  # pragma: no cover - continue best-effort
            print(f"WARN: failed pair {legacy_path}:{pipeline_path} -> {e}", file=sys.stderr)
    return samples

# ---------------- Statistics -----------------

def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    k = pct * (len(sorted_values) - 1)
    f = math.floor(k); c = math.ceil(k)
    if f == c:
        return sorted_values[int(k)]
    d0 = sorted_values[f] * (c - k)
    d1 = sorted_values[c] * (k - f)
    return d0 + d1



def _summarize(samples: list[Sample], method: str) -> tuple[dict[str, Any], dict[str, float], dict[str, float]]:
    # Gather per-component lists
    value_map: dict[str, list[float]] = {}
    missing_counts: dict[str, int] = {}
    for s in samples:
        present = set(s.components.keys())
        for comp, val in s.components.items():
            value_map.setdefault(comp, []).append(val)
        # increment missing for components absent that we have seen in others
        all_keys = present | set(missing_counts.keys()) | set(value_map.keys())
        for comp in all_keys:
            if comp not in present:
                missing_counts[comp] = missing_counts.get(comp, 0) + 1
            else:
                missing_counts.setdefault(comp, 0)
    comp_stats: dict[str, Any] = {}
    # Preliminary weight raw store
    prelim_weights: dict[str, float] = {}
    for comp, vals in value_map.items():
        vals_sorted = sorted(vals)
        count = len(vals)
        mn = min(vals_sorted) if vals_sorted else 0.0
        mx = max(vals_sorted) if vals_sorted else 0.0
        mean = statistics.fmean(vals_sorted) if vals_sorted else 0.0
        std = statistics.pstdev(vals_sorted) if len(vals_sorted) > 1 else 0.0
        p50 = _percentile(vals_sorted, 0.5)
        p90 = _percentile(vals_sorted, 0.9)
        p95 = _percentile(vals_sorted, 0.95)
        miss_rate = missing_counts.get(comp, 0) / max(1, len(samples))
        # signal strength: dispersion away from perfect 1.0 (higher dispersion => more information)
        signal_strength = std
        # Weight heuristic selection
        if method == 'inverse-var':
            w_raw = 0.0 if std == 0 else 1.0 / (std * std)
        elif method == 'variance':
            w_raw = std * std
        else:  # signal_scaled
            w_raw = max(std, 1e-6)
        # Penalize if high missing rate (>0.5 reduce by half)
        if miss_rate > 0.5:
            w_raw *= 0.5
        prelim_weights[comp] = w_raw
        comp_stats[comp] = {
            'count': count,
            'mean': round(mean, 6),
            'std': round(std, 6),
            'min': round(mn, 6),
            'max': round(mx, 6),
            'p50': round(p50, 6),
            'p90': round(p90, 6),
            'p95': round(p95, 6),
            'mean_miss': round(miss_rate, 4),
            'signal_strength': round(signal_strength, 6),
        }
    # Normalize weights
    total_w = sum(prelim_weights.values()) or 1.0
    norm = {k: round(v/total_w, 6) for k, v in prelim_weights.items()}
    for k, v in norm.items():
        comp_stats[k]['weight_recommendation'] = v
    return comp_stats, prelim_weights, norm

# ---------------- CLI -----------------

def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="Generate parity weight study artifact")
    ap.add_argument('--pairs', action='append', help='Legacy:pipeline JSON path pair (repeatable)')
    ap.add_argument('--dir', help='Directory containing legacy/pipeline paired JSONs')
    ap.add_argument('--synthetic', type=int, help='Generate N synthetic pairs')
    ap.add_argument('--noise', type=float, default=0.05, help='Synthetic noise amplitude (0..1)')
    ap.add_argument('--missing-prob', type=float, default=0.0, help='Synthetic missing probability per component')
    ap.add_argument('--method', choices=['signal_scaled','inverse-var','variance'], default='signal_scaled')
    ap.add_argument('--seed', type=int, help='Random seed for synthetic reproducibility')
    ap.add_argument('--out', help='Output file (JSON)')
    ap.add_argument('--pretty', action='store_true', help='Pretty-print JSON output')
    ap.add_argument('--base-components', default='index_count,option_count,alerts,strike_coverage,strike_shape,strike_cov_variance', help='Comma list for synthetic base components')
    # Adoption helpers
    ap.add_argument('--emit-env', action='store_true', help='Emit env var line G6_PARITY_COMPONENT_WEIGHTS=... with normalized weights (sorted)')
    ap.add_argument('--weights-only', action='store_true', help='Only output weight plan (omit full artifact JSON)')
    ap.add_argument('--apply-out', help='Path to write .env snippet containing G6_PARITY_COMPONENT_WEIGHTS line')
    return ap.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.seed is not None:
        random.seed(args.seed)
    samples: list[Sample] = []
    mode = None
    params: dict[str, Any] = {}

    if args.pairs:
        pairs: list[tuple[str, str]] = []
        for p in args.pairs:
            if ':' not in p:
                print(f"ERROR invalid pair format: {p}", file=sys.stderr)
                return 1
            a, b = p.split(':', 1)
            pairs.append((a, b))
        samples.extend(_collect_samples(pairs))
        mode = 'pairs'
    if args.dir:
        d = Path(args.dir)
        if not d.exists():
            print(f"ERROR directory not found: {d}", file=sys.stderr)
            return 1
        # naive pairing: find *legacy*.json and substitute legacy->pipeline
        for lp in d.glob('*legacy*.json'):
            pp = Path(str(lp).replace('legacy', 'pipeline'))
            if pp.exists():
                samples.extend(_collect_samples([(str(lp), str(pp))]))
        mode = 'dir'
    if args.synthetic:
        base_components = [c.strip() for c in args.base_components.split(',') if c.strip()]
        params['synthetic_noise'] = args.noise
        params['synthetic_missing_prob'] = args.missing_prob
        synth = _synthetic_pairs(args.synthetic, base_components=base_components, noise=args.noise, missing_prob=args.missing_prob)
        samples.extend(synth)
        mode = mode or 'synthetic'
        if mode != 'synthetic':  # mixture
            mode = f"{mode}+synthetic"
    if not samples:
        print("ERROR: no samples collected (provide --pairs, --dir or --synthetic)", file=sys.stderr)
        return 1

    comp_stats, raw_weights, norm_weights = _summarize(samples, args.method)
    artifact = {
        'generated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'version': 1,
        'source': {'mode': mode, 'count': len(samples)},
        'components': comp_stats,
        'weight_plan': {
            'raw': {k: round(v, 6) for k, v in raw_weights.items()},
            'normalized': norm_weights,
            'method': args.method,
            'notes': 'Weights derived from component dispersion; higher variability => more discriminative signal.' if args.method=='signal_scaled' else 'Classic meta-weight based on variance/inverse-variance.'
        },
        'parameters': params,
    }
    # Weight adoption rendering
    def _env_line() -> str:
        # Sort component names for stable diff / reproducibility
        ordered = sorted(norm_weights.items())
        parts = [f"{k}={v}" for k, v in ordered]
        return "G6_PARITY_COMPONENT_WEIGHTS=" + ",".join(parts)

    env_line = _env_line()

    if args.apply_out:
        Path(args.apply_out).write_text(env_line + '\n', encoding='utf-8')

    if args.weights_only:
        # Minimal output mode
        if args.emit_env:
            print(env_line)
        else:
            minimal = {
                'generated_at': artifact['generated_at'],
                'source': artifact['source'],
                'weight_plan': artifact['weight_plan'],
            }
            print(json.dumps(minimal, indent=2 if args.pretty else None))
        return 0

    text = json.dumps(artifact, indent=2 if args.pretty else None, sort_keys=args.pretty)
    if args.out:
        Path(args.out).write_text(text + ('\n' if not text.endswith('\n') else ''), encoding='utf-8')
    else:
        print(text)
    if args.emit_env:
        # Print env line AFTER artifact so tools reading first JSON remain unaffected.
        print(env_line)
    return 0

if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
