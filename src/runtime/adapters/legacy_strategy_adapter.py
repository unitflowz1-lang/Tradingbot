import logging
from typing import List

from src.models import Direction, TradingSignal
from src.runtime.contracts.commands import SignalIntent
from src.runtime.contracts.snapshots import MarketSnapshot
from src.runtime.signal.signal_engine import SignalEngine
from src.strategies.trend_strategy import SimpleTrendStrategy


class LegacyStrategyAdapter(SignalEngine):
    """
    Adapter for existing SimpleTrendStrategy.
    Phase 1 behavior: preserve current strategy outputs and map to SignalIntent.
    """

    def __init__(self, strategies: dict[str, SimpleTrendStrategy]):
        self.strategies = strategies

    async def generate(self, snapshot: MarketSnapshot) -> List[SignalIntent]:
        intents: List[SignalIntent] = []
        logger = logging.getLogger(__name__)

        for symbol, sym_snap in snapshot.symbols.items():
            strategy = self.strategies.get(symbol)
            if strategy is None:
                strategy = SimpleTrendStrategy(symbol)
                self.strategies[symbol] = strategy

            signal_result = await strategy.analyze(sym_snap.bars)
            if isinstance(signal_result, (list, tuple)):
                analysis_items = list(signal_result)
                signal = next(
                    (
                        item for item in analysis_items
                        if getattr(item, "symbol", None) and getattr(item, "direction", None) is not None
                    ),
                    None,
                )
                logger.info(
                    "[LEGACY_STRATEGY_ADAPTER] %s analyze returned %d values | signal_extracted=%s",
                    symbol,
                    len(analysis_items),
                    bool(signal is not None),
                )
            else:
                signal = signal_result
            if signal is None:
                continue

            intents.append(self._to_intent(signal))

        return intents

    def _to_intent(self, signal: TradingSignal) -> SignalIntent:
        if getattr(signal, "forced_execution", False):
            priority = "CRITICAL"
        elif signal.confidence >= 0.8:
            priority = "HIGH"
        else:
            priority = "NORMAL"

        features = {
            "confidence": float(signal.confidence),
            "rr_ratio": float(getattr(signal, "rr_ratio", 0.0)),
            "ml_accuracy": float(getattr(signal, "ml_accuracy", 0.0)),
            "quality_score": float(getattr(signal, "quality_score", 0.0)),
        }

        side = signal.direction if isinstance(signal.direction, Direction) else Direction.LONG
        return SignalIntent(
            symbol=signal.symbol,
            side=side,
            entry_ref=signal.entry_price,
            confidence=signal.confidence,
            rr_estimate=float(getattr(signal, "rr_ratio", 0.0)),
            priority=priority,
            features=features,
        )
