"""
Phase 3 Integration Module
Integrates all Phase 3 components into the trading loop
"""

import logging
from dataclasses import dataclass
from typing import Optional, Tuple
from datetime import datetime

from src.models import Position, Direction
from src.trading.exit_reason import ExitReason

# Import Phase 3 components
from src.exit.multi_level_profit_taker import MultiLevelProfitTaker, MultiLevelConfig
from src.exit.reversal_exit_detector import ReversalExitDetector, ReversalExitConfig, ReversalType
from src.exit.market_mode_detector import MarketModeDetector, MarketModeConfig, MarketMode
from src.exit.breakout_tp_calculator import BreakoutTPCalculator, BreakoutTPConfig

logger = logging.getLogger(__name__)


@dataclass
class Phase3ExitSignal:
    """Signal from Phase 3 components to exit a position"""
    should_exit: bool
    exit_type: str  # 'MULTI_LEVEL', 'REVERSAL', 'MODE_ADAPTIVE'
    reason: str
    exit_percentage: Optional[float] = None  # For partial exits
    new_tp: Optional[float] = None  # Updated TP from mode detector
    new_sl: Optional[float] = None  # Updated SL from mode detector


class Phase3ExitManager:
    """
    Manages Phase 3 exit optimization
    
    Integrates:
    1. Multi-Level Profit Taker - Exit in tiers
    2. Reversal Exit Detector - Detect reversals early
    3. Market Mode Detector - Identify market mode
    4. Breakout TP Calculator - Adaptive targets
    """
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        """Initialize Phase 3 components"""
        self.logger = logger or logging.getLogger(__name__)
        
        # Initialize all Phase 3 components
        self.profit_taker = MultiLevelProfitTaker(MultiLevelConfig())
        self.reversal_detector = ReversalExitDetector(ReversalExitConfig())
        self.mode_detector = MarketModeDetector(MarketModeConfig())
        self.tp_calculator = BreakoutTPCalculator(BreakoutTPConfig())
        
        # Track candle history for reversal detection
        self.candle_history = {}  # symbol -> list of OHLC dicts
        self.rsi_history = {}     # symbol -> list of RSI values
        self.momentum_history = {}  # symbol -> list of momentum values
        
        self.logger.info("[PHASE3] Exit Manager initialized")
    
    def update_candle_history(self, symbol: str, candle: dict, max_history: int = 50):
        """Update candle history for reversal detection"""
        if symbol not in self.candle_history:
            self.candle_history[symbol] = []
        
        self.candle_history[symbol].append(candle)
        # Keep only recent candles
        if len(self.candle_history[symbol]) > max_history:
            self.candle_history[symbol] = self.candle_history[symbol][-max_history:]
    
    def update_rsi_history(self, symbol: str, rsi: float, max_history: int = 20):
        """Update RSI history for reversal detection"""
        if symbol not in self.rsi_history:
            self.rsi_history[symbol] = []
        
        self.rsi_history[symbol].append(rsi)
        # Keep only recent values
        if len(self.rsi_history[symbol]) > max_history:
            self.rsi_history[symbol] = self.rsi_history[symbol][-max_history:]
    
    def check_multi_level_exit(self, position: Position) -> Phase3ExitSignal:
        """
        Check if multi-level profit taking should trigger
        
        Args:
            position: The position to check
        
        Returns:
            Phase3ExitSignal with exit details
        """
        level, exit_pct = self.profit_taker.should_take_profit(
            current_price=position.current_price,
            entry_price=position.entry_price,
            stop_loss=position.stop_loss,
            direction='LONG' if position.direction == Direction.LONG else 'SHORT',
        )
        
        if level is not None:
            return Phase3ExitSignal(
                should_exit=True,
                exit_type='MULTI_LEVEL',
                reason=f"Multi-level profit: {level.comment} at {level.profit_target:.1f}R",
                exit_percentage=exit_pct,
            )
        
        return Phase3ExitSignal(should_exit=False, exit_type='', reason='')
    
    def check_reversal_exit(self, position: Position, symbol: str,
                           buy_signal: bool = False,
                           sell_signal: bool = False) -> Phase3ExitSignal:
        """
        Check if reversal exit should trigger
        
        Args:
            position: The position to check
            symbol: Symbol for history lookup
            buy_signal: Whether BUY signal is active (opposite signal detection)
            sell_signal: Whether SELL signal is active (opposite signal detection)
        
        Returns:
            Phase3ExitSignal with exit details
        """
        if symbol not in self.candle_history or len(self.candle_history[symbol]) < 3:
            return Phase3ExitSignal(should_exit=False, exit_type='', reason='')
        
        current_candle = self.candle_history[symbol][-1]
        previous_candles = self.candle_history[symbol][-4:-1]
        
        # Determine opposite signal trigger
        opposite_signal = False
        if position.direction == Direction.LONG and sell_signal:
            opposite_signal = True
        elif position.direction == Direction.SHORT and buy_signal:
            opposite_signal = True
        
        should_exit, rev_type, reason = self.reversal_detector.should_exit_on_reversal(
            current_candle=current_candle,
            previous_candles=previous_candles,
            trade_direction='LONG' if position.direction == Direction.LONG else 'SHORT',
            rsi_values=self.rsi_history.get(symbol, []),
            momentum_values=self.momentum_history.get(symbol, []),
            opposite_signal_triggered=opposite_signal,
        )
        
        if should_exit and rev_type:
            return Phase3ExitSignal(
                should_exit=True,
                exit_type='REVERSAL',
                reason=f"Reversal detected: {rev_type.value}",
            )
        
        return Phase3ExitSignal(should_exit=False, exit_type='', reason='')
    
    def check_mode_adaptive_targets(self, position: Position,
                                    atr: float,
                                    volatility_regime: str = 'NORMAL_VOL',
                                    trend_strength: float = 20.0) -> Phase3ExitSignal:
        """
        Check if market mode suggests updated targets
        
        Args:
            position: The position to check
            atr: Current ATR value
            volatility_regime: Current volatility (HIGH_VOL, NORMAL_VOL, LOW_VOL)
            trend_strength: ADX value for trend strength
        
        Returns:
            Phase3ExitSignal with updated targets if needed
        """
        # Detect current market mode
        mode = self.mode_detector.detect_market_mode(
            volatility_regime=volatility_regime,
            trend_strength=trend_strength,
            recent_range=atr / position.entry_price,
        )
        
        # Calculate targets for this mode
        targets = self.tp_calculator.calculate_targets(
            entry_price=position.entry_price,
            direction='LONG' if position.direction == Direction.LONG else 'SHORT',
            atr=atr,
            market_mode=mode.name,
            base_stop_loss=position.stop_loss,
        )
        
        # Check if new targets offer better R:R
        current_rr = (abs(position.take_profit - position.entry_price) /
                     abs(position.entry_price - position.stop_loss))
        
        if targets.risk_reward_ratio > current_rr * 1.05:  # At least 5% better
            return Phase3ExitSignal(
                should_exit=False,  # Don't exit, just update targets
                exit_type='MODE_ADAPTIVE',
                reason=f"Updated targets for {mode.value}: R:R {targets.risk_reward_ratio:.2f}",
                new_tp=targets.take_profit,
                new_sl=targets.stop_loss,
            )
        
        return Phase3ExitSignal(should_exit=False, exit_type='', reason='')
    
    def check_all_exits(self, position: Position, symbol: str,
                       atr: float = 0.01,
                       volatility_regime: str = 'NORMAL_VOL',
                       trend_strength: float = 20.0,
                       buy_signal: bool = False,
                       sell_signal: bool = False) -> Phase3ExitSignal:
        """
        Check all Phase 3 exit conditions
        
        Priority order:
        1. Multi-level profit taking (scaling out)
        2. Reversal detection (avoiding losses)
        3. Mode-adaptive targets (improving R:R)
        
        Args:
            position: The position to check
            symbol: Trading symbol
            atr: Current ATR
            volatility_regime: Current volatility regime
            trend_strength: Current trend strength (ADX)
            buy_signal: Whether BUY signal is active
            sell_signal: Whether SELL signal is active
        
        Returns:
            Phase3ExitSignal with highest priority exit
        """
        # Check exits in priority order
        
        # 1. Multi-level profit taking (takes priority)
        multi_level = self.check_multi_level_exit(position)
        if multi_level.should_exit:
            return multi_level
        
        # 2. Reversal detection
        reversal = self.check_reversal_exit(
            position, symbol,
            buy_signal=buy_signal,
            sell_signal=sell_signal
        )
        if reversal.should_exit:
            return reversal
        
        # 3. Mode-adaptive targets
        mode = self.check_mode_adaptive_targets(
            position, atr,
            volatility_regime=volatility_regime,
            trend_strength=trend_strength
        )
        
        return mode
    
    def get_summary(self) -> dict:
        """Get Phase 3 status summary"""
        return {
            'multi_level_status': self.profit_taker.summary(),
            'mode': self.mode_detector.current_mode.name if hasattr(self.mode_detector, 'current_mode') else 'UNKNOWN',
            'reversal_detectors_enabled': sum([
                self.reversal_detector.config.enable_3candle_reversal,
                self.reversal_detector.config.enable_opposite_signal,
                self.reversal_detector.config.enable_rsi_divergence,
                self.reversal_detector.config.enable_price_action,
                self.reversal_detector.config.enable_momentum_loss,
            ]),
        }
