"""
SRH-Reversal Engine Integration Bridge
======================================

Adapter and integration layer that connects the Reversal Engine to your existing
Selective Risk Handling (SRH) system, trading pipeline, and exit handlers.

This module provides:
  1. Real SRH Adapter - connects to actual risk governor & regime detection
  2. Execution Pipeline - feeds reversal signals into your trading broker
  3. State Management - tracks open reversals and exit conditions
  4. Logging Hooks - integrates with your exit logger and monitoring

Author: Integration Team
Version: 1.0.0
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Dict, List
from enum import Enum

from src.trading.reversal_engine import (
    ReversalEngine,
    ReversalExitManager,
    MarketAnalyzer,
    CooldownManager,
    ReversalDecision,
    ExitDecision,
    ReversalConfig,
)

logger = logging.getLogger(__name__)


@dataclass
class ReversalTradeState:
    """Track state of an active reversal trade."""

    symbol: str
    action: str  # "BUY" or "SELL"
    entry_price: float
    entry_timestamp: datetime
    entry_atr: float
    entry_confidence: float
    entry_type: str  # "aggressive" or "conservative"
    setup_signature: str = ""
    entry_invalidation_price: Optional[float] = None
    
    position_id: Optional[str] = None
    entry_index: int = 0
    
    # Exit state tracking
    partial_taken: bool = False
    sl_moved: bool = False
    bars_in_trade: int = 0
    unrealized_r: float = 0.0
    
    def to_dict(self) -> Dict:
        """Convert to loggable dict."""
        return {
            "symbol": self.symbol,
            "action": self.action,
            "entry_price": self.entry_price,
            "entry_timestamp": self.entry_timestamp.isoformat(),
            "entry_atr": self.entry_atr,
            "entry_confidence": self.entry_confidence,
            "entry_type": self.entry_type,
            "setup_signature": self.setup_signature,
            "entry_invalidation_price": self.entry_invalidation_price,
            "position_id": self.position_id,
            "partial_taken": self.partial_taken,
            "sl_moved": self.sl_moved,
            "bars_in_trade": self.bars_in_trade,
            "unrealized_r": self.unrealized_r,
        }


class RealSRHAdapter:
    """
    Adapter that interfaces with your actual SRH system.
    Replace MockSRH calls with real risk governor queries.
    """

    def __init__(self, risk_governor=None, regime_detector=None, session_manager=None):
        """
        Initialize adapter with real SRH components.

        Args:
            risk_governor: Instance of your RiskGovernor
            regime_detector: Instance of your regime detection system
            session_manager: Instance of your session manager
        """
        self.risk_governor = risk_governor
        self.regime_detector = regime_detector
        self.session_manager = session_manager
        self.logger = logging.getLogger(__name__)

    def get_regime(self, symbol: str) -> str:
        """Get regime from RiskGovernor or RegimeDetector."""
        if self.regime_detector:
            if hasattr(self.regime_detector, "get_regime"):
                return self.regime_detector.get_regime(symbol)
            if hasattr(self.regime_detector, "get_current_regime"):
                return self.regime_detector.get_current_regime(symbol)
        return "VOLATILE"  # Default fallback

    def get_htf_trend(self, symbol: str) -> str:
        """Get HTF trend from regime detector."""
        if self.regime_detector:
            if hasattr(self.regime_detector, "get_htf_trend"):
                return self.regime_detector.get_htf_trend(symbol)
        return "NEUTRAL"

    def get_session(self, symbol: str) -> str:
        """Get current session from session manager."""
        if self.session_manager:
            if hasattr(self.session_manager, "get_session"):
                return self.session_manager.get_session(symbol)
            if hasattr(self.session_manager, "get_current_session"):
                return self.session_manager.get_current_session()
        return "LONDON_NY_OVERLAP"

    def news_active(self, symbol: str = None) -> bool:
        """Check if major news is active (query news system)."""
        if self.risk_governor and hasattr(self.risk_governor, "is_news_event_active"):
            return self.risk_governor.is_news_event_active(symbol)
        return False

    def get_spread_metrics(self, symbol: str) -> tuple:
        """Get spread from broker data."""
        # Implement via your broker interface
        return 0.2, 0.18  # (current, average)

    def get_waterfall_multiplier(self, symbol: str, confidence: float) -> float:
        """Get risk adjustment from risk governor."""
        if self.risk_governor and hasattr(self.risk_governor, "get_position_multiplier"):
            return self.risk_governor.get_position_multiplier(confidence)
        return min(1.0, confidence * 1.2)


class ReversalExecutionPipeline:
    """
    Orchestrates reversal detection, execution, and exit management.

    Workflow:
      1. Analyze symbol with ReversalEngine
      2. If signal generated, request execution
      3. Track trade state
      4. Monitor for exit conditions
      5. Return exit decisions to position manager
    """

    def __init__(
        self,
        srh_adapter: RealSRHAdapter,
        execution_engine=None,  # Your TradeExecutor
        position_manager=None,  # Your PositionManager
        exit_logger=None,
        config: ReversalConfig = ReversalConfig(),
    ):
        """
        Initialize pipeline.

        Args:
            srh_adapter: Real SRH adapter
            execution_engine: TradeExecutor for order placement
            position_manager: PositionManager for state tracking
            exit_logger: ExitLogger for trade logging
        """
        self.srh_adapter = srh_adapter
        self.execution_engine = execution_engine
        self.position_manager = position_manager
        self.exit_logger = exit_logger
        self.logger = logging.getLogger(__name__)
        self.config = config

        # Initialize reversal components
        self.cooldown_mgr = CooldownManager(cooldown_candles=self.config.COOLDOWN_CANDLES)
        self.reversal_engine = ReversalEngine(
            srh=srh_adapter,
            cooldown_mgr=self.cooldown_mgr,
            config=self.config,
        )

        # Track active reversal trades
        self.active_reversals: Dict[str, ReversalTradeState] = {}

    def analyze_symbol(self, symbol: str, df, timeframe: str = "M5") -> ReversalDecision:
        """
        Analyze a symbol and return reversal decision.

        Args:
            symbol: Trading symbol
            df: DataFrame with OHLCV + indicators

        Returns:
            ReversalDecision
        """
        # Calculate features
        df = MarketAnalyzer.calculate_features(df, symbol=symbol, timeframe=timeframe, config=self.config)

        # Evaluate with reversal engine
        decision = self.reversal_engine.evaluate_symbol(symbol, df, timeframe=timeframe)

        return decision

    def execute_reversal(
        self,
        symbol: str,
        decision: ReversalDecision,
        entry_price: float,
        atr: float,
        current_index: Optional[int] = None,
        entry_invalidation_price: Optional[float] = None,
    ) -> Optional[ReversalTradeState]:
        """
        Execute reversal trade if signal approved.

        Args:
            symbol: Trading symbol
            decision: ReversalDecision from engine
            entry_price: Current price
            atr: Current ATR
            current_index: Candle index used for cooldown tracking
            entry_invalidation_price: Structural invalidation level from entry candle wick

        Returns:
            ReversalTradeState if executed, None otherwise
        """
        if decision.action == "NO_TRADE":
            return None

        self.logger.info(
            f"[REVERSAL_EXECUTION] {symbol} | Action: {decision.action} | "
            f"Confidence: {decision.confidence:.2f} | Entry Type: {decision.entry_type}"
        )

        # Create trade state
        trade_state = ReversalTradeState(
            symbol=symbol,
            action=decision.action,
            entry_price=entry_price,
            entry_timestamp=datetime.now(timezone.utc),
            entry_atr=atr,
            entry_confidence=decision.confidence,
            entry_type=decision.entry_type,
            setup_signature=decision.reason if decision.action != "NO_TRADE" else "",
            entry_invalidation_price=entry_invalidation_price,
            entry_index=current_index or 0,
        )

        self.cooldown_mgr.record_trade(symbol, current_index if current_index is not None else 0)

        # Request execution (optional - if you have execution engine)
        if self.execution_engine:
            # Implement your order placement logic
            pass

        # Track trade
        self.active_reversals[symbol] = trade_state

        # Record trade startup
        if self.exit_logger:
            self.exit_logger.log_entry(
                symbol=symbol,
                direction=decision.action,
                entry_price=entry_price,
                setup="REVERSAL_ENGINE",
                confidence=decision.confidence,
                reason=decision.reason,
            )

        return trade_state

    def evaluate_position_exit(
        self,
        symbol: str,
        df,
        unrealized_r: float = 0.0,
        bars_in_trade: int = 0,
    ) -> Optional[ExitDecision]:
        """
        Evaluate if active reversal position should exit.

        Args:
            symbol: Trading symbol
            df: Current market data
            unrealized_r: Unrealized profit in R-multiples
            bars_in_trade: Candles in trade

        Returns:
            ExitDecision if exit triggered, None otherwise
        """
        if symbol not in self.active_reversals:
            return None

        trade = self.active_reversals[symbol]
        trade.bars_in_trade = bars_in_trade
        trade.unrealized_r = unrealized_r

        # Evaluate exit
        exit_decision = ReversalExitManager.evaluate_exit(
            symbol=symbol,
            action=trade.action,
            entry_price=trade.entry_price,
            entry_atr=trade.entry_atr,
            bars_in_trade=bars_in_trade,
            unrealized_r=unrealized_r,
            current_df=df,
            partial_taken=trade.partial_taken,
            sl_moved=trade.sl_moved,
            config=self.config,
            entry_invalidation_price=trade.entry_invalidation_price,
        )

        if exit_decision.action != "HOLD":
            self.logger.info(
                f"[REVERSAL_EXIT] {symbol} | Action: {exit_decision.action} | "
                f"Reason: {exit_decision.reason} | R-Multiple: {unrealized_r:.2f}"
            )

            # Update state
            if exit_decision.action == "CLOSE_PARTIAL_50":
                trade.partial_taken = True
            elif exit_decision.action == "MOVE_SL_BE":
                trade.sl_moved = True
            elif exit_decision.action == "CLOSE_FULL":
                # Trade complete, clean up
                del self.active_reversals[symbol]

            return exit_decision

        return None

    def record_reversal_exit(
        self,
        symbol: str,
        exit_price: float,
        exit_reason: str,
        pnl: float = 0.0,
    ):
        """
        Log completed reversal trade exit.

        Args:
            symbol: Trading symbol
            exit_price: Exit price
            exit_reason: Reason for exit
            pnl: Realized P&L
        """
        if symbol not in self.active_reversals:
            return

        trade = self.active_reversals[symbol]

        self.logger.info(
            f"[REVERSAL_CLOSED] {symbol} {trade.action} | "
            f"Entry: {trade.entry_price:.5f} | Exit: {exit_price:.5f} | "
            f"PnL: ${pnl:.2f} | Reason: {exit_reason}"
        )

        if self.exit_logger:
            self.exit_logger.log_exit(
                symbol=symbol,
                direction=trade.action,
                entry_price=trade.entry_price,
                exit_price=exit_price,
                exit_reason=exit_reason,
                pnl=pnl,
                setup="REVERSAL_ENGINE",
                setup_confidence=trade.entry_confidence,
            )

        if trade.setup_signature:
            self.reversal_engine.record_setup_outcome(trade.setup_signature, pnl > 0.0)

        # Remove from active
        del self.active_reversals[symbol]


class ReversalSignalValidator:
    """
    Optional validator to cross-check reversal signals against other systems
    before execution. Useful for risk validation and conflict checking.
    """

    def __init__(self, risk_calculator=None, admission_controller=None):
        """
        Initialize validator with risk and admission systems.

        Args:
            risk_calculator: RiskCalculator for position sizing
            admission_controller: AdmissionController for signal filtering
        """
        self.risk_calculator = risk_calculator
        self.admission_controller = admission_controller
        self.logger = logging.getLogger(__name__)

    def validate_signal(
        self,
        symbol: str,
        decision: ReversalDecision,
        portfolio=None,
    ) -> bool:
        """
        Validate reversal signal against risk and admission rules.

        Args:
            symbol: Trading symbol
            decision: ReversalDecision from engine
            portfolio: Current portfolio

        Returns:
            True if signal passes validation, False otherwise
        """
        if decision.action == "NO_TRADE":
            return False

        # Check risk constraints
        if self.risk_calculator and portfolio:
            # Implement risk assessment
            pass

        # Check admission criteria
        if self.admission_controller:
            # Implement admission check
            pass

        return True


# ============================================================================
# INTEGRATION WITH MAIN TRADING LOOP
# ============================================================================

def integrate_reversal_engine(main_trading_loop_obj):
    """
    Example of how to integrate reversal engine into your main trading loop.

    In your main.py or trading loop, add:

    ```python
    # Initialize
    srh_adapter = RealSRHAdapter(
        risk_governor=your_risk_governor,
        regime_detector=your_regime_detector,
        session_manager=your_session_manager,
    )

    reversal_pipeline = ReversalExecutionPipeline(
        srh_adapter=srh_adapter,
        execution_engine=your_execution_engine,
        position_manager=your_position_manager,
        exit_logger=your_exit_logger,
    )

    # In each trading cycle:
    for symbol in symbols:
        # (1) ANALYSIS & ENTRY
        decision = reversal_pipeline.analyze_symbol(symbol, market_df)

        if decision.action != "NO_TRADE":
            trade_state = reversal_pipeline.execute_reversal(
                symbol=symbol,
                decision=decision,
                entry_price=market_df['close'].iloc[-1],
                atr=market_df['atr'].iloc[-1],
            )

        # (2) ACTIVE EXIT MANAGEMENT
        for open_symbol in reversal_pipeline.active_reversals.keys():
            exit_decision = reversal_pipeline.evaluate_position_exit(
                symbol=open_symbol,
                df=market_df[open_symbol],
                unrealized_r=calculate_unrealized_r(open_symbol),
                bars_in_trade=get_bars_in_trade(open_symbol),
            )

            if exit_decision:
                close_trade(open_symbol, exit_decision)
                reversal_pipeline.record_reversal_exit(
                    symbol=open_symbol,
                    exit_price=market_df[open_symbol]['close'].iloc[-1],
                    exit_reason=exit_decision.reason,
                )
    ```
    """
    pass
