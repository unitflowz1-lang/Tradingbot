"""
State Synchronization Manager
Ensures shadow tracker stays in perfect sync with MT5 positions.
Implements event-driven polling with efficient diff detection.

FIX #1: HEARTBEAT_DRIFT - State Sync & Memory Leak
"""

import logging
import json
import os
from typing import Dict, List, Set, Optional, Callable, Any
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import asyncio
import MetaTrader5 as mt5
from src.utils.json_utils import safe_json_load, safe_json_write

logger = logging.getLogger(__name__)


@dataclass
class PositionSnapshot:
    """Immutable snapshot of a single position"""
    ticket: int
    symbol: str
    entry_price: float
    current_price: float
    profit_loss: float
    open_time: datetime
    volume: float
    direction: str  # "BUY" or "SELL"
    swap: float = 0.0
    tick_value: float = 0.0
    contract_size: float = 100000.0
    
    def __hash__(self):
        return hash(self.ticket)
    
    def __eq__(self, other):
        if not isinstance(other, PositionSnapshot):
            return False
        return self.ticket == other.ticket


@dataclass
class SyncDifference:
    """Represents a synchronization discrepancy"""
    type: str  # "ORPHAN_LOCAL" | "ORPHAN_MT5" | "PRICE_MISMATCH" | "SIZE_MISMATCH"
    ticket: int
    symbol: str
    detail: str
    severity: str  # "CRITICAL" | "WARNING" | "INFO"
    recommended_action: str


class StateSyncManager:
    """
    Manages synchronization between local shadow tracker and MT5 live positions.
    Detects and reconciles discrepancies with configurable strategies.
    """
    
    def __init__(self, broker, shadow_tracker_dict: Dict, config: Optional[Dict] = None, position_manager: Optional[Any] = None):
        """
        Args:
            broker: MT5BrokerInterface instance
            shadow_tracker_dict: Reference to the bot's local position dict
            config: Configuration for sync behavior
        """
        self.broker = broker
        self.shadow_tracker = shadow_tracker_dict
        self.position_manager = position_manager
        self.config = self._default_config()
        if config:
            self.config.update(config)
        
        # Sync state
        self.last_sync_time: Optional[datetime] = None
        self.last_mt5_snapshot: Dict[int, PositionSnapshot] = {}
        self.sync_history: List[Dict] = []
        self.consecutive_sync_failures: int = 0
        self.pending_cleanup: Dict[str, Dict[str, Any]] = {}
        self.pending_adoption: Dict[str, Dict[str, Any]] = {}
        
        # Event callbacks
        self.on_orphan_detected: List[Callable[[SyncDifference], None]] = []
        self.on_sync_complete: List[Callable[[Dict], None]] = []
    
    @staticmethod
    def _default_config() -> Dict:
        return {
            'sync_interval_seconds': 2.0,  # Poll MT5 every 2 seconds
            'max_sync_lag_seconds': 5.0,   # Alert if lag > 5 seconds
            'enable_auto_cleanup': True,   # Auto-remove orphan locals
            'enable_auto_healing': True,   # Auto-override locals with MT5 truth
            'max_consecutive_failures': 3, # Trigger alert after 3 failures
            'adoption_observation_cycles': 2,  # Require persistence across syncs before adoption
            'adoption_price_tolerance_pips': 3.0,  # Ignore transient MT5 price wobble while observing
            'mt5_retry_attempts': 4,
            'mt5_retry_backoff_seconds': 0.25,
            'heartbeat_drift_threshold': 5.0,
            'slave_mode': True,
        }
    
    def register_orphan_handler(self, callback: Callable[[SyncDifference], None]):
        """Register callback for when orphan positions are detected"""
        self.on_orphan_detected.append(callback)
    
    def register_sync_complete_handler(self, callback: Callable[[Dict], None]):
        """Register callback when sync completes"""
        self.on_sync_complete.append(callback)

    def _normalize_ticket(self, ticket: object) -> str:
        """Normalize ticket ids so MT5 ints and shadow-state string keys compare safely."""
        return str(ticket)

    def _build_emergency_adoption_payload(self, snapshot: PositionSnapshot) -> Dict[str, Any]:
        pip_val = 0.01 if "JPY" in snapshot.symbol.upper() else 0.0001
        emergency_sl = (
            snapshot.entry_price - (50 * pip_val)
            if snapshot.direction == "BUY"
            else snapshot.entry_price + (50 * pip_val)
        )
        return {
            "symbol": snapshot.symbol,
            "entry_price": float(snapshot.entry_price),
            "current_price": float(snapshot.current_price),
            "profit": float(snapshot.profit_loss),
            "volume": float(snapshot.volume),
            "quantity": float(snapshot.volume),
            "direction": 0 if snapshot.direction == "BUY" else 1,
            "opened_at": snapshot.open_time.isoformat(),
            "adoption_time": snapshot.open_time.isoformat(),
            "adoption_confirmed": True,
            "amnesia_protected": True,
            "state_sync_adopted": True,
            "sync_source": "STATE_SYNC_EMERGENCY_ADOPTION",
            "emergency_sl": float(emergency_sl),
        }

    @staticmethod
    def _decimal_or_zero(value: Any) -> Decimal:
        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return Decimal("0")

    def _get_symbol_digits(self, symbol: str) -> int:
        fallback_digits = 3 if "JPY" in str(symbol).upper() else 5
        try:
            info = mt5.symbol_info(str(symbol or "").replace("/", "").upper())
            if info:
                return int(getattr(info, "digits", fallback_digits) or fallback_digits)
        except Exception:
            pass
        return fallback_digits

    def _get_symbol_pip_size(self, symbol: str) -> Decimal:
        digits = self._get_symbol_digits(symbol)
        return Decimal("0.01") if digits == 3 else Decimal("0.0001")

    def _round_for_symbol(self, symbol: str, value: Any) -> float:
        digits = self._get_symbol_digits(symbol)
        return float(
            self._decimal_or_zero(value).quantize(
                Decimal("1").scaleb(-digits),
                rounding=ROUND_HALF_UP,
            )
        )

    def _persist_fill_price_update(self, ticket: str, payload: Dict[str, Any]) -> None:
        if self.position_manager is not None:
            try:
                if hasattr(self.position_manager, "position_attribution_data"):
                    attr = self.position_manager.position_attribution_data.setdefault(ticket, {})
                    attr["entry_price"] = payload.get("entry_price", 0.0)
                    attr["current_price"] = payload.get("current_price", 0.0)
                    attr["profit"] = payload.get("profit", 0.0)
                if hasattr(self.position_manager, "_save_state"):
                    self.position_manager._save_state()
                if hasattr(self.position_manager, "_save_shadow_state"):
                    self.position_manager._save_shadow_state()
            except Exception as exc:
                logger.error("[SYNC_STATION] Failed to persist position manager state for ticket %s: %s", ticket, exc)

        registry_path = os.path.join(os.getcwd(), "transactional_tickets.json")
        try:
            # FIX: Use safe_json_load for robust handling
            registry = safe_json_load(
                file_path=registry_path,
                default={},
                auto_recover=True,
            )
            entry = dict(registry.get(ticket, {}) or {})
            entry["entry_price"] = payload.get("entry_price", 0.0)
            entry["current_price"] = payload.get("current_price", 0.0)
            entry["profit"] = payload.get("profit", 0.0)
            entry["symbol"] = payload.get("symbol", entry.get("symbol", "UNKNOWN"))
            entry["persisted_at"] = datetime.now(timezone.utc).isoformat()
            registry[ticket] = entry
            
            # FIX: Use safe_json_write for atomic writes with backup
            safe_json_write(
                file_path=registry_path,
                data=registry,
                indent=2,
                create_backup=True,
            )
        except Exception as exc:
            logger.error("[SYNC_STATION] Failed writing transactional registry for ticket %s: %s", ticket, exc)

    async def _call_mt5_with_backoff(
        self,
        method_name: str,
        *args,
        none_is_error: bool = True,
    ) -> Any:
        retries = int(self.config.get("mt5_retry_attempts", 4))
        base_backoff = float(self.config.get("mt5_retry_backoff_seconds", 0.25))
        last_error: Optional[Exception] = None

        for attempt in range(retries):
            try:
                method = getattr(mt5, method_name)
                result = await asyncio.to_thread(method, *args)
                if result is None and none_is_error:
                    raise RuntimeError(f"{method_name} returned None")
                return result
            except Exception as exc:
                last_error = exc
                if attempt >= retries - 1:
                    break
                await asyncio.sleep(base_backoff * (2 ** attempt))

        raise RuntimeError(f"MT5 call failed after {retries} attempts: {method_name} | {last_error}")

    def cleanup_and_reset_state(self, reason: str) -> None:
        """
        Clear local mirrors and pending sync artifacts so the next cycle can rebuild
        cleanly from terminal truth.
        """
        logger.critical("[STATE_SYNC_RESET] Triggered cleanup/reset. Reason: %s", reason)
        self.pending_cleanup.clear()
        self.pending_adoption.clear()
        self.last_mt5_snapshot.clear()

        try:
            self.shadow_tracker.clear()
        except Exception as exc:
            logger.error("[STATE_SYNC_RESET] Failed clearing shadow tracker: %s", exc)

        if self.position_manager is not None:
            try:
                if hasattr(self.position_manager, "open_positions"):
                    self.position_manager.open_positions.clear()
                if hasattr(self.position_manager, "active_ticket_registry"):
                    self.position_manager.active_ticket_registry.clear()
                if hasattr(self.position_manager, "managed_tickets"):
                    managed = getattr(self.position_manager, "managed_tickets")
                    if isinstance(managed, dict):
                        managed.clear()
                if hasattr(self.position_manager, "_save_shadow_state"):
                    self.position_manager._save_shadow_state()
            except Exception as exc:
                logger.error("[STATE_SYNC_RESET] Position manager reset failed: %s", exc)

    def reconcile_positions(self, snapshots: Dict[str, PositionSnapshot]) -> None:
        """
        Single source of truth mirror: local state becomes a projection of MT5.
        """
        live_tickets = set(snapshots.keys())
        stale_tickets = [ticket for ticket in list(self.shadow_tracker.keys()) if self._normalize_ticket(ticket) not in live_tickets]
        for stale_ticket in stale_tickets:
            self.shadow_tracker.pop(stale_ticket, None)

        for ticket, snapshot in snapshots.items():
            payload = self._build_emergency_adoption_payload(snapshot)
            existing = self.shadow_tracker.get(ticket) or {}
            existing_entry = self._decimal_or_zero(existing.get("entry_price", payload.get("entry_price", 0.0)))
            broker_entry = self._decimal_or_zero(getattr(snapshot, "entry_price", 0.0))
            fill_discrepancy_pips = 0.0
            broker_symbol = str(getattr(snapshot, "symbol", payload.get("symbol", "")) or "")
            broker_entry_price = float(getattr(snapshot, "entry_price", payload.get("entry_price", 0.0)) or 0.0)
            broker_current_price = float(getattr(snapshot, "current_price", payload.get("current_price", 0.0)) or 0.0)
            broker_pnl = float(getattr(snapshot, "profit_loss", 0.0) or 0.0)
            broker_open_time = getattr(snapshot, "open_time", None) or datetime.now(timezone.utc)
            broker_volume = float(getattr(snapshot, "volume", 0.0) or 0.0)
            broker_tick_value = float(getattr(snapshot, "tick_value", 0.0) or 0.0)
            broker_contract_size = float(getattr(snapshot, "contract_size", 0.0) or 0.0)
            pip_size = self._get_symbol_pip_size(broker_symbol)
            if pip_size > 0:
                fill_discrepancy_pips = float((abs(existing_entry - broker_entry) / pip_size).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
            payload["profit"] = round(broker_pnl, 2)
            payload["entry_price"] = self._round_for_symbol(broker_symbol, broker_entry_price)
            payload["current_price"] = self._round_for_symbol(broker_symbol, broker_current_price)
            payload["opened_at"] = broker_open_time.isoformat()
            payload["adoption_time"] = existing.get("adoption_time", broker_open_time.isoformat())
            payload["sync_source"] = "MT5_SINGLE_SOURCE_OF_TRUTH"
            self.shadow_tracker[ticket] = payload
            logger.info(
                "[SYNC_DEBUG] Symbol: %s | Lot: %.2f | TickVal: %.5f | Contract: %.0f",
                broker_symbol,
                broker_volume,
                broker_tick_value,
                broker_contract_size,
            )
            if str(broker_symbol or "").replace("/", "").upper() == "AUDUSD":
                local_tick_value = 0.0
                if self.position_manager is not None:
                    try:
                        local_tick_value = float(
                            getattr(self.position_manager, "_local_tick_value", 0.0)
                            or existing.get("tick_value", 0.0)
                            or 0.0
                        )
                    except Exception:
                        local_tick_value = 0.0
                logger.debug(
                    "[TICK_VAL_DEBUG] AUD/USD | BrokerTickValue: %.5f | LocalTickValue: %.5f",
                    broker_tick_value,
                    float(local_tick_value or 0.0),
                )
            if self.position_manager is not None:
                try:
                    if hasattr(self.position_manager, "open_positions"):
                        position_state = self.position_manager.open_positions.setdefault(ticket, {})
                        position_state["entry_price"] = payload["entry_price"]
                        position_state["current_price"] = payload["current_price"]
                        position_state["profit"] = payload["profit"]
                        position_state["pnl"] = payload["profit"]
                        position_state["unrealized_pnl"] = payload["profit"]
                    if hasattr(self.position_manager, "position_attribution_data"):
                        attr = self.position_manager.position_attribution_data.setdefault(ticket, {})
                        attr["entry_price"] = payload["entry_price"]
                        attr["current_price"] = payload["current_price"]
                        attr["profit"] = payload["profit"]
                        attr["pnl"] = payload["profit"]
                    if hasattr(self.position_manager, "unrealized_pnl"):
                        self.position_manager.unrealized_pnl = payload["profit"]
                except Exception as exc:
                    logger.error("[SYNC_STATION] Failed to refresh in-memory broker state for ticket %s: %s", ticket, exc)
            self._persist_fill_price_update(ticket, payload)
            if fill_discrepancy_pips > 5.0:
                self._persist_fill_price_update(ticket, payload)
                logger.warning(
                    "[SYNC_STATION] Disk state updated with fill price for ticket %s.",
                    ticket,
                )

        if self.position_manager is not None:
            try:
                if hasattr(self.position_manager, "_save_state"):
                    self.position_manager._save_state()
                if hasattr(self.position_manager, "_save_shadow_state"):
                    self.position_manager._save_shadow_state()
            except Exception as exc:
                logger.error("[STATE_SYNC] Failed to persist mirrored broker-slave state: %s", exc)

    async def poll_terminal_state(self) -> Dict[str, PositionSnapshot]:
        """
        Poll terminal state directly from MT5. This is the authoritative source used
        before each trade cycle.
        """
        try:
            account_info = await self._call_mt5_with_backoff("account_info")
        except Exception as exc:
            self.cleanup_and_reset_state(f"account_info_unavailable: {exc}")
            return {}

        if account_info is None:
            self.cleanup_and_reset_state("account_info returned None")
            return {}

        snapshots = await self._fetch_mt5_positions()
        snapshot_map = {self._normalize_ticket(snapshot.ticket): snapshot for snapshot in snapshots}

        if self.config.get("enable_auto_healing", True):
            self.reconcile_positions(snapshot_map)

        return snapshot_map

    async def heartbeat_reconcile(self, tracked_total_pnl: Optional[float] = None) -> Dict[str, Any]:
        """
        Compare the terminal's live PnL with the caller's tracked value and trigger a
        reset/mirror rebuild on significant drift.
        """
        snapshot_map = await self.poll_terminal_state()
        live_total_pnl = sum(float(snapshot.profit_loss) for snapshot in snapshot_map.values())
        mirrored_total_pnl = sum(
            float((self.shadow_tracker.get(ticket) or {}).get("profit", 0.0) or 0.0)
            for ticket in snapshot_map.keys()
        )
        reference_total_pnl = mirrored_total_pnl if self.config.get("slave_mode", True) else float(tracked_total_pnl or 0.0)
        drift = abs(reference_total_pnl - live_total_pnl)

        if drift > float(self.config.get("heartbeat_drift_threshold", 5.0)):
            logger.debug(
                "[HEARTBEAT_DRIFT] Tracked PnL drift exceeded threshold | tracked=%.2f | live=%.2f | drift=%.2f",
                reference_total_pnl,
                live_total_pnl,
                drift,
            )
            self.cleanup_and_reset_state(f"heartbeat_drift:{drift:.2f}")
            if self.config.get("enable_auto_healing", True):
                self.reconcile_positions(snapshot_map)

        return {
            "live_total_pnl": live_total_pnl,
            "tracked_total_pnl": reference_total_pnl,
            "drift": drift,
            "position_count": len(snapshot_map),
        }

    def _emergency_adopt_mt5_position(self, snapshot: PositionSnapshot) -> bool:
        ticket = self._normalize_ticket(snapshot.ticket)
        payload = self._build_emergency_adoption_payload(snapshot)
        try:
            if self.position_manager is not None and hasattr(self.position_manager, "adopt_shadow_position"):
                self.position_manager.adopt_shadow_position(ticket, payload, save_immediate=True)
            else:
                self.shadow_tracker[ticket] = payload
            logger.critical(
                "[STATE_SYNC_EMERGENCY_ADOPTION] Ticket %s (%s) reconstructed into local registry for immediate management.",
                ticket,
                snapshot.symbol,
            )
            return True
        except Exception as exc:
            logger.error(
                "[STATE_SYNC_EMERGENCY_ADOPTION] Failed to adopt MT5 orphan %s (%s): %s",
                ticket,
                snapshot.symbol,
                exc,
            )
            return False

    def _price_tolerance(self, symbol: str) -> float:
        pip_val = 0.01 if "JPY" in str(symbol).upper() else 0.0001
        return float(self.config.get("adoption_price_tolerance_pips", 3.0)) * pip_val

    def _queue_mt5_orphan(self, snapshot: PositionSnapshot, sync_start: datetime) -> bool:
        """
        Hold newly-seen MT5 orphans for a short observation window so brief MT5/local
        race conditions do not immediately count as sync issues.

        Returns True when the orphan is stable enough to adopt now.
        """
        ticket = self._normalize_ticket(snapshot.ticket)
        tolerance = self._price_tolerance(snapshot.symbol)
        existing = self.pending_adoption.get(ticket)
        if existing is None:
            self.pending_adoption[ticket] = {
                "symbol": snapshot.symbol,
                "first_seen": sync_start.isoformat(),
                "last_seen": sync_start.isoformat(),
                "cycles_seen": 1,
                "entry_price": float(snapshot.entry_price),
                "current_price": float(snapshot.current_price),
                "volume": float(snapshot.volume),
            }
            logger.info(
                "[STATE_SYNC_PENDING_ADOPTION] Ticket %s (%s) observed in MT5 only. "
                "Waiting %d cycle(s) for stable reconciliation window.",
                ticket,
                snapshot.symbol,
                int(self.config.get("adoption_observation_cycles", 2)),
            )
            return False

        existing["last_seen"] = sync_start.isoformat()
        price_stable = abs(float(existing.get("current_price", 0.0)) - float(snapshot.current_price)) <= tolerance
        volume_stable = abs(float(existing.get("volume", 0.0)) - float(snapshot.volume)) < 1e-9
        symbol_stable = str(existing.get("symbol")) == str(snapshot.symbol)
        existing["current_price"] = float(snapshot.current_price)
        existing["volume"] = float(snapshot.volume)
        existing["cycles_seen"] = int(existing.get("cycles_seen", 0)) + 1

        required_cycles = int(self.config.get("adoption_observation_cycles", 2))
        if symbol_stable and volume_stable and price_stable and int(existing["cycles_seen"]) >= required_cycles:
            self.pending_adoption.pop(ticket, None)
            return True

        logger.debug(
            "[STATE_SYNC_PENDING_ADOPTION] Ticket %s (%s) still stabilizing | cycles=%d/%d | price_stable=%s | volume_stable=%s",
            ticket,
            snapshot.symbol,
            int(existing["cycles_seen"]),
            required_cycles,
            price_stable,
            volume_stable,
        )
        return False
    
    async def synchronize(self) -> bool:
        """
        Execute full sync cycle: fetch MT5 positions, compare to local, reconcile.
        
        Returns:
            True if sync successful
        """
        try:
            sync_start = datetime.now(timezone.utc)
            
            # Step 1: Poll authoritative terminal state
            mt5_snapshot_map = await self.poll_terminal_state()
            mt5_positions = list(mt5_snapshot_map.values())
            mt5_tickets = set(mt5_snapshot_map.keys())
            
            # Step 2: Get local shadow tracker state
            local_tickets = {self._normalize_ticket(ticket) for ticket in self.shadow_tracker.keys()}
            
            # Step 3: Diff analysis
            orphan_local = local_tickets - mt5_tickets  # Closed manually in MT5
            orphan_mt5 = mt5_tickets - local_tickets    # Opened outside bot

            # Step 4: Record discrepancies from the pre-mirror delta.
            differences = []
            for ticket in orphan_local:
                shadow_entry = self.shadow_tracker.get(ticket) or {}
                symbol = shadow_entry.get('symbol', '?')
                differences.append(SyncDifference(
                    type="ORPHAN_LOCAL",
                    ticket=ticket,
                    symbol=symbol,
                    detail="Local state missing from terminal truth",
                    severity="WARNING",
                    recommended_action="Purge from local mirror"
                ))

            for ticket in orphan_mt5:
                snapshot = mt5_snapshot_map.get(ticket)
                symbol = snapshot.symbol if snapshot else "?"
                differences.append(SyncDifference(
                    type="ORPHAN_MT5",
                    ticket=ticket,
                    symbol=symbol,
                    detail="Position present in MT5 and mirrored into local state",
                    severity="INFO",
                    recommended_action="Adopt terminal truth"
                ))
            
            # Update snapshot
            self.last_mt5_snapshot = mt5_snapshot_map
            self.last_sync_time = sync_start
            self.consecutive_sync_failures = 0
            
            # Log sync result
            duration_ms = (datetime.now(timezone.utc) - sync_start).total_seconds() * 1000
            sync_result = {
                'timestamp': sync_start.isoformat(),
                'duration_ms': duration_ms,
                'mt5_position_count': len(mt5_tickets),
                'local_position_count': len(local_tickets),
                'orphan_local_count': len(orphan_local),
                'orphan_mt5_count': len(orphan_mt5),
                'pending_adoption_count': 0,
                'differences': differences
            }
            self.sync_history.append(sync_result)
            
            # Invoke callbacks
            for callback in self.on_sync_complete:
                try:
                    callback(sync_result)
                except Exception as e:
                    logger.error(f"[STATE_SYNC] Sync callback error: {e}")
            
            logger.info(
                f"[STATE_SYNC] Sync complete: {len(mt5_tickets)} MT5, {len(local_tickets)} Local, "
                f"Issues: {len(differences)}, Pending: 0, Duration: {duration_ms:.1f}ms"
            )
            
            return True
            
        except Exception as e:
            self.consecutive_sync_failures += 1
            logger.error(
                f"[STATE_SYNC] Sync failed (attempt {self.consecutive_sync_failures}): {e}"
            )
            
            if self.consecutive_sync_failures >= self.config['max_consecutive_failures']:
                logger.critical(
                    f"[STATE_SYNC_EMERGENCY] {self.consecutive_sync_failures} consecutive failures. "
                    f"Consider full system reset."
                )
            
            return False
    
    async def _fetch_mt5_positions(self) -> List[PositionSnapshot]:
        """Fetch all open positions from MT5"""
        try:
            positions = await self._call_mt5_with_backoff("positions_get")
            
            snapshots = []
            for pos in positions:
                current_price = float(getattr(pos, "price_current", 0.0) or getattr(pos, "price_open", 0.0) or 0.0)
                swap_value = float(getattr(pos, "swap", 0.0) or 0.0)
                profit_loss = float(getattr(pos, "profit", 0.0) or 0.0) + swap_value
                tick_value = 0.0
                contract_size = 100000.0
                try:
                    info = mt5.symbol_info(pos.symbol)
                    if info:
                        tick_value = float(getattr(info, "trade_tick_value", 0.0) or 0.0)
                        contract_size = float(getattr(info, "trade_contract_size", 100000.0) or 100000.0)
                except Exception:
                    tick_value = 0.0
                    contract_size = 100000.0
                
                snapshot = PositionSnapshot(
                    ticket=pos.ticket,
                    symbol=pos.symbol,
                    entry_price=pos.price_open,
                    current_price=current_price,
                    profit_loss=profit_loss,
                    open_time=datetime.fromtimestamp(pos.time, tz=timezone.utc),
                    volume=pos.volume,
                    direction="BUY" if pos.type == mt5.ORDER_TYPE_BUY else "SELL",
                    swap=swap_value,
                    tick_value=tick_value,
                    contract_size=contract_size,
                )
                snapshots.append(snapshot)
            
            return snapshots
            
        except Exception as e:
            logger.error(f"[STATE_SYNC] Failed to fetch MT5 positions: {e}")
            return []
    
    def _notify_orphan_handlers(self, difference: SyncDifference):
        """Invoke orphan detection callbacks"""
        for callback in self.on_orphan_detected:
            try:
                callback(difference)
            except Exception as e:
                logger.error(f"[STATE_SYNC] Orphan handler error: {e}")
    
    def get_sync_health(self) -> Dict:
        """Get current sync health status"""
        return {
            'last_sync': self.last_sync_time.isoformat() if self.last_sync_time else None,
            'sync_count': len(self.sync_history),
            'consecutive_failures': self.consecutive_sync_failures,
            'local_positions': len(self.shadow_tracker),
            'mt5_positions': len(self.last_mt5_snapshot),
            'pending_adoptions': len(self.pending_adoption),
            'is_healthy': self.consecutive_sync_failures < self.config['max_consecutive_failures']
        }
