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
import argparse, sys, json, gzip, pathlib, csv, statistics, typing as t, hashlib
from dataclasses import dataclass, asdict

# ---------------- Aggregate -----------------
Artifact = t.Dict[str, t.Any]

def _load_artifact(path: pathlib.Path) -> Artifact | None:
    try:
        if path.suffix == '.gz':
            with gzip.open(path, 'rt', encoding='utf-8') as f:
                return json.load(f)
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:  # pragma: no cover (I/O error path)
        print(f"[bench.aggregate] WARN: failed to read {path}: {e}", file=sys.stderr)
        return None

def _iter_artifacts(root: pathlib.Path) -> t.Iterator[tuple[pathlib.Path, Artifact]]:
    for p in sorted(root.glob('benchmark_cycle_*.json*')):
        art = _load_artifact(p)
        if art is None:
            continue
        yield p, art

def _aggregate_build_rows(arts: list[Artifact], include_index_breakdown: bool):
    phase_keys: set[str] = set(); reason_keys: set[str] = set(); index_keys: set[str] = set()
    for a in arts:
        phase_keys.update((a.get('phase_times') or {}).keys())
        reason_keys.update((a.get('partial_reason_totals') or {}).keys())
        if include_index_breakdown:
            for ix in a.get('indices') or []:
                name = ix.get('index');
                if name: index_keys.add(str(name))
    base_cols = ['timestamp','duration_s','options_total','indices_count']
    phase_cols = [f'phase_{k}' for k in sorted(phase_keys)]
    reason_cols = [f'partial_reason_{k}' for k in sorted(reason_keys)]
    idx_cols = [f'per_index_{k}_options' for k in sorted(index_keys)] if include_index_breakdown else []
    header = base_cols + phase_cols + reason_cols + idx_cols
    rows: list[dict[str,t.Any]] = []
    for a in arts:
        row: dict[str,t.Any] = {c: '' for c in header}
        row['timestamp'] = a.get('timestamp'); row['duration_s'] = a.get('duration_s'); row['options_total'] = a.get('options_total')
        indices = a.get('indices') or []
        row['indices_count'] = len(indices)
        for k,v in (a.get('phase_times') or {}).items(): row[f'phase_{k}'] = v
        for k,v in (a.get('partial_reason_totals') or {}).items(): row[f'partial_reason_{k}'] = v
        if include_index_breakdown:
            for ix in indices:
                name = ix.get('index');
                if not name: continue
                opts = sum(ex.get('options') or 0 for ex in (ix.get('expiries') or []))
                col = f'per_index_{name}_options'
                if col in row: row[col] = opts
        rows.append(row)
    return header, rows

def _compute_stats(rows: list[dict[str,t.Any]]):
    def collect(field: str):
        return [float(r[field]) for r in rows if r.get(field) not in (None, '', 'NaN')]
    def pct(sorted_vals: list[float], p: float) -> float:
        if not sorted_vals: return float('nan')
        k = (len(sorted_vals) - 1) * p; f = int(k); c = min(f+1, len(sorted_vals)-1)
        if f == c: return sorted_vals[f]
        return sorted_vals[f]*(c-k) + sorted_vals[c]*(k-f)
    out: dict[str,dict[str,t.Any]] = {}
    for field in ['duration_s','options_total']:
        vals = collect(field)
        if not vals: continue
        sv = sorted(vals)
        entry: dict[str,t.Any] = {
            'count': len(vals), 'min': min(vals), 'max': max(vals), 'mean': sum(vals)/len(vals),
            'p50': pct(sv,0.50), 'p95': pct(sv,0.95), 'p99': pct(sv,0.99)
        }
        if len(vals) > 1:
            try: entry['stdev'] = statistics.stdev(vals)
            except Exception: pass
        out[field] = entry
    return out

def _write_markdown(stats: dict[str, dict[str,t.Any]], path: pathlib.Path):
    lines = ["# Benchmark Aggregate Statistics","","| metric | count | min | p50 | p95 | p99 | max | mean | stdev |","|--------|-------|-----|-----|-----|-----|-----|------|-------|"]
    for metric in ['duration_s','options_total']:
        if metric not in stats: continue
        s = stats[metric]
        lines.append(f"| {metric} | {s.get('count','')} | {s.get('min','')} | {s.get('p50','')} | {s.get('p95','')} | {s.get('p99','')} | {s.get('max','')} | {s.get('mean','')} | {s.get('stdev','')} |")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines)+"\n", encoding='utf-8')

# ---------------- Diff -----------------

def _pct(old: float | int | None, new: float | int | None) -> str:
    if old in (None, 0) or old is None or new is None: return 'n/a'
    try: return f"{((float(new) - float(old)) / float(old)) * 100.0:+.1f}%"
    except Exception: return 'n/a'

def _diff(old_path: str, new_path: str):
    def _load(path: str) -> Artifact:
        p = pathlib.Path(path)
        if p.suffix == '.gz':
            with gzip.open(p, 'rt', encoding='utf-8') as f: return json.load(f)
        with open(p, 'r', encoding='utf-8') as f: return json.load(f)
    old = _load(old_path); new = _load(new_path)
    lines: list[str] = []
    lines.append(f"Benchmark Diff: {old_path} -> {new_path}")
    d_old = old.get('duration_s'); d_new = new.get('duration_s')
    lines.append(f"Cycle Duration: {d_old:.3f}s -> {d_new:.3f}s ({_pct(d_old,d_new)})")
    if 'options_total' in old or 'options_total' in new:
        o_tot = old.get('options_total',0); n_tot = new.get('options_total',0)
        lines.append(f"Options Total: {o_tot} -> {n_tot} ({_pct(o_tot,n_tot)})")
    lines.append("\nPhase Timings:")
    phases = set((old.get('phase_times') or {}).keys()) | set((new.get('phase_times') or {}).keys())
    for ph in sorted(phases):
        o = (old.get('phase_times') or {}).get(ph); n = (new.get('phase_times') or {}).get(ph)
        if o is None: lines.append(f"  {ph:<20} added {n:.3f}s"); continue
        if n is None: lines.append(f"  {ph:<20} removed (was {o:.3f}s)"); continue
        lines.append(f"  {ph:<20} {o:.3f}s -> {n:.3f}s ({_pct(o,n)})")
    lines.append("\nPartial Reason Totals:")
    pr_old = old.get('partial_reason_totals') or {}; pr_new = new.get('partial_reason_totals') or {}
    all_r = set(pr_old.keys()) | set(pr_new.keys())
    if not all_r: lines.append("  (none)")
    for r in sorted(all_r):
        o = pr_old.get(r,0); n = pr_new.get(r,0)
        lines.append(f"  {r:<12} {o} -> {n} ({_pct(o,n)})")
    lines.append("\nPer-Index:")
    idx_old = {d.get('index'): d for d in (old.get('indices') or [])}
    idx_new = {d.get('index'): d for d in (new.get('indices') or [])}
    for name in sorted(set(idx_old.keys()) | set(idx_new.keys())):
        o = idx_old.get(name); n = idx_new.get(name)
        if o and n:
            opts_o = sum(ex.get('options') or 0 for ex in o.get('expiries') or [])
            opts_n = sum(ex.get('options') or 0 for ex in n.get('expiries') or [])
            lines.append(f"  {name:<10} status {o.get('status')} -> {n.get('status')} | options {opts_o} -> {opts_n} ({_pct(opts_o,opts_n)})")
        elif o and not n:
            lines.append(f"  {name:<10} removed")
        else:
            if n:
                opts_n = sum(ex.get('options') or 0 for ex in n.get('expiries') or [])
                lines.append(f"  {name:<10} added | status {n.get('status')} | options {opts_n}")
            else:
                lines.append(f"  {name:<10} added (no data)")
    return "\n".join(lines)

# ---------------- Verify -----------------
CANONICAL_SEPARATORS = (',', ':')

@dataclass
class ArtifactResult:
    file: str; ok: bool; expected: str | None; computed: str | None; error: str | None = None
    def to_row(self) -> str:
        status = 'OK' if self.ok else ('MISMATCH' if not self.error else 'ERROR')
        return f"{status:9} {self.file} expected={self.expected} computed={self.computed} {('err='+self.error) if self.error else ''}".strip()

def _verify_iter(root: pathlib.Path):
    for p in sorted(root.glob('benchmark_cycle_*.json')):
        if p.is_file(): yield p
    for p in sorted(root.glob('benchmark_cycle_*.json.gz')):
        if p.is_file(): yield p

def _verify_load(path: pathlib.Path):
    if path.suffix == '.gz':
        with gzip.open(path, 'rt', encoding='utf-8') as f: return json.load(f)
    with open(path, 'r', encoding='utf-8') as f: return json.load(f)

def _verify_digest(payload: dict) -> str:
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

def _verify(root: str, verbose: bool, json_report: str | None):
    rp = pathlib.Path(root)
    if not rp.exists() or not rp.is_dir():
        return 1, [], [], []
    results: list[ArtifactResult] = []; mismatches: list[ArtifactResult] = []; errors: list[ArtifactResult] = []
    for p in _verify_iter(rp):
        r = _verify_file(p); results.append(r)
        if verbose: print(r.to_row())
        if r.error and r.error not in ('digest_mismatch','missing_digest'): errors.append(r)
        elif not r.ok: mismatches.append(r)
    if json_report:
        try:
            report = {'directory': str(rp), 'total': len(results), 'ok': sum(1 for r in results if r.ok), 'mismatches': [asdict(r) for r in mismatches], 'errors': [asdict(r) for r in errors]}
            with open(json_report, 'w', encoding='utf-8') as f: json.dump(report, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[bench.verify] WARN: failed writing json report: {e}", file=sys.stderr)
    had_error = bool(errors); has_mismatch = bool(mismatches)
    if had_error: return 3, results, mismatches, errors
    if has_mismatch: return 2, results, mismatches, errors
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
    if argv is None: argv = sys.argv[1:]
    p = _build_parser(); args = p.parse_args(argv)
    if args.cmd == 'aggregate':
        root = pathlib.Path(args.dir); arts = [a for _,a in _iter_artifacts(root)]
        header, rows = _aggregate_build_rows(arts, args.include_index_breakdown)
        out_fh = None
        try:
            if args.out:
                out_path = pathlib.Path(args.out); out_path.parent.mkdir(parents=True, exist_ok=True)
                out_fh = open(out_path, 'w', encoding='utf-8', newline='')
                writer = csv.DictWriter(out_fh, fieldnames=header); writer.writeheader(); writer.writerows(rows)
            else:
                writer = csv.DictWriter(sys.stdout, fieldnames=header); writer.writeheader(); writer.writerows(rows)
        finally:
            if out_fh: out_fh.close()
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
