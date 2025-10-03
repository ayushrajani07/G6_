# Alerts Panel Enhancement - Full Length Display

## Overview
The alerts panel has been enhanced to use the full available length for displaying rolling alert logs, significantly increasing the amount of alert history visible at any time.

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