# Testing

## Windows note: use the pytest wrapper

On Windows (PowerShell/cmd), quoting for marker expressions and environment injection via PYTEST_ADDOPTS can cause flaky or failing runs (e.g., -m "not serial"). To avoid this, use the Python wrapper which sanitizes the environment and passes arguments directly to pytest:

- scripts/pytest_run.py serial → run full suite in serial (-n 0)
- scripts/pytest_run.py parallel-subset → run not serial with xdist (-n auto)
- scripts/pytest_run.py fast-inner → quick loop excluding slow/integration/perf/serial

VS Code tasks in .vscode/tasks.json are wired to this wrapper so you can use the Command Palette → Run Task and pick:

- pytest - full serial
- pytest - parallel (xdist)
- pytest - fast inner loop

This avoids shell quoting pitfalls and ensures G6_INFLUX_OPTIONAL=1 during tests while clearing PYTEST_* variables.
# Testing Strategy

This project splits tests into **core** and **optional** categories to minimize interference with normal development while still offering richer integration coverage when desired.

## Categories & Markers

| Marker | Purpose | Default | Enable Condition |
|--------|---------|---------|------------------|
| `optional` | Developer / exploratory or heavier integration flows (mock multi-cycles) | Skipped | `G6_ENABLE_OPTIONAL_TESTS=1` |
| `slow` | Longer-running variants (more cycles / timing dependent) | Skipped | `G6_ENABLE_SLOW_TESTS=1` or `-m slow` |
| `integration` | Higher-level orchestration tests (may spin threads) | Included (unless also optional/slow) | N/A |
| `perf` | Lightweight performance smoke tests (timing ceilings) | Skipped | `G6_ENABLE_OPTIONAL_TESTS=1` (perf tests are also marked optional) |

Core unit-style and fast integration tests run with plain `pytest` and no env flags.

## Environment Flags

Set any of these (case-insensitive values: `1,true,yes,on`):

- `G6_ENABLE_OPTIONAL_TESTS=1` – include tests marked `@pytest.mark.optional`.
- `G6_ENABLE_SLOW_TESTS=1` – include tests marked `@pytest.mark.slow`.

Example (PowerShell):
```powershell
$env:G6_ENABLE_OPTIONAL_TESTS='1'; pytest -q
```

## Mock Runtime Fixture

`run_mock_cycle` fixture provides a reusable harness to run `unified_main` in mock mode for N cycles without external API auth.

Usage example:
```python
def test_progress(run_mock_cycle):
    data = run_mock_cycle(cycles=2, interval=2)
    assert data['cycle'] >= 1
```

Internals (current implementation):
- Leverages internal loop bounding via `G6_MAX_CYCLES` so cycles proceed within a single `unified_main` process (lower overhead).
- Skips provider readiness probe in tests via `G6_SKIP_PROVIDER_READINESS=1` to reduce startup latency.
- Enforces fancy console + Unicode (unless ASCII fallback applies) for consistent output capture.
- Uses `--metrics-custom-registry` and initial `--metrics-reset` to avoid Prometheus duplication (see also `metrics_isolated` fixture for future granular metrics tests).
- Writes status JSON to a session temp directory.

## Adding New Optional Tests
1. Mark them: `@pytest.mark.optional` (and `@pytest.mark.slow` if longer).
2. Prefer shared fixtures (`run_mock_cycle`) over bespoke script calls.
3. Avoid network / external APIs—mock provider only.

## Rationale
- Keeping optional tests gated preserves fast feedback cycles.
- Developers can opt-in for deeper validation pre-commit or before releases.
- Reduces flakiness and CI time by default while protecting advanced behaviors.

## Removed / Consolidated
- `test_mock_cycle.py` and `test_mock_dashboard.py` replaced by `test_mock_runtime_optional.py` (parameterized / consolidated).

## Schema Validation
Runtime status JSON now has a lightweight schema & validator (`src/schema/runtime_status_validator.py`).
An optional test (`test_runtime_status_schema_optional.py`) validates real mock output; failures list human-readable messages.

Manual validation example:
```powershell
python scripts/dev_tools.py validate-status --file .\runtime_status.json
```
Or pipe:
```powershell
type .\runtime_status.json | python scripts/dev_tools.py validate-status
```

## Performance Marker
`@pytest.mark.perf` introduced for coarse timing alerts. Current perf test (`test_perf_mock_cycle_optional.py`) ensures two short mock cycles finish under a tightened threshold (<8s) after readiness probe skip optimization. Adjust only if unavoidable CI variance is observed.

## Unified Dev Tools Script
`scripts/dev_tools.py` consolidates common developer flows:
- `run-once` – single mock cycle
- `dashboard` – repeated cycles with summary output
- `view-status` – tail/pretty-print a status file
- `validate-status` – schema validation (file/stdin)
- `full-tests` – run core then optional+slow suites

Examples:
```powershell
python scripts/dev_tools.py run-once --interval 2 --status-file tmp_status.json
python scripts/dev_tools.py dashboard --cycles 3 --interval 2
python scripts/dev_tools.py full-tests
```

## Metrics Isolation Helper
`metrics_isolated` fixture (wrapping `isolated_metrics_registry`) is available for tests that construct metrics directly without CLI flags, ensuring collectors are cleaned after use.

## Benchmark Harness
`scripts/benchmark_cycles.py` provides a quick wall-clock benchmark for N mock cycles:
```powershell
python scripts/benchmark_cycles.py --cycles 5 --interval 2 --pretty
```
Outputs JSON (total_time, avg_cycle, etc.). Currently per-cycle list is approximated evenly until deeper instrumentation lands.

## Strict Schema Mode
The runtime status validator now supports a `strict=True` mode (used in optional tests) that rejects unknown top-level keys to surface accidental drift:
```python
from src.schema.runtime_status_validator import validate_runtime_status
errors = validate_runtime_status(obj, strict=True)
```
Optional test: `test_runtime_status_strict_optional.py`.

## New / Notable Environment Variables
| Variable | Purpose |
|----------|---------|
| `G6_MAX_CYCLES` | Internal loop bound used by tests & benchmarks to stop after N cycles. |
| `G6_SKIP_PROVIDER_READINESS` | Skip live provider readiness probe (speeds test startup). |
| `G6_FORCE_ASCII` / `G6_FORCE_UNICODE` | Override automatic Unicode fallback heuristic. |

## Unicode / ASCII Fallback
Startup now auto-detects a non-UTF console and (unless `G6_FORCE_UNICODE` set) disables fancy Unicode banners and enforces ASCII for portability.

## Recently Completed Enhancements
- Added readiness probe skip (`G6_SKIP_PROVIDER_READINESS`) for tests.
- Added benchmark harness.
- Added CLI-based status validation test.
- Implemented strict schema validation mode + tests.
- Implemented Unicode fallback & ASCII enforcement logic.
- Tightened perf threshold from 15s to 8s.

Happy testing!
