import types

import pandas as pd

from src.utils.overlay_plotting import effective_window, build_merged


def test_effective_window_basic():
    assert effective_window(0.5) == 3.0
    assert round(effective_window(0.25), 2) == 7.0
    assert effective_window(1.0) == 1.0
    assert effective_window(0.0) != effective_window(0.0)  # NaN


def test_build_merged_minimal():
    live = pd.DataFrame({
        'timestamp': pd.to_datetime(['2025-09-23T09:15:00','2025-09-23T09:15:30']),
        'time_key': ['09:15:00','09:15:30'],
        'ce': [10, 12],
        'pe': [15, 18],
        'avg_ce': [11, 11],
        'avg_pe': [16, 17],
        'tp_live': [25, 30],
        'avg_tp_live': [27, 28],
    })
    overlay = pd.DataFrame({
        'timestamp': pd.to_datetime(['2025-09-23T09:15:00','2025-09-23T09:15:30']),
        'time_key': ['09:15:00','09:15:30'],
        'tp_mean': [24, 29],
        'tp_ema': [24, 28],
        'avg_tp_mean': [26, 27],
        'avg_tp_ema': [26, 27],
    })
    merged = build_merged(live, overlay)
    assert list(merged['tp_mean']) == [24, 29]
    assert list(merged['avg_tp_mean']) == [26, 27]