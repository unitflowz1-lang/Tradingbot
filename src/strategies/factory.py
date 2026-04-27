"""Strategy factory for symbol-level strategy routing."""

from __future__ import annotations

import importlib.util
import logging
from typing import Any, Dict, Optional

from src.strategies.high_reward_reversal_peaks import (
    HighRewardReversalPeaksStrategy,
    ReversalPeaksConfig,
)
from src.strategies.advanced_mean_reversion import (
    AdvancedMeanReversionConfig,
    AdvancedMeanReversionStrategy,
)
from src.strategies.advanced_microstructure_strategy import (
    AdvancedMicrostructureConfig,
    AdvancedMicrostructureStrategy,
)
from src.strategies.advanced_volatility_strategy import (
    AdvancedVolatilityConfig,
    AdvancedVolatilityStrategy,
)
from src.strategies.advanced_intermarket_strategy import (
    AdvancedIntermarketConfig,
    AdvancedIntermarketStrategy,
)
from src.strategies.quant_hybrid_strategy import QuantHybridStrategy
from src.strategies.trend_strategy import SimpleTrendStrategy

logger = logging.getLogger(__name__)


STRATEGY_REGISTRY = {
    "simpletrend": SimpleTrendStrategy,
    "quanthybrid": QuantHybridStrategy,
    "reversalpeaks": HighRewardReversalPeaksStrategy,
    "meanreversion": AdvancedMeanReversionStrategy,
    "advancedmeanreversion": AdvancedMeanReversionStrategy,
    "microstructure": AdvancedMicrostructureStrategy,
    "advancedmicrostructure": AdvancedMicrostructureStrategy,
    "volatility": AdvancedVolatilityStrategy,
    "advancedvolatility": AdvancedVolatilityStrategy,
    "intermarket": AdvancedIntermarketStrategy,
    "advancedintermarket": AdvancedIntermarketStrategy,
}


def _get_symbol_strategy_block(symbol: str, config_manager: Optional[Any]) -> Dict[str, Any]:
    if config_manager is None:
        return {}
    candidates = [
        symbol,
        symbol.replace("/", ""),
        symbol.replace("/", "_"),
    ]
    for key in candidates:
        block = config_manager.get_nested_config(f"trading_pairs.{key}", default={})
        if isinstance(block, dict) and block:
            return block
    return {}


def _build_reversal_config(
    symbol_block: Dict[str, Any],
    root_config: Optional[Any],
) -> ReversalPeaksConfig:
    params = dict(symbol_block.get("strategy_params") or {})
    if "risk_per_trade" not in params and root_config is not None:
        params["risk_per_trade"] = float(getattr(getattr(root_config, "trading", None), "risk_per_trade", 0.01) or 0.01)
    return ReversalPeaksConfig(**params)


def _build_mean_reversion_config(
    symbol_block: Dict[str, Any],
    root_config: Optional[Any],
) -> AdvancedMeanReversionConfig:
    params = dict(symbol_block.get("strategy_params") or {})
    if "risk_per_trade" not in params and root_config is not None:
        params["risk_per_trade"] = float(
            getattr(getattr(root_config, "trading", None), "risk_per_trade", 0.01) or 0.01
        )
    return AdvancedMeanReversionConfig(**params)


def _build_microstructure_config(
    symbol_block: Dict[str, Any],
    root_config: Optional[Any],
) -> AdvancedMicrostructureConfig:
    params = dict(symbol_block.get("strategy_params") or {})
    if "risk_per_trade" not in params and root_config is not None:
        params["risk_per_trade"] = float(
            getattr(getattr(root_config, "trading", None), "risk_per_trade", 0.01) or 0.01
        )
    return AdvancedMicrostructureConfig(**params)


def _build_volatility_config(
    symbol_block: Dict[str, Any],
    root_config: Optional[Any],
) -> AdvancedVolatilityConfig:
    params = dict(symbol_block.get("strategy_params") or {})
    if "risk_per_trade" not in params and root_config is not None:
        params["risk_per_trade"] = float(
            getattr(getattr(root_config, "trading", None), "risk_per_trade", 0.01) or 0.01
        )
    return AdvancedVolatilityConfig(**params)


def _build_intermarket_config(
    symbol_block: Dict[str, Any],
    root_config: Optional[Any],
) -> AdvancedIntermarketConfig:
    params = dict(symbol_block.get("strategy_params") or {})
    if "risk_per_trade" not in params and root_config is not None:
        params["risk_per_trade"] = float(
            getattr(getattr(root_config, "trading", None), "risk_per_trade", 0.01) or 0.01
        )
    return AdvancedIntermarketConfig(**params)


def build_strategy(
    symbol: str,
    config: Optional[Any] = None,
    admission_controller: Optional[Any] = None,
    config_manager: Optional[Any] = None,
    runtime_hooks: Optional[Dict[str, Any]] = None,
):
    runtime_hooks = runtime_hooks or {}
    related_data_loader = runtime_hooks.get("related_data_loader")
    alpha_portfolio_engine = runtime_hooks.get("alpha_portfolio_engine")
    force_quant_hybrid = bool(runtime_hooks.get("force_quant_hybrid", True))
    symbol_block = _get_symbol_strategy_block(symbol, config_manager)
    strategy_name = str(symbol_block.get("strategy", "SimpleTrend") or "SimpleTrend").strip()
    strategy_key = strategy_name.lower()
    strategy_class = STRATEGY_REGISTRY.get(strategy_key)
    
    logger.info(
        "[STRATEGY_FACTORY] %s | Requested strategy: %s | Class: %s | force_quant_hybrid: %s",
        symbol,
        strategy_name,
        strategy_class.__name__ if strategy_class else "None",
        force_quant_hybrid,
    )
    
    if strategy_class is None:
        raise ValueError(f"Unknown strategy '{strategy_name}' for symbol {symbol}")

    # CRITICAL FIX: Force ALL symbols to use QuantHybridStrategy when force_quant_hybrid is True
    # This ensures all symbols get full quant metrics (Z-Score, GARCH, Flow Delta)
    if force_quant_hybrid and strategy_class is not QuantHybridStrategy:
        logger.info(
            "[STRATEGY_UPGRADE] %s | Upgrading %s to QuantHybridStrategy for live quant orchestration.",
            symbol,
            strategy_class.__name__,
        )
        strategy_class = QuantHybridStrategy

    if strategy_class is HighRewardReversalPeaksStrategy:
        # Safety fallback: keep execution flowing when optional TA dependency is unavailable.
        if importlib.util.find_spec("pandas_ta") is None:
            logger.critical(
                "[STRATEGY_FALLBACK] %s configured for ReversalPeaks but pandas_ta is unavailable. "
                "Falling back to SimpleTrendStrategy.",
                symbol,
            )
            return SimpleTrendStrategy(
                symbol,
                config=config,
                admission_controller=admission_controller,
            )
        reversal_config = _build_reversal_config(symbol_block, config)
        return strategy_class(
            symbol=symbol,
            config=reversal_config,
            admission_controller=admission_controller,
        )

    if strategy_class is AdvancedMeanReversionStrategy:
        mean_reversion_config = _build_mean_reversion_config(symbol_block, config)
        return strategy_class(
            symbol=symbol,
            config=mean_reversion_config,
            admission_controller=admission_controller,
        )

    if strategy_class is AdvancedMicrostructureStrategy:
        microstructure_config = _build_microstructure_config(symbol_block, config)
        return strategy_class(
            symbol=symbol,
            config=microstructure_config,
            admission_controller=admission_controller,
        )

    if strategy_class is AdvancedVolatilityStrategy:
        volatility_config = _build_volatility_config(symbol_block, config)
        return strategy_class(
            symbol=symbol,
            config=volatility_config,
            admission_controller=admission_controller,
        )

    if strategy_class is AdvancedIntermarketStrategy:
        intermarket_config = _build_intermarket_config(symbol_block, config)
        strategy = strategy_class(
            symbol=symbol,
            config=intermarket_config,
            admission_controller=admission_controller,
            related_data_loader=related_data_loader,
        )
        if alpha_portfolio_engine is not None:
            setattr(strategy, "alpha_portfolio_engine", alpha_portfolio_engine)
        return strategy

    if strategy_class is QuantHybridStrategy:
        strategy = strategy_class(
            symbol=symbol,
            config=config,
            admission_controller=admission_controller,
            related_data_loader=related_data_loader,
            hybrid_config=dict(symbol_block.get("strategy_params") or {}),
        )
        if alpha_portfolio_engine is not None:
            setattr(strategy, "alpha_portfolio_engine", alpha_portfolio_engine)
        return strategy

    strategy = strategy_class(
        symbol,
        config=config,
        admission_controller=admission_controller,
    )
    if alpha_portfolio_engine is not None:
        setattr(strategy, "alpha_portfolio_engine", alpha_portfolio_engine)
    return strategy
