"""
Strategy manager and base strategy framework.
Allows multiple strategies to run simultaneously with weighted capital allocation.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import pandas as pd
from enum import Enum
from utils.logger import get_logger


logger = get_logger(__name__)


class Signal(str, Enum):
    """Trading signals."""
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class StrategySignal:
    """Strategy signal with metadata."""
    signal: Signal
    strength: float  # 0.0 to 1.0 confidence
    strategy_name: str
    timestamp: datetime
    metadata: Dict = None


class Strategy(ABC):
    """
    Base strategy class.
    All strategies must inherit and implement required methods.
    """
    
    def __init__(self, name: str, config: Dict = None):
        """
        Initialize strategy.
        
        Args:
            name: Strategy name
            config: Strategy configuration parameters
        """
        self.name = name
        self.config = config or {}
        self.enabled = True
    
    @abstractmethod
    def generate_signal(self, data: pd.DataFrame) -> Signal:
        """
        Generate trading signal from market data.
        
        Args:
            data: OHLCV DataFrame
        
        Returns:
            Signal (BUY, SELL, HOLD)
        """
        pass
    
    @abstractmethod
    def calculate_stop_loss(self, entry_price: float, direction: str,
                           data: pd.DataFrame) -> float:
        """
        Calculate stop loss level.
        
        Args:
            entry_price: Entry price
            direction: BUY or SELL
            data: Market data for ATR, volatility, etc.
        
        Returns:
            Stop loss price
        """
        pass
    
    @abstractmethod
    def calculate_take_profit(self, entry_price: float, direction: str,
                             data: pd.DataFrame) -> float:
        """
        Calculate take profit level.
        
        Args:
            entry_price: Entry price
            direction: BUY or SELL
            data: Market data
        
        Returns:
            Take profit price
        """
        pass
    
    def validate_trade(self, signal: Signal, data: pd.DataFrame) -> bool:
        """
        Validate if trade meets strategy criteria.
        Can override for complex validation.
        
        Args:
            signal: Generated signal
            data: Current market data
        
        Returns:
            True if trade is valid
        """
        return signal != Signal.HOLD
    
    def on_trade_open(self, trade_id: str):
        """Hook called when trade opens."""
        pass
    
    def on_trade_close(self, trade_id: str, exit_reason: str):
        """Hook called when trade closes."""
        pass
    
    def update(self, data: pd.DataFrame):
        """Update strategy state with new data."""
        pass


class StrategyManager:
    """
    Manages multiple strategies running simultaneously.
    Handles signal aggregation and capital allocation.
    """
    
    def __init__(self):
        """Initialize StrategyManager."""
        self.strategies: Dict[str, Strategy] = {}
        self.strategy_weights: Dict[str, float] = {}
        self.signal_history: List[StrategySignal] = []
    
    def register_strategy(self, strategy: Strategy, weight: float = 1.0) -> bool:
        """
        Register a strategy.
        
        Args:
            strategy: Strategy instance
            weight: Capital allocation weight (0.0 to 1.0)
        
        Returns:
            True if registered successfully
        """
        if weight <= 0 or weight > 1.0:
            logger.error("Invalid strategy weight", weight=weight)
            return False
        
        self.strategies[strategy.name] = strategy
        self.strategy_weights[strategy.name] = weight
        
        logger.info("Strategy registered",
                   strategy_name=strategy.name,
                   weight=weight)
        
        return True
    
    def remove_strategy(self, strategy_name: str) -> bool:
        """Remove a strategy."""
        if strategy_name in self.strategies:
            del self.strategies[strategy_name]
            del self.strategy_weights[strategy_name]
            logger.info("Strategy removed", strategy_name=strategy_name)
            return True
        return False
    
    def generate_signals(self, market_data: Dict[str, pd.DataFrame]) -> Dict[str, StrategySignal]:
        """
        Generate signals from all registered strategies.
        
        Args:
            market_data: Dict of symbol -> OHLCV DataFrame
        
        Returns:
            Dict of strategy_name -> StrategySignal
        """
        signals = {}
        
        for symbol, data in market_data.items():
            for strategy_name, strategy in self.strategies.items():
                if not strategy.enabled or len(data) < 10:
                    continue
                
                try:
                    signal = strategy.generate_signal(data)
                    
                    # Calculate signal strength
                    strength = self._calculate_signal_strength(
                        strategy, data, signal
                    )
                    
                    strategy_signal = StrategySignal(
                        signal=signal,
                        strength=strength,
                        strategy_name=strategy_name,
                        timestamp=datetime.now(),
                        metadata={'symbol': symbol}
                    )
                    
                    signals[f"{strategy_name}_{symbol}"] = strategy_signal
                    self.signal_history.append(strategy_signal)
                    
                    if signal != Signal.HOLD:
                        logger.info("Signal generated",
                                   strategy=strategy_name,
                                   symbol=symbol,
                                   signal=signal.value,
                                   strength=strength)
                
                except Exception as e:
                    logger.error(f"Error generating signal: {e}",
                               strategy=strategy_name,
                               symbol=symbol)
        
        return signals
    
    def aggregate_signals(self, signals: Dict[str, StrategySignal],
                         threshold: float = 0.5) -> Dict[str, Signal]:
        """
        Aggregate signals from multiple strategies for a symbol.
        Uses weighted voting.
        
        Args:
            signals: Signals from all strategies
            threshold: Minimum weighted vote needed for signal
        
        Returns:
            Final signal per symbol
        """
        symbol_votes: Dict[str, Dict[str, float]] = {}
        
        for signal_key, signal_obj in signals.items():
            symbol = signal_obj.metadata.get('symbol', '')
            strategy_name = signal_obj.strategy_name
            
            if symbol not in symbol_votes:
                symbol_votes[symbol] = {
                    'BUY': 0.0,
                    'SELL': 0.0,
                    'HOLD': 0.0
                }
            
            weight = self.strategy_weights.get(strategy_name, 1.0)
            signal_value = signal_obj.signal.value
            
            symbol_votes[symbol][signal_value] += weight * signal_obj.strength
        
        # Convert votes to signals
        aggregated = {}
        for symbol, votes in symbol_votes.items():
            total_vote = sum(votes.values())
            
            if total_vote == 0:
                aggregated[symbol] = Signal.HOLD
            else:
                # Normalize votes
                votes = {k: v / total_vote for k, v in votes.items()}
                
                # Get dominant signal
                if votes['BUY'] > threshold:
                    aggregated[symbol] = Signal.BUY
                elif votes['SELL'] > threshold:
                    aggregated[symbol] = Signal.SELL
                else:
                    aggregated[symbol] = Signal.HOLD
        
        return aggregated
    
    def get_strategy_stats(self, strategy_name: str) -> Dict:
        """Get statistics for a strategy."""
        if strategy_name not in self.strategies:
            return {}
        
        strategy_signals = [s for s in self.signal_history
                           if s.strategy_name == strategy_name]
        
        if not strategy_signals:
            return {}
        
        buy_signals = len([s for s in strategy_signals if s.signal == Signal.BUY])
        sell_signals = len([s for s in strategy_signals if s.signal == Signal.SELL])
        avg_strength = sum(s.strength for s in strategy_signals) / len(strategy_signals)
        
        return {
            'total_signals': len(strategy_signals),
            'buy_signals': buy_signals,
            'sell_signals': sell_signals,
            'avg_strength': avg_strength,
            'weight': self.strategy_weights.get(strategy_name, 1.0)
        }
    
    def _calculate_signal_strength(self, strategy: Strategy,
                                  data: pd.DataFrame, signal: Signal) -> float:
        """
        Calculate signal strength/confidence (0.0 to 1.0).
        Can be overridden for custom strength calculation.
        """
        # Default: base strength on volatility and trend confirmation
        if len(data) < 2:
            return 0.5
        
        # Simple volatility-based strength
        returns = data['close'].pct_change().dropna()
        volatility = returns.std()
        
        # Higher volatility = lower confidence
        strength = max(0.3, min(0.9, 1.0 - volatility))
        
        return strength


# Regime-based strategy switching
class RegimeStrategy:
    """
    Switches strategies based on market regime detection.
    """
    
    def __init__(self, manager: StrategyManager):
        """Initialize regime strategy."""
        self.manager = manager
        self.current_regime = "trending"
        self.regime_strategies = {
            'trending': ['sma_crossover', 'breakout'],
            'mean_reversion': ['mean_reversion', 'bollinger'],
            'volatile': ['mean_reversion'],
            'low_volatility': ['sma_crossover']
        }
    
    def update_regime(self, regime: str):
        """Update market regime and enable/disable strategies accordingly."""
        if regime == self.current_regime:
            return
        
        self.current_regime = regime
        
        # Disable all strategies
        for strategy in self.manager.strategies.values():
            strategy.enabled = False
        
        # Enable strategies for current regime
        for strategy_name in self.regime_strategies.get(regime, []):
            if strategy_name in self.manager.strategies:
                self.manager.strategies[strategy_name].enabled = True
        
        logger.info("Market regime changed",
                   regime=regime,
                   active_strategies=self.regime_strategies.get(regime, []))
