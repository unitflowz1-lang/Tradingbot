"""
Auto-Rotation Engine for Elite Signal Prioritization
Implements intelligent position rotation to free slots for high-conviction opportunities
when the portfolio is at maximum capacity.

Core Logic:
- Identifies Tier-A (elite) signals: forced_execution=True OR Strategy_Score >= 90.0
- When portfolio is full and elite signal detected: triggers rotation protocol
- Selects "sacrificial trade" based on performance and stagnation criteria
- Documents rotation in telemetry for analysis
"""

import logging
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class RotationCandidate:
    """Candidate position for sacrifice during rotation"""
    position_id: int
    symbol: str
    unrealized_pnl: float
    direction: str
    entry_price: float
    current_price: float
    opened_at: datetime
    open_duration_minutes: float
    entry_r_multiple: float = 1.0  # Risk units at entry
    profit_threshold_r: float = 0.5  # 0.5R threshold for "stale" detection
    
    def is_stale(self) -> bool:
        """Check if trade is stale (open long without hitting 0.5R profit)"""
        if self.unrealized_pnl > self.entry_r_multiple * self.profit_threshold_r:
            return False  # Has hit profitability threshold
        return self.open_duration_minutes > 15 * 60  # Open > 15 mins without hitting threshold


@dataclass
class EliteSignal:
    """High-conviction trading signal eligible for rotation"""
    symbol: str
    strategy_score: float  # 0-100
    forced_execution: bool
    confidence: float  # ML confidence
    rr_ratio: float  # Risk-Reward ratio
    direction: str  # "LONG" or "SHORT"
    expected_r_multiple: Optional[float] = None
    
    @property
    def is_tier_a(self) -> bool:
        """Check if this is a Tier-A (elite) signal"""
        return self.forced_execution or self.strategy_score >= 90.0
    
    @property
    def tier_level(self) -> str:
        """Return tier classification"""
        if self.strategy_score >= 90.0:
            return "TIER_A_SCORE_90"
        elif self.forced_execution:
            return "TIER_A_FORCED"
        else:
            return "STANDARD"


@dataclass
class RotationMetrics:
    """Track rotation event metrics for telemetry"""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    elite_signal_symbol: str = ""
    elite_signal_score: float = 0.0
    sacrificed_symbol: str = ""
    sacrificed_pnl: float = 0.0
    sacrificed_hold_minutes: float = 0.0
    sacrificed_reason: str = ""  # "LOWEST_PNL", "STALE_TRADE", or combination
    rotation_success: bool = False
    execution_error: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize for logging/reporting"""
        return {
            'timestamp': self.timestamp.isoformat(),
            'elite_signal': self.elite_signal_symbol,
            'elite_score': self.elite_signal_score,
            'sacrificed': self.sacrificed_symbol,
            'sacrificed_pnl': round(self.sacrificed_pnl, 2),
            'sacrificed_hold_minutes': round(self.sacrificed_hold_minutes, 1),
            'reason': self.sacrificed_reason,
            'success': self.rotation_success,
            'error': self.execution_error
        }


class AutoRotationEngine:
    """
    Manages intelligent position rotation for elite signals.
    
    Criteria for rotation:
    1. Portfolio at MAX_POSITIONS
    2. Tier-A signal detected (forced_execution OR score >= 90)
    3. Safety: Don't close trades < 15 minutes old
    4. Selection: Lowest P&L first, then stale trades, then oldest
    """
    
    def __init__(self, max_positions: int = 6, min_position_age_minutes: int = 15):
        """
        Initialize Auto-Rotation Engine
        
        Args:
            max_positions: Maximum concurrent positions allowed
            min_position_age_minutes: Minimum age before a position can be sacrificed (safety buffer)
        """
        self.max_positions = max_positions
        self.min_position_age_minutes = min_position_age_minutes
        self.rotation_history: List[RotationMetrics] = []
        self.logger = logger
        
        # Statistics
        self.total_rotations_initiated = 0
        self.total_rotations_executed = 0
        self.total_rotations_failed = 0
        self.total_elite_signals_processed = 0
        self.sacrificial_loss_sum = 0.0
        self.elite_gains_sum = 0.0
    
    def should_rotate(self, 
                      current_positions_count: int,
                      signal: EliteSignal) -> bool:
        """
        Determine if rotation should be triggered
        
        Args:
            current_positions_count: Number of currently open positions
            signal: The incoming signal to evaluate
            
        Returns:
            True if rotation should be triggered
        """
        # Portfolio must be at capacity
        if current_positions_count < self.max_positions:
            return False
        
        # Signal must be Tier-A
        if not signal.is_tier_a:
            return False
        
        return True
    
    def select_sacrificial_candidate(self,
                                    open_positions: List[RotationCandidate],
                                    current_time: datetime = None) -> Optional[RotationCandidate]:
        """
        Select the "weakest link" position for sacrifice.
        
        Priority Order:
        1. Criterion A: Lowest unrealized P&L
        2. Criterion B: If P&L is similar, longest duration without 0.5R profit (stale)
        3. Criterion C: Safety - never sacrifice positions < 15 minutes old
        
        Args:
            open_positions: List of candidate positions to evaluate
            current_time: Reference time for age calculation (default: now)
            
        Returns:
            RotationCandidate to sacrifice, or None if no valid candidate
        """
        if not open_positions:
            return None
        
        if current_time is None:
            current_time = datetime.now(timezone.utc)
        
        # Filter out positions too young to sacrifice (safety buffer)
        eligible = []
        for pos in open_positions:
            age_minutes = (current_time - pos.opened_at).total_seconds() / 60
            pos.open_duration_minutes = age_minutes
            
            if age_minutes >= self.min_position_age_minutes:
                eligible.append(pos)
        
        if not eligible:
            self.logger.warning(
                "[ROTATION] No positions old enough to sacrifice (all < %d min). "
                "Cannot rotate.",
                self.min_position_age_minutes
            )
            return None
        
        # Sort by criteria (primary: lowest PnL, secondary: stalest, tertiary: oldest)
        def sort_key(pos: RotationCandidate) -> Tuple:
            # Primary: Lowest unrealized PnL
            pnl_score = pos.unrealized_pnl
            
            # Secondary: If PnL within 5% range, prefer stale trades
            # (positions that have been open long without hitting profit target)
            stale_score = pos.open_duration_minutes / (pos.profit_threshold_r > 0 and
                                                       pos.unrealized_pnl / pos.entry_r_multiple or 1.0)
            
            # Tertiary: Oldest first
            age_score = pos.open_duration_minutes
            
            return (pnl_score, -stale_score, -age_score)
        
        sacrificial = min(eligible, key=sort_key)
        
        return sacrificial
    
    def evaluate_rotation(self,
                         open_positions: List[RotationCandidate],
                         elite_signal: EliteSignal,
                         current_time: datetime = None) -> Tuple[bool, RotationCandidate, str]:
        """
        Evaluate if rotation is feasible and select candidate
        
        Args:
            open_positions: Current open positions
            elite_signal: The elite signal triggering potential rotation
            current_time: Current time for calculations
            
        Returns:
            (can_rotate: bool, candidate: RotationCandidate, reason: str)
        """
        # Check if rotation is triggered by this signal
        if not self.should_rotate(len(open_positions), elite_signal):
            return False, None, "Portfolio not full or signal not elite"
        
        # Try to find sacrificial candidate
        candidate = self.select_sacrificial_candidate(open_positions, current_time)
        
        if candidate is None:
            return False, None, "No eligible positions to sacrifice (all too young)"
        
        return True, candidate, "Rotation conditions met"
    
    def create_rotation_metric(self,
                               elite_signal: EliteSignal,
                               sacrificed: Optional[RotationCandidate] = None,
                               success: bool = False,
                               error: str = "") -> RotationMetrics:
        """Create a rotation event record for telemetry"""
        metric = RotationMetrics(
            elite_signal_symbol=elite_signal.symbol,
            elite_signal_score=elite_signal.strategy_score,
            sacrificed_symbol=sacrificed.symbol if sacrificed else "N/A",
            sacrificed_pnl=sacrificed.unrealized_pnl if sacrificed else 0.0,
            sacrificed_hold_minutes=sacrificed.open_duration_minutes if sacrificed else 0.0,
            sacrificed_reason=sacrificed and f"PnL: {sacrificed.unrealized_pnl:.2f} | "
                            f"Stale: {sacrificed.is_stale()}" or "N/A",
            rotation_success=success,
            execution_error=error
        )
        return metric
    
    def log_rotation_initiated(self, 
                              elite_signal: EliteSignal,
                              sacrificial: RotationCandidate):
        """Log rotation initiation in critical format for operator visibility"""
        self.total_rotations_initiated += 1
        
        self.logger.critical(
            "[ROTATION_INITIATED] Sacrificing %s (P&L: $%.2f | Age: %.1f min) "
            "to free slot for Elite Strike: %s (Score: %.1f | Tier: %s)",
            sacrificial.symbol,
            sacrificial.unrealized_pnl,
            sacrificial.open_duration_minutes,
            elite_signal.symbol,
            elite_signal.strategy_score,
            elite_signal.tier_level
        )
    
    def log_rotation_executed(self,
                             elite_signal: EliteSignal,
                             sacrificial: RotationCandidate,
                             ticket_sacrifice: Any):
        """Log successful execution"""
        self.total_rotations_executed += 1
        self.sacrificial_loss_sum += sacrificial.unrealized_pnl
        
        self.logger.critical(
            "[ROTATION_EXECUTED] Sacrificial close ticket #%s (%s, P&L: $%.2f). "
            "Elite signal %s (Score: %.1f) now prioritized for execution.",
            ticket_sacrifice,
            sacrificial.symbol,
            sacrificial.unrealized_pnl,
            elite_signal.symbol,
            elite_signal.strategy_score
        )
    
    def log_rotation_failed(self,
                           elite_signal: EliteSignal,
                           reason: str):
        """Log failed rotation attempt"""
        self.total_rotations_failed += 1
        
        self.logger.warning(
            "[ROTATION_FAILED] Could not rotate for Elite signal %s (Score: %.1f). "
            "Reason: %s",
            elite_signal.symbol,
            elite_signal.strategy_score,
            reason
        )
    
    def get_rotation_stats(self) -> Dict[str, Any]:
        """Return cumulative rotation statistics"""
        return {
            'total_initiated': self.total_rotations_initiated,
            'total_executed': self.total_rotations_executed,
            'total_failed': self.total_rotations_failed,
            'success_rate': (self.total_rotations_executed / self.total_rotations_initiated * 100
                           if self.total_rotations_initiated > 0 else 0.0),
            'sacrificial_loss_sum': round(self.sacrificial_loss_sum, 2),
            'elite_gains_sum': round(self.elite_gains_sum, 2),
            'net_rotation_impact': round(self.elite_gains_sum + self.sacrificial_loss_sum, 2),
        }
    
    def record_elite_gain(self, pnl: float):
        """Record P&L from executed elite signal for telemetry"""
        self.elite_gains_sum += pnl
