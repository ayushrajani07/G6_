# Terminal Summary Thresholds Reference

_Last updated: 2025-09-27_

Central registry for dashboard / summary_view related display and (future) scoring thresholds.

## Overview
Thresholds are defined in `scripts/summary/thresholds.py` inside a single `REGISTRY` mapping. They can be overridden at runtime using the environment variable `G6_SUMMARY_THRESH_OVERRIDES` which expects a JSON object.

Example:
```
G6_SUMMARY_THRESH_OVERRIDES='{"dq.warn":82, "dq.error":68, "stream.stale.warn_sec":45}'
```

Dot notation keys map to attribute access with underscores:
- Key `dq.warn` -> `T.get("dq.warn")` or `T.dq_warn`
- Key `stream.stale.warn_sec` -> `T.stream_stale_warn_sec`

Overrides are type-coerced based on the default value's type, with defensive fallbacks.

Unknown keys are ignored (logged at debug once) to avoid hard failures due to typos.

## Current Registry Keys
| Key | Default | Description |
|-----|---------|-------------|
| `dq.warn` | 85.0 | Data quality warning threshold (%) – DQ >= warn is green. |
| `dq.error` | 70.0 | Data quality error threshold (%) – DQ < error is red. |
| `stream.stale.warn_sec` | 60.0 | Stream idle age (seconds) at which a yellow warning is shown. |
| `stream.stale.error_sec` | 180.0 | Stream idle age (seconds) at which a red error is shown. |
| `latency.p95.warn_frac` | 1.10 | p95/interval ratio at which timeliness becomes WARN. |
| `latency.p95.error_frac` | 1.40 | p95/interval ratio at which timeliness becomes ERROR. |
| `mem.tier2.mb` | 800.0 | Approximate RSS MB boundary for medium memory pressure. |
| `mem.tier3.mb` | 1200.0 | Approximate RSS MB boundary for high memory pressure. |

## Access Pattern
```
from scripts.summary.thresholds import T
warn = T.dq_warn
err = T.get("dq.error")
all_effective = dump_effective()
```

## Testing Helpers
`reset_for_tests()` resets loaded overrides and caches; used only inside tests.

## Future Additions
Planned additions (post snapshot builder) will include scoring penalty factors and anomaly sensitivity thresholds; these will be added under new domains such as `score.*` or `anomaly.*` to avoid breaking existing overrides.

---
_This file is auto-maintained alongside threshold registry changes. Update both when modifying defaults._
