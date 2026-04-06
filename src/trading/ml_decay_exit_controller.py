"""
ML Decay Exit Controller
Prevents micro-exits triggered by momentary confidence drops.
Implements MIN_HOLD_TIME threshold and rolling confidence window.

FIX #3: MICRO-CHURNING VIA ML_DECAY - Prevents high-spread bleed
"""

import logging
from typing import Dict, Optional, List
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from collections import deque

logger = logging.getLogger(__name__)


@dataclass
class MLConfidenceState:
    """Tracks ML confidence for a single position"""
    ticket: int
    symbol: str
    opened_at: datetime
    opening_ml_confidence: float
    
    # Confidence tracking
    confidence_history: deque = field(default_factory=lambda: deque(maxlen=10))
    last_confidence: float = 0.0
    confidence_drop_count: int = 0
    
    # Hold time tracking
    min_hold_time_seconds: int = 180  # 3 minutes default
    
    def add_confidence_reading(self, confidence: float):
        """Record a confidence reading"""
        self.confidence_history.append(confidence)
        self.last_confidence = confidence
    
    def get_hold_time_seconds(self) -> float:
        """Get seconds trade has been held"""
        elapsed = datetime.now(timezone.utc) - self.opened_at
        return elapsed.total_seconds()
    
    def is_past_min_hold_time(self) -> bool:
        """Check if minimum hold time has elapsed"""
        return self.get_hold_time_seconds() >= self.min_hold_time_seconds
    
    def get_avg_confidence_over_window(self, window_size: int = 5) -> float:
        """Get average confidence over last N readings"""
        if not self.confidence_history:
            return 0.0
        
        recent = list(self.confidence_history)[-window_size:]
        return sum(recent) / len(recent) if recent else 0.0
    
    def is_sustained_low_confidence(
        self,
        threshold: float = 0.05,
        required_readings: int = 5
    ) -> bool:
        """
        Check if confidence has been LOW for N consecutive readings.
        
        Args:
            threshold: Confidence level to consider "low" (e.g., 0.05 = 5%)
            required_readings: Number of consecutive readings required
            
        Returns:
            True if last N readings are all below threshold
        """
        if len(self.confidence_history) < required_readings:
            return False
        
        recent = list(self.confidence_history)[-required_readings:]
        return all(conf < threshold for conf in recent)


class MLDecayExitController:
    """
    Controls ML-based exits with patience and smoothing.
    Prevents churning from single momentary confidence drops.
    """
    
    def __init__(
        self,
        min_hold_time_minutes: int = 3,
        enable_decay_exits: bool = True,
        ml_confidence_threshold: float = 0.05,
        sustained_low_readings_required: int = 5
    ):
        """
        Args:
            min_hold_time_minutes: Minimum hold time before ML decay can trigger (default 3 min)
            enable_decay_exits: Enable/disable ML decay exits
            ml_confidence_threshold: Confidence level to consider "low"
            sustained_low_readings_required: How many consecutive low readings trigger exit
        """
        self.min_hold_time_minutes = min_hold_time_minutes
        self.min_hold_time_seconds = min_hold_time_minutes * 60
        self.enable_decay_exits = enable_decay_exits
        self.ml_confidence_threshold = ml_confidence_threshold
        self.sustained_low_readings_required = sustained_low_readings_required
        
        # State tracking per position
        self.ml_states: Dict[int, MLConfidenceState] = {}
        
        # Statistics
        self.total_eval_count = 0
        self.prevented_exits = 0
        self.approved_exits = 0
    
    def register_position(
        self,
        ticket: int,
        symbol: str,
        opening_ml_confidence: float,
        opened_at: datetime
    ):
        """Register a new position for ML decay tracking"""
        self.ml_states[ticket] = MLConfidenceState(
            ticket=ticket,
            symbol=symbol,
            opened_at=opened_at,
            opening_ml_confidence=opening_ml_confidence,
            min_hold_time_seconds=self.min_hold_time_seconds
        )
        logger.info(
            f"[ML_DECAY_CTRL] Registered #{ticket} {symbol} "
            f"(ML conf: {opening_ml_confidence:.1%})"
        )
    
    def should_trigger_ml_decay_exit(
        self,
        ticket: int,
        symbol: str,
        current_ml_confidence: float
    ) -> tuple:
        """
        Evaluate if ML decay exit should trigger.
        
        Args:
            ticket: Position ticket
            symbol: Currency pair
            current_ml_confidence: Current ML confidence (0.0-1.0)
            
        Returns:
            (should_exit: bool, reason: str, details: dict)
        """
        self.total_eval_count += 1
        
        # Check if tracking this position
        if ticket not in self.ml_states:
            return False, "Not tracked", {}
        
        if not self.enable_decay_exits:
            return False, "ML decay exits disabled", {}
        
        state = self.ml_states[ticket]
        state.add_confidence_reading(current_ml_confidence)
        
        # ===== FIX #3A: MIN_HOLD_TIME CHECK =====
        if not state.is_past_min_hold_time():
            hold_time = state.get_hold_time_seconds()
            self.prevented_exits += 1
            return False, "Below minimum hold time", {
                'hold_time_seconds': hold_time,
                'min_required_seconds': self.min_hold_time_seconds,
                'deficit_seconds': self.min_hold_time_seconds - hold_time
            }
        
        # ===== FIX #3B: SUSTAINED LOW CONFIDENCE CHECK =====
        if not state.is_sustained_low_confidence(
            threshold=self.ml_confidence_threshold,
            required_readings=self.sustained_low_readings_required
        ):
            return False, "Confidence drop not sustained", {
                'current_confidence': current_ml_confidence,
                'threshold': self.ml_confidence_threshold,
                'readings_required': self.sustained_low_readings_required,
                'recent_readings': list(state.confidence_history)
            }
        
        # ===== ALL CHECKS PASSED: APPROVE EXIT =====
        self.approved_exits += 1
        
        details = {
            'hold_time_seconds': state.get_hold_time_seconds(),
            'opening_confidence': state.opening_ml_confidence,
            'current_confidence': current_ml_confidence,
            'confidence_decay_pct': (state.opening_ml_confidence - current_ml_confidence) * 100,
            'avg_confidence_window': state.get_avg_confidence_over_window(),
            'confidence_readings': list(state.confidence_history)
        }
        
        logger.info(
            f"[ML_DECAY_EXIT_APPROVED] #{ticket} {symbol} | "
            f"Held {details['hold_time_seconds']:.0f}s, "
            f"Confidence {state.opening_ml_confidence:.1%} → {current_ml_confidence:.1%}"
        )
        
        return True, "Sustained low confidence + min hold time met", details
    
    def unregister_position(self, ticket: int):
        """Remove position from tracking (position closed)"""
        if ticket in self.ml_states:
            del self.ml_states[ticket]
    
    def get_controller_stats(self) -> Dict:
        """Get controller statistics"""
        return {
            'total_evaluations': self.total_eval_count,
            'prevented_exits': self.prevented_exits,
            'approved_exits': self.approved_exits,
            'tracked_positions': len(self.ml_states),
            'prevented_exit_pct': (
                self.prevented_exits / self.total_eval_count * 100
                if self.total_eval_count > 0 else 0
            )
        }


# ============================================================================
# Quick Reference: Integration Pattern
# ============================================================================

if __name__ == "__main__":
    print("""
    Integration Pattern in main.py:
    
    # 1. Initialize
    ml_decay_controller = MLDecayExitController(
        min_hold_time_minutes=3,
        enable_decay_exits=True,
        ml_confidence_threshold=0.05,
        sustained_low_readings_required=5
    )
    
    # 2. When entering trade
    ml_decay_controller.register_position(
        ticket=execution_result.ticket,
        symbol=signal.symbol,
        opening_ml_confidence=signal.ml_confidence,
        opened_at=datetime.now(timezone.utc)
    )
    
    # 3. Before dynamic exit
    should_exit, reason, details = ml_decay_controller.should_trigger_ml_decay_exit(
        ticket=position.ticket,
        symbol=position.symbol,
        current_ml_confidence=current_ml_confidence
    )
    
    if should_exit:
        # Close position via market order
        pass
    
    # 4. When position closes
    ml_decay_controller.unregister_position(ticket)
    
    # 5. Monitor stats
    stats = ml_decay_controller.get_controller_stats()
    """)
