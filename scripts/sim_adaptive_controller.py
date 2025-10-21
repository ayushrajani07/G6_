"""Adaptive Controller Simulation Script

Usage (example):
  python scripts/sim_adaptive_controller.py --cycles 30 --breach-pattern 0,1,1,0,0,0,0 --memory-pattern 0,0,0,2,2,1,0

Demonstrates demotion/promotions driven by:
  - SLA breach streak (derived from simulated breach events)
  - Memory tier elevations

Environment flags influencing behavior (or override via args):
  G6_ADAPTIVE_SLA_BREACH_STREAK, G6_ADAPTIVE_RECOVERY_CYCLES,
  G6_ADAPTIVE_MIN_DETAIL_MODE, G6_ADAPTIVE_MAX_DETAIL_MODE

Outputs a table of cycle events with columns:
  cycle | breach? | memory_tier | detail_mode | action(reason)
"""
from __future__ import annotations

import argparse
import os

from src.orchestrator.adaptive_controller import evaluate_adaptive_controller
from src.orchestrator.context import RuntimeContext


class _MetricsStub:
    def __init__(self):
        class _Counter:
            def __init__(self):
                self._value = type('V', (), {'get': lambda self_: self_.val})()
                self.val = 0
            def inc(self, n: int = 1):
                self.val += n
        class _LabeledCounter:
            def __init__(self):
                self.series = []
            def labels(self, **lbls):
                class _Inc:
                    def __init__(self, outer, labels):
                        self.outer = outer; self.labels = labels
                    def inc(self, n: int = 1):
                        self.outer.series.append((self.labels, n))
                return _Inc(self, lbls)
        class _Gauge:
            def __init__(self):
                self.values = {}
            def labels(self, **lbls):
                class _Set:
                    def __init__(self, outer, labels):
                        self.outer = outer; self.labels = tuple(sorted(labels.items()))
                    def set(self, v):
                        self.outer.values[self.labels] = v
                return _Set(self, lbls)
        self.cycle_sla_breach = _Counter()
        self.adaptive_controller_actions = _LabeledCounter()
        self.option_detail_mode = _Gauge()


def parse_pattern(raw: str, cycles: int) -> list[int]:
    if not raw:
        return [0]*cycles
    parts = [p.strip() for p in raw.split(',') if p.strip()]
    seq = [int(p) for p in parts]
    if len(seq) >= cycles:
        return seq[:cycles]
    # Repeat pattern if shorter
    out = []
    i = 0
    while len(out) < cycles:
        out.append(seq[i % len(seq)])
        i += 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cycles', type=int, default=25, help='Total simulated cycles')
    ap.add_argument('--breach-pattern', type=str, default='', help='Comma list of 0/1 for SLA breach occurrences (repeats)')
    ap.add_argument('--memory-pattern', type=str, default='', help='Comma list of memory tiers (0/1/2) per cycle (repeats)')
    ap.add_argument('--interval', type=float, default=60.0, help='Cycle interval seconds (for reference)')
    args = ap.parse_args()

    metrics = _MetricsStub()
    ctx = RuntimeContext(config={}, metrics=metrics)
    ctx.index_params = {"NIFTY": {"enable": True, "expiries": ["this_week"]}}

    breach_seq = parse_pattern(args.breach_pattern, args.cycles)
    mem_seq = parse_pattern(args.memory_pattern, args.cycles)

    os.environ.setdefault('G6_ADAPTIVE_CONTROLLER', '1')

    header = f"{'cycle':>5} {'breach':>6} {'mem':>4} {'mode':>4} action(reason)"
    print(header)
    print('-'*len(header))
    for c in range(args.cycles):
        breach = breach_seq[c] == 1
        mem_tier = mem_seq[c]
        ctx.set_flag('memory_tier', mem_tier)
        if breach:
            metrics.cycle_sla_breach.inc()
        # Evaluate controller
        evaluate_adaptive_controller(ctx, elapsed=10.0, interval=args.interval)
        mode = ctx.flag('option_detail_mode')
        # Extract last action if any
        last_action = metrics.adaptive_controller_actions.series[-1] if metrics.adaptive_controller_actions.series else None
        action_repr = ''
        if last_action:
            labels, inc = last_action
            action_repr = f"{labels.get('action')}({labels.get('reason')})"
        print(f"{c:5d} {int(breach):6d} {mem_tier:4d} {mode:4d} {action_repr}")

    # Summarize actions
    demotes = sum(1 for (lbls, _) in metrics.adaptive_controller_actions.series if lbls.get('action')=='demote')
    promotes = sum(1 for (lbls, _) in metrics.adaptive_controller_actions.series if lbls.get('action')=='promote')
    print(f"\nTotal demotes={demotes} promotes={promotes}")


if __name__ == '__main__':
    main()
