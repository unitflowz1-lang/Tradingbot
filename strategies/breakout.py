"""
Breakout Strategy.
Trades breakouts from consolidation patterns.
"""

import pandas as pd
import numpy as np
from core.strategy_manager import Strategy, Signal
from utils.logger import get_logger


logger = get_logger(__name__)


class BreakoutStrategy(Strategy):
    """
    Breakout Strategy.
    Identifies consolidation periods and trades breakouts.
    Buys when price breaks above resistance.
    Sells when price breaks below support.
    """
    
    def __init__(self, config: dict = None):
        """Initialize Breakout strategy."""
        super().__init__("breakout", config)
        
        # Strategy parameters
        self.consolidation_period = config.get('consolidation_period', 20) if config else 20
        self.breakout_threshold_pips = config.get('breakout_threshold_pips', 20) if config else 20
        self.min_consolidation_pips = config.get('min_consolidation_pips', 10) if config else 10
    
    def generate_signal(self, data: pd.DataFrame) -> Signal:
        """Generate breakout signal with volume confirmation and improved filtering."""
        if len(data) < self.consolidation_period + 10:
            return Signal.HOLD
        
        try:
            # Get recent price range
            recent_high = data['high'].iloc[-self.consolidation_period:].max()
            recent_low = data['low'].iloc[-self.consolidation_period:].min()
            
            # Check if consolidation exists
            consolidation_range = (recent_high - recent_low) / 0.0001  # Convert to pips
            
            if consolidation_range < self.min_consolidation_pips:
                return Signal.HOLD  # Not consolidated enough
            
            # Get current price and volume
            current_price = data['close'].iloc[-1]
            current_volume = data.get('volume', pd.Series([100000] * len(data))).iloc[-1]
            
            # **IMPROVED:** Stricter entry requirements
            # Entry must be 0.3% from extreme (vs original 0.5%)
            strict_high_threshold = recent_high * 0.997
            strict_low_threshold = recent_low * 1.003
            
            # **IMPROVED:** Volume confirmation (100k minimum)
            min_volume = 100000
            volume_ok = current_volume > min_volume
            
            # Breakout threshold
            breakout_distance = self.consolidation_period * 0.0001
            
            # Check for upside breakout with volume
            if (current_price >= strict_high_threshold and
                volume_ok and
                current_price > recent_high + breakout_distance):
                logger.debug("Breakout Buy Signal (Improved)",
                           price=current_price,
                           resistance=recent_high,
                           range=consolidation_range,
                           volume=current_volume)
                return Signal.BUY
            
            # Check for downside breakout with volume
            elif (current_price <= strict_low_threshold and
                  volume_ok and
                  current_price < recent_low - breakout_distance):
                logger.debug("Breakout Sell Signal (Improved)",
                           price=current_price,
                           support=recent_low,
                           range=consolidation_range,
                           volume=current_volume)
                return Signal.SELL
            
            return Signal.HOLD
        
        except Exception as e:
            logger.error(f"Error in breakout signal generation: {e}")
            return Signal.HOLD
    
    def calculate_stop_loss(self, entry_price: float, direction: str,
                           data: pd.DataFrame) -> float:
        """Stop loss at opposite side of consolidation."""
        if len(data) < self.consolidation_period:
            if direction.upper() == "BUY":
                return entry_price - 0.01
            else:
                return entry_price + 0.01
        
        try:
            recent_high = data['high'].iloc[-self.consolidation_period:].max()
            recent_low = data['low'].iloc[-self.consolidation_period:].min()
            
            # Add buffer
            buffer = (recent_high - recent_low) * 0.1
            
            if direction.upper() == "BUY":
                return recent_low - buffer
            else:
                return recent_high + buffer
        
        except Exception as e:
            logger.error(f"Error calculating SL: {e}")
            if direction.upper() == "BUY":
                return entry_price - 0.01
            else:
                return entry_price + 0.01
    
    def calculate_take_profit(self, entry_price: float, direction: str,
                             data: pd.DataFrame) -> float:
        """Take profit based on breakout magnitude."""
        if len(data) < self.consolidation_period:
            if direction.upper() == "BUY":
                return entry_price + 0.02
            else:
                return entry_price - 0.02
        
        try:
            recent_high = data['high'].iloc[-self.consolidation_period:].max()
            recent_low = data['low'].iloc[-self.consolidation_period:].min()
            breakout_distance = recent_high - recent_low
            
            if direction.upper() == "BUY":
                return entry_price + (breakout_distance * 0.75)
            else:
                return entry_price - (breakout_distance * 0.75)
        
        except Exception as e:
            logger.error(f"Error calculating TP: {e}")
            if direction.upper() == "BUY":
                return entry_price + 0.02
            else:
                return entry_price - 0.02
