"""
Integration Guide: Dynamic Trailing SL with TradingEngine
===========================================================

This guide shows how to integrate DynamicTrailingSLManager into your
existing trading bot to automatically trail stop losses and lock profits.

PROBLEM: Positions oscillating ±1-3 pips without protection
SOLUTION: Intelligent trailing SL + profit locking + MT5 spam protection
"""

# ============================================================================
# STEP 1: Add to TradingEngine Initialization
# ============================================================================

# In core/engine.py, add to __init__:

from src.trading.dynamic_trailing_sl_manager import (
    DynamicTrailingSLManager,
    TrailingConfig,
)

class TradingEngine:
    def __init__(self, config: TradingConfig, broker: Broker, data_handler: DataHandler):
        """Initialize TradingEngine WITH trailing SL manager."""
        # ... existing code ...

        # NEW: Initialize dynamic trailing SL manager
        trailing_config = TrailingConfig(
            buffer_pips=5,  # Trail 5 pips behind price
            min_time_between_mods_seconds=5,  # At least 5 sec between mods
            min_pip_movement=0.001,  # At least 10 pips movement before mod
            enable_profit_lock=True,  # Enable profit locking
            profit_lock_threshold_pips=20,  # Lock SL after +20 pips profit
        )

        self.trailing_sl_manager = DynamicTrailingSLManager(
            broker=broker,
            config=trailing_config,
        )

        logger.info("[ENGINE] Trailing SL Manager initialized")


# ============================================================================
# STEP 2: Track Positions When Opened
# ============================================================================

# In _process_signals() or wherever you submit orders:

async def _process_signals(self, signals: Dict):
    """Process strategy signals."""
    for symbol, signal in signals.items():
        # ... existing order submission code ...

        if order_id:
            # NEW: Track this position for trailing SL
            self.trailing_sl_manager.track_position(
                ticket=order_id,
                symbol=symbol,
                side=signal.value,  # "BUY" or "SELL"
                entry_price=current_price,
                current_sl=risk_levels.stop_loss,
            )

            logger.info(
                f"Position tracked for trailing SL | "
                f"Ticket: {order_id} | {symbol} | {signal.value}"
            )


# ============================================================================
# STEP 3: Update Trailing SL in Main Loop (CRITICAL)
# ============================================================================

# In run() method, add trailing SL update:

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
            trailing_results = await self._update_trailing_stops()

            # Monitor risk
            self._monitor_risk()

            # Log trailing SL diagnostics periodically
            if int(time.time()) % 300 == 0:  # Every 5 minutes
                self.trailing_sl_manager.log_diagnostics()

            # Sleep before next iteration
            await asyncio.sleep(60)

        except Exception as e:
            logger.error(f"[ENGINE] Error in trading loop: {e}")
            await asyncio.sleep(60)


async def _update_trailing_stops(self) -> Dict:
    """Update trailing stops for all open positions."""
    try:
        results = {}

        for symbol in self.config.data.pairs:
            # Get current price
            if symbol not in self.market_data:
                continue

            data = self.market_data[symbol]
            current_price = data["close"].iloc[-1] if len(data) > 0 else None

            if not current_price:
                continue

            # Update trailing SL for all positions in this symbol
            tracked_positions = self.trailing_sl_manager.get_all_positions()

            for ticket, state in tracked_positions.items():
                if state.symbol == symbol:
                    modified, reason = await self.trailing_sl_manager.update_trailing_sl(
                        ticket=ticket,
                        current_price=current_price,
                    )

                    results[ticket] = (modified, reason)

                    if modified:
                        logger.info(
                            f"[TRAILING_SL] {symbol} | Ticket: {ticket} | "
                            f"Price: {current_price:.5f} | {reason}"
                        )

        return results

    except Exception as e:
        logger.error(f"Error updating trailing stops: {e}")
        return {}


# ============================================================================
# STEP 4: Stop Tracking When Position Closes
# ============================================================================

# In _update_positions(), when closing a position:

async def _update_positions(self):
    """Update open positions."""
    for symbol, data in self.market_data.items():
        current_price = data["close"].iloc[-1]

        for trade_id, trade in list(self.portfolio.trades.items()):
            if trade.symbol == symbol:
                # ... existing position update logic ...

                # Check stop loss
                if trade.direction == "BUY" and current_price <= trade.stop_loss:
                    await self.execution_engine.close_position(trade_id)
                    self.portfolio.close_position(trade_id, current_price, "SL")

                    # NEW: Stop tracking this position
                    state = self.trailing_sl_manager.untrack_position(trade_id)
                    if state:
                        logger.info(
                            f"[TRAILING_SL_CLOSED] {symbol} | {state.total_modifications} "
                            f"modifications during position lifetime"
                        )


# ============================================================================
# STEP 5: Report on Shutdown
# ============================================================================

# In shutdown():

async def shutdown(self):
    """Shutdown with trailing SL report."""
    logger.info("[ENGINE] Shutting down...")

    # NEW: Generate trailing SL report
    logger.info("[TRAILING_SL_REPORT] ===== Trailing SL Statistics =====")
    for ticket, state in self.trailing_sl_manager.get_all_positions().items():
        logger.info(
            f"  Position {ticket}:"
            f" {state.total_modifications} SL modifications"
            f" | Profit locked: {state.profit_locked_at_price is not None}"
        )

    # Continue normal shutdown...


# ============================================================================
# CONFIGURATION TUNING
# ============================================================================

# TrailingConfig parameters and their effects:

"""
buffer_pips:
    - How many pips to trail behind price
    - Lower (2-3): Tighter protection, may get hit more
    - Higher (5-10): Looser trail, keeps more profit
    - Recommendation: 5 pips for FX, 10 pips for crypto

min_time_between_mods_seconds:
    - Minimum time between SL modifications
    - Prevents ERR_TRADE_TOO_MANY_REQUESTS
    - Recommendation: 5-10 seconds (adjust if MT5 rejects)

min_pip_movement:
    - Minimum price movement before SL update
    - Prevents trivial modifications (saves API calls)
    - Recommendation: 10 pips (0.0001 for 5-decimal FX)

enable_profit_lock:
    - Automatically lock SL to break-even when in profit
    - Solves: "I was at +2 but let it reverse to -1"

profit_lock_threshold_pips:
    - Trigger profit lock after this many pips profit
    - Recommendation: 20-30 pips (depends on your pair)
"""


# ============================================================================
# EXAMPLE: Different Trading Strategies
# ============================================================================

# SCALP TRADING (tight stops, quick exits):
scalp_config = TrailingConfig(
    buffer_pips=2,  # Very tight
    min_time_between_mods_seconds=3,  # Quick updates
    min_pip_movement=0.0002,  # 2 pips movement triggers update
    enable_profit_lock=True,
    profit_lock_threshold_pips=5,  # Lock quick profits
)

# SWING TRADING (loose stops, hold longer):
swing_config = TrailingConfig(
    buffer_pips=10,  # Looser trail
    min_time_between_mods_seconds=30,  # Less frequent updates
    min_pip_movement=0.005,  # 50 pips movement before update
    enable_profit_lock=True,
    profit_lock_threshold_pips=50,  # Lock after bigger moves
)

# CRYPTO TRADING (adjust pip scale):
crypto_config = TrailingConfig(
    buffer_pips=10,  # 10 large pips
    min_time_between_mods_seconds=5,
    min_pip_movement=0.01,  # Crypto scales different
    enable_profit_lock=True,
    profit_lock_threshold_pips=100,  # Larger moves
)


# ============================================================================
# TROUBLESHOOTING
# ============================================================================

# Issue: "ERR_TRADE_TOO_MANY_REQUESTS"
# Solution: Increase min_time_between_mods_seconds (try 10-15 seconds)
code_example_time = """
trailing_config = TrailingConfig(
    min_time_between_mods_seconds=15,  # <- Increase this
)
"""

# Issue: SL keeps getting hit, position closed too early
# Solution: Increase buffer_pips or increase min_pip_movement
code_example_buffer = """
trailing_config = TrailingConfig(
    buffer_pips=10,  # <- Increase from 5
    min_pip_movement=0.002,  # <- Increase from 0.001
)
"""

# Issue: Profit not being locked
# Solution: Lower profit_lock_threshold_pips or enable_profit_lock=False issue
code_example_profit = """
trailing_config = TrailingConfig(
    enable_profit_lock=True,
    profit_lock_threshold_pips=10,  # <- Lower this (was 20)
)
"""


# ============================================================================
# MONITORING & ANALYSIS
# ============================================================================

# Get modification history for a position:
history = trailing_sl_manager.get_modification_history(ticket="12345")
# Returns list of:
# {
#     "timestamp": "2026-04-16T12:30:45",
#     "price": 1.0875,
#     "new_sl": 1.0825,
#     "old_sl": 1.0820,
#     "profit_pips": 25.0,
# }

# View all tracked positions:
positions = trailing_sl_manager.get_all_positions()
for ticket, state in positions.items():
    print(f"Ticket {ticket}:")
    print(f"  Symbol: {state.symbol}")
    print(f"  Modifications: {state.total_modifications}")
    print(f"  Profit locked: {state.profit_locked_at_price}")


# ============================================================================
# EXPECTED BEHAVIOR
# ============================================================================

"""
BEFORE (without trailing SL):
- Position enters at 1.0850 with SL at 1.0800
- Price moves to 1.0875 (+25 pips profit) ✓
- Price reverses to 1.0840 (-10 pips from high)
- Position closed at 1.0800 (SL hit) = -50 pips loss ✗
- Result: No profit lock, watch gains disappear

AFTER (with trailing SL + profit lock):
- Position enters at 1.0850 with SL at 1.0800
- Price moves to 1.0875 (+25 pips profit) ✓
- Trailing SL updates: 1.0800 -> 1.0820 (+5 pips buffer)
- Profit lock triggers: SL moves to 1.0851 (slight profit)
- Price reverses to 1.0840
- Position closed at 1.0851 (SL hit) = +1 pip profit ✓
- Result: Profit protected, escaped before reversal

SPAM PROTECTION in action:
- Price moves 0.0002 in 1 second: No SL update (time throttle)
- Price moves 0.0005 in 10 sec: Update sent (both checks pass)
- Price moves 0.0001 in 30 sec: No SL update (movement < min threshold)
- Price moves 0.001 in 30 sec: Update sent (all checks pass)
"""


# ============================================================================
# SUMMARY
# ============================================================================

"""
Integration steps:
1. Initialize DynamicTrailingSLManager in TradingEngine.__init__
2. Track positions when orders are submitted (_process_signals)
3. Update trailing SL in main loop (run -> _update_trailing_stops)
4. Untrack positions when closed (_update_positions)
5. Log statistics on shutdown (shutdown)

Key benefits:
✓ Automatically trail SL behind price
✓ Lock profit to break-even when in profit
✓ Prevent "watched profit evaporate" scenario
✓ MT5 spam protection (no ERR_TRADE_TOO_MANY_REQUESTS)
✓ Track modification history for analysis

Expected improvement:
- Positions won't oscillate -3 to +3 anymore
- Profit locked after +20 pips
- More closed positions at breakeven vs losses
- Better backtest/live trading stats
"""
