#!/usr/bin/env python3
"""Unified Benchmark Tools (Consolidated Phase 2)

Replaces legacy separate scripts:
  - bench_aggregate.py
  - bench_diff.py
  - bench_verify.py

Subcommands:
  aggregate  -> Aggregate artifacts to CSV / stats / markdown
  diff       -> Human-readable diff between two artifacts
  verify     -> Digest verification over artifact directory

During grace period the original script names remain as thin deprecation
wrappers importing and delegating into this module.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import pathlib
import statistics
import sys
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from typing import Any, cast

# ---------------- Aggregate -----------------
Artifact = dict[str, Any]

def _load_artifact(path: pathlib.Path) -> Artifact | None:
    try:
        if path.suffix == '.gz':
            with gzip.open(path, 'rt', encoding='utf-8') as f:
                return cast(Artifact, json.load(f))
        with open(path, encoding='utf-8') as f:
            return cast(Artifact, json.load(f))
    except Exception as e:  # pragma: no cover (I/O error path)
        print(f"[bench.aggregate] WARN: failed to read {path}: {e}", file=sys.stderr)
        return None

def _iter_artifacts(root: pathlib.Path) -> Iterator[tuple[pathlib.Path, Artifact]]:
    for p in sorted(root.glob('benchmark_cycle_*.json*')):
        art = _load_artifact(p)
        if art is None:
            continue
        yield p, art

def _aggregate_build_rows(
    arts: list[Artifact], include_index_breakdown: bool
) -> tuple[list[str], list[dict[str, Any]]]:
    phase_keys: set[str] = set()
    reason_keys: set[str] = set()
    index_keys: set[str] = set()
    for a in arts:
        pt = cast(dict[str, Any], a.get('phase_times') or {})
        phase_keys.update(pt.keys())
        pr = cast(dict[str, Any], a.get('partial_reason_totals') or {})
        reason_keys.update(pr.keys())
        if include_index_breakdown:
            indices_list = cast(list[dict[str, Any]], a.get('indices') or [])
            for ix in indices_list:
                name = ix.get('index')
                if name:
                    index_keys.add(str(name))
    base_cols = ['timestamp', 'duration_s', 'options_total', 'indices_count']
    phase_cols = [f'phase_{k}' for k in sorted(phase_keys)]
    reason_cols = [f'partial_reason_{k}' for k in sorted(reason_keys)]
    idx_cols = [f'per_index_{k}_options' for k in sorted(index_keys)] if include_index_breakdown else []
    header = base_cols + phase_cols + reason_cols + idx_cols
    rows: list[dict[str, Any]] = []
    for a in arts:
        row: dict[str, Any] = {c: '' for c in header}
        row['timestamp'] = a.get('timestamp')
        row['duration_s'] = a.get('duration_s')
        row['options_total'] = a.get('options_total')
        indices = cast(list[dict[str, Any]], a.get('indices') or [])
        row['indices_count'] = len(indices)
        for k, v in cast(dict[str, Any], a.get('phase_times') or {}).items():
            row[f'phase_{k}'] = v
        for k, v in cast(dict[str, Any], a.get('partial_reason_totals') or {}).items():
            row[f'partial_reason_{k}'] = v
        if include_index_breakdown:
            for ix in indices:
                name = ix.get('index')
                if not name:
                    continue
                opts = sum((cast(dict[str, Any], ex).get('options') or 0) for ex in (ix.get('expiries') or []))
                col = f'per_index_{name}_options'
                if col in row:
                    row[col] = opts
        rows.append(row)
    return header, rows

def _compute_stats(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    def collect(field: str) -> list[float]:
        return [float(r[field]) for r in rows if r.get(field) not in (None, '', 'NaN')]

    def pct(sorted_vals: list[float], p: float) -> float:
        if not sorted_vals:
            return float('nan')
        k = (len(sorted_vals) - 1) * p
        f = int(k)
        c = min(f + 1, len(sorted_vals) - 1)
        if f == c:
            return sorted_vals[f]
        return sorted_vals[f] * (c - k) + sorted_vals[c] * (k - f)
    out: dict[str, dict[str, Any]] = {}
    for field in ['duration_s', 'options_total']:
        vals = collect(field)
        if not vals:
            continue
        sv = sorted(vals)
        entry: dict[str, Any] = {
            'count': len(vals),
            'min': min(vals),
            'max': max(vals),
            'mean': sum(vals) / len(vals),
            'p50': pct(sv, 0.50),
            'p95': pct(sv, 0.95),
            'p99': pct(sv, 0.99),
        }
        if len(vals) > 1:
            try:
                entry['stdev'] = statistics.stdev(vals)
            except Exception:
                pass
        out[field] = entry
    return out

def _write_markdown(stats: dict[str, dict[str, Any]], path: pathlib.Path) -> None:
    lines: list[str] = [
        "# Benchmark Aggregate Statistics",
        "",
        "| metric | count | min | p50 | p95 | p99 | max | mean | stdev |",
        "|--------|-------|-----|-----|-----|-----|-----|------|-------|",
    ]
    for metric in ['duration_s', 'options_total']:
        if metric not in stats:
            continue
        s = stats[metric]
        lines.append(
            "| "
            + " | ".join(
                [
                    metric,
                    str(s.get('count', '')),
                    str(s.get('min', '')),
                    str(s.get('p50', '')),
                    str(s.get('p95', '')),
                    str(s.get('p99', '')),
                    str(s.get('max', '')),
                    str(s.get('mean', '')),
                    str(s.get('stdev', '')),
                ]
            )
            + " |",
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding='utf-8')

# ---------------- Diff -----------------

def _fmt_secs(x: Any) -> str:
    try:
        return f"{float(x):.3f}s"
    except Exception:
        return "n/a"

def _pct(old: Any, new: Any) -> str:
    if old in (None, 0) or old is None or new is None:
        return 'n/a'
    try:
        return f"{((float(new) - float(old)) / float(old)) * 100.0:+.1f}%"
    except Exception:
        return 'n/a'

def _diff(old_path: str, new_path: str) -> str:
    def _load(path: str) -> Artifact:
        p = pathlib.Path(path)
        if p.suffix == '.gz':
            with gzip.open(p, 'rt', encoding='utf-8') as f:
                return cast(Artifact, json.load(f))
        with open(p, encoding='utf-8') as f:
            return cast(Artifact, json.load(f))
    old = _load(old_path)
    new = _load(new_path)
    lines: list[str] = []
    lines.append(f"Benchmark Diff: {old_path} -> {new_path}")
    d_old = old.get('duration_s')
    d_new = new.get('duration_s')
    lines.append(f"Cycle Duration: {_fmt_secs(d_old)} -> {_fmt_secs(d_new)} ({_pct(d_old,d_new)})")
    if 'options_total' in old or 'options_total' in new:
        o_tot = old.get('options_total', 0)
        n_tot = new.get('options_total', 0)
        lines.append(f"Options Total: {o_tot} -> {n_tot} ({_pct(o_tot,n_tot)})")
    lines.append("\nPhase Timings:")
    pt_old = cast(dict[str, Any], old.get('phase_times') or {})
    pt_new = cast(dict[str, Any], new.get('phase_times') or {})
    phases = set(pt_old.keys()) | set(pt_new.keys())
    for ph in sorted(phases):
        o = pt_old.get(ph)
        n = pt_new.get(ph)
        if o is None:
            lines.append(f"  {ph:<20} added {_fmt_secs(n)}")
            continue
        if n is None:
            lines.append(f"  {ph:<20} removed (was {_fmt_secs(o)})")
            continue
        lines.append(f"  {ph:<20} {_fmt_secs(o)} -> {_fmt_secs(n)} ({_pct(o,n)})")
    lines.append("\nPartial Reason Totals:")
    pr_old = cast(dict[str, Any], old.get('partial_reason_totals') or {})
    pr_new = cast(dict[str, Any], new.get('partial_reason_totals') or {})
    all_r = set(pr_old.keys()) | set(pr_new.keys())
    if not all_r:
        lines.append("  (none)")
    for r in sorted(all_r):
        o = pr_old.get(r, 0)
        n = pr_new.get(r, 0)
        lines.append(f"  {r:<12} {o} -> {n} ({_pct(o,n)})")
    lines.append("\nPer-Index:")
    idx_list_old = cast(list[dict[str, Any]], old.get('indices') or [])
    idx_list_new = cast(list[dict[str, Any]], new.get('indices') or [])
    idx_old: dict[Any, dict[str, Any]] = {d.get('index'): d for d in idx_list_old}
    idx_new: dict[Any, dict[str, Any]] = {d.get('index'): d for d in idx_list_new}
    for name in sorted(set(idx_old.keys()) | set(idx_new.keys())):
        o = idx_old.get(name)
        n = idx_new.get(name)
        name_s = str(name) if name is not None else "(none)"
        if o and n:
            opts_o = sum(ex.get('options') or 0 for ex in o.get('expiries') or [])
            opts_n = sum(ex.get('options') or 0 for ex in n.get('expiries') or [])
            lines.append(
                f"  {name_s:<10} status {o.get('status')} -> {n.get('status')} | "
                f"options {opts_o} -> {opts_n} ({_pct(opts_o,opts_n)})"
            )
        elif o and not n:
            lines.append(f"  {name_s:<10} removed")
        else:
            if n:
                opts_n = sum(ex.get('options') or 0 for ex in n.get('expiries') or [])
                lines.append(f"  {name_s:<10} added | status {n.get('status')} | options {opts_n}")
            else:
                lines.append(f"  {name_s:<10} added (no data)")
    return "\n".join(lines)

# ---------------- Verify -----------------
CANONICAL_SEPARATORS = (',', ':')

@dataclass
class ArtifactResult:
    file: str
    ok: bool
    expected: str | None
    computed: str | None
    error: str | None = None

    def to_row(self) -> str:
        status = 'OK' if self.ok else ('MISMATCH' if not self.error else 'ERROR')
        return (
            f"{status:9} {self.file} expected={self.expected} computed={self.computed} "
            f"{('err='+self.error) if self.error else ''}"
        ).strip()

def _verify_iter(root: pathlib.Path) -> Iterator[pathlib.Path]:
    for p in sorted(root.glob('benchmark_cycle_*.json')):
        if p.is_file():
            yield p
    for p in sorted(root.glob('benchmark_cycle_*.json.gz')):
        if p.is_file():
            yield p

def _verify_load(path: pathlib.Path) -> Artifact:
    if path.suffix == '.gz':
        with gzip.open(path, 'rt', encoding='utf-8') as f:
            return cast(Artifact, json.load(f))
    with open(path, encoding='utf-8') as f:
        return cast(Artifact, json.load(f))

def _verify_digest(payload: dict[str, Any]) -> str:
    filtered = {k: payload[k] for k in payload if k != 'digest_sha256'}
    canonical = json.dumps(filtered, sort_keys=True, separators=CANONICAL_SEPARATORS, ensure_ascii=False)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()

def _verify_file(path: pathlib.Path) -> ArtifactResult:
    try:
        payload = _verify_load(path)
        expected = payload.get('digest_sha256')
        computed = _verify_digest(payload)
        ok = (expected == computed) and expected is not None
        if expected is None:
            return ArtifactResult(str(path), False, expected, computed, 'missing_digest')
        return ArtifactResult(str(path), ok, expected, computed, None if ok else 'digest_mismatch')
    except Exception as e:  # pragma: no cover
        return ArtifactResult(str(path), False, None, None, str(e))

def _verify(
    root: str,
    verbose: bool,
    json_report: str | None,
) -> tuple[int, list[ArtifactResult], list[ArtifactResult], list[ArtifactResult]]:
    rp = pathlib.Path(root)
    if not rp.exists() or not rp.is_dir():
        return 1, [], [], []
    results: list[ArtifactResult] = []
    mismatches: list[ArtifactResult] = []
    errors: list[ArtifactResult] = []
    for p in _verify_iter(rp):
        r = _verify_file(p)
        results.append(r)
        if verbose:
            print(r.to_row())
        if r.error and r.error not in ('digest_mismatch', 'missing_digest'):
            errors.append(r)
        elif not r.ok:
            mismatches.append(r)
    if json_report:
        try:
            report = {
                'directory': str(rp),
                'total': len(results),
                'ok': sum(1 for r in results if r.ok),
                'mismatches': [asdict(r) for r in mismatches],
                'errors': [asdict(r) for r in errors],
            }
            with open(json_report, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[bench.verify] WARN: failed writing json report: {e}", file=sys.stderr)
    had_error = bool(errors)
    has_mismatch = bool(mismatches)
    if had_error:
        return 3, results, mismatches, errors
    if has_mismatch:
        return 2, results, mismatches, errors
    return 0, results, mismatches, errors

# ---------------- CLI -----------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description='Unified benchmark tools')
    sub = p.add_subparsers(dest='cmd', required=True)

    p_agg = sub.add_parser('aggregate', help='Aggregate benchmark artifacts to CSV')
    p_agg.add_argument('--dir', required=True)
    p_agg.add_argument('--out')
    p_agg.add_argument('--include-index-breakdown', action='store_true')
    p_agg.add_argument('--stats-out')
    p_agg.add_argument('--markdown-out')

    p_diff = sub.add_parser('diff', help='Diff two benchmark artifacts')
    p_diff.add_argument('old')
    p_diff.add_argument('new')

    p_ver = sub.add_parser('verify', help='Verify digests of benchmark artifacts in a directory')
    p_ver.add_argument('artifact_dir')
    p_ver.add_argument('--verbose', action='store_true')
    p_ver.add_argument('--json-report')

    return p

def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    p = _build_parser()
    args = p.parse_args(argv)
    if args.cmd == 'aggregate':
        root = pathlib.Path(args.dir)
        arts = [a for _, a in _iter_artifacts(root)]
        header, rows = _aggregate_build_rows(arts, args.include_index_breakdown)
        out_fh = None
        try:
            if args.out:
                out_path = pathlib.Path(args.out)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_fh = open(out_path, 'w', encoding='utf-8', newline='')
                writer = csv.DictWriter(out_fh, fieldnames=header)
                writer.writeheader()
                writer.writerows(rows)
            else:
                writer = csv.DictWriter(sys.stdout, fieldnames=header)
                writer.writeheader()
                writer.writerows(rows)
        finally:
            if out_fh:
                out_fh.close()
        if args.stats_out:
            stats = _compute_stats(rows)
            pathlib.Path(args.stats_out).write_text(json.dumps(stats, indent=2), encoding='utf-8')
        if args.markdown_out:
            stats = _compute_stats(rows)
            _write_markdown(stats, pathlib.Path(args.markdown_out))
        return 0
    elif args.cmd == 'diff':
        print(_diff(args.old, args.new))
        return 0
    elif args.cmd == 'verify':
        code, *_rest = _verify(args.artifact_dir, args.verbose, args.json_report)
        return code
    else:
        p.error('Unknown command')
    return 1

if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
