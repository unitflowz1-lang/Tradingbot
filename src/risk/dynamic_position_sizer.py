"""
Dynamic Position Sizer - Phase 2 Implementation
Adjusts position size based on signal quality and market volatility
"""

import logging
from typing import Dict, Tuple
from dataclasses import dataclass


@dataclass
class PositionSizingConfig:
    """Configuration for position sizing"""
    base_risk_pct: float = 2.0  # 2% base risk per trade
    min_position_size: float = 0.01  # Minimum lot size
    max_position_size: float = 1.0  # Maximum lot size
    account_balance: float = 10000.0  # Default account balance


class DynamicPositionSizer:
    """
    Dynamically adjusts position size based on:
    1. Signal Quality Score (0-100)
    2. Market Volatility Regime
    3. Account Risk Management
    """
    
    def __init__(self, config: PositionSizingConfig = None):
        """Initialize position sizer"""
        self.config = config or PositionSizingConfig()
        self.logger = logging.getLogger(f"[POSITION_SIZER]")
        self.logger.info(f"Dynamic Position Sizer initialized | Base Risk: {self.config.base_risk_pct}%")
    
    def get_quality_multiplier(self, signal_score: float) -> float:
        """
        Get position size multiplier based on signal quality
        
        Args:
            signal_score: Score from 0-100
            
        Returns:
            Multiplier for position size (0.5 to 1.5)
        """
        if signal_score >= 80:
            return 1.5  # Excellent signal: 150% of base
        elif signal_score >= 65:
            return 1.0  # Good signal: 100% of base
        elif signal_score >= 50:
            return 0.75  # Acceptable signal: 75% of base
        else:
            return 0.5  # Poor signal: 50% of base (shouldn't happen if Phase 1 filtering works)
    
    def get_volatility_multiplier(self, volatility_regime: str) -> float:
        """
        Get position size multiplier based on market volatility
        
        Args:
            volatility_regime: One of 'LOW_VOL', 'NORMAL_VOL', 'HIGH_VOL'
            
        Returns:
            Multiplier for position size (0.7 to 1.3)
        """
        volatility_multipliers = {
            'LOW_VOL': 1.2,      # Lower volatility = better risk/reward = larger position
            'NORMAL_VOL': 1.0,   # Normal volatility = standard position
            'HIGH_VOL': 0.8,     # High volatility = wider stops needed = smaller position
        }
        return volatility_multipliers.get(volatility_regime, 1.0)
    
    def get_trend_strength_multiplier(self, trend_strength: str) -> float:
        """
        Get position size multiplier based on trend strength
        
        Args:
            trend_strength: One of 'STRONG_TREND', 'WEAK_TREND', 'CHOPPY'
            
        Returns:
            Multiplier for position size
        """
        trend_multipliers = {
            'STRONG_TREND': 1.2,    # Strong trends = higher confidence
            'WEAK_TREND': 0.9,      # Weak trends = lower confidence
            'CHOPPY': 0.7,          # Choppy = avoid (but Phase 1 should skip this)
        }
        return trend_multipliers.get(trend_strength, 1.0)
    
    def calculate_position_size(
        self,
        signal_score: float,
        volatility_regime: str,
        trend_strength: str,
        account_balance: float = None,
        entry_price: float = None,
        stop_loss: float = None,
        shadow_positions_pl: float = 0.0,
    ) -> Tuple[float, Dict]:
        """
        Calculate optimal position size with all multipliers
        
        ===== PATCH #8: SHADOW POSITION VOLUME ACCOUNTING =====
        Account for unrealized losses from shadow positions when sizing new trades.
        
        Args:
            signal_score: Signal quality score (0-100)
            volatility_regime: Market volatility ('LOW_VOL', 'NORMAL_VOL', 'HIGH_VOL')
            trend_strength: Trend strength ('STRONG_TREND', 'WEAK_TREND', 'CHOPPY')
            account_balance: Account balance (defaults to config)
            entry_price: Entry price (for precise risk calculation)
            stop_loss: Stop loss price (for precise risk calculation)
            shadow_positions_pl: Total unrealized PnL from shadow positions (typically negative)
            
        Returns:
            Tuple of (position_size, details_dict)
        """
        balance = account_balance or self.config.account_balance
        
        # Adjust balance by shadow position losses
        adjusted_balance = balance + shadow_positions_pl  # PnL is negative for losses
        
        # If shadow positions consumed too much balance, scale back position size
        shadow_consumed_ratio = 1.0
        if shadow_positions_pl < 0:
            shadow_consumed_ratio = max(0.3, adjusted_balance / balance)  # Floor at 30% capacity
        
        # Calculate base position size from risk
        base_risk_amount = adjusted_balance * (self.config.base_risk_pct / 100.0)
        
        # Get individual multipliers
        quality_mult = self.get_quality_multiplier(signal_score)
        vol_mult = self.get_volatility_multiplier(volatility_regime)
        trend_mult = self.get_trend_strength_multiplier(trend_strength)
        
        # Combine multipliers (multiplicative approach for better balance)
        combined_multiplier = quality_mult * vol_mult * trend_mult
        
        # Apply shadow position scaling to combined multiplier
        combined_multiplier *= shadow_consumed_ratio
        
        # Calculate adjusted risk amount
        adjusted_risk = base_risk_amount * combined_multiplier
        
        # If we have entry and SL, calculate precise position size
        if entry_price is not None and stop_loss is not None:
            risk_per_pip = abs(entry_price - stop_loss)
            if risk_per_pip > 0:
                position_size = adjusted_risk / risk_per_pip
            else:
                position_size = self.config.min_position_size
        else:
            # Use simple multiplier approach
            base_position = adjusted_balance * 0.02 / 1000  # Default: ~0.02 lots for $10k account
            position_size = base_position * combined_multiplier
        
        # Enforce position size limits
        position_size = max(self.config.min_position_size, position_size)
        position_size = min(self.config.max_position_size, position_size)
        
        # Round to nearest 0.01
        position_size = round(position_size, 2)
        
        # Build details dictionary
        details = {
            'position_size': position_size,
            'base_risk_amount': base_risk_amount,
            'adjusted_risk_amount': adjusted_risk,
            'quality_score': signal_score,
            'quality_multiplier': quality_mult,
            'volatility_regime': volatility_regime,
            'volatility_multiplier': vol_mult,
            'trend_strength': trend_strength,
            'trend_multiplier': trend_mult,
            'combined_multiplier': combined_multiplier,
            'account_balance': balance,
            'adjusted_balance': adjusted_balance,
            'shadow_positions_pl': shadow_positions_pl,
            'shadow_consumed_ratio': shadow_consumed_ratio,
        }
        
        # Log the calculation
        self._log_position_sizing(details)
        
        return position_size, details
    
    def _log_position_sizing(self, details: Dict) -> None:
        """Log position sizing calculation"""
        log_msg = (
            f"Position Size: {details['position_size']:.2f} lots | "
            f"Quality: {details['quality_score']:.0f}/100 ({details['quality_multiplier']:.2f}x) | "
            f"Vol: {details['volatility_regime']} ({details['volatility_multiplier']:.2f}x) | "
            f"Trend: {details['trend_strength']} ({details['trend_multiplier']:.2f}x) | "
            f"Combined: {details['combined_multiplier']:.2f}x | "
            f"Risk: ${details['adjusted_risk_amount']:.2f}"
        )
        
        # Add shadow position info if present
        if 'shadow_positions_pl' in details and details['shadow_positions_pl'] < 0:
            log_msg += (
                f" | [SHADOW ACCOUNTING] Balance: ${details['account_balance']:.2f} → "
                f"${details['adjusted_balance']:.2f} "
                f"(PnL: ${details['shadow_positions_pl']:.2f}, Ratio: {details['shadow_consumed_ratio']:.2%})"
            )
        
        self.logger.info(log_msg)
    
    def adjust_for_drawdown(self, current_drawdown_pct: float, position_size: float) -> float:
        """
        Reduce position size if account is in drawdown
        
        Args:
            current_drawdown_pct: Current drawdown percentage
            position_size: Current position size
            
        Returns:
            Adjusted position size
        """
        if current_drawdown_pct < 5:
            return position_size  # No adjustment
        elif current_drawdown_pct < 10:
            return position_size * 0.9  # Reduce by 10%
        elif current_drawdown_pct < 15:
            return position_size * 0.75  # Reduce by 25%
        elif current_drawdown_pct < 20:
            return position_size * 0.5  # Reduce by 50%
        else:
            return position_size * 0.25  # Reduce by 75%


# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    sizer = DynamicPositionSizer(
        PositionSizingConfig(
            base_risk_pct=2.0,
            account_balance=10000.0,
        )
    )
    
    # Example: Excellent signal in normal volatility with strong trend
    pos_size, details = sizer.calculate_position_size(
        signal_score=85,
        volatility_regime='NORMAL_VOL',
        trend_strength='STRONG_TREND',
    )
    print(f"\nExcellent signal: {pos_size} lots")
    
    # Example: Good signal in high volatility with weak trend
    pos_size, details = sizer.calculate_position_size(
        signal_score=70,
        volatility_regime='HIGH_VOL',
        trend_strength='WEAK_TREND',
    )
    print(f"Good signal, high volatility: {pos_size} lots")
    
    # Example: With precise entry and stop loss
    pos_size, details = sizer.calculate_position_size(
        signal_score=80,
        volatility_regime='NORMAL_VOL',
        trend_strength='STRONG_TREND',
        entry_price=1.0950,
        stop_loss=1.0850,
    )
    print(f"With entry/SL: {pos_size} lots")
