# Centralized Error Handling in G6

This document describes the unified error handling model for UI panels and general code, replacing ad-hoc try/except blocks with a consistent, observable flow.

## Goals
- Single place to classify, route, and record errors with severity and category
- Consistent UX for panels: graceful fallbacks instead of stack traces
- Metrics-friendly: low-cardinality, structured context via the central handler

## Components
- Central handler: `src/error_handling.py` (see `handle_*` helpers)
- Panel helpers: `src/utils/panel_error_utils.py`
  - `@centralized_panel_error_handler(component)` decorator
  - `safe_panel_execute(func, ..., default_return=..., error_msg=...)`
- Generic helper: `src/utils/error_utils.py`
  - `try_with_central_handler(func, default, category, severity, component, ...)`

## Panel usage
Wrap top-level panel functions with the decorator and use `safe_panel_execute` for inner helpers:

```python
from src.utils.panel_error_utils import centralized_panel_error_handler, safe_panel_execute

@centralized_panel_error_handler("indices_panel")
def indices_panel(status: dict | None, *, show_title: bool = True):
    # build table safely
    value = safe_panel_execute(parse_value, status, default_return="N/A", error_msg="Parse failed")
    # ... return a Rich Panel/Table ...
```

Behavior:
- On exceptions, errors are routed to `handle_ui_error` with structured context
- A small error panel is returned (when Rich is available) to avoid breaking the UI
- Logs include an error-id (when provided by the handler implementation)

## Non-panel usage
For utility paths where a default value is appropriate, use the generic helper:

```python
from src.utils.error_utils import try_with_central_handler
from src.error_handling import ErrorCategory, ErrorSeverity

result = try_with_central_handler(
    lambda: compute_expensive(),
    default={"data": None},
    category=ErrorCategory.DATA_COLLECTION,
    severity=ErrorSeverity.MEDIUM,
    component="collector.compute",
)
```

Quick patterns now used in the codebase:

- Env parsing with defaults (configuration):

```python
from src.utils.error_utils import try_with_central_handler
from src.error_handling import ErrorCategory, ErrorSeverity

buf_size = try_with_central_handler(
  lambda: int(os.environ.get('G6_CSV_BUFFER_SIZE','0')),
  0,
  category=ErrorCategory.CONFIGURATION,
  severity=ErrorSeverity.LOW,
  component="storage.csv_sink",
  context={"var":"G6_CSV_BUFFER_SIZE"},
)
```

- Background loop with fallback to last good snapshot:

```python
try:
  data = self._fetch()
  with self._lock:
    self._data = data
except Exception as e:
  get_error_handler().handle_error(
    e,
    category=ErrorCategory.RESOURCE,
    severity=ErrorSeverity.LOW,
    component="web.metrics_cache",
    function_name="_loop",
    message="Background fetch failed; retaining previous snapshot",
    should_log=False,
  )
  # keep previous self._data
```

Adopted modules: unified_main, config loader, health monitor, csv_sink, metrics_cache.

## Migration guidance
- Replace local decorators like `@panel_error_handler` with `@centralized_panel_error_handler("<component>")`
- Replace scattered try/except blocks that only log with `safe_panel_execute` or `try_with_central_handler`
- Prefer small component names (e.g., `alerts_panel`, `monitoring_panel.storage_backup_panel`) for clarity

## Tests and verification
- Unit tests validate the helpers and end-to-end paths; run the test suite with pytest
- Panels are exercised in smoke tests; centralized routing keeps metrics consistent
