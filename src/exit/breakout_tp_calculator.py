"""
Breakout Profit Target Calculator
Calculates mode-adaptive take profit and stop loss levels
"""

import logging
from dataclasses import dataclass
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class BreakoutTargets:
    """Calculated targets for a trade"""
    entry_price: float
    take_profit: float
    stop_loss: float
    risk: float
    reward: float
    risk_reward_ratio: float
    mode: str


@dataclass
class BreakoutTPConfig:
    """Configuration for breakout-mode take profit calculation"""
    
    # Breakout Mode (High Volatility) - Wider moves expected
    breakout_tp_multiplier: float = 3.0      # 3R target
    breakout_sl_multiplier: float = 0.5      # 0.5R stop
    breakout_min_atr: float = 0.001          # Minimum ATR for breakout mode
    
    # Bounce Mode (Normal Volatility) - Normal moves
    bounce_tp_multiplier: float = 2.0        # 2R target
    bounce_sl_multiplier: float = 1.0        # 1R stop
    
    # Range Mode (Low Volatility) - Tight moves
    range_tp_multiplier: float = 1.5         # 1.5R target
    range_sl_multiplier: float = 0.75        # 0.75R stop
    range_max_atr: float = 0.0005            # Maximum ATR for range mode
    
    # Risk management caps
    max_tp_multiplier: float = 4.0            # Never target > 4R
    min_tp_multiplier: float = 1.0            # Never target < 1R
    max_sl_multiplier: float = 2.0            # Never risk > 2R
    min_sl_multiplier: float = 0.25           # Never risk < 0.25R


class BreakoutTPCalculator:
    """
    Calculates take profit and stop loss based on market mode and volatility
    
    Features:
    - Mode-adaptive targets (Breakout/Bounce/Range)
    - ATR-based calculations
    - Risk-reward ratio optimization
    - Trailing stop support
    - Dynamic adjustments based on market conditions
    
    Example:
    ```python
    calc = BreakoutTPCalculator()
    
    targets = calc.calculate_targets(
        entry_price=1.0950,
        direction='LONG',
        atr=0.005,
        market_mode='BREAKOUT',
        volatility_regime='HIGH_VOL',
    )
    
    print(f"TP: {targets.take_profit:.5f}")
    print(f"SL: {targets.stop_loss:.5f}")
    print(f"R:R: {targets.risk_reward_ratio:.2f}")
    ```
    """
    
    def __init__(self, config: BreakoutTPConfig = None):
        """Initialize calculator"""
        self.config = config or BreakoutTPConfig()
        
        logger.info("Breakout TP Calculator initialized")
        logger.info(f"  Breakout: TP={self.config.breakout_tp_multiplier:.1f}R, SL={self.config.breakout_sl_multiplier:.1f}R")
        logger.info(f"  Bounce: TP={self.config.bounce_tp_multiplier:.1f}R, SL={self.config.bounce_sl_multiplier:.1f}R")
        logger.info(f"  Range: TP={self.config.range_tp_multiplier:.1f}R, SL={self.config.range_sl_multiplier:.1f}R")
    
    def calculate_targets(
        self,
        entry_price: float,
        direction: str,
        atr: float = None,
        market_mode: str = 'BOUNCE',
        volatility_regime: str = 'NORMAL_VOL',
        base_stop_loss: float = None,
    ) -> BreakoutTargets:
        """
        Calculate take profit and stop loss for a trade
        
        Args:
            entry_price: Trade entry price
            direction: 'LONG' or 'SHORT'
            atr: Current ATR value (optional, used for mode detection)
            market_mode: 'BREAKOUT', 'BOUNCE', or 'RANGE'
            volatility_regime: 'LOW_VOL', 'NORMAL_VOL', or 'HIGH_VOL'
            base_stop_loss: Pre-calculated hard stop (if provided, use it)
            
        Returns:
            BreakoutTargets with TP, SL, and R:R ratio
        """
        
        # Get multipliers for mode
        tp_mult = self._get_tp_multiplier(market_mode, volatility_regime)
        sl_mult = self._get_sl_multiplier(market_mode, volatility_regime)
        
        logger.debug(
            f"Mode: {market_mode} | "
            f"Vol: {volatility_regime} | "
            f"TP: {tp_mult:.1f}R | "
            f"SL: {sl_mult:.1f}R"
        )
        
        # If base SL provided, calculate risk from it
        if base_stop_loss:
            risk = abs(entry_price - base_stop_loss)
        else:
            # Use ATR if provided
            if atr:
                risk = atr * 1.5  # Default hard stop
            else:
                logger.warning("No ATR or base_stop_loss provided, using entry as reference")
                risk = entry_price * 0.01  # 1% as fallback
        
        # Calculate TP
        if direction == 'LONG':
            take_profit = entry_price + (risk * tp_mult)
            stop_loss = base_stop_loss or (entry_price - (risk * sl_mult))
        else:  # SHORT
            take_profit = entry_price - (risk * tp_mult)
            stop_loss = base_stop_loss or (entry_price + (risk * sl_mult))
        
        # Validate and adjust if needed
        take_profit, stop_loss = self._validate_targets(
            entry_price, take_profit, stop_loss, direction
        )
        
        # Calculate final risk-reward ratio
        actual_risk = abs(entry_price - stop_loss)
        actual_reward = abs(take_profit - entry_price)
        rr_ratio = actual_reward / actual_risk if actual_risk > 0 else 0
        
        return BreakoutTargets(
            entry_price=entry_price,
            take_profit=take_profit,
            stop_loss=stop_loss,
            risk=actual_risk,
            reward=actual_reward,
            risk_reward_ratio=rr_ratio,
            mode=market_mode,
        )
    
    def calculate_tp_price(
        self,
        entry_price: float,
        direction: str,
        risk: float,
        market_mode: str = 'BOUNCE',
    ) -> float:
        """
        Calculate take profit price for given risk and mode
        
        Args:
            entry_price: Trade entry price
            direction: 'LONG' or 'SHORT'
            risk: Risk amount (stop loss distance)
            market_mode: 'BREAKOUT', 'BOUNCE', or 'RANGE'
            
        Returns:
            Take profit price
        """
        
        tp_mult = self._get_tp_multiplier(market_mode)
        profit = risk * tp_mult
        
        if direction == 'LONG':
            return entry_price + profit
        else:
            return entry_price - profit
    
    def calculate_sl_price(
        self,
        entry_price: float,
        direction: str,
        risk: float,
        market_mode: str = 'BOUNCE',
    ) -> float:
        """
        Calculate stop loss price for given risk and mode
        
        Args:
            entry_price: Trade entry price
            direction: 'LONG' or 'SHORT'
            risk: Maximum risk amount
            market_mode: 'BREAKOUT', 'BOUNCE', or 'RANGE'
            
        Returns:
            Stop loss price
        """
        
        sl_mult = self._get_sl_multiplier(market_mode)
        loss = risk * sl_mult
        
        if direction == 'LONG':
            return entry_price - loss
        else:
            return entry_price + loss
    
    def _get_tp_multiplier(
        self,
        market_mode: str,
        volatility_regime: str = 'NORMAL_VOL',
    ) -> float:
        """Get TP multiplier for mode with volatility adjustment"""
        
        if market_mode == 'BREAKOUT':
            base = self.config.breakout_tp_multiplier
        elif market_mode == 'RANGE':
            base = self.config.range_tp_multiplier
        else:  # BOUNCE
            base = self.config.bounce_tp_multiplier
        
        # Adjust for volatility
        if volatility_regime == 'HIGH_VOL':
            base *= 1.1  # +10% in high volatility
        elif volatility_regime == 'LOW_VOL':
            base *= 0.9  # -10% in low volatility
        
        # Enforce limits
        base = max(self.config.min_tp_multiplier, min(self.config.max_tp_multiplier, base))
        
        return base
    
    def _get_sl_multiplier(
        self,
        market_mode: str,
        volatility_regime: str = 'NORMAL_VOL',
    ) -> float:
        """Get SL multiplier for mode with volatility adjustment"""
        
        if market_mode == 'BREAKOUT':
            base = self.config.breakout_sl_multiplier
        elif market_mode == 'RANGE':
            base = self.config.range_sl_multiplier
        else:  # BOUNCE
            base = self.config.bounce_sl_multiplier
        
        # Adjust for volatility (opposite direction: high vol = wider stops)
        if volatility_regime == 'HIGH_VOL':
            base *= 1.2  # +20% wider in high volatility
        elif volatility_regime == 'LOW_VOL':
            base *= 0.8  # -20% tighter in low volatility
        
        # Enforce limits
        base = max(self.config.min_sl_multiplier, min(self.config.max_sl_multiplier, base))
        
        return base
    
    def _validate_targets(
        self,
        entry_price: float,
        take_profit: float,
        stop_loss: float,
        direction: str,
    ) -> Tuple[float, float]:
        """
        Validate that TP and SL are on correct sides of entry
        
        Args:
            entry_price: Entry price
            take_profit: Calculated TP
            stop_loss: Calculated SL
            direction: 'LONG' or 'SHORT'
            
        Returns:
            (validated_tp, validated_sl)
        """
        
        if direction == 'LONG':
            # For LONG: TP > Entry > SL
            if take_profit <= entry_price:
                logger.warning(f"Invalid LONG TP {take_profit:.5f} <= Entry {entry_price:.5f}")
                take_profit = entry_price + (entry_price * 0.01)  # 1% above entry
            
            if stop_loss >= entry_price:
                logger.warning(f"Invalid LONG SL {stop_loss:.5f} >= Entry {entry_price:.5f}")
                stop_loss = entry_price - (entry_price * 0.01)  # 1% below entry
        
        else:  # SHORT
            # For SHORT: Entry > TP > SL (inverted)
            if take_profit >= entry_price:
                logger.warning(f"Invalid SHORT TP {take_profit:.5f} >= Entry {entry_price:.5f}")
                take_profit = entry_price - (entry_price * 0.01)  # 1% below entry
            
            if stop_loss <= entry_price:
                logger.warning(f"Invalid SHORT SL {stop_loss:.5f} <= Entry {entry_price:.5f}")
                stop_loss = entry_price + (entry_price * 0.01)  # 1% above entry
        
        return take_profit, stop_loss


# Preset configurations

CONSERVATIVE_BREAKOUT_CONFIG = BreakoutTPConfig(
    breakout_tp_multiplier=2.5,        # More conservative
    breakout_sl_multiplier=0.75,       # Wider stop
    bounce_tp_multiplier=1.8,
    bounce_sl_multiplier=1.2,
    range_tp_multiplier=1.3,
    range_sl_multiplier=0.9,
)

MODERATE_BREAKOUT_CONFIG = BreakoutTPConfig(
    breakout_tp_multiplier=3.0,        # Default
    breakout_sl_multiplier=0.5,
    bounce_tp_multiplier=2.0,
    bounce_sl_multiplier=1.0,
    range_tp_multiplier=1.5,
    range_sl_multiplier=0.75,
)

AGGRESSIVE_BREAKOUT_CONFIG = BreakoutTPConfig(
    breakout_tp_multiplier=3.5,        # More aggressive
    breakout_sl_multiplier=0.4,        # Tighter stop
    bounce_tp_multiplier=2.3,
    bounce_sl_multiplier=0.8,
    range_tp_multiplier=1.8,
    range_sl_multiplier=0.6,
)
