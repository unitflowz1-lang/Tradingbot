"""
CapacityGate: Emergency brake to prevent over-leveraging.

PROBLEM: Bot enters "Sniper Mode" and "Aggressive Engagement" while holding 4-5 
open positions. This leads to over-leverage, increased drawdown risk, and negative 
PnL on short entries due to slippage.

SOLUTION: Hard limit on concurrent positions. When capacity reached:
1. No new trades are admitted
2. Only reduce-only orders (exits) are allowed
3. System logs why each trade was denied

CRITICAL: Use CapacityGate.can_open_new_trade() before entering ExecutionEngine.
"""

import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone
from enum import Enum
import threading

logger = logging.getLogger(__name__)


class CapacityDenyReason(Enum):
    """Reasons why a trade was denied."""
    MAX_POSITIONS_REACHED = "max_positions_reached"
    MAX_RISK_PER_SYMBOL = "max_risk_per_symbol"
    MAX_SECTOR_EXPOSURE = "max_sector_exposure"
    EMERGENCY_SHUTDOWN = "emergency_shutdown"
    COOLING_OFF_PERIOD = "cooling_off_period"
    MAINTENANCE_MODE = "maintenance_mode"


class CapacityGate:
    """
    Hard capacity gate to prevent over-leveraging.
    
    Thread-safe via RLock.
    
    Tracks:
    1. Total concurrent positions (hard limit)
    2. Risk per symbol (prevent concentration)
    3. Sector exposure (prevent correlation)
    4. Emergency shutdown mode
    5. Cool-off periods after large losses
    """
    
    def __init__(
        self,
        max_concurrent_positions: int = 3,
        max_risk_per_symbol: float = 0.02,  # 2% account risk per symbol
        max_sector_exposure: float = 0.50,  # 50% in single sector
    ):
        """
        Initialize capacity gate.
        
        Args:
            max_concurrent_positions: Hard limit on open positions (default 3)
            max_risk_per_symbol: Max account equity at risk per symbol (default 2%)
            max_sector_exposure: Max account exposure to single sector (default 50%)
        """
        self.max_concurrent_positions = max_concurrent_positions
        self.max_risk_per_symbol = max_risk_per_symbol
        self.max_sector_exposure = max_sector_exposure
        
        self._lock = threading.RLock()
        
        # Tracking
        self._open_positions: Dict[str, Dict] = {}  # {ticket: {symbol, direction, volume, risk}}
        self._symbol_position_count: Dict[str, int] = {}  # {symbol: count}
        self._symbol_exposure_risk: Dict[str, float] = {}  # {symbol: total_risk}
        self._sector_exposure: Dict[str, float] = {}  # {sector: total_exposure}
        
        # Emergency mode
        self._emergency_shutdown = False
        self._emergency_reason = ""
        
        # Cool-off period (after large losses)
        self._cool_off_until: Optional[datetime] = None
        self._cool_off_reason = ""
        
        # Maintenance mode (for updates/rebalancing)
        self._maintenance_mode = False
        
        # Denial log
        self._denials: List[Dict] = []
        self._max_denials_logged = 100
        
        logger.info(
            "[CAPACITY_GATE_INIT] Max positions: %d | Risk/symbol: %.1f%% | Sector exposure: %.1f%%",
            max_concurrent_positions,
            max_risk_per_symbol * 100,
            max_sector_exposure * 100
        )
    
    def can_open_new_trade(
        self,
        symbol: str,
        direction: str,
        volume: float,
        risk_amount: float,
        account_equity: float,
        sector: Optional[str] = None,
    ) -> Tuple[bool, Optional[CapacityDenyReason], str]:
        """
        Check if a new trade can be opened.
        
        Returns:
            (allowed: bool, deny_reason: Optional[CapacityDenyReason], message: str)
        """
        with self._lock:
            # Check emergency shutdown
            if self._emergency_shutdown:
                return (
                    False,
                    CapacityDenyReason.EMERGENCY_SHUTDOWN,
                    f"[CAPACITY_DENIED] Emergency shutdown active: {self._emergency_reason}"
                )
            
            # Check maintenance mode
            if self._maintenance_mode:
                return (
                    False,
                    CapacityDenyReason.MAINTENANCE_MODE,
                    "[CAPACITY_DENIED] System in maintenance mode. No new trades allowed."
                )
            
            # Check cool-off period
            if self._cool_off_until is not None:
                now = datetime.now(timezone.utc)
                if now < self._cool_off_until:
                    seconds_remaining = (self._cool_off_until - now).total_seconds()
                    return (
                        False,
                        CapacityDenyReason.COOLING_OFF_PERIOD,
                        f"[CAPACITY_DENIED] Cool-off period active (%.0f seconds remaining): {self._cool_off_reason}"
                        % seconds_remaining
                    )
                else:
                    # Cool-off finished
                    self._cool_off_until = None
                    self._cool_off_reason = ""
            
            # Check max concurrent positions
            current_positions = len(self._open_positions)
            if current_positions >= self.max_concurrent_positions:
                return (
                    False,
                    CapacityDenyReason.MAX_POSITIONS_REACHED,
                    f"[CAPACITY_DENIED] {current_positions}/{self.max_concurrent_positions} positions open. "
                    f"Max capacity reached. New {symbol} {direction} trade BLOCKED."
                )
            
            # Check risk per symbol
            symbol_risk = self._symbol_exposure_risk.get(symbol, 0.0)
            new_total_risk = symbol_risk + risk_amount
            max_risk_allowed = account_equity * self.max_risk_per_symbol
            
            if new_total_risk > max_risk_allowed:
                return (
                    False,
                    CapacityDenyReason.MAX_RISK_PER_SYMBOL,
                    f"[CAPACITY_DENIED] {symbol} risk concentration too high. "
                    f"Current: ${symbol_risk:.2f} + New: ${risk_amount:.2f} > Max: ${max_risk_allowed:.2f}"
                )
            
            # Check sector exposure
            if sector is not None:
                sector_exp = self._sector_exposure.get(sector, 0.0)
                new_sector_total = sector_exp + volume
                max_sector_allowed = account_equity * self.max_sector_exposure
                
                if new_sector_total > max_sector_allowed:
                    return (
                        False,
                        CapacityDenyReason.MAX_SECTOR_EXPOSURE,
                        f"[CAPACITY_DENIED] {sector} sector over-exposed. "
                        f"Current: ${sector_exp:.2f} + New: ${volume:.2f} > Max: ${max_sector_allowed:.2f}"
                    )
            
            # All checks passed
            return (True, None, f"[CAPACITY_OK] {symbol} {direction} trade ALLOWED (load: {current_positions}/{self.max_concurrent_positions})")
    
    def register_opened_position(
        self,
        ticket: str,
        symbol: str,
        direction: str,
        volume: float,
        risk_amount: float,
        sector: Optional[str] = None,
    ) -> None:
        """
        Register a newly opened position.
        
        Args:
            ticket: Position ticket ID
            symbol: Trading symbol
            direction: "LONG" or "SHORT"
            volume: Position size
            risk_amount: Risk in dollars
            sector: Optional sector classification
        """
        with self._lock:
            self._open_positions[ticket] = {
                "symbol": symbol,
                "direction": direction,
                "volume": volume,
                "risk": risk_amount,
                "sector": sector,
                "opened_at": datetime.now(timezone.utc),
            }
            
            self._symbol_position_count[symbol] = self._symbol_position_count.get(symbol, 0) + 1
            self._symbol_exposure_risk[symbol] = self._symbol_exposure_risk.get(symbol, 0.0) + risk_amount
            
            if sector is not None:
                self._sector_exposure[sector] = self._sector_exposure.get(sector, 0.0) + volume
            
            logger.info(
                "[CAPACITY_REGISTERED] %s | Ticket: %s | Volume: %.2f | Risk: $%.2f | Load: %d/%d",
                symbol,
                ticket,
                volume,
                risk_amount,
                len(self._open_positions),
                self.max_concurrent_positions
            )
    
    def unregister_closed_position(self, ticket: str) -> None:
        """
        Unregister a closed position.
        
        Args:
            ticket: Position ticket ID
        """
        with self._lock:
            if ticket not in self._open_positions:
                return
            
            pos = self._open_positions.pop(ticket)
            symbol = pos["symbol"]
            sector = pos.get("sector")
            volume = pos["volume"]
            risk = pos.get("risk", 0.0)
            
            self._symbol_position_count[symbol] = self._symbol_position_count.get(symbol, 1) - 1
            if self._symbol_position_count[symbol] <= 0:
                self._symbol_position_count.pop(symbol, None)
            
            current_risk = self._symbol_exposure_risk.get(symbol, risk)
            self._symbol_exposure_risk[symbol] = max(0.0, current_risk - risk)
            if self._symbol_exposure_risk[symbol] <= 0:
                self._symbol_exposure_risk.pop(symbol, None)
            
            if sector is not None:
                current = self._sector_exposure.get(sector, volume)
                self._sector_exposure[sector] = max(0.0, current - volume)
                if self._sector_exposure[sector] <= 0:
                    self._sector_exposure.pop(sector, None)
            
            logger.info(
                "[CAPACITY_UNREGISTERED] %s | Ticket: %s | Load: %d/%d",
                symbol,
                ticket,
                len(self._open_positions),
                self.max_concurrent_positions
            )
    
    def trigger_emergency_shutdown(self, reason: str, duration_minutes: int = 60) -> None:
        """
        Trigger emergency shutdown (no new trades allowed).
        
        Args:
            reason: Reason for shutdown (logged)
            duration_minutes: How long until auto-recovery (default 60)
        """
        with self._lock:
            self._emergency_shutdown = True
            self._emergency_reason = reason
            
            # Auto-recovery after duration
            if duration_minutes > 0:
                from datetime import timedelta
                recovery_time = datetime.now(timezone.utc) + timedelta(minutes=duration_minutes)
                self._cool_off_until = recovery_time
            
            logger.critical(
                "[CAPACITY_EMERGENCY] Shutdown triggered: %s | Recovery in %d minutes",
                reason,
                duration_minutes
            )
    
    def clear_emergency_shutdown(self) -> None:
        """Clear emergency shutdown mode."""
        with self._lock:
            if self._emergency_shutdown:
                logger.warning(
                    "[CAPACITY_RECOVERY] Emergency shutdown cleared. "
                    "Previous reason: %s",
                    self._emergency_reason
                )
            self._emergency_shutdown = False
            self._emergency_reason = ""
    
    def trigger_cool_off_period(self, reason: str, seconds: int = 300) -> None:
        """
        Trigger cool-off period (no new trades for N seconds).
        
        Args:
            reason: Reason for cool-off (logged)
            seconds: Cool-off duration in seconds (default 300 = 5 min)
        """
        with self._lock:
            from datetime import timedelta
            self._cool_off_until = datetime.now(timezone.utc) + timedelta(seconds=seconds)
            self._cool_off_reason = reason
            
            logger.warning(
                "[CAPACITY_COOL_OFF] %d-second cool-off triggered: %s",
                seconds,
                reason
            )
    
    def set_maintenance_mode(self, enabled: bool) -> None:
        """Enable/disable maintenance mode (no new trades)."""
        with self._lock:
            self._maintenance_mode = enabled
            status = "ENABLED" if enabled else "DISABLED"
            logger.info("[CAPACITY_MAINTENANCE] Maintenance mode %s", status)
    
    def get_current_load(self) -> Dict[str, any]:
        """
        Get current capacity load status.
        
        Returns:
            Dict with load metrics
        """
        with self._lock:
            return {
                "total_positions": len(self._open_positions),
                "max_capacity": self.max_concurrent_positions,
                "capacity_used_pct": (len(self._open_positions) / self.max_concurrent_positions) * 100,
                "symbols": list(self._symbol_position_count.keys()),
                "positions_per_symbol": dict(self._symbol_position_count),
                "sectors_exposed": list(self._sector_exposure.keys()),
                "sector_exposure": dict(self._sector_exposure),
                "emergency_shutdown": self._emergency_shutdown,
                "maintenance_mode": self._maintenance_mode,
                "in_cool_off": self._cool_off_until is not None and datetime.now(timezone.utc) < self._cool_off_until,
            }
    
    def get_stats(self) -> Dict[str, any]:
        """Get statistics about capacity gating."""
        return self.get_current_load()


# Singleton instance
_capacity_gate_instance: Optional[CapacityGate] = None
_capacity_gate_lock = threading.RLock()


def get_capacity_gate(
    max_concurrent_positions: int = 3,
    max_risk_per_symbol: float = 0.02,
    max_sector_exposure: float = 0.50,
) -> CapacityGate:
    """Get or create singleton CapacityGate instance."""
    global _capacity_gate_instance
    
    if _capacity_gate_instance is None:
        with _capacity_gate_lock:
            if _capacity_gate_instance is None:
                _capacity_gate_instance = CapacityGate(
                    max_concurrent_positions=max_concurrent_positions,
                    max_risk_per_symbol=max_risk_per_symbol,
                    max_sector_exposure=max_sector_exposure,
                )
    
    return _capacity_gate_instance


# ===== USAGE PATTERN =====
# Initialize once at startup:
#     capacity_gate = get_capacity_gate(
#         max_concurrent_positions=3,
#         max_risk_per_symbol=0.02,
#     )
#
# Before entering ExecutionEngine:
#     allowed, deny_reason, message = capacity_gate.can_open_new_trade(
#         symbol=signal.symbol,
#         direction=signal.direction,
#         volume=final_lots,
#         risk_amount=potential_loss,
#         account_equity=current_balance,
#     )
#     if not allowed:
#         logger.warning(message)
#         return None  # HARD BLOCK - don't execute
#
#     # Trade allowed, register it
#     capacity_gate.register_opened_position(
#         ticket=executed_ticket,
#         symbol=signal.symbol,
#         direction=signal.direction,
#         volume=final_lots,
#         risk_amount=potential_loss,
#     )
#
# When position closes:
#     capacity_gate.unregister_closed_position(ticket)
#
# Expected: No more than 3 concurrent positions, explicit denials logged
