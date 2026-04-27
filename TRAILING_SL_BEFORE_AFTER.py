"""
Before/After: Trailing SL Implementation
=========================================

Shows exact code changes needed to integrate dynamic trailing SL
into your existing TradingEngine.

PROBLEM: Positions oscillating ±1-3 pips, profit not locked
SOLUTION: Automatic trailing SL with spam protection
"""

# ============================================================================
# BEFORE: Current Implementation (No Trailing SL)
# ============================================================================

# File: core/engine.py (BEFORE)

class TradingEngine:
    def __init__(self, config: TradingConfig, broker: Broker, data_handler: DataHandler):
        """Initialize TradingEngine."""
        self.config = config
        self.broker = broker
        self.data_handler = data_handler

        # Core components
        self.strategy_manager = StrategyManager()
        self.execution_engine = ExecutionEngine(broker)
        self.risk_manager = RiskManager(config.data.pairs[0], config.risk)
        self.portfolio = Portfolio(10000.0, config.risk)

        # State
        self.state = TradingState()
        self.market_data: Dict[str, pd.DataFrame] = {}
        self.symbol_atr: Dict[str, float] = {}


    async def run(self):
        """Main trading loop (BEFORE)."""
        self.state.is_running = True
        logger.info("[ENGINE] Starting trading loop...")

        while self.state.is_running:
            try:
                if not self._check_trading_allowed():
                    await asyncio.sleep(60)
                    continue

                # Update market data
                await self._load_market_data()

                # Generate signals
                signals = self.strategy_manager.generate_signals(self.market_data)

                # Process signals
                await self._process_signals(signals)

                # Update positions
                await self._update_positions()

                # Monitor risk
                self._monitor_risk()

                # Sleep before next iteration
                await asyncio.sleep(60)

            except Exception as e:
                logger.error(f"[ENGINE] Error in trading loop: {e}")
                await asyncio.sleep(60)


    async def _process_signals(self, signals: Dict):
        """Process strategy signals (BEFORE)."""
        for symbol, signal in signals.items():
            if signal.value == "HOLD":
                continue

            if symbol not in self.market_data:
                continue

            data = self.market_data[symbol]
            current_price = data['close'].iloc[-1]

            try:
                pos_size = self.risk_manager.calculate_position_size(...)
            except:
                continue

            risk_levels = self.risk_manager.calculate_stops_and_targets(...)

            order_id = await self.execution_engine.submit_market_order(
                symbol=symbol,
                direction=signal.value,
                quantity=pos_size.quantity,
                stop_loss=risk_levels.stop_loss,
                take_profit=risk_levels.take_profit,
                comment="Signal from engine"
            )

            if order_id:
                logger.info(f"[ENGINE] Order submitted: {order_id}")
            # <- No tracking for trailing SL


# ============================================================================
# AFTER: With Trailing SL Implementation
# ============================================================================

# File: core/engine.py (AFTER)

# ===== NEW IMPORTS =====
from src.trading.dynamic_trailing_sl_manager import (
    DynamicTrailingSLManager,
    TrailingConfig,
)

class TradingEngine:
    def __init__(self, config: TradingConfig, broker: Broker, data_handler: DataHandler):
        """Initialize TradingEngine WITH trailing SL."""
        self.config = config
        self.broker = broker
        self.data_handler = data_handler

        # Core components
        self.strategy_manager = StrategyManager()
        self.execution_engine = ExecutionEngine(broker)
        self.risk_manager = RiskManager(config.data.pairs[0], config.risk)
        self.portfolio = Portfolio(10000.0, config.risk)

        # State
        self.state = TradingState()
        self.market_data: Dict[str, pd.DataFrame] = {}
        self.symbol_atr: Dict[str, float] = {}

        # ===== NEW: Initialize trailing SL manager =====
        trailing_config = TrailingConfig(
            buffer_pips=5,
            min_time_between_mods_seconds=5,
            min_pip_movement=0.001,
            enable_profit_lock=True,
            profit_lock_threshold_pips=20,
        )
        self.trailing_sl_manager = DynamicTrailingSLManager(
            broker=broker,
            config=trailing_config,
        )
        logger.info("[ENGINE] Trailing SL Manager initialized")


    async def run(self):
        """Main trading loop WITH trailing SL updates."""
        self.state.is_running = True
        logger.info("[ENGINE] Starting trading loop...")

        while self.state.is_running:
            try:
                if not self._check_trading_allowed():
                    await asyncio.sleep(60)
                    continue

                # Update market data
                await self._load_market_data()

                # Generate signals
                signals = self.strategy_manager.generate_signals(self.market_data)

                # Process signals
                await self._process_signals(signals)

                # Update positions
                await self._update_positions()

                # ===== NEW: Update trailing stops =====
                await self._update_trailing_stops()

                # Monitor risk
                self._monitor_risk()

                # ===== NEW: Log diagnostics periodically =====
                if int(time.time()) % 300 == 0:  # Every 5 minutes
                    self.trailing_sl_manager.log_diagnostics()

                # Sleep before next iteration
                await asyncio.sleep(60)

            except Exception as e:
                logger.error(f"[ENGINE] Error in trading loop: {e}")
                await asyncio.sleep(60)


    async def _process_signals(self, signals: Dict):
        """Process strategy signals WITH trailing SL tracking."""
        for symbol, signal in signals.items():
            if signal.value == "HOLD":
                continue

            if symbol not in self.market_data:
                continue

            data = self.market_data[symbol]
            current_price = data['close'].iloc[-1]

            try:
                pos_size = self.risk_manager.calculate_position_size(...)
            except:
                continue

            risk_levels = self.risk_manager.calculate_stops_and_targets(...)

            order_id = await self.execution_engine.submit_market_order(
                symbol=symbol,
                direction=signal.value,
                quantity=pos_size.quantity,
                stop_loss=risk_levels.stop_loss,
                take_profit=risk_levels.take_profit,
                comment="Signal from engine"
            )

            if order_id:
                logger.info(f"[ENGINE] Order submitted: {order_id}")

                # ===== NEW: Track position for trailing SL =====
                self.trailing_sl_manager.track_position(
                    ticket=order_id,
                    symbol=symbol,
                    side=signal.value,  # "BUY" or "SELL"
                    entry_price=current_price,
                    current_sl=risk_levels.stop_loss,
                )
                logger.info(
                    f"[TRAILING_SL] Position tracked | {symbol} {signal.value} | "
                    f"Entry: {current_price:.5f} | SL: {risk_levels.stop_loss:.5f}"
                )


    # ===== NEW: Add this method =====
    async def _update_trailing_stops(self):
        """Update trailing stops for all open positions."""
        try:
            for symbol in self.config.data.pairs:
                if symbol not in self.market_data:
                    continue

                data = self.market_data[symbol]
                if len(data) == 0:
                    continue

                current_price = data["close"].iloc[-1]

                # Update trailing SL for all positions in this symbol
                tracked_positions = self.trailing_sl_manager.get_all_positions()

                for ticket, state in tracked_positions.items():
                    if state.symbol == symbol:
                        modified, reason = await self.trailing_sl_manager.update_trailing_sl(
                            ticket=ticket,
                            current_price=current_price,
                        )

                        if modified:
                            logger.info(
                                f"[TRAILING_SL_UPDATE] {symbol} | Ticket: {ticket} | "
                                f"Price: {current_price:.5f} | {reason}"
                            )

        except Exception as e:
            logger.error(f"Error updating trailing stops: {e}")


    async def _update_positions(self):
        """Update open positions WITH trailing SL cleanup."""
        for symbol, data in self.market_data.items():
            if len(data) == 0:
                continue

            current_price = data['close'].iloc[-1]

            for trade_id, trade in list(self.portfolio.trades.items()):
                if trade.symbol == symbol:
                    self.portfolio.update_position(trade_id, current_price)

                    # Check stop loss
                    if trade.direction == "BUY" and current_price <= trade.stop_loss:
                        await self.execution_engine.close_position(trade_id)
                        self.portfolio.close_position(trade_id, current_price, "SL")

                        # ===== NEW: Stop tracking this position =====
                        state = self.trailing_sl_manager.untrack_position(trade_id)
                        if state:
                            logger.info(
                                f"[TRAILING_SL_CLOSED] {symbol} | Ticket: {trade_id} | "
                                f"Total modifications: {state.total_modifications} | "
                                f"Profit locked: {state.profit_locked_at_price is not None}"
                            )

                    elif trade.direction == "SELL" and current_price >= trade.stop_loss:
                        await self.execution_engine.close_position(trade_id)
                        self.portfolio.close_position(trade_id, current_price, "SL")

                        # ===== NEW: Stop tracking this position =====
                        state = self.trailing_sl_manager.untrack_position(trade_id)
                        if state:
                            logger.info(
                                f"[TRAILING_SL_CLOSED] {symbol} | Ticket: {trade_id} | "
                                f"Total modifications: {state.total_modifications} | "
                                f"Profit locked: {state.profit_locked_at_price is not None}"
                            )

                    # Check take profit
                    elif trade.direction == "BUY" and current_price >= trade.take_profit:
                        await self.execution_engine.close_position(trade_id)
                        self.portfolio.close_position(trade_id, current_price, "TP")

                        # ===== NEW: Stop tracking this position =====
                        state = self.trailing_sl_manager.untrack_position(trade_id)
                        if state:
                            logger.info(
                                f"[TRAILING_SL_CLOSED] {symbol} | Ticket: {trade_id} | TP hit"
                            )

                    elif trade.direction == "SELL" and current_price <= trade.take_profit:
                        await self.execution_engine.close_position(trade_id)
                        self.portfolio.close_position(trade_id, current_price, "TP")

                        # ===== NEW: Stop tracking this position =====
                        state = self.trailing_sl_manager.untrack_position(trade_id)
                        if state:
                            logger.info(
                                f"[TRAILING_SL_CLOSED] {symbol} | Ticket: {trade_id} | TP hit"
                            )


    async def shutdown(self):
        """Shutdown WITH trailing SL report."""
        logger.info("[ENGINE] Shutting down...")

        # ===== NEW: Report on trailing SL =====
        logger.info("[ENGINE] ===== Trailing SL Report =====")
        for ticket, state in self.trailing_sl_manager.get_all_positions().items():
            logger.info(
                f"  Position {ticket} ({state.symbol} {state.side}): "
                f"{state.total_modifications} SL modifications | "
                f"Profit locked: {state.profit_locked_at_price is not None}"
            )

        # Existing shutdown logic
        if self.engine:
            await self.engine.shutdown()

        if self.broker:
            await self.broker.disconnect()

        logger.info("[ENGINE] Shutdown complete")


# ============================================================================
# SUMMARY OF CHANGES
# ============================================================================

changes = {
    "__init__": {
        "added": "Initialize DynamicTrailingSLManager with TrailingConfig",
        "lines": 3,
    },
    "run": {
        "added": "Call _update_trailing_stops() in main loop + log diagnostics",
        "lines": 4,
    },
    "_process_signals": {
        "added": "Track position after order submission",
        "lines": 6,
    },
    "_update_trailing_stops": {
        "added": "NEW METHOD: Update trailing SL for all positions",
        "lines": 25,
    },
    "_update_positions": {
        "added": "Untrack position when closed",
        "lines": 8,
    },
    "shutdown": {
        "added": "Report on trailing SL statistics",
        "lines": 8,
    },
}

total_changes = sum(c["lines"] for c in changes.values())
print(f"Total changes: ~{total_changes} lines of code")
print(f"Files modified: 1 (core/engine.py)")
print(f"Files added: 2 (src/trading/dynamic_trailing_sl_manager.py + integration guide)")


# ============================================================================
# EXPECTED BEHAVIOR CHANGES
# ============================================================================

behaviors = {
    "Before": {
        "Entry": "1.0850, SL: 1.0800",
        "At +25 pips (1.0875)": "SL still at 1.0800 (no trailing)",
        "Reversal to 1.0840": "SL hit at 1.0800 = -50 pips loss",
        "Profit saved": "NONE - watched +25 turn into -50",
    },
    "After": {
        "Entry": "1.0850, SL: 1.0800",
        "At +25 pips (1.0875)": "SL trails to 1.0820, profit lock triggers SL->1.0851",
        "Reversal to 1.0840": "SL hit at 1.0851 = +1 pip profit",
        "Profit saved": "+25 (entry to high) vs +1 (entry to close) = strategy effectiveness",
    },
}

print("\n" + "="*70)
print("BEHAVIOR COMPARISON")
print("="*70)
for scenario, details in behaviors.items():
    print(f"\n{scenario}:")
    for point, value in details.items():
        print(f"  {point}: {value}")
