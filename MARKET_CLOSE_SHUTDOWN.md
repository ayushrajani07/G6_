# Market Close Shutdown Implementation

## Overview
Implemented automatic collector shutdown at the end of market trading hours to ensure the G6 platform stops data collection when markets close, preventing unnecessary API calls and resource usage.

## Features Implemented

### 1. Market Close Detection in Collection Loop
- **File Modified**: `src/unified_main.py`
- **Location**: `collection_loop()` function
- **Trigger**: Only active when `market_hours_only=True`

### 2. Two-Level Market Close Detection

#### Level 1: Next Collection Time Check
```python
if market_hours_only:
    sleep_time = max(0, interval - elapsed)
    next_collection_time = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(seconds=sleep_time)
    
    if not is_market_open(reference_time=next_collection_time):
        logging.info("Market will close before next collection cycle. Stopping collector.")
        break
```
- Calculates when the next collection cycle would occur
- Checks if market will still be open at that time
- Stops collector if market will be closed

#### Level 2: Current Market Status Check  
```python
if not is_market_open():
    logging.info("Market has closed. Stopping collector at end of trading hours.")
    break
```
- Checks current market status after each cycle
- Immediate shutdown if market has closed during processing

### 3. Graceful Shutdown Process
1. **Detection**: Market close detected via `is_market_open()` function
2. **Logging**: Clear shutdown message logged  
3. **Loop Exit**: Clean break from main collection loop
4. **Cleanup**: Existing `finally` block in `main()` handles resource cleanup:
   - Health monitor shutdown
   - Provider connections closed
   - Metrics server stopped
   - Status polling thread terminated

## Usage

### Command Line Flag
```bash
python scripts/run_orchestrator_loop.py --config config/g6_config.json --interval 60 --market-hours-only
```

### Configuration
The market close detection is controlled by the `market_hours_only` parameter passed to `collection_loop()`.

### Market Hours Configuration
Market hours are defined in `src/utils/market_hours.py`:
```python
DEFAULT_MARKET_HOURS = {
    "equity": {
        "regular": {"start": "09:15:00", "end": "15:30:00"},
    }
}
```

## Testing

### Test Files Created
1. **`test_market_close.py`**: Unit tests for market hours logic
2. **`test_unified_main_market_close.py`**: Integration tests for shutdown functionality

### Test Results
- ✅ Market close detection working correctly
- ✅ Graceful shutdown with proper logging
- ✅ No impact when `market_hours_only=False` 
- ✅ Clean resource cleanup on exit

## Benefits

### 1. Resource Optimization
- Stops unnecessary API calls after market close
- Reduces server resource usage during non-trading hours
- Prevents accumulation of stale data

### 2. Operational Efficiency  
- Automatic shutdown eliminates need for manual intervention
- Clear logging provides operational visibility
- Consistent behavior across different deployment scenarios

### 3. Cost Savings
- Reduces API usage costs from external providers
- Lower compute resource utilization
- Minimizes bandwidth usage

## Integration with Existing Code

### Backward Compatibility
- Existing behavior preserved when `market_hours_only=False`
- No changes to default configuration or API
- Graceful degradation if market hours detection fails

### Consistency with Other Loops
- `src/main.py` already has sophisticated market close logic
- Implementation follows similar patterns for consistency
- Enhanced logic available in unified_main.py for newer deployments

## Example Log Output

```
INFO: Cycle completed in 2.45s
INFO: Market will close before next collection cycle. Stopping collector.
INFO: Shutting down G6 Platform
INFO: Stopping health monitor
INFO: Closing data providers  
INFO: Shutdown complete
```

## Configuration Examples

### Always Run (Default)
```json
{
  "market_hours_only": false
}
```

### Market Hours Only
```json
{
  "market_hours_only": true,
  "market_hours": {
    "equity": {
      "regular": {"start": "09:15:00", "end": "15:30:00"}
    }
  }
}
```

## Future Enhancements

### Potential Improvements
1. **Pre-market/Post-market Support**: Different shutdown logic for different trading sessions
2. **Holiday Detection**: Integration with trading calendar for market holidays
3. **Configurable Shutdown Delay**: Allow custom delay after market close
4. **Notification System**: Alert operators when automatic shutdown occurs

### Extension Points
- Market hours configuration via external API
- Custom shutdown callbacks for cleanup tasks
- Integration with external monitoring systems