#!/usr/bin/env python3
from collections import defaultdict


def analyze_participant_flows(legs: list[dict[str, str | int | float]]) -> dict[str, int | float]:
    """
    Aggregate net OI changes per participant type.
    """
    net_flows = defaultdict(int)
    for leg in legs:
        ptype = leg.get("participant")
        change = int(leg.get("oi_change", 0) or 0)
        if ptype:
            net_flows[ptype] += change

    result = dict(net_flows)
    result["total_net"] = sum(result.values())
    return result

def analyze_cash_flows(legs: list[dict[str, str | int | float]]) -> dict[str, int | float]:
    """
    Aggregate net cash flows per participant type.
    """
    cash_flows = defaultdict(float)
    for leg in legs:
        ptype = leg.get("participant")
        change = float(leg.get("notional_change", 0.0) or 0.0)
        if ptype:
            cash_flows[ptype] += change

    result = dict(cash_flows)
    result["total_cash_flow"] = sum(result.values())
    return result
