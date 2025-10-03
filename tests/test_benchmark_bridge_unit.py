import os, json, pathlib, gzip, time
from src.collectors.modules.benchmark_bridge import write_benchmark_artifact
from src.bench.anomaly import detect_anomalies as _detect

class _Ctx:
    def __init__(self):
        self.phase_times = {'fetch':0.01, 'process':0.02}
        self.phase_failures = {}
        import logging
        self.logger = logging.getLogger('benchmark_bridge_test')

class _Metrics:  # minimal dynamic attr container
    pass

# Simple indices_struct sample mirroring legacy shape
_SAMPLE_INDICES = [
    {
        'index': 'NIFTY',
        'status': 'OK',
        'expiries': [
            {
                'rule': 'this_week',
                'status': 'OK',
                'options': 10,
                'strike_coverage': 1.0,
                'field_coverage': 0.5,
                'partial_reason': None,
            }
        ]
    }
]

def _read_json_any(p: pathlib.Path):
    if p.suffix == '.gz':
        with gzip.open(p, 'rt', encoding='utf-8') as fh:
            return json.load(fh)
    with open(p, 'r', encoding='utf-8') as fh:
        return json.load(fh)


def test_bridge_writes_artifact(tmp_path):
    # Arrange
    os.environ['G6_BENCHMARK_DUMP'] = str(tmp_path)
    # Disable anomalies first
    os.environ.pop('G6_BENCHMARK_ANNOTATE_OUTLIERS', None)
    metrics = _Metrics()
    ctx = _Ctx()
    write_benchmark_artifact(_SAMPLE_INDICES, total_elapsed=0.123, ctx_like=ctx, metrics=metrics, detect_anomalies_fn=_detect)
    files = list(tmp_path.glob('benchmark_cycle_*.json')) + list(tmp_path.glob('benchmark_cycle_*.json.gz'))
    assert files, 'expected artifact'
    data = _read_json_any(files[0])
    assert data['version'] == 1
    assert data['options_total'] == 10
    assert 'anomalies' not in data
    assert 'digest_sha256' in data and data['digest_sha256']


def test_bridge_anomalies(tmp_path):
    os.environ['G6_BENCHMARK_DUMP'] = str(tmp_path)
    os.environ['G6_BENCHMARK_ANNOTATE_OUTLIERS'] = '1'
    os.environ['G6_BENCHMARK_ANOMALY_HISTORY'] = '10'
    os.environ['G6_BENCHMARK_ANOMALY_THRESHOLD'] = '3.5'
    metrics = _Metrics()
    ctx = _Ctx()
    # Seed a few baseline artifacts (stable)
    for _ in range(5):
        write_benchmark_artifact(_SAMPLE_INDICES, total_elapsed=0.10, ctx_like=ctx, metrics=metrics, detect_anomalies_fn=_detect)
        time.sleep(0.001)  # ensure distinct timestamp
    # Now produce an anomalous spike by modifying options count via indices struct copy
    spike_struct = [{**_SAMPLE_INDICES[0], 'expiries':[dict(_SAMPLE_INDICES[0]['expiries'][0], options=200)]}]
    write_benchmark_artifact(spike_struct, total_elapsed=0.10, ctx_like=ctx, metrics=metrics, detect_anomalies_fn=_detect)
    files = sorted(tmp_path.glob('benchmark_cycle_*.json'))
    assert files, 'expected artifacts'
    last = _read_json_any(files[-1])
    assert 'anomalies' in last, 'expected anomalies block'
    assert 'options_total' in last['anomalies']
    # Clean env
    for k in ['G6_BENCHMARK_DUMP','G6_BENCHMARK_ANNOTATE_OUTLIERS','G6_BENCHMARK_ANOMALY_HISTORY','G6_BENCHMARK_ANOMALY_THRESHOLD']:
        os.environ.pop(k, None)
