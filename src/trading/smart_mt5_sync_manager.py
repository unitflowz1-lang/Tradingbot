"""
SmartMT5SyncManager: Intelligent position state synchronization.

PROBLEM: sync_mt5_state() runs every cycle (every 10 seconds), overwriting
ProfitProtectionModule memory before it can execute exits.

SOLUTION: 
1. Decouple sync from cycle frequency
2. Only sync if live positions changed OR 5 minutes have passed
3. Never sync while profit protection is actively working
"""

import logging
import threading
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Set, Any, Tuple
import time

logger = logging.getLogger(__name__)


class SmartMT5SyncManager:
    """
    Intelligent sync manager that reduces sync frequency while preserving state accuracy.
    
    Sync triggers:
    1. Position count changed (new open/close detected)
    2. 5 minutes have passed since last sync
    3. Explicit force_sync requested
    
    Thread-safe via RLock.
    """
    
    def __init__(
        self,
        min_sync_interval_seconds: int = 300,  # 5 minutes
        track_position_changes: bool = True,
    ):
        """
        Initialize smart sync manager.
        
        Args:
            min_sync_interval_seconds: Min time between syncs (default 300 = 5 min)
            track_position_changes: If True, sync when position count changes
        """
        self.min_sync_interval_seconds = min_sync_interval_seconds
        self.track_position_changes = track_position_changes
        
        self._lock = threading.RLock()
        self._last_sync_at: Optional[datetime] = None
        self._last_position_count: int = 0
        self._last_live_tickets: Set[str] = set()
        
        # Statistics
        self._total_syncs: int = 0
        self._syncs_due_to_time: int = 0
        self._syncs_due_to_position_change: int = 0
        self._syncs_skipped: int = 0
        
        # Ghost ticket tracking
        self._ghost_tickets_found = 0
        self._ghost_tickets_cleaned = 0
        
        logger.info(
            "[SMART_SYNC_INIT] Min interval: %d seconds | Track position changes: %s",
            min_sync_interval_seconds,
            track_position_changes
        )
    
    def should_sync(
        self,
        current_positions: List[Any],
        current_live_tickets: Optional[Set[str]] = None,
    ) -> Tuple[bool, str]:
        """
        Determine if sync is needed.
        
        Returns:
            (should_sync: bool, reason: str)
            - (True, "time_expired") if > min_sync_interval_seconds
            - (True, "position_changed") if position count or tickets changed
            - (False, "sync_fresh") if recently synced and no changes
        """
        with self._lock:
            now = datetime.now(timezone.utc)
            current_count = len(current_positions) if current_positions else 0
            current_tickets = current_live_tickets or {
                str(getattr(p, "position_id", "")) for p in (current_positions or [])
            }
            
            # First sync ever
            if self._last_sync_at is None:
                return True, "first_sync"
            
            # Check time elapsed
            elapsed = (now - self._last_sync_at).total_seconds()
            if elapsed > self.min_sync_interval_seconds:
                self._syncs_due_to_time += 1
                return True, "time_expired"
            
            # Check position count changed
            if self.track_position_changes:
                if current_count != self._last_position_count:
                    self._syncs_due_to_position_change += 1
                    return True, "position_changed"
                
                # Check if specific tickets changed (not just count)
                if current_tickets != self._last_live_tickets:
                    self._syncs_due_to_position_change += 1
                    return True, "position_changed"
            
            # No sync needed
            self._syncs_skipped += 1
            return False, "sync_fresh"
    
    def mark_synced(
        self,
        current_positions: List[Any],
        current_live_tickets: Optional[Set[str]] = None,
        reason: str = "unknown",
    ) -> None:
        """
        Record that sync occurred. Call this AFTER successful sync.
        
        Args:
            current_positions: Current positions list
            current_live_tickets: Set of ticket IDs
            reason: Reason for sync (logged)
        """
        with self._lock:
            now = datetime.now(timezone.utc)
            self._last_sync_at = now
            self._last_position_count = len(current_positions) if current_positions else 0
            self._last_live_tickets = current_live_tickets or {
                str(getattr(p, "position_id", "")) for p in (current_positions or [])
            }
            self._total_syncs += 1
            
            logger.info(
                "[SMART_SYNC_DONE] Sync #%d | Reason: %s | Positions: %d | Tickets: %s | Total syncs: %d (time: %d, change: %d, skipped: %d)",
                self._total_syncs,
                reason,
                self._last_position_count,
                self._last_live_tickets,
                self._total_syncs,
                self._syncs_due_to_time,
                self._syncs_due_to_position_change,
                self._syncs_skipped,
            )
    
    def find_ghost_tickets(
        self,
        live_mt5_tickets: Set[str],
        local_registry_tickets: Set[str],
    ) -> Tuple[Set[str], Dict[str, str]]:
        """
        Find ghost tickets (local but not in MT5).
        
        Ghost tickets are tickets that exist in local memory but don't exist in
        the live MT5 terminal. They should be removed from the transactional registry.
        
        Args:
            live_mt5_tickets: Set of ticket IDs currently in MT5
            local_registry_tickets: Set of ticket IDs in local registry
        
        Returns:
            (ghost_tickets: Set[str], analysis: Dict)
        """
        with self._lock:
            ghost_tickets = local_registry_tickets - live_mt5_tickets
            
            analysis = {
                "ghost_count": len(ghost_tickets),
                "mt5_count": len(live_mt5_tickets),
                "local_count": len(local_registry_tickets),
                "ghost_list": list(ghost_tickets),
            }
            
            if ghost_tickets:
                self._ghost_tickets_found += len(ghost_tickets)
                logger.warning(
                    "[GHOST_TICKETS_DETECTED] Found %d ghost tickets (local but not in MT5): %s",
                    len(ghost_tickets),
                    ghost_tickets,
                )
            
            return ghost_tickets, analysis
    
    def cleanup_ghost_tickets(
        self,
        ghost_tickets: Set[str],
        cleanup_callback,
    ) -> Tuple[int, List[str]]:
        """
        Remove ghost tickets from registry.
        
        Args:
            ghost_tickets: Set of ticket IDs to remove
            cleanup_callback: Function to call for cleanup (e.g., position_manager.remove_ticket)
        
        Returns:
            (removed_count: int, removed_tickets: List[str])
        """
        removed_tickets = []
        
        for ticket in ghost_tickets:
            try:
                cleanup_callback(ticket)
                removed_tickets.append(ticket)
                self._ghost_tickets_cleaned += 1
                logger.critical(
                    "[GHOST_TICKET_CLEANED] Permanently removed ghost ticket %s from registry",
                    ticket,
                )
            except Exception as e:
                logger.error(
                    "[GHOST_TICKET_CLEANUP_ERROR] Failed to cleanup ticket %s: %s",
                    ticket,
                    e,
                )
        
        if removed_tickets:
            logger.warning(
                "[GHOST_CLEANUP_SUMMARY] Removed %d ghost ticket(s) from registry",
                len(removed_tickets),
            )
        
        return len(removed_tickets), removed_tickets
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about sync behavior."""
        with self._lock:
            return {
                "total_syncs": self._total_syncs,
                "syncs_due_to_time": self._syncs_due_to_time,
                "syncs_due_to_position_change": self._syncs_due_to_position_change,
                "syncs_skipped": self._syncs_skipped,
                "ghost_tickets_found": self._ghost_tickets_found,
                "ghost_tickets_cleaned": self._ghost_tickets_cleaned,
                "min_sync_interval_seconds": self.min_sync_interval_seconds,
                "last_sync_at": self._last_sync_at.isoformat() if self._last_sync_at else None,
                "last_position_count": self._last_position_count,
            }
    
    def force_sync_next_cycle(self) -> None:
        """Force sync on next check (for emergency situations)."""
        with self._lock:
            self._last_sync_at = None  # Reset timer
            logger.warning("[SMART_SYNC] Forcing sync on next cycle (emergency)")
    
    def reset_stats(self) -> None:
        """Reset statistics (for testing)."""
        with self._lock:
            self._total_syncs = 0
            self._syncs_due_to_time = 0
            self._syncs_due_to_position_change = 0
            self._syncs_skipped = 0


def create_ghost_cleanup_callback(position_manager):
    """
    Create a cleanup callback for removing ghost tickets from position_manager.
    
    Args:
        position_manager: The PositionManager instance
    
    Returns:
        Callable that removes a ticket from all registries
    """
    def cleanup_ticket(ticket: str) -> None:
        """Remove ticket from all registries."""
        # Remove from various registries
        if hasattr(position_manager, 'shadow_positions'):
            position_manager.shadow_positions.pop(ticket, None)
        
        if hasattr(position_manager, 'open_positions'):
            position_manager.open_positions.pop(ticket, None)
        
        if hasattr(position_manager, 'position_attribution_data'):
            position_manager.position_attribution_data.pop(ticket, None)
        
        if hasattr(position_manager, 'active_ticket_registry'):
            position_manager.active_ticket_registry.discard(ticket)
        
        if hasattr(position_manager, 'managed_tickets'):
            if isinstance(position_manager.managed_tickets, dict):
                position_manager.managed_tickets.pop(ticket, None)
        
        # Persist changes
        if hasattr(position_manager, '_save_state'):
            position_manager._save_state()
    
    return cleanup_ticket


# Singleton instance
_sync_manager_instance: Optional[SmartMT5SyncManager] = None
_sync_manager_lock = threading.RLock()


def get_smart_sync_manager(
    min_sync_interval_seconds: int = 300,
    track_position_changes: bool = True,
) -> SmartMT5SyncManager:
    """Get or create singleton SmartMT5SyncManager."""
    global _sync_manager_instance
    
    if _sync_manager_instance is None:
        with _sync_manager_lock:
            if _sync_manager_instance is None:
                _sync_manager_instance = SmartMT5SyncManager(
                    min_sync_interval_seconds=min_sync_interval_seconds,
                    track_position_changes=track_position_changes,
                )
    
    return _sync_manager_instance


# ===== USAGE PATTERN =====
# Instead of:
#     if position_manager and hasattr(position_manager, "sync_mt5_state"):
#         synced_positions = await position_manager.sync_mt5_state(persist=True)  # EVERY CYCLE!
#
# Use:
#     smart_sync = get_smart_sync_manager()
#     should_sync, reason = smart_sync.should_sync(portfolio.positions)
#     
#     if should_sync:
#         logger.info(f"[SYNC_TRIGGER] Reason: {reason}")
#         if position_manager and hasattr(position_manager, "sync_mt5_state"):
#             synced_positions = await position_manager.sync_mt5_state(persist=True)
#         smart_sync.mark_synced(portfolio.positions, reason=reason)
#     else:
#         logger.debug(f"[SYNC_SKIPPED] {reason} - Next sync in ~{smart_sync.min_sync_interval_seconds}s")
#
#     # Detect and clean ghost tickets
#     mt5_tickets = {str(p.position_id) for p in...}
#     local_tickets = {...}
#     ghost_tickets, analysis = smart_sync.find_ghost_tickets(mt5_tickets, local_tickets)
#     if ghost_tickets:
#         cleanup_callback = create_ghost_cleanup_callback(position_manager)
#         removed, list = smart_sync.cleanup_ghost_tickets(ghost_tickets, cleanup_callback)
#
# Expected: sync runs ~12 times/day instead of ~8640 times/day (1 per 10 sec)
