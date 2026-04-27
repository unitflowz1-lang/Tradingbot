"""
Example: Integrating APIResilienceController into TradingEngine
==============================================================

This is a minimal example showing how to modify core/engine.py to use
the APIResilienceController for automatic failover.

CHANGES NEEDED:
1. Import the resilience controller
2. Initialize it in __init__
3. Use it in _process_signals() to get adjusted position sizes
4. Log trade flags for audit
"""

import asyncio
import logging
from datetime import datetime, timedelta
import pandas as pd

from src.analysis.api_resilience_controller import (
    APIResilienceController,
    create_resilience_controller,
)
from src.analysis.finnhub_macro_manager import create_finnhub_manager

logger = logging.getLogger(__name__)


class ResilientTradingEngine:
    """
    Enhanced Trading Engine with API Resilience.

    Key additions:
    - APIResilienceController for macro data failover
    - Automatic position sizing reduction during API outages
    - Trade flagging for audit trail
    """

    def __init__(self, config, broker, data_handler, risk_manager):
        """Initialize with resilience controller."""
        self.config = config
        self.broker = broker
        self.data_handler = data_handler
        self.risk_manager = risk_manager

        # Resilience controller (to be initialized later)
        self.resilience_controller = None
        self.finnhub_manager = None

    async def initialize(self) -> bool:
        """
        Initialize the trading engine WITH resilience.

        Connects to broker, sets up macro monitoring, and initializes
        the APIResilienceController for automatic failover.
        """
        logger.info("[ENGINE] Initializing trading engine with resilience...")

        try:
            # Connect to broker (existing code)
            if not await self.broker.connect():
                logger.error("[ENGINE] Failed to connect to broker")
                return False

            # NEW: Initialize Finnhub macro manager
            self.finnhub_manager = create_finnhub_manager(
                symbols=self.config.data.pairs,
                macro_risk_cache=None,  # Or pass macro_risk_cache if you have it
            )

            if self.finnhub_manager:
                await self.finnhub_manager.start()
                logger.info("[ENGINE] ✓ Finnhub macro manager started")
            else:
                logger.warning("[ENGINE] ⚠ Finnhub macro manager not available")

            # NEW: Initialize resilience controller (wraps finnhub_manager)
            if self.finnhub_manager:
                self.resilience_controller = create_resilience_controller(
                    finnhub_manager=self.finnhub_manager,
                    risk_manager=self.risk_manager,
                )
                logger.info("[ENGINE] ✓ API Resilience Controller initialized")

                # Start monitoring health in background
                asyncio.create_task(self._monitor_resilience_health())
            else:
                logger.warning("[ENGINE] ⚠ Resilience controller not available (no macro manager)")

            logger.info("[ENGINE] Engine initialized successfully with resilience")
            return True

        except Exception as e:
            logger.error(f"[ENGINE] Initialization error: {e}")
            return False

    async def run(self):
        """Main trading loop WITH resilience-aware position sizing."""
        logger.info("[ENGINE] Starting trading loop with resilience...")

        while self.state.is_running:
            try:
                # Check if trading is allowed
                if not self._check_trading_allowed():
                    await asyncio.sleep(60)
                    continue

                # Update market data
                await self._load_market_data()

                # Generate signals (existing code)
                signals = self.strategy_manager.generate_signals(self.market_data)

                # Process signals WITH resilience
                await self._process_signals_with_resilience(signals)

                # Update positions
                await self._update_positions()

                # Monitor risk
                self._monitor_risk()

                # Sleep before next iteration
                await asyncio.sleep(60)

            except Exception as e:
                logger.error(f"[ENGINE] Error in trading loop: {e}")
                await asyncio.sleep(60)

    async def _process_signals_with_resilience(self, signals: dict):
        """
        Process strategy signals WITH resilience-aware position sizing.

        NEW: Uses APIResilienceController to adjust position sizes based
        on API health status.
        """
        try:
            # Aggregate signals per symbol
            aggregated = self.strategy_manager.aggregate_signals(signals)

            for symbol, signal in aggregated.items():
                if signal.value == "HOLD":
                    continue

                # Check if we should trade this symbol
                if symbol not in self.market_data:
                    continue

                # Get current price
                data = self.market_data[symbol]
                current_price = data["close"].iloc[-1]

                # ===== NEW: Get macro data WITH automatic failover =====
                macro_data = None
                if self.resilience_controller:
                    macro_data = await self.resilience_controller.get_macro_data(symbol)
                    logger.info(
                        f"[MACRO] {symbol} | Mode: {macro_data['mode']} | "
                        f"Risk: {macro_data['risk_score']:.1f}/10 | "
                        f"Freshness: {'✓' if macro_data['data_freshness_ok'] else '✗'}"
                    )

                # Calculate base position size (existing logic)
                try:
                    base_pos_size = self.risk_manager.calculate_position_size(
                        symbol,
                        current_price,
                        current_price - 0.005,  # Estimate SL for sizing
                        current_atr=self.symbol_atr.get(symbol),
                    )
                except Exception as e:
                    logger.error(f"Error calculating position size: {e}")
                    continue

                # ===== NEW: Get ADJUSTED position size from resilience controller =====
                adjusted_pos_size = base_pos_size.quantity
                trade_flags = None

                if self.resilience_controller:
                    adjusted_pos_size, trade_flags = await self.resilience_controller.get_adjusted_position_size(
                        symbol=symbol,
                        base_size=base_pos_size.quantity,
                    )

                # Calculate stops and targets (existing logic)
                risk_levels = self.risk_manager.calculate_stops_and_targets(
                    current_price,
                    signal.value,
                    current_atr=self.symbol_atr.get(symbol),
                )

                # ===== NEW: Include trade flags in order comment =====
                direction = signal.value
                trade_comment = (
                    f"Signal from {signal.strategy_name if hasattr(signal, 'strategy_name') else 'engine'}"
                )

                if trade_flags:
                    trade_comment += f" | {trade_flags.trade_comment}"

                # Submit order with ADJUSTED size
                order_id = await self.execution_engine.submit_market_order(
                    symbol=symbol,
                    direction=direction,
                    quantity=adjusted_pos_size,  # <- ADJUSTED by resilience controller
                    stop_loss=risk_levels.stop_loss,
                    take_profit=risk_levels.take_profit,
                    comment=trade_comment,
                )

                if order_id:
                    # ===== NEW: Log with resilience context =====
                    size_reduction = (
                        base_pos_size.quantity - adjusted_pos_size
                    ) / base_pos_size.quantity * 100 if base_pos_size.quantity > 0 else 0

                    logger.info(
                        f"[ORDER] {symbol} {direction} | ID: {order_id} | "
                        f"Size: {base_pos_size.quantity:.2f} -> {adjusted_pos_size:.2f} "
                        f"(-{size_reduction:.0f}%) | "
                        f"Mode: {trade_flags.admission_mode.value if trade_flags else 'NORMAL'}"
                    )

        except Exception as e:
            logger.error(f"[ENGINE] Error processing signals: {e}")

    async def _monitor_resilience_health(self):
        """
        Background task to monitor API resilience health.

        Logs health status periodically and alerts on critical issues.
        """
        while self.state.is_running:
            try:
                if not self.resilience_controller:
                    await asyncio.sleep(60)
                    continue

                for symbol in self.config.data.pairs:
                    health = self.resilience_controller.get_health_status(symbol)

                    if not health:
                        continue

                    # Log health status
                    logger.info(
                        f"[HEALTH] {symbol} | Mode: {health['mode']} | "
                        f"Failures: {health['consecutive_failures']} | "
                        f"Total Failures: {health['total_failures']} | "
                        f"Timeouts: {health['total_timeouts']}"
                    )

                    # Alert on critical issues
                    if health["mode"] == "PRESERVATION":
                        logger.critical(
                            f"[DEGRADATION_ALERT] {symbol} in PRESERVATION mode | "
                            f"New long-term positions halted | "
                            f"Next retry: {health['next_retry_time']}"
                        )

                    if health["mode"] == "TECHNICAL_ONLY":
                        logger.warning(
                            f"[TECHNICAL_ONLY_ACTIVE] {symbol} | "
                            f"Position sizing: 50% | "
                            f"Indicators: RSI, ADX, Price Action, ATR only"
                        )

                await asyncio.sleep(60)

            except Exception as e:
                logger.error(f"[HEALTH_MONITOR] Error: {e}")
                await asyncio.sleep(60)

    async def shutdown(self):
        """Shutdown with resilience cleanup."""
        logger.info("[ENGINE] Shutting down with resilience report...")

        # Generate resilience report
        if self.resilience_controller:
            logger.info("[RESILIENCE_REPORT] ===== API Resilience Status =====")

            for symbol in self.config.data.pairs:
                health = self.resilience_controller.get_health_status(symbol)

                if health:
                    logger.info(
                        f"  {symbol}:"
                        f" Mode={health['mode']}"
                        f" | Failures={health['total_failures']}"
                        f" | Timeouts={health['total_timeouts']}"
                        f" | Last Error: {health['last_error']}"
                    )

        # Stop macro manager
        if self.finnhub_manager:
            await self.finnhub_manager.stop()
            logger.info("[ENGINE] ✓ Finnhub macro manager stopped")

        # Continue normal shutdown...
        logger.info("[ENGINE] Shutdown complete")


# ============================================================================
# Usage Example
# ============================================================================

async def example_usage():
    """
    Demonstrates using the resilient trading engine.

    Usage:
        python -c "from example import example_usage; asyncio.run(example_usage())"
    """
    from utils.config import ConfigManager, TradingConfig
    from core.execution import MockBroker
    from core.data_handler import MT5DataHandler
    from core.risk_manager import RiskManager

    # Load config
    config_manager = ConfigManager("config.yaml")
    config = config_manager.get_config()

    # Initialize components
    broker = MockBroker()
    await broker.connect()

    data_handler = MT5DataHandler(broker)

    risk_manager = RiskManager(
        symbol=config.data.pairs[0],
        risk_config=config.risk,
    )

    # Create resilient engine
    engine = ResilientTradingEngine(
        config=config,
        broker=broker,
        data_handler=data_handler,
        risk_manager=risk_manager,
    )

    # Initialize with resilience
    if await engine.initialize():
        logger.info("✓ Resilient trading engine initialized successfully")

        # Run trading loop
        try:
            await engine.run()
        except KeyboardInterrupt:
            logger.info("Received shutdown signal")
        finally:
            await engine.shutdown()
    else:
        logger.error("✗ Failed to initialize resilient trading engine")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(example_usage())
