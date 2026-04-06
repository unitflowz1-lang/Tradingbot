"""
Centralized Expectancy Calculation
===================================
SINGLE SOURCE OF TRUTH for all expectancy calculations across the bot.

Prevents "Split-Brain" critical errors where different modules use different expectancy math.
Used by: SignalCombiner, Ensemble, AdmissionController, SLTPCalculator
"""

from typing import Optional, Tuple
import logging

logger = logging.getLogger(__name__)


def calculate_expectancy(
    entry_price: float,
    stop_loss: float, 
    take_profit: float,
    win_probability: float,  # 0.0 to 1.0
    symbol: str = "UNKNOWN"
) -> Tuple[float, float, float]:
    """
    Calculate expectancy metrics using standardized formula.
    
    === CANONICAL FORMULA ===
    EV = (Win_Prob * Reward) - ((1 - Win_Prob) * Risk)
    RR_Ratio = Reward / Risk
    Expectancy_R = Win_Prob * RR_Ratio - ((1 - Win_Prob) * 1.0)
    
    Args:
        entry_price: Entry price
        stop_loss: Stop loss price
        take_profit: Take profit price
        win_probability: Probability of winning (0-1)
        symbol: Symbol for logging
        
    Returns:
        Tuple of (expectancy_value, risk_reward_ratio, edge_percentage)
    """
    
    # Validate inputs
    if not (0.0 <= win_probability <= 1.0):
        logger.warning(f"[EXPECTANCY] {symbol} | Invalid win_prob {win_probability}, clamping to [0,1]")
        win_probability = max(0.0, min(1.0, win_probability))
    
    # Calculate risk and reward
    risk = abs(entry_price - stop_loss)
    reward = abs(take_profit - entry_price)
    
    if risk <= 0:
        logger.error(f"[EXPECTANCY] {symbol} | Invalid risk {risk}, using default 20 pips")
        risk = 0.0001  # Default risk
    
    if reward <= 0:
        logger.error(f"[EXPECTANCY] {symbol} | Invalid reward {reward}, using default 20 pips")
        reward = 0.0001  # Default reward
    
    # Calculate metrics
    rr_ratio = reward / risk if risk > 0 else 1.0
    
    # Expected Value = (Win% * Reward) - (Loss% * Risk)
    loss_probability = 1.0 - win_probability
    ev_value = (win_probability * reward) - (loss_probability * risk)
    
    # Expectancy in R-multiples
    expectancy_r = (win_probability * rr_ratio) - (loss_probability * 1.0)
    
    # Edge as percentage
    edge = (ev_value / risk * 100) if risk > 0 else 0.0
    
    logger.info(
        f"[EXPECTANCY_CALC] {symbol} | "
        f"WinProb={win_probability:.3f} | "
        f"Risk={risk:.6f} | Reward={reward:.6f} | "
        f"RR={rr_ratio:.3f} | EV={ev_value:.6f} | "
        f"Expectancy_R={expectancy_r:.3f} | Edge={edge:.2f}%"
    )
    
    return ev_value, rr_ratio, expectancy_r


def get_risk_reward_ratio(
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    symbol: str = "UNKNOWN"
) -> float:
    """Get just the Risk/Reward ratio from prices"""
    risk = abs(entry_price - stop_loss)
    reward = abs(take_profit - entry_price)
    
    if risk <= 0:
        return 1.0
    
    return reward / risk


# === Integration Points ===
# All modules should use this function:
#
# from src.risk.expectancy_calculator import calculate_expectancy
# 
# ev_val, rr_ratio, exp_r = calculate_expectancy(
#     entry_price=1.1050,
#     stop_loss=1.1000,
#     take_profit=1.1100, 
#     win_probability=0.55,
#     symbol="EURUSD"
# )
