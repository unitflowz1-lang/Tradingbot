#!/usr/bin/env python3
"""
Test script to verify signal generation fixes
"""
import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import logging
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger(__name__)

async def test_signal_generation():
    """Test that signals are being generated with proper ML and confidence"""
    try:
        import MetaTrader5 as mt5
        
        if not mt5.initialize():
            logger.error("MT5 initialization failed")
            return
        
        from src.strategies.trend_strategy import SimpleTrendStrategy
        from src.models import MarketData
        from datetime import datetime, timezone
        
        strategy = SimpleTrendStrategy(symbol="USD/JPY", verbose=True)
        
        # Fetch recent H1 data
        rates = mt5.copy_rates_from_pos("USD/JPY", mt5.TIMEFRAME_H1, 0, 250)
        if rates is None or len(rates) < 50:
            logger.error("Insufficient data from MT5")
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
        
        logger.info(f"📊 Testing signal generation with {len(historical_data)} bars")
        logger.info(f"Price range: {min(d.close for d in historical_data):.5f} - {max(d.close for d in historical_data):.5f}")
        
        # Analyze
        signal = await strategy.analyze(historical_data)
        
        if signal is None:
            logger.critical("❌ SIGNAL IS NONE - Analysis failed to generate signal!")
            # Check _last_symbol_report for debugging
            report = getattr(strategy, "_last_symbol_report", {})
            logger.info(f"Last symbol report: {report}")
            return False
        
        logger.info(f"✅ Signal generated successfully!")
        logger.info(f"   Direction: {signal.direction}")
        logger.info(f"   Confidence: {signal.confidence:.2%}")
        logger.info(f"   Entry: {signal.entry_price:.5f}")
        logger.info(f"   SL: {signal.stop_loss:.5f}")
        logger.info(f"   TP: {signal.take_profit:.5f}")
        
        # Verify signal attributes
        if signal.direction is None:
            logger.critical("❌ Signal direction is None!")
            return False
        
        if signal.confidence == 0.0:
            logger.warning(f"⚠️  Signal confidence is 0.0 - may indicate low ML confidence")
        
        # Check for synthetic signals
        if hasattr(signal, 'forced_execution'):
            logger.info(f"   Forced execution: {signal.forced_execution}")
        
        mt5.shutdown()
        return True
        
    except Exception as e:
        logger.error(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    result = asyncio.run(test_signal_generation())
    sys.exit(0 if result else 1)
