"""
Mean Reversion Strategy.
Trades based on Bollinger Bands and RSI oversold/overbought conditions.
"""

import pandas as pd
import numpy as np
from core.strategy_manager import Strategy, Signal
from utils.logger import get_logger


logger = get_logger(__name__)


class MeanReversionStrategy(Strategy):
    """
    Mean Reversion Strategy.
    Uses Bollinger Bands and RSI for mean reversion signals.
    Buys when price touches lower band and RSI is oversold.
    Sells when price touches upper band and RSI is overbought.
    """
    
    def __init__(self, config: dict = None):
        """Initialize Mean Reversion strategy."""
        super().__init__("mean_reversion", config)
        
        # Bollinger Bands parameters
        self.bb_period = config.get('bb_period', 20) if config else 20
        self.bb_std = config.get('bb_std', 2.0) if config else 2.0
        
        # RSI parameters
        self.rsi_period = config.get('rsi_period', 14) if config else 14
        self.rsi_oversold = config.get('rsi_oversold', 25) if config else 25
        self.rsi_overbought = config.get('rsi_overbought', 70) if config else 70
    
    def generate_signal(self, data: pd.DataFrame) -> Signal:
        """Generate mean reversion signal with improved filtering."""
        if len(data) < max(self.bb_period, self.rsi_period) + 5:
            return Signal.HOLD
        
        try:
            # Calculate Bollinger Bands
            close = data['close']
            sma = close.rolling(window=self.bb_period).mean()
            std = close.rolling(window=self.bb_period).std()
            
            upper_band = sma + (std * self.bb_std)
            lower_band = sma - (std * self.bb_std)
            
            # Calculate RSI
            rsi = self._calculate_rsi(close, self.rsi_period)
            
            # Get current values
            current_price = close.iloc[-1]
            current_rsi = rsi.iloc[-1]
            current_upper = upper_band.iloc[-1]
            current_lower = lower_band.iloc[-1]
            current_sma = sma.iloc[-1]
            
            if pd.isna(current_rsi) or pd.isna(current_upper):
                return Signal.HOLD
            
            # **IMPROVED:** Stricter mean reversion detection
            range_size = current_upper - current_lower
            
            # Buy signal: price near lower band (20% vs 25%) AND RSI oversold
            if (current_price < (current_lower + range_size * 0.20) and
                current_rsi < self.rsi_oversold and
                range_size > 0.0002):  # Require volatility
                logger.debug("Mean Reversion Buy Signal (Improved)",
                           price=current_price,
                           lower_band=current_lower,
                           rsi=current_rsi,
                           distance_from_band=current_price-current_lower)
                return Signal.BUY
            
            # Sell signal: price near upper band (20% vs 25%) AND RSI overbought
            elif (current_price > (current_upper - range_size * 0.20) and
                  current_rsi > self.rsi_overbought and
                  range_size > 0.0002):
                logger.debug("Mean Reversion Sell Signal (Improved)",
                           price=current_price,
                           upper_band=current_upper,
                           rsi=current_rsi,
                           distance_from_band=current_upper-current_price)
                return Signal.SELL
            
            return Signal.HOLD
        
        except Exception as e:
            logger.error(f"Error in mean reversion signal generation: {e}")
            return Signal.HOLD
    
    def calculate_stop_loss(self, entry_price: float, direction: str,
                           data: pd.DataFrame) -> float:
        """Stop loss at opposite Bollinger Band."""
        if len(data) < self.bb_period:
            if direction.upper() == "BUY":
                return entry_price - 0.01
            else:
                return entry_price + 0.01
        
        try:
            close = data['close']
            sma = close.rolling(window=self.bb_period).mean()
            std = close.rolling(window=self.bb_period).std()
            
            upper_band = sma + (std * self.bb_std)
            lower_band = sma - (std * self.bb_std)
            
            if direction.upper() == "BUY":
                # Stop at lower band
                return lower_band.iloc[-1]
            else:
                # Stop at upper band
                return upper_band.iloc[-1]
        
        except Exception as e:
            logger.error(f"Error calculating SL: {e}")
            if direction.upper() == "BUY":
                return entry_price - 0.01
            else:
                return entry_price + 0.01
    
    def calculate_take_profit(self, entry_price: float, direction: str,
                             data: pd.DataFrame) -> float:
        """Take profit at middle band (SMA)."""
        if len(data) < self.bb_period:
            if direction.upper() == "BUY":
                return entry_price + 0.01
            else:
                return entry_price - 0.01
        
        try:
            close = data['close']
            sma = close.rolling(window=self.bb_period).mean()
            
            # Slight buffer beyond SMA
            buffer = 0.0005
            
            if direction.upper() == "BUY":
                return sma.iloc[-1] + buffer
            else:
                return sma.iloc[-1] - buffer
        
        except Exception as e:
            logger.error(f"Error calculating TP: {e}")
            if direction.upper() == "BUY":
                return entry_price + 0.01
            else:
                return entry_price - 0.01
    
    def _calculate_rsi(self, prices: pd.Series, period: int = 14) -> pd.Series:
        """Calculate RSI indicator."""
        delta = prices.diff()
        gains = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        losses = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        
        rs = gains / losses
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
