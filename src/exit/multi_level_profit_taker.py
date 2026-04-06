"""
Multi-Level Profit Taking System
Exits trades in tiers to capture extended moves while locking in gains
"""

import logging
from dataclasses import dataclass, field
from typing import List, Tuple, Optional

logger = logging.getLogger(__name__)


@dataclass
class ProfitLevel:
    """Single profit level definition"""
    profit_target: float        # e.g., 0.5 = 0.5R (half risk)
    exit_percentage: int        # Percentage of position to exit (20-100)
    comment: str               # Label for this level (e.g., "Quick Profit")
    
    def __post_init__(self):
        """Validate profit level"""
        if not 0 < self.profit_target <= 3.0:
            raise ValueError(f"profit_target must be 0-3.0R, got {self.profit_target}")
        if not 0 <= self.exit_percentage <= 100:
            raise ValueError(f"exit_percentage must be 0-100, got {self.exit_percentage}")


@dataclass
class MultiLevelConfig:
    """Configuration for multi-level profit taking"""
    levels: List[ProfitLevel] = field(
        default_factory=lambda: [
            ProfitLevel(0.5, 20, "Quick Profit"),      # Exit 20% at +0.5R
            ProfitLevel(1.0, 35, "Half Position"),     # Exit 35% at +1.0R
            ProfitLevel(1.5, 30, "Lock Gains"),        # Exit 30% at +1.5R
            ProfitLevel(2.0, 0, "Trail Remaining"),    # Trail remaining 15%
        ]
    )
    trailing_distance_pips: int = 30      # Trail distance in pips
    trailing_only_upward: bool = True     # Only move stops upward (for LONG)
    min_position_size: float = 0.01       # Minimum position size
    
    def __post_init__(self):
        """Validate configuration"""
        if not self.levels:
            raise ValueError("Must have at least one profit level")
        
        total_exit_pct = sum(level.exit_percentage for level in self.levels[:-1])
        if total_exit_pct > 100:
            raise ValueError(f"Total exit percentage {total_exit_pct}% exceeds 100%")


class MultiLevelProfitTaker:
    """
    Manages multi-level profit taking for trades
    
    Features:
    - Exit portions of position at predefined profit levels
    - Trail remaining position after hitting profit targets
    - Track which levels have been hit
    - Calculate remaining position size
    
    Example:
    ```python
    config = MultiLevelConfig(
        levels=[
            ProfitLevel(0.5, 20, "Quick Profit"),
            ProfitLevel(1.0, 35, "Half Position"),
            ProfitLevel(1.5, 30, "Lock Gains"),
            ProfitLevel(2.0, 0, "Trail Remaining"),
        ]
    )
    
    taker = MultiLevelProfitTaker(config)
    
    # On each price tick
    profit_level, exit_pct = taker.should_take_profit(
        current_price=1.1000,
        entry_price=1.0950,
        stop_loss=1.0850,
    )
    
    if profit_level:
        print(f"Exit {exit_pct}% at {profit_level.comment}")
        await close_partial(exit_pct)
    ```
    """
    
    def __init__(self, config: MultiLevelConfig = None):
        """Initialize profit taker"""
        self.config = config or MultiLevelConfig()
        self.triggered_level_indices = set()  # Track which level indices were hit
        
        logger.info("Multi-Level Profit Taker initialized")
        for i, level in enumerate(self.config.levels):
            logger.info(
                f"  Level {i+1}: {level.comment} | "
                f"TP: {level.profit_target:.1f}R | "
                f"Exit: {level.exit_percentage}% | "
                f"Remaining: {100-sum(l.exit_percentage for l in self.config.levels[:i+1])}%"
            )
    
    def should_take_profit(
        self,
        current_price: float,
        entry_price: float,
        stop_loss: float,
        direction: str = 'LONG',
        trade_id: str = None,
    ) -> Tuple[Optional[ProfitLevel], Optional[int]]:
        """
        Check if any profit level should be triggered
        
        Args:
            current_price: Current market price
            entry_price: Trade entry price
            stop_loss: Current stop loss price
            direction: Trade direction ('LONG' or 'SHORT')
            trade_id: Trade ID for logging
            
        Returns:
            (ProfitLevel, exit_percentage) if triggered, else (None, None)
        """
        
        # Calculate risk and profit
        risk = abs(entry_price - stop_loss)
        
        if direction == 'LONG':
            profit = current_price - entry_price
        else:  # SHORT
            profit = entry_price - current_price
        
        if profit <= 0:
            return None, None  # No profit yet
        
        profit_multiple = profit / risk if risk > 0 else 0
        
        # Check each level in order
        for i, level in enumerate(self.config.levels):
            if i in self.triggered_level_indices:
                continue  # Already triggered this level
            
            if profit_multiple >= level.profit_target:
                # Profit level triggered!
                self.triggered_level_indices.add(i)
                
                logger.info(
                    f"[PROFIT_LEVEL] {trade_id or 'TRADE'} | "
                    f"{direction} | "
                    f"Profit: {profit_multiple:.2f}R (>= {level.profit_target}R) | "
                    f"Exit: {level.exit_percentage}% | {level.comment}"
                )
                
                return level, level.exit_percentage
        
        return None, None
    
    def calculate_tp_price(
        self,
        entry_price: float,
        risk: float,
        profit_multiple: float,
        direction: str = 'LONG',
    ) -> float:
        """
        Calculate take profit price for a given R multiple
        
        Args:
            entry_price: Trade entry price
            risk: Risk amount (stop loss distance)
            profit_multiple: Number of Rs to target (e.g., 1.0, 1.5, 2.0)
            direction: Trade direction ('LONG' or 'SHORT')
            
        Returns:
            TP price for the given multiple
        """
        target_profit = risk * profit_multiple
        
        if direction == 'LONG':
            tp_price = entry_price + target_profit
        else:  # SHORT
            tp_price = entry_price - target_profit
        
        return tp_price
    
    def get_remaining_position(self) -> float:
        """
        Calculate percentage of position remaining to exit/trail
        
        Returns:
            Remaining position percentage (0-100)
        """
        exited_pct = sum(
            self.config.levels[i].exit_percentage
            for i in self.triggered_level_indices
        )
        remaining = 100 - exited_pct
        return max(0, remaining)
    
    def get_triggered_levels(self) -> List[Tuple[ProfitLevel, int]]:
        """
        Get all triggered profit levels with exit percentages
        
        Returns:
            List of (ProfitLevel, exit_percentage) tuples
        """
        return [
            (self.config.levels[i], self.config.levels[i].exit_percentage)
            for i in sorted(self.triggered_level_indices)
        ]
    
    def reset_for_new_trade(self):
        """Reset triggered levels for a new trade"""
        self.triggered_level_indices.clear()
        logger.debug("Profit taker reset for new trade")
    
    def get_trailing_configuration(self) -> dict:
        """
        Get configuration for trailing the remaining position
        
        Returns:
            Dict with trailing configuration
        """
        remaining_pct = self.get_remaining_position()
        
        if remaining_pct <= 0:
            return {}
        
        return {
            'remaining_percentage': remaining_pct,
            'trailing_distance_pips': self.config.trailing_distance_pips,
            'trailing_only_upward': self.config.trailing_only_upward,
        }
    
    def summary(self) -> str:
        """Get summary of profit taking status"""
        exited_pct = sum(
            self.config.levels[i].exit_percentage
            for i in self.triggered_level_indices
        )
        remaining = 100 - exited_pct
        
        summary_lines = [
            f"Profit Taking Status:",
            f"  Levels Triggered: {len(self.triggered_level_indices)}/{len(self.config.levels)}",
            f"  Position Exited: {exited_pct}%",
            f"  Position Remaining: {remaining}%",
        ]
        
        if self.triggered_level_indices:
            summary_lines.append("  Exits:")
            for i in sorted(self.triggered_level_indices):
                level = self.config.levels[i]
                summary_lines.append(f"    - {level.comment}: {level.exit_percentage}%")
        
        return "\n".join(summary_lines)


# Preset configurations for different strategies

CONSERVATIVE_PROFIT_CONFIG = MultiLevelConfig(
    levels=[
        ProfitLevel(0.3, 15, "Early Exit"),     # Take small gains early
        ProfitLevel(0.7, 30, "Scale Out"),
        ProfitLevel(1.2, 35, "Lock Profits"),
        ProfitLevel(1.8, 0, "Trail Rest"),
    ],
    trailing_distance_pips=20,
)

MODERATE_PROFIT_CONFIG = MultiLevelConfig(
    levels=[
        ProfitLevel(1.5, 50, "TP1 Securing 50%"),    # securing 50% at 1.5R
        ProfitLevel(2.5, 25, "TP2 Securing 25%"),    # securing 25% at 2.5R
        ProfitLevel(3.0, 0, "Runner Trail"),         # Final 25% Runner
    ],
    trailing_distance_pips=40,
)

AGGRESSIVE_PROFIT_CONFIG = MultiLevelConfig(
    levels=[
        ProfitLevel(0.7, 15, "Breakeven Pass"),  # Let winners run longer
        ProfitLevel(1.2, 25, "Scale Out"),
        ProfitLevel(1.8, 35, "Lock Profits"),
        ProfitLevel(2.5, 0, "Trail Rest"),
    ],
    trailing_distance_pips=40,
)
