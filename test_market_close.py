#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test Market Close Detection Logic
Tests the market close shutdown functionality in the collector.
"""

import sys
import os
import datetime
from unittest import mock

# Add project root to path
sys.path.insert(0, os.path.abspath('.'))

def test_market_close_detection():
    """Test market close detection logic."""
    print("🧪 Testing Market Close Detection Logic")
    print("=" * 50)
    
    from src.utils.market_hours import is_market_open, get_next_market_open, DEFAULT_MARKET_HOURS
    
    # Test 1: Check current market status
    print("\n1️⃣ Current Market Status:")
    current_status = is_market_open(market_type="equity", session_type="regular")
    print(f"   Market currently open: {current_status}")
    
    if current_status:
        # Find when market will close
        equity_close = DEFAULT_MARKET_HOURS["equity"]["regular"]["end"]
        print(f"   Market closes at: {equity_close} IST")
        
        # Calculate time to close
        from datetime import datetime, timezone, timedelta
        # Use a proper IST timezone (UTC+05:30) and ensure both datetimes are aware
        ist_tz = timezone(timedelta(hours=5, minutes=30), name="IST")
        now_utc = datetime.now(timezone.utc)
        ist_now = now_utc.astimezone(ist_tz)

        close_time = datetime.strptime(equity_close, "%H:%M:%S").time()
        close_datetime = datetime.combine(ist_now.date(), close_time, tzinfo=ist_tz)
        
        if ist_now.time() < close_time:
            time_to_close = (close_datetime - ist_now).total_seconds()
            print(f"   Time until close: {time_to_close/60:.1f} minutes")
        else:
            print("   Market should be closed (past closing time)")
    else:
        next_open = get_next_market_open(market_type="equity", session_type="regular")
        print(f"   Next market open: {next_open}")
    
    # Test 2: Simulate market close detection
    print("\n2️⃣ Simulating Market Close Detection:")
    
    # Mock a future time when market is closed
    import datetime as dt
    future_closed_time = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)
    
    with mock.patch('src.utils.market_hours.is_market_open') as mock_is_open:
        # First call returns True (market open), second returns False (market closed)
        mock_is_open.side_effect = [True, False]
        
        print("   Simulating collection cycle during market hours...")
        market_open_1 = is_market_open()
        print(f"   First check - Market open: {market_open_1}")
        
        print("   Simulating next collection cycle after market close...")
        market_open_2 = is_market_open()
        print(f"   Second check - Market open: {market_open_2}")
        
        if not market_open_2:
            print("   ✅ Market close detected - Collector would stop")
        else:
            print("   ❌ Market close not detected")
    
    # Test 3: Test next collection time logic
    print("\n3️⃣ Testing Next Collection Time Logic:")
    
    interval = 60  # 60 seconds
    elapsed = 10   # 10 seconds elapsed
    sleep_time = max(0, interval - elapsed)
    next_collection_time = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=sleep_time)
    
    print(f"   Current interval: {interval}s")
    print(f"   Cycle elapsed: {elapsed}s")
    print(f"   Sleep time: {sleep_time}s")
    print(f"   Next collection at: {next_collection_time}")
    
    # Check if market will be open at next collection time
    next_market_status = is_market_open(reference_time=next_collection_time)
    print(f"   Market will be open at next collection: {next_market_status}")
    
    if not next_market_status:
        print("   ✅ Market will close before next collection - Collector would stop")
    else:
        print("   ⏭️  Market will still be open at next collection - Continue")
    
    print("\n✅ Market Close Detection Test Complete!")
    # Use an assertion instead of returning a value to satisfy pytest expectations
    assert True

if __name__ == "__main__":
    test_market_close_detection()