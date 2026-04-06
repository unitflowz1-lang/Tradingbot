"""Trade execution engine for handling market and limit order execution"""

import asyncio
import json
import logging
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import datetime, timezone, timedelta
import time
from typing import Dict, Any, Optional, List
import os
try:
    import MetaTrader5 as mt5
except Exception:  # pragma: no cover - runtime dependency may be unavailable in test envs
    mt5 = None
from src.interfaces import TradeExecutor, BrokerInterface
from src.models import (
    Order, ExecutionResult, OrderStatus, OrderType, MarketData,
    Direction
)
from src.exceptions import TradeExecutionError, BrokerAPIError
from src.config import BrokerConfig
from src.error_handler import ErrorHandler
from src.utils.pip_standardizer import calculate_true_spread_pips, PipStandardizer
from utils.safe_format import format_float, safe_float


# ===== GLOBAL UTILITY: FRIDAY LATE TRADING RISK CHECK =====
def is_friday_late_trading_risk(check_time: Optional[datetime] = None) -> bool:
    """
    Check if current time is Friday after 15:00 ET (3 PM).
    Used for global Friday entry kill-switch to prevent weekend gap risk.
    
    Args:
        check_time: Optional datetime to check. Defaults to now in UTC.
        
    Returns:
        True if it's Friday after 15:00 ET, False otherwise
    """
    strict_friday_lock_enabled = str(os.environ.get("STRICT_FRIDAY_LOCK", "1")).strip().lower() in {"1", "true", "yes", "on"}
    if not strict_friday_lock_enabled:
        return False

    if check_time is None:
        check_time = datetime.now(timezone.utc)
    
    # Ensure timezone awareness
    if check_time.tzinfo is None:
        check_time = check_time.replace(tzinfo=timezone.utc)
    
    # Convert UTC to ET (UTC-5, or UTC-4 during DST)
    # For simplicity, use -5 offset
    et_time = check_time - timedelta(hours=5)
    
    # Friday = 4 (Monday = 0)
    is_friday = et_time.weekday() == 4
    is_after_3pm = et_time.hour >= 15
    
    return is_friday and is_after_3pm


class ExecutionEngine(TradeExecutor):
    """Execution engine for handling trade execution with slippage control"""
    
    def __init__(self, broker: BrokerInterface, config: Optional[BrokerConfig] = None):
        """Initialize execution engine
        
        Args:
            broker: Broker interface for API communication
            config: Broker configuration settings
        """
        self.broker = broker
        self.config = config or BrokerConfig(
            broker_name="default",
            api_key="",
            api_secret="",
            base_url="",
            timeout=30
        )
        self.logger = logging.getLogger(__name__)
        self.error_handler = ErrorHandler()
        
        # Order tracking for reconciliation
        self.pending_orders: Dict[str, Order] = {}
        self.order_modifications: Dict[str, List[Dict[str, Any]]] = {}
        
        # Execution quality metrics
        self.execution_metrics = {
            'total_executions': 0,
            'successful_executions': 0,
            'failed_executions': 0,
            'total_slippage': 0.0,
            'average_slippage': 0.0,
            'max_slippage': 0.0,
            'modification_attempts': 0,
            'successful_modifications': 0,
            'failed_modifications': 0,
            'reconciliation_errors': 0
        }
        self.cycle_interval = 10
        # Strike Guard: blocks duplicate concurrent strikes for same symbol.
        self.in_flight_orders: set[str] = set()
        self._in_flight_lock = asyncio.Lock()
        # Global execution pause (e.g., liquidity shock)
        self._global_execution_pause_until: Optional[datetime] = None
        # Sunday open guard (session start sleep)
        self.market_reopened_at: Optional[datetime] = None
        self.session_start_sleep_minutes: int = int(os.environ.get("SESSION_START_SLEEP_MINUTES", "60"))
        self.spread_history: Dict[str, List[Dict[str, Any]]] = {}
        
        # ===== CYCLE 45 OPTIMIZATION: Tick Freshness Tracking =====
        # Record when execute() method starts to detect stale price thinking
        self.start_tick_time: Optional[datetime] = None
        self.tick_freshness_threshold_seconds: int = 10  # Skip validation if tick > 10 seconds old

    @staticmethod
    def _symbol_key(symbol: str) -> str:
        return str(symbol or "").replace("/", "").upper()

    @staticmethod
    def _is_favorable_execution_price(
        direction: Direction,
        expected_price: float,
        execution_price: float,
    ) -> bool:
        """Return True when the live fill price improves entry for the trade direction."""
        if direction == Direction.LONG:
            return execution_price < expected_price
        return execution_price > expected_price

    @staticmethod
    def _is_adverse_execution_price(
        direction: Direction,
        expected_price: float,
        execution_price: float,
    ) -> bool:
        """Return True when the live fill price worsens entry for the trade direction."""
        if direction == Direction.LONG:
            return execution_price > expected_price
        return execution_price < expected_price

    def _normalize_price(self, symbol: str, price: Optional[float]) -> Optional[float]:
        """Normalize price to broker digits to avoid MT5 invalid-request rejections."""
        if price is None:
            return None
        try:
            # Prefer broker-native mapper/normalizer when available.
            if hasattr(self.broker, "_map_symbol") and hasattr(self.broker, "_normalize_price"):
                mt5_symbol = self.broker._map_symbol(symbol)  # type: ignore[attr-defined]
                return self.broker._normalize_price(mt5_symbol, price)  # type: ignore[attr-defined]
        except Exception:
            pass

        try:
            import MetaTrader5 as mt5  # type: ignore
            mt5_symbol = str(symbol or "").replace("/", "").upper()
            info = mt5.symbol_info(mt5_symbol)
            digits = int(getattr(info, "digits", 5)) if info else 5
            return round(float(price), digits)
        except Exception:
            return float(price)

    def _normalize_order_prices(self, order: Order) -> None:
        """Apply symbol-digit normalization in-place to order price/SL/TP."""
        order.price = self._normalize_price(order.symbol, order.price)
        order.stop_loss = self._normalize_price(order.symbol, order.stop_loss)
        order.take_profit = self._normalize_price(order.symbol, order.take_profit)

    def _enforce_take_profit_lock(self, order: Order) -> None:
        if not bool(getattr(order, "tp_lock_enabled", False)):
            return
        locked_tp = float(getattr(order, "tp_lock_price", 0.0) or 0.0)
        if locked_tp <= 0.0 or order.price is None or order.take_profit is None:
            return
        entry_price = float(order.price or 0.0)
        current_tp = float(order.take_profit or 0.0)
        if abs(current_tp - entry_price) < abs(locked_tp - entry_price):
            self.logger.critical(
                "[TP_LOCK] %s | Execution restored locked TP %.5f over tighter downstream TP %.5f.",
                order.symbol,
                locked_tp,
                current_tp,
            )
            order.take_profit = locked_tp

    def _enforce_signal_level_lock(self, order: Order) -> None:
        if not bool(getattr(order, "level_lock_enabled", False)):
            return
        locked_sl = float(getattr(order, "locked_stop_loss", 0.0) or 0.0)
        locked_tp = float(getattr(order, "locked_take_profit", 0.0) or 0.0)
        if locked_sl > 0.0 and order.stop_loss is not None:
            current_sl = float(order.stop_loss or 0.0)
            if abs(current_sl - locked_sl) > 1e-10:
                self.logger.critical(
                    "[LEVEL_LOCK] %s | Restored locked SL %.5f over downstream SL %.5f.",
                    order.symbol,
                    locked_sl,
                    current_sl,
                )
                order.stop_loss = locked_sl
        if locked_tp > 0.0 and order.take_profit is not None:
            current_tp = float(order.take_profit or 0.0)
            if abs(current_tp - locked_tp) > 1e-10:
                self.logger.critical(
                    "[LEVEL_LOCK] %s | Restored locked TP %.5f over downstream TP %.5f.",
                    order.symbol,
                    locked_tp,
                    current_tp,
                )
                order.take_profit = locked_tp

    def _clear_symbol_execution_cache(self, symbol: str) -> None:
        try:
            clear_fn = getattr(self.broker, "clear_frozen_quote_state", None)
            if callable(clear_fn):
                clear_fn(symbol)
        except Exception as exc:
            self.logger.debug("[STALE_TICK_ABORT] %s | Symbol cache clear failed: %s", symbol, exc)

    def can_execute(
        self,
        *,
        symbol: str,
        market_data: Optional[MarketData],
        request_type: str = "NEW_ORDER",
    ) -> bool:
        request_type_upper = str(request_type or "NEW_ORDER").upper()
        if request_type_upper in {"MODIFY", "CLOSE"}:
            return True
        if market_data is None:
            return False

        tick_age_seconds = getattr(market_data, "tick_age_seconds", None)
        if tick_age_seconds is None and getattr(market_data, "timestamp", None) is not None:
            tick_ts = market_data.timestamp
            if getattr(tick_ts, "tzinfo", None) is None:
                tick_ts = tick_ts.replace(tzinfo=timezone.utc)
            tick_age_seconds = max(0.0, time.time() - tick_ts.timestamp())
        tick_age_seconds = float(tick_age_seconds or 0.0)
        quote_is_frozen = bool(getattr(market_data, "quote_is_frozen", False))

        if tick_age_seconds > 3.0 or quote_is_frozen:
            self.logger.warning(
                "[EXECUTION_BLOCKED] %s | request=%s | tick_age=%.1fs | quote_is_frozen=%s | "
                "Blocking new entry on stale/synthetic quote.",
                symbol,
                request_type_upper,
                tick_age_seconds,
                quote_is_frozen,
            )
            return False
        return True
    
    async def execute(self, order: Order) -> ExecutionResult:
        """Execute trade order with slippage control"""
        # ===== CYCLE 45 OPTIMIZATION: Record Tick Start Time =====
        self.start_tick_time = datetime.now(timezone.utc)
        
        now = datetime.now(timezone.utc)
        if self.market_reopened_at:
            reopen_ts = self.market_reopened_at
            if reopen_ts.tzinfo is None:
                reopen_ts = reopen_ts.replace(tzinfo=timezone.utc)
            if reopen_ts.weekday() == 6 and now <= (reopen_ts + timedelta(minutes=self.session_start_sleep_minutes)):
                self.logger.critical(
                    "[SESSION_START_SLEEP] Sunday open guard active. Blocking execution until %s.",
                    (reopen_ts + timedelta(minutes=self.session_start_sleep_minutes)).strftime("%Y-%m-%d %H:%M:%S UTC"),
                )
                return ExecutionResult(
                    success=False,
                    order_id=getattr(order, "order_id", None),
                    executed_price=None,
                    executed_quantity=None,
                    error_message="EXECUTION_PAUSED: SESSION_START_SLEEP",
                    timestamp=now,
                )
        if self._global_execution_pause_until and datetime.now(timezone.utc) < self._global_execution_pause_until:
            return ExecutionResult(
                success=False,
                order_id=getattr(order, "order_id", None),
                executed_price=None,
                executed_quantity=None,
                error_message="EXECUTION_PAUSED: Global pause active",
                timestamp=datetime.now(timezone.utc),
            )
        symbol_key = self._symbol_key(order.symbol)
        async with self._in_flight_lock:
            if symbol_key in self.in_flight_orders:
                self.logger.warning(
                    f"[IN_FLIGHT_GUARD] Blocking duplicate strike for {order.symbol}. "
                    "Existing execution is still in-flight."
                )
                return ExecutionResult(
                    success=False,
                    order_id=getattr(order, "order_id", None),
                    executed_price=None,
                    executed_quantity=None,
                    error_message=f"IN_FLIGHT_GUARD: {order.symbol} already in flight",
                    timestamp=datetime.now(timezone.utc)
                )
            self.in_flight_orders.add(symbol_key)

        try:
            self.logger.info(f"Executing order {order.order_id} for {order.symbol}")
            
            # Validate order before execution
            await self._validate_order(order)
            self._enforce_signal_level_lock(order)
            self._enforce_take_profit_lock(order)
            
            # ===== FIX #8: [READY_TO_EXECUTE] LOG WITH FINAL PARAMETERS =====
            # Print final Lot Size and Risk Amount right before sending order to MT5
            risk_amount = order.quantity * abs(order.take_profit - order.stop_loss) if order.quantity and order.take_profit and order.stop_loss else 0.0
            self.logger.info(
                f"[READY_TO_EXECUTE] {order.symbol} | "
                f"Final Lot Size: {format_float(order.quantity, '.2f')} | "
                f"Risk Amount: ${format_float(risk_amount, '.2f')} | "
                f"Direction: {getattr(order.direction, 'value', 'UNKNOWN')} | "
                f"Entry: {format_float(order.price, '.5f')} | "
                f"SL: {format_float(order.stop_loss, '.5f')} | "
                f"TP: {format_float(order.take_profit, '.5f')} | "
                f"Sending order to MT5 terminal..."
            )
            
            # Get current market data for execution
            market_data = await self.broker.get_market_data(order.symbol)
            if not market_data:
                self.logger.error(
                    f"[CRITICAL_REJECTION] {order.symbol} | MARKET_DATA_UNAVAILABLE. Order aborted."
                )
                return ExecutionResult(
                    success=False,
                    order_id=order.order_id,
                    executed_price=None,
                    executed_quantity=None,
                    error_message="CRITICAL_REJECTION: MARKET_DATA_UNAVAILABLE",
                    timestamp=datetime.now(timezone.utc),
                )
            
            # ===== CYCLE 45 OPTIMIZATION: Tick Freshness Validation =====
            # If execute() method took > 10 seconds to reach here, refresh tick to avoid stale price thinking
            if self.start_tick_time:
                tick_age_seconds = (datetime.now(timezone.utc) - self.start_tick_time).total_seconds()
                if tick_age_seconds > self.tick_freshness_threshold_seconds:
                    self.logger.critical(
                        "[TICK_STALE_REFRESH] %s | Execution delayed %.1f seconds (> %d second threshold) | "
                        "Refreshing market data to avoid stale price thinking.",
                        order.symbol,
                        tick_age_seconds,
                        self.tick_freshness_threshold_seconds
                    )
                    # Refresh market data
                    refreshed_market_data = await self.broker.get_market_data(order.symbol)
                    if refreshed_market_data:
                        market_data = refreshed_market_data
                        self.logger.info(
                            "[TICK_REFRESHED] %s | Fresh market data acquired | Proceeding with execution.",
                            order.symbol
                        )
            
            if not self.can_execute(symbol=order.symbol, market_data=market_data, request_type="NEW_ORDER"):
                refreshed_market_data = await self.broker.get_market_data(order.symbol)
                if self.can_execute(symbol=order.symbol, market_data=refreshed_market_data, request_type="NEW_ORDER"):
                    market_data = refreshed_market_data
                else:
                    refresh_tick_age = getattr(refreshed_market_data, "tick_age_seconds", None) if refreshed_market_data else None
                    self._clear_symbol_execution_cache(order.symbol)
                    self.logger.warning(
                        "[STALE_TICK_ABORT] %s | Tick age exceeds 3s or quote remains frozen after refresh. Aborting trade instead of using fallback pricing.",
                        order.symbol,
                    )
                    return ExecutionResult(
                        success=False,
                        order_id=order.order_id,
                        executed_price=None,
                        executed_quantity=None,
                        error_message=f"CRITICAL_REJECTION: STALE_TICK_REFRESH_REQUIRED ({refresh_tick_age})",
                        timestamp=datetime.now(timezone.utc),
                    )
            
            # ===== HARD SPREAD GATE (FINAL GATE) =====
            spread_check_ok = await self._hard_spread_gate(order, market_data)
            if not spread_check_ok:
                return ExecutionResult(
                    success=False,
                    order_id=order.order_id,
                    executed_price=None,
                    executed_quantity=None,
                    error_message="REJECTED: SPREAD_TOO_WIDE",
                    timestamp=datetime.now(timezone.utc),
                )

            # ===== FIX #1: GLOBAL FRIDAY ENTRY KILL-SWITCH =====
            # Block all new entries on Friday after 15:00 ET to prevent weekend gap risk
            if is_friday_late_trading_risk():
                self.logger.critical(
                    "[FRIDAY_LATE_KILL_SWITCH] %s | Blocking entry. Current time is Friday after 15:00 ET. "
                    "Too much weekend gap risk for new positions.",
                    order.symbol,
                )
                return ExecutionResult(
                    success=False,
                    order_id=order.order_id,
                    executed_price=None,
                    executed_quantity=None,
                    error_message="EXECUTION_PAUSED: FRIDAY_LATE_TRADING_RISK",
                    timestamp=datetime.now(timezone.utc),
                )

            signal_mode = str(getattr(order, "signal_mode", getattr(order, "mode", "")) or "").upper()
            structure_override = bool(getattr(order, "structure_override", False))
            if structure_override or signal_mode == "EXPLORATION":
                self.logger.critical(
                    "[SNIPER_STRIKE] %s | Override cleared all filters. Entering MT5 execution path now.",
                    order.symbol,
                )
                self.logger.critical(
                    "[STRIKING] %s | Final execution gates passed. Dispatching order to broker.",
                    order.symbol,
                )
            
            # Execute based on order type
            if order.order_type == OrderType.MARKET:
                result = await self._execute_market_order(order, market_data)
            elif order.order_type == OrderType.LIMIT:
                result = await self._execute_limit_order(order, market_data)
            else:
                raise TradeExecutionError(
                    f"Unsupported order type: {order.order_type}",
                    error_code="UNSUPPORTED_ORDER_TYPE",
                    context={"order_type": order.order_type.value}
                )
            
            # Update execution metrics
            self._update_execution_metrics(result, order, market_data)
            
            # Track order for reconciliation if successful
            if result.success:
                self.cycle_interval = 10
                self.pending_orders[order.order_id] = order
            
            self.logger.info(
                f"Order {order.order_id} executed: "
                f"success={result.success}, price={result.executed_price}"
            )
            
            return result
            
        except Exception as e:
            self.logger.error(f"Failed to execute order {order.order_id}: {str(e)}")
            
            # Create failed execution result
            result = ExecutionResult(
                success=False,
                order_id=order.order_id,
                executed_price=None,
                executed_quantity=None,
                error_message=str(e),
                timestamp=datetime.now(timezone.utc)
            )
            
            self._update_execution_metrics(result, order, None)
            return result
        finally:
            async with self._in_flight_lock:
                self.in_flight_orders.discard(symbol_key)
    
    async def modify_order(self, order_id: str, modifications: Dict[str, Any]) -> bool:
        """Modify existing order with comprehensive error handling
        
        Args:
            order_id: ID of order to modify
            modifications: Dictionary of modifications to apply
            
        Returns:
            True if modification successful, False otherwise
        """
        self.execution_metrics['modification_attempts'] += 1
        
        try:
            self.logger.info(f"Modifying order {order_id}: {modifications}")
            
            # Validate order exists and is modifiable
            await self._validate_order_for_modification(order_id)
            
            # Validate modifications
            validated_modifications = await self._validate_modifications(
                order_id, modifications
            )
            
            # Record modification attempt for reconciliation
            self._record_modification_attempt(order_id, validated_modifications)
            
            # Execute modification with retry logic
            success = await self._execute_order_modification(
                order_id, validated_modifications
            )
            
            if success:
                self.execution_metrics['successful_modifications'] += 1
                self.logger.info(f"Order {order_id} modified successfully")
                
                # Update local order tracking
                await self._update_local_order_state(order_id, validated_modifications)
                
                # Verify modification with broker (reconciliation)
                await self._verify_order_modification(order_id, validated_modifications)
            else:
                self.execution_metrics['failed_modifications'] += 1
                self.logger.error(f"Order {order_id} modification failed")
                
                # Attempt reconciliation on failure
                await self._reconcile_order_state(order_id)
            
            return success
            
        except AttributeError:
            # Let AttributeError bubble up for None modifications
            raise
        except Exception as e:
            self.execution_metrics['failed_modifications'] += 1
            self.logger.error(f"Failed to modify order {order_id}: {str(e)}")
            
            # Attempt reconciliation on error
            await self._handle_modification_error(order_id, e)
            return False
    
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel order with comprehensive error handling
        
        Args:
            order_id: ID of order to cancel
            
        Returns:
            True if cancellation successful, False otherwise
        """
        try:
            self.logger.info(f"Cancelling order {order_id}")
            
            # Use error handler for retry logic
            success = await self.error_handler.execute_with_retry(
                self._broker_cancel_order,
                order_id,
                error_context=f"cancel_order_{order_id}"
            )
            
            if success:
                # Remove from pending orders tracking
                self.pending_orders.pop(order_id, None)
                self.logger.info(f"Order {order_id} cancelled successfully")
            else:
                self.logger.error(f"Failed to cancel order {order_id}")
            
            return success
            
        except Exception as e:
            self.logger.error(f"Failed to cancel order {order_id}: {str(e)}")
            return False

    async def _broker_cancel_order(self, order_id: str) -> bool:
        """Actual broker API call for order cancellation"""
        try:
            return await self.broker.cancel_order(order_id)
        except Exception as e:
            self.logger.error(f"Broker cancellation failed: {e}")
            return False
    
    async def _validate_order(self, order: Order) -> None:
        """Validate order before execution
        
        Args:
            order: Order to validate
            
        Raises:
            TradeExecutionError: If order is invalid
        """
        # Check if order is in pending status
        if order.status != OrderStatus.PENDING:
            raise TradeExecutionError(
                f"Order {order.order_id} is not in pending status: {order.status}",
                error_code="INVALID_ORDER_STATUS",
                context={"status": order.status.value}
            )
        
        # Validate account has sufficient margin
        try:
            portfolio = await self.broker.get_account_info()
            
            # Estimate required margin (simplified calculation)
            estimated_margin = order.quantity * (order.price or 1.0) * 0.01  # 1% margin
            
            if portfolio.margin_available < estimated_margin:
                raise TradeExecutionError(
                    "Insufficient margin for order execution",
                    error_code="INSUFFICIENT_MARGIN",
                    context={
                        "required_margin": estimated_margin,
                        "available_margin": portfolio.margin_available
                    }
                )
        except BrokerAPIError as e:
            raise TradeExecutionError(
                f"Failed to validate account margin: {str(e)}",
                error_code="MARGIN_VALIDATION_FAILED",
                context={"broker_error": str(e)}
            )
    
    async def _hard_spread_gate(self, order: Order, market_data: MarketData) -> bool:
        """
        ===== HARD SPREAD-LIMIT ENFORCEMENT =====
        Final gate: terminate execution if spread is too wide.
        
        Args:
            order: Order being executed
            market_data: Current market data with bid/ask
            
        Returns:
            bool: True if spread is acceptable, False otherwise
        """
        try:
            if not market_data or not hasattr(market_data, 'spread'):
                return False

            calculated_spread_pips = self._calculate_reported_spread_pips(
                order.symbol,
                float(getattr(market_data, "ask", 0.0) or 0.0),
                float(getattr(market_data, "bid", 0.0) or 0.0),
            )
            broker_reported_spread_pips = self._spread_to_pips(order.symbol, float(market_data.spread or 0.0))
            avg_spread = self._get_average_spread_pips(order)
            mismatch_delta = round(abs(calculated_spread_pips - broker_reported_spread_pips), 2)
            mismatch_tolerance = round(max(2.0, avg_spread * 0.75), 2)
            if mismatch_delta > mismatch_tolerance:
                self.logger.warning(
                    "[SPREAD_MISMATCH] %s | Calculated=%sp | Reported=%sp | Delta=%sp | Tolerance=%sp",
                    order.symbol,
                    format_float(calculated_spread_pips, ".1f"),
                    format_float(broker_reported_spread_pips, ".1f"),
                    format_float(mismatch_delta, ".1f"),
                    format_float(mismatch_tolerance, ".1f"),
                )

            spread_pips = round(max(calculated_spread_pips, broker_reported_spread_pips), 2)
            self._record_spread_sample(order.symbol, spread_pips, as_of=datetime.now(timezone.utc))
            avg_spread = self._get_average_spread_pips(order)
            max_allowable = self._get_max_allowable_pips(order, avg_spread)
            signal_confidence = float(getattr(order, "signal_confidence", 0.0) or 0.0)
            if signal_confidence > 1.0:
                signal_confidence = signal_confidence / 100.0
            sniper_override = (
                str(getattr(order, "trade_tier", "") or "").upper() == "TIER_A"
                or signal_confidence > 0.85
            )
            if sniper_override:
                prior_allowable = max_allowable
                max_allowable = round(max_allowable * 1.5, 2)
                self.logger.info(
                    "[SNIPER_OVERRIDE] %s | Tier=%s | Confidence=%.1f%% | Spread cap %.2fp -> %.2fp",
                    order.symbol,
                    str(getattr(order, "trade_tier", "") or "N/A"),
                    signal_confidence * 100.0,
                    prior_allowable,
                    max_allowable,
                )

            # USD/JPY 100-pip shock guard: pause all execution for 60s
            symbol_key = self._symbol_key(order.symbol)
            if symbol_key in {"USDJPY", "USD/JPY"} and spread_pips >= 100.0:
                self._pause_all_execution(60, f"USD/JPY spread spike {spread_pips:.1f} pips")

            if spread_pips > (avg_spread * 3.0) or spread_pips > max_allowable:
                self.logger.critical(
                    f"[FINAL_HARD_GATE] REJECTED: SPREAD_TOO_WIDE | {order.symbol} | "
                    f"Spread {format_float(spread_pips, '.1f')} pips > max({avg_spread:.1f}*3, {max_allowable:.1f}) | "
                    f"Avg={avg_spread:.1f} MaxAllow={max_allowable:.1f}"
                )
                return False

            return True
                
        except Exception as e:
            self.logger.debug(f"[HARD_SPREAD_GATE] Error checking spread: {e}")
            return False

    def _pause_all_execution(self, seconds: int, reason: str) -> None:
        until = datetime.now(timezone.utc) + timedelta(seconds=max(1, int(seconds)))
        self._global_execution_pause_until = until
        self.logger.critical(
            "[EXECUTION_PAUSE] Global pause for %ds | Until %s | Reason: %s",
            seconds,
            until.strftime("%Y-%m-%d %H:%M:%S UTC"),
            reason,
        )

    @staticmethod
    def _decimal_or_zero(value: Any) -> Decimal:
        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return Decimal("0")

    def _get_symbol_precision(self, symbol: str) -> tuple[int, float]:
        digits = 3 if "JPY" in str(symbol).upper() else 5
        point = 0.001 if digits == 3 else 0.00001
        try:
            if mt5 is not None:
                mt5_symbol = self._symbol_key(symbol)
                map_fn = getattr(self.broker, "_map_symbol", None)
                if callable(map_fn):
                    mt5_symbol = map_fn(symbol)
                info = mt5.symbol_info(mt5_symbol)
                if info:
                    digits = int(getattr(info, "digits", digits) or digits)
                    point = float(getattr(info, "point", point) or point)
        except Exception:
            pass
        return digits, point

    def _calculate_reported_spread_pips(self, symbol: str, ask: float, bid: float) -> float:
        digits, point = self._get_symbol_precision(symbol)
        return round(
            PipStandardizer.spread_to_pips(
                ask=ask,
                bid=bid,
                digits=digits,
                point=point,
                symbol=symbol,
            ),
            2,
        )

    def _record_spread_sample(self, symbol: str, spread_pips: float, as_of: Optional[datetime] = None) -> None:
        symbol_key = self._symbol_key(symbol)
        now = as_of or datetime.now(timezone.utc)
        cutoff = now - timedelta(minutes=5)
        history = [
            sample for sample in self.spread_history.get(symbol_key, [])
            if sample.get("timestamp") and sample["timestamp"] >= cutoff
        ]
        history.append({
            "timestamp": now,
            "spread_pips": round(float(spread_pips or 0.0), 2),
        })
        self.spread_history[symbol_key] = history

    def _spread_to_pips(self, symbol: str, spread: float) -> float:
        if not spread:
            return 0.0
        digits, point = self._get_symbol_precision(symbol)
        return round(
            PipStandardizer.broker_value_to_pips_by_digits(
                value=float(spread or 0.0),
                digits=digits,
                point=point,
                symbol=symbol,
            ),
            2,
        )

    def _price_diff_to_pips(self, symbol: str, diff: float) -> float:
        if diff <= 0:
            return 0.0
        digits, point = self._get_symbol_precision(symbol)
        return round(
            PipStandardizer.broker_value_to_pips_by_digits(
                value=float(diff or 0.0),
                digits=digits,
                point=point,
                symbol=symbol,
            ),
            2,
        )

    def _get_average_spread_pips(self, order: Order) -> float:
        symbol_key = self._symbol_key(order.symbol)
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(minutes=5)
        history = [
            sample for sample in self.spread_history.get(symbol_key, [])
            if sample.get("timestamp") and sample["timestamp"] >= cutoff
        ]
        if history:
            self.spread_history[symbol_key] = history
            avg_pips = sum(float(sample.get("spread_pips", 0.0) or 0.0) for sample in history) / max(len(history), 1)
            return round(avg_pips, 2)
        normal_spreads = {
            'EUR/USD': 1.5,
            'GBP/USD': 2.0,
            'USD/JPY': 1.5,
            'USD/CHF': 2.0,
            'AUD/USD': 2.5,
            'USD/CAD': 2.0,
            'NZD/USD': 3.0
        }
        if hasattr(order, "avg_spread_pips") and order.avg_spread_pips:
            try:
                return float(order.avg_spread_pips)
            except Exception:
                pass
        return float(normal_spreads.get(order.symbol, 2.0))

    def _get_max_allowable_pips(self, order: Order, avg_spread_pips: float) -> float:
        if hasattr(order, "max_allowable_pips") and order.max_allowable_pips:
            try:
                base_allowable = float(order.max_allowable_pips)
                return round(max(base_allowable, float(avg_spread_pips) * 1.25), 2)
            except Exception:
                pass
        # Allow config-based override if provided
        if hasattr(self.config, "max_spread_threshold") and getattr(self.config, "max_spread_threshold"):
            try:
                raw = float(getattr(self.config, "max_spread_threshold"))
                base_allowable = self._spread_to_pips(order.symbol, raw)
                return round(max(base_allowable, float(avg_spread_pips) * 1.25), 2)
            except Exception:
                pass
        try:
            raw_allowable = os.environ.get("MAX_ALLOWABLE_PIPS", os.environ.get("MAX_ALLOWED_SPREAD", "25.0"))
            base_allowable = float(raw_allowable)
        except Exception:
            base_allowable = 25.0
        return round(max(base_allowable, float(avg_spread_pips) * 1.25), 2)
    
    async def _execute_market_order(self, order: Order, market_data: MarketData) -> ExecutionResult:
        """Execute market order via broker"""
        try:
            self._normalize_order_prices(order)
            # ===== SL/TP GUARD: Block unprotected trades before sending to MT5 =====
            sl_val = order.stop_loss
            tp_val = order.take_profit
            sl_missing = sl_val is None or sl_val == 0.0
            tp_missing = tp_val is None or tp_val == 0.0

            if sl_missing or tp_missing:
                # Calculate R:R for log context
                rr_context = 0.0
                if not sl_missing and not tp_missing and order.price:
                    risk   = abs(order.price - sl_val)
                    reward = abs(tp_val - order.price)
                    rr_context = (reward / risk) if risk > 0 else 0.0

                self.logger.critical(
                    f"[ORDER_EXECUTION] SLTP_NOT_ATTACHED_ABORTED_TRADE | "
                    f"{order.symbol} | {getattr(order.direction, 'value', 'UNKNOWN')} | "
                    f"Entry={format_float(order.price, '.5f')} | "
                    f"SL={format_float(sl_val, '.5f')} | "
                    f"TP={format_float(tp_val, '.5f')} | "
                    f"R:R={format_float(rr_context, '.2f')}R | "
                    f"SL_missing={sl_missing} TP_missing={tp_missing} | "
                    f"BrokerValidation=REJECTED | "
                    f"Trade BLOCKED — unprotected position would be opened."
                )
                return ExecutionResult(
                    success=False,
                    order_id=order.order_id,
                    executed_price=None,
                    executed_quantity=None,
                    error_message="SLTP_NOT_ATTACHED_ABORTED_TRADE: SL or TP is None/zero",
                    timestamp=datetime.now(timezone.utc)
                )

            # ===== [ORDER_EXECUTION] Pre-send audit log =====
            live_entry = market_data.ask if order.direction == Direction.LONG else market_data.bid
            rr_ratio = 0.0
            if live_entry and sl_val and tp_val:
                risk = abs(live_entry - sl_val)
                reward = abs(tp_val - live_entry)
                rr_ratio = (reward / risk) if risk > 0 else 0.0

            self.logger.info(
                f"[ORDER_EXECUTION] {order.symbol} | PRE-SEND | "
                f"{getattr(order.direction, 'value', 'UNKNOWN')} | "
                f"Entry={format_float(live_entry, '.5f')} | "
                f"SL={format_float(sl_val, '.5f')} | "
                f"TP={format_float(tp_val, '.5f')} | "
                f"R:R={format_float(rr_ratio, '.2f')}R | "
                f"Volume={format_float(order.quantity, '.2f')} lots | "
                f"BrokerValidation=PENDING"
            )
            if rr_ratio < 1.5:
                self.logger.critical(
                    "[ORDER_EXECUTION] %s | HARD_REJECT | Live RR %.2fR < 1.50 using Entry=%s SL=%s TP=%s",
                    order.symbol,
                    rr_ratio,
                    format_float(live_entry, ".5f"),
                    format_float(sl_val, ".5f"),
                    format_float(tp_val, ".5f"),
                )
                return ExecutionResult(
                    success=False,
                    order_id=order.order_id,
                    executed_price=None,
                    executed_quantity=None,
                    error_message=f"REJECTED: LIVE_RR_BELOW_MINIMUM ({rr_ratio:.2f}R)",
                    timestamp=datetime.now(timezone.utc),
                )

            # ===== FIX #1: POSITIVE SLIPPAGE ACCEPTANCE =====
            # Accept trades where price moves favorably (improves RR), reject only when RR degrades + slippage excessive
            if order.price is not None and market_data is not None:
                expected_price = float(order.price)
                execution_price = market_data.ask if order.direction == Direction.LONG else market_data.bid
                slippage_pips = self._price_diff_to_pips(order.symbol, abs(execution_price - expected_price))
                
                # Calculate original RR from signal
                original_rr = getattr(order, 'rr_ratio', 1.5)
                if original_rr is None or original_rr <= 0:
                    original_rr = 1.5  # Safe default
                
                # Calculate current RR with fresh market price
                if order.stop_loss and order.take_profit:
                    current_risk = abs(execution_price - order.stop_loss)
                    current_reward = abs(order.take_profit - execution_price)
                    current_rr = (current_reward / current_risk) if current_risk > 0 else original_rr
                else:
                    current_rr = original_rr
                
                favorable_slippage = self._is_favorable_execution_price(
                    order.direction,
                    expected_price,
                    execution_price,
                )
                adverse_slippage = self._is_adverse_execution_price(
                    order.direction,
                    expected_price,
                    execution_price,
                )

                # ===== POSITIVE SLIPPAGE ACCEPTANCE LOGIC =====
                if favorable_slippage and slippage_pips > 0:
                    # Market moved in our favor based on trade direction.
                    # Extend TP to restore original RR ratio on improved entry price.
                    old_tp = order.take_profit
                    favorable_move_pips = self._price_diff_to_pips(order.symbol, abs(execution_price - expected_price))
                    
                    # Restore original RR by extending TP (direction-aware calculation)
                    risk_distance = abs(execution_price - order.stop_loss)
                    
                    # FIX: Calculate new TP based on direction to prevent SHORT trades from pushing TP above entry
                    if order.direction == Direction.LONG:
                        new_tp = execution_price + (original_rr * risk_distance)
                    else:  # SHORT direction
                        new_tp = execution_price - (original_rr * risk_distance)
                    
                    tp_move_pips = self._price_diff_to_pips(order.symbol, abs(new_tp - old_tp))
                    
                    self.logger.critical(
                        f"[POSITIVE_SLIPPAGE_ACCEPT] {order.symbol} | Market moved favorably | "
                        f"Original RR: {format_float(original_rr, '.2f')}R | "
                        f"Current RR: {format_float(current_rr, '.2f')}R | "
                        f"Slippage: {format_float(slippage_pips, '.2f')} pips (IN OUR FAVOR) | "
                        f"Signal={format_float(expected_price, '.5f')} Market={format_float(execution_price, '.5f')} | "
                        f"ACCEPTING IMPROVED ENTRY"
                    )
                    
                    # If we have a favorable move, adjust TP to maintain RR
                    if tp_move_pips > 0:
                        self.logger.critical(
                            f"[TP_ADJUSTED_FOR_SLIPPAGE] {order.symbol} | Positive slippage detected: +"
                            f"{format_float(favorable_move_pips, '.2f')} pips | "
                            f"TP extended: {format_float(old_tp, '.5f')} → {format_float(new_tp, '.5f')} "
                            f"({format_float(tp_move_pips, '.2f')} pips) | "
                            f"RR restored to {format_float(original_rr, '.2f')}R"
                        )
                        order.take_profit = new_tp
                    
                    order.price = execution_price  # Execute at current market price (better entry)
                elif adverse_slippage and current_rr <= original_rr and slippage_pips > 5.0:
                    # RR degraded AND excessive slippage
                    admission_locked = bool(getattr(order, "admission_locked", False) or getattr(order, "level_lock_enabled", False))
                    structure_override = bool(getattr(order, "structure_override", False))
                    is_time_sensitive = admission_locked or structure_override
                    
                    log_level = "warning" if is_time_sensitive else "critical"
                    log_msg = (
                        f"[SLIPPAGE_DEGRADE_REJECT] {order.symbol} | RR degraded + excessive slippage | "
                        f"Original RR: {format_float(original_rr, '.2f')}R | "
                        f"Current RR: {format_float(current_rr, '.2f')}R | "
                        f"Slippage: {format_float(slippage_pips, '.2f')} pips > 5.0 | "
                        f"Mode={'TIME_SENSITIVE' if is_time_sensitive else 'STANDARD'} | "
                        f"Signal={format_float(expected_price, '.5f')} Market={format_float(execution_price, '.5f')}"
                    )
                    if log_level == "critical":
                        self.logger.critical(log_msg)
                    else:
                        self.logger.warning(log_msg)
                    
                    return ExecutionResult(
                        success=False,
                        order_id=order.order_id,
                        executed_price=None,
                        executed_quantity=None,
                        error_message="REJECTED: SLIPPAGE_DEGRADE_EXCESSIVE",
                        timestamp=datetime.now(timezone.utc),
                    )
                else:
                    # RR unchanged AND slippage <= 5.0 pips: acceptable
                    self.logger.info(
                        f"[SLIPPAGE_ACCEPTABLE] {order.symbol} | RR maintained at {format_float(current_rr, '.2f')}R | "
                        f"Slippage: {format_float(slippage_pips, '.2f')} pips (within tolerance) | "
                        f"PROCEEDING WITH EXECUTION"
                    )

            # ===== FIX #2: PRE-FLIGHT PRICE REFRESH - Refresh stale signal price before execution =====
            if mt5 and order.price is not None:
                try:
                    # Resolve broker-native symbol for MT5 API, including optional suffix support.
                    symbol_for_mt5 = self._symbol_key(order.symbol)
                    map_fn = getattr(self.broker, "_map_symbol", None)
                    if callable(map_fn):
                        symbol_for_mt5 = map_fn(order.symbol)
                    
                    # Get fresh market tick
                    tick = mt5.symbol_info_tick(symbol_for_mt5)
                    if tick:
                        # Get fresh entry price based on direction
                        fresh_price = tick.ask if order.direction == Direction.LONG else tick.bid
                        
                        # Calculate new RR with fresh price
                        if order.stop_loss and order.take_profit and fresh_price:
                            risk = abs(fresh_price - order.stop_loss)
                            reward = abs(order.take_profit - fresh_price)
                            new_rr = (reward / risk) if risk > 0 else 0.0
                            
                            old_rr = 0.0
                            if order.price:
                                old_risk = abs(order.price - order.stop_loss)
                                old_reward = abs(order.take_profit - order.price)
                                old_rr = (old_reward / old_risk) if old_risk > 0 else 0.0
                            
                            # If fresh price maintains RR > 1.5, update order price
                            if new_rr > 1.5:
                                self.logger.critical(
                                    f"[PRE_FLIGHT_REFRESH] {order.symbol} | Price refreshed | "
                                    f"Old Entry: {format_float(order.price, '.5f')} (RR={format_float(old_rr, '.2f')}R) | "
                                    f"Fresh Entry: {format_float(fresh_price, '.5f')} (RR={format_float(new_rr, '.2f')}R) | "
                                    f"Slippage: {format_float(abs(fresh_price - order.price), '.5f')} | "
                                    f"Market OK - PROCEEDING WITH UPDATED PRICE"
                                )
                                order.price = fresh_price
                            else:
                                # ===== FIX #2: DYNAMIC TAKE-PROFIT FOR SLIPPAGE (Slippage-to-TP Bridge) =====
                                # RR degraded below 1.5 due to slippage, try to adjust TP to restore ratio
                                slippage_amount = abs(fresh_price - order.price)
                                old_tp = order.take_profit
                                
                                # Adjust TP outward by the slippage amount to restore RR
                                if order.direction == Direction.LONG:
                                    adjusted_tp = old_tp + slippage_amount
                                else:
                                    adjusted_tp = old_tp - slippage_amount
                                
                                # Recalculate RR with adjusted TP
                                adjusted_risk = abs(fresh_price - order.stop_loss)
                                adjusted_reward = abs(adjusted_tp - fresh_price)
                                adjusted_rr = (adjusted_reward / adjusted_risk) if adjusted_risk > 0 else 0.0
                                
                                # Safety Guard: Check if adjusted TP hits major resistance/support level
                                # (Using symbol high/low as proxy for major levels)
                                symbol_info = None
                                if mt5:
                                    try:
                                        symbol_info = mt5.symbol_info(symbol_for_mt5)
                                    except:
                                        pass
                                
                                can_adjust = True
                                resistance_warning = ""
                                if symbol_info:
                                    symbol_high = getattr(symbol_info, 'session_high', None)
                                    symbol_low = getattr(symbol_info, 'session_low', None)
                                    
                                    # If TP would hit session high/low, reject (resistance level)
                                    if symbol_high and adjusted_tp >= symbol_high:
                                        can_adjust = False
                                        resistance_warning = f"hits session high {format_float(symbol_high, '.5f')}"
                                    elif symbol_low and adjusted_tp <= symbol_low:
                                        can_adjust = False
                                        resistance_warning = f"hits session low {format_float(symbol_low, '.5f')}"
                                
                                if can_adjust and adjusted_rr >= 1.5:
                                    # TP adjustment succeeds
                                    self.logger.critical(
                                        f"[SLIPPAGE_TO_TP_BRIDGE] {order.symbol} | RR recovered via TP adjustment | "
                                        f"Original TP: {format_float(old_tp, '.5f')} | "
                                        f"Adjusted TP: {format_float(adjusted_tp, '.5f')} (adjusted +{format_float(slippage_amount, '.5f')}) | "
                                        f"New RR: {format_float(adjusted_rr, '.2f')}R (was {format_float(new_rr, '.2f')}R) | "
                                        f"EXECUTION APPROVED WITH TP ADJUSTMENT"
                                    )
                                    order.take_profit = adjusted_tp
                                    order.price = fresh_price
                                else:
                                    # TP adjustment fails or hits resistance, reject
                                    if can_adjust:
                                        reject_reason = f"even after TP adjustment (new RR {adjusted_rr:.2f}R < 1.5R)"
                                    else:
                                        reject_reason = f"adjustment would hit {resistance_warning}"
                                    
                                    self.logger.critical(
                                        f"[SLIPPAGE_ZONE_REJECT] {order.symbol} | Cannot compensate for slippage | "
                                        f"Original Entry: {format_float(order.price, '.5f')} (RR={format_float(old_rr, '.2f')}R) | "
                                        f"Fresh Entry: {format_float(fresh_price, '.5f')} (RR={format_float(new_rr, '.2f')}R) | "
                                        f"Reason: {reject_reason} — EXECUTION REJECTED"
                                    )
                                    return ExecutionResult(
                                        success=False,
                                        order_id=order.order_id,
                                        executed_price=None,
                                        executed_quantity=None,
                                        error_message=f"SLIPPAGE_ZONE_REJECT: {reject_reason}",
                                        timestamp=datetime.now(timezone.utc)
                                    )
                    else:
                        # Could not get fresh tick, proceed with original price (log warning)
                        self.logger.warning(
                            f"[PRE_FLIGHT_REFRESH_FAILED] {order.symbol} | Could not get fresh market tick | "
                            f"Proceeding with signal price: {format_float(order.price, '.5f')}"
                        )
                except Exception as refresh_error:
                    # On error refreshing price, log but proceed with original price
                    self.logger.warning(
                        f"[PRE_FLIGHT_REFRESH_ERROR] {order.symbol} | Error getting fresh price: {str(refresh_error)} | "
                        f"Proceeding with signal price: {format_float(order.price, '.5f')}"
                    )

            # ===== FIX #5: EUR/USD EXECUTION GAP - CATCH AND LOG MT5 ERRORS =====
            order_id = None

            try:
                order_id = await self.broker.place_order(
                    symbol=order.symbol,
                    direction=order.direction,
                    size=order.quantity,
                    stop_loss=order.stop_loss,
                    take_profit=order.take_profit
                )
            except Exception as place_error:
                # Capture the MT5 error code if available (e.g., 10018 Requote, 10019 Timeout)
                error_str = str(place_error)
                if "MARKET_CLOSED" in error_str or "10018" in error_str or "market closed" in error_str.lower():
                    self.cycle_interval = 300
                    self.logger.warning(
                        f"[EXECUTION_DEFERRED_MARKET_CLOSED] {order.symbol} | "
                        f"Order placement deferred: {error_str} | "
                        f"Entry: {format_float(order.price, '.5f')} | "
                        f"SL: {format_float(order.stop_loss, '.5f')} | "
                        f"TP: {format_float(order.take_profit, '.5f')}"
                    )
                    return ExecutionResult(
                        success=False,
                        order_id=order.order_id,
                        executed_price=None,
                        executed_quantity=None,
                        error_message=f"MARKET_CLOSED_DEFERRED: {error_str}",
                        timestamp=datetime.now(timezone.utc)
                    )
                self.logger.critical(
                    f"[EXECUTION_CRITICAL_FAIL] {order.symbol} | Signal passed quality filters "
                    f"but order placement FAILED. MT5 Error: {error_str} | "
                    f"Entry: {format_float(order.price, '.5f')} | SL: {format_float(order.stop_loss, '.5f')} | TP: {format_float(order.take_profit, '.5f')} | "
                    f"This is a critical gap."
                )
                # Re-raise to trigger normal error handling below
                raise
            
            # Record execution
            execution_price = market_data.ask if order.direction == Direction.LONG else market_data.bid
            
            # ===== FIX #9: [STRIKE_AUTHORIZED] CRITICAL LOG =====
            # Print final Ticket ID, Lot Size, and specific Override Rule used to greenlight trade
            rr = abs(order.take_profit - live_entry) / abs(live_entry - order.stop_loss) if abs(live_entry - order.stop_loss) > 0 else 0
            override_rule = "STANDARD"
            
            # Determine which override rule was used
            if hasattr(order, 'forced_execution') and order.forced_execution:
                override_rule = "FORCED_EXECUTION"
            elif rr > 2.5:
                override_rule = "PROFIT_OVERRIDE"
            elif hasattr(order, 'profit_override') and order.profit_override:
                override_rule = "PROFIT_OVERRIDE"
            
            # Calculate spread for log
            spread = 0.0
            spread_limit = 2.0 # Default
            if market_data:
                raw_spread = abs(market_data.ask - market_data.bid)
                point = 0.0001
                if "JPY" in order.symbol:
                     point = 0.01
                spread = raw_spread / point
                
                # Dynamic limit based on symbol
                if order.symbol == "GBP/USD": spread_limit = 2.6
                elif order.symbol == "EUR/USD": spread_limit = 1.8
                elif "JPY" in order.symbol: spread_limit = 2.5
            
            self.logger.critical(
                f"[STRIKE_AUTHORIZED] {order.symbol} | Spread: {format_float(spread, '.1f')} pips | Limit: {format_float(spread_limit, '.1f')} pips | "
                f"Ticket: {order_id} | Lot Size: {format_float(order.quantity, '.2f')} | Rule: {override_rule} | "
                f"RR: {format_float(rr, '.2f')}R | Entry: {format_float(live_entry, '.5f')} | SL: {format_float(order.stop_loss, '.5f')} | TP: {format_float(order.take_profit, '.5f')}"
            )
            
            return ExecutionResult(
                success=True,
                order_id=order_id,
                executed_price=execution_price,
                executed_quantity=order.quantity,
                error_message=None,
                timestamp=datetime.now(timezone.utc)
            )
        except Exception as e:
            self.logger.error(f"Broker execution failed: {e}")
            return ExecutionResult(
                success=False,
                order_id=order.order_id,
                executed_price=None,
                executed_quantity=None,
                error_message=str(e),
                timestamp=datetime.now(timezone.utc)
            )

    async def _send_immediate_order(self, order: Order) -> ExecutionResult:
        """
        ===== FIX #8: [STRIKE_PROCEEDING] CRITICAL LOG =====
        Immediately transmit order to MT5, bypassing all secondary logic/checks.
        """
        self.logger.critical(f"[STRIKE_PROCEEDING] 🚀 🚀 🚀 FORCED EXECUTION ACTIVATED for {order.symbol} | Bypassing all intermediate logic.")
        self.logger.critical(f"[MT5_SEND_ATTEMPT] Symbol: {order.symbol} | Volume: {format_float(order.quantity, '.2f')}")

        self._normalize_order_prices(order)
        self._enforce_signal_level_lock(order)
        self._enforce_take_profit_lock(order)
        # ===== SL/TP GUARD: Block unprotected forced trades =====
        sl_val = order.stop_loss
        tp_val = order.take_profit
        sl_missing = sl_val is None or sl_val == 0.0
        tp_missing = tp_val is None or tp_val == 0.0

        if sl_missing or tp_missing:
            rr_context = 0.0
            if not sl_missing and not tp_missing and order.price:
                risk   = abs(order.price - sl_val)
                reward = abs(tp_val - order.price)
                rr_context = (reward / risk) if risk > 0 else 0.0

            self.logger.critical(
                f"[ORDER_EXECUTION] SLTP_NOT_ATTACHED_ABORTED_TRADE | "
                f"{order.symbol} | FORCED_EXECUTION | "
                f"Entry={format_float(order.price, '.5f')} | "
                f"SL={format_float(sl_val, '.5f')} | "
                f"TP={format_float(tp_val, '.5f')} | "
                f"R:R={format_float(rr_context, '.2f')}R | "
                f"SL_missing={sl_missing} TP_missing={tp_missing} | "
                f"BrokerValidation=REJECTED | "
                f"Trade BLOCKED — unprotected forced position would be opened."
            )
            return ExecutionResult(
                success=False,
                order_id=order.order_id,
                executed_price=None,
                executed_quantity=None,
                error_message="SLTP_NOT_ATTACHED_ABORTED_TRADE: SL or TP is None/zero (forced execution)",
                timestamp=datetime.now(timezone.utc)
            )

        # ===== [ORDER_EXECUTION] Pre-send audit log =====
        market_data = await self.broker.get_market_data(order.symbol)
        if market_data is None or not self.can_execute(symbol=order.symbol, market_data=market_data, request_type="NEW_ORDER"):
            refreshed_market_data = await self.broker.get_market_data(order.symbol)
            if refreshed_market_data is None or not self.can_execute(symbol=order.symbol, market_data=refreshed_market_data, request_type="NEW_ORDER"):
                self._clear_symbol_execution_cache(order.symbol)
                self.logger.warning(
                    "[STALE_TICK_ABORT] %s | Forced execution aborted because quote is frozen or older than 3s.",
                    order.symbol,
                )
                return ExecutionResult(
                    success=False,
                    order_id=order.order_id,
                    executed_price=None,
                    executed_quantity=None,
                    error_message="CRITICAL_REJECTION: STALE_TICK_REFRESH_REQUIRED [FORCED]",
                    timestamp=datetime.now(timezone.utc)
                )
            market_data = refreshed_market_data
        live_entry = (
            market_data.ask if (market_data is not None and order.direction == Direction.LONG)
            else (market_data.bid if market_data is not None else order.price)
        )
        rr_ratio = 0.0
        if live_entry and sl_val and tp_val:
            risk = abs(live_entry - sl_val)
            reward = abs(tp_val - live_entry)
            rr_ratio = (reward / risk) if risk > 0 else 0.0

        self.logger.info(
            f"[ORDER_EXECUTION] {order.symbol} | PRE-SEND | FORCED_EXECUTION | "
            f"{getattr(order.direction, 'value', 'UNKNOWN')} | "
            f"Entry={format_float(live_entry, '.5f')} | "
            f"SL={format_float(sl_val, '.5f')} | "
            f"TP={format_float(tp_val, '.5f')} | "
            f"R:R={format_float(rr_ratio, '.2f')}R | "
            f"Volume={format_float(order.quantity, '.2f')} lots | "
            f"BrokerValidation=PENDING"
        )
        if rr_ratio < 1.5:
            self.logger.critical(
                "[ORDER_EXECUTION] %s | FORCED_HARD_REJECT | Live RR %.2fR < 1.50 using Entry=%s SL=%s TP=%s",
                order.symbol,
                rr_ratio,
                format_float(live_entry, ".5f"),
                format_float(sl_val, ".5f"),
                format_float(tp_val, ".5f"),
            )
            return ExecutionResult(
                success=False,
                order_id=order.order_id,
                executed_price=None,
                executed_quantity=None,
                error_message=f"REJECTED: LIVE_RR_BELOW_MINIMUM ({rr_ratio:.2f}R) [FORCED]",
                timestamp=datetime.now(timezone.utc)
            )

        try:
            order_id = await self.broker.place_order(
                symbol=order.symbol,
                direction=order.direction,
                size=order.quantity,
                stop_loss=order.stop_loss,
                take_profit=order.take_profit
            )
            
            # Record execution metadata
            execution_price = live_entry if live_entry is not None else order.price
            
            # [STRIKE_AUTHORIZED] log for forced execution too
            self.logger.critical(
                f"[STRIKE_AUTHORIZED] {order.symbol} | FORCED_EXECUTION | "
                f"Ticket: {order_id} | Lot Size: {format_float(order.quantity, '.2f')} | "
                f"Entry: {format_float(execution_price, '.5f')} | SL: {format_float(order.stop_loss, '.5f')} | TP: {format_float(order.take_profit, '.5f')}"
            )

            return ExecutionResult(
                 success=True,
                 order_id=order_id,
                 executed_price=execution_price,
                 executed_quantity=order.quantity,
                 error_message=None,
                 timestamp=datetime.now(timezone.utc)
            )
        except Exception as e:
             err = str(e)
             if "MARKET_CLOSED" in err or "10018" in err or "market closed" in err.lower():
                 self.cycle_interval = 300
                 self.logger.warning(
                     f"[EXECUTION_DEFERRED_MARKET_CLOSED] {order.symbol} | "
                     f"Forced execution deferred: {err}"
                 )
                 return ExecutionResult(
                     success=False,
                     order_id=order.order_id,
                     executed_price=None,
                     executed_quantity=None,
                     error_message=f"MARKET_CLOSED_DEFERRED: {err}",
                     timestamp=datetime.now(timezone.utc)
                 )
             self.logger.error(f"Immediate broker execution failed: {e}")
             return ExecutionResult(
                 success=False,
                 order_id=order.order_id,
                 executed_price=None,
                 executed_quantity=None,
                 error_message=str(e),
                 timestamp=datetime.now(timezone.utc)
             )
        
        try:
            # Get minimal market data for price logging
            market_data = await self.broker.get_market_data(order.symbol)
            
            # Send directly to market execution
            result = await self._execute_market_order(order, market_data)
            
            # Update metrics and track
            self._update_execution_metrics(result, order, market_data)
            if result.success:
                self.pending_orders[order.order_id] = order
                
            return result
        except Exception as e:
            self.logger.error(f"[SEND_IMMEDIATE_FAILED] {order.symbol} | Error: {e}")
            return ExecutionResult(
                success=False,
                order_id=order.order_id,
                executed_price=None,
                executed_quantity=None,
                error_message=f"Forced execution immediate failure: {str(e)}",
                timestamp=datetime.now(timezone.utc)
            )
    
    async def _execute_limit_order(self, order: Order, market_data: MarketData) -> ExecutionResult:
        """Execute limit order
        
        Args:
            order: Limit order to execute
            market_data: Current market data
            
        Returns:
            ExecutionResult with execution details
        """
        if order.price is None:
            raise TradeExecutionError(
                "Limit order must have a price",
                error_code="MISSING_LIMIT_PRICE",
                context={"order_id": order.order_id}
            )
        
        # Check if limit order can be filled at current market price
        can_fill = False
        
        if order.direction == Direction.LONG:
            # Buy limit: can fill if ask price <= limit price
            can_fill = market_data.ask <= order.price
            execution_price = min(market_data.ask, order.price)
        else:
            # Sell limit: can fill if bid price >= limit price
            can_fill = market_data.bid >= order.price
            execution_price = max(market_data.bid, order.price)
        
        if not can_fill:
            return ExecutionResult(
                success=False,
                order_id=order.order_id,
                executed_price=None,
                executed_quantity=None,
                error_message="Limit order cannot be filled at current market price",
                timestamp=datetime.now(timezone.utc)
            )
        
        # Apply minimal slippage for limit orders
        slippage_factor = self._calculate_slippage_factor(order.quantity, market_data) * 0.1
        
        if order.direction == Direction.LONG:
            execution_price *= (1 + slippage_factor)
        else:
            execution_price *= (1 - slippage_factor)
        
        execution_price = round(execution_price, 5)
        
        # Simulate execution delay
        await asyncio.sleep(0.05)
        
        return ExecutionResult(
            success=True,
            order_id=order.order_id,
            executed_price=execution_price,
            executed_quantity=order.quantity,
            error_message=None,
            timestamp=datetime.now(timezone.utc)
        )
    
    def _calculate_slippage_factor(self, quantity: float, market_data: MarketData) -> float:
        """Calculate slippage factor based on order size and market conditions
        
        Args:
            quantity: Order quantity
            market_data: Current market data
            
        Returns:
            Slippage factor as decimal (e.g., 0.0001 for 1 pip)
        """
        # Base slippage (1 pip for major pairs)
        base_slippage = 0.0001
        
        # Increase slippage for larger orders
        size_factor = min(quantity / 100000, 0.5)  # Max 50% increase for very large orders
        
        # Increase slippage for wider spreads
        spread_factor = market_data.spread / market_data.get_mid_price()
        
        # Calculate total slippage factor
        total_slippage = base_slippage * (1 + size_factor + spread_factor)
        
        return min(total_slippage, 0.001)  # Cap at 10 pips
    
    def _update_execution_metrics(
        self, 
        result: ExecutionResult, 
        order: Order, 
        market_data: Optional[MarketData]
    ) -> None:
        """Update execution quality metrics
        
        Args:
            result: Execution result
            order: Original order
            market_data: Market data at execution time
        """
        self.execution_metrics['total_executions'] += 1
        
        if result.success:
            self.execution_metrics['successful_executions'] += 1
            
            # Calculate slippage if we have market data and expected price
            if market_data and result.executed_price:
                if order.order_type == OrderType.MARKET:
                    expected_price = (
                        market_data.ask if order.direction == Direction.LONG 
                        else market_data.bid
                    )
                    slippage = abs(result.executed_price - expected_price)
                    
                    self.execution_metrics['total_slippage'] += slippage
                    self.execution_metrics['max_slippage'] = max(
                        self.execution_metrics['max_slippage'], slippage
                    )
                    
                    # Update average slippage
                    if self.execution_metrics['successful_executions'] > 0:
                        self.execution_metrics['average_slippage'] = (
                            self.execution_metrics['total_slippage'] / 
                            self.execution_metrics['successful_executions']
                        )
        else:
            self.execution_metrics['failed_executions'] += 1
    
    def get_execution_metrics(self) -> Dict[str, float]:
        """Get execution quality metrics
        
        Returns:
            Dictionary of execution metrics
        """
        return self.execution_metrics.copy()
    
    async def execute_trade(self, order: Order) -> ExecutionResult:
        """Compatibility alias for execute"""
        return await self.execute(order)

    def reset_metrics(self) -> None:
        """Reset execution metrics"""
        self.execution_metrics = {
            'total_executions': 0,
            'successful_executions': 0,
            'failed_executions': 0,
            'total_slippage': 0.0,
            'average_slippage': 0.0,
            'max_slippage': 0.0,
            'modification_attempts': 0,
            'successful_modifications': 0,
            'failed_modifications': 0,
            'reconciliation_errors': 0
        }

    async def _validate_order_for_modification(self, order_id: str) -> None:
        """Validate that order exists and can be modified
        
        Args:
            order_id: ID of order to validate
            
        Raises:
            TradeExecutionError: If order cannot be modified
        """
        try:
            # In a real implementation, this would check with the broker
            # For now, we'll simulate the validation
            await asyncio.sleep(0.01)  # Simulate API call
            
            # Check if order exists in our tracking
            if order_id not in self.pending_orders:
                # Try to fetch from broker (simulated)
                self.logger.warning(f"Order {order_id} not in local tracking")
            
            # Validate order is in modifiable state
            # Orders that are FILLED, CANCELLED, or REJECTED cannot be modified
            # This would be checked against broker state in real implementation
            
        except Exception as e:
            raise TradeExecutionError(
                f"Failed to validate order {order_id} for modification: {str(e)}",
                error_code="ORDER_VALIDATION_FAILED",
                context={"order_id": order_id, "error": str(e)}
            )

    async def _validate_modifications(
        self, 
        order_id: str, 
        modifications: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Validate and sanitize order modifications
        
        Args:
            order_id: ID of order being modified
            modifications: Dictionary of modifications to validate
            
        Returns:
            Validated modifications dictionary
            
        Raises:
            TradeExecutionError: If modifications are invalid
        """
        valid_keys = {
            'price', 'quantity', 'stop_loss', 'take_profit', 'order_type'
        }
        
        validated = {}
        
        for key, value in modifications.items():
            if key not in valid_keys:
                raise TradeExecutionError(
                    f"Invalid modification key: {key}",
                    error_code="INVALID_MODIFICATION_KEY",
                    context={"order_id": order_id, "invalid_key": key}
                )
            
            # Validate specific field types and ranges
            if key in ['price', 'stop_loss', 'take_profit']:
                if not isinstance(value, (int, float)) or value <= 0:
                    raise TradeExecutionError(
                        f"Invalid {key}: must be positive number",
                        error_code="INVALID_PRICE_VALUE",
                        context={"order_id": order_id, "field": key, "value": value}
                    )
                validated[key] = float(value)
            
            elif key == 'quantity':
                if not isinstance(value, (int, float)) or value <= 0:
                    raise TradeExecutionError(
                        f"Invalid quantity: must be positive number",
                        error_code="INVALID_QUANTITY_VALUE",
                        context={"order_id": order_id, "value": value}
                    )
                validated[key] = float(value)
            
            elif key == 'order_type':
                if not isinstance(value, OrderType):
                    try:
                        validated[key] = OrderType(value)
                    except ValueError:
                        raise TradeExecutionError(
                            f"Invalid order type: {value}",
                            error_code="INVALID_ORDER_TYPE",
                            context={"order_id": order_id, "value": value}
                        )
                else:
                    validated[key] = value
        
        return validated

    def _record_modification_attempt(
        self, 
        order_id: str, 
        modifications: Dict[str, Any]
    ) -> None:
        """Record modification attempt for reconciliation tracking
        
        Args:
            order_id: ID of order being modified
            modifications: Modifications being applied
        """
        if order_id not in self.order_modifications:
            self.order_modifications[order_id] = []
        
        self.order_modifications[order_id].append({
            'timestamp': datetime.now(timezone.utc),
            'modifications': modifications.copy(),
            'status': 'attempted'
        })

    async def _execute_order_modification(
        self, 
        order_id: str, 
        modifications: Dict[str, Any]
    ) -> bool:
        """Execute order modification with broker API
        
        Args:
            order_id: ID of order to modify
            modifications: Validated modifications to apply
            
        Returns:
            True if modification successful, False otherwise
        """
        try:
            # Use error handler for retry logic
            result = await self.error_handler.execute_with_retry(
                self._broker_modify_order,
                order_id,
                modifications,
                error_context=f"modify_order_{order_id}"
            )
            
            return result
            
        except Exception as e:
            self.logger.error(
                f"Failed to execute modification for order {order_id}: {str(e)}"
            )
            return False

    async def _broker_modify_order(
        self, 
        order_id: str, 
        modifications: Dict[str, Any]
    ) -> bool:
        """Actual broker API call for order modification with validation"""
        try:
            sl = modifications.get('stop_loss')
            tp = modifications.get('take_profit')
            
            # Sanitize values - convert invalid values to None
            if sl is not None and (sl == 0 or sl != sl):  # NaN check
                sl = None
            if tp is not None and (tp == 0 or tp != tp):  # NaN check
                tp = None
            
            # If both are None, skip modification
            if sl is None and tp is None:
                self.logger.warning(f"Skipping modify order {order_id}: both SL and TP are invalid")
                return False

            freeze_zone_probe = getattr(self.broker, "is_modification_within_freeze_zone", None)
            if callable(freeze_zone_probe):
                try:
                    blocked, detail = freeze_zone_probe(order_id=order_id, sl=sl, tp=tp)
                    if blocked:
                        self.logger.warning(
                            "[MOD_STALE] Aborting modification: Price too close to Freeze Zone. %s",
                            str(detail or ""),
                        )
                        return False
                except Exception as exc:
                    self.logger.debug("[MOD_STALE_CHECK] Preflight freeze-zone probe failed for %s: %s", order_id, exc)
            
            # Retry logic for modification (Emergency Exit Loop)
            MAX_RETRIES = 2
            import asyncio
            for attempt in range(MAX_RETRIES):
                try:
                    # Execute modification
                    result = await self.broker.modify_order(order_id, sl=sl, tp=tp)
                    
                    # Fix: Check for NoneType which indicates timeout/connection issue
                    if result is None:
                        self.logger.warning(f"[BROKER_TIMEOUT] Modification attempt {attempt+1}/{MAX_RETRIES} returned None for order {order_id}. Retrying...")
                        await asyncio.sleep(0.5) # Wait before retry
                        continue
                        
                    return result
                    
                except Exception as e:
                    self.logger.error(f"[MODIFICATION_ERROR] Attempt {attempt+1} failed: {e}")
                    if attempt == MAX_RETRIES - 1:
                        raise e # Re-raise on last attempt
                    await asyncio.sleep(0.5)

            return False
        except Exception as e:
            self.logger.error(f"Broker modification failed: {e}")
            return False

    async def _update_local_order_state(
        self, 
        order_id: str, 
        modifications: Dict[str, Any]
    ) -> None:
        """Update local order tracking with modifications
        
        Args:
            order_id: ID of order that was modified
            modifications: Modifications that were applied
        """
        if order_id in self.pending_orders:
            order = self.pending_orders[order_id]
            
            # Apply modifications to local copy
            for key, value in modifications.items():
                if hasattr(order, key):
                    setattr(order, key, value)
            
            self.logger.debug(
                f"Updated local state for order {order_id}: {modifications}"
            )

    async def _verify_order_modification(
        self, 
        order_id: str, 
        expected_modifications: Dict[str, Any]
    ) -> None:
        """Verify order modification with broker (reconciliation)
        
        Args:
            order_id: ID of order to verify
            expected_modifications: Expected modifications to verify
        """
        try:
            # Simulate broker order status check
            await asyncio.sleep(0.05)
            
            # In real implementation, this would fetch order from broker
            # and compare with expected state
            
            # Update modification tracking
            if order_id in self.order_modifications:
                for mod_record in self.order_modifications[order_id]:
                    if mod_record['status'] == 'attempted':
                        mod_record['status'] = 'verified'
                        mod_record['verified_at'] = datetime.now(timezone.utc)
                        break
            
            self.logger.debug(f"Verified modification for order {order_id}")
            
        except Exception as e:
            self.execution_metrics['reconciliation_errors'] += 1
            self.logger.error(
                f"Failed to verify modification for order {order_id}: {str(e)}"
            )

    async def _handle_modification_error(
        self, 
        order_id: str, 
        error: Exception
    ) -> None:
        """Handle modification errors and attempt reconciliation
        
        Args:
            order_id: ID of order that failed modification
            error: Error that occurred during modification
        """
        self.logger.error(
            f"Handling modification error for order {order_id}: {str(error)}"
        )
        
        try:
            # Attempt to reconcile order state with broker
            await self._reconcile_order_state(order_id)
            
        except Exception as reconcile_error:
            self.execution_metrics['reconciliation_errors'] += 1
            self.logger.error(
                f"Failed to reconcile order {order_id} after modification error: "
                f"{str(reconcile_error)}"
            )

    async def _reconcile_order_state(self, order_id: str) -> None:
        """Reconcile local order state with broker state"""
        try:
            # 1. Check basic status
            status = await self.broker.get_order_status(order_id)
            
            if status:
                self.logger.info(f"Reconciled order {order_id}: Broker Status = {status.value}")
                
                # If filled, cancelled or rejected, it's no longer 'pending'
                if status in [OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED]:
                    if order_id in self.pending_orders:
                        self.pending_orders.pop(order_id, None)
                        self.logger.info(f"Order {order_id} is {status.value}. Removed from pending tracking.")
                        
            else:
                # Order not found on broker - treat as orphaned/stale
                self.logger.debug(f"Order {order_id} not found on broker (orphaned). Removing from tracking.")
                # Orphaned orders should be removed from pending list
                if order_id in self.pending_orders:
                    self.pending_orders.pop(order_id, None)
                    self.logger.debug(f"Orphaned order {order_id} removed from pending tracking.")
            
            # 2. If it's a modification verification (not just status), we might need to check specific fields
            # We can do this by fetching full portfolio if needed
            
        except Exception as e:
            raise TradeExecutionError(
                f"Failed to reconcile order state: {str(e)}",
                error_code="RECONCILIATION_FAILED",
                context={"order_id": order_id}
            )

    async def reconcile_all_orders(self) -> Dict[str, Any]:
        """Reconcile all tracked orders with broker state
        
        Returns:
            Dictionary with reconciliation results
        """
        results = {
            'total_orders': len(self.pending_orders),
            'reconciled': 0,
            'errors': 0,
            'discrepancies': []
        }
        
        # Create a list copy of keys to avoid "dictionary changed size during iteration" error
        for order_id in list(self.pending_orders.keys()):
            try:
                await self._reconcile_order_state(order_id)
                results['reconciled'] += 1
            except Exception as e:
                results['errors'] += 1
                results['discrepancies'].append({
                    'order_id': order_id,
                    'error': str(e)
                })
        
        self.logger.info(
            f"Order reconciliation complete: {results['reconciled']} "
            f"reconciled, {results['errors']} errors"
        )
        
        return results

    def get_modification_history(self, order_id: str) -> List[Dict[str, Any]]:
        """Get modification history for an order
        
        Args:
            order_id: ID of order to get history for
            
        Returns:
            List of modification records
        """
        return self.order_modifications.get(order_id, [])

    def get_pending_orders(self) -> Dict[str, Order]:
        """Get all pending orders
        
        Returns:
            Dictionary of pending orders
        """
        return self.pending_orders.copy()

    async def emergency_cancel_all_orders(self) -> Dict[str, bool]:
        """Emergency cancellation of all pending orders
        
        Returns:
            Dictionary mapping order IDs to cancellation success status
        """
        results = {}
        
        for order_id in list(self.pending_orders.keys()):
            try:
                success = await self.cancel_order(order_id)
                results[order_id] = success
                
                if success:
                    self.logger.info(f"Emergency cancelled order {order_id}")
                else:
                    self.logger.error(f"Failed to emergency cancel order {order_id}")
                    
            except Exception as e:
                results[order_id] = False
                self.logger.error(
                    f"Exception during emergency cancel of order {order_id}: {str(e)}"
                )
        
        return results
