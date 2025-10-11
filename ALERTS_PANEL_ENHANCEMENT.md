<!-- Archived stub: original content moved to archive/2025-10-05/ALERTS_PANEL_ENHANCEMENT.md -->
# Alerts Panel Enhancement (Archived)

Summarized in `docs/features_history.md` (Alerts Panel Full-Length Expansion).

## Changes Made

### 1. Increased Display Capacity
- **Normal mode**: 15 rows (up from 5 rows) - 3x increase
- **Compact mode**: 4 rows (up from 2 rows) - 2x increase
- Alert panel now uses ~70% of right column height more effectively

### 2. Enhanced Rolling Log Storage
- **Rolling log entries**: Up to 100 recent entries (from 50)
- **Persistent storage**: Up to 500 entries (from 200)
- **Centralized alerts**: Up to 50 entries (from 20)

### 3. Better Space Utilization
- Alert panel takes advantage of its 70% allocation in the right column
- More comprehensive view of system alerts and data quality issues
- Improved rolling log persistence for historical tracking

## Technical Implementation

### File Modified
- `scripts/summary/panels/alerts.py`

### Key Changes
```python
# Increased display rows
max_rows = 4 if compact else 15  # Was: 2 if compact else 5

# Enhanced rolling log capacity
def _get_rolling_alerts_log(max_entries=100):  # Was: max_entries=50

# Increased persistent storage
def _add_to_rolling_alerts_log(new_alerts, max_entries=500):  # Was: max_entries=200

# More centralized alerts
centralized_alerts = handler.get_errors_for_alerts_panel(count=50)  # Was: count=20
```

## Benefits

1. **Better System Monitoring**: More alert history visible without scrolling
2. **Improved Debugging**: Longer alert trail for troubleshooting issues  
3. **Enhanced User Experience**: Fuller utilization of available screen real estate
4. **Better Context**: More comprehensive view of system health trends

## 2025-10-08 (Wave 4 – W4-03) Alert Severity Labels

Implemented category severity mapping surfaced via `alerts.severity` in the pipeline snapshot summary:

Default mapping (can be overridden by env `G6_ALERT_SEVERITY_MAP` with JSON):

| Category | Default Severity |
|----------|------------------|
| index_failure | critical |
| index_empty | critical |
| expiry_empty | warning |
| low_both_coverage | warning |
| low_strike_coverage | warning |
| low_field_coverage | info |
| liquidity_low | info |
| stale_quote | warning |
| wide_spread | warning |
| synthetic_quotes_used | info (legacy placeholder) |

Environment override example:
```
G6_ALERT_SEVERITY_MAP={"index_failure":"warning","low_field_coverage":"critical"}
```

Snapshot snippet:
```jsonc
"alerts": {
	"total": 7,
	"categories": {"index_failure":1, "low_field_coverage":2, ...},
	"index_triggers": {"index_failure":["NIFTY"]},
	"severity": {"index_failure":"critical","low_field_coverage":"info", ...}
}
```

Panels and parity diff logic can now classify and group alerts by severity without additional per-cycle computation.

## 2025-10-08 (Wave 4 – W4-04) Panel Severity Grouping

Added optional grouping of alert categories by severity in the alerts panel footer.

Environment flags:
- `G6_ALERTS_SEVERITY_GROUPING` (default: `1` / enabled) – toggle grouping footer lines.
- `G6_ALERTS_SEVERITY_TOP_CAP` (default: `3`) – max top categories displayed per severity bucket.

Footer additions when enabled:
```
Active: 3 Critical | 5 Warning | 2 Info
Categories: 5 crit(cat) 4 warn(cat) 2 info(cat)
Top: SYSTEM_FAILURE:5 SLOW_PHASE:4 DATA_DELAY:3 ...
```

Behavior notes:
- Gracefully degrades (no grouping lines) if snapshot lacks `alerts.categories` or `alerts.severity`.
- Capped total displayed top categories (panel logic hard-caps to 6 overall after per-severity cap).
- Resilient to errors: exceptions in grouping logic are captured and logged via `handle_ui_error` but do not break panel rendering.

Implementation reference: `scripts/summary/panels/alerts.py` (section marked `Severity Grouping (W4-04)`).

Testing: `tests/test_alerts_panel_severity_grouping.py` validates enabled/disabled modes and presence of grouping lines.

## Visual Result
The alerts panel now displays a comprehensive rolling log that fills the available panel space, showing:
- Timestamps with time formatting
- Color-coded alert levels (ERROR/WARNING/INFO)
- Component names and detailed messages
- Active alert summary footer

## Layout Integration
- Maintains compatibility with existing 3-column layout
- Works seamlessly with both compact and normal display modes
- Preserves footer summary with alert counts and status
- No impact on other panel dimensions or functionality