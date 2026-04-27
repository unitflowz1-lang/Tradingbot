"""
Profit Protection & Trade Management Module
------------------------------------------
Handles post-entry trade management including:
1. R-multiple based Break-even moves.
2. ATR-based Trailing Stops.
3. Partial Profit locking at R-levels.
4. Broker constraint management (Stop levels, Freeze distances).
5. Normalized stop adjustments.
6. Exit priority rules.
"""

import logging
import asyncio
import os
import json
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple, Any, Set
from dataclasses import dataclass, field
import MetaTrader5 as mt5

from src.analysis.llm_macro_monitor import macro_risk_cache
from src.models import Position, Direction, MarketData
from src.interfaces import BrokerInterface, TradeExecutor
from src.trading.ml_decay_exit_controller import MLDecayExitController
from src.trading.modification_gate import ModificationGate, ModificationProposal, ModificationType
from src.trading.dynamic_trailing_sl_manager import DynamicTrailingSLManager
from src.trading.LAYER_3_TIME_DECAY_ENHANCED import TimeDecayStopLossManager
from src.trading.dynamic_profit_compression import DynamicProfitCompressionManager
from src.utils.pip_standardizer import PipStandardizer

logger = logging.getLogger(__name__)

@dataclass
class TradeManagementSettings:
    """AGGRESSIVE SNIPER: Configuration for profit protection behavior"""
    # Break-even settings
    use_breakeven: bool = True
    breakeven_trigger_r: float = 1.0  # Move to BE only after the trade proves itself at 1.0R
    breakeven_offset_pips: float = 1.0 # AGGRESSIVE: Increased from 0.5 to 1.0 pip (spread buffer)

    # Dynamic Profit Locking settings (R-based floating-profit locks before trailing)
    use_dynamic_profit_locking: bool = True
    dynamic_profit_lock_min_step_pips: float = 2.0
    dynamic_profit_lock_levels: List[Dict[str, float]] = field(default_factory=lambda: [
        {"trigger_r": 1.5, "lock_profit_fraction": 0.25, "use_entry_plus_spread": 0.0},
    ])
    
    # Trailing Stop settings
    use_trailing_stop: bool = True
    trailing_stop_activation_r: float = 1.0  # AGGRESSIVE SNIPER: Activate at 1.0R (break-even)
    trailing_stop_atr_multiplier: float = 1.8 # Trail by 1.8x ATR (volatility adjusted)
    trailing_atr_by_regime: Dict[str, float] = field(default_factory=lambda: {
        "TRENDING": 3.5,         # AGGRESSIVE: Let winners run further (was 2.8)
        "RANGING": 1.5,          # Tighter in ranges (was 1.3)
        "HIGH_VOLATILITY": 2.0,  # Moderate trail (was 1.5)
        "LOW_LIQUIDITY": 1.5,    # Slightly wider (was 1.2)
    })
    
    # === FIX #1A: Min SL Distance Floor (prevents 30% tightening spiral) ===
    min_sl_distance_atr_multiplier: float = 1.5  # SL must be at least 1.5x ATR away from current price
    
    # === FIX #1B: Modification Cooldown (prevents SL spam and broker rate-limiting) ===
    modification_cooldown_seconds: int = 300  # 5 minutes: do not tighten SL more than once per 5 min
    significant_price_move_r: float = 1.0     # Only modify SL if price moved > 1.0R (overrides cooldown)
    
    # Partial Profit settings
    use_partial_profits: bool = True
    partial_profit_levels: List[Dict[str, float]] = field(default_factory=lambda: [
        {"r_level": 1.0, "close_percent": 0.25}, # Close 25% at 1R
        {"r_level": 1.5, "close_percent": 0.33}, # Close 33% of remaining at 1.5R
    ])
    
    # Institutional scale-out settings (single-shot)
    use_scale_out: bool = True
    scale_out_trigger_r: float = 1.0
    scale_out_close_percent: float = 0.5
    scale_out_be_with_spread: bool = True
    runner_buffer_pips: float = 5.0
    
    # Execution settings
    max_retries: int = 3
    retry_delay_ms: int = 1000
    state_file: str = "profit_protection_state.json"
    
    # === DYNAMIC EXIT SUITE SETTINGS ===
    # Profit Shaving Settings
    use_profit_shaving: bool = True
    profit_shaving_trigger_r: float = 1.5  # Trigger at 1.5R (halfway to 3.0R)
    profit_shaving_close_percent: float = 0.5  # Close 50% of position
    
    # RSI Exhaustion Settings
    use_rsi_exhaustion: bool = True
    rsi_exhaustion_threshold_min_profit_r: float = 0.5  # Only trigger if profit > 0.5R
    rsi_exhaustion_long_overbought: float = 75.0  # LONG: RSI > 75 = overbought
    rsi_exhaustion_short_oversold: float = 25.0  # SHORT: RSI < 25 = oversold
    
    # Momentum Stall Settings
    use_momentum_stall: bool = True
    momentum_stall_range_pips: float = 30.0  # Price within X pips
    momentum_stall_candles: int = 20  # For N consecutive candles
    momentum_stall_velocity_multiplier: float = 0.1  # Tighten to 0.1R trailing
    
    # EV-Decay Settings  
    use_ev_decay_exit: bool = True
    ev_decay_confidence_floor: float = 0.05  # Exit if ML conf < 5%
    
    # Price history for momentum detection (5-min candles)
    price_history_max_size: int = 200


class DynamicProfitController:
    """Multi-stage profit harvesting controller."""

    def __init__(
        self,
        broker: BrokerInterface,
        settings: TradeManagementSettings,
        position_manager=None,
    ):
        self.broker = broker
        self.settings = settings
        self.position_manager = position_manager
        self.levels = [
            {
                "target_r": 0.5,
                "close_pct": 0.20,
                "action": "SCALE_OUT",
                "state_key": "dynamic_partial_0_5r",
                "label": "Level 1",
                "comment": "Quick Profit",
            },
            {
                "target_r": 1.0,
                "close_pct": 0.35,
                "action": "SCALE_OUT",
                "state_key": "dynamic_partial_1_0r",
                "label": "Level 2",
                "comment": "Half Position",
            },
            {
                "target_r": 1.5,
                "close_pct": 0.30,
                "action": "SCALE_OUT_AND_RUNNER",
                "state_key": "dynamic_partial_1_5r",
                "label": "Level 3",
                "comment": "Lock Gains",
            },
        ]

    def _calculate_current_r(self, position: Position, risk_price: float, reference_price: Optional[float] = None) -> float:
        if risk_price <= 0:
            return 0.0
        price = float(reference_price if reference_price is not None else position.current_price)
        if position.direction == Direction.LONG:
            profit_price = price - position.entry_price
        else:
            profit_price = position.entry_price - price
        return profit_price / risk_price

    async def check_exits(self, module: "ProfitProtectionModule", position: Position, state: Dict[str, Any], atr: float) -> bool:
        trigger_price = float(state.get("peak_profit_price") or position.current_price)
        current_r = self._calculate_current_r(
            position,
            float(state.get("initial_risk_price") or 0.0),
            reference_price=trigger_price,
        )
        if current_r <= 0:
            return False

        action_taken = False
        for level in self.levels:
            if current_r < float(level["target_r"]):
                continue
            if level["state_key"] in state.get("partial_hits", set()):
                continue
            executed = await self._execute_action(module, position, state, level, atr, current_r)
            if executed:
                state["partial_hits"].add(level["state_key"])
                action_taken = True
                continue
            # Preserve milestone order: do not advance to higher-level exits
            # until lower profit-protection actions have been confirmed.
            break
        return action_taken

    async def _execute_action(
        self,
        module: "ProfitProtectionModule",
        position: Position,
        state: Dict[str, Any],
        level: Dict[str, Any],
        atr: float,
        current_r: float,
    ) -> bool:
        action = str(level["action"])
        pos_id = str(position.position_id)

        if action == "SCALE_OUT":
            close_pct = float(level.get("close_pct", 0.0) or 0.0)
            logger.info(
                "[SCALED_EXIT_EXECUTED] %s (ID:%s) %s %s hit at %.2fR. Closing %.0f%%.",
                position.symbol,
                pos_id,
                level.get("label", "Level"),
                level.get("comment", ""),
                current_r,
                close_pct * 100.0,
            )
            partial_ok = await module._execute_partial_close(position, close_pct)
            if partial_ok:
                state["scaled_out"] = True
                be_trigger_r = float(getattr(self.settings, "breakeven_trigger_r", 1.0) or 1.0)
                if float(level.get("target_r", 0.0) or 0.0) >= be_trigger_r:
                    be_ok = await module._move_to_breakeven(
                        position,
                        atr=0.0,
                        use_spread_buffer=True,
                        offset_pips=0.0,
                    )
                    if be_ok:
                        state["breakeven_reached"] = True
                        state["last_modified_sl"] = float(
                            getattr(position, "stop_loss", position.entry_price) or position.entry_price
                        )
            return bool(partial_ok)

        if action == "SCALE_OUT_AND_RUNNER":
            close_pct = float(level.get("close_pct", 0.0) or 0.0)
            logger.info(
                "[SCALED_EXIT_EXECUTED] %s (ID:%s) %s %s hit at %.2fR. Closing %.0f%% and activating runner.",
                position.symbol,
                pos_id,
                level.get("label", "Level"),
                level.get("comment", ""),
                current_r,
                close_pct * 100.0,
            )
            partial_ok = await module._execute_partial_close(position, close_pct)
            if not partial_ok:
                return False
            state["scaled_out"] = True
            state["trailing_active"] = True
            state["is_running_as_runner"] = True
            if not state.get("runner_tp_cleared", False):
                logger.info(
                    "[RUNNER_MODE_ENABLED] %s (ID:%s) reached %.2fR. Remaining position now managed as runner.",
                    position.symbol,
                    pos_id,
                    current_r,
                )
                state["runner_tp_cleared"] = True
            return bool(await module._continuous_sl_check(position=position, state=state))

        return False


class ProfitProtectionModule:
    """Module for advanced trade management and profit protection"""
    
    def __init__(self, 
                 broker: BrokerInterface, 
                 execution_engine: TradeExecutor,
                 settings: Optional[TradeManagementSettings] = None,
                 position_manager=None):
        self.broker = broker
        self.execution_engine = execution_engine
        self.settings = settings or TradeManagementSettings()
        self.position_manager = position_manager
        
        # Track persistent state for each position: {pos_id: {state_dict}}
        self.position_states: Dict[str, Dict[str, Any]] = {}
        
        # ===== FIX #1: WEEKEND LOCKOUT (Prevent Friday Harvest Re-Entry Loop) =====
        # Symbols harvested on Friday to prevent immediate re-entry
        self.weekend_lockout: Set[str] = set()
        
        # === FIX #3: EMERGENCY CATCH-UP OVERRIDE ===
        # Allows one-time SL modification bypass for all active positions when mt5 errors occur
        self.emergency_catchup_active: bool = False
        self._macro_shield_min_sl_step_pips = float(
            os.environ.get("MIN_SL_MODIFICATION_PIPS", "2.0")
        )
        self._macro_shield_cooldown_seconds = int(
            os.environ.get("MACRO_SHIELD_COOLDOWN_SECONDS", "600")
        )
        self._macro_shield_min_price_drift_pct = float(
            os.environ.get("MACRO_SHIELD_MIN_PRICE_DRIFT_PCT", "0.5")
        )
        self.shield_cooldowns: Dict[str, float] = {}
        self.ml_decay_controller = MLDecayExitController(
            min_hold_time_minutes=3,
            enable_decay_exits=True,
            ml_confidence_threshold=float(self.settings.ev_decay_confidence_floor),
            sustained_low_readings_required=int(os.environ.get("ML_DECAY_REQUIRED_DROPS", "5")),
        )
        self.dynamic_profit_controller = DynamicProfitController(
            broker=broker,
            settings=self.settings,
            position_manager=position_manager,
        )
        # Track repeated SL modification failures per ticket so one broker rejection
        # does not create an infinite retry loop every cycle.
        self.modify_failure_counts: Dict[str, int] = {}
        self.modify_cooldowns: Dict[str, datetime] = {}
        self._emergency_news_exit_cooldown_until: Optional[datetime] = None
        self.global_news_cooldown_until: Optional[datetime] = None
        
        # === LAYER 3: TIME-DECAY STOP LOSS MANAGER ===
        self.time_decay_manager = TimeDecayStopLossManager()
        self.TIME_DECAY_SHADOW_MODE = False  # Layer 3 executing live stop loss modifications
        self.time_decay_enabled = bool(
            os.environ.get("TIME_DECAY_ENABLED", "True").lower() in ("true", "1", "yes")
        )
        # FIX #1: Shadow Mode Log Formatting - accurately reflect LIVE vs SHADOW mode
        mode_status = "SHADOW" if self.TIME_DECAY_SHADOW_MODE else "LIVE"
        modification_status = "No MT5 modifications will be executed, only logging proposals." if self.TIME_DECAY_SHADOW_MODE else "MT5 modifications WILL BE EXECUTED (LIVE MODE)."
        logger.info(
            "[TIME_DECAY_SHADOW_RUNNING] Layer 3 initialized with MODE=%s. %s",
            mode_status,
            modification_status,
        )
        
        # === DYNAMIC PROFIT COMPRESSION (DPC) MANAGER ===
        self.dpc_manager = DynamicProfitCompressionManager()
        self.dpc_enabled = bool(
            os.environ.get("PROFIT_COMPRESSION_ENABLED", "True").lower() in ("true", "1", "yes")
        )
        logger.info(
            "[DPC_ENABLED] Dynamic Profit Compression initialized (enabled=%s)",
            self.dpc_enabled,
        )
        
        # Pre-flight tracking
        self.preflight_bar_history: Dict[str, list] = {}  # Track bar increments per position
        self.preflight_checks_done: bool = False
        
        self._load_state()

    def _serialize_state_value(self, value: Any) -> Any:
        """Convert in-memory state into JSON-safe primitives."""
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, set):
            return [self._serialize_state_value(item) for item in value]
        if isinstance(value, dict):
            return {key: self._serialize_state_value(val) for key, val in value.items()}
        if isinstance(value, list):
            return [self._serialize_state_value(item) for item in value]
        return value

    def _deserialize_state_value(self, key: str, value: Any) -> Any:
        """Restore selected JSON-safe state fields back to runtime objects."""
        if key == 'partial_hits' and isinstance(value, list):
            return set(value)
        if key == 'dynamic_profit_lock_hits' and isinstance(value, list):
            return set(value)
        if key == 'last_sl_modification_time' and isinstance(value, str):
            try:
                restored = datetime.fromisoformat(value)
                if restored.tzinfo is None:
                    restored = restored.replace(tzinfo=timezone.utc)
                return restored
            except Exception:
                return None
        return value
        
    def _save_state(self):
        """Persist state to disk"""
        try:
            serialized_state = {}
            for pid, pstate in self.position_states.items():
                serialized_state[pid] = self._serialize_state_value(pstate)
                
            with open(self.settings.state_file, 'w') as f:
                json.dump(serialized_state, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save ProfitProtectionModule state: {e}")

    def _load_state(self):
        """Load state from disk"""
        if os.path.exists(self.settings.state_file):
            try:
                with open(self.settings.state_file, 'r') as f:
                    data = json.load(f)
                    for pid, pstate in data.items():
                        if isinstance(pstate, dict):
                            for key, value in list(pstate.items()):
                                pstate[key] = self._deserialize_state_value(key, value)
                    self.position_states = data
                logger.info(f"Loaded ProfitProtectionModule state for {len(self.position_states)} positions")
            except Exception as e:
                logger.error(f"Failed to load ProfitProtectionModule state: {e}")
    
    def cleanup_closed_position(self, position_id: str) -> None:
        """Clean up state when a position is closed"""
        pos_id = str(position_id)
        
        # Remove from profit protection state
        if pos_id in self.position_states:
            self.position_states.pop(pos_id)
            logger.debug("[MGMT_CLEANUP] Removed %s from position_states", pos_id)
        
        # Remove from DPC manager
        self.dpc_manager.untrack_position(pos_id)
        
        # Remove from ML decay controller
        if hasattr(self.ml_decay_controller, 'untrack_position'):
            self.ml_decay_controller.untrack_position(int(pos_id))
        
        # Remove from modification cooldowns
        self.modify_cooldowns.pop(pos_id, None)
        self.modify_failure_counts.pop(pos_id, None)
        
        # Remove from preflight history
        self.preflight_bar_history.pop(pos_id, None)
        
        self._save_state()
    
    
    # ========== LAYER 3: PRE-FLIGHT CHECK FUNCTION ==========
    def preflight_check(self, position_id: str, bars_since_entry: int) -> Tuple[bool, str]:
        """
        PRE-FLIGHT CHECK: Validate that bars_since_entry increments per-bar, not per-pulse.
        
        Logs:
        - [PREFLIGHT_BARS_OK] if frequency is correct
        - [PREFLIGHT_BARS_ERROR] if frequency is wrong
        
        Returns: (is_ok, diagnostic_message)
        """
        pos_id = str(position_id)
        
        # Initialize history for this position
        if pos_id not in self.preflight_bar_history:
            self.preflight_bar_history[pos_id] = []
        
        history = self.preflight_bar_history[pos_id]
        
        # Record current reading with timestamp
        history.append({
            'bars': bars_since_entry,
            'timestamp': datetime.now(timezone.utc),
        })
        
        # Keep only last 50 readings
        if len(history) > 50:
            history.pop(0)
        
        # Check frequency if we have enough history
        if len(history) >= 15:
            # Look at the last 15 increments
            old_reading = history[-15]
            new_reading = history[-1]
            
            bars_delta = new_reading['bars'] - old_reading['bars']
            time_delta_seconds = (new_reading['timestamp'] - old_reading['timestamp']).total_seconds()
            
            # Expected: 15 bars should span ~15 hours (54000 seconds)
            # If only ~150 seconds: clearly per-pulse
            if bars_delta == 15:
                if time_delta_seconds < 300:  # Less than 5 minutes for 15 bars
                    reason = (
                        f"BARS FREQUENCY ERROR: 15 bars in {time_delta_seconds:.0f} seconds. "
                        f"Indicates manage_position() called per-pulse (every 10s), not per-bar (hourly). "
                        f"Expected: 15 bars in ~54000 seconds (15 hours). "
                        f"FIX: Ensure manage_position() only called on bar close, not every data update."
                    )
                    logger.error(f"[PREFLIGHT_BARS_ERROR] {pos_id}: {reason}")
                    return False, reason
                else:
                    # Looks correct
                    reason = f"Bars increment frequency correct: 15 bars in {time_delta_seconds:.0f}s (~15 hours)"
                    logger.info(f"[PREFLIGHT_BARS_OK] {pos_id}: {reason}")
                    return True, reason
        
        return True, "Insufficient history for frequency check yet"
    
    # === FIX #3: EMERGENCY CATCH-UP CONTROL METHODS ===
    def enable_emergency_catchup(self):
        """Enable emergency catch-up mode to bypass cooldown for all positions (one-time)"""
        self.emergency_catchup_active = True
        logger.critical(
            "[EMERGENCY_CATCHUP_ENABLED] Modification cooldown bypassed for all positions "
            "to catch up after UnboundLocalError recovery"
        )
    
    def disable_emergency_catchup(self):
        """Disable emergency catch-up after all positions have been updated"""
        if self.emergency_catchup_active:
            logger.info("[EMERGENCY_CATCHUP_DISABLED] Catch-up complete. Normal cooldown enforcement resumed.")
        self.emergency_catchup_active = False
    
    # ===== FIX #1: WEEKEND LOCKOUT METHODS =====
    def is_symbol_locked_for_weekend(self, symbol: str) -> bool:
        """Check if symbol is locked due to Friday harvest"""
        return symbol in self.weekend_lockout
    
    def clear_weekend_lockout(self) -> None:
        """Clear weekend lockout when market re-opens on Sunday/Monday"""
        if self.weekend_lockout:
            cleared_symbols = list(self.weekend_lockout)
            self.weekend_lockout.clear()
            logger.critical(
                "[WEEKEND_LOCKOUT_CLEARED] Market re-opened. Cleared lockout for: %s",
                ", ".join(cleared_symbols),
            )

    def _get_pip_value(self, symbol: str) -> float:
        """Get pip value for symbol using broker digits when available."""
        try:
            mt5_symbol = symbol.replace("/", "")
            info = mt5.symbol_info(mt5_symbol)
            if info:
                return PipStandardizer.get_pip_value_from_digits(
                    digits=getattr(info, "digits", None),
                    point=getattr(info, "point", None),
                    symbol=symbol,
                )
        except:
            pass
            
        # Hardcoded fallback if MT5 disconnected or symbol lookup fails
        if 'JPY' in symbol.upper():
            return 0.01
        return 0.0001

    def _spread_to_pips(self, symbol: str, spread_value: float) -> float:
        try:
            mt5_symbol = symbol.replace("/", "")
            info = mt5.symbol_info(mt5_symbol)
            if info:
                return PipStandardizer.broker_value_to_pips_by_digits(
                    value=float(spread_value or 0.0),
                    digits=getattr(info, "digits", None),
                    point=getattr(info, "point", None),
                    symbol=symbol,
                )
        except Exception:
            pass
        return PipStandardizer.broker_value_to_pips(float(spread_value or 0.0), symbol)

    def _get_macro_risk_state(self, symbol: str, market_data: MarketData) -> Tuple[float, str]:
        penalty = 0.0
        reason = ""

        try:
            penalty = float(macro_risk_cache.get_macro_risk_penalty(symbol) or 0.0)
        except Exception:
            penalty = 0.0
        try:
            reason = str(macro_risk_cache.get_macro_risk_reason(symbol) or "")
        except Exception:
            reason = ""

        indicators = getattr(market_data, "indicators", None)
        if isinstance(indicators, dict):
            try:
                penalty = max(penalty, float(indicators.get("macro_risk", penalty) or 0.0))
            except Exception:
                pass
            try:
                local_reason = str(indicators.get("macro_risk_reason", "") or "")
                if local_reason:
                    reason = local_reason
            except Exception:
                pass

        if hasattr(market_data, "macro_risk"):
            try:
                penalty = max(penalty, float(getattr(market_data, "macro_risk") or 0.0))
            except Exception:
                pass
        if hasattr(market_data, "macro_risk_reason"):
            local_reason = str(getattr(market_data, "macro_risk_reason") or "")
            if local_reason:
                reason = local_reason

        return penalty, reason

    def _is_macro_risk_high(self, penalty: float, reason: str) -> bool:
        reason_upper = str(reason or "").upper()
        return (
            penalty >= 0.25
            or "HIGH_IMPACT_NEWS_PENDING" in reason_upper
            or "MACRO_RISK_HIGH" in reason_upper
            or reason_upper == "HIGH"
        )

    def activate_global_news_cooldown(self, minutes: int = 15) -> None:
        until = datetime.now(timezone.utc) + timedelta(minutes=max(1, int(minutes)))
        self.global_news_cooldown_until = until
        logger.critical(
            "[GLOBAL_NEWS_COOLDOWN] New entries blocked until %s after emergency news exit.",
            until.strftime("%Y-%m-%d %H:%M:%S UTC"),
        )

    def is_global_news_cooldown_active(self) -> bool:
        if self.global_news_cooldown_until is None:
            return False
        if datetime.now(timezone.utc) < self.global_news_cooldown_until:
            return True
        self.global_news_cooldown_until = None
        return False

    async def _execute_emergency_news_response(
        self,
        trigger_symbol: str,
        spread_pips: float,
        macro_penalty: float,
        macro_reason: str,
    ) -> bool:
        now = datetime.now(timezone.utc)
        if self._emergency_news_exit_cooldown_until and now < self._emergency_news_exit_cooldown_until:
            return False

        self._emergency_news_exit_cooldown_until = now + timedelta(seconds=30)
        tightened_any = False
        closed_any = False
        positions: List[Position] = []
        try:
            if hasattr(self.broker, "get_positions"):
                fetched_positions = await self.broker.get_positions()
                if fetched_positions:
                    positions = list(fetched_positions)
        except Exception as exc:
            logger.warning("[EMERGENCY_NEWS_EXIT] Failed to fetch open positions from broker: %s", exc)

        if not positions:
            return False

        if spread_pips <= 15.0:
            logger.critical(
                "[EMERGENCY_NEWS_SHIELD] %s | MacroRisk=%.3f (%s) | Spread=%.1f pips in caution band. "
                "Tightening existing stop losses instead of forcing market close.",
                trigger_symbol,
                macro_penalty,
                macro_reason or "UNKNOWN",
                spread_pips,
            )
            for live_position in positions:
                try:
                    if await self.apply_macro_shield(live_position, ml_confidence=0.0):
                        tightened_any = True
                except Exception as exc:
                    logger.error(
                        "[EMERGENCY_NEWS_SHIELD] Failed to tighten %s #%s: %s",
                        live_position.symbol,
                        live_position.position_id,
                        exc,
                    )
            return tightened_any

        logger.critical(
            "[EMERGENCY_NEWS_EXIT] %s | MacroRisk=%.3f (%s) | Spread=%.1f pips > 15.0. "
            "Issuing market-close for all open positions.",
            trigger_symbol,
            macro_penalty,
            macro_reason or "UNKNOWN",
            spread_pips,
        )
        self.activate_global_news_cooldown(minutes=15)

        for live_position in positions:
            try:
                success = await self.broker.close_position(live_position.position_id)
                if success:
                    closed_any = True
            except Exception as exc:
                logger.error(
                    "[EMERGENCY_NEWS_EXIT] Failed to close %s #%s: %s",
                    live_position.symbol,
                    live_position.position_id,
                    exc,
                )
        return closed_any

    def _normalize_price(self, price: float, digits: int) -> float:
        """Normalize price to symbol digits"""
        return round(price, digits)

    def _get_modification_gate(self) -> ModificationGate:
        """Use the broker-level gate when available, otherwise create one from env config."""
        gate = getattr(self.broker, "modification_gate", None)
        if gate is None:
            gate = ModificationGate(
                min_sl_step_pips=self._macro_shield_min_sl_step_pips,
                min_tp_step_pips=float(os.environ.get("MIN_TP_MODIFICATION_PIPS", "2.0")),
                modification_cooldown_seconds=0,
            )
            setattr(self.broker, "modification_gate", gate)
        return gate

    def _extract_governance_mode(self, market_data: MarketData) -> Optional[str]:
        if hasattr(market_data, "governance_mode"):
            value = getattr(market_data, "governance_mode")
            if value:
                return str(value).upper()
        if hasattr(market_data, "indicators") and getattr(market_data, "indicators", None):
            value = market_data.indicators.get("governance_mode")
            if value:
                return str(value).upper()
        if isinstance(market_data, dict):
            value = market_data.get("governance_mode")
            if value:
                return str(value).upper()
        return None

    def _get_modify_cooldown_remaining(self, ticket_id: str) -> float:
        cooldown_until = self.modify_cooldowns.get(str(ticket_id))
        if not isinstance(cooldown_until, datetime):
            return 0.0
        remaining = (cooldown_until - datetime.now(timezone.utc)).total_seconds()
        if remaining <= 0:
            self.modify_cooldowns.pop(str(ticket_id), None)
            return 0.0
        return float(remaining)

    def _clear_modify_failure_tracking(self, ticket_id: str) -> None:
        ticket_key = str(ticket_id)
        self.modify_failure_counts.pop(ticket_key, None)
        self.modify_cooldowns.pop(ticket_key, None)

    def _record_modify_failure(
        self,
        ticket_id: str,
        symbol: str,
        label: str,
        reason: str,
        retcode: Optional[int] = None,
        comment: str = "",
    ) -> None:
        ticket_key = str(ticket_id)
        failures = int(self.modify_failure_counts.get(ticket_key, 0)) + 1
        self.modify_failure_counts[ticket_key] = failures

        if failures < 5:
            return

        cooldown_until = datetime.now(timezone.utc) + timedelta(minutes=5)
        self.modify_cooldowns[ticket_key] = cooldown_until
        logger.warning(
            "[PROTECTION_COOLDOWN] %s (ID:%s) %s failed %s times consecutively. Cooling down until %s | retcode=%s | comment=%s | reason=%s",
            symbol,
            ticket_id,
            label,
            failures,
            cooldown_until.isoformat(),
            retcode if retcode is not None else "N/A",
            comment or "N/A",
            reason or "N/A",
        )

    async def apply_macro_shield(self, position: Position, ml_confidence: float = 0.0) -> bool:
        """
        Apply macro-risk SL widening/tightening with modification throttling.

        Every MACRO_SHIELD SL proposal is evaluated by ModificationGate before any broker API call.
        """
        entry_px = float(getattr(position, "entry_price", 0.0) or 0.0)
        current_price = float(
            getattr(position, "current_price", getattr(position, "price_current", 0.0)) or 0.0
        )
        current_sl = float(getattr(position, "stop_loss", 0.0) or 0.0)
        current_tp = float(getattr(position, "take_profit", 0.0) or 0.0)
        conf_hint = float(ml_confidence or 0.0)
        pos_id = str(position.position_id)

        if entry_px <= 0.0 or current_sl <= 0.0:
            return False
        if current_price <= 0.0:
            current_price = entry_px

        if not self.emergency_catchup_active:
            last_shield_ts = self.shield_cooldowns.get(pos_id)
            if last_shield_ts is not None:
                elapsed = time.time() - last_shield_ts
                if elapsed < self._macro_shield_cooldown_seconds:
                    logger.debug(
                        "[THROTTLE] Shield cooldown active for %s: %.0fs remaining.",
                        position.symbol,
                        self._macro_shield_cooldown_seconds - elapsed,
                    )
                    return False

        price_drift_pct = abs(current_price - entry_px) / entry_px * 100.0 if entry_px > 0 else 0.0
        if not self.emergency_catchup_active and price_drift_pct < self._macro_shield_min_price_drift_pct:
            logger.debug(
                "[THROTTLE] Shield request skipped for %s: price drift %.3f%% < %.3f%%.",
                position.symbol,
                price_drift_pct,
                self._macro_shield_min_price_drift_pct,
            )
            return False

        new_sl: Optional[float] = None
        reason = ""
        direction_name = "LONG" if position.direction == Direction.LONG else "SHORT"

        if position.direction == Direction.LONG and current_sl < entry_px:
            if conf_hint > 0.15:
                candidate_sl = entry_px - ((entry_px - current_sl) * 1.2)
                if candidate_sl < current_sl:
                    new_sl = candidate_sl
                    reason = "MACRO_SHIELD_WIDENING"
            else:
                candidate_sl = entry_px - ((entry_px - current_sl) * 0.7)
                if candidate_sl > current_sl:
                    new_sl = candidate_sl
                    reason = "MACRO_SHIELD_TIGHTENING"
        elif position.direction == Direction.SHORT and current_sl > entry_px:
            if conf_hint > 0.15:
                candidate_sl = entry_px + ((current_sl - entry_px) * 1.2)
                if candidate_sl > current_sl:
                    new_sl = candidate_sl
                    reason = "MACRO_SHIELD_WIDENING"
            else:
                candidate_sl = entry_px + ((current_sl - entry_px) * 0.7)
                if candidate_sl < current_sl:
                    new_sl = candidate_sl
                    reason = "MACRO_SHIELD_TIGHTENING"

        if new_sl is None:
            return False

        # Sticky SL: only improve protection. Never re-send if the proposed level is not materially better.
        if position.direction == Direction.LONG and float(new_sl) <= current_sl:
            return False
        if position.direction == Direction.SHORT and float(new_sl) >= current_sl:
            return False

        pip_value = PipStandardizer.get_pip_value_for_pair(position.symbol)
        proposal = ModificationProposal(
            ticket=int(position.position_id),
            symbol=position.symbol,
            current_sl=current_sl,
            proposed_sl=float(new_sl),
            current_tp=current_tp,
            proposed_tp=current_tp,
            modification_type=ModificationType.STOP_LOSS,
            reason=reason,
        )
        gate = self._get_modification_gate()
        should_send, gate_reason, gate_details = gate.evaluate_modification(
            proposal,
            pip_value=pip_value,
        )

        if not should_send:
            logger.debug(
                "[THROTTLE] Shield request skipped for %s: %s | details=%s | min_sl_step_pips=%.2f",
                position.symbol,
                gate_reason,
                gate_details,
                float(getattr(gate, "min_sl_step_pips", self._macro_shield_min_sl_step_pips)),
            )
            return False

        logger.critical(
            "[MACRO_SHIELD] %s | %s %s %.5f -> %.5f | Conf=%.2f | Delta=%.2f pips",
            position.symbol,
            "Widening SL 20%" if "WIDENING" in reason else "Tightening SL 30%",
            f"({direction_name})",
            current_sl,
            float(new_sl),
            conf_hint,
            proposal.get_sl_distance_pips(pip_value),
        )
        success = await self.broker.modify_order(
            order_id=position.position_id,
            sl=float(new_sl),
            tp=current_tp if current_tp > 0 else None,
        )
        if success:
            position.stop_loss = float(new_sl)
            self.shield_cooldowns[pos_id] = time.time()
        return bool(success)

    async def manage_position(self, 
                               position: Position, 
                               market_data: MarketData, 
                               atr: float,
                               regime: Optional[str] = None,
                               volatility_regime: Optional[str] = None,
                               rsi: Optional[float] = None,
                               ml_confidence: Optional[float] = None) -> bool:
        """
        Apply management logic for a single position.
        Returns True if a management action was taken.
        
        Args:
            position: The Position object
            market_data: Current market data
            atr: Average True Range for trailing
            regime: Market regime label
            volatility_regime: Volatility regime label
            rsi: Optional RSI value (if not in market_data)
            ml_confidence: Optional ML confidence (if not in market_data)
        """
        pos_id = str(position.position_id)
        
        # === EXTRACT TECHNICAL INDICATORS ===
        # Try to get RSI and ML confidence from multiple sources
        extracted_rsi = rsi
        if extracted_rsi is None:
            # Try to get from market_data
            if hasattr(market_data, 'indicators') and market_data.indicators:
                extracted_rsi = market_data.indicators.get('rsi')
            elif hasattr(market_data, 'rsi'):
                extracted_rsi = market_data.rsi
            elif isinstance(market_data, dict) and 'rsi' in market_data:
                extracted_rsi = market_data.get('rsi')
        
        extracted_ml_conf = ml_confidence
        if extracted_ml_conf is None:
            # Try to get from market_data
            if hasattr(market_data, 'ml_confidence'):
                extracted_ml_conf = market_data.ml_confidence
            elif hasattr(market_data, 'indicators') and market_data.indicators:
                extracted_ml_conf = market_data.indicators.get('ml_confidence')
            elif isinstance(market_data, dict) and 'ml_confidence' in market_data:
                extracted_ml_conf = market_data.get('ml_confidence')
        
        # Ensure market_data has these attributes for dynamic exit methods
        if not hasattr(market_data, 'indicators'):
            market_data.indicators = {}
        if extracted_rsi is not None:
            market_data.indicators['rsi'] = extracted_rsi
        if extracted_ml_conf is not None:
            market_data.ml_confidence = extracted_ml_conf
        
        # 1. Initialize state if new or missing
        if pos_id not in self.position_states:
             pip_value = self._get_pip_value(position.symbol)
             
             # Calculate original risk (R) in price units
             if position.stop_loss and position.stop_loss != 0:
                 initial_risk_price = abs(position.entry_price - position.stop_loss)
             else:
                 # Default 20 pip risk if no SL (for R calculation)
                 initial_risk_price = 20 * pip_value
             
             self.position_states[pos_id] = {
                 'symbol': position.symbol,
                 'entry_price': position.entry_price,
                 'initial_risk_price': initial_risk_price,
                 'breakeven_reached': False,
                 'trailing_active': False,
                 'scaled_out': False,
                 'is_running_as_runner': False,
                 'runner_tp_cleared': False,
                 'partial_hits': set(),
                 'last_modified_sl': position.stop_loss,
                 'peak_profit_price': position.current_price,
                 'profit_lock_r': 0.0,
                 'market_regime': None,
                 'volatility_regime': None,
                 'governance_mode': None,
                 'last_sl_modification_time': None,  # === FIX #1B: Cooldown tracking ===
                 # === DYNAMIC EXIT SUITE STATE ===
                 'profit_shaving_done': False,  # Profit Shaving (1.5R)
                 'rsi_exhaustion_done': False,  # RSI Exhaustion
                 'momentum_stall_done': False,  # Momentum Stall Detection
                 'ev_decay_done': False,  # EV-Decay
                 'prev_rsi': None,  # Previous candle RSI (for crossing detection)
                 'rsi_crossed_above': False,  # Track if RSI crossed above 75 (for LONG)
                 'rsi_crossed_below': False,  # Track if RSI crossed below 25 (for SHORT)
                 'price_history': [],  # Last N close prices (for momentum stall)
                 'ml_confidence': 0.0,  # Current ML confidence for direction
                 'prev_ml_confidence': 0.0,  # Previous ML confidence (for flip detection)
                 'dynamic_profit_lock_hits': set(),
                 # === LAYER 3: TIME-DECAY STATE ===
                 'bars_since_entry': 0,          # Track bars for stagnation detection
                 'time_decay_sl_applied': False, # Flag if Layer 3 moved SL this cycle
                 'marked_for_auto_rotation': False,  # Flag from auto-rotation engine
                 'harvested': False,             # Flag if already harvested
             }
             opening_confidence = float(extracted_ml_conf or 0.0)
             opened_at = getattr(position, 'opened_at', datetime.now(timezone.utc))
             if isinstance(opened_at, str):
                 try:
                     opened_at = datetime.fromisoformat(opened_at)
                 except Exception:
                     opened_at = datetime.now(timezone.utc)
             if opened_at.tzinfo is None:
                 opened_at = opened_at.replace(tzinfo=timezone.utc)
             self.ml_decay_controller.register_position(
                 ticket=int(position.position_id),
                 symbol=position.symbol,
                 opening_ml_confidence=opening_confidence,
                 opened_at=opened_at,
             )
             logger.info(f"[MGMT INIT] Tracking {position.symbol} ID:{pos_id} | R={initial_risk_price/pip_value:.1f} pips")
             self._save_state()
        
        state = self.position_states[pos_id]
        risk_price = state['initial_risk_price']
        if risk_price <= 0: return False
        
        # Update peak profit price with Noise Filtering (0.5 pips)
        # Prevents "SL Drift" due to bid/ask bounce or micro-fluctuations
        pip_val = self._get_pip_value(position.symbol)
        noise_filter = 0.5 * pip_val
        
        if position.direction == Direction.LONG:
            if position.current_price > state.get('peak_profit_price', 0) + noise_filter:
                state['peak_profit_price'] = position.current_price
            profit_price = position.current_price - position.entry_price
        else:
            if position.current_price < state.get('peak_profit_price', 999) - noise_filter:
                state['peak_profit_price'] = position.current_price
            profit_price = position.entry_price - position.current_price
            
        current_R = profit_price / risk_price
        action_taken = False

        # Keep latest regime context for dynamic trailing decisions.
        if regime:
            state['market_regime'] = str(regime).upper()
        if volatility_regime:
            state['volatility_regime'] = str(volatility_regime).upper()
        governance_mode = self._extract_governance_mode(market_data)
        if governance_mode:
            state['governance_mode'] = governance_mode

        # === LAYER 3: TIME-DECAY STOP LOSS MANAGEMENT (Shadow Mode / Live Execution) ===
        # Process time decay logic BEFORE other exit strategies
        # This layer manages SL based on time stagnation and auto-rotation triggers
        if self.time_decay_enabled:
            # Update bars_since_entry counter
            state['bars_since_entry'] = state.get('bars_since_entry', 0) + 1
            
            # Check preflight: ensure bars increment per-bar, not per-pulse
            is_ok, diagnostic = self.preflight_check(pos_id, state['bars_since_entry'])
            
            # Process Layer 3 logic through the TimeDecayStopLossManager
            try:
                # Fetch broker constraints and current market tick
                symbol_info = await self._get_symbol_info(position.symbol)
                mt5_symbol = position.symbol.replace("/", "")
                current_tick = await asyncio.to_thread(mt5.symbol_info_tick, mt5_symbol)
                
                # Call check_and_apply_decay which now handles:
                # - All validation (direction, constraints, preflight checks)
                # - Shadow mode (validate only, log success)
                # - Live mode (validate + execute via broker)
                # Returns: True if valid/success, False if invalid/failed
                decay_handled = await self.time_decay_manager.check_and_apply_decay(
                    position=position,
                    state=state,
                    current_r=current_R,
                    bars_since_entry=state['bars_since_entry'],
                    risk_price=risk_price,
                    symbol_info=symbol_info,
                    current_tick=current_tick,
                    broker=self.broker,  # Pass broker for live mode execution
                )
                
                # decay_handled will be:
                # - True in shadow mode if proposal is valid (logged as [LAYER3_SHADOW_SUCCESS])
                # - True in live mode if MT5 modification succeeded (logged as [LAYER3_APPLIED])
                # - False if validation failed or MT5 modification was rejected
                if decay_handled:
                    logger.debug(
                        "[LAYER3_PROCESSED] %s #%s | Decay logic completed successfully",
                        position.symbol,
                        pos_id,
                    )
                
            except Exception as e:
                logger.error(
                    "[LAYER3_ERROR] %s #%s | Exception in time_decay_manager: %s",
                    position.symbol,
                    pos_id,
                    e,
                    exc_info=True,
                )

        # === DYNAMIC PROFIT COMPRESSION (DPC) LAYER ===
        # Lock in profits at milestone distances to TP (Tier 1/2/3)
        if self.dpc_enabled and position.take_profit and position.take_profit > 0:
            try:
                # Track position in DPC manager
                self.dpc_manager.track_position(
                    ticket=pos_id,
                    symbol=position.symbol,
                    direction=position.direction,
                    entry_price=position.entry_price,
                    tp_price=position.take_profit,
                    current_sl=position.stop_loss or 0.0,
                    commission=float(getattr(position, 'commission', 0.0) or 0.0),
                    swap=float(getattr(position, 'swap', 0.0) or 0.0),
                )
                
                # Check if any compression tier has been hit
                should_modify, new_sl, tier, log_msg = self.dpc_manager.check_compression_tiers(
                    ticket=pos_id,
                    current_price=position.current_price,
                )
                
                if should_modify and new_sl is not None:
                    logger.info(log_msg)
                    
                    # Attempt to modify SL via broker (respects Stops Guard and Shadow Mode)
                    try:
                        modify_ok = await self.broker.modify_order(
                            order_id=pos_id,
                            sl=new_sl,
                            tp=position.take_profit,
                        )
                        if modify_ok:
                            position.stop_loss = new_sl
                            state['last_modified_sl'] = new_sl
                            action_taken = True
                            logger.debug(
                                "[DPC_MODIFIED] %s #%s | SL successfully modified to %.5f",
                                position.symbol,
                                pos_id,
                                new_sl,
                            )
                        else:
                            logger.warning(
                                "[DPC_MODIFY_FAILED] %s #%s | Broker rejected SL modification to %.5f",
                                position.symbol,
                                pos_id,
                                new_sl,
                            )
                    except Exception as modify_exc:
                        logger.error(
                            "[DPC_MODIFY_ERROR] %s #%s | Exception modifying SL: %s",
                            position.symbol,
                            pos_id,
                            modify_exc,
                        )
            except Exception as dpc_exc:
                logger.error(
                    "[DPC_ERROR] %s #%s | Exception in DPC logic: %s",
                    position.symbol,
                    pos_id,
                    dpc_exc,
                    exc_info=True,
                )

        macro_penalty, macro_reason = self._get_macro_risk_state(position.symbol, market_data)
        spread_pips = self._spread_to_pips(position.symbol, float(getattr(market_data, "spread", 0.0) or 0.0))
        if self._is_macro_risk_high(macro_penalty, macro_reason) and spread_pips > 10.0:
            if await self._execute_emergency_news_response(
                trigger_symbol=position.symbol,
                spread_pips=spread_pips,
                macro_penalty=macro_penalty,
                macro_reason=macro_reason,
            ):
                return True
        
        # EXIT PRIORITY RULE:
        # 1. Take Profit (Handled by MT5 server)
        # 2. Stop Loss (Handled by MT5 server)
        # 3. Scale-Out + BE lock (This module)
        # 4. Partial Profit (This module, optional legacy path)
        # 4. Trailing Stop adjustment (This module)
        # 5. Break-even move (This module)
        
        # 2-5. Dynamic Profit Exit controller:
        # 0.5R -> move to BE + 5 pips
        # 1.0R -> close 50%
        # 1.5R -> enable trailing
        if await self._apply_dynamic_profit_lock(position, state):
            self._save_state()
            action_taken = True

        if await self.dynamic_profit_controller.check_exits(self, position, state, atr):
            self._save_state()
            action_taken = True

        if state.get("is_running_as_runner", False):
            if await self._continuous_sl_check(position, state):
                self._save_state()
                action_taken = True

        friday_force_close_hour = int(os.environ.get("MOMENTUM_STALL_FRIDAY_FORCE_CLOSE_HOUR", "16"))
        broker_now = datetime.now(timezone.utc)
        friday_force_close_window = (
            broker_now.weekday() == 4 and broker_now.hour >= friday_force_close_hour
        )

        # === DYNAMIC EXIT SUITE ===
        # Apply the 4 profit-taking exit strategies
        if current_R > 0:  # Only if in profit
            # 1. Profit Shaving at 1.5R (close 50% position)
            if self.settings.use_profit_shaving and not state['profit_shaving_done']:
                if current_R >= self.settings.profit_shaving_trigger_r:
                    if await self._execute_profit_shaving(position, state, current_R, risk_price):
                        action_taken = True

            # 2. RSI-Based Exhaustion Exit
            if self.settings.use_rsi_exhaustion and not state['rsi_exhaustion_done']:
                if current_R > self.settings.rsi_exhaustion_threshold_min_profit_r:
                    if await self._execute_rsi_exhaustion_exit(position, state, current_R, market_data):
                        action_taken = True

            # 3. Momentum Stall Detection
            if self.settings.use_momentum_stall and not state['momentum_stall_done']:
                if current_R > 0:  # Any profit
                    if await self._execute_momentum_stall_exit(position, state, current_R, market_data):
                        action_taken = True

            # 4. EV-Decay Exit
            if self.settings.use_ev_decay_exit and not state['ev_decay_done']:
                if current_R > 0:  # Any profit
                    if await self._execute_ev_decay_exit(position, state, current_R, market_data):
                        action_taken = True
        elif self.settings.use_momentum_stall and not state['momentum_stall_done'] and friday_force_close_window:
            if await self._execute_momentum_stall_exit(position, state, current_R, market_data):
                action_taken = True

        return action_taken

    async def _execute_partial_close(self, position: Position, percent: float) -> bool:
        """Execute partial TP by selling a percentage of current volume"""
        # Normalized Volume
        symbol_info = await self._get_symbol_info(position.symbol)
        if not symbol_info: return False
        
        step = symbol_info.volume_step
        requested_vol = position.quantity * percent
        # Round to volume step
        close_vol = max(step, round(requested_vol / step) * step)
        
        if close_vol >= position.quantity:
            logger.warning(f"Calculated partial volume {close_vol} >= position volume {position.quantity}. Closing full.")
            return await self.broker.close_position(position.position_id)
        
        mt5_symbol = symbol_info.name
        tick = await asyncio.to_thread(mt5.symbol_info_tick, mt5_symbol)
        if not tick: return False
        
        price = tick.bid if position.direction == Direction.LONG else tick.ask
        
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": mt5_symbol,
            "volume": float(close_vol),
            "type": mt5.ORDER_TYPE_SELL if position.direction == Direction.LONG else mt5.ORDER_TYPE_BUY,
            "position": int(position.position_id),
            "price": price,
            "deviation": 20,
            "magic": 234000,
            "comment": f"Partial {int(percent*100)}% R-target",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC, # Attempt IOC
        }
        
        # Use retry logic for partial close as well
        for attempt in range(self.settings.max_retries):
            result = await asyncio.to_thread(mt5.order_send, request)
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                logger.info(f"[PARTIAL SUCCESS] {position.symbol} ID:{position.position_id} closed {close_vol} lots ({int(percent*100)}%)")
                remaining_volume = max(0.0, float(position.quantity) - float(close_vol))
                position.quantity = remaining_volume
                self._sync_shadow_position_volume(position.position_id, remaining_volume)
                return True
            
            # If filling mode error, fallback
            if result.retcode == 10030: # UNSUPPORTED_FILLING
                request["type_filling"] = mt5.ORDER_FILLING_FOK
                continue
                
            logger.warning(f"[PARTIAL RETRY] {position.symbol} partial close failed (code {result.retcode}): {result.comment}. Attempt {attempt+1}")
            await asyncio.sleep(self.settings.retry_delay_ms / 1000.0)
            
        return False

    async def _execute_scale_out_and_lock(self, position: Position, state: Dict[str, Any], current_r: float) -> bool:
        """Harvest partial profit once the configured profit trigger is reached."""
        if not self.settings.use_scale_out:
            return False
        if state.get("scaled_out", False):
            return False
        if current_r < float(self.settings.scale_out_trigger_r or 0.0):
            return False

        close_pct = float(self.settings.scale_out_close_percent or 0.0)
        if close_pct <= 0.0:
            return False

        logger.info(
            "[SCALE_OUT_READY] %s (ID:%s) reached %.2fR. Closing %.0f%% and locking protection.",
            position.symbol,
            position.position_id,
            current_r,
            close_pct * 100.0,
        )

        partial_ok = await self._execute_partial_close(position, close_pct)
        if not partial_ok:
            return False

        state["scaled_out"] = True
        state.setdefault("partial_hits", set()).add("dynamic_partial_1_0r")

        if self.settings.use_breakeven:
            be_ok = await self._move_to_breakeven(
                position,
                atr=0.0,
                use_spread_buffer=bool(self.settings.scale_out_be_with_spread),
                offset_pips=0.0 if self.settings.scale_out_be_with_spread else None,
            )
            if be_ok:
                state["breakeven_reached"] = True

        logger.critical(
            "[SCALE_OUT_CONFIRMED] %s #%s | Closed %.0f%% at %.2fR | BE lock=%s",
            position.symbol,
            position.position_id,
            close_pct * 100.0,
            current_r,
            "ON" if state.get("breakeven_reached", False) else "OFF",
        )
        return True

    async def _continuous_sl_check(self, position: Position, state: Dict[str, Any]) -> bool:
        """Continuously tighten the runner stop from live price once Level 3 has been reached."""
        if not state.get("is_running_as_runner", False):
            return False

        symbol_info = await self._get_symbol_info(position.symbol)
        if not symbol_info:
            return False

        tick = await asyncio.to_thread(mt5.symbol_info_tick, symbol_info.name)
        if not tick:
            return False

        current_price = float(tick.bid if position.direction == Direction.LONG else tick.ask)
        point = float(getattr(symbol_info, "point", 0.0) or 0.0)
        if current_price <= 0.0 or point <= 0.0:
            return False

        buffer_pips = float(self.settings.runner_buffer_pips or 0.0)
        buffer_price = buffer_pips * point * 10.0

        if position.direction == Direction.LONG:
            target_sl = current_price - buffer_price
        else:
            target_sl = current_price + buffer_price

        min_dist = DynamicTrailingSLManager.get_min_dist_from_price(
            DynamicTrailingSLManager,
            position.symbol,
            symbol_info=symbol_info,
        )
        if position.direction == Direction.LONG:
            target_sl = min(float(target_sl), current_price - min_dist)
        else:
            target_sl = max(float(target_sl), current_price + min_dist)

        current_sl = float(getattr(position, "stop_loss", 0.0) or 0.0)
        if current_sl > 0.0:
            if position.direction == Direction.LONG and target_sl <= current_sl:
                return False
            if position.direction == Direction.SHORT and target_sl >= current_sl:
                return False

        logger.info(
            "[CONTINUOUS_TRAIL_ACTIVE] %s (ID:%s) | Runner live | Price=%.5f | Buffer=%.1f pips",
            position.symbol,
            position.position_id,
            current_price,
            buffer_pips,
        )
        return await self._secure_modify_sl(position, target_sl, "CONTINUOUS_TRAIL")

    async def _get_breakeven_buffer_price(
        self,
        symbol: str,
        use_spread_buffer: bool,
        offset_pips: Optional[float] = None,
    ) -> float:
        """Get breakeven buffer in price units (offset pips and optional live spread-aware floor)."""
        effective_offset_pips = (
            float(offset_pips)
            if offset_pips is not None
            else float(self.settings.breakeven_offset_pips)
        )
        base_buffer = effective_offset_pips * self._get_pip_value(symbol)
        if not use_spread_buffer:
            return base_buffer

        try:
            symbol_info = await self._get_symbol_info(symbol)
            if not symbol_info:
                return base_buffer
            tick = await asyncio.to_thread(mt5.symbol_info_tick, symbol_info.name)
            if not tick:
                return base_buffer
            spread = abs(float(tick.ask) - float(tick.bid))
            return max(base_buffer, spread)
        except Exception:
            return base_buffer

    async def _move_to_breakeven(
        self,
        position: Position,
        atr: float = 0.0,
        use_spread_buffer: bool = False,
        offset_pips: Optional[float] = None,
    ) -> bool:
        """Move Stop Loss to entry plus offset"""
        atr_buffer = max(0.0, float(atr or 0.0) * 0.2)
        offset = atr_buffer
        if offset <= 0.0:
            offset = await self._get_breakeven_buffer_price(
                position.symbol,
                use_spread_buffer=use_spread_buffer,
                offset_pips=offset_pips,
            )
        
        if position.direction == Direction.LONG:
            target_sl = position.entry_price + offset
        else:
            target_sl = position.entry_price - offset

        current_sl = float(getattr(position, "stop_loss", 0.0) or 0.0)
        if current_sl > 0:
            already_protected = (
                current_sl >= target_sl if position.direction == Direction.LONG else current_sl <= target_sl
            )
            if already_protected:
                logger.info(
                    "[BREAK_EVEN_ALREADY_SET] %s (ID:%s) | Existing SL %.5f already protects at or beyond target %.5f.",
                    position.symbol,
                    position.position_id,
                    current_sl,
                    target_sl,
                )
                return True
             
        return await self._secure_modify_sl(position, target_sl, "BREAK-EVEN")

    async def _apply_dynamic_profit_lock(self, position: Position, state: Dict[str, Any]) -> bool:
        """Apply percentage-based profit locking before trailing logic activates."""
        if not self.settings.use_dynamic_profit_locking:
            return False

        symbol_info = await self._get_symbol_info(position.symbol)
        if not symbol_info:
            return False

        tick = await asyncio.to_thread(mt5.symbol_info_tick, symbol_info.name)
        if not tick:
            return False

        bid = float(getattr(tick, "bid", 0.0) or 0.0)
        ask = float(getattr(tick, "ask", 0.0) or 0.0)
        if bid <= 0.0 or ask <= 0.0:
            return False

        spread = max(0.0, ask - bid)
        entry_price = float(getattr(position, "entry_price", 0.0) or 0.0)
        if entry_price <= 0.0:
            return False

        current_price = bid if position.direction == Direction.LONG else ask
        risk_price = float(state.get("initial_risk_price") or 0.0)
        current_r = self.dynamic_profit_controller._calculate_current_r(
            position,
            risk_price,
            reference_price=current_price,
        )
        current_profit_pct = self._calculate_profit_percent(position, current_price)
        if current_profit_pct <= 0.0 and current_r <= 0.0:
            return False

        state_hits = state.setdefault("dynamic_profit_lock_hits", set())
        current_sl = float(getattr(position, "stop_loss", 0.0) or 0.0)
        min_step_price = max(
            float(self.settings.dynamic_profit_lock_min_step_pips or 0.0) * self._get_pip_value(position.symbol),
            float(getattr(symbol_info, "trade_tick_size", 0.0) or 0.0),
            float(getattr(symbol_info, "point", 0.0) or 0.0),
        )

        action_taken = False
        for level in self.settings.dynamic_profit_lock_levels:
            trigger_profit_pct = float(level.get("trigger_profit_pct", 0.0) or 0.0)
            trigger_r = float(level.get("trigger_r", 0.0) or 0.0)
            if trigger_r > 0.0:
                if current_r + 1e-9 < trigger_r:
                    continue
            elif current_profit_pct + 1e-9 < trigger_profit_pct:
                continue

            state_key = self._dynamic_profit_lock_state_key(level)
            if state_key in state_hits:
                continue

            target_sl = self._calculate_dynamic_profit_lock_sl(
                position=position,
                entry_price=entry_price,
                current_price=current_price,
                spread=spread,
                level=level,
            )
            if target_sl is None:
                continue

            if current_sl > 0.0:
                if position.direction == Direction.LONG:
                    if target_sl <= current_sl:
                        state_hits.add(state_key)
                        continue
                    if (target_sl - current_sl) < min_step_price:
                        logger.debug(
                            "[DYNAMIC_LOCK_THROTTLED] %s (ID:%s) %.1f%% tier skipped | new SL %.5f is only %.2f pips above current %.5f.",
                            position.symbol,
                            position.position_id,
                            trigger_profit_pct,
                            target_sl,
                            (target_sl - current_sl) / max(self._get_pip_value(position.symbol), 1e-12),
                            current_sl,
                        )
                        continue
                else:
                    if target_sl >= current_sl:
                        state_hits.add(state_key)
                        continue
                    if (current_sl - target_sl) < min_step_price:
                        logger.debug(
                            "[DYNAMIC_LOCK_THROTTLED] %s (ID:%s) %.1f%% tier skipped | new SL %.5f is only %.2f pips below current %.5f.",
                            position.symbol,
                            position.position_id,
                            trigger_profit_pct,
                            target_sl,
                            (current_sl - target_sl) / max(self._get_pip_value(position.symbol), 1e-12),
                            current_sl,
                        )
                        continue

            modified = await self._secure_modify_sl(
                position,
                target_sl,
                f"DYNAMIC_LOCK_{str(trigger_profit_pct).replace('.', '_')}PCT",
            )
            if not modified:
                break

            state_hits.add(state_key)
            if float(level.get("lock_profit_pct", 0.0) or 0.0) <= 0.0:
                state["breakeven_reached"] = True
            action_taken = True
            current_sl = float(getattr(position, "stop_loss", 0.0) or 0.0)

        return action_taken

    def _calculate_profit_percent(self, position: Position, current_price: float) -> float:
        entry_price = float(getattr(position, "entry_price", 0.0) or 0.0)
        if entry_price <= 0.0:
            return 0.0
        if position.direction == Direction.LONG:
            return ((current_price - entry_price) / entry_price) * 100.0
        return ((entry_price - current_price) / entry_price) * 100.0

    def _dynamic_profit_lock_state_key(self, level: Dict[str, float]) -> str:
        trigger_r = float(level.get("trigger_r", 0.0) or 0.0)
        if trigger_r > 0.0:
            return f"lock_r_{str(trigger_r).replace('.', '_')}"
        trigger_profit_pct = float(level.get("trigger_profit_pct", 0.0) or 0.0)
        return f"lock_pct_{str(trigger_profit_pct).replace('.', '_')}"

    def _calculate_dynamic_profit_lock_sl(
        self,
        position: Position,
        entry_price: float,
        current_price: float,
        spread: float,
        level: Dict[str, float],
    ) -> Optional[float]:
        use_entry_plus_spread = bool(float(level.get("use_entry_plus_spread", 0.0) or 0.0))
        if use_entry_plus_spread:
            if position.direction == Direction.LONG:
                return entry_price + spread
            return entry_price - spread

        lock_profit_fraction = float(level.get("lock_profit_fraction", 0.0) or 0.0)
        if lock_profit_fraction > 0.0:
            lock_profit_fraction = max(0.0, min(lock_profit_fraction, 1.0))
            floating_profit = (
                current_price - entry_price if position.direction == Direction.LONG else entry_price - current_price
            )
            if floating_profit <= 0.0:
                return None
            locked_profit = floating_profit * lock_profit_fraction
            if position.direction == Direction.LONG:
                return entry_price + locked_profit
            return entry_price - locked_profit

        lock_profit_pct = float(level.get("lock_profit_pct", 0.0) or 0.0)
        if lock_profit_pct < 0.0:
            return None
        if position.direction == Direction.LONG:
            return entry_price * (1.0 + (lock_profit_pct / 100.0))
        return entry_price * (1.0 - (lock_profit_pct / 100.0))

    def _sync_shadow_position_volume(self, position_id: str, remaining_volume: float) -> None:
        """Persist updated live volume to the shadow tracker after partial closes."""
        if not self.position_manager or not hasattr(self.position_manager, "adopt_shadow_position"):
            return
        try:
            self.position_manager.adopt_shadow_position(
                str(position_id),
                {
                    "volume": float(remaining_volume),
                    "quantity": float(remaining_volume),
                },
                save_immediate=True,
            )
        except Exception as sync_err:
            logger.debug("[DYNAMIC_PROFIT] Shadow volume sync failed for %s: %s", position_id, sync_err)

    def _get_dynamic_trailing_multiplier(self, state: Dict) -> float:
        """Resolve ATR multiplier from active market/volatility regime context."""
        regime_raw = str(state.get('market_regime') or '').upper()
        vol_raw = str(state.get('volatility_regime') or '').upper()
        mapping = self.settings.trailing_atr_by_regime or {}

        alias_map = {
            "TREND": "TRENDING",
            "TRENDING": "TRENDING",
            "RANGE": "RANGING",
            "RANGING": "RANGING",
            "HIGH_VOL": "HIGH_VOLATILITY",
            "HIGH_VOLATILITY": "HIGH_VOLATILITY",
            "VOLATILE": "HIGH_VOLATILITY",
            "LOW_LIQUIDITY": "LOW_LIQUIDITY",
            "ILLIQUID": "LOW_LIQUIDITY",
        }

        regime_key = alias_map.get(regime_raw, regime_raw)
        vol_key = alias_map.get(vol_raw, vol_raw)

        if regime_key in mapping:
            return float(mapping[regime_key])
        if vol_key in mapping:
            return float(mapping[vol_key])
        return float(self.settings.trailing_stop_atr_multiplier)

    async def _apply_trailing_stop(self, position: Position, atr: float, state: Dict, current_r: float) -> bool:
        """Calculate and apply ATR trailing stop"""
        # FIX #4: DPC PRECEDENCE - If DPC Tier 1 is active, skip trailing stop to let Tier 1 manage risk-free entry
        if self.dpc_enabled:
            dpc_state = self.dpc_manager.get_compression_state(position.position_id)
            if dpc_state and dpc_state.tier_1_hit:
                logger.debug(
                    "[TRAILING_SKIP_DPC_T1] %s #%s | DPC Tier 1 already active (risk-free). "
                    "Skipping ATR trailing to preserve DPC precedence.",
                    position.symbol,
                    position.position_id,
                )
                return False
        
        # Breathing-room guard: do not trail before configured R threshold.
        if current_r < self.settings.trailing_stop_activation_r:
            return False

        atr_mult = self._get_dynamic_trailing_multiplier(state)
        if str(state.get("governance_mode") or "").upper() == "DEFENSIVE_PRESERVATION":
            atr_mult *= 0.5
            logger.info(
                "[DEFENSIVE_TRAIL] %s #%s | Governance=DEFENSIVE_PRESERVATION | Tightening ATR multiplier to %.2f",
                position.symbol,
                position.position_id,
                atr_mult,
            )
        trail_dist = atr * atr_mult
        peak = state['peak_profit_price']
        
        if position.direction == Direction.LONG:
            target_sl = peak - trail_dist
        else:
            target_sl = peak + trail_dist
            
        # Ensure we never move SL backward (loosening risk)
        # AND require a minimum improvement of 0.5 pips to reduce API spam/drift
        current_sl = position.stop_loss
        pip_val = self._get_pip_value(position.symbol)
        min_improvement = 0.5 * pip_val
        
        if current_sl and current_sl != 0:
            if position.direction == Direction.LONG:
                if target_sl <= current_sl + min_improvement: return False
            else:
                if target_sl >= current_sl - min_improvement: return False

        # ===== 1.5 RR MATH FLOOR (Post-Entry Protection) =====
        # Forbid ANY ATR update that drops distance-to-TP vs distance-to-SL below 1.5
        # Uses raw price deltas — symbol-agnostic (works for JPY, standard and exotic pairs)
        if position.take_profit and position.take_profit != 0 and target_sl != 0:
            if position.direction == Direction.LONG:
                reward = abs(position.take_profit - position.entry_price)
                new_risk = abs(position.entry_price - target_sl)
            else:
                reward = abs(position.entry_price - position.take_profit)
                new_risk = abs(target_sl - position.entry_price)
            if new_risk > 0:
                proposed_rr = reward / new_risk
                if proposed_rr < 1.5:
                    logger.warning(
                        f"[RR_FLOOR_BLOCK] {position.symbol} #{position.position_id} | "
                        f"ATR trailing SL {target_sl:.5f} would yield RR {proposed_rr:.2f} < 1.5 floor. "
                        f"Update SUPPRESSED to preserve risk integrity."
                    )
                    return False
                logger.debug(
                    f"[RR_FLOOR_PASS] {position.symbol} #{position.position_id} | "
                    f"Proposed RR {proposed_rr:.2f} ≥ 1.5. Trailing update permitted."
                )
        # ======================================================
        
        # ===== RISK CEILING INJECTION (EURUSD) =====
        # Ensure trailing logic NEVER pushes SL above ceiling for EURUSD Shorts
        if position.symbol == 'EURUSD' and position.direction == Direction.SHORT:
            ceil_sl = 1.17945
            if target_sl > ceil_sl:
                 logger.warning(
                     f"[TRAILING_CLAMP] ATR-based SL {target_sl:.5f} exceeds Risk Ceiling {ceil_sl} "
                     f"for EURUSD #{position.position_id}. Clamping to ceiling."
                 )
                 target_sl = ceil_sl

        logger.info(
            "[TRAILING_REGIME] %s #%s | Regime=%s | VolRegime=%s | ATR=%.5f | Mult=%.2f | R=%.2f",
            position.symbol,
            position.position_id,
            state.get('market_regime', 'UNKNOWN'),
            state.get('volatility_regime', 'UNKNOWN'),
            atr,
            atr_mult,
            current_r,
        )
        return await self._secure_modify_sl(position, target_sl, "TRAILING")

    async def _apply_velocity_trailing(self, position: Position, atr: float, state: Dict, current_r: float) -> bool:
        """
        Dynamic "Velocity Trailing" based on R-multiple milestones.
        === FIX #1: DYNAMIC VELOCITY_MODE (replaced static 0.4R with 0.8-1.2R range) ===
        - >1.5R: lock in +0.5R
        - >2.0R: trail at dynamic 0.8R-1.2R (based on volatility)
        - >2.5R: continue dynamic trail from 0.8R-1.2R range
        - All changes respect Min_SL_Distance_ATR floor (1.5x ATR)
        """
        if current_r < 1.5:
            return False

        risk_price = float(state.get("initial_risk_price") or 0.0)
        if risk_price <= 0:
            return False

        entry = float(position.entry_price)
        lock_sl = None
        if position.direction == Direction.LONG:
            lock_sl = entry + (0.5 * risk_price)
        else:
            lock_sl = entry - (0.5 * risk_price)

        trail_sl = None
        if atr > 0 and current_r >= 2.0:
            # === FIX #1: Dynamic VELOCITY_MODE range (0.8-1.2R instead of 0.4-0.2R) ===
            # Calculate volatility-based trail multiplier within 0.8 - 1.2 ATR range
            if current_r >= 2.5:
                # Hyper-trail at 0.8x ATR (tighter)
                trail_mult = 0.8
            else:
                # Standard trail at 1.0x ATR
                trail_mult = 1.0
            
            # If volatility regime supports (low vol), can tighten to 0.8
            vol_regime = state.get('volatility_regime', '').upper()
            if vol_regime == 'LOW_VOLATILITY':
                trail_mult = 0.8
            elif vol_regime == 'HIGH_VOLATILITY':
                trail_mult = 1.2  # Loosen in high vol
            
            trail_dist = atr * trail_mult
            peak = float(state.get("peak_profit_price") or position.current_price)
            if position.direction == Direction.LONG:
                trail_sl = peak - trail_dist
            else:
                trail_sl = peak + trail_dist

        # Pick the more protective SL (never widen risk).
        target_sl = lock_sl
        if trail_sl is not None:
            if position.direction == Direction.LONG:
                target_sl = max(lock_sl or trail_sl, trail_sl)
            else:
                target_sl = min(lock_sl or trail_sl, trail_sl)

        if target_sl is None:
            return False

        # === FIX #1A: Apply Min_SL_Distance_ATR floor before update ===
        min_sl_floor = self.settings.min_sl_distance_atr_multiplier * atr
        current_price = position.current_price
        pip_val = self._get_pip_value(position.symbol)
        
        dist_to_sl = abs(target_sl - current_price)
        if dist_to_sl < min_sl_floor:
            # SL is too close to current price - back it off to floor distance
            if position.direction == Direction.LONG:
                target_sl = current_price - min_sl_floor
            else:
                target_sl = current_price + min_sl_floor
            logger.info(
                f"[MIN_SL_FLOOR] {position.symbol} ID:{position.position_id} | "
                f"Proposed SL too close ({dist_to_sl:.5f}) | Backed off to {min_sl_floor:.5f} (1.5x ATR floor)"
            )

        # Require meaningful improvement to avoid SL spam.
        current_sl = position.stop_loss
        min_improvement = 0.5 * pip_val
        if current_sl and current_sl != 0:
            if position.direction == Direction.LONG:
                if target_sl <= current_sl + min_improvement:
                    return False
            else:
                if target_sl >= current_sl - min_improvement:
                    return False

        modified = await self._secure_modify_sl(position, target_sl, "DYNAMIC_TRAIL", atr=atr)
        if modified:
            if position.direction == Direction.LONG:
                lock_r = (target_sl - entry) / risk_price
            else:
                lock_r = (entry - target_sl) / risk_price
            logger.critical(
                f"[DYNAMIC_EXIT] Symbol {position.symbol} | Trail Active | Current Lock-in: +{lock_r:.2f} R."
            )
        return modified

    async def _secure_modify_sl(
        self,
        position: Position,
        target_sl: float,
        label: str,
        atr: float = 0.0,
        priority_execution: bool = False,
    ) -> bool:
        """Modify SL with broker validation, normalization, retries, cooldown check
        
        === FIX #1B: Modification cooldown check ===
        - No more than once per 5 minutes unless price moved significantly (> 1.0R)
        """

        symbol_info = await self._get_symbol_info(position.symbol)
        if not symbol_info: return False
        
        # === FIX #1B: Cooldown check (do not tighten SL more than once per 5 minutes) ===
        pos_id = str(position.position_id)
        state = self.position_states.get(pos_id, {})
        now = datetime.now(timezone.utc)
        last_mod_time = state.get('last_sl_modification_time')
        cooldown_remaining = self._get_modify_cooldown_remaining(pos_id)
        if cooldown_remaining > 0:
            logger.info(
                "[PROTECTION_COOLDOWN_ACTIVE] %s (ID:%s) %s skipped for %.0fs after repeated broker rejections.",
                position.symbol,
                position.position_id,
                label,
                cooldown_remaining,
            )
            return False
        
        if priority_execution:
            logger.critical(
                "[PRIORITY_EXECUTION] %s ID:%s | %s bypassing modification cooldown.",
                position.symbol,
                position.position_id,
                label,
            )
        elif last_mod_time is not None:
            elapsed_sec = (now - last_mod_time).total_seconds()
            cooldown_sec = self.settings.modification_cooldown_seconds
            
            if elapsed_sec < cooldown_sec:
                # === FIX #3: EMERGENCY CATCH-UP OVERRIDE ===
                # On emergency SL updates (e.g., after UnboundLocalError fix), allow one bypass
                if self.emergency_catchup_active:
                    logger.critical(
                        f"[EMERGENCY_CATCHUP] {position.symbol} ID:{position.position_id} | "
                        f"Bypassing cooldown for emergency SL catch-up (elapsed: {elapsed_sec:.0f}s of {cooldown_sec}s)"
                    )
                else:
                    # Check if price moved significantly to override cooldown
                    risk_price = state.get('initial_risk_price', 0.0)
                    significant_move_threshold = self.settings.significant_price_move_r * risk_price
                    entry = position.entry_price
                    current_price = position.current_price
                    price_move = abs(current_price - entry)
                    
                    if price_move < significant_move_threshold:
                        logger.info(
                            f"[COOLDOWN_BLOCK] {position.symbol} ID:{position.position_id} | "
                            f"Cooldown active ({elapsed_sec:.0f}s of {cooldown_sec}s). "
                            f"Price move {price_move:.5f} < threshold {significant_move_threshold:.5f}. Skipping."
                        )
                        return False
                    else:
                        logger.info(
                            f"[COOLDOWN_OVERRIDE] {position.symbol} ID:{position.position_id} | "
                            f"Significant price move {price_move:.5f} > {significant_move_threshold:.5f}. Proceeding despite cooldown."
                        )
        
        symbol_info = await self._get_symbol_info(position.symbol)
        if not symbol_info: return False

        async def _harvest_unprotected_stall(reason: str) -> bool:
            if label != "MOMENTUM_STALL":
                return False
            logger.warning(
                "[STALL_PROTECTION_DEFERRED] %s ID:%s | %s | Deferring exit and retrying next cycle.",
                position.symbol,
                position.position_id,
                reason,
            )
            logger.info(
                "[STALL_BYPASS] ID:%s | SL modification restricted by broker. Holding position active.",
                position.position_id,
            )
            return False
        
        # 1. Normalize
        normalized_sl = self._normalize_price(target_sl, symbol_info.digits)
        tick_size = max(
            float(getattr(symbol_info, "trade_tick_size", 0.0) or 0.0),
            float(getattr(symbol_info, "point", 0.0) or 0.0),
        )
        if tick_size > 0:
            normalized_sl = self._normalize_price(
                round(float(normalized_sl) / tick_size) * tick_size,
                symbol_info.digits,
            )
        
        # 2. Check Broker Constraints (Stops Level)
        tick = await asyncio.to_thread(mt5.symbol_info_tick, symbol_info.name)
        if not tick: return False
        
        min_distance_points = max(
            float(getattr(symbol_info, "trade_stops_level", 0) or 0),
            float(getattr(symbol_info, "trade_freeze_level", 0) or 0),
        )
        pip_value = self._get_pip_value(position.symbol)
        stops_level_price = (min_distance_points * symbol_info.point) + (0.2 * pip_value)
        price_to_check = tick.bid if position.direction == Direction.LONG else tick.ask
        entry_price = float(getattr(position, "entry_price", 0.0) or 0.0)
        spread_price = abs(float(getattr(tick, "ask", 0.0) or 0.0) - float(getattr(tick, "bid", 0.0) or 0.0))
        broker_min_distance = (float(getattr(symbol_info, "trade_stops_level", 0) or 0.0) * float(getattr(symbol_info, "point", 0.0) or 0.0)) + spread_price
        current_distance = abs(float(price_to_check) - float(normalized_sl))
        min_modify_step = max(
            float(getattr(symbol_info, "trade_stops_level", 0) or 0.0) * float(getattr(symbol_info, "point", 0.0) or 0.0),
            tick_size,
        )

        freeze_level_points = float(getattr(symbol_info, "trade_freeze_level", 0) or 0)
        freeze_distance = (freeze_level_points + 2.0) * float(getattr(symbol_info, "point", 0.0) or 0.0)
        
        if current_distance <= freeze_distance:
            logger.info(
                f"[{label}_ABORT] {position.symbol} ID:{position.position_id} | "
                f"SL {normalized_sl:.5f} is within Freeze Zone ({freeze_distance:.5f}) of current price {price_to_check:.5f}. Aborting locally."
            )
            return False

        # Skip this cycle if the proposed stop is still inside the broker's hard minimum
        # plus spread. This prevents repeated invalid-stop requests from ever reaching MT5.
        if broker_min_distance > 0 and current_distance < broker_min_distance:
            logger.info(
                "[PROTECTION_PREFLIGHT_BLOCK] %s (ID:%s) %s skipped | distance=%.5f < min_required=%.5f (stops+spread).",
                position.symbol,
                position.position_id,
                label,
                current_distance,
                broker_min_distance,
            )
            self._record_modify_failure(
                ticket_id=pos_id,
                symbol=position.symbol,
                label=label,
                reason="BROKER_STOP_LEVEL_PRECHECK",
                comment=f"distance {current_distance:.5f} < required {broker_min_distance:.5f}",
            )
            return False
        
        # For LONG, SL must be < Bid - StopsLevel
        # For SHORT, SL must be > Ask + StopsLevel
        if position.direction == Direction.LONG:
            legal_sl = self._normalize_price(price_to_check - stops_level_price, symbol_info.digits)
            if normalized_sl >= legal_sl:
                logger.warning(
                    "[PROXIMITY_CLAMP] %s ID:%s | %s SL %.5f too close to bid %.5f. Clamping to legal %.5f.",
                    position.symbol,
                    position.position_id,
                    label,
                    normalized_sl,
                    price_to_check,
                    legal_sl,
                )
                normalized_sl = legal_sl
        else:
            legal_sl = self._normalize_price(price_to_check + stops_level_price, symbol_info.digits)
            if normalized_sl <= legal_sl:
                logger.warning(
                    "[PROXIMITY_CLAMP] %s ID:%s | %s SL %.5f too close to ask %.5f. Clamping to legal %.5f.",
                    position.symbol,
                    position.position_id,
                    label,
                    normalized_sl,
                    price_to_check,
                    legal_sl,
                )
                normalized_sl = legal_sl

        protects_profit = (
            normalized_sl > entry_price if position.direction == Direction.LONG else normalized_sl < entry_price
        )
        if label == "MOMENTUM_STALL" and not protects_profit:
            return await _harvest_unprotected_stall("Freeze/stops zone prevented an in-profit SL placement")

        # 3. Validation: Never move backward
        if position.stop_loss and position.stop_loss != 0:
            if position.direction == Direction.LONG and normalized_sl < position.stop_loss:
                if label == "BREAK-EVEN":
                    logger.info(
                        "[BREAK_EVEN_ALREADY_SET] %s (ID:%s) | Existing SL %.5f is tighter than BE target %.5f.",
                        position.symbol,
                        position.position_id,
                        float(position.stop_loss),
                        normalized_sl,
                    )
                    return True
                return await _harvest_unprotected_stall("Clamped SL would widen risk on MOMENTUM_STALL") if label == "MOMENTUM_STALL" else False
            if position.direction == Direction.SHORT and normalized_sl > position.stop_loss:
                if label == "BREAK-EVEN":
                    logger.info(
                        "[BREAK_EVEN_ALREADY_SET] %s (ID:%s) | Existing SL %.5f is tighter than BE target %.5f.",
                        position.symbol,
                        position.position_id,
                        float(position.stop_loss),
                        normalized_sl,
                    )
                    return True
                return await _harvest_unprotected_stall("Clamped SL would widen risk on MOMENTUM_STALL") if label == "MOMENTUM_STALL" else False

        # 4. Modification with Retries (wrapped in try/except to prevent crash)
        # ===== FIX #3: MIN_TP_CHANGE buffer guard =====
        # Broker often rejects tiny SL/TP changes (e.g., Momentum Stall / Auto-Trail),
        # which leads to cooldown spam. If the delta is < 2.0 pips, abort locally.
        request_tp = None
        if label in {"MOMENTUM_STALL", "TRAILING", "DYNAMIC_TRAIL"}:
            min_change_pips = 2.0
            current_sl = float(getattr(position, "stop_loss", 0.0) or 0.0)
            proposed_sl = float(normalized_sl or 0.0)
            current_tp = float(getattr(position, "take_profit", 0.0) or 0.0)
            proposed_tp = current_tp  # secure_modify_sl does not alter TP

            if pip_value and pip_value > 0 and current_sl > 0:
                sl_delta_pips = abs(proposed_sl - current_sl) / float(pip_value)
                tp_delta_pips = abs(proposed_tp - current_tp) / float(pip_value)
                if max(sl_delta_pips, tp_delta_pips) < min_change_pips:
                    logger.critical(
                        "[MOD_GUARD] Skipping tiny modification to prevent broker lock | %s ID:%s | %s | SLΔ=%.2f pips",
                        position.symbol,
                        position.position_id,
                        label,
                        sl_delta_pips,
                    )
                    return False
            if current_sl > 0 and min_modify_step > 0.0:
                sl_delta = abs(proposed_sl - current_sl)
                if sl_delta < min_modify_step:
                    logger.debug(
                        "[STALL_PROTECTION_DEFERRED] %s ID:%s | %s | reason=MIN_SL_CHANGE | "
                        "comment=SL change %.6f below broker minimum step %.6f",
                        position.symbol,
                        position.position_id,
                        label,
                        sl_delta,
                        min_modify_step,
                    )
                    return False
            if current_tp > 0 and min_modify_step > 0.0:
                tp_delta = abs(proposed_tp - current_tp)
                if tp_delta < min_modify_step:
                    logger.debug(
                        "[STALL_PROTECTION_DEFERRED] %s ID:%s | %s | reason=MIN_TP_CHANGE | "
                        "comment=TP change below broker minimum step; sending SL-only modification.",
                        position.symbol,
                        position.position_id,
                        label,
                    )
                    request_tp = None
                else:
                    request_tp = proposed_tp

        try:
            success = await self.broker.modify_order(
                order_id=position.position_id,
                sl=normalized_sl,
                tp=request_tp
            )
        except Exception as modify_err:
            last_modify = getattr(self.broker, "last_modify_result", {}) or {}
            self._record_modify_failure(
                ticket_id=pos_id,
                symbol=position.symbol,
                label=label,
                reason=str(last_modify.get("reason") or "BROKER_EXCEPTION"),
                retcode=last_modify.get("retcode"),
                comment=str(last_modify.get("comment") or modify_err),
            )
            logger.error(
                "[MODIFY_FAILED] %s (ID:%s) %s modification failed: %s | retcode=%s | comment=%s",
                position.symbol,
                position.position_id,
                label,
                modify_err,
                last_modify.get("retcode", "N/A"),
                last_modify.get("comment", "N/A"),
            )
            success = False
        
        if success:
            self._clear_modify_failure_tracking(pos_id)
            if pos_id in self.position_states:
                self.position_states[pos_id]['last_sl_modification_time'] = now
                self.position_states[pos_id]['last_modified_sl'] = normalized_sl
            position.stop_loss = normalized_sl
            log_tag = "[BREAK_EVEN_SUCCESS]" if label == "BREAK-EVEN" else f"[{label} SUCCESS]"
            logger.info(f"{log_tag} {position.symbol} (ID:{position.position_id}) SL moved to {normalized_sl:.5f}")
            logger.critical(
                f"[PROTECTION_CONFIRMED] {position.symbol} #{position.position_id} | "
                f"{label} protection applied | New SL: {normalized_sl:.5f} | "
                f"TP: {position.take_profit} | Bot-managed exit. NOT a manual intervention."
            )
            entry_price = float(getattr(position, "entry_price", 0.0) or 0.0)
            risk_price = float(state.get('initial_risk_price', 0.0) or 0.0)
            locked_r = 0.0
            if risk_price > 0 and entry_price > 0:
                if position.direction == Direction.LONG and normalized_sl > entry_price:
                    locked_r = (normalized_sl - entry_price) / risk_price
                elif position.direction == Direction.SHORT and normalized_sl < entry_price:
                    locked_r = (entry_price - normalized_sl) / risk_price
            if locked_r > 0:
                if pos_id in self.position_states:
                    self.position_states[pos_id]['profit_lock_r'] = locked_r
                logger.critical(
                    "[PROFIT_LOCKED] %s | +%.2fR secured | SL moved to %.5f",
                    position.symbol,
                    locked_r,
                    normalized_sl,
                )
            self._save_state()
            return True
        else:
            last_modify = getattr(self.broker, "last_modify_result", {}) or {}
            self._record_modify_failure(
                ticket_id=pos_id,
                symbol=position.symbol,
                label=label,
                reason=str(last_modify.get("reason") or "BROKER_REJECTED"),
                retcode=last_modify.get("retcode"),
                comment=str(last_modify.get("comment") or ""),
            )
            # Modify often fails if broker is in a freeze period or price is moving fast
            # We already caught StopsLevel, so this is likely a temporary constraint
            if label == "MOMENTUM_STALL":
                logger.warning(
                    "[STALL_PROTECTION_DEFERRED] %s ID:%s | Broker rejected MOMENTUM_STALL protection. Will retry with legal distance next cycle.",
                    position.symbol,
                    position.position_id,
                )
                logger.info(
                    "[STALL_BYPASS] ID:%s | SL modification restricted by broker. Holding position active.",
                    position.position_id,
                )
            logger.warning(
                "[PROTECTION_DEFERRED] %s (ID:%s) Could not apply %s protection. Will retry next cycle. | retcode=%s | comment=%s | reason=%s",
                position.symbol,
                position.position_id,
                label,
                last_modify.get("retcode", "N/A"),
                last_modify.get("comment", "N/A"),
                last_modify.get("reason", "N/A"),
            )
            return False

    async def _get_symbol_info(self, symbol: str) -> Any:
        mt5_symbol = symbol.replace("/", "")
        return await asyncio.to_thread(mt5.symbol_info, mt5_symbol)

    # === DYNAMIC EXIT SUITE METHODS ===
    
    async def _execute_profit_shaving(self, position: Position, state: Dict, current_r: float, risk_price: float) -> bool:
        """
        Profit Shaving Strategy: Close 50% of position at 1.5R (halfway to 3.0R target)
        Ensures every significantly profitable trade locks in at least some gains
        """
        if state['profit_shaving_done']:
            return False
            
        if current_r < self.settings.profit_shaving_trigger_r:
            return False
        
        # Calculate PnL in USD for logging
        pnl_realized = (current_r / 2) * risk_price  # Half the profit locked in
        
        logger.info(
            f"[DYNAMIC_EXIT] Type: PARTIAL_SHAVE | {position.symbol} ID:{position.position_id} "
            f"reached {current_r:.2f}R. Closing 50% position."
        )
        
        success = await self._execute_partial_close(position, self.settings.profit_shaving_close_percent)
        if success:
            state['profit_shaving_done'] = True
            self._save_state()
            logger.critical(
                f"[DYNAMIC_EXIT] Type: PARTIAL_SHAVE | PnL Secured: ${pnl_realized:.2f} | "
                f"{position.symbol} #{position.position_id}"
            )
            return True
        return False

    async def _execute_rsi_exhaustion_exit(self, position: Position, state: Dict, current_r: float, market_data: MarketData) -> bool:
        """
        RSI Exhaustion Exit: Exit when RSI peaks and reverses
        - For LONGs: RSI crosses above 75 (overbought) then ticks downward
        - For SHORTs: RSI crosses below 25 (oversold) then ticks upward
        - Only if profit > 0.5R (defined by use config)
        """
        if state['rsi_exhaustion_done']:
            return False
            
        if current_r <= self.settings.rsi_exhaustion_threshold_min_profit_r:
            return False
        
        # Extract RSI from market_data if available
        current_rsi = None
        if hasattr(market_data, 'indicators') and market_data.indicators:
            current_rsi = market_data.indicators.get('rsi')
        elif isinstance(market_data, dict) and 'rsi' in market_data:
            current_rsi = market_data.get('rsi')
        
        if current_rsi is None:
            return False  # No RSI data available
        
        prev_rsi = state.get('prev_rsi')
        state['prev_rsi'] = current_rsi  # Update for next cycle
        
        if prev_rsi is None:
            return False  # Need at least 2 candles to detect crossing
        
        exit_triggered = False
        direction_label = ""
        
        if position.direction == Direction.LONG:
            # For LONG: detect RSI crossing above 75, then declining
            if not state['rsi_crossed_above']:
                # First, check if RSI crossed above threshold
                if prev_rsi <= self.settings.rsi_exhaustion_long_overbought and current_rsi > self.settings.rsi_exhaustion_long_overbought:
                    state['rsi_crossed_above'] = True
                    logger.info(
                        f"[RSI_EXHAUSTION_PREP] {position.symbol} LONG: RSI crossed above "
                        f"{self.settings.rsi_exhaustion_long_overbought} (now {current_rsi:.1f})"
                    )
            else:
                # Now wait for it to tick downward
                if current_rsi < prev_rsi:
                    exit_triggered = True
                    direction_label = "LONG overbought reversal"
        else:
            # For SHORT: detect RSI crossing below 25, then rising
            if not state['rsi_crossed_below']:
                # First, check if RSI crossed below threshold
                if prev_rsi >= self.settings.rsi_exhaustion_short_oversold and current_rsi < self.settings.rsi_exhaustion_short_oversold:
                    state['rsi_crossed_below'] = True
                    logger.info(
                        f"[RSI_EXHAUSTION_PREP] {position.symbol} SHORT: RSI crossed below "
                        f"{self.settings.rsi_exhaustion_short_oversold} (now {current_rsi:.1f})"
                    )
            else:
                # Now wait for it to tick upward
                if current_rsi > prev_rsi:
                    exit_triggered = True
                    direction_label = "SHORT oversold reversal"
        
        if exit_triggered:
            # Close entire position at market
            pnl_realized = current_r * (position.quantity if position.quantity else 1) * 0.01  # Rough estimate
            
            logger.info(
                f"[DYNAMIC_EXIT] Type: RSI_EXHAUSTION | {position.symbol} ID:{position.position_id} | "
                f"RSI {direction_label} detected at {current_rsi:.1f}, profit {current_r:.2f}R"
            )
            
            success = await self.broker.close_position(position.position_id)
            if success:
                state['rsi_exhaustion_done'] = True
                self._save_state()
                logger.critical(
                    f"[DYNAMIC_EXIT] Type: RSI_EXHAUSTION | PnL Secured: ${pnl_realized:.2f} | "
                    f"{position.symbol} #{position.position_id}"
                )
                return True
        
        self._save_state()
        return False

    async def _execute_momentum_stall_exit(self, position: Position, state: Dict, current_r: float, market_data: MarketData) -> bool:
        """
        Momentum Stall Detection: Tighten trailing stop when price is stuck
        - Detect: Price remains within configured range for self.settings.momentum_stall_candles candles
        - Action: Tighten VELOCITY_MODE trailing from 0.4R to 0.1R (hard lock on current price)
        - Logic: If market stops moving, bot stops "hoping" and starts "locking"
        
        ===== FIX #4: CONSOLIDATE FRIDAY HARVEST LOGIC =====
        NO trade is to be closed on Friday for "Momentum" or "Harvest" reasons unless Net Profit > $5.00
        This prevents spreading small profits away or closing break-even trades before weekend
        """
        if state['momentum_stall_done']:
            return False

        broker_now = datetime.now(timezone.utc)
        friday_force_close_hour = int(os.environ.get("MOMENTUM_STALL_FRIDAY_FORCE_CLOSE_HOUR", "16"))
        if broker_now.weekday() == 4 and broker_now.hour >= friday_force_close_hour:
            net_pnl_dollars = float(
                getattr(position, 'unrealized_pnl', current_r * 0.01 * (position.quantity or 1)) or 0.0
            )
            logger.critical(
                "[MOMENTUM_STALL_FRIDAY_FORCE_CLOSE] %s ID:%s | Friday after %02d:00 with stalled trade at %.2fR ($%.2f net). "
                "Overriding profit/spread thresholds and force-closing before weekend gap risk.",
                position.symbol,
                position.position_id,
                friday_force_close_hour,
                current_r,
                net_pnl_dollars,
            )
            success = await self.broker.close_position(position.position_id)
            if success:
                state['momentum_stall_done'] = True
                self._save_state()
                self.weekend_lockout.add(position.symbol)
                logger.critical(
                    "[WEEKEND_LOCKOUT] %s | Added to weekend lockout list to prevent Friday re-entry loop",
                    position.symbol,
                )
                logger.critical(
                    "[DYNAMIC_EXIT] Type: MOMENTUM_STALL_FRIDAY_FORCE_CLOSE | Weekend risk override executed | %s #%s",
                    position.symbol,
                    position.position_id,
                )
                return True
        # ===== FIX #4: UNIFIED FRIDAY MOMENTUM_STALL THRESHOLD  =====
        # On Friday after 16:00, enforce $5.00 minimum net profit before ANY exit close
        # This consolidates MomentumStall and FridayHarvest logic into one gate
        if False and current_r > 0 and broker_now.weekday() == 4 and broker_now.hour >= 16:
            # Calculate actual dollar P&L (position unrealized_pnl is already net of costs)
            net_pnl_dollars = float(getattr(position, 'unrealized_pnl', current_r * 0.01 * (position.quantity or 1)) or 0.0)
            
            if net_pnl_dollars < 5.0:
                # Net PnL below $5.00 threshold on Friday — SKIP momentum stall close
                logger.info(
                    "[MOMENTUM_STALL_FRIDAY_BYPASS] %s ID:%s | Friday after 16:00 with profit %.2fR ($%.2f net) < $5.00 threshold. "
                    "Skipping momentum stall exit to avoid spreading costs on break-even harvest.",
                    position.symbol,
                    position.position_id,
                    current_r,
                    net_pnl_dollars,
                )
                return False  # ===== FIX #4: HARD REJECTION - Do not close Friday losses or thin profits =====
            
            # Net PnL >= $5.00 on Friday — harvest immediately with market close (not just SL tighten)
            logger.critical(
                "[MOMENTUM_STALL_FRIDAY_HARVEST] %s ID:%s | Friday after 16:00 with profit %.2fR ($%.2f net) >= $5.00 threshold. "
                "Executing immediate market close to harvest profits before weekend.",
                position.symbol,
                position.position_id,
                current_r,
                net_pnl_dollars,
            )
            success = await self.broker.close_position(position.position_id)
            if success:
                state['momentum_stall_done'] = True
                self._save_state()
                # ===== FIX #1: WEEKEND LOCKOUT = Add symbol to lockout list =====
                self.weekend_lockout.add(position.symbol)
                logger.critical(
                    "[WEEKEND_LOCKOUT] %s | Added to weekend lockout list to prevent Friday re-entry loop",
                    position.symbol,
                )
                logger.critical(
                    "[DYNAMIC_EXIT] Type: MOMENTUM_STALL_FRIDAY_HARVEST | Friday harvest close executed | %s #%s",
                    position.symbol,
                    position.position_id,
                )
                return True
        
        # Add current price to history
        pip_value = self._get_pip_value(position.symbol)
        state['price_history'].append(position.current_price)
        
        # Keep only last N prices
        if len(state['price_history']) > self.settings.price_history_max_size:
            state['price_history'] = state['price_history'][-self.settings.price_history_max_size:]
        stall_detected, price_range = self._check_momentum_stall(position, state, pip_value, current_r)
        if not stall_detected:
            return False
        
        # Price is stalled - apply momentum stall exit
        risk_price = state['initial_risk_price']
        stall_sl_distance = self.settings.momentum_stall_velocity_multiplier * risk_price
        
        logger.info(
            f"[DYNAMIC_EXIT] Type: MOMENTUM_STALL | {position.symbol} ID:{position.position_id} | "
            f"Price stalled within {price_range/pip_value:.1f} pips for {self.settings.momentum_stall_candles} candles | "
            f"Tightening trailing to {self.settings.momentum_stall_velocity_multiplier}R lock"
        )
        
        # Calculate hard-lock SL at current price + stall distance
        if position.direction == Direction.LONG:
            target_sl = position.current_price - stall_sl_distance
        else:
            target_sl = position.current_price + stall_sl_distance
        
        pnl_realized = current_r * 0.01 * (position.quantity if position.quantity else 1)
        
        modified = await self._secure_modify_sl(
            position,
            target_sl,
            "MOMENTUM_STALL",
            priority_execution=True,
        )
        if modified:
            state['momentum_stall_done'] = True
            self._save_state()
            logger.critical(
                f"[DYNAMIC_EXIT] Type: MOMENTUM_STALL | PnL Secured: ${pnl_realized:.2f} | "
                f"{position.symbol} #{position.position_id}"
            )
            return True
        
        return False

    def _check_momentum_stall(
        self,
        position: Position,
        state: Dict[str, Any],
        pip_value: float,
        current_r: float,
    ) -> Tuple[bool, float]:
        candles_required = max(1, int(self.settings.momentum_stall_candles))
        opened_at = getattr(position, "opened_at", None)
        if isinstance(opened_at, str):
            try:
                opened_at = datetime.fromisoformat(opened_at)
            except Exception:
                opened_at = None
        if isinstance(opened_at, datetime):
            if opened_at.tzinfo is None:
                opened_at = opened_at.replace(tzinfo=timezone.utc)
            if (datetime.now(timezone.utc) - opened_at).total_seconds() < 900:
                return False, 0.0

        if len(state['price_history']) < candles_required:
            return False, 0.0

        last_n_prices = state['price_history'][-candles_required:]
        price_range = max(last_n_prices) - min(last_n_prices)
        stall_range_price = float(self.settings.momentum_stall_range_pips) * pip_value
        if price_range > stall_range_price:
            return False, price_range

        if current_r > 0 and self._count_recent_adverse_candles(position.direction, state['price_history']) < 3:
            return False, price_range

        return True, price_range

    def _count_recent_adverse_candles(self, direction: Direction, price_history: List[float]) -> int:
        if len(price_history) < 4:
            return 0
        recent_prices = price_history[-4:]
        adverse = 0
        for previous_price, current_price in zip(recent_prices, recent_prices[1:]):
            moved_against = current_price < previous_price if direction == Direction.LONG else current_price > previous_price
            if moved_against:
                adverse += 1
                continue
            break
        return adverse

    async def _execute_ev_decay_exit(self, position: Position, state: Dict, current_r: float, market_data: MarketData) -> bool:
        """
        EV-Decay Exit: Exit when ML confidence drops below threshold or flips
        - Trigger: ML confidence for trade direction drops below 5%
        - Alternative: ML confidence flips to opposite direction (negative crossover)
        - Action: Close entire position at market if currently in any profit
        - Reason: If AI no longer believes in the trade, exit with the gain
        """
        if state['ev_decay_done']:
            return False
        
        # Extract ML confidence from market_data
        current_ml_conf = None
        if hasattr(market_data, 'ml_confidence'):
            current_ml_conf = market_data.ml_confidence
        elif hasattr(market_data, 'indicators') and market_data.indicators:
            current_ml_conf = market_data.indicators.get('ml_confidence')
        elif isinstance(market_data, dict):
            current_ml_conf = market_data.get('ml_confidence')
        
        if current_ml_conf is None:
            return False  # No ML confidence data available
        
        prev_ml_conf = state.get('prev_ml_confidence', current_ml_conf)
        state['prev_ml_confidence'] = current_ml_conf

        should_exit, controller_reason, controller_details = self.ml_decay_controller.should_trigger_ml_decay_exit(
            ticket=int(position.position_id),
            symbol=position.symbol,
            current_ml_confidence=float(current_ml_conf),
        )

        flip_triggered = (
            (prev_ml_conf > 0 and current_ml_conf <= 0) or
            (prev_ml_conf < 0 and current_ml_conf >= 0)
        )

        if should_exit or flip_triggered:
            pnl_realized = current_r * 0.01 * (position.quantity if position.quantity else 1)
            trigger_reason = "confidence flip" if flip_triggered else controller_reason
            
            logger.info(
                f"[DYNAMIC_EXIT] Type: ML_DECAY | Mode: PRIORITY_EXECUTION | {position.symbol} ID:{position.position_id} | "
                f"ML confidence {trigger_reason}: was {prev_ml_conf:.3f}, now {current_ml_conf:.3f} | "
                f"Details: {controller_details}"
            )
            
            success = await self.broker.close_position(position.position_id)
            if success:
                state['ev_decay_done'] = True
                self._save_state()
                logger.critical(
                    f"[DYNAMIC_EXIT] Type: ML_DECAY | PnL Secured: ${pnl_realized:.2f} | "
                    f"{position.symbol} #{position.position_id}"
                )
                return True
        
        return False

    def close_tracking(self, position_id: str):
        """Cleanup when trade is exited"""
        pos_id = str(position_id)
        if pos_id in self.position_states:
             logger.debug(f"[MGMT CLEANUP] Removing tracking for ID:{pos_id}")
             del self.position_states[pos_id]
        self.shield_cooldowns.pop(pos_id, None)
        try:
            self.ml_decay_controller.unregister_position(int(position_id))
        except Exception:
            pass
        self._save_state()

    def get_summary(self) -> Dict[str, Any]:
        """Get summary of managed trades"""
        be_count = sum(1 for p in self.position_states.values() if p.get('breakeven_reached'))
        trail_count = sum(1 for p in self.position_states.values() if p.get('trailing_active'))
        
        return {
            "tracked_count": len(self.position_states),
            "breakeven_count": be_count,
            "trailing_count": trail_count,
            "symbols": list(set(p.get('symbol') for p in self.position_states.values()))
        }
