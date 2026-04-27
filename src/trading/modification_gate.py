"""
Trade Modification Gate
Prevents API spam by enforcing minimum modification distances.
Ensures SL/TP changes are only sent if movement exceeds threshold.

FIX #4: API MODIFICATION SPAM - Stop-Loss Tightening
"""

import logging
from typing import Dict, Optional, Tuple
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class ModificationType(Enum):
    """Type of modification"""
    STOP_LOSS = "SL"
    TAKE_PROFIT = "TP"
    BOTH = "SL_TP"


@dataclass
class ModificationProposal:
    """Proposed SL/TP modification"""
    ticket: int
    symbol: str
    current_sl: float
    proposed_sl: float
    current_tp: float
    proposed_tp: float
    modification_type: ModificationType
    reason: str  # e.g., "TRAILING_STOP", "MACRO_SHIELD"
    
    def get_sl_distance_pips(self, pip_value: float = 0.0001) -> float:
        """Get SL change distance in pips"""
        if self.current_sl == 0:
            return 0.0
        return abs(self.proposed_sl - self.current_sl) / pip_value
    
    def get_tp_distance_pips(self, pip_value: float = 0.0001) -> float:
        """Get TP change distance in pips"""
        if self.current_tp == 0:
            return 0.0
        return abs(self.proposed_tp - self.current_tp) / pip_value


class ModificationGate:
    """
    Gate that validates modifications before submission to broker.
    Prevents spam and reduces rate-limit risk.
    """
    
    def __init__(
        self,
        min_sl_step_pips: float = 2.0,
        min_tp_step_pips: float = 2.0,
        modification_cooldown_seconds: int = 300
    ):
        """
        Args:
            min_sl_step_pips: Minimum SL movement (pips) to send API request
            min_tp_step_pips: Minimum TP movement (pips) to send API request
            modification_cooldown_seconds: Minimum seconds between modifications (per position)
        """
        self.min_sl_step_pips = min_sl_step_pips
        self.min_tp_step_pips = min_tp_step_pips
        self.modification_cooldown_seconds = modification_cooldown_seconds
        
        # Last modification per ticket
        self.last_modification_time: Dict[int, datetime] = {}
        self.modification_history: Dict[int, list] = {}
        
        # Statistics
        self.proposals_evaluated = 0
        self.proposals_approved = 0
        self.proposals_blocked_step = 0
        self.proposals_blocked_cooldown = 0
    
    def evaluate_modification(
        self,
        proposal: ModificationProposal,
        pip_value: float = 0.0001
    ) -> Tuple[bool, str, Dict]:
        """
        Evaluate if modification should proceed.
        
        Args:
            proposal: Proposed modification
            pip_value: Pip value for the symbol (0.01 for JPY, 0.0001 for others)
            
        Returns:
            (should_send: bool, reason: str, details: dict)
        """
        self.proposals_evaluated += 1
        ticket = proposal.ticket
        
        # ===== CHECK 1: MODIFICATION COOLDOWN =====
        if ticket in self.last_modification_time:
            time_since_last = (
                datetime.now(timezone.utc) - self.last_modification_time[ticket]
            ).total_seconds()
            
            if time_since_last < self.modification_cooldown_seconds:
                self.proposals_blocked_cooldown += 1
                return False, "Modification cooldown active", {
                    'reason': 'COOLDOWN',
                    'time_since_last_seconds': time_since_last,
                    'cooldown_seconds': self.modification_cooldown_seconds,
                    'wait_remaining_seconds': (
                        self.modification_cooldown_seconds - time_since_last
                    )
                }
        
        # ===== CHECK 2: MINIMUM SL STEP =====
        if proposal.modification_type in [ModificationType.STOP_LOSS, ModificationType.BOTH]:
            if proposal.current_sl in (None, 0, 0.0) and proposal.proposed_sl not in (None, 0, 0.0):
                sl_distance = self.min_sl_step_pips
            else:
                sl_distance = proposal.get_sl_distance_pips(pip_value)
            
            if sl_distance < self.min_sl_step_pips:
                self.proposals_blocked_step += 1
                return False, "SL movement below minimum step", {
                    'reason': 'INSUFFICIENT_SL_STEP',
                    'current_sl': proposal.current_sl,
                    'proposed_sl': proposal.proposed_sl,
                    'distance_pips': sl_distance,
                    'min_distance_pips': self.min_sl_step_pips,
                    'deficit_pips': self.min_sl_step_pips - sl_distance
                }
        
        # ===== CHECK 3: MINIMUM TP STEP =====
        if proposal.modification_type in [ModificationType.TAKE_PROFIT, ModificationType.BOTH]:
            if proposal.current_tp in (None, 0, 0.0) and proposal.proposed_tp not in (None, 0, 0.0):
                tp_distance = self.min_tp_step_pips
            else:
                tp_distance = proposal.get_tp_distance_pips(pip_value)
            
            if tp_distance < self.min_tp_step_pips:
                self.proposals_blocked_step += 1
                return False, "TP movement below minimum step", {
                    'reason': 'INSUFFICIENT_TP_STEP',
                    'current_tp': proposal.current_tp,
                    'proposed_tp': proposal.proposed_tp,
                    'distance_pips': tp_distance,
                    'min_distance_pips': self.min_tp_step_pips,
                    'deficit_pips': self.min_tp_step_pips - tp_distance
                }
        
        # ===== ALL CHECKS PASSED: APPROVE =====
        self.proposals_approved += 1
        
        # Record modification
        if ticket not in self.modification_history:
            self.modification_history[ticket] = []
        
        self.modification_history[ticket].append({
            'timestamp': datetime.now(timezone.utc),
            'type': proposal.modification_type.value,
            'reason': proposal.reason,
            'sl_distance_pips': proposal.get_sl_distance_pips(pip_value),
            'tp_distance_pips': proposal.get_tp_distance_pips(pip_value)
        })
        
        self.last_modification_time[ticket] = datetime.now(timezone.utc)
        
        logger.info(
            f"[MODIFICATION_APPROVED] #{ticket} {proposal.symbol} | "
            f"Type: {proposal.modification_type.value} | "
            f"Reason: {proposal.reason}"
        )
        
        return True, "Modification approved", {
            'reason': 'APPROVED',
            'sl_distance_pips': proposal.get_sl_distance_pips(pip_value),
            'tp_distance_pips': proposal.get_tp_distance_pips(pip_value)
        }
    
    def cleanup_ticket(self, ticket: int):
        """Clean up tracking for closed position"""
        if ticket in self.last_modification_time:
            del self.last_modification_time[ticket]
        if ticket in self.modification_history:
            del self.modification_history[ticket]
    
    def get_gate_stats(self) -> Dict:
        """Get gate statistics"""
        blocked_total = self.proposals_blocked_step + self.proposals_blocked_cooldown
        
        return {
            'proposals_evaluated': self.proposals_evaluated,
            'proposals_approved': self.proposals_approved,
            'proposals_blocked_total': blocked_total,
            'proposals_blocked_step': self.proposals_blocked_step,
            'proposals_blocked_cooldown': self.proposals_blocked_cooldown,
            'approval_rate_pct': (
                self.proposals_approved / self.proposals_evaluated * 100
                if self.proposals_evaluated > 0 else 0
            ),
            'tracked_positions': len(self.last_modification_time)
        }


# ============================================================================
# Quick Reference: Integration Pattern
# ============================================================================

if __name__ == "__main__":
    print("""
    Integration Pattern in main.py:
    
    from src.trading.modification_gate import ModificationGate, ModificationProposal, ModificationType
    from src.utils.pip_standardizer import PipStandardizer
    
    # 1. Initialize
    modification_gate = ModificationGate(
        min_sl_step_pips=2.0,
        min_tp_step_pips=2.0,
        modification_cooldown_seconds=300
    )
    
    # 2. Replace this OLD CODE (BUGGY):
    # ========================================
    # if new_sl < current_sl:
    #     trade_modify = mt5.TradeModify(...)
    #     mt5.trade_send(trade_modify)
    
    # 3. With this NEW CODE (FIXED):
    # ========================================
    proposal = ModificationProposal(
        ticket=position.ticket,
        symbol=position.symbol,
        current_sl=position.sl,
        proposed_sl=new_sl,
        current_tp=position.tp,
        proposed_tp=position.tp,
        modification_type=ModificationType.STOP_LOSS,
        reason="MACRO_SHIELD"
    )
    
    pip_value = PipStandardizer.get_pip_value_for_pair(symbol)
    should_send, reason, details = modification_gate.evaluate_modification(
        proposal,
        pip_value=pip_value
    )
    
    if should_send:
        trade_modify = mt5.TradeModify(
            ticket=position.ticket,
            sl=new_sl,
            tp=position.tp
        )
        result = mt5.trade_send(trade_modify)
    else:
        logger.debug(f"[BLOCKED] {reason}: {details}")
    
    # 4. When position closes
    modification_gate.cleanup_ticket(position.ticket)
    
    # 5. Monitor stats
    stats = modification_gate.get_gate_stats()
    logger.info(f"Approved: {stats['proposals_approved']}, Blocked: {stats['proposals_blocked_total']}")
    """)
