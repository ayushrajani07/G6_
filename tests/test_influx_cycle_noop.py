import os, sys, tempfile
from importlib import import_module

def test_null_influx_sink_cycle_noop():
    mod = import_module('src.storage.influx_sink')
    NullInfluxSink = getattr(mod, 'NullInfluxSink')
    sink = NullInfluxSink()
    # Should not raise
    sink.write_cycle_stats(cycle=1, elapsed=0.5, success_rate=100.0, options_last=10, per_index={'NIFTY':10})
