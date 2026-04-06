"""
OrderReconciliation: Clean up ghost tickets and dead order references.

PROBLEM: Bot maintains references to tickets that have been closed in MT5 but still
exist in transactional_registry, managed_tickets, and shadow_positions. These "ghost"
tickets cause:
1. Unnecessary sync operations
2. Failed modification attempts
3. Memory leaks
4. Confusion in trade accounting

SOLUTION:
1. Regularly scan for ghost tickets (local but not in live MT5)
2. Permanently remove ghost tickets from all registries
3. Log what's being cleaned up for audit trail
4. Prevent re-adoption of recently-closed tickets
"""

import logging
import threading
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Set, Any, Tuple
import json
import os

logger = logging.getLogger(__name__)


class OrderReconciliation:
    """
    Reconcile local position registries with live MT5 positions.
    
    Cleans up ghost tickets that don't exist in MT5 but persist in memory.
    Thread-safe via RLock.
    """
    
    # File to track recently-closed tickets (prevent re-adoption)
    RECENT_CLOSES_FILE = "recent_closed_tickets.json"
    RECENT_CLOSES_TTL_HOURS = 1
    
    def __init__(self, position_manager: Optional[Any] = None):
        """
        Initialize order reconciliation.
        
        Args:
            position_manager: PositionManager instance for cleanup
        """
        self.position_manager = position_manager
        self._lock = threading.RLock()
        
        # Statistics
        self._ghost_tickets_detected = 0
        self._ghost_tickets_removed = 0
        self._reconciliation_runs = 0
        self._orphaned_orders_found = 0
        
        # Track recently-closed tickets to prevent re-adoption
        self._recently_closed: Dict[str, datetime] = {}
        self._load_recent_closes()
        
        logger.info(
            "[ORDER_RECONCILIATION_INIT] Ghost ticket cleanup enabled. "
            "Recently-closed ticket tracking: %d tickets",
            len(self._recently_closed),
        )
    
    def _load_recent_closes(self) -> None:
        """Load recently-closed tickets from disk."""
        try:
            if os.path.exists(self.RECENT_CLOSES_FILE):
                with open(self.RECENT_CLOSES_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for ticket, close_time_str in data.items():
                    try:
                        close_time = datetime.fromisoformat(close_time_str)
                        if close_time.tzinfo is None:
                            close_time = close_time.replace(tzinfo=timezone.utc)
                        self._recently_closed[ticket] = close_time
                    except Exception:
                        continue
                
                # Clean up expired entries
                self._expire_recent_closes()
                logger.debug(
                    "[ORDER_RECONCILIATION] Loaded %d recently-closed tickets",
                    len(self._recently_closed),
                )
        except Exception as e:
            logger.warning("[ORDER_RECONCILIATION] Failed to load recent closes: %s", e)
    
    def _save_recent_closes(self) -> None:
        """Persist recently-closed tickets to disk."""
        try:
            data = {
                ticket: close_time.isoformat()
                for ticket, close_time in self._recently_closed.items()
            }
            with open(self.RECENT_CLOSES_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning("[ORDER_RECONCILIATION] Failed to save recent closes: %s", e)
    
    def _expire_recent_closes(self) -> None:
        """Remove entries older than TTL."""
        now = datetime.now(timezone.utc)
        expired = [
            ticket
            for ticket, close_time in self._recently_closed.items()
            if (now - close_time).total_seconds() > (self.RECENT_CLOSES_TTL_HOURS * 3600)
        ]
        for ticket in expired:
            self._recently_closed.pop(ticket, None)
    
    async def reconcile(
        self,
        live_mt5_positions: List[Any],
    ) -> Tuple[List[str], List[str], Dict[str, Any]]:
        """
        Reconcile local registries with live MT5.
        
        Identifies and removes ghost tickets from all local registries.
        
        Args:
            live_mt5_positions: List of live positions from MT5
        
        Returns:
            (ghost_tickets_removed: List[str], orphaned_orders: List[str], analysis: Dict)
        """
        with self._lock:
            self._reconciliation_runs += 1
            
            # Get live tickets from MT5
            live_tickets = {
                str(getattr(p, "position_id", "")) for p in (live_mt5_positions or [])
                if getattr(p, "position_id", "")
            }
            
            logger.info(
                "[ORDER_RECONCILIATION_START] Reconciliation #%d | Live MT5 tickets: %d",
                self._reconciliation_runs,
                len(live_tickets),
            )
            
            # Get local tickets from position_manager registries
            local_tickets = self._get_local_tickets()
            logger.debug(
                "[ORDER_RECONCILIATION] Local registries: %d tickets total",
                len(local_tickets),
            )
            
            # Find ghost tickets (local but not in MT5)
            ghost_tickets = local_tickets - live_tickets
            orphaned_orders = []
            
            if ghost_tickets:
                self._ghost_tickets_detected += len(ghost_tickets)
                logger.critical(
                    "[GHOST_TICKETS_FOUND] %d ghost ticket(s) detected (local but not in MT5): %s",
                    len(ghost_tickets),
                    ghost_tickets,
                )
            
            # Clean up ghost tickets
            removed = []
            if ghost_tickets and self.position_manager:
                removed = await self._cleanup_ghost_tickets(ghost_tickets)
                self._ghost_tickets_removed += len(removed)
            
            # Record recently closed for re-adoption prevention
            for ticket in removed:
                self._recently_closed[ticket] = datetime.now(timezone.utc)
            
            analysis = {
                "reconciliation_run": self._reconciliation_runs,
                "live_tickets_mt5": len(live_tickets),
                "local_tickets_registries": len(local_tickets),
                "ghost_tickets_detected": len(ghost_tickets),
                "ghost_tickets_removed": len(removed),
                "orphaned_orders_cleaned": len(orphaned_orders),
                "total_ghost_removed_lifetime": self._ghost_tickets_removed,
            }
            
            logger.info(
                "[ORDER_RECONCILIATION_SUMMARY] Live: %d | Local: %d | Ghost: %d | Removed: %d",
                len(live_tickets),
                len(local_tickets),
                len(ghost_tickets),
                len(removed),
            )
            
            return removed, orphaned_orders, analysis
    
    def _get_local_tickets(self) -> Set[str]:
        """Get all tickets from local registries."""
        tickets = set()
        
        if not self.position_manager:
            return tickets
        
        # shadow_positions
        if hasattr(self.position_manager, "shadow_positions"):
            shadow = getattr(self.position_manager, "shadow_positions", {})
            if isinstance(shadow, dict):
                tickets.update(shadow.keys())
        
        # open_positions
        if hasattr(self.position_manager, "open_positions"):
            open_pos = getattr(self.position_manager, "open_positions", {})
            if isinstance(open_pos, dict):
                tickets.update(open_pos.keys())
        
        # position_attribution_data
        if hasattr(self.position_manager, "position_attribution_data"):
            attr = getattr(self.position_manager, "position_attribution_data", {})
            if isinstance(attr, dict):
                tickets.update(attr.keys())
        
        # active_ticket_registry
        if hasattr(self.position_manager, "active_ticket_registry"):
            active = getattr(self.position_manager, "active_ticket_registry", set())
            if isinstance(active, (set, list)):
                tickets.update(str(t) for t in active)
        
        # managed_tickets
        if hasattr(self.position_manager, "managed_tickets"):
            managed = getattr(self.position_manager, "managed_tickets", {})
            if isinstance(managed, dict):
                tickets.update(managed.keys())
        
        return tickets
    
    async def _cleanup_ghost_tickets(self, ghost_tickets: Set[str]) -> List[str]:
        """
        Remove ghost tickets from all registries.
        
        Args:
            ghost_tickets: Set of ticket IDs to remove
        
        Returns:
            List of successfully removed tickets
        """
        removed = []
        
        for ticket in ghost_tickets:
            try:
                logger.debug(
                    "[ORDER_RECONCILIATION_CLEANUP] Removing ghost ticket %s",
                    ticket,
                )
                
                # Remove from shadow_positions
                if hasattr(self.position_manager, "shadow_positions"):
                    getattr(self.position_manager, "shadow_positions", {}).pop(ticket, None)
                
                # Remove from open_positions
                if hasattr(self.position_manager, "open_positions"):
                    getattr(self.position_manager, "open_positions", {}).pop(ticket, None)
                
                # Remove from position_attribution_data
                if hasattr(self.position_manager, "position_attribution_data"):
                    getattr(self.position_manager, "position_attribution_data", {}).pop(ticket, None)
                
                # Remove from active_ticket_registry
                if hasattr(self.position_manager, "active_ticket_registry"):
                    active = getattr(self.position_manager, "active_ticket_registry", set())
                    if isinstance(active, set):
                        active.discard(ticket)
                
                # Remove from managed_tickets
                if hasattr(self.position_manager, "managed_tickets"):
                    getattr(self.position_manager, "managed_tickets", {}).pop(ticket, None)
                
                # Persist changes
                if hasattr(self.position_manager, "_save_state"):
                    self.position_manager._save_state()
                
                removed.append(ticket)
                logger.critical(
                    "[GHOST_TICKET_REMOVED] Permanently removed ghost ticket %s from all registries",
                    ticket,
                )
                
            except Exception as e:
                logger.error(
                    "[GHOST_TICKET_CLEANUP_ERROR] Failed to clean ticket %s: %s",
                    ticket,
                    e,
                )
        
        # Persist recently-closed tickets
        if removed:
            self._save_recent_closes()
        
        return removed
    
    def is_recently_closed(self, ticket: str) -> bool:
        """
        Check if ticket was recently closed.
        
        Use this to prevent re-adoption of just-closed tickets.
        
        Args:
            ticket: Ticket ID to check
        
        Returns:
            True if ticket was recently closed
        """
        with self._lock:
            if ticket not in self._recently_closed:
                return False
            
            close_time = self._recently_closed[ticket]
            now = datetime.now(timezone.utc)
            age_seconds = (now - close_time).total_seconds()
            
            if age_seconds > (self.RECENT_CLOSES_TTL_HOURS * 3600):
                self._recently_closed.pop(ticket, None)
                return False
            
            return True
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about order reconciliation."""
        with self._lock:
            return {
                "reconciliation_runs": self._reconciliation_runs,
                "ghost_tickets_detected_lifetime": self._ghost_tickets_detected,
                "ghost_tickets_removed_lifetime": self._ghost_tickets_removed,
                "orphaned_orders_cleaned": self._orphaned_orders_found,
                "recently_closed_tracked": len(self._recently_closed),
            }


# Singleton instance
_order_reconciliation_instance: Optional[OrderReconciliation] = None
_order_reconciliation_lock = threading.RLock()


def get_order_reconciliation(
    position_manager: Optional[Any] = None,
) -> OrderReconciliation:
    """Get or create singleton OrderReconciliation."""
    global _order_reconciliation_instance
    
    if _order_reconciliation_instance is None:
        with _order_reconciliation_lock:
            if _order_reconciliation_instance is None:
                _order_reconciliation_instance = OrderReconciliation(
                    position_manager=position_manager,
                )
    
    return _order_reconciliation_instance


# ===== INTEGRATION PATTERN =====
# In main.py, after profit pre-check, add ghost ticket cleanup:
#
# # STEP 1: Run profit pre-check
# await profit_precheck.execute_precheck(...)
#
# # STEP 2: Clean ghost tickets (BEFORE sync)
# order_reconciliation = get_order_reconciliation(position_manager)
# live_mt5_positions = await broker.get_positions()
# removed, orphaned, analysis = await order_reconciliation.reconcile(live_mt5_positions)
# if removed:
#     logger.warning(f"[GHOST_CLEANUP] Removed {len(removed)} ghost ticket(s)")
#
# # STEP 3: THEN do sync (if needed)
# smart_sync = get_smart_sync_manager()
# should_sync, reason = smart_sync.should_sync(portfolio.positions)
# if should_sync:
#     await position_manager.sync_mt5_state(persist=True)
#
# Expected: Ghost tickets cleaned up automatically, no failed modifications
