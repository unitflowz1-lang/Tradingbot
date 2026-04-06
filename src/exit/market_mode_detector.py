"""
Market Mode Detector
Identifies current market mode (Breakout/Bounce/Range) for adaptive trading
"""

import logging
from dataclasses import dataclass
from typing import Optional
from enum import Enum

logger = logging.getLogger(__name__)


class MarketMode(Enum):
    """Current market trading mode"""
    BREAKOUT = "High volatility breakout mode"   # Strong trend, wider moves
    BOUNCE = "Normal volatility bounce mode"     # Moderate moves
    RANGE = "Low volatility range mode"          # Tight, consolidated moves


@dataclass
class MarketModeConfig:
    """Configuration for market mode detection"""
    # Volatility thresholds (in percentile)
    high_volatility_percentile: float = 0.80      # Top 20% = high vol
    low_volatility_percentile: float = 0.20       # Bottom 20% = low vol
    
    # Trend strength thresholds (ADX)
    strong_trend_adx: float = 25.0                # ADX > 25 = strong trend
    weak_trend_adx: float = 15.0                  # ADX < 15 = weak trend
    
    # Range detection
    lookback_bars: int = 20                       # Bars to check for range
    range_threshold: float = 0.002                # Range as % of price
    
    # Mode persistence
    min_bars_in_mode: int = 5                     # Minimum candles in mode


class MarketModeDetector:
    """
    Detects current market mode for adaptive position sizing and exits
    
    Modes:
    1. BREAKOUT - High volatility, strong trend
       - Characteristics: ATR high, ADX > 25, directional moves
       - Strategy: Larger positions, wider stops, 3R targets
       
    2. BOUNCE - Normal volatility, moderate trend
       - Characteristics: ATR normal, ADX 15-25, mixed moves
       - Strategy: Normal positions, normal stops, 2R targets
       
    3. RANGE - Low volatility, choppy market
       - Characteristics: ATR low, ADX < 15, bound moves
       - Strategy: Smaller positions, tight stops, 1.5R targets
    
    Example:
    ```python
    detector = MarketModeDetector()
    
    mode = detector.detect_market_mode(
        volatility_regime='HIGH_VOL',
        trend_strength=30.0,  # ADX value
        recent_range=0.003,   # As % of price
    )
    
    if mode == MarketMode.BREAKOUT:
        tp_multiplier = 3.0
        sl_multiplier = 0.5
    elif mode == MarketMode.BOUNCE:
        tp_multiplier = 2.0
        sl_multiplier = 1.0
    else:  # RANGE
        tp_multiplier = 1.5
        sl_multiplier = 0.75
    ```
    """
    
    def __init__(self, config: MarketModeConfig = None):
        """Initialize market mode detector"""
        self.config = config or MarketModeConfig()
        self.current_mode = MarketMode.BOUNCE
        self.bars_in_current_mode = 0
        
        logger.info("Market Mode Detector initialized")
        logger.info(f"  High vol threshold: {self.config.high_volatility_percentile*100:.0f}th percentile")
        logger.info(f"  Low vol threshold: {self.config.low_volatility_percentile*100:.0f}th percentile")
        logger.info(f"  Strong trend ADX: > {self.config.strong_trend_adx}")
        logger.info(f"  Weak trend ADX: < {self.config.weak_trend_adx}")
    
    def detect_market_mode(
        self,
        volatility_regime: str = 'NORMAL_VOL',
        trend_strength: float = 20.0,
        recent_range: float = 0.001,
        atr_percentile: Optional[float] = None,
    ) -> MarketMode:
        """
        Detect current market mode
        
        Args:
            volatility_regime: 'LOW_VOL', 'NORMAL_VOL', or 'HIGH_VOL'
            trend_strength: ADX value (0-100)
            recent_range: Recent price range as % of price
            atr_percentile: ATR percentile (0-1) if available
            
        Returns:
            Current MarketMode
        """
        
        # Volatility classification
        if volatility_regime == 'HIGH_VOL' or (atr_percentile and atr_percentile > self.config.high_volatility_percentile):
            vol_signal = 'HIGH'
        elif volatility_regime == 'LOW_VOL' or (atr_percentile and atr_percentile < self.config.low_volatility_percentile):
            vol_signal = 'LOW'
        else:
            vol_signal = 'NORMAL'
        
        # Trend classification
        if trend_strength > self.config.strong_trend_adx:
            trend_signal = 'STRONG'
        elif trend_strength < self.config.weak_trend_adx:
            trend_signal = 'WEAK'
        else:
            trend_signal = 'MEDIUM'
        
        # Range classification
        is_range_bound = recent_range < self.config.range_threshold
        
        # Determine mode based on signals
        if vol_signal == 'HIGH' and trend_signal == 'STRONG':
            mode = MarketMode.BREAKOUT
            logger.info(f"[MARKET_MODE] BREAKOUT: High vol + Strong trend (ADX={trend_strength:.1f})")
        
        elif vol_signal == 'LOW' or (trend_signal == 'WEAK' and is_range_bound):
            mode = MarketMode.RANGE
            logger.info(f"[MARKET_MODE] RANGE: Low vol or weak trend + range-bound")
        
        else:
            mode = MarketMode.BOUNCE
            logger.debug(f"[MARKET_MODE] BOUNCE: Normal conditions")
        
        # Update mode persistence tracker
        if mode == self.current_mode:
            self.bars_in_current_mode += 1
        else:
            logger.info(f"[MODE_CHANGE] {self.current_mode.name} → {mode.name}")
            self.current_mode = mode
            self.bars_in_current_mode = 1
        
        return mode
    
    def get_tp_multiplier(self, market_mode: MarketMode = None) -> float:
        """
        Get take profit multiplier for current market mode
        
        Args:
            market_mode: MarketMode (uses current if not provided)
            
        Returns:
            Risk multiplier for take profit (e.g., 2.0 = 2R)
        """
        mode = market_mode or self.current_mode
        
        multipliers = {
            MarketMode.BREAKOUT: 3.0,    # Wider moves in breakouts
            MarketMode.BOUNCE: 2.0,      # Normal moves
            MarketMode.RANGE: 1.5,       # Tight moves in ranges
        }
        
        return multipliers.get(mode, 2.0)
    
    def get_sl_multiplier(self, market_mode: MarketMode = None) -> float:
        """
        Get stop loss multiplier for current market mode
        
        Args:
            market_mode: MarketMode (uses current if not provided)
            
        Returns:
            Risk multiplier for stop loss (e.g., 0.5 = 0.5R)
        """
        mode = market_mode or self.current_mode
        
        multipliers = {
            MarketMode.BREAKOUT: 0.5,    # Tight SL in breakouts
            MarketMode.BOUNCE: 1.0,      # Normal SL
            MarketMode.RANGE: 0.75,      # Medium SL in ranges
        }
        
        return multipliers.get(mode, 1.0)
    
    def get_position_multiplier(self, market_mode: MarketMode = None) -> float:
        """
        Get position size multiplier for current market mode
        
        Args:
            market_mode: MarketMode (uses current if not provided)
            
        Returns:
            Position multiplier (1.0 = base, 1.2 = 20% larger, 0.8 = 20% smaller)
        """
        mode = market_mode or self.current_mode
        
        multipliers = {
            MarketMode.BREAKOUT: 1.2,    # Slightly larger in breakouts
            MarketMode.BOUNCE: 1.0,      # Base size
            MarketMode.RANGE: 0.8,       # Smaller in ranges (lower confidence)
        }
        
        return multipliers.get(mode, 1.0)
    
    def get_mode_summary(self) -> dict:
        """
        Get detailed summary of current mode
        
        Returns:
            Dict with mode details
        """
        return {
            'mode': self.current_mode.name,
            'description': self.current_mode.value,
            'bars_in_mode': self.bars_in_current_mode,
            'tp_multiplier': self.get_tp_multiplier(),
            'sl_multiplier': self.get_sl_multiplier(),
            'position_multiplier': self.get_position_multiplier(),
        }


# Mode determination helper function

def determine_market_mode(
    volatility: float,          # ATR or volatility measure
    volatility_avg: float,      # Average volatility
    volatility_std: float,      # Std dev of volatility
    trend_strength: float,      # ADX value
    config: MarketModeConfig = None,
) -> MarketMode:
    """
    Determine market mode using statistical approach
    
    Args:
        volatility: Current volatility measure
        volatility_avg: Average volatility over period
        volatility_std: Standard deviation of volatility
        trend_strength: ADX value
        config: MarketModeConfig
        
    Returns:
        MarketMode
    """
    
    cfg = config or MarketModeConfig()
    
    # Z-score of volatility
    if volatility_std > 0:
        vol_zscore = (volatility - volatility_avg) / volatility_std
    else:
        vol_zscore = 0
    
    # Volatility classification
    if vol_zscore > 1.0:
        vol_class = 'HIGH'
    elif vol_zscore < -1.0:
        vol_class = 'LOW'
    else:
        vol_class = 'NORMAL'
    
    # Trend classification
    if trend_strength > cfg.strong_trend_adx:
        trend_class = 'STRONG'
    elif trend_strength < cfg.weak_trend_adx:
        trend_class = 'WEAK'
    else:
        trend_class = 'MEDIUM'
    
    # Mode determination
    if vol_class == 'HIGH' and trend_class == 'STRONG':
        return MarketMode.BREAKOUT
    elif vol_class == 'LOW' or trend_class == 'WEAK':
        return MarketMode.RANGE
    else:
        return MarketMode.BOUNCE


# Preset configurations

CONSERVATIVE_MODE_CONFIG = MarketModeConfig(
    high_volatility_percentile=0.75,   # Top 25% (stricter)
    low_volatility_percentile=0.25,    # Bottom 25%
    strong_trend_adx=30.0,             # Stricter trend requirement
    weak_trend_adx=20.0,
)

MODERATE_MODE_CONFIG = MarketModeConfig(
    high_volatility_percentile=0.80,   # Default
    low_volatility_percentile=0.20,
    strong_trend_adx=25.0,
    weak_trend_adx=15.0,
)

AGGRESSIVE_MODE_CONFIG = MarketModeConfig(
    high_volatility_percentile=0.85,   # Top 15% (less strict)
    low_volatility_percentile=0.15,    # Bottom 15%
    strong_trend_adx=20.0,             # More relaxed
    weak_trend_adx=10.0,
)
