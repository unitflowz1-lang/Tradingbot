"""
Phase 3 Exit Optimization Modules
"""

from .multi_level_profit_taker import (
    MultiLevelProfitTaker,
    ProfitLevel,
    MultiLevelConfig,
    CONSERVATIVE_PROFIT_CONFIG,
    MODERATE_PROFIT_CONFIG,
    AGGRESSIVE_PROFIT_CONFIG,
)

from .reversal_exit_detector import (
    ReversalExitDetector,
    ReversalType,
    ReversalExitConfig,
    CONSERVATIVE_REVERSAL_CONFIG,
    MODERATE_REVERSAL_CONFIG,
    AGGRESSIVE_REVERSAL_CONFIG,
)

from .market_mode_detector import (
    MarketModeDetector,
    MarketMode,
    MarketModeConfig,
    determine_market_mode,
    CONSERVATIVE_MODE_CONFIG,
    MODERATE_MODE_CONFIG,
    AGGRESSIVE_MODE_CONFIG,
)

from .breakout_tp_calculator import (
    BreakoutTPCalculator,
    BreakoutTargets,
    BreakoutTPConfig,
    CONSERVATIVE_BREAKOUT_CONFIG,
    MODERATE_BREAKOUT_CONFIG,
    AGGRESSIVE_BREAKOUT_CONFIG,
)

__all__ = [
    # Multi-Level Profit Taker
    'MultiLevelProfitTaker',
    'ProfitLevel',
    'MultiLevelConfig',
    'CONSERVATIVE_PROFIT_CONFIG',
    'MODERATE_PROFIT_CONFIG',
    'AGGRESSIVE_PROFIT_CONFIG',
    
    # Reversal Exit Detector
    'ReversalExitDetector',
    'ReversalType',
    'ReversalExitConfig',
    'CONSERVATIVE_REVERSAL_CONFIG',
    'MODERATE_REVERSAL_CONFIG',
    'AGGRESSIVE_REVERSAL_CONFIG',
    
    # Market Mode Detector
    'MarketModeDetector',
    'MarketMode',
    'MarketModeConfig',
    'determine_market_mode',
    'CONSERVATIVE_MODE_CONFIG',
    'MODERATE_MODE_CONFIG',
    'AGGRESSIVE_MODE_CONFIG',
    
    # Breakout TP Calculator
    'BreakoutTPCalculator',
    'BreakoutTargets',
    'BreakoutTPConfig',
    'CONSERVATIVE_BREAKOUT_CONFIG',
    'MODERATE_BREAKOUT_CONFIG',
    'AGGRESSIVE_BREAKOUT_CONFIG',
]
