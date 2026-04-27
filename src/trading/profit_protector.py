"""
Profit Protection System
Protects profitable positions by:
1. Locking in profits at breakeven after hitting targets
2. Scaling out at profit milestones
3. Preventing drawdown from peaks
"""

import logging
import json
import os
from dataclasses import dataclass, field
from typing import Dict, Tuple, Any
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass
class PositionProfit:
    """Track profit metrics for a position"""
    position_id: str
    symbol: str
    entry_price: float
    peak_profit: float = 0.0
    peak_profit_price: float = 0.0
    peak_profit_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    breakeven_locked: bool = False
    scale_out_count: int = 0
    
    def update_peak(self, current_profit: float, current_price: float):
        """Update peak profit if new high"""
        if current_profit > self.peak_profit:
            self.peak_profit = current_profit
            self.peak_profit_price = current_price
            self.peak_profit_time = datetime.now(timezone.utc)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for persistence"""
        return {
            'position_id': self.position_id,
            'symbol': self.symbol,
            'entry_price': self.entry_price,
            'peak_profit': self.peak_profit,
            'peak_profit_price': self.peak_profit_price,
            'peak_profit_time': self.peak_profit_time.isoformat(),
            'breakeven_locked': self.breakeven_locked,
            'scale_out_count': self.scale_out_count
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PositionProfit':
        """Create from dictionary"""
        try:
            # Handle string timestamp
            if isinstance(data.get('peak_profit_time'), str):
                data['peak_profit_time'] = datetime.fromisoformat(data['peak_profit_time'])
            
            return cls(**data)
        except Exception as e:
            logger.error(f"Failed to deserialize PositionProfit: {e}")
            # Return partial or default if critical fail
            return cls(
                position_id=data.get('position_id'),
                symbol=data.get('symbol'),
                entry_price=data.get('entry_price', 0.0)
            )


class ProfitProtector:
    """Manages profit protection for active positions"""
    
    def __init__(self, 
                 breakeven_threshold: float = 50.0,
                 partial_takeprofit_threshold: float = 75.0,
                 max_drawdown_from_peak: float = 20.0,
                 scale_out_percents: list = None,
                 state_file: str = "profit_protector_state.json"):
        """
        Initialize profit protector
        
        Args:
            breakeven_threshold: Profit needed to lock breakeven ($)
            partial_takeprofit_threshold: Profit for partial TP ($)
            max_drawdown_from_peak: Max loss from peak before closing ($)
            scale_out_percents: Percentages to scale out at [50%, 75%, 100%]
            state_file: File path for state persistence
        """
        self.positions: Dict[str, PositionProfit] = {}
        self.breakeven_threshold = breakeven_threshold
        self.partial_takeprofit_threshold = partial_takeprofit_threshold
        self.max_drawdown_from_peak = max_drawdown_from_peak
        self.scale_out_percents = scale_out_percents or [0.50, 0.75, 1.00]  # 50%, 75%, 100%
        self.state_file = state_file
        
        # Load state on startup
        self.load_state()
        
    def save_state(self):
        """Save current state to file"""
        try:
            data = {pid: p.to_dict() for pid, p in self.positions.items()}
            # Write to temp file first then rename for atomic write
            temp_file = self.state_file + ".tmp"
            with open(temp_file, 'w') as f:
                json.dump(data, f, indent=2)
            
            # Atomic rename (replace)
            if os.path.exists(self.state_file):
                os.remove(self.state_file)
            os.rename(temp_file, self.state_file)
            
        except Exception as e:
            logger.error(f"Failed to save ProfitProtector state: {e}")

    def load_state(self):
        """Load state from file"""
        if not os.path.exists(self.state_file):
            return
            
        try:
            with open(self.state_file, 'r') as f:
                data = json.load(f)
                
            self.positions = {}
            for pid, p_data in data.items():
                self.positions[pid] = PositionProfit.from_dict(p_data)
                
            logger.info(f"Loaded ProfitProtector state: {len(self.positions)} positions")
        except Exception as e:
            logger.error(f"Failed to load ProfitProtector state: {e}")
            
    def track_position(self, position_id: str, symbol: str, entry_price: float):
        """Start tracking a new position"""
        if position_id not in self.positions:
            self.positions[position_id] = PositionProfit(
                position_id=position_id,
                symbol=symbol,
                entry_price=entry_price
            )
            self.save_state()
    
    def update_position(self, position_id: str, current_profit: float, current_price: float):
        """Update position's current profit"""
        if position_id not in self.positions:
            return
        
        pos = self.positions[position_id]
        if current_profit > pos.peak_profit:
            pos.update_peak(current_profit, current_price)
            # Only save on meaningful updates (new peak)
            self.save_state()
    
    def should_lock_breakeven(self, position_id: str, current_profit: float) -> bool:
        """
        Check if position should lock breakeven
        
        Returns True if:
        - Profit >= breakeven threshold
        - Breakeven not already locked
        """
        if position_id not in self.positions:
            return False
        
        pos = self.positions[position_id]
        
        if not pos.breakeven_locked and current_profit >= self.breakeven_threshold:
            pos.breakeven_locked = True
            logger.info(
                f"[BREAKEVEN LOCK] {pos.symbol}: Locking at entry price "
                f"(peak profit: ${pos.peak_profit:.2f}, current: ${current_profit:.2f})"
            )
            self.save_state()
            return True
        
        return False
    
    def should_scale_out(self, position_id: str, current_profit: float) -> Tuple[bool, int]:
        """
        Check if position should scale out
        
        Returns (should_scale_out, scale_out_percent)
        """
        if position_id not in self.positions:
            return False, 0
        
        pos = self.positions[position_id]
        
        # Only scale out if we have peak profit to reference
        if pos.peak_profit <= 0:
            return False, 0
        
        # Check each scale-out level
        should_save = False
        result = (False, 0)
        
        if pos.scale_out_count == 0 and current_profit >= pos.peak_profit * 0.5:
            pos.scale_out_count = 1
            result = (True, 50)  # Close 50% at 50% of peak profit
            should_save = True
        
        elif pos.scale_out_count == 1 and current_profit >= pos.peak_profit * 0.75:
            pos.scale_out_count = 2
            result = (True, 50)  # Close another 50% at 75% of peak profit
            should_save = True
            
        if should_save:
            self.save_state()
            
        return result
    
    def should_take_profit(self, position_id: str, current_profit: float) -> bool:
        """
        Check if position should close due to profit protection
        
        Returns True if profit drops significantly from peak
        """
        if position_id not in self.positions:
            return False
        
        pos = self.positions[position_id]
        
        # Only protect if we had peak profit
        if pos.peak_profit <= 0:
            return False
        
        # Calculate drawdown from peak
        drawdown_from_peak = pos.peak_profit - current_profit
        
        # Close if drawdown exceeds threshold
        if drawdown_from_peak >= self.max_drawdown_from_peak:
            logger.info(
                f"[PROFIT PROTECTION] {pos.symbol}: Peak ${pos.peak_profit:.2f} "
                f"dropped to ${current_profit:.2f} (${drawdown_from_peak:.2f} loss), closing"
            )
            return True
        
        return False
    
    def get_protection_status(self, position_id: str) -> Dict:
        """Get current protection status of a position"""
        if position_id not in self.positions:
            return {}
        
        pos = self.positions[position_id]
        return {
            'position_id': position_id,
            'symbol': pos.symbol,
            'peak_profit': pos.peak_profit,
            'breakeven_locked': pos.breakeven_locked,
            'scale_out_count': pos.scale_out_count,
            'peak_profit_time': pos.peak_profit_time.isoformat()
        }
    
    def close_position(self, position_id: str):
        """Remove position from tracking when closed"""
        if position_id in self.positions:
            pos = self.positions[position_id]
            logger.debug(f"[PROFIT TRACKING] Closed: {pos.symbol} (peak: ${pos.peak_profit:.2f})")
            del self.positions[position_id]
            self.save_state()
    
    def get_summary(self) -> Dict:
        """Get summary of all tracked positions"""
        total_peak_profit = sum(p.peak_profit for p in self.positions.values())
        locked_count = sum(1 for p in self.positions.values() if p.breakeven_locked)
        
        return {
            'tracked_positions': len(self.positions),
            'total_peak_profit': total_peak_profit,
            'breakeven_locked_count': locked_count,
            'positions': {pid: self.get_protection_status(pid) for pid in self.positions}
        }
