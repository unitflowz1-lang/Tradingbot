"""Range-focused strategy wrapper for weak-trend markets."""

from __future__ import annotations

import logging
from typing import Any, Optional

from src.strategies.trend_strategy import SimpleTrendStrategy


logger = logging.getLogger(__name__)


class RangeStrategy(SimpleTrendStrategy):
    """Mean-reversion biased strategy built on the shared signal pipeline."""

    def __init__(
        self,
        symbol: str,
        verbose: bool = True,
        entry_filters: Optional[dict] = None,
        config: Optional[Any] = None,
        admission_controller: Optional[Any] = None,
    ):
        range_filters = {
            "adx_min": 0.0,
            "rsi_min": 20.0,
            "rsi_max": 80.0,
            "ml_confidence_min": 0.45,
            "meta_win_prob_min": 0.25,
            "signal_quality_min": 0.45,
            "chop_max": 75.0,
        }
        if isinstance(entry_filters, dict):
            range_filters.update(entry_filters)
        super().__init__(
            symbol=symbol,
            verbose=verbose,
            entry_filters=range_filters,
            config=config,
            admission_controller=admission_controller,
        )
        self._preferred_trade_style = "MEAN_REVERSION"
        self._strategy_family = "RANGE"
        logger.info("[RANGE_STRATEGY] %s | Mean-reversion wrapper initialized", self.symbol)
