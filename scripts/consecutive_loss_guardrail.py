"""
Consecutive Loss Guardrail Integration Patch
=============================================
Adds consecutive loss monitoring to main.py trading loop
Triggers CRITICAL alert after 3 consecutive losses

Usage:
    Import and call check_consecutive_loss_guardrail() after each trade closes
"""

import json
import logging
from pathlib import Path
from typing import List, Dict
from collections import deque

logger = logging.getLogger(__name__)


class ConsecutiveLossGuardrail:
    """
    Monitors consecutive losses and triggers alerts
    """
    
    def __init__(self, threshold: int = 3):
        self.threshold = threshold
        self.consecutive_losses = 0
        self.max_consecutive_losses = 0
        self.total_trades = 0
        self.alert_history = deque(maxlen=100)
        
        logger.critical(f"[GUARDRAIL] Consecutive loss monitor initialized (threshold: {threshold})")
    
    def check_trade_result(self, trade_pnl: float, trade_info: Dict = None) -> bool:
        """
        Check trade result and update consecutive loss counter
        
        Args:
            trade_pnl: P&L of the closed trade
            trade_info: Optional trade metadata
        
        Returns:
            True if alert threshold reached, False otherwise
        """
        self.total_trades += 1
        
        if trade_pnl < 0:
            # Loss
            self.consecutive_losses += 1
            self.max_consecutive_losses = max(self.max_consecutive_losses, self.consecutive_losses)
            
            logger.warning(
                f"[TRADE_RESULT] Loss #{self.consecutive_losses} in a row | "
                f"P&L: ${trade_pnl:.2f} | "
                f"Total Trades: {self.total_trades}"
            )
            
            # Check if threshold reached
            if self.consecutive_losses >= self.threshold:
                self._trigger_alert()
                return True
        else:
            # Win or breakeven - reset counter
            if self.consecutive_losses > 0:
                logger.info(
                    f"[TRADE_RESULT] Winning trade breaks losing streak | "
                    f"Streak was: {self.consecutive_losses} | "
                    f"P&L: ${trade_pnl:.2f}"
                )
            self.consecutive_losses = 0
        
        return False
    
    def _trigger_alert(self):
        """
        Trigger CRITICAL alert for consecutive losses
        """
        alert_msg = (
            f"🔴🔴🔴 CRITICAL: CONSECUTIVE LOSS THRESHOLD REACHED! 🔴🔴🔴\n"
            f"Consecutive Losses: {self.consecutive_losses}\n"
            f"Threshold: {self.threshold}\n"
            f"Total Trades: {self.total_trades}\n"
            f"Max Consecutive Losses (session): {self.max_consecutive_losses}\n\n"
            f"RECOMMENDED ACTIONS:\n"
            f"1. Reduce position sizes by 50%\n"
            f"2. Increase quality floor to 80%\n"
            f"3. Review recent trade patterns\n"
            f"4. Consider pausing trading if losses continue\n"
            f"5. Check market conditions for regime changes"
        )
        
        # Log CRITICAL alert
        logger.critical(f"[CONSECUTIVE_LOSS_ALERT] {alert_msg}")
        
        # Save to critical alerts file
        alert_file = Path("logs/critical_alerts.log")
        try:
            with open(alert_file, 'a') as f:
                from datetime import datetime, timezone
                timestamp = datetime.now(timezone.utc).isoformat()
                f.write(f"{timestamp} | CONSECUTIVE_LOSS_ALERT | Losses: {self.consecutive_losses}\n")
        except Exception as e:
            logger.error(f"[GUARDRAIL] Failed to save alert: {e}")
        
        # Save alert to history
        self.alert_history.append({
            'timestamp': str(__import__('datetime').datetime.now(__import__('datetime').timezone.utc)),
            'consecutive_losses': self.consecutive_losses,
            'threshold': self.threshold,
            'total_trades': self.total_trades,
        })
    
    def get_status(self) -> Dict:
        """
        Get current guardrail status
        """
        return {
            'consecutive_losses': self.consecutive_losses,
            'max_consecutive_losses': self.max_consecutive_losses,
            'total_trades': self.total_trades,
            'threshold': self.threshold,
            'alert_triggered': self.consecutive_losses >= self.threshold,
            'recent_alerts': len(self.alert_history),
        }
    
    def reset(self):
        """
        Reset the guardrail (use with caution)
        """
        logger.warning("[GUARDRAIL] Resetting consecutive loss counter")
        self.consecutive_losses = 0


# Global instance for easy access
_guardrail_instance = None


def get_guardrail() -> ConsecutiveLossGuardrail:
    """
    Get or create global guardrail instance
    """
    global _guardrail_instance
    if _guardrail_instance is None:
        _guardrail_instance = ConsecutiveLossGuardrail(threshold=3)
    return _guardrail_instance


def check_consecutive_loss_guardrail(trade_pnl: float, trade_info: Dict = None) -> bool:
    """
    Convenience function to check consecutive losses
    
    Args:
        trade_pnl: P&L of closed trade
        trade_info: Optional trade metadata
    
    Returns:
        True if alert threshold reached
    """
    guardrail = get_guardrail()
    return guardrail.check_trade_result(trade_pnl, trade_info)


def get_guardrail_status() -> Dict:
    """
    Get current guardrail status
    """
    guardrail = get_guardrail()
    return guardrail.get_status()


if __name__ == "__main__":
    # Test the guardrail
    import sys
    logging.basicConfig(level=logging.DEBUG, format='%(levelname)s | %(message)s')
    
    guardrail = ConsecutiveLossGuardrail(threshold=3)
    
    print("\n=== Testing Consecutive Loss Guardrail ===\n")
    
    # Simulate trades
    test_trades = [
        (100.0, "Win 1"),
        (-50.0, "Loss 1"),
        (-60.0, "Loss 2"),
        (-70.0, "Loss 3 - SHOULD TRIGGER ALERT"),
        (80.0, "Win 2 - Resets counter"),
        (-40.0, "Loss 4"),
        (-50.0, "Loss 5"),
        (-60.0, "Loss 6 - SHOULD TRIGGER ALERT AGAIN"),
    ]
    
    for pnl, description in test_trades:
        print(f"\nTrade: {description} (P&L: ${pnl:.2f})")
        alert_triggered = guardrail.check_trade_result(pnl)
        if alert_triggered:
            print("🔴 ALERT TRIGGERED!")
    
    print(f"\nFinal Status: {guardrail.get_status()}")
