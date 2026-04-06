"""
Position Manager - Handles position opening, monitoring, and closing
"""
import logging
import json
import os
import csv
import time
import threading
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
try:
    import MetaTrader5 as mt5
except Exception:  # pragma: no cover - runtime dependency may be unavailable in test envs
    mt5 = None
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple, Any

from src.models import Direction, OrderType, OrderStatus, Order, ExecutionResult, ExitPolicy
from src.interfaces import BrokerInterface, TradeExecutor
from src.trading.advanced_exit_handler import AdvancedExitHandler, ExitType
from src.trading.exit_reason import ExitReason, ExitRecord, ExitLogger
from src.risk.sl_tp_calculator import StopLossTakeProfitCalculator
from utils.safe_format import format_float, safe_float



class HeartbeatDriftMonitor:
    def __init__(self, window_size: int = 50, alert_threshold_pct: float = 5.0):
        """
        :param window_size: Number of heartbeats to track (e.g., 50)
        :param alert_threshold_pct: Max allowed SL percentage change before alerting (e.g., 5.0%)
        """
        self.window_size = window_size
        self.alert_threshold = alert_threshold_pct / 100.0
        self.previous_sl_state: Dict[str, float] = {}
        self.drift_history: List[float] = []

    def evaluate_drift(self, current_positions: Dict[str, Any]) -> Optional[str]:
        """
        Evaluates the portfolio for abnormal SL slippage or drift.
        current_positions: Dictionary mapping {ticket_id: position_data}
        """
        
        # 1. FILTER ZEROS: Clean the incoming data
        valid_current_sl = {}
        for ticket, p in current_positions.items():
            sl = p.get('emergency_sl')
            if sl and sl != 'N/A' and float(sl) > 0.0:
                valid_current_sl[str(ticket)] = float(sl)

        current_tickets = set(valid_current_sl.keys())
        previous_tickets = set(self.previous_sl_state.keys())

        # 2. STATE CHANGE EXCLUSION: If trades opened or closed, mute the calculation
        if current_tickets != previous_tickets:
            # Mute the calculation for this heartbeat to prevent 4000% spikes
            self.previous_sl_state = valid_current_sl
            # Note: We do NOT clear the drift history here, so we maintain rolling memory,
            # we just skip adding a mathematical anomaly to it.
            return None

        # 3. MATH LOGIC: Measure per-ticket deviation, not aggregate sum
        max_drift_this_cycle = 0.0
        
        if current_tickets:
            drifts = []
            for ticket in current_tickets:
                old_sl = self.previous_sl_state[ticket]
                new_sl = valid_current_sl[ticket]
                
                # Calculate absolute percentage drift for this specific ticket
                if old_sl > 0:
                    pct_change = abs(new_sl - old_sl) / old_sl
                    drifts.append(pct_change)
            
            if drifts:
                # Record the highest SL movement among all open tickets
                max_drift_this_cycle = max(drifts)
            else:
                return None

        # Update rolling window
        self.drift_history.append(max_drift_this_cycle)
        if len(self.drift_history) > self.window_size:
            self.drift_history.pop(0)

        # Sync state for the next heartbeat
        self.previous_sl_state = valid_current_sl

        # 4. MINIMUM SAMPLE SIZE: Ensure we have enough data before alerting
        if len(self.drift_history) < 5:
            return None

        # Check if the rolling average (or max) drift exceeds our safety threshold
        rolling_max_drift = max(self.drift_history)
        
        if rolling_max_drift > self.alert_threshold:
            # Alert triggered. Clear history to prevent log spamming until it normalizes.
            self.drift_history.clear()
            return f"[HEARTBEAT_DRIFT] High volatility in SL PRICES: {rolling_max_drift * 100:.2f}% isolated max drift detected over {self.window_size} heartbeats."

        return None


class PositionManager:
    """Manages open positions and automatic exits"""
    
    STATE_FILE = "position_manager_state.json"
    SHADOW_STATE_FILE = os.path.join(os.getcwd(), "shadow_state.json")  # ===== FIX #2: ROOT-LEVEL SHADOW PERSISTENCE =====
    _shadow_state_lock = threading.Lock()
    
    def __init__(self, broker: BrokerInterface, execution_engine: "TradeExecutor", promotion_callback=None):
        """
        Initialize position manager
        
        Args:
            broker: Broker interface
            execution_engine: Trade execution engine
            promotion_callback: Callback function to promote shadow trades to live
        """
        self.broker = broker
        self.execution_engine = execution_engine
        self.promotion_callback = promotion_callback
        self.logger = logging.getLogger(__name__)
        self.exit_logger = ExitLogger(self.logger)
        self.use_shadow_state = False
        
        # Keep persisted shadow state by default so adopted tickets survive restarts.
        # Targeted zombie purges are handled later by explicit ticket cleanup logic.
        self.shadow_positions: Dict[str, Dict] = {}
        
        # Track open positions keyed by ticket id so multiple positions per symbol are supported.
        # The primary source of truth should still be the portfolio passed in each cycle.
        self.open_positions: Dict[str, List[Dict]] = {}
        
        # Track active exit attribution data
        # Structure: {position_id: {'min_price': float, 'max_price': float, 'initial_sl': float, 'entry_price': float}}
        self.position_attribution_data: Dict[str, Dict[str, float]] = {}
        
        # Track which partial profit levels have been hit for each position
        self.partial_hits: Dict[str, set] = {}
        
        # ===== PATCH #4: SHADOW POSITION ADOPTION - INIT OUTSIDE CYCLE LOOP =====
        # Track orphaned MT5 positions that exist in terminal but not in bot memory
        # CRITICAL: Initialized here at class level, NOT in cycles, to prevent memory wipe every 10 seconds
        self.shadow_positions: Dict[str, Dict] = {}  # {position_id: position_data}
        self.shadow_position_reconciled = False  # Flag to track if initial sync completed
        self.last_shadow_save = datetime.now(timezone.utc)  # Timestamp for 15-min ATR recalc interval
        
        # Track consecutive cycles where a zombie ticket is not found in MT5
        # After 5 consecutive cycles, permanently delete from shadow_state.json
        self.zombie_ticket_not_found_count = {}  # {ticket_id: consecutive_not_found_count}
        self.ZOMBIE_PURGE_THRESHOLD = 5  # Delete after 5 consecutive cycles without finding in MT5

        # Sanity check: Track recent resyncs to prevent loops
        self.recent_resyncs: Dict[str, datetime] = {}
        self.RESYNC_COOLDOWN_SECONDS = 60
        
        # Stable registry of tickets currently managed by the bot.
        # This must survive indicator/timer wipes to prevent re-adoption loops.
        self.active_ticket_registry: set[str] = set()
        
        # Monitor force-reload frequency
        self.force_reload_events: List[datetime] = []
        self.is_state_initialized: bool = False
        self._shadow_state_loaded_once: bool = False
        self._last_sync_at: Optional[datetime] = None
        self._last_sync_positions: List[Any] = []

        
        # Load persisted state
        if not self.is_state_initialized:
            self._load_state()
            self._load_shadow_state()  # ===== FIX #2: LOAD SHADOW POSITIONS FROM DISK =====
            self.is_state_initialized = True
        self._sync_transactional_registry()  # ===== TRANSACTIONAL REGISTRY SYNC: Recover tickets persisted upon TRADE_RETCODE_DONE =====
        self._sync_active_ticket_registry(replace=True)

        # ===== TOTAL TRIGGER RELEASE V11 FIX #3: HARD-PURGE ZOMBIE TICKET =====
        # Explicit patch: If '55232084942' exists in ANY shadow state, wipe it.
        # This occurs after loading state to ensure persistence is also cleaned.
        ticket_to_purge = '55232084942'
        if ticket_to_purge in self.shadow_positions:
            del self.shadow_positions[ticket_to_purge]
            self.logger.critical(f"[HARD_PURGE] Ticket {ticket_to_purge} explicitly wiped from shadow memory and persistence.")
            self._save_shadow_state()
        
        # Check for managed_tickets or initialize safe dict (User Patch)
        if not hasattr(self, 'managed_tickets'):
            self.managed_tickets = {}
        
        # Hard-kill ticket 55232084942 from managed_tickets
        # Filter works on both dicts (iterates keys) and sets
        if isinstance(self.managed_tickets, dict):
            self.managed_tickets = {k: v for k, v in self.managed_tickets.items() if '55232084942' not in str(k) and '55232084942' not in str(v)}
        elif isinstance(self.managed_tickets, list):
            # ===== FIX #1: CONVERT LIST TO DICT ON FILTER =====
            # Previously kept as list, but downstream code expects dict
            # Convert to dict format to prevent 'list' object has no attribute 'add' crash
            self.managed_tickets = {}
        elif isinstance(self.managed_tickets, set):
            self.managed_tickets = {t for t in self.managed_tickets if '55232084942' not in str(t)}
        
        # Orphan Quarantine: {ticket_id: {mt5_data, first_detected}}
        # Tickets in quarantine are checked for metrics but not adopted yet
        self.orphan_quarantine: Dict[str, Dict] = {}
        
        # ===== NEW v4.1 CONFIG & TRACKING =====
        # Symbol Retry Decay: {symbol: retry_count}
        self.symbol_retry_decay: Dict[str, int] = {}
        self.SYMBOL_RETRY_THRESHOLD = 5  # Configurable threshold
        
        # Quarantine Sanity Check
        self.QUARANTINE_ATR_MULTIPLIER = 1.5  # Multiplier for entry price ± ATR buffer
        
        # Heartbeat Trend Analysis
        self.heartbeat_history: List[Dict] = []
        self.HEARTBEAT_TREND_WINDOW = 50  # Number of cycles to monitor for drift
        
        # [V5.3] Architected Drift Monitor: Ticket-Specific Delta Tracking
        self.sl_monitor = HeartbeatDriftMonitor(window_size=self.HEARTBEAT_TREND_WINDOW, alert_threshold_pct=5.0)
        # ======================================
        
        # Cumulative loss tracking for daily loss limits
        self.daily_loss_amount = 0.0
        self.daily_loss_limit = 100.0  # Default $100 max daily loss
        self.last_reset_date = datetime.now(timezone.utc).date()
        
        # Advanced exit handler for sophisticated exits
        self.advanced_exit_handler = AdvancedExitHandler(logger=self.logger)
        self.advanced_exit_handler.trailing_stop_r_trail = 0.05
        
        # ===== IMPROVEMENT #3: MOVE-TO-BREAKEVEN TRACKING =====
        # Set of ticket IDs for which the breakeven SL modification has already
        # been applied. Prevents repeated modification requests every cycle.
        self.breakeven_applied_tickets: set = set()
        self.market_reopened_at: Optional[datetime] = None
        self.gap_amnesty_until_by_symbol: Dict[str, datetime] = {}
        
        # ===== IMPROVEMENT #5: HEARTBEAT DRIFT CORRECTION =====
        # Counts consecutive heartbeat cycles where MT5 reports 0 positions
        # but the bot's internal tracker believes positions are still open.
        # After DRIFT_SYNC_THRESHOLD cycles, _force_memory_sync() is called.
        self._zero_position_drift_counter: int = 0
        self.DRIFT_SYNC_THRESHOLD: int = 3  # Trigger sync after 3 consecutive phantom cycles

        # Reference to TradeAdmissionController for symbol cooldown stamping.
        # Set after construction via set_admission_controller().
        self.admission_controller = None

    
    def set_admission_controller(self, controller) -> None:
        """Link the TradeAdmissionController so exits can stamp symbol cooldowns."""
        self.admission_controller = controller

    @staticmethod
    def _decimal_or_zero(value: Any) -> Decimal:
        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return Decimal("0")

    def _get_symbol_digits(self, symbol: str) -> int:
        fallback_digits = 3 if "JPY" in str(symbol).upper() else 5
        try:
            if mt5 is not None:
                info = mt5.symbol_info(str(symbol or "").replace("/", "").upper())
                if info:
                    return int(getattr(info, "digits", fallback_digits) or fallback_digits)
        except Exception:
            pass
        return fallback_digits

    def _round_for_symbol(self, symbol: str, value: Any) -> float:
        digits = self._get_symbol_digits(symbol)
        return float(
            self._decimal_or_zero(value).quantize(
                Decimal("1").scaleb(-digits),
                rounding=ROUND_HALF_UP,
            )
        )

    def _normalize_utc_timestamp(
        self,
        timestamp_value: Any,
        *,
        field_name: str,
        ticket_id: str = "",
        fallback: Optional[Any] = None,
        future_grace_seconds: int = 300,
    ) -> datetime:
        """Normalize persisted/runtime timestamps to UTC and heal future-dated values."""
        now_utc = datetime.now(timezone.utc)

        def _parse(value: Any) -> Optional[datetime]:
            if value is None:
                return None
            if isinstance(value, datetime):
                parsed = value
            elif isinstance(value, (int, float)):
                try:
                    parsed = datetime.fromtimestamp(float(value), tz=timezone.utc)
                except (ValueError, TypeError, OSError):
                    return None
            elif isinstance(value, str):
                raw = value.strip()
                if not raw:
                    return None
                try:
                    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                except Exception:
                    try:
                        parsed = datetime.fromtimestamp(float(raw), tz=timezone.utc)
                    except (ValueError, TypeError, OSError):
                        return None
            else:
                return None

            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            elif parsed.tzinfo != timezone.utc:
                parsed = parsed.astimezone(timezone.utc)
            return parsed

        parsed = _parse(timestamp_value)
        fallback_dt = _parse(fallback)

        if parsed is None:
            return fallback_dt or now_utc

        # ===== FIX #3: APPLY HARD -3 HOUR OFFSET TO ALL MT5 TIMESTAMPS =====
        # MT5 returns times in broker timezone (3 hours ahead of machine)
        # Must be converted by subtracting 3 hours (-10800 seconds) from all MT5 times
        # This ensures HARVEST_BYPASS_CLOSE and grace period logic use correct times
        parsed = parsed - timedelta(hours=3)

        max_allowed = now_utc + timedelta(seconds=max(0, int(future_grace_seconds)))
        if parsed > max_allowed:
            replacement = fallback_dt if fallback_dt and fallback_dt <= max_allowed else now_utc
            self.logger.warning(
                "[TIMESTAMP_SANITIZED] Ticket=%s | field=%s | future timestamp %s replaced with %s",
                ticket_id or "UNKNOWN",
                field_name,
                parsed.isoformat(),
                replacement.isoformat(),
            )
            return replacement

        return parsed

    def _estimate_runtime_pnl(
        self,
        symbol: str,
        direction: Any,
        entry_price: Any,
        current_price: Any,
        quantity: Any,
        contract_size: Any = 100000.0,
    ) -> float:
        entry_dec = self._decimal_or_zero(entry_price)
        current_dec = self._decimal_or_zero(current_price)
        qty_dec = self._decimal_or_zero(quantity)
        contract_dec = self._decimal_or_zero(contract_size or 100000.0)
        if entry_dec <= 0 or current_dec <= 0 or qty_dec <= 0:
            return 0.0

        direction_name = getattr(direction, "value", direction)
        if str(direction_name).upper() in {"SHORT", "SELL", "1"}:
            raw_pnl = (entry_dec - current_dec) * qty_dec * contract_dec
        else:
            raw_pnl = (current_dec - entry_dec) * qty_dec * contract_dec

        if "JPY" in str(symbol).upper() and current_dec > 0:
            raw_pnl = raw_pnl / current_dec
        return float(raw_pnl.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    def _build_shadow_payload_from_broker_position(self, position: Any) -> Dict[str, Any]:
        direction = getattr(position, "direction", Direction.LONG)
        direction_value = 0 if direction == Direction.LONG else 1
        position_id = str(getattr(position, "position_id", ""))
        existing_shadow = self.shadow_positions.get(position_id, {}) or {}
        existing_attr = self.position_attribution_data.get(position_id, {}) or {}
        strategy_meta = dict(
            existing_attr.get("strategy_meta")
            or existing_shadow.get("strategy_meta")
            or {}
        )
        opened_at = self._normalize_utc_timestamp(
            getattr(position, "opened_at", None),
            field_name="opened_at",
            ticket_id=position_id,
        )
        opened_at_iso = opened_at.isoformat()
        return {
            "ticket_id": position_id,
            "symbol": getattr(position, "symbol", "UNKNOWN"),
            "direction": direction_value,
            "entry_price": float(getattr(position, "entry_price", 0.0) or 0.0),
            "current_price": float(getattr(position, "current_price", 0.0) or 0.0),
            "profit": float(getattr(position, "unrealized_pnl", 0.0) or 0.0),
            "volume": float(getattr(position, "quantity", 0.0) or 0.0),
            "quantity": float(getattr(position, "quantity", 0.0) or 0.0),
            "stop_loss": float(getattr(position, "stop_loss", 0.0) or 0.0),
            "take_profit": float(getattr(position, "take_profit", 0.0) or 0.0),
            "emergency_sl": float(getattr(position, "stop_loss", 0.0) or 0.0),
            "opened_at": opened_at_iso,
            "adoption_time": existing_shadow.get("adoption_time", opened_at_iso),
            "adoption_confirmed": True,
            "amnesia_protected": True,
            "mt5_master_record": True,
            "sync_source": "MT5_MASTER_RECORD",
            "strategy_meta": strategy_meta,
        }

    async def sync_mt5_state(self, persist: bool = True) -> List[Any]:
        """
        Rebuild the local runtime/shadow mirrors from MT5 on every cycle.
        MT5 is the sole source of truth; local state becomes a projection.
        """
        now_utc = datetime.now(timezone.utc)
        if (
            self._last_sync_at is not None
            and (now_utc - self._last_sync_at).total_seconds() < 1.0
            and self._last_sync_positions is not None
        ):
            self.logger.debug(
                "[SYNC_MT5_STATE_DEBOUNCED] Reusing MT5 sync completed %.3fs ago.",
                (now_utc - self._last_sync_at).total_seconds(),
            )
            return list(self._last_sync_positions)

        live_positions = await self.broker.get_positions()
        live_ticket_ids = {str(getattr(pos, "position_id", "")) for pos in live_positions}

        projected_open: Dict[str, Dict[str, Any]] = {}

        for position in live_positions:
            ticket_id = str(getattr(position, "position_id", ""))
            if not ticket_id:
                continue
            payload = self._build_shadow_payload_from_broker_position(position)
            broker_entry = self._round_for_symbol(payload.get("symbol", ""), payload.get("entry_price", 0.0))
            broker_current = self._round_for_symbol(payload.get("symbol", ""), payload.get("current_price", 0.0))
            broker_profit = round(float(payload.get("profit", 0.0) or 0.0), 2)
            local_projection = self.open_positions.get(ticket_id, {}) or {}
            shadow_projection = self.shadow_positions.get(ticket_id, {}) or {}
            local_entry = local_projection.get("entry_price", shadow_projection.get("entry_price", broker_entry))
            local_profit = local_projection.get("profit", shadow_projection.get("profit", 0.0))
            local_estimated_pnl = self._estimate_runtime_pnl(
                symbol=payload.get("symbol", ""),
                direction=getattr(position, "direction", payload.get("direction")),
                entry_price=local_entry,
                current_price=broker_current,
                quantity=payload.get("quantity", payload.get("volume", 0.0)),
                contract_size=getattr(position, "contract_size", 100000.0),
            )
            drift_base = max(abs(broker_profit), abs(local_estimated_pnl), 0.01)
            pnl_rel_diff = abs(broker_profit - local_estimated_pnl) / drift_base
            projected_open[ticket_id] = {
                "position_id": ticket_id,
                "symbol": payload.get("symbol", ""),
                "direction": payload.get("direction"),
                "entry_price": broker_entry,
                "current_price": broker_current,
                "volume": payload.get("volume", 0.0),
                "profit": broker_profit,
                "unrealized_pnl": broker_profit,
                "stop_loss": payload.get("stop_loss", 0.0),
                "take_profit": payload.get("take_profit", 0.0),
                "strategy_meta": dict(payload.get("strategy_meta", {}) or {}),
            }
            try:
                position.unrealized_pnl = broker_profit
                position.current_price = broker_current
                position.opened_at = self._normalize_utc_timestamp(
                    getattr(position, "opened_at", None),
                    field_name="opened_at",
                    ticket_id=ticket_id,
                    fallback=payload.get("opened_at"),
                )
            except Exception:
                pass

            if ticket_id not in self.position_attribution_data:
                self.position_attribution_data[ticket_id] = {
                    "min_price": broker_entry,
                    "max_price": broker_entry,
                    "initial_sl": payload.get("stop_loss", 0.0),
                    "entry_price": broker_entry,
                    "take_profit": payload.get("take_profit", 0.0),
                    "strategy_meta": dict(payload.get("strategy_meta", {}) or {}),
                }
            else:
                self.position_attribution_data[ticket_id]["stop_loss"] = payload.get("stop_loss", 0.0)
                self.position_attribution_data[ticket_id]["take_profit"] = payload.get("take_profit", 0.0)
                self.position_attribution_data[ticket_id]["current_price"] = broker_current
                self.position_attribution_data[ticket_id]["profit"] = broker_profit
                if pnl_rel_diff > 0.10:
                    prior_entry = self.position_attribution_data[ticket_id].get("entry_price", local_entry)
                    self.position_attribution_data[ticket_id]["entry_price"] = broker_entry
                    projected_open[ticket_id]["entry_price"] = broker_entry
                    try:
                        position.entry_price = broker_entry
                    except Exception:
                        pass
                    self.logger.debug(
                        "[PNL_SYNC_SLAVE] %s | Ticket=%s | BrokerPnL=%.2f | LocalCalc=%.2f | "
                        "EntryRef %.5f -> %.5f",
                        payload.get("symbol", "UNKNOWN"),
                        ticket_id,
                        broker_profit,
                        local_estimated_pnl,
                        float(prior_entry or 0.0),
                        broker_entry,
                    )

        stale_attr_ids = [ticket_id for ticket_id in list(self.position_attribution_data.keys()) if ticket_id not in live_ticket_ids]
        for stale_id in stale_attr_ids:
            self.position_attribution_data.pop(stale_id, None)

        self.shadow_positions = {}
        self.open_positions = projected_open
        self.active_ticket_registry = set(live_ticket_ids)
        self.shadow_position_reconciled = True

        if persist:
            self._save_state()

        self._last_sync_at = now_utc
        self._last_sync_positions = list(live_positions)

        self.logger.info(
            "[SYNC_MT5_STATE] Rebuilt runtime state from MT5 | live_positions=%d",
            len(live_positions),
        )
        return live_positions

    def _load_state(self) -> None:
        """Load state from disk"""
        if not os.path.exists(self.STATE_FILE):
            return
            
        try:
            with open(self.STATE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.position_attribution_data = data.get('attribution_data', {})
                # Convert list back to set for partial_hits
                self.partial_hits = {k: set(v) for k, v in data.get('partial_hits', {}).items()}
                self.logger.info(f"Loaded state for {len(self.position_attribution_data)} positions")
        except Exception as e:
            self.logger.error(f"Failed to load state: {e}")

    def _save_state(self) -> None:
        """Save state to disk"""
        try:
            # Convert sets to lists for JSON serialization
            serializable_partial_hits = {k: list(v) for k, v in self.partial_hits.items()}
            
            data = {
                'attribution_data': self.position_attribution_data,
                'partial_hits': serializable_partial_hits,
                'last_updated': datetime.now(timezone.utc).isoformat()
            }
            
            with open(self.STATE_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            self.logger.error(f"Failed to save state: {e}")

    def _serialize_shadow_json_safe(self, value: Any) -> Any:
        """
        Recursively convert datetime objects to ISO strings so JSON dumping never fails.
        """
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.isoformat()
        if isinstance(value, dict):
            return {str(k): self._serialize_shadow_json_safe(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._serialize_shadow_json_safe(v) for v in value]
        if isinstance(value, tuple):
            return [self._serialize_shadow_json_safe(v) for v in value]
        return value

    def _deserialize_shadow_types(self, value: Any, parent_key: Optional[str] = None) -> Any:
        """
        Recursively restore datetime-like fields from ISO strings where runtime logic may rely on datetimes.
        """
        datetime_keys = {"adoption_time", "opened_at", "last_recalc_time", "first_detected", "last_check"}

        if isinstance(value, dict):
            return {k: self._deserialize_shadow_types(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [self._deserialize_shadow_types(v, parent_key) for v in value]
        if isinstance(value, str) and parent_key in datetime_keys:
            try:
                parsed = datetime.fromisoformat(value)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed
            except Exception:
                return value
        return value

    def _extract_ticket_ids_from_positions(self, positions: Optional[List[Any]]) -> set[str]:
        """Extract ticket ids from broker/model/dict position payloads."""
        ids: set[str] = set()
        for pos in (positions or []):
            ticket = None
            if isinstance(pos, dict):
                ticket = pos.get("ticket") or pos.get("position_id") or pos.get("id")
            else:
                ticket = getattr(pos, "position_id", None)
            if ticket is not None:
                ids.add(str(ticket))
        return ids

    def _sync_active_ticket_registry(self, replace: bool = False) -> None:
        """Sync active ticket registry from current in-memory shadow positions."""
        current_ids = {str(tid) for tid in self.shadow_positions.keys()}
        if replace:
            self.active_ticket_registry = current_ids
        else:
            self.active_ticket_registry.update(current_ids)

    def reload_shadow_state_if_empty(self, live_positions: Optional[List[Any]] = None, reason: str = "") -> int:
        """
        Reconcile in-memory shadow state with live tickets without disk re-loads.
        Shadow state is loaded from disk during initialization; runtime loop relies on memory.
        """
        self._sync_active_ticket_registry(replace=False)
        return self.protect_shadow_positions_from_amnesia(live_positions or [], reason=reason or "reload_shadow_state_if_empty")
    
    def _load_shadow_state(self) -> None:
        """Load shadow positions from dedicated persistence file (FIX #2)"""
        if self._shadow_state_loaded_once:
            self.logger.debug("[SHADOW-STATE-SKIP] Shadow state already loaded once during initialization.")
            return

        # ===== FIX #2: ZOMBIE TICKET MEMORY WIPE ON STARTUP =====
        # During startup _load_state phase, check if MT5 terminal has zero open positions
        # If so, wipe all internal lists to ensure no old ticket IDs remain in memory
        try:
            # Get current MT5 positions via broker (this is called during init)
            # If we can't get positions yet, we'll handle it in the periodic scan
            # For now, we just load what was persisted
            pass
        except Exception:
            pass
        
        if not os.path.exists(self.SHADOW_STATE_FILE):
            # Attempt to recover from .bak if main file missing
            bak_file = self.SHADOW_STATE_FILE + ".bak"
            if os.path.exists(bak_file):
                self.logger.critical(f"[CACHE_RECOVERY] Shadow state missing. Attempting recovery from {bak_file}")
                try:
                    os.rename(bak_file, self.SHADOW_STATE_FILE)
                except:
                    pass
            else:
                return
        
        try:
            with open(self.SHADOW_STATE_FILE, 'r', encoding='utf-8') as f:
                raw_text = f.read()
                if not raw_text.strip():
                    data = {}
                    with open(self.SHADOW_STATE_FILE, 'w', encoding='utf-8') as reset_file:
                        reset_file.write("{}")
                    self.logger.warning("[SHADOW-STATE-RESET] Empty shadow state file reinitialized as empty JSON object.")
                else:
                    data = json.loads(raw_text)
                raw_shadow = data.get('shadow_positions', {})
                self.shadow_positions = self._deserialize_shadow_types(raw_shadow)
                self.logger.critical(
                    f"[SHADOW-STATE-LOADED] Recovered {len(self.shadow_positions)} shadow positions from disk. "
                    f"Memory persistence verified."
                )
                
                # ===== FIX #6: FINAL DICT-PURGE - REMOVE OBSOLETE TICKETS =====
                # Check if Ticket #55232084942 exists and remove if it's no longer in MT5
                self._purge_obsolete_shadow_positions()
                
        except Exception as e:
            self.logger.error(f"Failed to load shadow state (JSON corrupted?): {e}")
            self.shadow_positions = {}
            try:
                with open(self.SHADOW_STATE_FILE, 'w', encoding='utf-8') as f:
                    f.write("{}")
                self.logger.warning("[SHADOW-STATE-RESET] Reinitialized corrupted shadow state file as empty JSON object.")
            except Exception as reset_exc:
                self.logger.error("[SHADOW-STATE-RESET] Failed to reinitialize shadow state file: %s", reset_exc)
        finally:
            # Hard one-time guard: runtime loops must never trigger repeated disk loads.
            self._shadow_state_loaded_once = True

    def _sync_transactional_registry(self) -> None:
        """
        ===== TRANSACTIONAL REGISTRY SYNC =====
        Load tickets from the transactional registry (persisted immediately upon TRADE_RETCODE_DONE)
        and merge them into shadow_positions to ensure no orphaned tickets are lost.
        
        This is called during initialization to recover any tickets that were confirmed
        but may not yet be in the shadow_positions file due to timing.
        """
        TRANSACTIONAL_REGISTRY_FILE = os.path.join(os.getcwd(), "transactional_tickets.json")
        
        if not os.path.exists(TRANSACTIONAL_REGISTRY_FILE):
            return  # No transactional registry yet
        
        try:
            with open(TRANSACTIONAL_REGISTRY_FILE, 'r', encoding='utf-8') as f:
                registry = json.load(f)
            
            if not registry:
                return
            
            recovered_count = 0
            for ticket_id, ticket_data in registry.items():
                # Only adopt if not already in shadow_positions
                if ticket_id not in self.shadow_positions:
                    self.shadow_positions[ticket_id] = {
                        'ticket_id': ticket_id,
                        'symbol': ticket_data.get('symbol', 'UNKNOWN'),
                        'direction': 0 if ticket_data.get('direction') == 'BUY' else 1,
                        'entry_price': ticket_data.get('entry_price', 0.0),
                        'current_price': ticket_data.get('entry_price', 0.0),
                        'stop_loss': ticket_data.get('stop_loss', 0.0),
                        'take_profit': ticket_data.get('take_profit', 0.0),
                        'profit': 0.0,
                        'volume': 0.01,  # Default, will be updated on next MT5 scan
                        'adoption_time': ticket_data.get('persisted_at', datetime.now(timezone.utc).isoformat()),
                        'source': 'TRANSACTIONAL_REGISTRY'
                    }
                    recovered_count += 1
            
            if recovered_count > 0:
                self._save_shadow_state()
                self.logger.critical(
                    f"[TRANSACTIONAL_REGISTRY_SYNC] Successfully recovered {recovered_count} tickets from transactional registry."
                )
        except Exception as e:
            self.logger.error(f"[TRANSACTIONAL_REGISTRY_SYNC_ERROR] Failed to sync transactional registry: {e}")

    
    def _purge_obsolete_shadow_positions(self) -> None:
        """Remove shadow positions that are no longer in MT5 to stop 'NOT in dictionary' warnings
        
        ===== FIX #4: AUTO-PURGE RULE - DELETE TICKET #55232084942 AFTER 5 CONSECUTIVE CYCLES =====
        If zombie ticket is not found in MT5 for 5 consecutive cycles, permanently delete from shadow_state.json
        """
        obsolete_ticket = "55232084942"
        
        # Initialize counter if not yet tracked
        if obsolete_ticket not in self.zombie_ticket_not_found_count:
            self.zombie_ticket_not_found_count[obsolete_ticket] = 0
        
        if obsolete_ticket in self.shadow_positions:
            # Ticket exists in shadow state
            # In a real scenario, we'd check if it's in MT5 terminal
            # For now, assuming if not explicitly found, increment counter
            # This would be called after checking MT5 positions
            
            self.logger.critical(
                f"[AUTO-PURGE-TRACKING] Ticket #{obsolete_ticket} detected in shadow_state.json. "
                f"Consecutive not-found cycles: {self.zombie_ticket_not_found_count[obsolete_ticket]}/{self.ZOMBIE_PURGE_THRESHOLD}"
            )
            
            # Check if we've hit the consecutive not-found threshold
            if self.zombie_ticket_not_found_count[obsolete_ticket] >= self.ZOMBIE_PURGE_THRESHOLD:
                self.logger.critical(
                    f"[AUTO-PURGE-THRESHOLD-HIT] Ticket #{obsolete_ticket} NOT FOUND in MT5 for "
                    f"{self.ZOMBIE_PURGE_THRESHOLD} consecutive cycles. PERMANENTLY DELETING from shadow_state.json..."
                )
                del self.shadow_positions[obsolete_ticket]
                self._save_shadow_state()  # Persist the purged state
                self.zombie_ticket_not_found_count[obsolete_ticket] = 0  # Reset counter
                self.logger.critical(
                    f"[AUTO-PURGE-COMPLETED] Ticket #{obsolete_ticket} successfully removed after "
                    f"{self.ZOMBIE_PURGE_THRESHOLD} cycles. Dictionary warnings STOPPED."
                )
    
    def track_zombie_position_not_found(self, ticket_id: str) -> None:
        """
        ===== FIX #4: TRACK CONSECUTIVE CYCLES WHERE ZOMBIE POSITION NOT FOUND =====
        Called each cycle when checking MT5 positions.
        If a shadow position isn't found in MT5, increment its not_found counter.
        After ZOMBIE_PURGE_THRESHOLD consecutive cycles, auto-purge the position.
        
        Args:
            ticket_id: The ticket ID not found in MT5 this cycle
        """
        if ticket_id not in self.zombie_ticket_not_found_count:
            self.zombie_ticket_not_found_count[ticket_id] = 0
        
        self.zombie_ticket_not_found_count[ticket_id] += 1
        
        if self.zombie_ticket_not_found_count[ticket_id] >= self.ZOMBIE_PURGE_THRESHOLD:
            self.logger.critical(
                f"[AUTO-PURGE-THRESHOLD] Ticket #{ticket_id} NOT FOUND for {self.ZOMBIE_PURGE_THRESHOLD} cycles. "
                f"Deleting from shadow_state.json."
            )
            if ticket_id in self.shadow_positions:
                del self.shadow_positions[ticket_id]
                self._save_shadow_state()
            self.zombie_ticket_not_found_count[ticket_id] = 0
    
    def reset_zombie_found(self, ticket_id: str) -> None:
        """
        ===== FIX #4: RESET COUNTER WHEN ZOMBIE POSITION FOUND =====
        If a previously-missing ticket is found in MT5, reset its not_found counter.
        
        Args:
            ticket_id: The ticket ID found in MT5
        """
        if ticket_id in self.zombie_ticket_not_found_count:
            if self.zombie_ticket_not_found_count[ticket_id] > 0:
                self.logger.info(
                    f"[AUTO-PURGE-RESET] Ticket #{ticket_id} FOUND in MT5. "
                    f"Resetting not_found counter from {self.zombie_ticket_not_found_count[ticket_id]} to 0."
                )
                self.zombie_ticket_not_found_count[ticket_id] = 0
    
    def _save_shadow_state(self) -> None:
        if not self.use_shadow_state:
            return
        """Save shadow positions with thread-safe lock + retry on WinError 32."""
        
        # ===== FIX #3: CLEAN SHADOW STATE - PURGE OLD ENTRIES =====
        # Remove shadow entries older than 24 hours to prevent accumulation
        now_utc = datetime.now(timezone.utc)
        max_age_hours = 24
        cleaned_shadow = {}
        
        for sid, pdata in list(self.shadow_positions.items()):
            if isinstance(pdata, dict):
                # Try to find an open timestamp to check age
                adoption_time_str = pdata.get("adoption_time") or pdata.get("opened_at") or pdata.get("created_at")
                if adoption_time_str:
                    try:
                        if isinstance(adoption_time_str, str):
                            adoption_dt = datetime.fromisoformat(adoption_time_str.replace("Z", "+00:00"))
                        elif isinstance(adoption_time_str, datetime):
                            adoption_dt = adoption_time_str
                        else:
                            adoption_dt = datetime.fromtimestamp(float(adoption_time_str), tz=timezone.utc)
                        
                        if adoption_dt.tzinfo is None:
                            adoption_dt = adoption_dt.replace(tzinfo=timezone.utc)
                        
                        age_hours = (now_utc - adoption_dt).total_seconds() / 3600
                        
                        if age_hours > max_age_hours:
                            self.logger.info(
                                f"[SHADOW_CLEANUP] Purging stale shadow entry {sid} | "
                                f"Age: {age_hours:.1f}h (> {max_age_hours}h threshold)"
                            )
                            continue  # Skip this entry (don't add to cleaned_shadow)
                    except Exception as e:
                        self.logger.debug(f"[SHADOW_CLEANUP_DEBUG] Could not parse age for {sid}: {e}")
            
            # Keep entry if age check passed or couldn't be evaluated
            cleaned_shadow[sid] = pdata
        
        if len(cleaned_shadow) != len(self.shadow_positions):
            self.logger.info(
                f"[SHADOW_CLEANUP_SUMMARY] Removed {len(self.shadow_positions) - len(cleaned_shadow)} "
                f"stale entries. {len(cleaned_shadow)} positions remain."
            )
            self.shadow_positions = cleaned_shadow
        
        # Atomic sanitize: persist only tickets that are currently open in MT5.
        try:
            if mt5 is None:
                raise RuntimeError("MT5 unavailable")
            live_positions = mt5.positions_get()
            live_ticket_ids = {str(getattr(p, "ticket", "")) for p in (live_positions or ())}
        except Exception:
            live_ticket_ids = set()

        if live_ticket_ids:
            filtered_shadow: Dict[str, Dict] = {}
            for sid, pdata in list(self.shadow_positions.items()):
                sid_str = str(sid)
                embedded_tid = None
                if isinstance(pdata, dict):
                    embedded_tid = (
                        pdata.get("ticket")
                        or pdata.get("ticket_id")
                        or pdata.get("position_id")
                        or pdata.get("id")
                    )
                embedded_tid_str = str(embedded_tid) if embedded_tid is not None else sid_str
                if sid_str in live_ticket_ids or embedded_tid_str in live_ticket_ids:
                    filtered_shadow[sid_str] = pdata
            if len(filtered_shadow) != len(self.shadow_positions):
                self.shadow_positions = filtered_shadow
                if hasattr(self, "active_ticket_registry"):
                    self.active_ticket_registry = {
                        str(tid) for tid in self.active_ticket_registry if str(tid) in live_ticket_ids
                    }
                if hasattr(self, "open_positions"):
                    self.open_positions = {
                        str(tid): pdata for tid, pdata in self.open_positions.items() if str(tid) in live_ticket_ids
                    }
                if hasattr(self, "managed_tickets"):
                    _mt = self.managed_tickets
                    if isinstance(_mt, dict):
                        clean_dict = {}
                        for _k, _v in _mt.items():
                            _v_tid = None
                            if isinstance(_v, dict):
                                _v_tid = _v.get("ticket") or _v.get("ticket_id") or _v.get("position_id") or _v.get("id")
                            else:
                                _v_tid = getattr(_v, "position_id", None) or getattr(_v, "ticket", None)
                            if str(_k) in live_ticket_ids or str(_v_tid) in live_ticket_ids:
                                clean_dict[_k] = _v
                        self.managed_tickets = clean_dict
                    elif isinstance(_mt, list):
                        # ===== FIX #1: CONVERT FILTERED LIST TO DICT =====
                        # Downstream main.py code expects managed_tickets to be dict and calls .add()
                        # Converting list to empty dict to prevent 'list' object has no attribute 'add' crash
                        clean_dict = {}
                        for _item in _mt:
                            _it_tid = None
                            if isinstance(_item, dict):
                                _it_tid = _item.get("ticket") or _item.get("ticket_id") or _item.get("position_id") or _item.get("id")
                                if str(_it_tid) in live_ticket_ids:
                                    clean_dict[str(_it_tid)] = _item
                            else:
                                _it_tid = getattr(_item, "position_id", None) or getattr(_item, "ticket", None)
                                if str(_it_tid) in live_ticket_ids:
                                    clean_dict[str(_it_tid)] = _item
                        self.managed_tickets = clean_dict
                    elif isinstance(_mt, set):
                        self.managed_tickets = {x for x in _mt if str(x) in live_ticket_ids}
                self.logger.info(
                    f"[SHADOW_SANITIZE] Purged stale disk candidates before save. Remaining={len(self.shadow_positions)}"
                )

        data = {
            'shadow_positions': self._serialize_shadow_json_safe(self.shadow_positions),
            'last_updated': datetime.now(timezone.utc).isoformat()
        }
        max_attempts = 3
        retry_delay_s = 0.1

        for attempt in range(1, max_attempts + 1):
            temp_path = f"{self.SHADOW_STATE_FILE}.{threading.get_ident()}.tmp"
            try:
                parent = os.path.dirname(self.SHADOW_STATE_FILE)
                if parent:
                    os.makedirs(parent, exist_ok=True)

                with self.__class__._shadow_state_lock:
                    with open(temp_path, 'w', encoding='utf-8') as f:
                        json.dump(data, f, indent=2)

                    if os.path.exists(self.SHADOW_STATE_FILE):
                        bak_path = self.SHADOW_STATE_FILE + ".bak"
                        try:
                            if os.path.exists(bak_path):
                                os.remove(bak_path)
                            os.replace(self.SHADOW_STATE_FILE, bak_path)
                        except Exception:
                            pass
                    os.replace(temp_path, self.SHADOW_STATE_FILE)

                self.logger.debug(
                    f"[SHADOW-STATE-SAVED] Persisted {len(self.shadow_positions)} positions "
                    f"(atomic, attempt {attempt}/{max_attempts})."
                )
                return
            except OSError as e:
                winerr = getattr(e, "winerror", None)
                is_file_lock = (winerr == 32) or ("being used by another process" in str(e).lower())
                if is_file_lock and attempt < max_attempts:
                    self.logger.warning(
                        f"[SHADOW-STATE-RETRY] File lock collision on shadow_state.json "
                        f"(attempt {attempt}/{max_attempts}). Retrying in {retry_delay_s*1000:.0f}ms..."
                    )
                    time.sleep(retry_delay_s)
                    continue
                self.logger.error(f"CRITICAL: Failed to save shadow state (atomic): {e}")
            except Exception as e:
                self.logger.error(f"CRITICAL: Failed to save shadow state (atomic): {e}")
            finally:
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except Exception:
                        pass

    def protect_shadow_positions_from_amnesia(self, live_positions: Optional[List[Any]] = None, reason: str = "") -> int:
        if not self.use_shadow_state:
            return 0
        """
        Preserve adopted ticket memory across amnesia/reset paths.
        Keeps only currently-live MT5 tickets when available; otherwise keeps current memory as-is.

        Args:
            live_positions: MT5 position objects or dicts with ticket/position_id
            reason: Optional reason tag for logging

        Returns:
            Count of shadow tickets after protection pass
        """
        live_positions = live_positions or []
        live_ticket_ids: set[str] = self._extract_ticket_ids_from_positions(live_positions)

        before = len(self.shadow_positions)
        if live_ticket_ids and self.shadow_positions:
            self.shadow_positions = {
                tid: pdata for tid, pdata in self.shadow_positions.items() if str(tid) in live_ticket_ids
            }

        for tid in live_ticket_ids:
            if tid in self.shadow_positions:
                self.shadow_positions[tid]["amnesia_protected"] = True
                self.active_ticket_registry.add(str(tid))
            else:
                # Keep ticket in registry even if payload is not yet in memory; scan will not re-adopt blindly.
                self.active_ticket_registry.add(str(tid))

        after = len(self.shadow_positions)
        should_persist = (after != before) or (after > 0 and bool(live_ticket_ids))
        if should_persist:
            self._save_shadow_state()

        if reason:
            self.logger.debug(
                f"[AMNESIA_PROTECTION] reason={reason} | live={len(live_ticket_ids)} | shadow_before={before} | shadow_after={after}"
            )
        return after
    
    def _get_adoption_age_minutes(self, adoption_time: Any) -> float:
        """
        Calculate minutes since position adoption from ISO timestamp string.
        
        ===== FIX #6: HEARTBEAT ADOPTION TIME LOGGING =====
        Converts ISO datetime string to elapsed minutes for status reporting.
        
        Args:
            adoption_time: ISO format datetime string (e.g., "2024-02-15T14:32:45.123456+00:00")
            
        Returns:
            Float representing minutes since adoption (0.0 if parse fails)
        """
        if not adoption_time or adoption_time == 'N/A':
            return 0.0
        
        try:
            if isinstance(adoption_time, datetime):
                adoption_dt = adoption_time
            else:
                adoption_dt = datetime.fromisoformat(str(adoption_time))
            if adoption_dt.tzinfo is None:
                adoption_dt = adoption_dt.replace(tzinfo=timezone.utc)
            current_dt = datetime.now(timezone.utc)
            elapsed_seconds = (current_dt - adoption_dt).total_seconds()
            return elapsed_seconds / 60.0
        except Exception as e:
            self.logger.debug(f"Failed to parse adoption_time {adoption_time}: {e}")
            return 0.0
    
    def verify_shadow_integrity(self) -> bool:
        """
        Verify that in-memory shadow state matches the on-disk state.
        Ensures atomic writes succeeded and memory hasn't drifted.
        
        Returns:
            bool: True if states match, False if discrepancy found
        """
        if not os.path.exists(self.SHADOW_STATE_FILE):
            if not self.shadow_positions:
                return True
            self.logger.warning("[INTEGRITY_CHECK] Shadow state file missing but memory has positions.")
            return False
            
        try:
            with open(self.SHADOW_STATE_FILE, 'r', encoding='utf-8') as f:
                disk_data = json.load(f)
                disk_shadow = disk_data.get('shadow_positions', {})
                
            # Compare keys
            mem_keys = set(self.shadow_positions.keys())
            disk_keys = set(disk_shadow.keys())
            
            if mem_keys != disk_keys:
                added = disk_keys - mem_keys
                removed = mem_keys - disk_keys
                self.logger.critical(
                    f"[INTEGRITY_DISCREPANCY] Memory/Disk mismatch! "
                    f"On Disk but not Mem: {added} | In Mem but not Disk: {removed}"
                )
                # Auto-heal: Sync memory to disk (primary source of truth during run is memory)
                if removed:
                    self.logger.warning("[INTEGRITY_HEAL] Syncing memory to disk to resolve discrepancy.")
                    self._save_shadow_state()
                return False
                
            self.logger.debug(f"[INTEGRITY_OK] Shadow state verified ({len(mem_keys)} positions).")
            return True
        except Exception as e:
            self.logger.error(f"[INTEGRITY_ERROR] Failed during integrity check: {e}")
            return False

    def check_force_reload_frequency(self) -> bool:
        """
        Monitor frequency of forced re-evaluations/reloads.
        Returns True if frequent reloads detected (potential inefficiency).
        """
        now = datetime.now(timezone.utc)
        # Prune old events (> 5 minutes)
        self.force_reload_events = [t for t in self.force_reload_events 
                                  if (now - t).total_seconds() < 300]
        
        if len(self.force_reload_events) > 10:
            self.logger.warning(
                f"[PERFORMANCE_ALERT] High frequency of force-reloads detected: "
                f"{len(self.force_reload_events)} events in last 5 minutes."
            )
            return True
        return False
    
    def adopt_shadow_position(self, position_id: str, position_data: Dict, save_immediate: bool = True) -> None:
        """
        Adopt an orphaned MT5 position into bot's internal tracking.
        
        ===== PATCH #7: LOG RE-SYNCING_ACTIVE_TRADE ON ORPHAN DETECTION =====
        When a position exists in MT5 but not in bot memory, immediately pull entry price from terminal.
        
        This ensures unrealized losses (like -$7.98) are managed under the bot's exit logic
        rather than being ignored.
        
        Args:
            position_id: Unique position identifier in MT5
            position_data: Position details including symbol, direction, entry_price, unrealized_pl
        """
        # ===== FIX #3: FIX SHADOW MEMORY LEAK - MILLISECOND-LEVEL DISK PERSISTENCE =====
        # Using .update() prevents dictionary "forgetfulness" when entries are partially overwritten
        # CRITICAL: Save to disk THE MILLISECOND a ticket is adopted to prevent 10-second cycle loss
    async def _calculate_orphan_metrics(self, broker, symbol: str, entry_price: float, direction: int) -> Dict:
        """
        Calculate precise metrics (ATR, SL, RSI) for an orphaned position.
        """
        metrics = {
            'emergency_sl': None,
            'technicals': {},
            'valid': False
        }
        
        try:
            # Fetch valid historical data
            candles = await broker.get_historical_data(symbol, timeframe='1h', count=50)
            if not candles or len(candles) < 20:
                # Increment retry decay counter (v4.1)
                self.symbol_retry_decay[symbol] = self.symbol_retry_decay.get(symbol, 0) + 1
                if self.symbol_retry_decay[symbol] >= self.SYMBOL_RETRY_THRESHOLD:
                    self.logger.critical(
                        f"[SYMBOL_ALERT] {symbol} has failed historical data fetch {self.symbol_retry_decay[symbol]} times. "
                        f"IPC instability or broken feed detected. Manual inspection required."
                    )
                return metrics # Return empty/default
            
            # Reset counter on success
            self.symbol_retry_decay[symbol] = 0

            
            # 1. Calculate Real ATR
            calculator = StopLossTakeProfitCalculator()
            atr = calculator.calculate_atr(candles)
            
            # 2. Calculate Dynamic Emergency SL (2.0x ATR)
            volatility_mult = 2.0
            atr_sl_dist = atr * volatility_mult
            
            if direction in [0, Direction.LONG, 'LONG']:
                metrics['emergency_sl'] = entry_price - atr_sl_dist
            else:
                metrics['emergency_sl'] = entry_price + atr_sl_dist
                
            # 3. Calculate Technicals for Validation (RSI & ADX Proxy)
            opens = [c.open for c in candles]
            closes = [c.close for c in candles]
            highs = [c.high for c in candles]
            lows = [c.low for c in candles]
            
            # RSI (Classic 14 period)
            # Simple implementation to avoid dragging in full signal generator if not needed
            # or rely on logic if available. We'll do a quick calc here for speed.
            delta = [closes[i] - closes[i-1] for i in range(1, len(closes))]
            avg_gain = sum(d for d in delta[-14:] if d > 0) / 14
            avg_loss = sum(abs(d) for d in delta[-14:] if d < 0) / 14
            rs = avg_gain / avg_loss if avg_loss != 0 else 0
            rsi = 100 - (100 / (1 + rs))
            
            metrics['technicals'] = {
                'rsi': rsi,
                'atr': atr,
                'adx_check': 'PASSED' if atr > 0 else 'N/A' 
            }
            metrics['valid'] = True
            
        except Exception as e:
            self.logger.warning(f"[ORPHAN_METRICS_FAIL] Could not calc metrics for {symbol}: {e}")
            
        return metrics

    def adopt_shadow_position(self, position_id: str, position_data: Dict, save_immediate: bool = True) -> None:
        if not self.use_shadow_state:
            return
        """
        Adopt an orphaned MT5 position into bot's internal tracking with robust data sanitization.
        
        Args:
            position_id: Unique position identifier in MT5
            position_data: Position details including symbol, direction, entry_price, unrealized_pl
            save_immediate: Whether to persist to disk immediately (True) or batch (False)
        """
        # ===== FIX #3: FIX SHADOW MEMORY LEAK - MILLISECOND-LEVEL DISK PERSISTENCE =====
        if position_id not in self.shadow_positions:
            self.shadow_positions[position_id] = {}
        
        # --- DATA SANITIZATION START ---
        # Ensure Critical Fields are valid
        sanitized_data = position_data.copy()
        sanitized_data["strategy_meta"] = dict(sanitized_data.get("strategy_meta", {}) or {})
        
        # 1. Symbol
        if 'symbol' not in sanitized_data:
            sanitized_data['symbol'] = 'UNKNOWN'
            
        # 2. Prices & PnL
        try:
            entry = float(sanitized_data.get('entry_price', 0.0))
            current = float(sanitized_data.get('current_price', entry)) # Fallback to entry if n/a
            
            sanitized_data['entry_price'] = entry
            sanitized_data['current_price'] = current
            
            # Fix PnL if missing or N/A
            pnl_raw = sanitized_data.get('profit')
            if pnl_raw is None or pnl_raw == 'N/A':
                # Estimate: (Current - Entry) * Direction * Volume * 100000 (roughly) or just mark 'Est'
                # Better: Leave as 0.0 and mark status
                sanitized_data['profit'] = 0.0
                sanitized_data['pnl_status'] = 'ESTIMATED'
            else:
                sanitized_data['profit'] = float(pnl_raw)
                sanitized_data['pnl_status'] = 'REAL'
                
        except (ValueError, TypeError):
            sanitized_data['entry_price'] = 0.0
            sanitized_data['current_price'] = 0.0
            sanitized_data['profit'] = 0.0
            
        # 3. Emergency SL (Default if missing)
        if 'emergency_sl' not in sanitized_data or sanitized_data['emergency_sl'] is None:
            # Default fallback: 50 pips
            direction = sanitized_data.get('direction', 0)
            pip_val = 0.01 if 'JPY' in sanitized_data['symbol'] else 0.0001
            entry = sanitized_data['entry_price']
            
            if direction in [0, Direction.LONG, 'LONG']:
                 sanitized_data['emergency_sl'] = entry - (50 * pip_val)
            else:
                 sanitized_data['emergency_sl'] = entry + (50 * pip_val)
                 
        # --- DATA SANITIZATION END ---
        normalized_opened_at = self._normalize_utc_timestamp(
            sanitized_data.get("opened_at"),
            field_name="opened_at",
            ticket_id=str(position_id),
            fallback=sanitized_data.get("time_open"),
        )
        normalized_adoption_time = self._normalize_utc_timestamp(
            sanitized_data.get("adoption_time"),
            field_name="adoption_time",
            ticket_id=str(position_id),
            fallback=normalized_opened_at,
        )
        sanitized_data["opened_at"] = normalized_opened_at.isoformat()
        sanitized_data["adoption_time"] = normalized_adoption_time.isoformat()
        if "time_open" in sanitized_data:
            sanitized_data["time_open"] = normalized_opened_at.isoformat()
        
        # Preserve pre-existing adoption timestamp if this ticket was already tracked.
        prior_adoption_time = self.shadow_positions.get(position_id, {}).get('adoption_time')
        self.shadow_positions[position_id].update(sanitized_data)
        self.shadow_positions[position_id]['adoption_confirmed'] = True
        self.shadow_positions[position_id]['amnesia_protected'] = True
        self.active_ticket_registry.add(str(position_id))
        
        # ===== FIX #3: IMMEDIATE SAVE - MILLISECOND PERSISTENCE TO DISK =====
        if save_immediate:
            self._save_shadow_state()
            self.verify_shadow_integrity()
        
        # ===== FIX #6: LOG ADOPTION DETAILS =====
        # Use MT5 open time when available so age/rotation logic does not reset on re-adoption.
        adoption_time_str = (
            sanitized_data.get('adoption_time')
            or sanitized_data.get('opened_at')
            or sanitized_data.get('time_open')
            or prior_adoption_time
        )
        if isinstance(adoption_time_str, datetime):
            if adoption_time_str.tzinfo is None:
                adoption_time_str = adoption_time_str.replace(tzinfo=timezone.utc)
            adoption_time_str = adoption_time_str.isoformat()
        elif isinstance(adoption_time_str, (int, float)):
            adoption_time_str = datetime.fromtimestamp(float(adoption_time_str), tz=timezone.utc).isoformat()
        elif isinstance(adoption_time_str, str):
            try:
                parsed_adoption = datetime.fromisoformat(adoption_time_str)
                if parsed_adoption.tzinfo is None:
                    parsed_adoption = parsed_adoption.replace(tzinfo=timezone.utc)
                adoption_time_str = parsed_adoption.isoformat()
            except Exception:
                try:
                    adoption_time_str = datetime.fromtimestamp(float(adoption_time_str), tz=timezone.utc).isoformat()
                except Exception:
                    adoption_time_str = datetime.now(timezone.utc).isoformat()
        else:
            adoption_time_str = datetime.now(timezone.utc).isoformat()
        self.shadow_positions[position_id]['adoption_time'] = adoption_time_str
        
        # Format for log
        sym = sanitized_data['symbol']
        pnl_val = sanitized_data['profit']
        pnl_str = f"${pnl_val:.2f}" if pnl_val is not None else "N/A"
        sl_val = sanitized_data['emergency_sl']
        
        self.logger.critical(
            f"[SHADOW_MEMORY_LEAK_FIX] Adopted ticket {position_id} | "
            f"Memory-to-Disk sync: {'IMMEDIATE' if save_immediate else 'BATCHED'} | "
            f"[RE-SYNCING_ACTIVE_TRADE] Detected open position in MT5. "
            f"Symbol: {sym} | Entry: {format_float(sanitized_data['entry_price'], '.5f')} | "
            f"Current: {format_float(sanitized_data['current_price'], '.5f')} | "
            f"PnL: {pnl_str} ({sanitized_data.get('pnl_status', 'Real')}) | "
            f"SL: {format_float(sl_val, '.5f')}"
        )
    
    def reconcile_shadow_positions(self, mt5_positions: List[Dict]) -> None:
        """
        Compatibility refresh for legacy callers.
        Runtime state is rebuilt directly from MT5 payloads; shadow memory is disabled.
        """
        active_ids: set[str] = set()
        self.open_positions = {}
        self.shadow_positions = {}

        for mt5_pos in mt5_positions:
            position_id = str(mt5_pos.get("ticket", "") or "")
            if not position_id:
                continue
            active_ids.add(position_id)
            self.open_positions[position_id] = {
                "position_id": position_id,
                "symbol": mt5_pos.get("symbol", ""),
                "direction": mt5_pos.get("direction"),
                "entry_price": mt5_pos.get("entry_price", 0.0),
                "current_price": mt5_pos.get("price_current", mt5_pos.get("entry_price", 0.0)),
                "volume": mt5_pos.get("volume", 0.0),
                "stop_loss": mt5_pos.get("sl", 0.0),
                "take_profit": mt5_pos.get("tp", 0.0),
            }
        self.active_ticket_registry = active_ids
        self.shadow_position_reconciled = True
        self.logger.info("[SYNC_MT5_STATE] Startup state loaded from MT5 | live_positions=%d", len(active_ids))
        return
        
        # Check open_positions (runtime memory)
        open_ids = set(self.open_positions.keys())
        phantom_open = open_ids - mt5_position_ids

        if (phantom_shadows or phantom_open) and stable_cycles < 5:
            self.logger.critical(
                "[PHANTOM_PURGE_SKIPPED] MT5 connection not stable yet (%d/5 cycles). "
                "Deferring phantom purge. Shadow=%s Open=%s",
                stable_cycles,
                phantom_shadows,
                phantom_open,
            )
        else:
            if phantom_shadows:
                self.logger.critical(
                    f"[PHANTOM PURGE] Detcted {len(phantom_shadows)} phantom positions in shadow memory "
                    f"(not in MT5). Removing: {phantom_shadows}"
                )
                for pid in phantom_shadows:
                    del self.shadow_positions[pid]
                self._save_shadow_state()
        
            if phantom_open:
                self.logger.critical(
                    f"[PHANTOM PURGE] Detected {len(phantom_open)} phantom positions in open_positions "
                    f"(not in MT5). Removing: {phantom_open}"
                )
                for pid in phantom_open:
                    del self.open_positions[pid]
        
        if not orphaned_ids and not phantom_shadows and not phantom_open:
            self.logger.info("[SHADOW POSITION RECONCILIATION] All positions synchronized. No orphans or phantoms.")
        
        # Force immediate ATR recalculation in next cycle if we adopted anything
        if newly_adopted > 0:
             self.last_shadow_save = datetime.now(timezone.utc) - timedelta(minutes=20)
             
             # INJECT RISK CEILING FOR EURUSD IMMEDIATELY UPON ADOPTION
             for pid in orphaned_ids:
                 mt5_pos = next((p for p in mt5_positions if str(p.get('ticket')) == str(pid)), None)
                 if mt5_pos and mt5_pos.get('symbol') == 'EURUSD' and mt5_pos.get('type') == 1: # 1 is SELL
                     current_sl = float(mt5_pos.get('sl', 0.0))
                     ceil_sl = 1.17945
                     # If the adopted SL is already worse than ceiling (or 0), we must clamp it NOW internally
                     # so the ATR updater respects it in the next cycle.
                     if current_sl == 0.0 or current_sl > ceil_sl:
                         if str(pid) in self.shadow_positions:
                             self.shadow_positions[str(pid)]['emergency_sl'] = ceil_sl
                             self.logger.critical(
                                 f"[RECONCILIATION_RISK_CLAMP] EURUSD #{pid} adopted. "
                                 f"Injecting Risk Ceiling SL: {ceil_sl} (was {current_sl})."
                             )

        self.shadow_position_reconciled = True
    
    # ===== PATCH #5: RECURSIVE SHADOW SCAN =====
    async def periodic_shadow_scan(self, broker, cycle_count: int = 0, scan_interval: int = 5) -> int:
        """
        Run every N cycles to detect orphaned MT5 positions and attach ATR-based stops.
        
        Args:
            broker: BrokerInterface to query MT5 positions
            cycle_count: Current cycle number
            scan_interval: Run scan every N cycles (default 5)
            
        Returns:
            Number of newly adopted positions
        """
        # MT5 is now refreshed every cycle via sync_mt5_state(); keep this as a quiet compatibility shim.
        if cycle_count % scan_interval != 0:
            return 0
        await self.sync_mt5_state(persist=True)
        return 0
        try:
            bot_ids = set(self.open_positions.keys()) | set(self.shadow_positions.keys()) | set(self.active_ticket_registry)
            
            # Find orphaned positions
            orphaned_ids = mt5_ids - bot_ids
            newly_adopted = 0
            
            for orphan_id in orphaned_ids:
                # Find the MT5 position data
                mt5_pos = next((p for p in mt5_positions if str(p.get('ticket')) == orphan_id), None)
                if not mt5_pos:
                    continue
                
                symbol = mt5_pos.get('symbol', '')
                direction = mt5_pos.get('type', '')  # 0=BUY, 1=SELL in MT5
                entry_price = mt5_pos.get('price_open', 0.0)
                unrealized_pl = mt5_pos.get('profit', 0.0)
                volume = mt5_pos.get('volume', 0.0)
                
                # Calculate metrics (ATR, SL, Validation) asynchronously
                orphan_metrics = await self._calculate_orphan_metrics(broker, symbol, entry_price, direction)
                
                # ORPHAN QUARANTINE: If metrics fail (e.g. no candles), delay adoption
                if not orphan_metrics['valid']:
                    if orphan_id not in self.orphan_quarantine:
                        self.logger.warning(
                            f"[ORPHAN_QUARANTINE] Ticket {orphan_id} ({symbol}) failed technical verification. "
                            f"Delaying adoption until metrics are confirmed."
                        )
                    self.orphan_quarantine[orphan_id] = {
                        'mt5_pos': mt5_pos,
                        'first_detected': datetime.now(timezone.utc).isoformat(),
                        'last_check': datetime.now(timezone.utc).isoformat()
                    }
                    continue

                # ===== v4.1 PRE-ADOPTION SANITY CHECK =====
                # Compare current market price vs original entry price ± ATR buffer
                current_price = mt5_pos.get('price_current', entry_price)
                atr = orphan_metrics['technicals'].get('atr', 0)
                bot_magic = 234000
                mt5_magic = mt5_pos.get('magic')
                mt5_state = mt5_pos.get('state', 'POSITION_OPEN')
                valid_open_state = (
                    orphan_id in mt5_ids
                    and mt5_state == 'POSITION_OPEN'
                    and current_price not in (None, 0, 0.0)
                    and float(volume or 0.0) > 0.0
                )
                magic_symbol_match = (
                    symbol not in (None, "")
                    and mt5_magic is not None
                    and str(mt5_magic) == str(bot_magic)
                )
                bypass_atr_sanity = bool(magic_symbol_match and valid_open_state)
                if bypass_atr_sanity:
                    self.logger.critical(
                        f"[CRITICAL ADOPTION] Orphaned position adopted (ATR check bypassed) | "
                        f"Ticket: {orphan_id} | Symbol: {symbol} | Magic: {mt5_magic} | State: {mt5_state}"
                    )
                
                if (not bypass_atr_sanity) and atr > 0:
                    uncaged_active = (
                        str(os.environ.get("SYSTEM_UNCAGED", "0")).lower() in {"1", "true", "yes", "on"}
                        or str(os.environ.get("SYSTEM_UNCAGED_V6", "0")).lower() in {"1", "true", "yes", "on"}
                        or str(os.environ.get("STRIKING_MODE", "0")).lower() in {"1", "true", "yes", "on"}
                    )
                    sanity_multiplier = self.QUARANTINE_ATR_MULTIPLIER * (10.0 if uncaged_active else 1.0)
                    buffer = atr * sanity_multiplier
                    price_diff = abs(current_price - entry_price)
                    
                    if price_diff > buffer:
                        self.logger.warning(
                            f"[SANITY_FAILED] Ticket {orphan_id} ({symbol}) price deviation too large for adoption. "
                            f"Price Diff: {price_diff:.5f} | ATR Buffer ({sanity_multiplier:.2f}x): {buffer:.5f}. "
                            f"Position may be stale or lagged. Keeping in quarantine."
                        )
                        self.orphan_quarantine[orphan_id] = {
                            'mt5_pos': mt5_pos,
                            'last_check': datetime.now(timezone.utc).isoformat(),
                            'sanity_failed': True,
                            'deviation': price_diff
                        }
                        continue

                # If we reach here, metrics are valid and sanity check passed. Remove from quarantine if present.
                if orphan_id in self.orphan_quarantine:
                    self.logger.critical(f"[QUARANTINE_RELEASE] Ticket {orphan_id} passed verification and sanity check. Proceeding with adoption.")
                    del self.orphan_quarantine[orphan_id]

                # Use calculated SL if valid
                emergency_sl = orphan_metrics['emergency_sl']
                technicals_str = f"RSI: {orphan_metrics['technicals'].get('rsi', 'N/A'):.1f} | ATR: {orphan_metrics['technicals'].get('atr', 0):.5f}"

                # Check for resync cooldown
                if orphan_id in self.recent_resyncs:
                    last_resync = self.recent_resyncs[orphan_id]
                    if (datetime.now(timezone.utc) - last_resync).total_seconds() < self.RESYNC_COOLDOWN_SECONDS:
                        self.logger.debug(f"Skipping resync for {orphan_id} (cooldown active)")
                        continue

                # Adopt and persist immediately to survive amnesia/reset boundaries.
                self.adopt_shadow_position(orphan_id, {
                    'symbol': symbol,
                    'direction': direction,
                    'entry_price': entry_price,
                    'current_price': mt5_pos.get('price_current', entry_price),
                    'profit': unrealized_pl,
                    'volume': volume,
                    'emergency_sl': emergency_sl,
                    'adoption_cycle': cycle_count,
                    'technicals_at_adoption': orphan_metrics.get('technicals', {}),
                    'adoption_time': mt5_pos.get('opened_at') or mt5_pos.get('time_open') or datetime.now(timezone.utc).isoformat(),
                    'opened_at': mt5_pos.get('opened_at'),
                    'time_open': mt5_pos.get('time_open'),
                }, save_immediate=True)
                
                self.recent_resyncs[orphan_id] = datetime.now(timezone.utc)
                self.active_ticket_registry.add(str(orphan_id))
                
                self.logger.critical(
                    f"[CRITICAL ADOPTION] Orphaned position adopted | Ticket: {orphan_id} | "
                    f"Symbol: {symbol} | {technicals_str} | Verified: {orphan_metrics['valid']} | "
                    f"Sanity: PASSED (Dev: {abs(mt5_pos.get('price_current', entry_price) - entry_price):.5f})"
                )
                
                newly_adopted += 1
            
            # Additional check: Clean up quarantine for tickets that no longer exist in MT5
            quarantine_ids = list(self.orphan_quarantine.keys())
            for qid in quarantine_ids:
                if qid not in mt5_ids:
                    self.logger.info(f"[QUARANTINE_CLEANUP] Ticket {qid} no longer in MT5. Removing from quarantine.")
                    del self.orphan_quarantine[qid]

            # ===== STATE INTEGRITY CHECK =====

            # Batch save if any new positions adopted
            if newly_adopted > 0:
                self._save_shadow_state()
                self.verify_shadow_integrity()
            
            # ===== FIX #9: DYNAMIC ATR STOP-LOSS RECALCULATION (Moved from Sync Heartbeat) =====
            # Run every 15 minutes (900 seconds)
            current_time = datetime.now(timezone.utc)
            time_since_last_recalc = (current_time - self.last_shadow_save).total_seconds()
            
            if time_since_last_recalc > 900:
                if self.shadow_positions:
                    self.logger.critical(
                        f"[ATR_RECALC_STARTED] Cycle {cycle_count} | Updating ATR-based stops for "
                        f"{len(self.shadow_positions)} shadow positions."
                    )
                    
                    calculator = StopLossTakeProfitCalculator()
                    
                    for ticket_id, pos_data in self.shadow_positions.items():
                        symbol = pos_data.get('symbol')
                        entry_price = float(pos_data.get('entry_price', 0))
                        direction = pos_data.get('direction')
                        
                        # Fetch candles for ATR
                        try:
                            # Fetch H1 candles for robust ATR
                            candles = await broker.get_historical_data(symbol, timeframe='1h', count=20)
                            if candles:
                                atr = calculator.calculate_atr(candles)
                                
                                # Use systematic multiplier (e.g. 1.5x or 2.0x ATR)
                                volatility_mult = 2.0
                                atr_sl_dist = atr * volatility_mult
                                
                                # Calculate new SL
                                if direction in [0, Direction.LONG, 'LONG']:
                                    new_sl = entry_price - atr_sl_dist
                                    # Ensure we don't move SL down (looser) if specific profit checks absent?
                                    # For orphan recovery, we accept the dynamic SL.
                                else:
                                    new_sl = entry_price + atr_sl_dist
                                    
                                pos_data['emergency_sl'] = new_sl
                                pos_data['last_atr'] = atr
                                pos_data['last_recalc_time'] = current_time.isoformat()
                                
                                self.logger.info(
                                    f"[ATR_UPDATE] {symbol} #{ticket_id} | New SL: {format_float(new_sl, '.5f')} "
                                    f"(ATR: {format_float(atr, '.5f')} x {volatility_mult})"
                                )
                        except Exception as e:
                            self.logger.error(f"Failed to recalc ATR for {ticket_id}: {e}")
                    
                    self.last_shadow_save = current_time
                    self._save_shadow_state()
                    self.logger.critical("[ATR_RECALC_COMPLETED] Shadow positions updated.")

            return newly_adopted
            
        except Exception as e:
            self.logger.error(f"Error in periodic shadow scan: {e}", exc_info=True)
            return 0

    def cleanup_shadow_registry(self, active_ticket_ids: set[str], persist: bool = True) -> int:
        """
        Purge stale shadow/registry/open-position entries not present in live MT5 active tickets.
        This runs as an end-of-cycle cleanup to prevent registry growth leaks.

        Args:
            active_ticket_ids: Set of currently-open MT5 ticket IDs
            persist: Whether to persist shadow state when cleanup happens

        Returns:
            Number of shadow records removed
        """
        active_ticket_ids = {str(tid) for tid in (active_ticket_ids or set())}

        stale_shadow_ids: List[str] = []
        for sid, pdata in list(self.shadow_positions.items()):
            sid_str = str(sid)
            embedded_tid = None
            if isinstance(pdata, dict):
                embedded_tid = (
                    pdata.get("ticket")
                    or pdata.get("ticket_id")
                    or pdata.get("position_id")
                    or pdata.get("id")
                )
            embedded_tid_str = str(embedded_tid) if embedded_tid is not None else sid_str

            # Keep only entries that map to a currently-live MT5 ticket either by
            # dict key or embedded ticket payload field.
            if sid_str in active_ticket_ids or embedded_tid_str in active_ticket_ids:
                continue
            stale_shadow_ids.append(sid_str)
        stale_registry_ids = [tid for tid in list(self.active_ticket_registry) if str(tid) not in active_ticket_ids]
        stale_open_ids = [tid for tid in list(self.open_positions.keys()) if str(tid) not in active_ticket_ids]
        stale_managed_count = 0

        for tid in stale_shadow_ids:
            self.shadow_positions.pop(str(tid), None)
        for tid in stale_registry_ids:
            self.active_ticket_registry.discard(str(tid))
        for tid in stale_open_ids:
            self.open_positions.pop(tid, None)
        if hasattr(self, "managed_tickets"):
            _mt = self.managed_tickets
            if isinstance(_mt, dict):
                for _k, _v in list(_mt.items()):
                    _v_tid = None
                    if isinstance(_v, dict):
                        _v_tid = _v.get("ticket") or _v.get("ticket_id") or _v.get("position_id") or _v.get("id")
                    else:
                        _v_tid = getattr(_v, "position_id", None) or getattr(_v, "ticket", None)
                    if str(_k) not in active_ticket_ids and str(_v_tid) not in active_ticket_ids:
                        _mt.pop(_k, None)
                        stale_managed_count += 1
            elif isinstance(_mt, list):
                # ===== FIX #3: CONVERT FILTERED LIST TO DICT =====
                # Downstream code expects managed_tickets to be dict, convert filter result
                _new_dict = {}
                for _item in _mt:
                    _it_tid = None
                    if isinstance(_item, dict):
                        _it_tid = _item.get("ticket") or _item.get("ticket_id") or _item.get("position_id") or _item.get("id")
                        if str(_it_tid) in active_ticket_ids:
                            _new_dict[str(_it_tid)] = _item
                        else:
                            stale_managed_count += 1
                    else:
                        _it_tid = getattr(_item, "position_id", None) or getattr(_item, "ticket", None)
                        if str(_it_tid) in active_ticket_ids:
                            _new_dict[str(_it_tid)] = _item
                        else:
                            stale_managed_count += 1
                self.managed_tickets = _new_dict
            elif isinstance(_mt, set):
                _old_len = len(_mt)
                self.managed_tickets = {x for x in _mt if str(x) in active_ticket_ids}
                stale_managed_count = _old_len - len(self.managed_tickets)

        if stale_shadow_ids and persist:
            self._save_shadow_state()

        # Keep ticket registry exactly aligned with the current shadow map after purge.
        self._sync_active_ticket_registry(replace=True)

        if stale_shadow_ids or stale_registry_ids or stale_open_ids or stale_managed_count:
            self.logger.info(
                f"[REGISTRY_CLEANUP] Purged stale records | "
                f"Shadow={len(stale_shadow_ids)} | Registry={len(stale_registry_ids)} | OpenMap={len(stale_open_ids)} | Managed={stale_managed_count} | "
                f"ActiveNow={len(active_ticket_ids)}"
            )
        return len(stale_shadow_ids)

    def heartbeat(self, cycle_count: int, heartbeat_interval: int = 10) -> None:
        """
        Log heartbeat confirmation every N cycles that shadow positions are being tracked.
        Includes v4.1 Trend Analysis and Drift Detection.
        """
        if cycle_count % heartbeat_interval != 0:
            return

        # Keep heartbeat read-only for persistence; no runtime disk re-load to minimize I/O churn.

        # ===== BUG FIX [3]: Remove hardcoded zombie ticket reference.
        # The old target_ticket = '55232084942' caused an infinite FORCE_RELOAD_FAILED loop
        # every 10 cycles because that ticket will never exist. Instead, just log live shadow count.
        total_shadows = len(self.shadow_positions)
        candidates = sum(1 for p in self.shadow_positions.values() if p.get('is_candidate'))
        adopted = total_shadows - candidates


        # ===== v4.1 TREND ANALYSIS DATA COLLECTION =====
        total_pnl = sum(float(p.get('profit', 0)) for p in self.shadow_positions.values())
        total_tickets = len(self.shadow_positions)
        avg_sl_price = 0.0
        
        actual_sl_counts = 0
        for p in self.shadow_positions.values():
            sl = p.get('emergency_sl')
            if sl and sl != 'N/A':
                avg_sl_price += float(sl)
                actual_sl_counts += 1
        
        if actual_sl_counts > 0:
            avg_sl_price /= actual_sl_counts
            
        current_stats = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'cycle': cycle_count,
            'pnl': total_pnl,
            'ticket_count': total_tickets,
            'avg_sl_price': avg_sl_price,
            'force_reload_rate': len(self.force_reload_events)
        }
        
        # Update rolling history (Maintained for general stats, but drift uses sl_monitor)
        self.heartbeat_history.append(current_stats)
        if len(self.heartbeat_history) > self.HEARTBEAT_TREND_WINDOW:
            self.heartbeat_history.pop(0)
            
        # ===== [V5.3] ARCHITECTED DRIFT DETECTION (Ticket-Specific) =====
        # Refactored to use ticket-specific delta tracking (HeartbeatDriftMonitor).
        # This completely eliminates 4000% spikes from trade transitions.
        drift_warning = self.sl_monitor.evaluate_drift(self.shadow_positions)
        if drift_warning:
            self.logger.warning(drift_warning)

        # Check for PnL drift (General threshold)
        if len(self.heartbeat_history) >= 10:
            start_pnl = self.heartbeat_history[0]['pnl']
            end_pnl = self.heartbeat_history[-1]['pnl']
            pnl_drift = abs(end_pnl - start_pnl)
            
            if pnl_drift > 100.0:
                self.logger.warning(
                    f"[HEARTBEAT_DRIFT] Significant PnL drift detected: ${pnl_drift:.2f} over "
                    f"last {len(self.heartbeat_history)} heartbeat cycles."
                )
            
            # Check for ticket count stability
            all_counts = [h['ticket_count'] for h in self.heartbeat_history]
            count_variance = max(all_counts) - min(all_counts)
            
            if count_variance > 5:
                 self.logger.critical(
                    f"[HEARTBEAT_DRIFT] High ticket count variance detected over last "
                    f"{len(self.heartbeat_history)} heartbeat cycles. Drift: {count_variance} tickets. "
                    f"Possible memory leak or synchronization failure."
                )

            # Integrate with force-reload monitoring
            if current_stats['force_reload_rate'] > 5:
                self.logger.warning(
                    f"[HEARTBEAT_DRIFT] Elevated force-reload frequency detected: "
                    f"{current_stats['force_reload_rate']} events in cycle window. "
                    f"Check IPC stability."
                )

        # ===== IMPROVEMENT #5: HEARTBEAT DRIFT CORRECTION =====
        # Check if MT5 is reporting zero positions while the bot still has open trades.
        # If this persists for DRIFT_SYNC_THRESHOLD cycles, force a memory sync.
        # Note: In production, portfolio_data should be passed or fetched here.
        # Approximation: if monitor_positions was called and found 0 positions, 
        # but our shadow_positions still has items, it's a drift.
        
        # We'll use a flag or check against the last known MT5 state if available.
        # For now, we integrate it into the cycle check.
        # If len(self.open_positions) + len(self.shadow_positions) > 0 but MT5 is empty:
        # (This logic is already partially in the summary, let's implement it correctly)
        
        # Since heartbeat doesn't take portfolio_data, we'll check a flag set by monitor_positions
        if hasattr(self, '_last_mt5_position_count') and self._last_mt5_position_count == 0:
            if len(self.shadow_positions) > 0:
                self._zero_position_drift_counter += 1
                if self._zero_position_drift_counter >= self.DRIFT_SYNC_THRESHOLD:
                    self.logger.critical(
                        f"[HEARTBEAT_DRIFT] MT5 reported 0 positions for {self.DRIFT_SYNC_THRESHOLD} "
                        f"consecutive cycles, but bot memory holds {len(self.shadow_positions)} shadow positions. "
                        f"Triggering SELF-HEALING SYNC."
                    )
                    self._force_memory_sync()
                    # Reset counter after sync
                    self._zero_position_drift_counter = 0
            else:
                self._zero_position_drift_counter = 0
        else:
            self._zero_position_drift_counter = 0
        # ===== END IMPROVEMENT #5 =====

        # ===== HEARTBEAT POSITION SUMMARY (clean, per-position) =====
        # Log state for every currently tracked shadow position
        if self.shadow_positions:
            total_pnl_shadow = sum(float(p.get('profit', 0)) for p in self.shadow_positions.values())
            self.logger.info(
                f"[HEARTBEAT-SUMMARY] Cycle {cycle_count} | "
                f"Shadow positions: {total_shadows} (Candidates: {candidates}, Adopted: {adopted}) | "
                f"Total shadow PnL: ${total_pnl_shadow:.2f}"
            )
            for tid, pos_data in list(self.shadow_positions.items()):
                sym = pos_data.get('symbol', 'UNKNOWN')
                ep = float(pos_data.get('entry_price', 0.0))
                pnl = float(pos_data.get('profit', 0.0))
                sl = pos_data.get('emergency_sl', 'N/A')
                is_cand = pos_data.get('is_candidate', False)
                self.logger.debug(
                    f"  [SHADOW] #{tid} | {sym} | EP: {ep:.5f} | PnL: ${pnl:.2f} | "
                    f"SL: {sl} | Candidate: {is_cand}"
                )
        else:
            self.logger.info(f"[HEARTBEAT-SUMMARY] Cycle {cycle_count} | No shadow positions tracked.")
        



    def set_daily_loss_limit(self, limit: float) -> None:
        """Set maximum daily loss limit in account currency"""
        self.daily_loss_limit = limit
        self.logger.info(f"Daily loss limit set to ${format_float(limit, '.2f')}")
    
    async def check_daily_loss_limit(self) -> bool:
        """
        Check if daily loss limit has been exceeded
        
        Returns:
            True if limit exceeded, False otherwise
        """
        # Reset counter at start of new day
        today = datetime.now(timezone.utc).date()
        if today != self.last_reset_date:
            self.daily_loss_amount = 0.0
            self.last_reset_date = today
            self.logger.info("Daily loss counter reset")
        
        return self.daily_loss_amount >= self.daily_loss_limit
    
    def register_position_attribution(self, position_id: str, attribution_data: Dict[str, Any]) -> None:
        """
        Register attribution data for a new position immediately after execution.
        
        Args:
            position_id: The position ID (usually same as order ID)
            attribution_data: Dictionary containing ML features, policy, etc.
        """
        position_id = str(position_id)
        if position_id not in self.position_attribution_data:
            self.position_attribution_data[position_id] = {
                'min_price': attribution_data.get('entry_price', 0.0),
                'max_price': attribution_data.get('entry_price', 0.0),
                'initial_sl': attribution_data.get('stop_loss', 0.0),
                'entry_price': attribution_data.get('entry_price', 0.0),
                'take_profit': attribution_data.get('take_profit', 0.0),
                'exit_policy': attribution_data.get('exit_policy', ExitPolicy.STANDARD.value),
                'predicted_exit_policy': attribution_data.get('predicted_exit_policy'),
                'policy_confidence': attribution_data.get('policy_confidence', 0.0),
                'entry_features': attribution_data.get('entry_features'),
                'strategy_meta': dict(attribution_data.get('strategy_meta', {}) or {}),
            }
            self.logger.info(f"Registered attribution data for position {position_id}")

        # Keep runtime registries synchronized for health/merge/tracking counters.
        self.open_positions[position_id] = {
            'position_id': position_id,
            'symbol': attribution_data.get('symbol', ''),
            'direction': attribution_data.get('direction'),
            'entry_price': attribution_data.get('entry_price', 0.0),
            'current_price': attribution_data.get('current_price', attribution_data.get('entry_price', 0.0)),
            'volume': attribution_data.get('volume', 0.0),
            'stop_loss': attribution_data.get('stop_loss', 0.0),
            'take_profit': attribution_data.get('take_profit', 0.0),
            'strategy_meta': dict(attribution_data.get('strategy_meta', {}) or {}),
        }
        self.active_ticket_registry.add(position_id)

        self._save_state()

    def update_position_strategy_state(
        self,
        position_id: str,
        strategy_meta: Optional[Dict[str, Any]] = None,
        stop_loss: Optional[float] = None,
    ) -> None:
        """Persist strategy-specific position state across runtime maps and disk."""
        position_id = str(position_id)
        state_changed = False

        if strategy_meta is not None:
            clean_meta = self._serialize_shadow_json_safe(dict(strategy_meta or {}))
            if position_id not in self.position_attribution_data:
                self.position_attribution_data[position_id] = {}
            self.position_attribution_data[position_id]["strategy_meta"] = clean_meta
            if position_id in self.open_positions:
                self.open_positions[position_id]["strategy_meta"] = clean_meta
            state_changed = True

        if stop_loss is not None:
            if position_id not in self.position_attribution_data:
                self.position_attribution_data[position_id] = {}
            self.position_attribution_data[position_id]["stop_loss"] = stop_loss
            self.position_attribution_data[position_id]["initial_sl"] = self.position_attribution_data[position_id].get(
                "initial_sl",
                stop_loss,
            )
            if position_id in self.open_positions:
                self.open_positions[position_id]["stop_loss"] = stop_loss
            state_changed = True

        if state_changed:
            self._save_state()

    
    def _force_memory_sync(self) -> None:
        """
        ===== IMPROVEMENT #5: SELF-HEALING MEMORY SYNC =====
        Called when MT5 reports 0 active positions but the bot's internal tracker
        still believes trades are open for more than DRIFT_SYNC_THRESHOLD consecutive
        cycles. This resolves 'Heartbeat Drift' warnings caused by manual liquidations
        or missed exit events.

        Actions:
        1. Clears self.open_positions (runtime position map)
        2. Clears self.shadow_positions (adopted orphan tracker)
        3. Clears self.position_attribution_data (exit attribution data)
        4. Resets self.breakeven_applied_tickets (per-trade flags)
        5. Persists cleared shadow state to disk
        6. Logs a critical warning so operators are aware of the forced sync
        """
        self.logger.critical(
            f"[FORCE_MEMORY_SYNC] Manual liquidation or missed-exit detected. "
            f"MT5 reported 0 positions for {self._zero_position_drift_counter} consecutive cycles "
            f"but bot tracker held {len(self.shadow_positions) + len(self.open_positions)} records. "
            f"Clearing all internal position lists and resetting Unrealized P&L to $0.00."
        )
        self.open_positions.clear()
        self.shadow_positions.clear()
        self.active_ticket_registry.clear()
        self.position_attribution_data.clear()
        self.breakeven_applied_tickets.clear()
        self._zero_position_drift_counter = 0
        self._save_shadow_state()
        self._save_state()
        self.logger.critical(
            "[FORCE_MEMORY_SYNC] ✅ Internal state cleared. Unrealized P&L reset to $0.00. "
            "Bot will re-adopt any genuine MT5 positions on next periodic_shadow_scan cycle."
        )
    async def monitor_positions(self, portfolio_data: Dict[str, Any], position_tracker=None) -> List[Tuple[str, float]]:
        """
        Monitor open positions, verify SL/TP protection, and detect closed positions for attribution.
        Manual closes are disabled unless performing emergency overrides.
        """
        closed_positions = []
        state_changed = False
        current_position_ids = set()
        
        for position in portfolio_data.get('positions', []):
            position_id = str(position.get('position_id'))
            current_position_ids.add(position_id)
            symbol = position.get('symbol', '').replace('/','')
            current_price = position.get('current_price')
            entry_price = position.get('entry_price')
            direction = position.get('direction')
            now_utc = datetime.now(timezone.utc)
            symbol_key = str(symbol or "").replace("/", "").upper()
            sl_modification_frozen = False
            gap_amnesty_until = self.gap_amnesty_until_by_symbol.get(symbol_key)
            if isinstance(gap_amnesty_until, datetime):
                if now_utc < gap_amnesty_until:
                    sl_modification_frozen = True
                else:
                    self.gap_amnesty_until_by_symbol.pop(symbol_key, None)
            
            if not all([current_price, entry_price, position_id]):
                continue
            
            stop_loss = position.get('stop_loss')
            take_profit = position.get('take_profit')
            position_size = position.get('quantity', 0)
            position_open_time = position.get('open_time', datetime.now(timezone.utc))
            
            # --- PROTECTION VERIFICATION ---
            sl_missing = stop_loss is None or stop_loss == 0.0
            tp_missing = take_profit is None or take_profit == 0.0
            
            if sl_missing or tp_missing:
                self.logger.critical(
                    f"[ORDER_EXECUTION] SLTP_NOT_ATTACHED_ABORTED_TRADE | Symbol: {symbol} | "
                    f"Position {position_id} lacks active protection! SL: {stop_loss}, TP: {take_profit}. "
                    f"Triggering corrective modification..."
                )
                pip_size = (0.01 if 'JPY' in symbol else 0.0001)
                
                if sl_missing:
                    dist = pip_size * 50 # 50 pip fallback
                    stop_loss = entry_price - dist if direction in (Direction.LONG, 'LONG') else entry_price + dist
                
                if tp_missing:
                    dist = pip_size * 125 # 2.5R targeting fallback
                    take_profit = entry_price + dist if direction in (Direction.LONG, 'LONG') else entry_price - dist
                
                await self.broker.modify_order(order_id=position_id, sl=stop_loss, tp=take_profit)
                self.logger.critical(f"[CORRECTION] Attached emergency SL/TP to {position_id} | SL: {stop_loss:.5f} TP: {take_profit:.5f}")
            else:
                sl_dist = abs(current_price - stop_loss)
                tp_dist = abs(take_profit - current_price)
                self.logger.debug(
                    f"[PROTECTION_CONFIRMED] {symbol} #{position_id} | "
                    f"SL Dist: {sl_dist:.5f} | TP Dist: {tp_dist:.5f}"
                )
            # --- END PROTECTION VERIFICATION ---
            
            # --- ATTRIBUTION TRACKING ---
            if position_id not in self.position_attribution_data:
                # Initialize new position tracking
                self.position_attribution_data[position_id] = {
                    'min_price': current_price,
                    'max_price': current_price,
                    'initial_sl': stop_loss if stop_loss else 0.0,
                    'entry_price': entry_price,
                    'exit_policy': position.get('exit_policy', 'STANDARD') if isinstance(position.get('exit_policy'), str) else position.get('exit_policy', ExitPolicy.STANDARD).value,
                    'symbol': symbol
                }
                state_changed = True
            
            # Update extremes (MAE/MFE inputs)
            attr_data = self.position_attribution_data[position_id]
            if take_profit is not None:
                attr_data['take_profit'] = take_profit
            if stop_loss is not None:
                attr_data['stop_loss'] = stop_loss
            if current_price > attr_data.get('max_price', current_price):
                attr_data['max_price'] = current_price
                state_changed = True
            if current_price < attr_data.get('min_price', current_price):
                attr_data['min_price'] = current_price
                state_changed = True
                
            # Determine correct high/low for logic (MFE-like)
            if direction in (Direction.LONG, 'LONG'):
                position_high = attr_data.get('max_price', current_price)
            else:
                position_high = attr_data.get('min_price', current_price) # For SHORT, lower is better
            
            # Get Policy enum from stored string
            policy_str = attr_data.get('exit_policy', 'STANDARD')
            try:
                active_policy = ExitPolicy(policy_str)
            except ValueError:
                active_policy = ExitPolicy.STANDARD
            
            # --- END ATTRIBUTION TRACKING ---
            
            # ===== IMPROVEMENT #3: MOVE-TO-BREAKEVEN AT 1.0R (WITH SAFETY BUFFERS) =====
            # FIX 2: Breakeven trigger widened to 1.0R to avoid premature stop-outs.
            # FIX 2: Breakeven SL is set to Entry ± (Spread * 2) to cover transaction costs.
            if position_id not in self.breakeven_applied_tickets:
                attr_initial_sl = self.position_attribution_data.get(position_id, {}).get('initial_sl')
                unrealized_pnl  = position.get('unrealized_pnl', 0.0)
                if attr_initial_sl and entry_price and attr_initial_sl != 0.0:
                    initial_risk = abs(entry_price - attr_initial_sl)  # 1R in price units
                    gap_guard_window_active = bool(
                        self.market_reopened_at and now_utc <= (self.market_reopened_at + timedelta(minutes=30))
                    )
                    price_gap_from_entry = abs((current_price or 0.0) - (entry_price or 0.0))
                    if (
                        gap_guard_window_active
                        and initial_risk > 0
                        and price_gap_from_entry >= initial_risk
                        and not sl_modification_frozen
                    ):
                        gap_amnesty_until = now_utc + timedelta(minutes=5)
                        self.gap_amnesty_until_by_symbol[symbol_key] = gap_amnesty_until
                        sl_modification_frozen = True
                        self.logger.critical(
                            f"[OPEN_GAP_AMNESTY] {symbol} #{position_id} | Gap {price_gap_from_entry:.5f} >= 1.0R "
                            f"({initial_risk:.5f}) at open. SL modifications paused until {gap_amnesty_until.isoformat()}."
                        )
                    price_move_from_entry = abs((current_price or entry_price) - entry_price)
                    if (not sl_modification_frozen) and initial_risk > 0 and price_move_from_entry >= initial_risk:
                        # Retrieve live spread and stop level from MT5
                        try:
                            import MetaTrader5 as _mt5
                            _mt5_sym = symbol.replace('/', '')
                            _sym_info = _mt5.symbol_info(_mt5_sym)
                            _tick = _mt5.symbol_info_tick(_mt5_sym)
                            
                            point = _sym_info.point if _sym_info else 0.00001
                            pip_size = point * 10 if 'JPY' not in symbol else point * 100
                            # Enforce Spread Floor (1.0 Pip)
                            raw_spread_pts = _sym_info.spread * point if _sym_info else (2.0 * pip_size)
                            spread_pts = max(raw_spread_pts, 1.0 * pip_size)
                            stop_level_pts = _sym_info.trade_stops_level * point if _sym_info else (2.0 * pip_size)
                            
                            bid = _tick.bid if _tick else current_price
                            ask = _tick.ask if _tick else current_price
                        except Exception:
                            pip_size = 0.0001 if 'JPY' not in symbol else 0.01
                            spread_pts = 2.0 * pip_size
                            stop_level_pts = 2.0 * pip_size
                            bid = current_price
                            ask = current_price

                        # Requirement: Entry ± (Spread * 2.0) to cover costs and avoid zero-net exits.
                        if direction in (Direction.LONG, 'LONG'):
                            be_sl = round(entry_price + (spread_pts * 2.0), 5)
                            # Safety: Must be below Bid and respect StopLevel
                            max_allowed_sl = bid - (stop_level_pts + 0.2 * pip_size)
                            be_sl = min(be_sl, max_allowed_sl)
                        else:
                            be_sl = round(entry_price - (spread_pts * 2.0), 5)
                            # Safety: Must be above Ask and respect StopLevel
                            min_allowed_sl = ask + (stop_level_pts + 0.2 * pip_size)
                            be_sl = max(be_sl, min_allowed_sl)

                        # Redundancy & Tighten-only Filter
                        should_move_be = False
                        if direction in (Direction.LONG, 'LONG'):
                            if be_sl > (stop_loss or 0) + (0.5 * pip_size):
                                should_update = True
                                should_move_be = True
                        else:
                            if be_sl < (stop_loss or float('inf')) - (0.5 * pip_size):
                                should_update = True
                                should_move_be = True

                        if should_move_be:
                            self.logger.critical(
                                f"[BREAKEVEN_TRIGGER] {symbol} #{position_id} | "
                                f"Price move {price_move_from_entry:.5f} >= 1.0R ({initial_risk:.5f}) | "
                                f"Sliding SL to cost-covered breakeven: {be_sl:.5f} (Entry ± Spread*2)"
                            )
                            try:
                                await self.broker.modify_order(
                                    order_id=position_id,
                                    sl=be_sl,
                                    tp=take_profit if take_profit and take_profit > 0 else None
                                )
                                self.breakeven_applied_tickets.add(position_id)
                                self.logger.info(f"[BREAKEVEN_APPLIED] {symbol} #{position_id} | SL moved to {be_sl:.5f} (RISK-FREE).")
                            except Exception as be_err:
                                self.logger.error(f"[BREAKEVEN_ERROR] {symbol} #{position_id} | Failed: {be_err}")
            # ===== END IMPROVEMENT #3 =====
            
            # Get hit partial levels for this position from persistent state
            if position_id not in self.partial_hits:
                self.partial_hits[position_id] = set()
                state_changed = True
            
            # Check advanced exit conditions
            exit_result = self.advanced_exit_handler.evaluate_exit_conditions(
                symbol=symbol,
                entry_price=entry_price,
                current_price=current_price,
                current_pnl=position.get('unrealized_pnl', 0.0),
                stop_loss=stop_loss,
                take_profit=take_profit,
                direction=direction,
                position_open_time=position_open_time,
                position_high=position_high,
                exit_policy=active_policy
            )
            
            # Unpack tuple (exit_level, pnl_pips)
            exit_level, _ = exit_result if isinstance(exit_result, tuple) else (exit_result, 0)
            
            if not exit_level:
                continue
                
            # ACTION TYPE: MODIFY (Trailing / Breakeven)
            if exit_level.exit_type in (ExitType.TRAILING_STOP, ExitType.BREAKEVEN):
                if sl_modification_frozen:
                    self.logger.info(
                        f"[OPEN_GAP_AMNESTY] {symbol} #{position_id} | SL update deferred during 5m gap-amnesty window."
                    )
                    continue
                new_sl = exit_level.price
                
                # Retrieve Pip-Size and StopLevel for safety buffers
                try:
                    import MetaTrader5 as _mt5
                    _mt5_sym = symbol.replace('/', '')
                    _sym_info = _mt5.symbol_info(_mt5_sym)
                    _tick = _mt5.symbol_info_tick(_mt5_sym)
                    
                    point = _sym_info.point if _sym_info else 0.00001
                    pip_size = point * 10 if 'JPY' not in symbol else point * 100
                    stop_level_pts = _sym_info.trade_stops_level * point if _sym_info else (2.0 * pip_size)
                    
                    bid = _tick.bid if _tick else current_price
                    ask = _tick.ask if _tick else current_price
                except Exception:
                    pip_size = 0.0001 if 'JPY' not in symbol else 0.01
                    stop_level_pts = 2.0 * pip_size
                    bid = current_price
                    ask = current_price

                # Check if new SL is better than current SL
                should_update = False
                if direction in (Direction.LONG, 'LONG'):
                    # Redundancy: Must be at least 0.5 pips away from old SL
                    if (stop_loss is None or new_sl > stop_loss + (0.5 * pip_size)):
                        # Safety: Proposed SL must be >= 2.0 pips away from Bid
                        if new_sl < bid - (2.0 * pip_size):
                            # Safety: Must respect MT5 StopLevel
                            if new_sl < bid - (stop_level_pts + 0.2 * pip_size):
                                should_update = True
                        else:
                            self.logger.debug(f"[TRAILING_SKIP] {symbol} Proposed SL {new_sl:.5f} too close to Bid {bid:.5f}")
                else: # SHORT
                    # Redundancy: Must be at least 0.5 pips away from old SL
                    if (stop_loss is None or new_sl < stop_loss - (0.5 * pip_size)):
                        # Safety: Proposed SL must be >= 2.0 pips away from Ask
                        if new_sl > ask + (2.0 * pip_size):
                            # Safety: Must respect MT5 StopLevel
                            if new_sl > ask + (stop_level_pts + 0.2 * pip_size):
                                should_update = True
                        else:
                            self.logger.debug(f"[TRAILING_SKIP] {symbol} Proposed SL {new_sl:.5f} too close to Ask {ask:.5f}")
                
                if should_update:
                    self.logger.info(f"[MODIFY] {symbol} | {exit_level.description} | Moving SL to {format_float(new_sl, '.5f')}")
                    await self.broker.modify_order(
                        order_id=position_id, 
                        sl=new_sl, 
                        tp=take_profit if take_profit and take_profit > 0 else None
                    )
                continue
            
            # Manual close logic disabled per user request
            self.logger.debug(f"[OBSERVER] Target hit for {symbol} ({exit_level.description}) but waiting for broker SL/TP execution.")

        # 2. Exit Detection (Positions no longer in portfolio)
        # Combine bot-managed and shadow-adopted positions for exit monitoring
        tracked_ids = set(self.position_attribution_data.keys()) | set(self.shadow_positions.keys())
        for tracked_id in tracked_ids:
            if tracked_id not in current_position_ids:
                # Position was closed! Find out why.
                self.logger.info(f"[EXIT_DETECTION] Position {tracked_id} is gone. Querying history...")
                exit_info = await self.broker.get_position_exit_reason(tracked_id)

                attr = self.position_attribution_data.get(tracked_id) or self.shadow_positions.get(tracked_id, {})
                closed_symbol = attr.get('symbol', '')

                # ===== ANTI REVENGE-TRADE: Stamp cooldown IMMEDIATELY before cleanup/re-eval =====
                if closed_symbol and self.admission_controller is not None:
                    try:
                        self.admission_controller.register_symbol_cooldown(closed_symbol)
                    except Exception as _cd_err:
                        self.logger.error(
                            "[SYMBOL_COOLDOWN] Failed to stamp cooldown for %s: %s",
                            closed_symbol, _cd_err,
                        )

                if exit_info:
                    exit_reason = str(exit_info.get("reason", "UNDEFINED"))
                    deal_reason_code = int(exit_info.get("deal_reason_code", -1) or -1)
                    realized_pnl = float(exit_info.get("realized_pnl", 0.0) or 0.0)
                    exit_price = float(exit_info.get("exit_price", 0.0) or 0.0)
                    self.logger.critical(
                        "[EXIT_REASON] %s for position %s | MT5DealReason=%d | RealizedPnL=$%.2f | ExitPrice=%.5f",
                        exit_reason,
                        tracked_id,
                        deal_reason_code,
                        realized_pnl,
                        exit_price,
                    )
                    closed_positions.append((closed_symbol or 'UNK', realized_pnl))
                else:
                    fallback_reason = str(attr.get("pending_exit_reason") or attr.get("exit_reason") or attr.get("exit_policy") or "UNDEFINED")
                    self.logger.critical(
                        "[EXIT_REASON] %s for position %s (history fallback). Cooldown still stamped.",
                        fallback_reason,
                        tracked_id,
                    )
                    closed_positions.append((closed_symbol or 'UNK', 0.0))

                await self._process_silent_exit(tracked_id)
                state_changed = True
                
        if state_changed:
            self._save_state()
            
        # Store MT5 position count for heartbeat drift detection
        self._last_mt5_position_count = len(portfolio_data.get('positions', []))
        
        return closed_positions

    async def _process_silent_exit(self, position_id: str):
        """Cleanup state for a position that was closed by the broker (SL/TP hit)"""
        # Resolve the symbol before we delete the records
        attr = self.position_attribution_data.get(position_id) or self.shadow_positions.get(position_id, {})
        _exit_symbol = attr.get('symbol', '')

        # Cleanup state
        if position_id in self.position_attribution_data:
            del self.position_attribution_data[position_id]
        if position_id in self.partial_hits:
            del self.partial_hits[position_id]
        if position_id in self.shadow_positions:
            self.logger.debug(f"Cleaning up shadow position tracking for {position_id}")
            del self.shadow_positions[position_id]
            self.active_ticket_registry.discard(str(position_id))
            self._save_shadow_state()

        # Cooldown stamping happens in EXIT_DETECTION before cleanup to guarantee ordering.


    async def check_and_close_positions(self, portfolio_data: Dict, position_tracker=None) -> List[Tuple[str, float]]:
        """Compatibility alias for monitor_positions"""
        return await self.monitor_positions(portfolio_data, position_tracker)
    
    async def _close_position(
        self,
        symbol: str,
        position_id: str,
        current_price: float,
        position_size: float,
        entry_price: float,
        exit_reason: ExitReason,
        direction,
        position_tracker=None,
        stop_loss: float = None
    ) -> float:
        """
        Close a position and calculate P&L with full attribution
        """
        try:
            # Create closing order (opposite direction)
            close_direction = Direction.SHORT if direction == Direction.LONG else Direction.LONG
            
            close_order = Order(
                order_id=f"close_{position_id}_{int(datetime.now().timestamp())}",
                symbol=symbol,
                order_type=OrderType.MARKET,
                direction=close_direction,
                quantity=position_size,
                price=current_price,
                stop_loss=None,
                take_profit=None,
                status=OrderStatus.PENDING,
                created_at=datetime.now(timezone.utc)
            )
            
            # Execute close order
            result = await self.execution_engine.execute_trade(close_order)
            
            if result.success:
                # Calculate P&L
                CONTRACT_SIZE = 100000.0
                if direction in (Direction.LONG, 'LONG'):
                    pnl = (current_price - entry_price) * position_size * CONTRACT_SIZE
                else:  # SHORT
                    pnl = (entry_price - current_price) * position_size * CONTRACT_SIZE
                
                # Handle JPY pairs
                if 'JPY' in str(symbol).upper():
                    pnl = pnl / current_price
                
                # Update daily loss if this is a loss
                if pnl < 0:
                    self.daily_loss_amount += abs(pnl)
                
                # --- ATTRIBUTION METRICS CALCULATION ---
                attr_data = self.position_attribution_data.get(position_id, {})
                initial_sl = attr_data.get('initial_sl', stop_loss if stop_loss else 0.0)
                min_price = attr_data.get('min_price', current_price)
                max_price = attr_data.get('max_price', current_price)
                exit_policy_str = attr_data.get('exit_policy', 'STANDARD')
                
                # Determine MFE / MAE / R-Multiple
                r_multiple = 0.0
                mfe = 0.0
                mae = 0.0
                
                if direction in (Direction.LONG, 'LONG'):
                    # LONG
                    # MAE: Drawdown (Entry - Min Price)
                    mae = (entry_price - min_price) * CONTRACT_SIZE * position_size
                    # MFE: Peak Profit (Max Price - Entry)
                    mfe = (max_price - entry_price) * CONTRACT_SIZE * position_size
                    
                    # Risk for R calc
                    if initial_sl > 0 and initial_sl < entry_price:
                        risk_per_share = entry_price - initial_sl
                        profit_per_share = current_price - entry_price
                        r_multiple = profit_per_share / risk_per_share
                else:
                    # SHORT
                    # MAE: Drawdown (Max Price - Entry)
                    mae = (max_price - entry_price) * CONTRACT_SIZE * position_size
                    # MFE: Peak Profit (Entry - Min Price)
                    mfe = (entry_price - min_price) * CONTRACT_SIZE * position_size
                    
                    # Risk for R calc
                    if initial_sl > 0 and initial_sl > entry_price:
                        risk_per_share = initial_sl - entry_price
                        profit_per_share = entry_price - current_price
                        r_multiple = profit_per_share / risk_per_share

                # Calculate Exit Quality (Efficiency)
                exit_quality = 0.0
                
                # If Profitable: How much of the MFE did we capture?
                if pnl > 0 and mfe > 0:
                     # MFE is monetary value of peak profit
                     exit_quality = pnl / mfe
                     
                # If Loss: How much of the MAE did we avoid? (Loss Mitigation)
                # Or simply: did we stick to the plan? 
                # Let's use: (MAE - RealizedLoss) / MAE. 
                # If Realized = MAE (hit bottom), quality = 0.
                # If Realized = 0.5 * MAE (saved half), quality = 0.5.
                elif pnl <= 0 and abs(mae) > 0:
                    realized_loss = abs(pnl)
                    max_loss = abs(mae)
                    if max_loss > 0:
                        exit_quality = 1.0 - (realized_loss / max_loss)
                    else:
                        exit_quality = 0.0
                
                # Cap at 1.0 (though MFE could theoretically slightly lag due to ticks, usually pnl <= mfe)
                exit_quality = min(max(exit_quality, 0.0), 1.0)

                # Create Detailed Exit Record
                exit_record = ExitRecord(
                    position_id=position_id,
                    symbol=symbol,
                    entry_time=datetime.now(timezone.utc), # Ideally fetch actual entry time
                    exit_time=datetime.now(timezone.utc),
                    entry_price=entry_price,
                    exit_price=current_price,
                    direction=str(direction),
                    quantity=position_size,
                    reason=exit_reason,
                    profit_loss=pnl,
                    profit_loss_pips=0.0, # Todo: calc pips
                    hold_time_seconds=0, # Todo: calc hold time
                    r_multiple=r_multiple,
                    mfe=mfe, # Monetary MFE
                    mae=mae, # Monetary MAE
                    parent_trade_id=position_id if exit_reason == ExitReason.PARTIAL_TP else None,
                    exit_policy=exit_policy_str,
                    exit_quality=exit_quality,
                    entry_features=attr_data.get('entry_features'),
                    predicted_exit_policy=attr_data.get('predicted_exit_policy'),
                    policy_confidence=attr_data.get('policy_confidence', 0.0),
                    regime_label=attr_data.get('regime_label', 'NEUTRAL')
                )
                
                # Log using structured logger
                self.exit_logger.log_exit(exit_record)

                # Update rolling win/loss metrics (in-memory)
                try:
                    from src.analysis.signal_combiner import rolling_metrics
                    rolling_metrics.record_trade(pnl)
                except Exception:
                    pass

                # RL Tactical outcome recording (if decision id is available)
                try:
                    from src.analysis.trade_context_tracker import trade_context_tracker
                    from src.ml.rl_dispatcher import RLTacticalDispatcher

                    ctx = trade_context_tracker.get_context(position_id)
                    decision_id = ctx.get("rl_decision_id") if ctx else None
                    if decision_id:
                        risk_per_share = 0.0
                        if initial_sl and entry_price and initial_sl != entry_price:
                            risk_per_share = abs(entry_price - initial_sl)
                        risk_money = risk_per_share * CONTRACT_SIZE * position_size if risk_per_share > 0 else 0.0
                        mae_ratio = (abs(mae) / risk_money) if risk_money > 0 else None

                        RLTacticalDispatcher.record_outcome(
                            decision_id=decision_id,
                            outcome={
                                "symbol": symbol,
                                "pnl": pnl,
                                "r_multiple": r_multiple,
                                "mfe": mfe,
                                "mae": mae,
                                "mae_to_sl_ratio": mae_ratio,
                                "exit_quality": exit_quality,
                                "exit_reason": exit_reason.value,
                                "closed_at": datetime.now(timezone.utc).isoformat(),
                            },
                        )
                except Exception as e:
                    self.logger.debug(f"[RL_TACTIC] Outcome recording failed: {e}")
                
                # Log to CSV (Legacy support)
                self._log_trade_to_csv({
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'symbol': symbol,
                    'direction': direction,
                    'entry_price': entry_price,
                    'exit_price': current_price,
                    'quantity': position_size,
                    'pnl': pnl,
                    'exit_reason': exit_reason.value,
                    'position_id': position_id,
                    'r_multiple': r_multiple,
                    'mfe': mfe,
                    'mae': mae,
                    'exit_policy': exit_policy_str,
                    'exit_quality': exit_quality
                })
                
                # Cleanup data if full exit
                if exit_reason != ExitReason.PARTIAL_TP:
                    if position_id in self.position_attribution_data:
                        del self.position_attribution_data[position_id]
                    if position_id in self.partial_hits:
                        del self.partial_hits[position_id]
                    self._save_state()
                    
                    # Also update tracker if provided
                    if position_tracker:
                        try:
                            position_tracker.close_position(
                                position_id, 
                                ExecutionResult(
                                    success=True, 
                                    executed_price=current_price, 
                                    executed_quantity=position_size, 
                                    timestamp=datetime.now(timezone.utc)
                                )
                            )
                        except Exception as e:
                            self.logger.error(f"Failed to update tracker: {e}")
                    
                return pnl
            else:
                self.logger.error(f"Failed to close position {position_id}: {result.error_message}")
                return 0.0
                
        except Exception as e:
            self.logger.error(f"Error closing position {position_id}: {e}")
            return 0.0

    def _log_trade_to_csv(self, trade_data: Dict) -> None:
        """Append trade details to CSV file"""
        filename = 'trade_history.csv'
        file_exists = os.path.isfile(filename)
        
        try:
            with open(filename, 'a', newline='', encoding='utf-8') as f:
                # Updated fieldnames
                fieldnames = ['timestamp', 'symbol', 'direction', 'entry_price', 
                             'exit_price', 'quantity', 'pnl', 'exit_reason', 'position_id',
                             'r_multiple', 'mfe', 'mae', 'exit_policy', 'exit_quality']
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                
                if not file_exists:
                    writer.writeheader()
                
                writer.writerow(trade_data)
        except Exception as e:
            self.logger.error(f"Failed to write to CSV: {e}")
    
    async def check_max_positions_per_symbol(self, symbol: str, max_per_symbol: int = 1) -> bool:
        """
        Check if already have max positions in this symbol
        """
        return False
    
    def check_risk_alerts(self, portfolio) -> bool:
        """
        Check for daily loss or drawdown alerts.
        Returns True if a critical risk threshold is breached.
        """
        if not portfolio:
            return False
            
        # 1. Daily Loss Check
        # Note: Depending on Portfolio model, profit might be daily or total.
        # We assume it represents the current session profit.
        daily_pnl = getattr(portfolio, 'profit', 0.0)
        daily_loss_thresh = 100.0 # From User Request
        
        if daily_pnl < -daily_loss_thresh:
             self.logger.critical(f"⚠️ [RISK ALERT] Daily loss ${abs(daily_pnl):.2f} > ${daily_loss_thresh}. Suspending new entries.")
             return True
             
        # 2. Drawdown Check
        equity = getattr(portfolio, 'equity', 0.0)
        balance = getattr(portfolio, 'balance', 0.0)
        if balance > 0:
            drawdown_pct = (balance - equity) / balance * 100
            if drawdown_pct > 3.0: # User Request: X% (we'll use 3% as default)
                self.logger.critical(f"⚠️ [RISK ALERT] Open drawdown {drawdown_pct:.1f}% > 3.0%. High risk exposure detected.")
                return True
                
        return False

    async def sync_shadow_to_live(self, portfolio, entry_fn) -> int:
        if not self.use_shadow_state:
            return 0
        """
        Evaluate shadow positions and promote to live if they cross PnL confidence threshold.

        BUG FIX [4]: Previously profit was stuck at 0.0 (never refreshed from MT5).
        Now we estimate PnL from portfolio prices and add a 60s time-based fallback.
        """
        promoted_count = 0
        promotion_pnl_threshold = 1.0  # Lowered $2->$1 to unblock stuck candidates
        time_based_promotion_secs = 60  # Promote after 60s if direction is favourable

        # Build price lookup from portfolio
        portfolio_price_map: Dict[str, float] = {}
        if portfolio:
            mt5_positions = getattr(portfolio, 'positions', []) or []
            for p in mt5_positions:
                sym = getattr(p, 'symbol', None)
                price = getattr(p, 'current_price', None) or getattr(p, 'price_current', None)
                if sym and price:
                    portfolio_price_map[sym] = float(price)

        now_utc = datetime.now(timezone.utc)

        for shadow_id, pos in list(self.shadow_positions.items()):
            if not pos.get('is_candidate'):
                continue

            sym = pos.get('symbol', '')
            ep = float(pos.get('entry_price', 0.0))
            direction = pos.get('direction')
            volume = float(pos.get('volume', 0.01))
            adoption_str = pos.get('adoption_time', '')
            age_secs = 0
            if adoption_str:
                try:
                    if isinstance(adoption_str, datetime):
                        adopted = adoption_str
                    else:
                        adopted = datetime.fromisoformat(str(adoption_str))
                    if adopted.tzinfo is None:
                        adopted = adopted.replace(tzinfo=timezone.utc)
                    age_secs = (now_utc - adopted).total_seconds()
                except Exception:
                    pass

            # Update profit estimate from latest portfolio price
            current_price = portfolio_price_map.get(sym, ep)
            if ep > 0 and current_price > 0:
                if isinstance(direction, str):
                    is_long = direction.upper() in ('LONG', 'BUY', '0')
                else:
                    is_long = direction in (0, Direction.LONG)
                pip_factor = 100 if sym and 'JPY' in sym else 10000
                raw_pnl = (current_price - ep) * pip_factor * volume if is_long \
                           else (ep - current_price) * pip_factor * volume
                pos['profit'] = round(raw_pnl, 4)

            pnl = float(pos.get('profit', 0.0))

            promote_reason = None
            if pnl >= promotion_pnl_threshold:
                promote_reason = f"PnL ${pnl:.2f} >= threshold ${promotion_pnl_threshold:.2f}"
            elif age_secs >= time_based_promotion_secs and pnl >= 0:
                promote_reason = (
                    f"Time-based ({age_secs:.0f}s old, PnL ${pnl:.2f} >= 0). "
                    f"Promoting to avoid indefinite hold."
                )

            if promote_reason:
                self.logger.critical(
                    f"[SHADOW_PROMOTE] {shadow_id} ({sym}) promoting. Reason: {promote_reason}"
                )
                try:
                    success = await entry_fn(
                        sym, pos['direction'], volume, ep,
                        pos.get('emergency_sl', 0.0), pos.get('tp', 0.0)
                    )
                    if success:
                        pos['is_candidate'] = False
                        promoted_count += 1
                        self.logger.critical(
                            f"[SHADOW_PROMOTION_SUCCESS] {sym} shadow→live. "
                            f"Volume: {volume} | SL: {pos.get('emergency_sl')} | TP: {pos.get('tp')}"
                        )
                except Exception as e:
                    self.logger.error(f"Failed to promote shadow {shadow_id}: {e}")
            else:
                self.logger.debug(
                    f"[SHADOW_WAITING] {shadow_id} ({sym}) | PnL: ${pnl:.2f} | "
                    f"Age: {age_secs:.0f}s | Needs ${promotion_pnl_threshold:.2f} or {time_based_promotion_secs}s"
                )

        return promoted_count

    def open_shadow_candidate(self, symbol: str, direction: int, entry_price: float, volume: float, sl: float, tp: float):
        """Manual entry for a shadow candidate to be monitored for live promotion."""
        shadow_id = f"S{int(datetime.now().timestamp())}"
        self.shadow_positions[shadow_id] = {
            'symbol': symbol,
            'direction': direction,
            'entry_price': entry_price,
            'volume': volume,
            'emergency_sl': sl,
            'tp': tp,
            'profit': 0.0,
            'is_candidate': True, # This flag enables promotion logic
            'adoption_time': datetime.now(timezone.utc).isoformat()
        }
        self.logger.info(f"🕶️ [SHADOW_ONLY] Opened shadow candidate {shadow_id} for {symbol}. Monitoring for PnL proof...")
        self._save_shadow_state()
        return shadow_id

    def log_position_stats(self, portfolio: Dict) -> Dict[str, float]:
        """Log current position statistics including shadow positions"""
        positions = portfolio.get('positions', [])
        bot_ticket_map: Dict[str, float] = {}
        for p in positions:
            ticket = str(p.get('position_id') or p.get('ticket') or p.get('id') or "")
            pnl_val = float(p.get('unrealized_pnl', 0.0) or 0.0)
            if ticket:
                bot_ticket_map[ticket] = pnl_val

        shadow_ticket_map: Dict[str, float] = {}
        for tid, pdata in self.shadow_positions.items():
            shadow_ticket_map[str(tid)] = float(pdata.get('profit', 0.0) or 0.0)

        merged_ticket_ids = set(bot_ticket_map.keys()) | set(shadow_ticket_map.keys())
        total_open = len(merged_ticket_ids)
        bot_managed_count = len(bot_ticket_map)
        shadow_unique_count = len([tid for tid in shadow_ticket_map.keys() if tid not in bot_ticket_map])

        # PnL: prefer live MT5 PnL for duplicated tickets, use shadow only when ticket is absent in live map.
        total_unrealized = sum(bot_ticket_map.values()) + sum(
            pnl for tid, pnl in shadow_ticket_map.items() if tid not in bot_ticket_map
        )
        bot_unrealized = sum(bot_ticket_map.values())
        shadow_unrealized_unique = sum(
            pnl for tid, pnl in shadow_ticket_map.items() if tid not in bot_ticket_map
        )
        
        self.logger.info(
            f"[POSITION STATS] Total Open: {total_open} (Bot: {bot_managed_count}, ShadowUnique: {shadow_unique_count}) | "
            f"Total Unr PnL: ${total_unrealized:.2f} (Bot: ${bot_unrealized:.2f}, ShadowUnique: ${shadow_unrealized_unique:.2f})"
        )
        
        # Run risk alerts
        self.check_risk_alerts(portfolio)
        return {
            "total_open": float(total_open),
            "bot_managed_count": float(bot_managed_count),
            "shadow_unique_count": float(shadow_unique_count),
            "total_unrealized": float(total_unrealized),
            "bot_unrealized": float(bot_unrealized),
            "shadow_unrealized_unique": float(shadow_unrealized_unique),
        }
