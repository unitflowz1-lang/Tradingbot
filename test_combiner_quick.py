#!/usr/bin/env python3
"""
Quick test to check combiner output and signal flow
"""
import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import logging
logging.basicConfig(level=logging.DEBUG, format='%(name)s | %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)

async def test():
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize():
            logger.error("MT5 init failed")
            return
        
        from src.strategies.trend_strategy import SimpleTrendStrategy
        from src.models import MarketData
        from datetime import datetime, timezone
        
        # Quick test for USD/JPY
        strategy = SimpleTrendStrategy(symbol="USD/JPY", verbose=True)
        
        # Get 250 bars
        rates = mt5.copy_rates_from_pos("USD/JPY", mt5.TIMEFRAME_H1, 0, 250)
        if not rates or len(rates) < 50:
            logger.error("Insufficient MT5 data")
            mt5.shutdown()
            return
        
        historical_data = [
            MarketData(
                timestamp=datetime.fromtimestamp(r['time'], tz=timezone.utc),
                open=r['open'],
                high=r['high'],
                low=r['low'],
                close=r['close'],
                volume=r['tick_volume'],
                symbol="USD/JPY"
            )
            for r in rates
        ]
        
        logger.critical(f"🔵 Testing signal generation with {len(historical_data)} bars")
        
        # Call analyze
        signal = await strategy.analyze(historical_data)
        
        logger.critical(f"📊 RESULT: Signal = {signal}")
        if signal:
            logger.critical(f"   ✓ Direction: {signal.direction}")
            logger.critical(f"   ✓ Confidence: {signal.confidence:.2%}")
        else:
            logger.critical(f"   ✗ Signal is None")
            
            # Check combiner directly
            logger.critical(f"🔍 Checking combiner state...")
            combiner_result = getattr(strategy, "_last_combiner_result", None)
            if combiner_result:
                logger.critical(f"   Last combiner result: {combiner_result}")
            
            # Check report
            report = getattr(strategy, "_last_symbol_report", {})
            logger.critical(f"   Last symbol report: {report}")
        
        mt5.shutdown()
        return signal is not None
        
    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(test())
    sys.exit(0 if success else 1)
