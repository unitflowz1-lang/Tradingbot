"""
Dynamic Profit Compression (DPC) Module - ULTIMATE PROFIT GUARD v2
-------------------------------------------------------------------
Locks in profits at milestone distances to TP and hard dollar amounts.

Features:
- Tier 1 (40% to TP): Move SL to Breakeven + Fees (Risk-Free)
- Tier 2 (70% to TP): Move SL to lock 50% of realized profit
- Tier 3 (90% to TP): Move SL to lock 80% of realized profit
- Dollar Lock Level 1 ($2.00): Lock in $0.25 (net positive after fees)
- Dollar Lock Level 2 ($5.00): Lock in $2.00 (aggressive protection)
- Dollar Lock Level 3 ($8.00): Lock in $5.00 (maximum protection)
- One-Way Ratchet: SL only moves tighter
- Broker Compliant: Works with Stops Guard and Shadow Mode
- Safety Buffer: 2-point (0.00002) maintained for all modifications
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum

import MetaTrader5 as mt5

from src.models import Direction
from src.utils.pip_standardizer import PipStandardizer

logger = logging.getLogger(__name__)


class CompressionTier(Enum):
    """Profit compression milestones - ULTIMATE PROFIT GUARD v2"""
    NONE = 0
    TIER_1 = 0.40      # 40% to TP - Breakeven + Fees (Risk Free)
    TIER_2 = 0.70      # 70% to TP - Lock 50% of profit
    TIER_3 = 0.90      # 90% to TP - Lock 80% of profit


@dataclass
class PositionCompressionState:
    """Track compression state for a single position"""
    ticket: str
    symbol: str
    direction: Direction
    entry_price: float
    tp_price: float
    current_sl: float
    commission: float = 0.0
    swap: float = 0.0
    
    # Compression tracking
    tier_1_hit: bool = False
    tier_2_hit: bool = False
    tier_3_hit: bool = False
    
    last_tier_sl: float = 0.0  # Last SL set by DPC
    compression_active: bool = False
    
    # Progressive step-lock tracking
    last_step_hit: int = 0  # Track which profit step has already tightened SL
    
    # Timestamps for tracking
    tier_1_hit_at: Optional[datetime] = None
    tier_2_hit_at: Optional[datetime] = None
    tier_3_hit_at: Optional[datetime] = None
    
    modification_history: list = field(default_factory=list)


class DynamicProfitCompressionManager:
    """Manage profit compression across multiple positions"""
    
    def __init__(self):
        self.positions: Dict[str, PositionCompressionState] = {}
        logger.info("[DPC_INIT] Dynamic Profit Compression Manager initialized")
    
    def track_position(
        self,
        ticket: str,
        symbol: str,
        direction: Direction,
        entry_price: float,
        tp_price: float,
        current_sl: float,
        commission: float = 0.0,
        swap: float = 0.0,
    ) -> None:
        """Register position for compression tracking"""
        if ticket in self.positions:
            # Update existing position
            state = self.positions[ticket]
            state.current_sl = current_sl
            state.commission = commission
            state.swap = swap
        else:
            # Create new tracking state
            state = PositionCompressionState(
                ticket=ticket,
                symbol=symbol,
                direction=direction,
                entry_price=entry_price,
                tp_price=tp_price,
                current_sl=current_sl,
                commission=commission,
                swap=swap,
            )
            self.positions[ticket] = state
            logger.debug(
                "[DPC_TRACK] %s ticket %s | Entry: %.5f, TP: %.5f, SL: %.5f",
                symbol,
                ticket,
                entry_price,
                tp_price,
                current_sl,
            )
    
    def untrack_position(self, ticket: str) -> None:
        """Remove position from tracking"""
        if ticket in self.positions:
            state = self.positions.pop(ticket)
            logger.debug(
                "[DPC_UNTRACK] %s ticket %s | Compression tiers hit: T1=%s, T2=%s, T3=%s",
                state.symbol,
                ticket,
                state.tier_1_hit,
                state.tier_2_hit,
                state.tier_3_hit,
            )
    
    def _get_pip_value(self, symbol: str) -> float:
        """Get pip value for symbol (e.g., 0.0001 for EURUSD)"""
        return PipStandardizer.get_pip_value_for_pair(symbol)
    
    def _calculate_fee_adjusted_entry(self, symbol: str, direction: Direction, entry_price: float, commission: float, swap: float) -> float:
        """Calculate Entry + (Commission + Swap) + 2 points for Tier 1 Risk-Free SL
        
        This is the "Profit Sniper" Tier 1: moves SL to exact break-even with 2-point safety buffer.
        
        Formula:
        - LONG: SL = Entry + (Commission + Swap in pips) + 2 points
        - SHORT: SL = Entry - (Commission + Swap in pips) - 2 points
        """
        # Get point value (smallest unit): 0.00001 for 5-decimal pairs
        try:
            symbol_info = mt5.symbol_info(symbol)
            point = float(getattr(symbol_info, 'point', 0.0001) or 0.0001)
        except:
            point = 0.0001  # Default for 5-decimal pairs
        
        # Convert commission and swap to price units
        fee_price = commission + abs(swap)
        
        # Add 2-point safety buffer (0.00002 for 5-decimal pairs)
        safety_buffer = 2 * point
        
        if direction == Direction.LONG:
            return entry_price + fee_price + safety_buffer
        else:
            return entry_price - fee_price - safety_buffer
    
    def _calculate_tier_sl(
        self,
        symbol: str,
        direction: Direction,
        entry_price: float,
        tp_price: float,
        current_price: float,
        tier: CompressionTier,
        commission: float,
        swap: float,
    ) -> float:
        """Calculate new SL for a given compression tier (ULTIMATE PROFIT GUARD v2)
        
        Tier 1 (40% progress to TP): SL = Breakeven + Fees + 2-point buffer
        Tier 2 (70% progress to TP): SL = Entry + (50% of current realized profit)
        Tier 3 (90% progress to TP): SL = Entry + (80% of current realized profit)
        """
        pip_value = self._get_pip_value(symbol)
        
        # Get point value
        try:
            symbol_info = mt5.symbol_info(symbol)
            point = float(getattr(symbol_info, 'point', 0.0001) or 0.0001)
        except:
            point = 0.0001
        
        # Safety buffer: 2 points (0.00002 for 5-decimal pairs)
        safety_buffer = 2 * point
        
        if direction == Direction.LONG:
            # LONG: Entry < Current < TP
            
            if tier == CompressionTier.TIER_1:
                # Tier 1 (40% to TP): Breakeven + Fees + 2-point buffer
                fee_price = commission + abs(swap)
                return entry_price + fee_price + safety_buffer
            
            elif tier == CompressionTier.TIER_2:
                # Tier 2 (70% to TP): Lock 50% of current realized profit
                realized_profit = current_price - entry_price
                locked_profit = realized_profit * 0.50
                return entry_price + locked_profit
            
            elif tier == CompressionTier.TIER_3:
                # Tier 3 (90% to TP): Lock 80% of current realized profit
                realized_profit = current_price - entry_price
                locked_profit = realized_profit * 0.80
                return entry_price + locked_profit
        
        else:  # SHORT
            # SHORT: Entry > Current > TP
            
            if tier == CompressionTier.TIER_1:
                # Tier 1 (40% to TP): Breakeven - Fees - 2-point buffer
                fee_price = commission + abs(swap)
                return entry_price - fee_price - safety_buffer
            
            elif tier == CompressionTier.TIER_2:
                # Tier 2 (70% to TP): Lock 50% of current realized profit
                realized_profit = entry_price - current_price
                locked_profit = realized_profit * 0.50
                return entry_price - locked_profit
            
            elif tier == CompressionTier.TIER_3:
                # Tier 3 (90% to TP): Lock 80% of current realized profit
                realized_profit = entry_price - current_price
                locked_profit = realized_profit * 0.80
                return entry_price - locked_profit
        
        return 0.0
    
    def _calculate_dollar_lock_sl(
        self,
        symbol: str,
        direction: Direction,
        entry_price: float,
        current_price: float,
        pip_value: float,
    ) -> Tuple[Optional[float], Optional[float], Optional[str]]:
        """
        Calculate Hard Dollar Lock SL if profit exceeds thresholds.
        
        Level 1: Profit > $2.00 → Lock in $0.25 (net positive after fees)
        Level 2: Profit > $5.00 → Lock in $2.00 (aggressive protection)
        Level 3: Profit > $8.00 → Lock in $5.00 (maximum protection)
        
        Returns:
            (new_sl, locked_amount_dollars, lock_level) or (None, None, None)
        """
        # Calculate current profit in dollars
        if direction == Direction.LONG:
            price_move = current_price - entry_price
            current_profit = price_move * pip_value * 10000  # Convert pips to dollars
        else:  # SHORT
            price_move = entry_price - current_price
            current_profit = price_move * pip_value * 10000
        
        # Check Level 3 first (highest threshold)
        if current_profit > 8.00:
            locked_amount = 5.00
            locked_pips = locked_amount / (pip_value * 10000)
            
            if direction == Direction.LONG:
                new_sl = entry_price + locked_pips
            else:
                new_sl = entry_price - locked_pips
            
            return new_sl, locked_amount, "LEVEL_3"
        
        # Check Level 2
        elif current_profit > 5.00:
            locked_amount = 2.00
            locked_pips = locked_amount / (pip_value * 10000)
            
            if direction == Direction.LONG:
                new_sl = entry_price + locked_pips
            else:
                new_sl = entry_price - locked_pips
            
            return new_sl, locked_amount, "LEVEL_2"
        
        # Check Level 1 (lowest threshold)
        elif current_profit > 2.00:
            locked_amount = 0.25
            locked_pips = locked_amount / (pip_value * 10000)
            
            if direction == Direction.LONG:
                new_sl = entry_price + locked_pips
            else:
                new_sl = entry_price - locked_pips
            
            return new_sl, locked_amount, "LEVEL_1"
        
        # No dollar lock triggered
        return None, None, None
    
    def _calculate_step_lock_sl(
        self,
        symbol: str,
        direction: Direction,
        entry_price: float,
        current_price: float,
        pip_value: float,
    ) -> Tuple[Optional[float], Optional[int], Optional[float]]:
        """
        Calculate progressive step-locking SL.
        The first step now starts at $3.00 profit to avoid tightening on tiny moves.
        
        Each step locks progressively more profit:
        - Step 2 ($3.00): Lock 30% of profit
        - Step 3 ($4.50): Lock 45% of profit
        - Step 4 ($6.00): Lock 60% of profit
        - Step 5 ($7.50): Lock 75% of profit
        - Step 6+ ($9.00+): Lock 85% of profit
        
        Returns:
            (new_sl, step_number, profit_locked_pct) or (None, None, None)
        """
        # Calculate current profit in dollars
        if direction == Direction.LONG:
            price_move = current_price - entry_price
            current_profit_dollars = price_move * pip_value * 10000
        else:  # SHORT
            price_move = entry_price - current_price
            current_profit_dollars = price_move * pip_value * 10000
        
        # Remove the early $1.50 SL move; first progressive lock now starts at $3.00.
        if current_profit_dollars < 3.00:
            return None, None, None
        
        # Calculate which step we're at
        step_number = int(current_profit_dollars / 1.50)
        
        # Determine lock percentage based on step
        if step_number >= 6:
            lock_pct = 0.85  # 85% lock at $9.00+
        elif step_number == 5:
            lock_pct = 0.75  # 75% lock at $7.50
        elif step_number == 4:
            lock_pct = 0.60  # 60% lock at $6.00
        elif step_number == 3:
            lock_pct = 0.45  # 45% lock at $4.50
        elif step_number == 2:
            lock_pct = 0.30  # 30% lock at $3.00
        else:  # step_number == 2
            lock_pct = 0.30  # 30% lock at $3.00
        
        # Calculate new SL based on locked profit percentage
        realized_profit_price = abs(price_move)
        locked_profit_price = realized_profit_price * lock_pct
        
        if direction == Direction.LONG:
            new_sl = entry_price + locked_profit_price
        else:  # SHORT
            new_sl = entry_price - locked_profit_price
        
        return new_sl, step_number, lock_pct
    
    def check_compression_tiers(
        self,
        ticket: str,
        current_price: float,
    ) -> Tuple[bool, Optional[float], Optional[CompressionTier], str]:
        """
        Check if position has hit any compression tiers.
        
        Returns:
            (should_modify, new_sl, tier_hit, log_msg)
        """
        if ticket not in self.positions:
            return False, None, None, ""
        
        state = self.positions[ticket]
        
        # Calculate distance to TP
        if state.direction == Direction.LONG:
            distance_to_tp = state.tp_price - state.entry_price
            progress = (current_price - state.entry_price) / distance_to_tp if distance_to_tp > 0 else 0.0
        else:  # SHORT
            distance_to_tp = state.entry_price - state.tp_price
            progress = (state.entry_price - current_price) / distance_to_tp if distance_to_tp > 0 else 0.0
        
        # Clamp progress to [0, 1]
        progress = max(0.0, min(1.0, progress))
        
        # FIRST: Check Hard Dollar Lock (triggers independently of progress %)
        pip_value = self._get_pip_value(state.symbol)
        dollar_sl, dollar_locked, dollar_level = self._calculate_dollar_lock_sl(
            state.symbol, state.direction, state.entry_price, current_price, pip_value
        )
        
        if dollar_sl is not None:
            # Check if dollar lock is tighter than current SL
            is_tighter = False
            if state.direction == Direction.LONG:
                is_tighter = dollar_sl > state.current_sl
            else:  # SHORT
                is_tighter = dollar_sl < state.current_sl
            
            if is_tighter:
                # Dollar lock wins - apply it
                state.last_tier_sl = dollar_sl
                state.compression_active = True
                state.current_sl = dollar_sl
                
                log_msg = (
                    f"[CASH_PROTECTED] {state.symbol} hit ${dollar_locked:.2f}. "
                    f"SL moved to lock in ${dollar_locked:.2f} ({dollar_level})."
                )
                
                state.modification_history.append({
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'tier': f'DOLLAR_LOCK_{dollar_level}',
                    'new_sl': dollar_sl,
                    'locked_amount_dollars': dollar_locked,
                    'progress_to_tp': progress,
                })
                
                return True, dollar_sl, None, log_msg
        
        # SECOND: Check progressive step-locking after the $3.00 threshold
        step_sl, step_number, step_lock_pct = self._calculate_step_lock_sl(
            state.symbol, state.direction, state.entry_price, current_price, pip_value
        )
        
        if step_sl is not None and step_number != state.last_step_hit:
            # Check if step lock is tighter than current SL
            is_tighter = False
            if state.direction == Direction.LONG:
                is_tighter = step_sl > state.current_sl
            else:  # SHORT
                is_tighter = step_sl < state.current_sl
            
            if is_tighter:
                # Step lock wins - apply it
                state.last_tier_sl = step_sl
                state.compression_active = True
                state.current_sl = step_sl
                state.last_step_hit = step_number
                
                profit_amount = step_number * 1.50
                lock_dollars = profit_amount * step_lock_pct
                
                log_msg = (
                    f"[STEP_SNIPER] {state.symbol} hit ${profit_amount:.2f} profit (Step {step_number}). "
                    f"Locked {step_lock_pct*100:.0f}% (${lock_dollars:.2f}) | SL tightened to {step_sl:.5f}"
                )
                
                state.modification_history.append({
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'tier': f'STEP_LOCK_{step_number}',
                    'new_sl': step_sl,
                    'profit_milestone': profit_amount,
                    'lock_percent': step_lock_pct * 100,
                    'locked_dollars': lock_dollars,
                })
                
                return True, step_sl, None, log_msg
        
        # THIRD: Check which percentage tier to activate (only if not already hit)
        new_tier = None
        new_sl = None
        
        if progress >= CompressionTier.TIER_3.value and not state.tier_3_hit:
            new_tier = CompressionTier.TIER_3
            new_sl = self._calculate_tier_sl(
                state.symbol, state.direction, state.entry_price, state.tp_price,
                current_price, new_tier, state.commission, state.swap
            )
        elif progress >= CompressionTier.TIER_2.value and not state.tier_2_hit:
            new_tier = CompressionTier.TIER_2
            new_sl = self._calculate_tier_sl(
                state.symbol, state.direction, state.entry_price, state.tp_price,
                current_price, new_tier, state.commission, state.swap
            )
        elif progress >= CompressionTier.TIER_1.value and not state.tier_1_hit:
            new_tier = CompressionTier.TIER_1
            new_sl = self._calculate_tier_sl(
                state.symbol, state.direction, state.entry_price, state.tp_price,
                current_price, new_tier, state.commission, state.swap
            )
        
        # No tier hit
        if new_tier is None or new_sl is None:
            return False, None, None, ""
        
        # Check One-Way Ratchet: only move SL if it's tighter than current
        is_tighter = False
        if state.direction == Direction.LONG:
            # For LONG, tighter SL means HIGHER value
            is_tighter = new_sl > state.current_sl
        else:  # SHORT
            # For SHORT, tighter SL means LOWER value
            is_tighter = new_sl < state.current_sl
        
        if not is_tighter and state.last_tier_sl > 0:
            # SL is not tighter than current; skip this tier
            return False, None, None, ""
        
        # Mark tier as hit
        lock_percent = 0
        if new_tier == CompressionTier.TIER_1:
            state.tier_1_hit = True
            state.tier_1_hit_at = datetime.now(timezone.utc)
            lock_percent = 0  # Risk-Free (Entry + Fees)
        elif new_tier == CompressionTier.TIER_2:
            state.tier_2_hit = True
            state.tier_2_hit_at = datetime.now(timezone.utc)
            lock_percent = 40  # Front-loaded protection
        elif new_tier == CompressionTier.TIER_3:
            state.tier_3_hit = True
            state.tier_3_hit_at = datetime.now(timezone.utc)
            lock_percent = 75  # Total Risk Removal
        
        # Update compression state
        state.last_tier_sl = new_sl
        state.compression_active = True
        state.current_sl = new_sl
        state.modification_history.append({
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'tier': new_tier.name,
            'new_sl': new_sl,
            'progress_to_tp': progress,
            'lock_percent': lock_percent,
        })
        
        log_msg = (
            f"[PROFIT_SNIPER] {new_tier.name} reached for {state.symbol}. "
            f"Locking in {lock_percent}% of target ({progress*100:.1f}% to TP). "
            f"SL moved to {new_sl:.5f}"
        )
        
        return True, new_sl, new_tier, log_msg
    
    def get_compression_state(self, ticket: str) -> Optional[PositionCompressionState]:
        """Get current compression state for a position"""
        return self.positions.get(ticket)
    
    def get_all_active_positions(self) -> Dict[str, PositionCompressionState]:
        """Get all tracked positions"""
        return dict(self.positions)
    
    def log_compression_summary(self) -> None:
        """Log summary of all compression states"""
        if not self.positions:
            return
        
        summary = []
        for ticket, state in self.positions.items():
            tiers = []
            if state.tier_1_hit:
                tiers.append(f"T1@{state.tier_1_hit_at.strftime('%H:%M:%S')}")
            if state.tier_2_hit:
                tiers.append(f"T2@{state.tier_2_hit_at.strftime('%H:%M:%S')}")
            if state.tier_3_hit:
                tiers.append(f"T3@{state.tier_3_hit_at.strftime('%H:%M:%S')}")
            
            tier_str = ",".join(tiers) if tiers else "NONE"
            summary.append(f"{state.symbol}#{ticket}: [{tier_str}]")
        
        logger.info(
            "[DPC_SUMMARY] Compression State | %s",
            " | ".join(summary)
        )
