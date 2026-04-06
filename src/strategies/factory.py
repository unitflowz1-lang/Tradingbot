"""Strategy factory for symbol-level strategy routing."""

from __future__ import annotations

import importlib.util
import logging
from typing import Any, Dict, Optional

from src.strategies.high_reward_reversal_peaks import (
    HighRewardReversalPeaksStrategy,
    ReversalPeaksConfig,
)
from src.strategies.range_strategy import RangeStrategy
from src.strategies.trend_strategy import SimpleTrendStrategy

logger = logging.getLogger(__name__)


STRATEGY_REGISTRY = {
    "range": RangeStrategy,
    "simpletrend": SimpleTrendStrategy,
    "reversalpeaks": HighRewardReversalPeaksStrategy,
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


def build_strategy(
    symbol: str,
    config: Optional[Any] = None,
    admission_controller: Optional[Any] = None,
    config_manager: Optional[Any] = None,
    strategy_override: Optional[str] = None,
):
    symbol_block = _get_symbol_strategy_block(symbol, config_manager)
    strategy_name = str(strategy_override or symbol_block.get("strategy", "SimpleTrend") or "SimpleTrend").strip()
    strategy_key = strategy_name.lower()
    strategy_class = STRATEGY_REGISTRY.get(strategy_key)
    if strategy_class is None:
        raise ValueError(f"Unknown strategy '{strategy_name}' for symbol {symbol}")

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

    return strategy_class(
        symbol,
        config=config,
        admission_controller=admission_controller,
    )
