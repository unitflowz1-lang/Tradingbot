"""
SMA Crossover Strategy.
Generates signals from simple moving average crossovers.
"""

import pandas as pd
import numpy as np
from core.strategy_manager import Strategy, Signal
from utils.logger import get_logger


logger = get_logger(__name__)


class SMAStrategy(Strategy):
    """
    SMA Crossover Strategy.
    Buys when fast SMA crosses above slow SMA.
    Sells when fast SMA crosses below slow SMA.
    """
    
    def __init__(self, config: dict = None):
        """Initialize SMA strategy."""
        super().__init__("sma_crossover", config)
        
        # Strategy parameters
        self.fast_period = config.get('fast_period', 20) if config else 20
        self.slow_period = config.get('slow_period', 50) if config else 50
        self.min_pips_apart = config.get('min_pips_apart', 10) if config else 10
        
        # State tracking
        self.last_signal = Signal.HOLD
        self.crossover_price = 0
    
    def generate_signal(self, data: pd.DataFrame) -> Signal:
        """Generate SMA crossover signal with improved filtering."""
        if len(data) < self.slow_period + 5:
            return Signal.HOLD
        
        try:
            # Calculate SMAs
            fast_sma = data['close'].rolling(window=self.fast_period).mean()
            slow_sma = data['close'].rolling(window=self.slow_period).mean()
            
            if len(fast_sma) < 2:
                return Signal.HOLD
            
            # Current and previous values
            fast_current = fast_sma.iloc[-1]
            fast_previous = fast_sma.iloc[-2]
            slow_current = slow_sma.iloc[-1]
            slow_previous = slow_sma.iloc[-2]
            
            # Check for NaN
            if pd.isna(fast_current) or pd.isna(slow_current):
                return Signal.HOLD
            
            # **IMPROVED:** Additional confirmation filters
            current_price = data['close'].iloc[-1]
            previous_price = data['close'].iloc[-2]
            open_price = data['open'].iloc[-1]
            high = data['high'].iloc[-1]
            low = data['low'].iloc[-1]
            
            # Calculate range and move metrics
            range_size = high - low
            range_pct = range_size / low if low > 0 else 0
            price_move = abs(current_price - previous_price) / previous_price if previous_price > 0 else 0
            close_position = (current_price - low) / range_size if range_size > 0 else 0.5
            
            # Bullish crossover: fast crosses above slow
            if (fast_previous < slow_previous) and (fast_current > slow_current):
                # **IMPROVED:** Require 0.4% move (vs 0.2%) + narrow range (< 0.8%)
                if price_move >= 0.004 and range_pct < 0.008 and close_position > 0.6:
                    self.last_signal = Signal.BUY
                    self.crossover_price = current_price
                    logger.debug("SMA Bullish Crossover (Improved)",
                               fast=fast_current,
                               slow=slow_current,
                               price=self.crossover_price,
                               move_pct=price_move*100,
                               range_pct=range_pct*100)
                    return Signal.BUY
            
            # Bearish crossover: fast crosses below slow
            elif (fast_previous > slow_previous) and (fast_current < slow_current):
                # **IMPROVED:** Require 0.4% move + narrow range + close near bottom
                if price_move >= 0.004 and range_pct < 0.008 and close_position < 0.4:
                    self.last_signal = Signal.SELL
                    self.crossover_price = current_price
                    logger.debug("SMA Bearish Crossover (Improved)",
                               fast=fast_current,
                               slow=slow_current,
                               price=self.crossover_price,
                               move_pct=price_move*100,
                               range_pct=range_pct*100)
                    return Signal.SELL
            
            # Current signal persists until opposite signal
            elif self.last_signal != Signal.HOLD:
                return self.last_signal
            
            return Signal.HOLD
        
        except Exception as e:
            logger.error(f"Error in SMA signal generation: {e}")
            return Signal.HOLD
    
    def calculate_stop_loss(self, entry_price: float, direction: str,
                           data: pd.DataFrame) -> float:
        """
        Calculate stop loss based on recent support/resistance.
        **IMPROVED:** Uses volatility-adjusted ATR multiplier.
        """
        if len(data) < 20:
            if direction.upper() == "BUY":
                return entry_price - 0.0050
            else:
                return entry_price + 0.0050
        
        try:
            # Calculate ATR
            high = data['high'].iloc[-20:]
            low = data['low'].iloc[-20:]
            close = data['close'].iloc[-20:]
            
            tr1 = high - low
            tr2 = abs(high - close.shift(1))
            tr3 = abs(low - close.shift(1))
            
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            atr = tr.mean()
            
            # **IMPROVED:** Volatility-adjusted ATR multiplier
            volatility = data['close'].pct_change().std() * 100  # Volatility as %
            
            if volatility > 2.0:  # Extreme volatility
                atr_multiplier = 2.5  # Wider stops
            elif volatility > 1.5:  # High volatility
                atr_multiplier = 2.0  # Medium-wide stops
            else:  # Normal conditions
                atr_multiplier = 1.5  # Standard stops
            
            # Stop loss is volatility-adjusted ATR away
            if direction.upper() == "BUY":
                return entry_price - (atr * atr_multiplier)
            else:
                return entry_price + (atr * atr_multiplier)
        
        except Exception as e:
            logger.error(f"Error calculating SL: {e}")
            if direction.upper() == "BUY":
                return entry_price - 0.0050
            else:
                return entry_price + 0.0050
    
    def calculate_take_profit(self, entry_price: float, direction: str,
                             data: pd.DataFrame) -> float:
        """Take profit at 2:1 risk-reward ratio."""
        sl = self.calculate_stop_loss(entry_price, direction, data)
        risk_distance = abs(entry_price - sl)
        
        if direction.upper() == "BUY":
            return entry_price + (risk_distance * 2)
        else:
            return entry_price - (risk_distance * 2)
    
    def validate_trade(self, signal: Signal, data: pd.DataFrame) -> bool:
        """Validate trade before execution."""
        if signal == Signal.HOLD:
            return False
        
        # Ensure signal is recent (within last 2 candles)
        if len(data) > 2:
            return True
        
        return False
