"""
Reversal Exit Detector
Identifies reversal patterns and triggers exits to avoid giving back gains
"""

import logging
from dataclasses import dataclass
from typing import Tuple, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class ReversalType(Enum):
    """Types of reversals that trigger exits"""
    THREE_CANDLE_REVERSAL = "3-candle reversal pattern"
    OPPOSITE_SIGNAL = "opposite entry signal triggered"
    RSI_DIVERGENCE = "RSI divergence (bearish/bullish)"
    PRICE_ACTION = "price action rejection"
    MOMENTUM_LOSS = "momentum loss detected"


@dataclass
class ReversalExitConfig:
    """Configuration for reversal-based exits"""
    enable_3candle_reversal: bool = True      # 3-candle reversal pattern
    enable_opposite_signal: bool = True       # Opposite signal triggered
    enable_rsi_divergence: bool = True        # RSI divergence
    enable_price_action: bool = True          # Price rejection
    enable_momentum_loss: bool = True         # Momentum loss
    
    reversal_confirmation_candles: int = 1    # Candles to confirm (1 = immediate)
    rsi_threshold: int = 50                   # RSI midpoint for divergence
    momentum_threshold: float = 0.0            # Momentum level threshold


class ReversalExitDetector:
    """
    Detects reversal patterns and signals exits
    
    Features:
    - 3-candle reversal pattern detection
    - Opposite signal exit triggers
    - RSI divergence detection
    - Price action rejection detection
    - Momentum loss detection
    
    Example:
    ```python
    config = ReversalExitConfig(
        enable_3candle_reversal=True,
        enable_opposite_signal=True,
        enable_rsi_divergence=True,
    )
    
    detector = ReversalExitDetector(config)
    
    # On each candle close
    should_exit, reversal_type, reason = detector.should_exit_on_reversal(
        current_candle={'open': 1.1000, 'high': 1.1050, 'low': 1.0950, 'close': 1.1000},
        previous_candles=[...],
        rsi_values=[...],
        trade_direction='LONG',
    )
    
    if should_exit:
        print(f"Exit: {reason}")
        await close_trade()
    ```
    """
    
    def __init__(self, config: ReversalExitConfig = None):
        """Initialize reversal detector"""
        self.config = config or ReversalExitConfig()
        
        logger.info("Reversal Exit Detector initialized")
        logger.info(f"  3-candle reversal: {self.config.enable_3candle_reversal}")
        logger.info(f"  Opposite signal: {self.config.enable_opposite_signal}")
        logger.info(f"  RSI divergence: {self.config.enable_rsi_divergence}")
        logger.info(f"  Price action: {self.config.enable_price_action}")
        logger.info(f"  Momentum loss: {self.config.enable_momentum_loss}")
    
    def should_exit_on_reversal(
        self,
        current_candle: dict,
        previous_candles: list,
        trade_direction: str,
        rsi_values: list = None,
        momentum_values: list = None,
        opposite_signal_triggered: bool = False,
    ) -> Tuple[bool, Optional[ReversalType], str]:
        """
        Check if a reversal pattern indicates trade exit
        
        Args:
            current_candle: Current OHLCV candle
            previous_candles: List of previous candles
            trade_direction: 'LONG' or 'SHORT'
            rsi_values: List of RSI values (most recent last)
            momentum_values: List of momentum values
            opposite_signal_triggered: Whether opposite signal was generated
            
        Returns:
            (should_exit, reversal_type, reason)
        """
        
        # Check 3-candle reversal
        if self.config.enable_3candle_reversal:
            is_reversal = self.detect_3candle_reversal(
                current_candle,
                previous_candles,
                trade_direction,
            )
            if is_reversal:
                reason = f"3-candle {trade_direction} reversal detected"
                logger.warning(f"[REVERSAL_EXIT] {reason}")
                return True, ReversalType.THREE_CANDLE_REVERSAL, reason
        
        # Check opposite signal
        if self.config.enable_opposite_signal and opposite_signal_triggered:
            reason = f"Opposite signal triggered ({self._get_opposite_direction(trade_direction)})"
            logger.warning(f"[REVERSAL_EXIT] {reason}")
            return True, ReversalType.OPPOSITE_SIGNAL, reason
        
        # Check RSI divergence
        if self.config.enable_rsi_divergence and rsi_values:
            is_divergence = self.detect_rsi_divergence(
                current_candle,
                previous_candles,
                rsi_values,
                trade_direction,
            )
            if is_divergence:
                reason = f"RSI divergence detected ({trade_direction})"
                logger.warning(f"[REVERSAL_EXIT] {reason}")
                return True, ReversalType.RSI_DIVERGENCE, reason
        
        # Check price action rejection
        if self.config.enable_price_action:
            is_rejection = self.detect_price_action_rejection(
                current_candle,
                previous_candles,
                trade_direction,
            )
            if is_rejection:
                reason = f"Price action rejection detected"
                logger.warning(f"[REVERSAL_EXIT] {reason}")
                return True, ReversalType.PRICE_ACTION, reason
        
        # Check momentum loss
        if self.config.enable_momentum_loss and momentum_values:
            momentum_lost = self.detect_momentum_loss(
                momentum_values,
                trade_direction,
            )
            if momentum_lost:
                reason = f"Momentum loss detected"
                logger.warning(f"[REVERSAL_EXIT] {reason}")
                return True, ReversalType.MOMENTUM_LOSS, reason
        
        return False, None, ""
    
    def detect_3candle_reversal(
        self,
        current_candle: dict,
        previous_candles: list,
        trade_direction: str,
    ) -> bool:
        """
        Detect 3-candle reversal pattern
        
        LONG reversal: 3 candles with
        - First: bullish (close > open)
        - Second: bullish (continues up)
        - Third: bearish engulfing (close < second open)
        
        SHORT reversal: 3 candles with opposite pattern
        """
        
        if not previous_candles or len(previous_candles) < 2:
            return False
        
        c2 = previous_candles[-2]  # Second-to-last candle
        c1 = previous_candles[-1]  # Last candle
        c0 = current_candle        # Current candle
        
        if trade_direction == 'LONG':
            # Bullish trend breaks with bearish candle
            is_bullish_1 = c2['close'] > c2['open']
            is_bullish_2 = c1['close'] > c1['open']
            is_bearish_3 = c0['close'] < c0['open']
            
            # Confirmation: Third candle closes below second's open
            engulfing = c0['close'] < c1['open']
            
            return is_bullish_1 and is_bullish_2 and is_bearish_3 and engulfing
        
        else:  # SHORT
            # Bearish trend breaks with bullish candle
            is_bearish_1 = c2['close'] < c2['open']
            is_bearish_2 = c1['close'] < c1['open']
            is_bullish_3 = c0['close'] > c0['open']
            
            # Confirmation: Third candle closes above second's open
            engulfing = c0['close'] > c1['open']
            
            return is_bearish_1 and is_bearish_2 and is_bullish_3 and engulfing
    
    def detect_rsi_divergence(
        self,
        current_candle: dict,
        previous_candles: list,
        rsi_values: list,
        trade_direction: str,
    ) -> bool:
        """
        Detect RSI divergence (price makes new high/low but RSI doesn't)
        
        LONG bearish divergence: Price higher, RSI lower
        SHORT bullish divergence: Price lower, RSI higher
        """
        
        if len(rsi_values) < 3:
            return False
        
        if len(previous_candles) < 1:
            return False
        
        prev_candle = previous_candles[-1]
        rsi_current = rsi_values[-1]
        rsi_previous = rsi_values[-2]
        
        if trade_direction == 'LONG':
            # Bearish divergence: price higher but RSI lower
            price_higher = current_candle['high'] > prev_candle['high']
            rsi_lower = rsi_current < rsi_previous
            rsi_weak = rsi_current < (50 + self.config.rsi_threshold)
            
            return price_higher and rsi_lower and rsi_weak
        
        else:  # SHORT
            # Bullish divergence: price lower but RSI higher
            price_lower = current_candle['low'] < prev_candle['low']
            rsi_higher = rsi_current > rsi_previous
            rsi_strong = rsi_current > (50 - self.config.rsi_threshold)
            
            return price_lower and rsi_higher and rsi_strong
    
    def detect_price_action_rejection(
        self,
        current_candle: dict,
        previous_candles: list,
        trade_direction: str,
    ) -> bool:
        """
        Detect price action rejection (wide wick rejection)
        
        LONG rejection: High wick up, closes near low
        SHORT rejection: Low wick down, closes near high
        """
        
        if not current_candle:
            return False
        
        current = current_candle
        range_size = current['high'] - current['low']
        
        if range_size == 0:
            return False
        
        if trade_direction == 'LONG':
            # Upper wick rejection
            upper_wick = current['high'] - current['close']
            body_size = current['close'] - current['open']
            
            # Large upper wick (> 60% of range) with small/negative body
            wick_ratio = upper_wick / range_size
            return wick_ratio > 0.6 and body_size <= 0
        
        else:  # SHORT
            # Lower wick rejection
            lower_wick = current['open'] - current['low']
            body_size = current['open'] - current['close']
            
            # Large lower wick (> 60% of range) with small/negative body
            wick_ratio = lower_wick / range_size
            return wick_ratio > 0.6 and body_size <= 0
    
    def detect_momentum_loss(
        self,
        momentum_values: list,
        trade_direction: str,
    ) -> bool:
        """
        Detect momentum loss (momentum turning against trade)
        
        LONG: Positive momentum turning negative
        SHORT: Negative momentum turning positive
        """
        
        if len(momentum_values) < 2:
            return False
        
        current_momentum = momentum_values[-1]
        previous_momentum = momentum_values[-2]
        
        if trade_direction == 'LONG':
            # Momentum was positive, now negative or zero
            was_positive = previous_momentum > 0
            now_nonpositive = current_momentum <= 0
            return was_positive and now_nonpositive
        
        else:  # SHORT
            # Momentum was negative, now positive or zero
            was_negative = previous_momentum < 0
            now_nonnegative = current_momentum >= 0
            return was_negative and now_nonnegative
    
    @staticmethod
    def _get_opposite_direction(direction: str) -> str:
        """Get opposite trade direction"""
        return 'SHORT' if direction == 'LONG' else 'LONG'


# Preset configurations

CONSERVATIVE_REVERSAL_CONFIG = ReversalExitConfig(
    enable_3candle_reversal=True,
    enable_opposite_signal=True,
    enable_rsi_divergence=True,
    enable_price_action=True,
    enable_momentum_loss=True,
    reversal_confirmation_candles=1,
)

MODERATE_REVERSAL_CONFIG = ReversalExitConfig(
    enable_3candle_reversal=True,
    enable_opposite_signal=True,
    enable_rsi_divergence=True,
    enable_price_action=True,
    enable_momentum_loss=False,  # Less sensitive
    reversal_confirmation_candles=1,
)

AGGRESSIVE_REVERSAL_CONFIG = ReversalExitConfig(
    enable_3candle_reversal=True,
    enable_opposite_signal=False,  # Only hard reversals
    enable_rsi_divergence=False,
    enable_price_action=True,
    enable_momentum_loss=False,
    reversal_confirmation_candles=2,  # Require confirmation
)
