"""
Advanced Stop Loss Strategy - Phase 2 Implementation
Implements 3-tier stop loss system with trailing and breakeven stops
"""

import logging
from typing import Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum


class StopLossType(Enum):
    """Types of stop loss"""
    HARD_STOP = "HARD_STOP"           # Absolute maximum loss
    TRAILING_STOP = "TRAILING_STOP"   # Follows price up
    BREAKEVEN_STOP = "BREAKEVEN_STOP" # Move to entry
    TIME_STOP = "TIME_STOP"           # Exit after time


@dataclass
class StopLossConfig:
    """Configuration for stop loss strategy"""
    # Hard stop: Maximum allowed loss in ATR multiples
    hard_stop_atr_multiple: float = 1.5  # 1.5 × ATR
    
    # Trailing stop: Activate after profit
    trailing_stop_activation_pips: float = 50  # +50 pips profit
    trailing_stop_distance_pips: float = 30     # Trail by 30 pips
    
    # Breakeven stop: Move to entry after profit
    breakeven_activation_pips: float = 30      # +30 pips profit
    
    # Time-based stop
    max_trade_duration_hours: float = 6.0      # Exit after 6 hours
    
    # General settings
    min_stop_distance_pips: float = 10          # Minimum SL distance
    use_adaptive_stops: bool = True             # Adapt to volatility


class StopLossManager:
    """
    Manages 3-tier stop loss system:
    1. Hard Stop: ATR × 1.5 (absolute limit)
    2. Trailing Stop: Activates after +50 pips
    3. Breakeven Stop: Activates after +30 pips
    """
    
    def __init__(self, config: StopLossConfig = None):
        """Initialize stop loss manager"""
        self.config = config or StopLossConfig()
        self.logger = logging.getLogger(f"[STOP_LOSS_MANAGER]")
        self.logger.info(f"Advanced Stop Loss Manager initialized")
        
        # Track active stops per trade
        self.active_stops: Dict[str, Dict] = {}
    
    def calculate_hard_stop(
        self,
        entry_price: float,
        direction: str,
        atr: float,
        volatility_regime: str = 'NORMAL_VOL',
    ) -> float:
        """
        Calculate hard stop loss (absolute maximum)
        
        Args:
            entry_price: Entry price
            direction: 'LONG' or 'SHORT'
            atr: Average True Range value
            volatility_regime: Market volatility
            
        Returns:
            Hard stop price
        """
        # Adapt hard stop to volatility
        atr_multiplier = self.config.hard_stop_atr_multiple
        
        if volatility_regime == 'HIGH_VOL':
            atr_multiplier *= 1.3  # Wider stops for high volatility
        elif volatility_regime == 'LOW_VOL':
            atr_multiplier *= 0.9  # Tighter stops for low volatility
        
        distance = atr * atr_multiplier
        
        if direction == 'LONG':
            hard_stop = entry_price - distance
        else:  # SHORT
            hard_stop = entry_price + distance
        
        self.logger.info(
            f"[HARD_STOP] {direction} | Entry: {entry_price:.5f} | "
            f"SL: {hard_stop:.5f} | Distance: {distance:.5f} ({atr_multiplier:.1f}x ATR)"
        )
        
        return hard_stop
    
    def should_activate_trailing_stop(
        self,
        current_price: float,
        entry_price: float,
        direction: str,
    ) -> bool:
        """
        Check if trailing stop should activate
        
        Args:
            current_price: Current price
            entry_price: Entry price
            direction: 'LONG' or 'SHORT'
            
        Returns:
            True if trailing stop should activate
        """
        profit_pips = self._calculate_profit_pips(
            current_price, entry_price, direction
        )
        return profit_pips >= self.config.trailing_stop_activation_pips
    
    def calculate_trailing_stop(
        self,
        current_price: float,
        direction: str,
        current_stop: float,
    ) -> float:
        """
        Calculate trailing stop (follows price up)
        
        Args:
            current_price: Current price
            direction: 'LONG' or 'SHORT'
            current_stop: Current stop loss level
            
        Returns:
            Updated stop loss price
        """
        distance = self.config.trailing_stop_distance_pips / 10000  # Convert to decimal
        
        if direction == 'LONG':
            # For long, trail below current price
            new_stop = current_price - distance
            # Only move stop up, never down
            if new_stop > current_stop:
                self.logger.info(
                    f"[TRAILING_STOP] LONG | Current: {current_price:.5f} | "
                    f"New SL: {new_stop:.5f} | Trail: {distance:.5f}"
                )
                return new_stop
        else:  # SHORT
            # For short, trail above current price
            new_stop = current_price + distance
            # Only move stop down, never up
            if new_stop < current_stop:
                self.logger.info(
                    f"[TRAILING_STOP] SHORT | Current: {current_price:.5f} | "
                    f"New SL: {new_stop:.5f} | Trail: {distance:.5f}"
                )
                return new_stop
        
        return current_stop
    
    def should_activate_breakeven_stop(
        self,
        current_price: float,
        entry_price: float,
        direction: str,
    ) -> bool:
        """
        Check if breakeven stop should activate
        
        Args:
            current_price: Current price
            entry_price: Entry price
            direction: 'LONG' or 'SHORT'
            
        Returns:
            True if breakeven stop should activate
        """
        profit_pips = self._calculate_profit_pips(
            current_price, entry_price, direction
        )
        return profit_pips >= self.config.breakeven_activation_pips
    
    def calculate_breakeven_stop(
        self,
        entry_price: float,
        direction: str,
        breakeven_buffer_pips: float = 5,
    ) -> float:
        """
        Calculate breakeven stop (move to entry + buffer)
        
        Args:
            entry_price: Entry price
            direction: 'LONG' or 'SHORT'
            breakeven_buffer_pips: Buffer from entry (default 5 pips profit)
            
        Returns:
            Breakeven stop price
        """
        buffer = breakeven_buffer_pips / 10000
        
        if direction == 'LONG':
            breakeven_stop = entry_price + buffer
        else:  # SHORT
            breakeven_stop = entry_price - buffer
        
        self.logger.info(
            f"[BREAKEVEN_STOP] {direction} | Entry: {entry_price:.5f} | "
            f"BE Stop: {breakeven_stop:.5f} | Buffer: {breakeven_buffer_pips} pips"
        )
        
        return breakeven_stop
    
    def check_time_stop(
        self,
        entry_time_minutes: int,
        current_time_minutes: int,
    ) -> bool:
        """
        Check if trade should close due to time
        
        Args:
            entry_time_minutes: Entry time in minutes from session start
            current_time_minutes: Current time in minutes from session start
            
        Returns:
            True if time stop should close trade
        """
        trade_duration = current_time_minutes - entry_time_minutes
        max_duration = self.config.max_trade_duration_hours * 60
        
        if trade_duration >= max_duration:
            self.logger.info(
                f"[TIME_STOP] Trade open for {trade_duration:.0f} min (max: {max_duration:.0f} min) - Close"
            )
            return True
        
        return False
    
    def update_stop_loss(
        self,
        trade_id: str,
        current_price: float,
        entry_price: float,
        direction: str,
        current_stop: float,
        atr: float,
        volatility_regime: str = 'NORMAL_VOL',
    ) -> Tuple[float, str]:
        """
        Update stop loss based on current market condition
        
        Args:
            trade_id: Unique trade identifier
            current_price: Current market price
            entry_price: Trade entry price
            direction: 'LONG' or 'SHORT'
            current_stop: Current stop loss level
            atr: Average True Range
            volatility_regime: Market volatility
            
        Returns:
            Tuple of (new_stop_price, stop_type_used)
        """
        stop_type = None
        new_stop = current_stop
        
        # Check for hard stop violation (shouldn't happen, but safety check)
        hard_stop = self.calculate_hard_stop(entry_price, direction, atr, volatility_regime)
        
        if direction == 'LONG' and current_price < hard_stop:
            self.logger.warning(f"[HARD_STOP] Hard stop hit! Price {current_price:.5f} < SL {hard_stop:.5f}")
            return hard_stop, StopLossType.HARD_STOP.value
        elif direction == 'SHORT' and current_price > hard_stop:
            self.logger.warning(f"[HARD_STOP] Hard stop hit! Price {current_price:.5f} > SL {hard_stop:.5f}")
            return hard_stop, StopLossType.HARD_STOP.value
        
        # Check for trailing stop activation
        if self.should_activate_trailing_stop(current_price, entry_price, direction):
            new_stop = self.calculate_trailing_stop(current_price, direction, new_stop)
            stop_type = StopLossType.TRAILING_STOP.value
        
        # Check for breakeven activation (takes priority if higher profit)
        if self.should_activate_breakeven_stop(current_price, entry_price, direction):
            breakeven = self.calculate_breakeven_stop(entry_price, direction)
            
            # Use whichever is better
            if direction == 'LONG' and breakeven > new_stop:
                new_stop = breakeven
                stop_type = StopLossType.BREAKEVEN_STOP.value
            elif direction == 'SHORT' and breakeven < new_stop:
                new_stop = breakeven
                stop_type = StopLossType.BREAKEVEN_STOP.value
        
        # Store active stop info
        self.active_stops[trade_id] = {
            'current_stop': new_stop,
            'stop_type': stop_type,
            'last_updated': current_price,
        }
        
        return new_stop, stop_type or StopLossType.HARD_STOP.value
    
    def _calculate_profit_pips(
        self,
        current_price: float,
        entry_price: float,
        direction: str,
    ) -> float:
        """
        Calculate profit in pips
        
        Args:
            current_price: Current price
            entry_price: Entry price
            direction: 'LONG' or 'SHORT'
            
        Returns:
            Profit in pips
        """
        price_diff = current_price - entry_price
        
        if direction == 'SHORT':
            price_diff = -price_diff
        
        return price_diff * 10000  # Convert to pips


# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    manager = StopLossManager()
    
    # Example: LONG trade at 1.0950 with ATR of 0.0050
    hard_stop = manager.calculate_hard_stop(
        entry_price=1.0950,
        direction='LONG',
        atr=0.0050,
    )
    print(f"Hard Stop: {hard_stop:.5f}")
    
    # Simulate trade moving in profit
    current_price = 1.1000  # +50 pips profit
    new_stop, stop_type = manager.update_stop_loss(
        trade_id='EURUSD_001',
        current_price=current_price,
        entry_price=1.0950,
        direction='LONG',
        current_stop=hard_stop,
        atr=0.0050,
    )
    print(f"Updated Stop: {new_stop:.5f} (Type: {stop_type})")
