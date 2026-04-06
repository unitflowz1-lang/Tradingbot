"""
Exit Manager - Safety Valves for Position Closure
==================================================

Consolidates multiple exit criteria:
1. TIME-BASED EXIT: Close positions open >N bars (configurable, default 40)
2. HARD LOSS THRESHOLD: Close positions with unrealized PnL < -$X (configurable, default -$15.00)
3. REVERSAL EXIT (OR LOGIC): Close if ANY 2 of 3 reversal signals trigger
   - RSI Divergence (RSI<30 for LONG, RSI>70 for SHORT)
   - Momentum Loss (momentum <= 0 for LONG, >= 0 for SHORT)
   - Price Action Reversal (bearish/bullish candle patterns)

All exits use the same secure close function to ensure proper registry/shadow state updates.
"""

import logging
import os
from dataclasses import dataclass
from typing import Optional, Tuple, List, Dict, Any
from datetime import datetime, timezone, timedelta
from enum import Enum

from src.models import Direction, Position


class ExitSignalType(Enum):
    """Types of exit signals (safety valves)"""
    ACTION_CLOSE_IMMEDIATE = "ACTION_CLOSE_IMMEDIATE"
    TIME_BASED_STAGNATION = "position_stagnant_too_long"
    HARD_LOSS_THRESHOLD = "unrealized_loss_exceeds_limit"
    REVERSAL_RSI = "rsi_divergence_detected"
    REVERSAL_MOMENTUM = "momentum_loss_detected"
    REVERSAL_PRICE_ACTION = "price_action_reversal"


@dataclass
class ExitManagerConfig:
    """Configuration for all exit safety valves"""
    
    # Time-Based Exit Settings
    enable_time_based_exit: bool = True
    stagnation_limit_bars: int = 40  # Close if open for >40 bars
    bar_duration_minutes: int = 60   # Assume 1-hour bars (change to 240 for 4H)
    aggressive_pruning_enabled: bool = True
    stagnation_priority_trigger_positions: int = 4
    stagnation_priority_limit_bars: int = 15
    stagnation_priority_low_pnl_count: int = 2
    # ===== FIX #3: ADD MIN_BARS_ALIVE THRESHOLD =====
    # Minimum age (in bars) before stagnation penalty can be applied
    # Protects newly opened positions from premature closure due to initial spread loss
    stagnation_priority_min_bars_alive: int = 5
    
    # Hard Loss Threshold Settings
    enable_hard_loss_stop: bool = True
    max_loss_threshold_usd: float = -15.00  # Close if loss exceeds this
    
    # Reversal Exit Settings (OR Logic)
    enable_reversal_exit: bool = True
    reversal_conditions_required: int = 2  # Any 2 of 3 signals trigger exit (1=any single, 2=any pair, 3=all three)
    
    # RSI Divergence
    rsi_threshold_long: float = 30.0    # LONG reversal if RSI < 30
    rsi_threshold_short: float = 70.0   # SHORT reversal if RSI > 70
    
    # Momentum Loss
    momentum_threshold: float = 0.0  # LONG: momentum <= 0, SHORT: momentum >= 0
    
    # Price Action (3-candle or similar patterns)
    enable_price_action_check: bool = True
    
    # Logging verbosity
    log_all_checks: bool = True  # Log every exit condition (verbose)
    log_only_triggers: bool = False  # Log only when exits are triggered (concise)
    

class ExitManager:
    """
    Manages position exits through multiple safety valves.
    
    Safety valves are checked in priority order:
    1. Hard Loss Threshold (immediate force-close, no questions asked)
    2. Time-Based Stagnation (close if held too long without profit)
    3. Reversal Exit (close if reversal signals appear)
    
    Example usage:
    ```python
    config = ExitManagerConfig(
        stagnation_limit_bars=40,
        max_loss_threshold_usd=-15.00,
        reversal_conditions_required=2
    )
    manager = ExitManager(config)
    
    should_exit, reason = manager.check_exit_conditions(
        position=position_obj,
        strategy_indicators={'rsi': 28.5, 'momentum': -0.0001},
        current_bar_time=datetime.now()
    )
    
    if should_exit:
        await broker.close_position(position.position_id)
        position_manager.shadow_positions.pop(position.position_id)
        profit_mgmt.close_tracking(position.position_id)
    ```
    """
    
    def __init__(self, config: ExitManagerConfig = None, logger: logging.Logger = None, broker: Any = None):
        """Initialize ExitManager with configuration"""
        self.config = config or ExitManagerConfig()
        self.logger = logger or logging.getLogger(__name__)
        self.broker = broker
        self.symbol_quarantine_until: Dict[str, datetime] = {}
        
        self.logger.info(
            "[INIT_EXIT_MANAGER] Initialized with: "
            "TIME_EXIT=%s (%d bars max) | "
            "HARD_LOSS=%s ($%.2f limit) | "
            "REVERSAL=%s (%d conditions) | "
            "Price_Action=%s",
            self.config.enable_time_based_exit,
            self.config.stagnation_limit_bars,
            self.config.enable_hard_loss_stop,
            self.config.max_loss_threshold_usd,
            self.config.enable_reversal_exit,
            self.config.reversal_conditions_required,
            self.config.enable_price_action_check
        )

    @staticmethod
    def _normalize_symbol_key(symbol: str) -> str:
        return str(symbol or "").replace("/", "").replace("_", "").upper()

    def quarantine_symbol(self, symbol: str, minutes: int = 240, reason: str = "signal_invalidation") -> Optional[datetime]:
        symbol_key = self._normalize_symbol_key(symbol)
        if not symbol_key:
            return None
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=max(1, int(minutes)))
        self.symbol_quarantine_until[symbol_key] = expires_at
        self.logger.warning(
            "[INVALIDATION_QUARANTINE] %s | Reason=%s | Entries blocked until %s",
            symbol,
            reason,
            expires_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
        )
        return expires_at

    def is_symbol_quarantined(
        self,
        symbol: str,
        current_time: Optional[datetime] = None,
    ) -> Tuple[bool, Optional[datetime]]:
        symbol_key = self._normalize_symbol_key(symbol)
        expires_at = self.symbol_quarantine_until.get(symbol_key)
        if expires_at is None:
            return False, None
        now_utc = current_time or datetime.now(timezone.utc)
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=timezone.utc)
        if expires_at <= now_utc:
            self.symbol_quarantine_until.pop(symbol_key, None)
            return False, None
        return True, expires_at
    
    def check_exit_conditions(
        self,
        position: Position,
        strategy_indicators: Optional[Dict[str, float]] = None,
        current_bar_time: Optional[datetime] = None,
        price_history: Optional[List[Dict[str, float]]] = None,
        open_positions: Optional[List[Any]] = None,
    ) -> Tuple[bool, str, ExitSignalType]:
        """
        Check if any exit condition is met for a position.
        
        Returns:
            (should_exit, detailed_reason, signal_type)
        """
        
        # Initialize
        should_exit = False
        exit_reason = ""
        exit_signal = None
        
        position_id = str(position.position_id)
        symbol = str(position.symbol)
        direction = position.direction
        unrealized_pnl = float(position.unrealized_pnl or 0.0)
        entry_price = float(position.entry_price or 0.0)
        current_price = float(position.current_price or 0.0)
        opened_at = position.opened_at
        
        # ===== HARD EXIT OVERRIDE: ABSOLUTE TIME-BASED STAGNATION =====
        # This runs before any technical/regime logic and returns an immediate close action.
        if self.config.enable_time_based_exit and opened_at:
            # ===== FIX #3: CALCULATE BARS_SINCE_OPENED AND PASS TO STAGNATION CHECK =====
            # Compute position age in bars using available market data
            now_utc = current_bar_time or datetime.now(timezone.utc)
            if now_utc.tzinfo is None:
                now_utc = now_utc.replace(tzinfo=timezone.utc)
            if opened_at.tzinfo is None:
                opened_at = opened_at.replace(tzinfo=timezone.utc)
            
            # Calculate time delta and convert to bars (assuming H1 = 3600 seconds per bar)
            # If price_history available, detect actual bar duration; otherwise default to 3600s
            time_delta_seconds = (now_utc - opened_at).total_seconds()
            bar_duration_seconds = 3600  # Default to 1-hour bars
            
            if price_history and len(price_history) >= 2:
                # Attempt to detect bar duration from price history timestamps
                try:
                    # Assuming price_history has 'time' or 'timestamp' field
                    first_ts = price_history[0].get('time') or price_history[0].get('timestamp')
                    second_ts = price_history[1].get('time') or price_history[1].get('timestamp')
                    if first_ts and second_ts:
                        detected_delta = second_ts.total_seconds() if hasattr(second_ts, 'total_seconds') else (second_ts - first_ts)
                        if isinstance(detected_delta, (int, float)) and detected_delta > 0:
                            bar_duration_seconds = int(detected_delta)
                except Exception:
                    pass  # Stick with default
            
            bars_since_opened = int(time_delta_seconds / bar_duration_seconds) if bar_duration_seconds > 0 else 0
            
            effective_stagnation_limit = self._get_effective_stagnation_limit(
                position=position,
                open_positions=open_positions,
                bars_since_opened=bars_since_opened,  # ===== FIX #3: PASS CALCULATED BARS =====
            )
            should_exit, exit_reason, exit_signal = self._check_hard_exit_override(
                position_id,
                symbol,
                unrealized_pnl,
                opened_at,
                now_utc,
                stagnation_limit_bars=effective_stagnation_limit,
            )
            if should_exit:
                return True, exit_reason, exit_signal

        # ===== SAFETY VALVE #1: HARD LOSS THRESHOLD =====
        # PRIORITY: Highest - Prevents bleeding positions immediately
        if self.config.enable_hard_loss_stop:
            should_exit, exit_reason, exit_signal = self._check_hard_loss_threshold(
                position_id, symbol, unrealized_pnl
            )
            if should_exit:
                return True, exit_reason, exit_signal
        
        # ===== SAFETY VALVE #3: REVERSAL EXIT (OR LOGIC) =====
        # PRIORITY: Medium - Close on reversal signals (2 of 3 required by default)
        if self.config.enable_reversal_exit and strategy_indicators:
            should_exit, exit_reason, exit_signal = self._check_reversal_conditions(
                position_id, symbol, direction, unrealized_pnl,
                strategy_indicators, price_history
            )
            if should_exit:
                return True, exit_reason, exit_signal
        
        # No exit conditions met
        if self.config.log_all_checks:
            self.logger.debug(
                "[EXIT_CHECK_COMPLETE] %s #%s | All safety valves clear | "
                "PnL: $%.2f | Direction: %s | No exit triggered",
                symbol, position_id, unrealized_pnl, direction
            )
        
        return False, "", None

    def _check_hard_exit_override(
        self,
        position_id: str,
        symbol: str,
        unrealized_pnl: float,
        opened_at: datetime,
        current_time: datetime,
        stagnation_limit_bars: Optional[int] = None,
    ) -> Tuple[bool, str, Optional[ExitSignalType]]:
        """Absolute time-exit that bypasses technical, harvest, and market-mode logic."""

        try:
            bars_open = self.get_bars_held(opened_at, current_time=current_time)
            effective_limit = float(stagnation_limit_bars or self.config.stagnation_limit_bars)
            if bars_open > effective_limit:
                reason = (
                    f"STAGNATION_THRESHOLD_MET: Position age {bars_open:.1f} bars exceeded "
                    f"hard limit {effective_limit:.1f}. ACTION_CLOSE_IMMEDIATE"
                )
                self.logger.critical(
                    "[FORCE_EXIT_TRIGGERED] Symbol: %s | Age: %.1f | PnL: %.2f | Reason: STAGNATION_THRESHOLD_MET",
                    symbol,
                    bars_open,
                    unrealized_pnl,
                )
                return True, reason, ExitSignalType.ACTION_CLOSE_IMMEDIATE
        except Exception as exc:
            self.logger.warning(
                "[FORCE_EXIT_CHECK_ERROR] %s #%s | Failed to evaluate hard stagnation override: %s",
                symbol,
                position_id,
                exc,
            )
        return False, "", None
    
    # ===== SAFETY VALVE #1: HARD LOSS THRESHOLD =====
    def _check_hard_loss_threshold(
        self,
        position_id: str,
        symbol: str,
        unrealized_pnl: float
    ) -> Tuple[bool, str, Optional[ExitSignalType]]:
        """
        Check if position loss exceeds the hard threshold.
        If unrealized PnL < -$15.00, force close immediately.
        """
        
        if unrealized_pnl < self.config.max_loss_threshold_usd:
            reason = (
                f"HARD_LOSS_THRESHOLD: Unrealized loss ${unrealized_pnl:.2f} exceeds "
                f"safety limit ${self.config.max_loss_threshold_usd:.2f} | "
                f"Force closing to prevent further drawdown"
            )
            self.logger.critical(
                "[HARD_LOSS_STOP] %s #%s | Loss: $%.2f < threshold: $%.2f | "
                "FORCE CLOSE (safety valve triggered)",
                symbol, position_id, unrealized_pnl, self.config.max_loss_threshold_usd
            )
            return True, reason, ExitSignalType.HARD_LOSS_THRESHOLD
        
        if self.config.log_all_checks:
            self.logger.debug(
                "[HARD_LOSS_CHECK] %s #%s | PnL: $%.2f > threshold: $%.2f (OK)",
                symbol, position_id, unrealized_pnl, self.config.max_loss_threshold_usd
            )
        
        return False, "", None
    
    # ===== SAFETY VALVE #2: TIME-BASED STAGNATION =====
    def _check_time_based_exit(
        self,
        position_id: str,
        symbol: str,
        opened_at: datetime,
        current_time: datetime,
        stagnation_limit_bars: Optional[int] = None,
    ) -> Tuple[bool, str, Optional[ExitSignalType]]:
        """
        Check if position has been open for too long without movement.
        If open for >40 bars (2400 minutes = 40 hours at 60min bars), close.
        """
        
        try:
            # Ensure both times are timezone-aware for proper comparison
            if opened_at.tzinfo is None:
                opened_at = opened_at.replace(tzinfo=timezone.utc)
            if current_time.tzinfo is None:
                current_time = current_time.replace(tzinfo=timezone.utc)
            
            time_held = current_time - opened_at
            bar_duration_seconds = self.config.bar_duration_minutes * 60
            bars_open = time_held.total_seconds() / bar_duration_seconds
            
            effective_limit = float(stagnation_limit_bars or self.config.stagnation_limit_bars)
            if bars_open >= effective_limit:
                reason = (
                    f"TIME_BASED_STAGNATION: Position held for {bars_open:.1f} bars "
                    f"(>= {effective_limit:.1f} bar limit) | "
                    f"Closing stagnated position to free capital"
                )
                self.logger.critical(
                    "[TIME_BASED_STOP] %s #%s | Held: %.1f bars >= %.1f limit | "
                    "FORCE CLOSE (stagnation exceeded)",
                    symbol, position_id, bars_open, effective_limit
                )
                return True, reason, ExitSignalType.TIME_BASED_STAGNATION
            
            if self.config.log_all_checks:
                self.logger.debug(
                    "[TIME_BASED_CHECK] %s #%s | Held: %.1f bars < %.1f limit (OK) | "
                    "Time Held: %.1fh",
                    symbol, position_id, bars_open, effective_limit,
                    time_held.total_seconds() / 3600
                )
            
            return False, "", None
        
        except Exception as e:
            self.logger.warning(
                "[TIME_BASED_CHECK_ERROR] %s #%s | Error calculating hold time: %s | "
                "Skipping time-based check",
                symbol, position_id, e
            )
            return False, "", None

    def _get_effective_stagnation_limit(
        self,
        position: Any,
        open_positions: Optional[List[Any]] = None,
        bars_since_opened: Optional[int] = None,  # ===== FIX #3: Add age parameter =====
    ) -> int:
        """
        Lower time-exit tolerance for the weakest positions when the book is full.
        
        ===== FIX #3: PREVENT PENALTIES FOR NEWLY OPENED POSITIONS =====
        Only apply stagnation-triggered penalty if position has been open for >= min_bars_alive.
        This gives newly opened positions time to overcome entry spread and establish direction.
        """

        default_limit = int(self.config.stagnation_limit_bars)
        if not self.config.aggressive_pruning_enabled:
            return default_limit

        open_positions = list(open_positions or [])
        if len(open_positions) < int(self.config.stagnation_priority_trigger_positions):
            return default_limit
        
        # ===== FIX #3: CHECK MINIMUM AGE BEFORE APPLYING PENALTY =====
        # Extract position age in bars
        position_age_bars = int(bars_since_opened or 0)
        min_bars_alive = int(self.config.stagnation_priority_min_bars_alive)
        
        if position_age_bars < min_bars_alive:
            # Position is too young, don't apply stagnation penalty yet
            self.logger.debug(
                "[STAGNATION_PRIORITY_GUARD] %s #%s | Position age %d bars < min_bars_alive %d. "
                "Skipping stagnation penalty (allowing time to overcome spread).",
                self._get_position_value(position, "symbol", "UNKNOWN"),
                str(self._get_position_value(position, "position_id", "")),
                position_age_bars,
                min_bars_alive,
            )
            return default_limit

        scored_positions: List[Tuple[float, str]] = []
        for candidate in open_positions:
            candidate_id = str(self._get_position_value(candidate, "position_id", ""))
            candidate_pnl = self._safe_float(self._get_position_value(candidate, "unrealized_pnl", 0.0))
            scored_positions.append((candidate_pnl, candidate_id))

        scored_positions.sort(key=lambda item: (item[0], item[1]))
        priority_ids = {
            candidate_id
            for _, candidate_id in scored_positions[: max(1, int(self.config.stagnation_priority_low_pnl_count))]
            if candidate_id
        }
        position_id = str(self._get_position_value(position, "position_id", ""))
        if position_id not in priority_ids:
            return default_limit

        priority_limit = int(self.config.stagnation_priority_limit_bars)
        self.logger.info(
            "[STAGNATION_PRIORITY] %s #%s | Portfolio saturated with %d open positions. "
            "Time-exit limit reduced from %d to %d bars for low-PnL position (Age: %d bars).",  # ===== FIX #3: Include age in log =====
            self._get_position_value(position, "symbol", "UNKNOWN"),
            position_id,
            len(open_positions),
            default_limit,
            priority_limit,
            position_age_bars,  # ===== FIX #3: Log position age =====
        )
        return priority_limit

    @staticmethod
    def _get_position_value(position: Any, field_name: str, default: Any = None) -> Any:
        if isinstance(position, dict):
            return position.get(field_name, default)
        return getattr(position, field_name, default)

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            return float(default)

    async def execute_force_close(self, position: Position) -> bool:
        """Direct-close path that bypasses queueing and strategy filters."""

        if self.broker is None or not hasattr(self.broker, "close_position"):
            self.logger.critical(
                "[FORCE_EXIT_FAILED] %s #%s | Broker hook unavailable for ACTION_CLOSE_IMMEDIATE.",
                getattr(position, "symbol", "UNKNOWN"),
                getattr(position, "position_id", "UNKNOWN"),
            )
            return False
        try:
            return bool(await self.broker.close_position(str(position.position_id)))
        except Exception as exc:
            self.logger.critical(
                "[FORCE_EXIT_FAILED] %s #%s | Direct broker close failed: %s",
                getattr(position, "symbol", "UNKNOWN"),
                getattr(position, "position_id", "UNKNOWN"),
                exc,
            )
            return False
    
    # ===== SAFETY VALVE #3: REVERSAL EXIT (OR LOGIC) =====
    def _check_reversal_conditions(
        self,
        position_id: str,
        symbol: str,
        direction: Any,
        unrealized_pnl: float,
        strategy_indicators: Dict[str, float],
        price_history: Optional[List[Dict[str, float]]] = None
    ) -> Tuple[bool, str, Optional[ExitSignalType]]:
        """
        Check for reversal signals using OR logic.
        Triggers exit if ANY 2+ of the following conditions are true:
        1. RSI Divergence (RSI<30 for LONG, RSI>70 for SHORT)
        2. Momentum Loss (momentum <= 0 for LONG, >= 0 for SHORT)
        3. Price Action Reversal (bearish for LONG, bullish for SHORT)
        
        By default: reversal_conditions_required=2, meaning any pair triggers exit.
        """
        
        triggered_conditions: List[Tuple[ExitSignalType, str]] = []
        
        # Extract indicators with safe defaults
        rsi = strategy_indicators.get('rsi')
        momentum = strategy_indicators.get('momentum')
        
        # ===== CHECK #1: RSI DIVERGENCE =====
        condition_1_met, condition_1_msg = self._check_rsi_divergence(direction, rsi)
        if condition_1_met:
            triggered_conditions.append((ExitSignalType.REVERSAL_RSI, condition_1_msg))
        
        # ===== CHECK #2: MOMENTUM LOSS =====
        condition_2_met, condition_2_msg = self._check_momentum_loss(direction, momentum)
        if condition_2_met:
            triggered_conditions.append((ExitSignalType.REVERSAL_MOMENTUM, condition_2_msg))
        
        # ===== CHECK #3: PRICE ACTION REVERSAL =====
        if self.config.enable_price_action_check and price_history:
            condition_3_met, condition_3_msg = self._check_price_action_reversal(
                direction, price_history
            )
            if condition_3_met:
                triggered_conditions.append((ExitSignalType.REVERSAL_PRICE_ACTION, condition_3_msg))
        
        # ===== DECIDE: DO TRIGGERED CONDITIONS MEET EXIT THRESHOLD? =====
        num_conditions_triggered = len(triggered_conditions)
        
        if num_conditions_triggered >= self.config.reversal_conditions_required:
            # Exit is triggered - combine all messages
            exit_signal = triggered_conditions[0][0]  # Use first signal type
            combined_reason = " | ".join([msg for _, msg in triggered_conditions])
            
            reason = (
                f"REVERSAL_EXIT: {num_conditions_triggered}/{3} conditions met (need {self.config.reversal_conditions_required}) | "
                f"{combined_reason} | Closing position"
            )
            
            self.logger.critical(
                "[REVERSAL_EXIT] %s #%s | Triggered: %d/%d conditions | PnL: $%.2f | "
                "%s | CLOSING",
                symbol, position_id, num_conditions_triggered, 3, unrealized_pnl,
                " + ".join([msg for _, msg in triggered_conditions])
            )
            
            return True, reason, exit_signal
        
        # Not enough conditions triggered
        if self.config.log_all_checks:
            condition_status = " | ".join([
                f"{cond_type.value}: YES" for cond_type, _ in triggered_conditions
            ]) or "No conditions met"
            
            self.logger.debug(
                "[REVERSAL_CHECK] %s #%s | Conditions: %d/%d triggered (need %d) | "
                "Status: %s | PnL: $%.2f (OK - holding)",
                symbol, position_id, num_conditions_triggered, 3,
                self.config.reversal_conditions_required,
                condition_status, unrealized_pnl
            )
        
        return False, "", None
    
    def _check_rsi_divergence(
        self,
        direction: Any,
        rsi: Optional[float]
    ) -> Tuple[bool, str]:
        """Check if RSI divergence signal is present"""
        
        if rsi is None:
            return False, ""
        
        rsi_float = float(rsi)
        
        # LONG: RSI < 30 = bearish divergence = reversal signal
        if direction in (Direction.LONG, 'LONG'):
            if rsi_float < self.config.rsi_threshold_long:
                msg = f"RSI={rsi_float:.1f} < {self.config.rsi_threshold_long:.1f} (LONG reversal)"
                return True, msg
        
        # SHORT: RSI > 70 = bullish divergence = reversal signal
        elif direction in (Direction.SHORT, 'SHORT'):
            if rsi_float > self.config.rsi_threshold_short:
                msg = f"RSI={rsi_float:.1f} > {self.config.rsi_threshold_short:.1f} (SHORT reversal)"
                return True, msg
        
        return False, ""
    
    def _check_momentum_loss(
        self,
        direction: Any,
        momentum: Optional[float]
    ) -> Tuple[bool, str]:
        """Check if momentum loss signal is present"""
        
        if momentum is None:
            return False, ""
        
        momentum_float = float(momentum)
        
        # LONG: Momentum <= 0 = upside momentum lost = reversal signal
        if direction in (Direction.LONG, 'LONG'):
            if momentum_float <= self.config.momentum_threshold:
                msg = f"Momentum={momentum_float:.6f} <= {self.config.momentum_threshold:.1f} (LONG lost)"
                return True, msg
        
        # SHORT: Momentum >= 0 = downside momentum lost = reversal signal
        elif direction in (Direction.SHORT, 'SHORT'):
            if momentum_float >= self.config.momentum_threshold:
                msg = f"Momentum={momentum_float:.6f} >= {self.config.momentum_threshold:.1f} (SHORT lost)"
                return True, msg
        
        return False, ""
    
    def _check_price_action_reversal(
        self,
        direction: Any,
        price_history: List[Dict[str, float]]
    ) -> Tuple[bool, str]:
        """
        Check if price action shows reversal pattern.
        Simplified: Look for bearish candles on LONG (close < open) or
        bullish candles on SHORT (close > open) in recent candles.
        """
        
        if not price_history or len(price_history) < 2:
            return False, ""
        
        try:
            # Check last 2 candles for reversal patterns
            recent = price_history[-2:]
            
            bearish_count = 0
            bullish_count = 0
            
            for candle in recent:
                open_price = float(candle.get('open', 0))
                close_price = float(candle.get('close', 0))
                
                if close_price < open_price:
                    bearish_count += 1
                elif close_price > open_price:
                    bullish_count += 1
            
            # LONG position: Need bearish candles (close < open)
            if direction in (Direction.LONG, 'LONG') and bearish_count >= 1:
                return True, f"Price action: {bearish_count} bearish candle(s) (LONG reversal)"
            
            # SHORT position: Need bullish candles (close > open)
            if direction in (Direction.SHORT, 'SHORT') and bullish_count >= 1:
                return True, f"Price action: {bullish_count} bullish candle(s) (SHORT reversal)"
            
            return False, ""
        
        except Exception as e:
            logging.getLogger(__name__).debug(f"[PRICE_ACTION_CHECK] Error: {e}")
            return False, ""
    
    # ===== UTILITY: CALCULATE BARS HELD =====
    def get_bars_held(
        self,
        opened_at: datetime,
        current_time: Optional[datetime] = None
    ) -> float:
        """Calculate how many bars a position has been held"""
        
        current_time = current_time or datetime.now(timezone.utc)
        
        # Ensure current_time is UTC-aware
        if current_time.tzinfo is None:
            self.logger.warning(
                "[TIMEZONE_NORMALIZATION_WARNING] current_time passed without tzinfo; treating as UTC: %s",
                current_time.isoformat(),
            )
            current_time = current_time.replace(tzinfo=timezone.utc)
        elif current_time.tzinfo != timezone.utc:
            # Convert to UTC if in different timezone
            current_time = current_time.astimezone(timezone.utc)
        
        # Ensure opened_at is UTC-aware
        if opened_at.tzinfo is None:
            # Naive datetime received. MT5 timestamps should already be UTC (pos.time is Unix timestamp).
            # Do NOT apply BROKER_TIMEZONE_OFFSET_HOURS - it causes timestamp drift.
            # Treat naive datetime as already being in UTC.
            self.logger.debug(
                "[TIMESTAMP_FORMAT_DEBUG] opened_at is naive datetime, treating as UTC (no offset): %s",
                opened_at.isoformat(),
            )
            opened_at = opened_at.replace(tzinfo=timezone.utc)
        elif opened_at.tzinfo != timezone.utc:
            # Convert to UTC if in different timezone
            opened_at = opened_at.astimezone(timezone.utc)
        
        total_seconds_open = (current_time - opened_at).total_seconds()
        if total_seconds_open < 0:
            self.logger.warning(
                "[POSITION_AGE_SYNC_WARNING] Current time %s precedes opened_at %s. Clamping negative age to 0 bars. "
                "DEBUG: current_utc_ts=%.2f, opened_at_utc_ts=%.2f, diff_seconds=%.2f. "
                "BROKER_TIMEZONE_OFFSET_HOURS is deprecated and is not applied to MT5 timestamps. "
                "Verify the source position timestamp written into runtime state.",
                current_time.isoformat(),
                opened_at.isoformat(),
                current_time.timestamp(),
                opened_at.timestamp(),
                total_seconds_open,
            )
            return 0.0
        bar_duration_seconds = self.config.bar_duration_minutes * 60
        bars_open = total_seconds_open / bar_duration_seconds
        
        return max(0.0, bars_open)
    
    # ===== UTILITY: CONFIGURE DYNAMIC SETTINGS =====
    def set_stagnation_limit(self, bars: int) -> None:
        """Change the stagnation limit dynamically"""
        self.config.stagnation_limit_bars = max(1, int(bars))
        self.logger.info(
            "[CONFIG_UPDATE] Stagnation limit updated to %d bars",
            self.config.stagnation_limit_bars
        )
    
    def set_max_loss_threshold(self, usd_value: float) -> None:
        """Change the max loss threshold dynamically"""
        self.config.max_loss_threshold_usd = float(usd_value)
        self.logger.info(
            "[CONFIG_UPDATE] Max loss threshold updated to $%.2f",
            self.config.max_loss_threshold_usd
        )
    
    def set_reversal_conditions_required(self, num_conditions: int) -> None:
        """Change how many reversal conditions are required (1, 2, or 3)"""
        self.config.reversal_conditions_required = max(1, min(3, int(num_conditions)))
        self.logger.info(
            "[CONFIG_UPDATE] Reversal exit threshold updated to %d/%d conditions",
            self.config.reversal_conditions_required, 3
        )
