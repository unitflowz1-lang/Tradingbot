#!/usr/bin/env python3
"""
Diagnostic script to identify why ML=NONE and Conf=0% (signal filtering issue)
"""
import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.models import MarketData, Direction
from src.strategies.trend_strategy import SimpleTrendStrategy
from datetime import datetime, timezone
from src.analysis.technical_indicators import IndicatorCalculator
import logging

logging.basicConfig(level=logging.DEBUG, format='%(levelname)s | %(message)s')
logger = logging.getLogger(__name__)

async def diagnose():
    """Check if H4 Trend filter is blocking all technical signals"""
    
    strategy = SimpleTrendStrategy(symbol="USD/JPY", verbose=True)
    
    # Simulate some recent market data (fetch from MT5 if available)
    try:
        # Try to get real data first
        import MetaTrader5 as mt5
        
        if not mt5.initialize():
            logger.warning("MT5 not available, skipping real data test")
            return
            
        rates = mt5.copy_rates_from_pos("USD/JPY", mt5.TIMEFRAME_H1, 0, 300)
        if rates is None or len(rates) == 0:
            logger.warning("No data from MT5")
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
        
        current_price = historical_data[-1].close
        
        # Calculate indicators
        calc = IndicatorCalculator()
        indicators = calc.calculate_all(historical_data)
        
        # Calculate H4 Trend (SMA200)
        if len(historical_data) >= 200:
            closes_long = [d.close for d in historical_data[-200:]]
            h4_trend_sma = sum(closes_long) / 200
        else:
            h4_trend_sma = None
        
        logger.info(f"Current Price: {current_price:.5f}")
        logger.info(f"H4 Trend (SMA200): {h4_trend_sma:.5f}" if h4_trend_sma else "H4 Trend: Not enough data")
        
        if h4_trend_sma:
            # Check filter bounds
            buy_threshold = h4_trend_sma * 0.9995
            sell_threshold = h4_trend_sma * 1.0005
            
            logger.info(f"BUY allowed if price > {buy_threshold:.5f} (99.95% of SMA200)")
            logger.info(f"SELL allowed if price < {sell_threshold:.5f} (100.05% of SMA200)")
            
            # Check current state
            buy_allowed = current_price > buy_threshold
            sell_allowed = current_price < sell_threshold
            
            logger.info(f"\nCurrent state:")
            logger.info(f"  BUY signals allowed: {buy_allowed}")
            logger.info(f"  SELL signals allowed: {sell_allowed}")
            logger.info(f"  Distance from SMA200: {(current_price - h4_trend_sma):.5f} ({((current_price - h4_trend_sma) / h4_trend_sma * 100):.3f}%)")
            
            if not buy_allowed and not sell_allowed:
                logger.critical("⚠️  BOTH BUY and SELL signals are BLOCKED!")
                logger.critical("   This explains ML=NONE, Conf=0% - NO technical signals getting through!")
                logger.critical("   Root cause: H4 Trend filter is TOO RESTRICTIVE")
        
        # Now try to analyze
        logger.info("\nRunning strategy.analyze()...")
        signal = await strategy.analyze(historical_data)
        
        logger.info(f"Signal returned: {signal}")
        if signal:
            logger.info(f"  Direction: {signal.direction}")
            logger.info(f"  Confidence: {signal.confidence:.2f}")
        else:
            logger.critical("⚠️  Signal is None - analysis produced no tradable signal")
        
        mt5.shutdown()
        
    except ImportError:
        logger.warning("MetaTrader5 not available, cannot diagnose")
    except Exception as e:
        logger.error(f"Error during diagnosis: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(diagnose())
