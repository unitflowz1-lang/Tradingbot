"""
Advanced Risk Management Module.
Comprehensive position sizing, stop loss, take profit, and portfolio protection.
"""

from dataclasses import dataclass
from typing import Dict, Optional, Tuple
from enum import Enum
from abc import ABC, abstractmethod
import numpy as np
from utils.logger import get_logger


logger = get_logger(__name__)


class PositionSizingMethod(str, Enum):
    """Position sizing methods."""
    FIXED = "fixed"
    EQUITY_RISK = "equity_risk"
    ATR_BASED = "atr_based"
    KELLY = "kelly"


class StopLossMethod(str, Enum):
    """Stop loss calculation methods."""
    FIXED = "fixed"
    ATR_BASED = "atr"
    VOLATILITY_BASED = "volatility"
    CHANDELIER = "chandelier"


@dataclass
class PositionSize:
    """Position size details."""
    quantity: float
    lot_size: float
    margin_required: float
    risk_amount: float


@dataclass
class RiskLevels:
    """Risk/reward levels for a trade."""
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_distance: float
    reward_distance: float
    risk_reward_ratio: float


class RiskManager:
    """
    Advanced risk management system.
    Handles position sizing, stops, profit targets, and portfolio protection.
    """
    
    def __init__(self, initial_capital: float, risk_config):
        """
        Initialize RiskManager.
        
        Args:
            initial_capital: Starting capital
            risk_config: Risk configuration
        """
        self.initial_capital = initial_capital
        self.current_equity = initial_capital
        self.risk_config = risk_config
        
        # Track daily losses
        self.daily_losses: Dict[str, float] = {}
        
        # Track maximum equity for drawdown
        self.peak_equity = initial_capital
    
    def calculate_position_size(self, symbol: str, entry_price: float,
                               stop_loss: float, current_atr: Optional[float] = None,
                               current_volatility: Optional[float] = None,
                               win_rate: Optional[float] = None) -> PositionSize:
        """
        Calculate position size based on configured method.
        **IMPROVED:** Includes volatility-adjusted risk scaling.
        
        Args:
            symbol: Trading symbol
            entry_price: Entry price
            stop_loss: Stop loss price
            current_atr: Current ATR value
            current_volatility: Current volatility (%)
            win_rate: Historical win rate for Kelly
        
        Returns:
            PositionSize object
        """
        method = self.risk_config.position_sizing
        
        # **IMPROVED:** Calculate volatility adjustment factor
        volatility_multiplier = 1.0
        if current_volatility is not None:
            # Normalize to "normal" volatility of 1.0%
            vol_ratio = current_volatility / 1.0
            
            if vol_ratio > 2.0:  # Extreme volatility
                volatility_multiplier = 0.5  # 50% position size
            elif vol_ratio > 1.5:  # High volatility
                volatility_multiplier = 0.667  # 66.7% position size
            elif vol_ratio > 1.0:  # Elevated volatility
                volatility_multiplier = 0.85  # 85% position size
            # else: volatility_multiplier = 1.0 (normal conditions)
        
        if method == PositionSizingMethod.FIXED:
            return self._fixed_position_size()
        
        elif method == PositionSizingMethod.EQUITY_RISK:
            return self._equity_risk_position_size(entry_price, stop_loss,
                                                   volatility_multiplier)
        
        elif method == PositionSizingMethod.ATR_BASED:
            if current_atr is None:
                raise ValueError("ATR required for ATR-based sizing")
            return self._atr_position_size(entry_price, stop_loss, current_atr,
                                          volatility_multiplier)
        
        elif method == PositionSizingMethod.KELLY:
            if win_rate is None:
                raise ValueError("Win rate required for Kelly sizing")
            return self._kelly_position_size(entry_price, stop_loss, win_rate,
                                            volatility_multiplier)
        
        else:
            return self._fixed_position_size()
    
    def _fixed_position_size(self) -> PositionSize:
        """Fixed lot size positioning."""
        lot_size = self.risk_config.fixed_lot
        qty = lot_size * 100000  # Convert lots to units
        margin = qty * 0.01 * self.current_equity  # Estimate margin (varies by broker)
        
        return PositionSize(
            quantity=qty,
            lot_size=lot_size,
            margin_required=margin,
            risk_amount=self.current_equity * self.risk_config.equity_risk_percent / 100
        )
    
    def _equity_risk_position_size(self, entry_price: float, stop_loss: float,
                                   volatility_multiplier: float = 1.0) -> PositionSize:
        """Equity risk percentage sizing with volatility adjustment."""
        # **IMPROVED:** Scale risk by volatility
        adjusted_risk = self.risk_config.equity_risk_percent * volatility_multiplier
        risk_amount = self.current_equity * (adjusted_risk / 100)
        
        # Calculate pip distance
        pip_distance = abs(entry_price - stop_loss) / 0.0001
        
        if pip_distance == 0:
            pip_distance = 1  # Prevent division by zero
        
        # Calculate position size
        # Risk amount = quantity * pip_distance * 0.0001
        quantity = risk_amount / (pip_distance * 0.0001)
        
        # Convert to standard lots (0.01 lot = 1000 units)
        lot_size = quantity / 100000
        margin = lot_size * self.current_equity * 0.01
        
        return PositionSize(
            quantity=quantity,
            lot_size=lot_size,
            margin_required=margin,
            risk_amount=risk_amount
        )
    
    def _atr_position_size(self, entry_price: float, stop_loss: float,
                          current_atr: float, volatility_multiplier: float = 1.0) -> PositionSize:
        """ATR-based position sizing with volatility adjustment."""
        # Use ATR instead of actual stop loss distance
        atr_distance = current_atr * self.risk_config.atr_multiple / 0.0001
        
        # **IMPROVED:** Scale risk by volatility
        adjusted_risk = self.risk_config.equity_risk_percent * volatility_multiplier
        risk_amount = self.current_equity * (adjusted_risk / 100)
        quantity = risk_amount / (atr_distance * 0.0001)
        lot_size = quantity / 100000
        margin = lot_size * self.current_equity * 0.01
        
        return PositionSize(
            quantity=quantity,
            lot_size=lot_size,
            margin_required=margin,
            risk_amount=risk_amount
        )
    
    def _kelly_position_size(self, entry_price: float, stop_loss: float,
                            win_rate: float, volatility_multiplier: float = 1.0) -> PositionSize:
        """Kelly Criterion position sizing with volatility adjustment."""
        # Kelly % = (bp - q) / b
        # b = reward/risk ratio
        # p = win probability
        # q = loss probability (1-p)
        
        risk_pips = abs(entry_price - stop_loss) / 0.0001
        
        # Average reward/risk (assume 2:1)
        reward_pips = risk_pips * 2
        b = reward_pips / risk_pips
        
        p = win_rate / 100
        q = 1 - p
        
        kelly_pct = ((b * p) - q) / b
        kelly_pct = max(0.01, min(kelly_pct, 0.10))  # Clamp between 1% and 10%
        
        # **IMPROVED:** Scale Kelly by volatility multiplier
        kelly_pct *= volatility_multiplier
        
        risk_amount = self.current_equity * kelly_pct
        quantity = risk_amount / (risk_pips * 0.0001)
        lot_size = quantity / 100000
        margin = lot_size * self.current_equity * 0.01
        
        return PositionSize(
            quantity=quantity,
            lot_size=lot_size,
            margin_required=margin,
            risk_amount=risk_amount
        )
    
    def calculate_stops_and_targets(self, entry_price: float, direction: str,
                                   current_atr: Optional[float] = None,
                                   current_volatility: Optional[float] = None) -> RiskLevels:
        """
        Calculate stop loss and take profit levels.
        **IMPROVED:** Volatility-adjusted ATR multiplier for dynamic stop placement.
        
        Args:
            entry_price: Entry price
            direction: BUY or SELL
            current_atr: Current ATR
            current_volatility: Current volatility (%)
        
        Returns:
            RiskLevels object
        """
        sl_method = self.risk_config.sl_type
        tp_method = self.risk_config.tp_type
        
        # **IMPROVED:** Calculate volatility-adjusted ATR multiplier
        atr_multiplier = self.risk_config.atr_multiple  # Default 1.5
        
        if current_volatility is not None:
            vol_ratio = current_volatility / 1.0  # Normalize to 1% normal volatility
            
            if vol_ratio > 2.0:  # Extreme volatility
                atr_multiplier = 2.5  # Wider stops
            elif vol_ratio > 1.5:  # High volatility
                atr_multiplier = 2.0  # Medium-wide stops
            # else: use default 1.5x ATR
        
        # Calculate stop loss
        if sl_method == StopLossMethod.FIXED:
            sl_pips = self.risk_config.atr_multiple * 100  # Default pips
        elif sl_method == StopLossMethod.ATR_BASED:
            if current_atr is None:
                sl_pips = 50  # Default
            else:
                # **IMPROVED:** Use volatility-adjusted multiplier
                sl_pips = (current_atr * atr_multiplier) / 0.0001
        else:
            sl_pips = 50
        
        # Calculate take profit
        if tp_method == StopLossMethod.FIXED:
            tp_pips = sl_pips * self.risk_config.tp_multiple
        elif tp_method == StopLossMethod.ATR_BASED:
            tp_pips = sl_pips * self.risk_config.tp_multiple
        else:
            tp_pips = sl_pips * 2
        
        # Convert pips to prices
        if direction.upper() == "BUY":
            stop_loss = entry_price - (sl_pips * 0.0001)
            take_profit = entry_price + (tp_pips * 0.0001)
        else:
            stop_loss = entry_price + (sl_pips * 0.0001)
            take_profit = entry_price - (tp_pips * 0.0001)
        
        return RiskLevels(
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            risk_distance=abs(entry_price - stop_loss),
            reward_distance=abs(take_profit - entry_price),
            risk_reward_ratio=abs(take_profit - entry_price) / abs(entry_price - stop_loss)
                             if abs(entry_price - stop_loss) != 0 else 0
        )
    
    def calculate_trailing_stop(self, current_price: float, entry_price: float,
                               direction: str, highest_price: float = None,
                               lowest_price: float = None,
                               current_atr: Optional[float] = None) -> float:
        """
        Calculate dynamic trailing stop price.
        
        Args:
            current_price: Current market price
            entry_price: Entry price
            direction: BUY or SELL
            highest_price: Highest price reached
            lowest_price: Lowest price reached
            current_atr: Current ATR for ATR-based trailing
        
        Returns:
            Recalculated stop loss price
        """
        if not self.risk_config.trailing_stop:
            return None
        
        if direction.upper() == "BUY":
            if highest_price is None:
                highest_price = current_price
            
            # Move stop loss up as price increases
            trailing_distance = (current_atr * self.risk_config.trailing_stop_atr / 0.0001) \
                               if current_atr else 50  # Default 50 pips
            
            new_stop = highest_price - (trailing_distance * 0.0001)
            # Stop should not go below entry
            return max(new_stop, entry_price)
        
        else:  # SELL
            if lowest_price is None:
                lowest_price = current_price
            
            trailing_distance = (current_atr * self.risk_config.trailing_stop_atr / 0.0001) \
                               if current_atr else 50
            
            new_stop = lowest_price + (trailing_distance * 0.0001)
            # Stop should not go below entry price
            return min(new_stop, entry_price)
    
    def check_daily_loss_limit(self, current_daily_loss: float) -> bool:
        """Check if daily loss limit is exceeded."""
        max_daily_loss = self.current_equity * self.risk_config.max_daily_loss
        
        if current_daily_loss > max_daily_loss:
            logger.warning("Daily loss limit exceeded",
                         current_loss=current_daily_loss,
                         max_loss=max_daily_loss)
            return False
        
        return True
    
    def check_drawdown_limit(self, current_equity: float) -> bool:
        """Check if maximum drawdown limit is exceeded."""
        self.peak_equity = max(self.peak_equity, current_equity)
        
        drawdown = (self.peak_equity - current_equity) / self.peak_equity
        max_drawdown = self.risk_config.max_drawdown
        
        if drawdown > max_drawdown:
            logger.warning("Maximum drawdown exceeded",
                         current_drawdown=drawdown,
                         max_drawdown=max_drawdown)
            return False
        
        return True
    
    def check_max_open_trades(self, current_open_trades: int) -> bool:
        """Check if max open trades limit is exceeded."""
        if current_open_trades >= self.risk_config.max_open_trades:
            logger.warning("Max open trades limit reached",
                         current=current_open_trades,
                         max=self.risk_config.max_open_trades)
            return False
        
        return True
    
    def calculate_breakeven_stop(self, entry_price: float, direction: str,
                                current_price: float, breakeven_buffer_pips: float = 5) -> Optional[float]:
        """
        Calculate break-even stop price.
        
        Args:
            entry_price: Original entry price
            direction: BUY or SELL
            current_price: Current market price
            breakeven_buffer_pips: Buffer above/below entry for break-even
        
        Returns:
            Break-even stop price if trade is in profit
        """
        buffer = breakeven_buffer_pips * 0.0001
        
        if direction.upper() == "BUY":
            if current_price > entry_price:
                return entry_price + buffer
        else:
            if current_price < entry_price:
                return entry_price - buffer
        
        return None
    
    def calculate_partial_profits(self, entry_price: float, current_price: float,
                                 direction: str, quantity: float) -> Dict[str, Tuple[float, float]]:
        """
        Calculate partial profit-taking levels and quantities.
        
        Args:
            entry_price: Entry price
            current_price: Current price
            direction: BUY or SELL
            quantity: Total position quantity
        
        Returns:
            Dict mapping levels to (quantity, price) to close
        """
        partial_points = self.risk_config.partial_profit_points or [0.5, 0.75, 1.0]
        partials = {}
        
        for i, point in enumerate(partial_points):
            # Use take profit calculation as base
            tp = self._calculate_take_profit_level(entry_price, direction, point)
            
            # Quantity to close at this level
            qty_to_close = quantity * (point if i == 0 else point - partial_points[i-1])
            
            partials[f"partial_{i+1}"] = (qty_to_close, tp)
        
        return partials
    
    def _calculate_take_profit_level(self, entry_price: float, direction: str,
                                     level: float) -> float:
        """Calculate profit level (0.0 to 1.0)."""
        # Default profit target: 2% of entry
        tp_pips = 200 * level
        
        if direction.upper() == "BUY":
            return entry_price + (tp_pips * 0.0001)
        else:
            return entry_price - (tp_pips * 0.0001)
    
    def update_equity(self, new_equity: float):
        """Update current equity and peak tracking."""
        self.current_equity = new_equity
        self.peak_equity = max(self.peak_equity, new_equity)
