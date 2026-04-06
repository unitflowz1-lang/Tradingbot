"""
AI Forex Trading Bot - Main Entry Point
Three-Layer Architecture: Learning, Execution, Risk Control
With Live Trading Improvements: Margin Management, Slippage Tracking, Equity Sizing
"""
import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Dict
from dataclasses import dataclass, field

from src.config import ConfigManager
import json
from src.data.mt5_broker import create_mt5_broker
from src.trading.execution_engine import ExecutionEngine
from src.trading.position_manager import PositionManager
from src.strategies.trend_strategy import SimpleTrendStrategy
from src.risk.risk_calculator import RiskCalculator, RiskConfig
from src.risk.sl_tp_calculator import StopLossTakeProfitCalculator
from src.health_check import HealthChecker
from src.logging_config import setup_logging

# Three-Layer Architecture Imports
from src.trading.trade_manager import TradeManagementLayer, TradeManagementConfig
from src.trading.exit_reason import ExitReason, ExitLogger
from src.risk.risk_governor import RiskGovernor, RiskGovernorConfig
from src.analysis.training_data_filter import TrainingDataFilter, TrainingDataValidator


# ============================================================================
# LIVE TRADING IMPROVEMENTS - Dataclasses
# ============================================================================

@dataclass
class SlippageProfile:
    """Track slippage statistics for better TP/SL estimation"""
    symbol: str
    avg_slippage: float = 0.0
    slippage_count: int = 0
    expected_slippage_pips: float = 1.0
    
    def update_slippage(self, expected: float, actual: float):
        """Update slippage statistics"""
        self.slippage_count += 1
        diff = abs(actual - expected) / 0.0001  # Convert to pips
        self.avg_slippage = ((self.avg_slippage * (self.slippage_count - 1)) + diff) / self.slippage_count
    
    def get_adjusted_sl(self, base_sl: float, direction: str) -> float:
        """Adjust SL for expected slippage (extra buffer below)"""
        adjustment = self.avg_slippage * 1.5 * 0.0001  # 1.5x multiplier for safety
        if direction.upper() == "BUY":
            return base_sl - adjustment
        else:
            return base_sl + adjustment
    
    def get_adjusted_tp(self, base_tp: float, direction: str) -> float:
        """Adjust TP for expected slippage (conservative)"""
        adjustment = self.avg_slippage * 0.5 * 0.0001  # Conservative
        if direction.upper() == "BUY":
            return base_tp - adjustment
        else:
            return base_tp + adjustment


@dataclass
class DynamicMarginManager:
    """Manage margin with dynamic safety buffers"""
    account_equity: float
    used_margin: float
    max_margin_percent: float = 80.0
    safety_buffer_percent: float = 20.0
    
    @property
    def available_margin(self) -> float:
        """Margin available for new positions"""
        max_allowed = self.account_equity * (self.max_margin_percent / 100)
        return max_allowed - self.used_margin
    
    @property
    def margin_utilization(self) -> float:
        """Current margin utilization percentage"""
        if self.account_equity == 0:
            return 0
        return (self.used_margin / self.account_equity) * 100
    
    @property
    def can_open_position(self) -> tuple:
        """Check if new position can be opened safely"""
        threshold = self.max_margin_percent - self.safety_buffer_percent
        if self.margin_utilization > threshold:
            return False, f"Margin {self.margin_utilization:.1f}% > {threshold:.1f}% limit"
        return True, "OK"
    
    def get_position_size_recommendation(self, equity: float) -> float:
        """Equity-based position sizing - 2% of equity per trade"""
        return (equity * 0.02) / 100  # Returns lot size for standard position


async def run_bot():
    """Main bot execution loop"""
    # 1. Setup Logging & Config
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("[INIT] 🚀 AI Forex Trading Bot Starting...")

    env = os.environ.get('ENVIRONMENT', 'mt5')
    config_manager = ConfigManager(env)
    config = config_manager.get_config()
    
    # LOAD OPTIMIZED CONFIG
    opt_config = {}
    try:
        opt_path = os.path.join("config", "optimized_config.json")
        if os.path.exists(opt_path):
            with open(opt_path, "r") as f:
                opt_config = json.load(f)
            logger.info(f"[INIT] ⚡ Loaded OPTIMIZED settings from {opt_path}")
    except Exception as e:
        logger.error(f"[INIT] Failed to load optimized config: {e}")

    # 2. Initialize Health Check
    health_checker = HealthChecker()
    await health_checker.start()

    # 3. Initialize MT5 Broker
    logger.info("Initializing MT5 Broker...")
    broker = create_mt5_broker(
        login=config.broker.login,
        password=config.broker.password,
        server=config.broker.server
    )

    connected = await broker.connect()
    if not connected:
        logger.error("❌ Failed to connect to MT5. Exiting.")
        return

    logger.info("--------------------------------------------------")
    logger.info("[OK] AI TRADING BOT ACTIVATED | v2.1.0")
    logger.info("--------------------------------------------------")
    logger.info("[OK] Mode: ACTIVE TRADING")
    logger.info("[OK] Strategy: TREND FOLLOWING + ML")
    logger.info("[OK] Feature: MAXOUT MODE [ON] (Aggressive Scaling)")
    logger.info("[OK] Feature: AUTO-TRAIL [ON] (Dynamic Stop Loss)")
    logger.info("[OK] Feature: SECURE PROFIT [ON] (Bank Gains > $50)")
    logger.info("[OK] Feature: PARTIAL PROFIT [ON] (Multi-stage exits)")
    logger.info("[OK] Feature: TIME EXIT [ON] (Close stagnated trades)")
    logger.info("[OK] Feature: LIVE IMPROVEMENTS [ON] (Margin, Slippage, Sizing)")
    logger.info("--------------------------------------------------")

    # 4. Initialize Components
    execution_engine = ExecutionEngine(broker)
    
    # Initialize Live Trading Improvements
    logger.info("[INIT] Initializing live trading improvements...")
    slippage_profiles = {
        "EUR/USD": SlippageProfile("EUR/USD"),
        "GBP/USD": SlippageProfile("GBP/USD"),
        "USD/JPY": SlippageProfile("USD/JPY"),
        "AUD/USD": SlippageProfile("AUD/USD"),
    }
    
    # Use Optimized Values
    opt_trading = opt_config.get('trading', {})
    opt_risk = opt_config.get('risk', {})

    margin_manager = DynamicMarginManager(
        account_equity=10000.0,
        used_margin=0.0,
        max_margin_percent=opt_risk.get('max_margin_percent', 85.0),
        safety_buffer_percent=opt_risk.get('safety_buffer_percent', 15.0)
    )
    logger.info("[OK] Live trading improvements initialized ✓")
    position_manager = PositionManager(broker, execution_engine)
    position_manager.set_daily_loss_limit(opt_risk.get('max_daily_loss', 500.0))
    
    sl_tp_calculator = StopLossTakeProfitCalculator(
        atr_period=int(opt_trading.get('atr_period', 14)),
        risk_reward_ratio=float(opt_trading.get('risk_reward_ratio', 2.0))
    )
    
    risk_config = RiskConfig(
        max_portfolio_risk=config.risk.max_position_size,
        max_positions=config.trading.max_positions
    )
    risk_calculator = RiskCalculator(risk_config)

    # 5. Initialize Three-Layer Architecture
    logger.info("[INIT] Initializing Three-Layer Architecture...")
    
    # Layer 3: Risk Governor (System-level safety)
    risk_governor = RiskGovernor(
        config=RiskGovernorConfig(
            max_daily_loss=500.0,               # $500 daily loss limit
            max_daily_profit=2000.0,            # $2000 profit target
            max_daily_trades=5,                 # 5 trades per day max
            max_drawdown_percent=15.0,          # 15% drawdown max
            max_concurrent_positions=config.trading.max_positions,
            max_positions_per_symbol=1,
            min_margin_percent=20.0,
        )
    )
    
    # Layer 2: Trade Management (Administrative decisions)
    trade_manager = TradeManagementLayer(
        config=TradeManagementConfig(
            use_trailing_stop=True,
            trailing_stop_trigger_pips=20,
            trailing_stop_move_pips=15,
            use_equity_lock=True,
            equity_lock_levels=[(10, 0.20), (20, 0.20), (35, 0.15)],
            use_time_exit=True,
            max_hold_time_minutes=480,
            time_exit_loss_threshold_pips=-10,
            use_breakeven_stop=True,
            breakeven_trigger_pips=15,
            breakeven_offset_pips=2,
        )
    )
    
    # Training data filtering (For clean ML learning)
    training_filter = TrainingDataFilter()
    training_validator = TrainingDataValidator()

    logger.info("[INIT] Three-Layer Architecture initialized ✅")

    # Define symbols to trade
    symbols = ["EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD"]
    
    # Configure Filters
    opt_filters = opt_config.get('signal_filters', {})
    entry_filters = {
        'adx_min': opt_filters.get('adx_min', 12),
        'rsi_min': opt_filters.get('rsi_min', 25),
        'rsi_max': opt_filters.get('rsi_max', 75),
        'ml_confidence_min': opt_filters.get('ml_confidence_min', 0.50),
        'signal_quality_min': opt_filters.get('signal_quality_min', 0.55)
    }
    
    strategies = {symbol: SimpleTrendStrategy(symbol, entry_filters=entry_filters)
                  for symbol in symbols}
    last_candle_times: Dict[str, datetime] = {
        symbol: datetime.fromtimestamp(0, tz=timezone.utc)
        for symbol in symbols
    }

    logger.info("[INIT] Bot initialization complete | Symbols: %s",
                symbols)
    # Use naive datetime for MT5 history calls as the library expects local terminal time
    last_history_check = datetime.now()
    cycle_count = 0
    consecutive_idle = 0

    # 5. Main Loop
    try:
        while True:
            cycle_count += 1
            # Track positions closed this cycle to prevent double-close attempts
            closed_this_cycle = set()
            
            # Only log cycle start every 10 cycles if idle to reduce
            # noise
            if consecutive_idle == 0 or cycle_count % 10 == 0:
                logger.info("[STATS] --- [CYCLE %d] ---", cycle_count)

            # Check for closed trades (PnL monitoring)
            try:
                current_time = datetime.now()
                deals = await broker.get_deal_history(last_history_check,
                                                      current_time)
                for deal in deals:
                    # Filter out deals before our initial start time
                    if deal['time'].replace(tzinfo=None) <= last_history_check:
                        continue
                        
                    pnl = deal['profit']
                    pnl_color = "\033[92m" if pnl >= 0 else "\033[91m"
                    pnl_sign = "+" if pnl >= 0 else "-"
                    pnl_str = (f"{pnl_color}{pnl_sign}${abs(pnl):.2f}"
                               f"\033[0m")
                    logger.info("[CLOSE] %s | PnL: %s | ID: %s",
                                deal['symbol'], pnl_str,
                                deal['position_id'])
                    # Reset idle on activity
                    consecutive_idle = 0
                last_history_check = current_time
            except Exception as e:
                logger.error("[ERROR] History check failed: %s", e)

            # Update Portfolio Info
            try:
                portfolio = await broker.get_account_info()
                risk_calculator.update_equity_curve(portfolio)
                
                # UPDATE LIVE TRADING IMPROVEMENTS
                margin_manager.account_equity = portfolio.equity
                margin_manager.used_margin = portfolio.margin_used
                
                # MARGIN CHECK: Can we open new positions?
                can_trade, margin_reason = margin_manager.can_open_position
                if not can_trade:
                    logger.warning("[MARGIN] %s - Skipping signal generation", margin_reason)
                
                # CIRCUIT BREAKER: If margin is critically low, STOP THE BOT
                CRITICAL_MARGIN_THRESHOLD = 200.0
                if portfolio.margin_available < CRITICAL_MARGIN_THRESHOLD:
                    logger.critical(
                        "=" * 60
                    )
                    logger.critical(
                        "[CIRCUIT BREAKER] MARGIN CRITICALLY LOW: $%.2f",
                        portfolio.margin_available
                    )
                    logger.critical(
                        "Bot is HALTING to prevent further margin issues."
                    )
                    logger.critical(
                        "Please manually close positions in MT5 and restart the bot."
                    )
                    logger.critical(
                        "=" * 60
                    )
                    # Stop the bot
                    break
                
                # Reduced logging for balance
                if cycle_count % 5 == 0 or consecutive_idle == 0:
                    logger.info(
                        "[STATS] Balance: %.2f | Equity: %.2f | "
                        "Active: %d | Margin: %.2f | Util: %.1f%%",
                        portfolio.balance, portfolio.equity,
                        len(portfolio.positions), portfolio.margin_available,
                        margin_manager.margin_utilization)
                
                # EMERGENCY: Check for position limit exceeded (MT5 10040 error)
                if len(portfolio.positions) > config.trading.max_positions:
                    logger.critical(
                        "🚨 POSITION LIMIT EXCEEDED! Current: %d | Max: %d | "
                        "CLOSING EXCESS POSITIONS IMMEDIATELY!",
                        len(portfolio.positions), config.trading.max_positions
                    )
                    # Close oldest losing positions first to get below limit
                    excess_count = len(portfolio.positions) - config.trading.max_positions
                    positions_to_close = sorted(
                        [p for p in portfolio.positions if p.unrealized_pnl < 0],
                        key=lambda p: p.opened_at  # Oldest first
                    )[:excess_count]
                    
                    for position in positions_to_close:
                        if position.position_id in closed_this_cycle:
                            continue  # Already closed
                        logger.warning(
                            f"[EMERGENCY CLOSE] {position.symbol} | Ticket: {position.position_id} | "
                            f"Loss: ${position.unrealized_pnl:.2f}"
                        )
                        try:
                            await broker.close_position(position.position_id)
                            closed_this_cycle.add(position.position_id)
                        except Exception as e:
                            logger.warning(f"Position {position.position_id} already closed: {e}")
                            closed_this_cycle.add(position.position_id)
                        await asyncio.sleep(0.5)  # Small delay between closes
                    
                    # If still over limit, close ANY positions until we're below
                    # Refresh portfolio to get updated position list
                    portfolio = await broker.get_account_info()
                    while len(portfolio.positions) > config.trading.max_positions:
                        # Find oldest position that hasn't been closed this cycle
                        remaining = [p for p in portfolio.positions if p.position_id not in closed_this_cycle]
                        if not remaining:
                            break  # All positions already attempted
                        oldest = min(remaining, key=lambda p: p.opened_at)
                        logger.critical(f"[FORCE CLOSE] {oldest.symbol} | Ticket: {oldest.position_id}")
                        try:
                            await broker.close_position(oldest.position_id)
                            closed_this_cycle.add(oldest.position_id)
                        except Exception as e:
                            logger.warning(f"[FORCE CLOSE] Position {oldest.position_id} already closed or error: {e}")
                            closed_this_cycle.add(oldest.position_id)  # Mark as handled
                        await asyncio.sleep(0.5)
                        # Refresh portfolio
                        portfolio = await broker.get_account_info()
                
                # EMERGENCY: Check for negative margin (margin call)
                if portfolio.margin_available < 0:
                    logger.error(
                        "🚨 MARGIN CALL! Margin available: $%.2f | "
                        "Closing all losing positions immediately!",
                        portfolio.margin_available
                    )
                    # Close all LOSING positions to recover margin
                    for position in portfolio.positions:
                        if position.unrealized_pnl < 0:  # Only close losers
                            logger.warning(f"[EMERGENCY CLOSE] {position.symbol} | Loss: ${position.unrealized_pnl:.2f}")
                            await broker.close_position(position.position_id)
                    # Skip rest of cycle and re-check margin
                    await asyncio.sleep(2)
                    return
                
                # Log position stats
                position_manager.log_position_stats({
                    'positions': [
                        {
                            'unrealized_pnl': p.unrealized_pnl
                        } for p in portfolio.positions
                    ]
                })
                
                # Check if daily loss limit exceeded
                if await position_manager.check_daily_loss_limit():
                    logger.warning(
                        "⚠️  DAILY LOSS LIMIT EXCEEDED! "
                        "Stopping new trades for today."
                    )
                    # Can still close positions but won't open new ones
                
                # LAYER 2 & 1: Trade Manager - Check ALL exit conditions for open positions
                # This includes: manual closes, trailing stops, equity locks, time exits, market exits
                for position in portfolio.positions[:]:  # Copy list to avoid modification during iteration
                    position_closed = False
                    
                    # Check manual closes first
                    should_close_manual, reason = trade_manager.check_manual_close(position)
                    if should_close_manual:
                        await broker.close_position(position.position_id)
                        trade_manager.record_exit(position, position.current_price, reason, was_manual=True)
                        logger.info(f"[ADMIN EXIT] {position.symbol} | Reason: {reason.value}")
                        position_closed = True
                    
                    if position_closed:
                        continue
                    
                    # Check equity locks (partial profit taking)
                    should_close_equity, reason = trade_manager.check_equity_lock(position)
                    if should_close_equity:
                        await broker.close_position(position.position_id)
                        trade_manager.record_exit(position, position.current_price, reason)
                        logger.info(f"[ADMIN EXIT] {position.symbol} | Reason: {reason.value}")
                        position_closed = True
                    
                    if position_closed:
                        continue
                    
                    # Check time-based exits
                    should_close_time, reason = trade_manager.check_time_exit(position)
                    if should_close_time:
                        await broker.close_position(position.position_id)
                        trade_manager.record_exit(position, position.current_price, reason)
                        logger.info(f"[ADMIN EXIT] {position.symbol} | Reason: {reason.value}")
                        position_closed = True
                    
                    if position_closed:
                        continue
                
                # Check and close positions with exit conditions (every cycle)
                # BUT: Skip if margin is critically low (position_manager causes 10019 errors)
                closing_trouble = False
                if portfolio.margin_available < 500:
                    closing_trouble = True
                
                if not closing_trouble:
                    try:
                        portfolio_dict = {
                            'positions': [
                                {
                                    'position_id': p.position_id,
                                    'symbol': p.symbol,
                                    'current_price': p.current_price,
                                    'entry_price': p.entry_price,
                                    'direction': p.direction,
                                    'stop_loss': p.stop_loss,
                                    'take_profit': p.take_profit,
                                    'quantity': p.quantity,
                                    'unrealized_pnl': p.unrealized_pnl,
                                    'open_time': p.opened_at
                                } for p in portfolio.positions
                            ]
                        }
                        closed = await position_manager.check_and_close_positions(
                            portfolio_dict
                        )
                        if closed:
                            consecutive_idle = 0
                    except Exception as e:
                        logger.error("[ERROR] Position closing check failed: %s", e)
                else:
                    logger.warning(
                        "[DANGER] Margin critically low: $%.2f | "
                        "Skipping normal exit checks, entering emergency recovery mode",
                        portfolio.margin_available
                    )

                any_activity = False
                
                # Track if we're having trouble closing positions (MT5 10019 errors)
                if closing_trouble:

                    # Try to force close ALL positions (not just exit condition matches)
                    for position in portfolio.positions[:5]:  # Close top 5 positions
                        if position.position_id in closed_this_cycle:
                            continue  # Already closed this cycle
                        try:
                            logger.warning(f"[FORCE CLOSE] {position.symbol} | Qty: {position.quantity}")
                            await broker.close_position(position.position_id)
                            closed_this_cycle.add(position.position_id)
                            await asyncio.sleep(0.5)  # Small delay between closes
                        except Exception as close_err:
                            logger.warning(f"[FORCE CLOSE] Position {position.position_id} already closed or failed: {close_err}")
                            closed_this_cycle.add(position.position_id)

                
                # Define async function to analyze each symbol concurrently
                async def analyze_and_trade_symbol(symbol):
                    nonlocal any_activity, closing_trouble
                    try:
                        # Fetch historical data
                        historical_data = (
                            await broker.get_historical_data(
                                symbol, timeframe=16385, count=150))
                        if not historical_data:
                            return
                    except Exception as e:
                        logger.error(f"[ERROR] Could not fetch data for {symbol}: {e}")
                        return
                    
                    # If margin is critically low, don't open ANY new positions
                    if closing_trouble or portfolio.margin_available < 500:
                        logger.debug(f"[SKIP NEW TRADES] Margin critical: ${portfolio.margin_available:.2f} | Focus on closing positions")
                        return

                    last_bar_time = historical_data[-1].timestamp
                    # DITCHED: We no longer return early if it's the same bar. 
                    # This allows the bot to catch intra-candle signals and stack positions faster.
                    
                    any_activity = True
                    logger.info(
                        "[ANALYSIS] Examining %s | Time: %s | Bars: %d",
                        symbol, last_bar_time.strftime('%H:%M'),
                        len(historical_data))

                    # Check if we already have a position in this symbol
                    # Check if we already have max positions in this symbol (Pyramiding)
                    # Conservative limit to prevent margin exhaustion
                    MAX_POSITIONS_PER_SYMBOL = 3  # Reduced from 10
                    current_symbol_positions = [
                        pos for pos in portfolio.positions 
                        if pos.symbol.replace("/", "") == symbol.replace("/", "")
                    ]
                    
                    if len(current_symbol_positions) >= MAX_POSITIONS_PER_SYMBOL:
                        logger.debug(f"[SKIP] Max positions ({MAX_POSITIONS_PER_SYMBOL}) reached for {symbol}")
                        return
                        
                    # Prevent opening multiple positions on the same candle/timeframe closely
                    # if we have a recent position
                    if current_symbol_positions:
                        # Calculate total PnL for this symbol to decide on aggression
                        symbol_pnl = sum(p.unrealized_pnl for p in current_symbol_positions)
                        
                        last_pos = max(current_symbol_positions, key=lambda p: p.opened_at)
                        time_since_last = datetime.now(timezone.utc) - last_pos.opened_at
                        
                        # Aggressive "Maxout" Logic:
                        # If we are profitable (> 0), we stack faster (every 1 min).
                        # If we are losing or flat, we wait longer (5 mins).
                        cooldown_seconds = 60 if symbol_pnl > 0 else 300
                        
                        if time_since_last.total_seconds() < cooldown_seconds:
                             if cycle_count % 6 == 0: # Log every 1 min approx
                                 cooldown_rem = int(cooldown_seconds - time_since_last.total_seconds())
                                 logger.debug(f"[COOLDOWN] {symbol} waiting {cooldown_rem}s more. (Total PnL: ${symbol_pnl:.2f})")
                             return

                    # Run Strategy Analysis
                    strategy = strategies[symbol]
                    signal = await strategy.analyze(historical_data)

                    if signal:
                        # LIVE IMPROVEMENT: Check margin before processing
                        if not can_trade:
                            return
                        
                        # Calculate intelligent stop loss and take profit
                        levels_result = sl_tp_calculator.calculate_levels(
                            entry_price=signal.entry_price,
                            direction=signal.direction,
                            historical_data=historical_data
                        )
                        if isinstance(levels_result, dict):
                            stop_loss = levels_result.get("stop_loss")
                            take_profit = levels_result.get("take_profit")
                            if stop_loss is None or take_profit is None:
                                raise ValueError(
                                    f"SL/TP calculator returned dict without stop_loss/take_profit for {symbol}"
                                )
                        else:
                            stop_loss, take_profit = levels_result
                        
                        # LIVE IMPROVEMENT: Apply slippage adjustments
                        slippage_profile = slippage_profiles.get(symbol)
                        if slippage_profile and slippage_profile.slippage_count > 5:
                            # Only apply adjustments after 5+ trades
                            stop_loss = slippage_profile.get_adjusted_sl(stop_loss, signal.direction.value)
                            take_profit = slippage_profile.get_adjusted_tp(take_profit, signal.direction.value)
                        
                        logger.info(
                            "[SIGNAL] %s | %s | Entry=%.5f | SL=%.5f | TP=%.5f | Confidence=%.2f",
                            symbol, signal.direction.value,
                            signal.entry_price,
                            stop_loss,
                            take_profit,
                            signal.confidence if hasattr(signal, 'confidence') else 0.5)
                        
                        logger.info(
                            "[DECISION] %s | %s @ %.5f | SL: %.5f | "
                            "TP: %.5f",
                            symbol, signal.direction.value,
                            signal.entry_price,
                            stop_loss,
                            take_profit)

                        # Run Risk Assessment
                        assessment = (
                            risk_calculator.assess_trade_risk(
                                signal, portfolio))

                        # Check daily loss limit before opening
                        exceeds_daily_limit = (
                            await position_manager.check_daily_loss_limit()
                        )
                        # LAYER 3: Risk Governor Check (System-level safety)
                        trades_allowed, risk_halt_reason = risk_governor.check_trading_allowed(portfolio)
                        if not trades_allowed:
                            logger.warning("[RISK GOVERNOR] %s", risk_halt_reason)
                            return  # Skip signal due to risk limits
                        
                        # Check for emergency conditions
                        should_force_close, emergency_reason = risk_governor.check_emergency_close(portfolio)
                        if should_force_close:
                            logger.critical("[RISK GOVERNOR EMERGENCY] %s - Force closing positions", emergency_reason)
                            for pos in risk_governor.get_forced_close_positions(portfolio, emergency_reason):
                                await broker.close_position(pos.position_id)
                                trade_manager.record_exit(pos, pos.current_price, ExitReason.RISK_HALT_DAILY)
                                await asyncio.sleep(0.3)
                            return  # Skip opening new trades
                        
                        # NEW: Check if we're at max positions limit (CRITICAL FIX)
                        if len(portfolio.positions) >= config.trading.max_positions:
                            logger.warning(
                                "[SKIP] Max positions reached! Current: %d / Max: %d",
                                len(portfolio.positions), config.trading.max_positions
                            )
                            return  # Skip this signal and move to next symbol
                        
                        # Check margin availability - prevent trades if margin is too low
                        minimum_margin_buffer = 100.0  # Keep $100 margin buffer
                        if portfolio.margin_available < minimum_margin_buffer:
                            logger.warning(
                                "[SKIP] Low margin! Available: $%.2f (min: $%.2f) | "
                                "Not opening new positions",
                                portfolio.margin_available, minimum_margin_buffer
                            )
                            return
                        
                        if assessment.is_valid and not exceeds_daily_limit:
                            # LIVE IMPROVEMENT: Equity-based position sizing
                            # Uses 3% of current equity per trade (Aggressive)
                            equity_based_size = (portfolio.equity * 0.03) / 100
                            
                            # Dynamic Sizing based on Signal Confidence
                            base_lots = equity_based_size
                            confidence = signal.confidence if hasattr(signal, 'confidence') else 0.5
                            
                            # Scale up for high confidence
                            if confidence > 0.7:
                                base_lots *= 1.5
                            
                            final_lots = max(0.01, round(base_lots, 2))
                            
                            # Cap based on optimized config
                            pos_cap = opt_trading.get('position_size_cap', 0.3)
                            final_lots = min(final_lots, pos_cap)

                            logger.info(
                                "[ACTION] Risk OK | Score: %.2f | "
                                "RawSize: %.4f%% | EquitySize: %.4f | Final: %.2f lots",
                                assessment.risk_score,
                                assessment.position_size * 100,
                                equity_based_size,
                                final_lots)

                            # Execute Trade with calculated SL/TP
                            from src.models import (Order, OrderType,
                                                    OrderStatus)
                            order = Order(
                                order_id=(
                                    f"order_"
                                    f"{int(datetime.now().timestamp())}"
                                ),
                                symbol=symbol,
                                order_type=OrderType.MARKET,
                                direction=signal.direction,
                                quantity=final_lots,
                                price=signal.entry_price,
                                stop_loss=stop_loss,
                                take_profit=take_profit,
                                status=OrderStatus.PENDING,
                                created_at=datetime.now(timezone.utc)
                            )

                            result = (
                                await
                                execution_engine.execute_trade(order))
                            if result.success:
                                # LIVE IMPROVEMENT: Track slippage on fill
                                actual_entry = result.entry_price if hasattr(result, 'entry_price') else signal.entry_price
                                slippage_profiles[symbol].update_slippage(signal.entry_price, actual_entry)
                                
                                logger.info(
                                    "\033[92m[OPEN] %s | %s | Qty=%.3f lots | "
                                    "Entry=%.5f | SL=%.5f | TP=%.5f | Order: %s\033[0m",
                                    symbol, signal.direction.value,
                                    assessment.position_size,
                                    actual_entry,
                                    stop_loss,
                                    take_profit,
                                    result.order_id)
                                # Register trade opening with risk governor (tracks daily stats)
                                risk_governor.register_trade_opened(symbol)
                            else:
                                logger.error("[ACTION] FAILED: %s",
                                             result.error_message)
                        elif exceeds_daily_limit:
                            logger.warning(
                                "[WARN] Daily loss limit exceeded, "
                                "skipping new trades"
                            )
                        else:
                            logger.warning(
                                "[WARN] Risk denied: %s",
                                ', '.join(assessment.warnings))

                # Run all symbol analysis concurrently
                await asyncio.gather(*[analyze_and_trade_symbol(sym) for sym in symbols])

                # Log Three-Layer Architecture Status
                exit_summary = trade_manager.get_exit_summary()
                risk_status = risk_governor.get_status()
                
                if cycle_count % 5 == 0:  # Log every 5 cycles to reduce noise
                    logger.info(
                        "[SUMMARY] Risk: %s | Positions: %d | "
                        "Daily Trades: %d/%d | "
                        "Exits: %d (Market: %d, Admin: %d)",
                        risk_status['state'],
                        len(portfolio.positions),
                        risk_status['daily_trades'],
                        risk_status['daily_limit'],
                        exit_summary['total_exits'],
                        exit_summary['market_driven_exits'],
                        exit_summary['administrative_exits']
                    )

                if not any_activity:
                    consecutive_idle += 1
                else:
                    consecutive_idle = 0

            except Exception as e:
                logger.error("[ERROR] Cycle failed: %s", e)

            # Wait for next cycle
            if consecutive_idle == 0:
                logger.info("[IDLE] Waiting for next market pulse...")
            await asyncio.sleep(10)  # Reduced from 60s for faster multi-bet execution

    except asyncio.CancelledError:
        logger.info("Bot stopping...")
    finally:
        await broker.disconnect()
        await health_checker.stop()


if __name__ == "__main__":
    asyncio.run(run_bot())
