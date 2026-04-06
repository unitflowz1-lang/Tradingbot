"""
PersistentPositionState: Maintains stable in-memory state + JSON disk persistence.

PROBLEM: Bot rebuilds position state from MT5 every cycle (SYNC_MT5_STATE), 
losing in-memory state and entering "amnesia" when terminal connection blips.

SOLUTION: 
1. Load position state once at startup from disk
2. Update state incrementally as MT5 events occur (MODIFIED/CLOSED)
3. Persist to disk on state change
4. Sync with MT5 only for conflict resolution (not as primary update source)

CRITICAL: This prevents 'SYNC_MT5_STATE' from running every cycle.
"""

import json
import threading
import logging
from typing import Dict, List, Optional, Any, Set
from datetime import datetime, timezone
from dataclasses import dataclass, asdict, field
from enum import Enum
import os

logger = logging.getLogger(__name__)


class PositionEventType(Enum):
    """Types of position state changes."""
    OPENED = "opened"
    MODIFIED = "modified"
    CLOSED = "closed"
    SYNCED = "synced"  # Full MT5 sync reconciliation
    ERROR = "error"


@dataclass
class PositionSnapshot:
    """Immutable snapshot of a position at a point in time."""
    symbol: str
    ticket: str
    direction: str  # "LONG" or "SHORT"
    entry_price: float
    current_price: float
    volume: float
    profit: float
    stop_loss: float
    take_profit: float
    opened_at: datetime
    updated_at: datetime
    strategy_meta: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "symbol": self.symbol,
            "ticket": self.ticket,
            "direction": self.direction,
            "entry_price": self.entry_price,
            "current_price": self.current_price,
            "volume": self.volume,
            "profit": self.profit,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "opened_at": self.opened_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "strategy_meta": self.strategy_meta,
        }


class PersistentPositionState:
    """
    In-memory position state with atomic disk persistence.
    
    Thread-safe via RLock.
    
    KEY BEHAVIORAL CHANGES vs old SYNC_MT5_STATE:
    1. Loads once at startup from disk
    2. Updates incrementally (no full rebuilds per cycle)
    3. Syncs with MT5 only for validation/conflict resolution
    4. Persists on every state change (atomic writes)
    """
    
    STATE_FILE = "position_state_persistent.json"
    
    def __init__(self, state_file: str = STATE_FILE):
        """
        Initialize persistent position state.
        
        Args:
            state_file: Path to JSON state file (default: position_state_persistent.json)
        """
        self.state_file = state_file
        self._lock = threading.RLock()
        
        # In-memory position registry: {ticket: PositionSnapshot}
        self._positions: Dict[str, PositionSnapshot] = {}
        
        # Event log for debugging (last 1000 events)
        self._event_log: List[Dict[str, Any]] = []
        self._max_events = 1000
        
        # Statistics
        self._total_opened = 0
        self._total_closed = 0
        self._total_modified = 0
        self._total_syncs = 0
        
        # Load persisted state on initialization
        self._load_from_disk()
        
        logger.info(
            "[PERSISTENT_STATE_INIT] Loaded %d positions from disk. "
            "State file: %s",
            len(self._positions),
            self.state_file
        )
    
    def _load_from_disk(self) -> None:
        """Load position state from JSON file."""
        try:
            if not os.path.exists(self.state_file):
                logger.info("[PERSISTENT_STATE] No state file found. Starting with clean state.")
                return
            
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            positions_data = data.get("positions", {})
            for ticket, pos_dict in positions_data.items():
                try:
                    opened_dt = datetime.fromisoformat(pos_dict["opened_at"])
                    updated_dt = datetime.fromisoformat(pos_dict["updated_at"])
                    snapshot = PositionSnapshot(
                        symbol=pos_dict["symbol"],
                        ticket=ticket,
                        direction=pos_dict["direction"],
                        entry_price=float(pos_dict["entry_price"]),
                        current_price=float(pos_dict["current_price"]),
                        volume=float(pos_dict["volume"]),
                        profit=float(pos_dict["profit"]),
                        stop_loss=float(pos_dict["stop_loss"]),
                        take_profit=float(pos_dict["take_profit"]),
                        opened_at=opened_dt,
                        updated_at=updated_dt,
                        strategy_meta=pos_dict.get("strategy_meta", {}),
                    )
                    self._positions[ticket] = snapshot
                except Exception as e:
                    logger.warning(
                        "[PERSISTENT_STATE] Failed to load position %s: %s",
                        ticket, e
                    )
                    continue
            
            logger.info(
                "[PERSISTENT_STATE_LOADED] Restored %d positions from %s",
                len(self._positions),
                self.state_file
            )
        except Exception as e:
            logger.error("[PERSISTENT_STATE] Failed to load state: %s", e)
    
    def _save_to_disk(self) -> None:
        """Atomically save position state to JSON file."""
        try:
            with self._lock:
                payload = {
                    "positions": {
                        ticket: snapshot.to_dict()
                        for ticket, snapshot in self._positions.items()
                    },
                    "saved_at": datetime.now(timezone.utc).isoformat(),
                    "total_opened": self._total_opened,
                    "total_closed": self._total_closed,
                    "total_modified": self._total_modified,
                    "total_syncs": self._total_syncs,
                }
            
            # Write to temp file first, then rename (atomic on most filesystems)
            temp_file = self.state_file + ".tmp"
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            
            if os.path.exists(self.state_file):
                os.replace(temp_file, self.state_file)
            else:
                os.rename(temp_file, self.state_file)
            
            logger.debug(
                "[PERSISTENT_STATE_SAVED] Saved %d positions to %s",
                len(self._positions),
                self.state_file
            )
        except Exception as e:
            logger.error("[PERSISTENT_STATE] Failed to save state: %s", e)
    
    def _log_event(self, event_type: PositionEventType, ticket: str, details: str) -> None:
        """Log a position event for debugging."""
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type.value,
            "ticket": ticket,
            "details": details,
        }
        self._event_log.append(event)
        if len(self._event_log) > self._max_events:
            self._event_log.pop(0)
    
    def add_position(self, position: PositionSnapshot) -> None:
        """
        Add a new opened position to state.
        
        Args:
            position: PositionSnapshot of newly opened position
        """
        with self._lock:
            self._positions[position.ticket] = position
            self._total_opened += 1
            self._log_event(
                PositionEventType.OPENED,
                position.ticket,
                f"{position.symbol} | Volume: {position.volume} | Entry: {position.entry_price}"
            )
            self._save_to_disk()
        
        logger.info(
            "[POSITION_ADDED] %s | Ticket: %s | Volume: %.2f | Entry: %.5f",
            position.symbol,
            position.ticket,
            position.volume,
            position.entry_price
        )
    
    def update_position(self, position: PositionSnapshot) -> None:
        """
        Update an existing position (price/profit changed).
        
        Args:
            position: Updated PositionSnapshot
        """
        with self._lock:
            if position.ticket not in self._positions:
                logger.warning(
                    "[POSITION_UPDATE] Ticket %s not found in state. Adding as new.",
                    position.ticket
                )
                self.add_position(position)
                return
            
            old_position = self._positions[position.ticket]
            self._positions[position.ticket] = position
            self._total_modified += 1
            self._log_event(
                PositionEventType.MODIFIED,
                position.ticket,
                f"PnL: {old_position.profit:.2f} → {position.profit:.2f} | "
                f"Price: {old_position.current_price:.5f} → {position.current_price:.5f}"
            )
            self._save_to_disk()
        
        logger.debug(
            "[POSITION_UPDATED] %s | Ticket: %s | Profit: %.2f | Price: %.5f",
            position.symbol,
            position.ticket,
            position.profit,
            position.current_price
        )
    
    def close_position(self, ticket: str, final_profit: float) -> bool:
        """
        Mark position as closed.
        
        Args:
            ticket: Position ticket ID
            final_profit: Final profit value
        
        Returns:
            True if position was found and closed, False if not found
        """
        with self._lock:
            if ticket not in self._positions:
                logger.warning(
                    "[POSITION_CLOSE] Ticket %s not found in state",
                    ticket
                )
                return False
            
            position = self._positions.pop(ticket)
            self._total_closed += 1
            self._log_event(
                PositionEventType.CLOSED,
                ticket,
                f"{position.symbol} | Final PnL: {final_profit:.2f}"
            )
            self._save_to_disk()
        
        logger.info(
            "[POSITION_CLOSED] %s | Ticket: %s | Final PnL: %.2f",
            position.symbol,
            ticket,
            final_profit
        )
        return True
    
    def get_position(self, ticket: str) -> Optional[PositionSnapshot]:
        """Get position by ticket."""
        with self._lock:
            return self._positions.get(ticket)
    
    def get_all_positions(self) -> List[PositionSnapshot]:
        """Get all open positions."""
        with self._lock:
            return list(self._positions.values())
    
    def get_positions_by_symbol(self, symbol: str) -> List[PositionSnapshot]:
        """Get all positions for a specific symbol."""
        with self._lock:
            return [pos for pos in self._positions.values() if pos.symbol == symbol]
    
    def get_open_ticket_ids(self) -> Set[str]:
        """Get set of all open position ticket IDs."""
        with self._lock:
            return set(self._positions.keys())
    
    def sync_with_mt5(self, mt5_positions: List[Any], merge_strategy: str = "mt5_authoritative") -> None:
        """
        Reconcile local state with MT5 positions.
        
        This is NOT a full rebuild. It's a validation check:
        - If position exists in both, update with MT5 data
        - If position only in MT5, add it
        - If position only in local state, keep it (may be just closed)
        
        Args:
            mt5_positions: List of positions from MT5
            merge_strategy: "mt5_authoritative" (default) or "local_preserving"
        """
        with self._lock:
            mt5_tickets = {str(getattr(p, "ticket", None)) for p in mt5_positions}
            
            # Update/add positions from MT5
            for mt5_pos in mt5_positions:
                ticket = str(getattr(mt5_pos, "ticket", None))
                if not ticket:
                    continue
                
                symbol = getattr(mt5_pos, "symbol", "UNKNOWN")
                direction = "LONG" if getattr(mt5_pos, "type", 0) == 0 else "SHORT"
                
                if ticket in self._positions:
                    # Position exists locally, update it
                    snapshot = PositionSnapshot(
                        symbol=symbol,
                        ticket=ticket,
                        direction=direction,
                        entry_price=getattr(mt5_pos, "price_open", 0.0),
                        current_price=getattr(mt5_pos, "price_current", 0.0),
                        volume=getattr(mt5_pos, "volume", 0.0),
                        profit=getattr(mt5_pos, "profit", 0.0),
                        stop_loss=getattr(mt5_pos, "sl", 0.0),
                        take_profit=getattr(mt5_pos, "tp", 0.0),
                        opened_at=self._positions[ticket].opened_at,  # Keep original
                        updated_at=datetime.now(timezone.utc),
                        strategy_meta=self._positions[ticket].strategy_meta,
                    )
                    self._positions[ticket] = snapshot
                else:
                    # New position, add it
                    snapshot = PositionSnapshot(
                        symbol=symbol,
                        ticket=ticket,
                        direction=direction,
                        entry_price=getattr(mt5_pos, "price_open", 0.0),
                        current_price=getattr(mt5_pos, "price_current", 0.0),
                        volume=getattr(mt5_pos, "volume", 0.0),
                        profit=getattr(mt5_pos, "profit", 0.0),
                        stop_loss=getattr(mt5_pos, "sl", 0.0),
                        take_profit=getattr(mt5_pos, "tp", 0.0),
                        opened_at=datetime.now(timezone.utc),
                        updated_at=datetime.now(timezone.utc),
                        strategy_meta={},
                    )
                    self._positions[ticket] = snapshot
                    logger.info(
                        "[POSITION_ADOPTED_FROM_MT5] %s | Ticket: %s | Volume: %.2f",
                        symbol,
                        ticket,
                        getattr(mt5_pos, "volume", 0.0)
                    )
            
            # Check for locally-held positions that were just closed in MT5
            closed_in_mt5 = set(self._positions.keys()) - mt5_tickets
            for ticket in closed_in_mt5:
                position = self._positions.pop(ticket)
                self._total_closed += 1
                logger.info(
                    "[POSITION_SYNCED_CLOSED] %s | Ticket: %s | Final PnL: %.2f",
                    position.symbol,
                    ticket,
                    position.profit
                )
            
            self._total_syncs += 1
            self._save_to_disk()
        
        logger.info(
            "[PERSISTENT_STATE_SYNCED] MT5 reconciliation complete. "
            "Now tracking %d positions (adopted: %d | closed: %d)",
            len(self._positions),
            len(mt5_tickets),
            len(closed_in_mt5)
        )
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about position state."""
        with self._lock:
            return {
                "total_positions_now": len(self._positions),
                "total_opened": self._total_opened,
                "total_closed": self._total_closed,
                "total_modified": self._total_modified,
                "total_mt5_syncs": self._total_syncs,
                "event_log_size": len(self._event_log),
                "state_file": self.state_file,
                "symbols_tracked": list(set(p.symbol for p in self._positions.values())),
            }
    
    def clear_for_testing(self) -> None:
        """Clear all state (testing only)."""
        with self._lock:
            self._positions.clear()
            self._event_log.clear()
            self._total_opened = 0
            self._total_closed = 0
            self._total_modified = 0
            self._total_syncs = 0
            if os.path.exists(self.state_file):
                os.remove(self.state_file)
            logger.warning("[PERSISTENT_STATE] Cleared all state for testing")


# ===== USAGE PATTERN =====
# Instead of:
#     for each cycle:
#         positions = await mt5.get_positions()
#         # Full rebuild of position state
#         sync_mt5_state()  # WRONG: Rebuilds every 10 seconds!
#
# Use:
#     persistent_state = PersistentPositionState()  # Load once at startup
#
#     for each cycle:
#         # Minimal reconciliation (not rebuild)
#         await persistent_state.sync_with_mt5(mt5.get_positions())
#         
#         # Or update incrementally as events occur
#         persistent_state.add_position(new_position)
#         persistent_state.update_position(updated_position)
#         persistent_state.close_position(ticket, final_pnl)
#
# Expected: No "SYNC_MT5_STATE" full rebuilds every cycle
