"""
RL Trading Environments

This module contains trading environment implementations for reinforcement learning,
including state processing, action spaces, and reward calculations.
"""

from .base import TradingEnvironment, EnvironmentConfig, ActionType, PortfolioState
from .forex_environment import ForexTradingEnvironment
from .state_processor import StateProcessor, DefaultStateProcessor
from .advanced_state_processor import AdvancedStateProcessor, FeatureConfig, NormalizationMethod
from .technical_indicators import TechnicalIndicators, IndicatorConfig
from .reward_calculator import (
    RewardCalculator, 
    DefaultRewardCalculator, 
    SharpeRewardCalculator,
    SimpleReturnRewardCalculator,
    AdvancedRewardCalculator,
    RewardConfig
)
from .multi_pair_environment import (
    MultiPairTradingEnvironment,
    MultiPairEnvironmentConfig,
    MultiPairPortfolioState
)
from .multi_pair_state_processor import MultiPairStateProcessor
from .multi_pair_reward_calculator import MultiPairRewardCalculator
from .transfer_learning import (
    TransferLearningConfig,
    CurrencyCharacteristics,
    CurrencyCharacteristicsAnalyzer,
    TransferLearningFramework,
    FineTuningAdapter,
    FeatureExtractionAdapter,
    ProgressiveAdapter
)
from .market_regime_detector import (
    SessionDetector,
    VolatilityRegimeDetector,
    TrendRegimeDetector,
    MarketRegimeDetector,
    TradingSession,
    VolatilityRegime,
    TrendRegime,
    MarketRegime,
    SessionInfo
)
from .adaptive_reward_calculator import AdaptiveRewardCalculator

__all__ = [
    "TradingEnvironment",
    "ForexTradingEnvironment",
    "EnvironmentConfig",
    "ActionType",
    "PortfolioState",
    "StateProcessor", 
    "DefaultStateProcessor",
    "AdvancedStateProcessor",
    "FeatureConfig",
    "NormalizationMethod",
    "TechnicalIndicators",
    "IndicatorConfig",
    "RewardCalculator",
    "DefaultRewardCalculator",
    "SharpeRewardCalculator", 
    "SimpleReturnRewardCalculator",
    "AdvancedRewardCalculator",
    "RewardConfig",
    "MultiPairTradingEnvironment",
    "MultiPairEnvironmentConfig",
    "MultiPairPortfolioState",
    "MultiPairStateProcessor",
    "MultiPairRewardCalculator",
    "TransferLearningConfig",
    "CurrencyCharacteristics",
    "CurrencyCharacteristicsAnalyzer",
    "TransferLearningFramework",
    "FineTuningAdapter",
    "FeatureExtractionAdapter",
    "ProgressiveAdapter",
    "SessionDetector",
    "VolatilityRegimeDetector",
    "TrendRegimeDetector",
    "MarketRegimeDetector",
    "TradingSession",
    "VolatilityRegime",
    "TrendRegime",
    "MarketRegime",
    "SessionInfo",
    "AdaptiveRewardCalculator"
]