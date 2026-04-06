"""
Position Direction Management
Tracks and manages LONG and SHORT positions separately with analytics
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Tuple
from datetime import datetime, timezone
from enum import Enum

logger = logging.getLogger(__name__)


class PositionType(Enum):
    """Position direction type"""
    LONG = "LONG"
    SHORT = "SHORT"


@dataclass
class DirectionStats:
    """Statistics for a position direction (LONG or SHORT)"""
    direction: PositionType
    total_positions: int = 0
    open_positions: int = 0
    total_unrealized_pnl: float = 0.0
    total_realized_pnl: float = 0.0
    winners: int = 0
    losers: int = 0
    total_profit: float = 0.0
    total_loss: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    win_rate: float = 0.0  # percentage
    # ===== FIX #5: SWAP/COMMISSION TRACKING =====
    total_swap_cost: float = 0.0  # Financing costs for open positions
    total_commission: float = 0.0  # Trading commissions
    # ===== FIX #7: SPREAD COST TRACKING =====
    total_spread_cost: float = 0.0  # Bid-ask spread costs at entry
    
    def calculate_metrics(self):
        """Calculate derived metrics"""
        if self.total_positions > 0:
            self.win_rate = (self.winners / self.total_positions) * 100
        
        if self.winners > 0:
            self.avg_win = self.total_profit / self.winners
        
        if self.losers > 0:
            self.avg_loss = self.total_loss / self.losers
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        self.calculate_metrics()
        return {
            'direction': self.direction.value,
            'total_positions': self.total_positions,
            'open_positions': self.open_positions,
            'unrealized_pnl': self.total_unrealized_pnl,
            'realized_pnl': self.total_realized_pnl,
            'winners': self.winners,
            'losers': self.losers,
            'win_rate': f"{self.win_rate:.1f}%",
            'total_profit': self.total_profit,
            'total_loss': self.total_loss,
            'largest_win': self.largest_win,
            'largest_loss': self.largest_loss,
            'avg_win': self.avg_win,
            'avg_loss': self.avg_loss,
            # ===== FIX #5: SWAP/COMMISSION DATA =====
            'total_swap_cost': self.total_swap_cost,
            'total_commission': self.total_commission,
            'net_pnl_after_costs': self.total_unrealized_pnl - self.total_swap_cost - self.total_commission,
            # ===== FIX #7: SPREAD COST IN SUMMARY =====
            'total_spread_cost': self.total_spread_cost,
            'total_all_costs': self.total_swap_cost + self.total_commission + self.total_spread_cost,
            'net_pnl_including_spread': self.total_unrealized_pnl - self.total_swap_cost - self.total_commission - self.total_spread_cost
        }


class PositionDirectionTracker:
    """Tracks LONG vs SHORT positions with separate analytics"""
    
    def __init__(self):
        """Initialize direction tracker"""
        self.long_positions: Dict[str, any] = {}
        self.short_positions: Dict[str, any] = {}
        self.long_stats = DirectionStats(PositionType.LONG)
        self.short_stats = DirectionStats(PositionType.SHORT)
        self.history: List[Dict] = []
    
    def classify_position(self, position) -> PositionType:
        """Classify a position as LONG or SHORT"""
        from src.models import Direction
        
        if position.direction == Direction.LONG:
            return PositionType.LONG
        else:
            return PositionType.SHORT
    
    def add_position(self, position_id: str, symbol: str, direction, quantity: float, entry_price: float):
        """Track a new open position"""
        # Determine position type from direction
        if hasattr(direction, 'value'):  # It's an enum
            if "LONG" in str(direction.value).upper():
                position_type = PositionType.LONG
            else:
                position_type = PositionType.SHORT
        else:  # It's a string
            position_type = PositionType.LONG if "LONG" in str(direction).upper() else PositionType.SHORT
        
        # ===== FIX #5: SWAP/COMMISSION TRACKING =====
        position_data = {
            'position_id': position_id,
            'symbol': symbol,
            'quantity': quantity,
            'entry_price': entry_price,
            'direction': position_type,
            'swap_cost': 0.0,  # Will be updated as position ages
            'commission': 0.0,  # Entry and exit commission
            'spread_cost': 0.0,  # ===== FIX #7: SPREAD COST AT ENTRY =====
            'total_cost': 0.0  # swap + commission + spread
        }
        
        if position_type == PositionType.LONG:
            self.long_positions[position_id] = position_data
            self.long_stats.open_positions += 1
            self.long_stats.total_positions += 1
        else:
            self.short_positions[position_id] = position_data
            self.short_stats.open_positions += 1
            self.short_stats.total_positions += 1
        
        logger.info(
            f"[POSITION CALL] {position_type.value} | {symbol} | "
            f"Entry: {entry_price:.5f} | Qty: {quantity:.2f}"
        )
    
    def close_position(self, position_id: str, symbol: str, direction, quantity: float, unrealized_pnl: float):
        """Update stats when position is closed"""
        # Determine position type from direction
        if hasattr(direction, 'value'):  # It's an enum
            if "LONG" in str(direction.value).upper():
                position_type = PositionType.LONG
            else:
                position_type = PositionType.SHORT
        else:  # It's a string
            position_type = PositionType.LONG if "LONG" in str(direction).upper() else PositionType.SHORT
        
        if position_type == PositionType.LONG:
            if position_id in self.long_positions:
                del self.long_positions[position_id]
            self.long_stats.open_positions = max(0, self.long_stats.open_positions - 1)
            stats = self.long_stats
        else:
            if position_id in self.short_positions:
                del self.short_positions[position_id]
            self.short_stats.open_positions = max(0, self.short_stats.open_positions - 1)
            stats = self.short_stats
        
        # Update PnL statistics
        if unrealized_pnl > 0:
            stats.winners += 1
            stats.total_profit += unrealized_pnl
            stats.largest_win = max(stats.largest_win, unrealized_pnl)
        elif unrealized_pnl < 0:
            stats.losers += 1
            stats.total_loss += abs(unrealized_pnl)
            stats.largest_loss = min(stats.largest_loss, unrealized_pnl)
        
        logger.info(
            f"[POSITION CLOSED] {position_type.value} | {symbol} | "
            f"P&L: ${unrealized_pnl:.2f}"
        )
    
    def update_unrealized_pnl(self, portfolio):
        """
        Sync internal state with actual portfolio positions and update PnL.
        This ensures tracker always matches MT5, even after restart.
        """
        if not portfolio:
             return
             
        # Broker (MT5) is the source of truth. If MT5 reports no open positions,
        # force-clear local state to prevent phantom-memory drift.
        if not portfolio.positions and (self.long_positions or self.short_positions):
            stale_count = len(self.long_positions) + len(self.short_positions)
            logger.critical(
                "[TRACKER_SYNC_GUARD] MT5 reports 0 positions but tracker has %d. "
                "Executing HARD RESET with broker as source-of-truth.",
                stale_count,
            )
            self.long_positions = {}
            self.short_positions = {}
            self.long_stats.open_positions = 0
            self.short_stats.open_positions = 0
            self.long_stats.total_unrealized_pnl = 0.0
            self.short_stats.total_unrealized_pnl = 0.0
            return

        # Reset current open position tracking (source of truth is portfolio)
        self.long_positions = {}
        self.short_positions = {}

        
        long_pnl = 0.0
        short_pnl = 0.0
        long_count = 0
        short_count = 0
        
        # Sync from current portfolio
        for pos in portfolio.positions:
             # Determine type safely
             pos_type = self.classify_position(pos)
             
             # Create position dict for compatibility
             pos_data = {
                 'position_id': pos.position_id,
                 'symbol': pos.symbol,
                 'quantity': pos.quantity,
                 'entry_price': pos.entry_price,
                 'direction': pos_type,
                 'unrealized_pnl': pos.unrealized_pnl
             }
             
             if pos_type == PositionType.LONG:
                 self.long_positions[pos.position_id] = pos_data
                 long_pnl += pos.unrealized_pnl
                 long_count += 1
             else:
                 self.short_positions[pos.position_id] = pos_data
                 short_pnl += pos.unrealized_pnl
                 short_count += 1
                 
        # Update live stats
        self.long_stats.total_unrealized_pnl = long_pnl
        self.long_stats.open_positions = long_count
        # Note: We don't overwrite total_positions as that tracks session history
        
        self.short_stats.total_unrealized_pnl = short_pnl
        self.short_stats.open_positions = short_count
    
    def get_position_summary(self) -> Dict:
        """Get summary of all positions by direction"""
        # Stats are updated via update_unrealized_pnl in main loop
        
        return {
            'long': self.long_stats.to_dict(),
            'short': self.short_stats.to_dict(),
            'total_open': (self.long_stats.open_positions + self.short_stats.open_positions),
            'total_unrealized': (
                self.long_stats.total_unrealized_pnl + 
                self.short_stats.total_unrealized_pnl
            ),
            'long_count': self.long_stats.open_positions,
            'short_count': self.short_stats.open_positions
        }
    
    def get_long_positions(self) -> List:
        """Get all open LONG positions"""
        return list(self.long_positions.values())
    
    def get_short_positions(self) -> List:
        """Get all open SHORT positions"""
        return list(self.short_positions.values())
    
    def get_long_symbols(self) -> List[str]:
        """Get symbols with open LONG positions"""
        return list(set(p['symbol'] for p in self.get_long_positions()))
    
    def get_short_symbols(self) -> List[str]:
        """Get symbols with open SHORT positions"""
        return list(set(p['symbol'] for p in self.get_short_positions()))
    
    def update_position_costs(self, position_id: str, swap_cost: float = 0.0, commission: float = 0.0):
        """
        ===== FIX #5: UPDATE SWAP AND COMMISSION COSTS =====
        Update swap and commission costs for a position.
        
        Args:
            position_id: Position identifier
            swap_cost: Financing cost (negative for costs, positive for credits)
            commission: Trading commission paid
        """
        # Find and update position
        if position_id in self.long_positions:
            self.long_positions[position_id]['swap_cost'] = swap_cost
            self.long_positions[position_id]['commission'] = commission
            self.long_positions[position_id]['total_cost'] = swap_cost + commission + self.long_positions[position_id].get('spread_cost', 0.0)
            self.long_stats.total_swap_cost += swap_cost
            self.long_stats.total_commission += commission
        elif position_id in self.short_positions:
            self.short_positions[position_id]['swap_cost'] = swap_cost
            self.short_positions[position_id]['commission'] = commission
            self.short_positions[position_id]['total_cost'] = swap_cost + commission + self.short_positions[position_id].get('spread_cost', 0.0)
            self.short_stats.total_swap_cost += swap_cost
            self.short_stats.total_commission += commission
    
    def update_position_spread_cost(self, position_id: str, spread_cost: float = 0.0):
        """
        ===== FIX #7: UPDATE SPREAD COST FOR A POSITION =====
        Update the spread cost at entry for a position.
        
        Args:
            position_id: Position identifier
            spread_cost: Cost of bid-ask spread at entry
        """
        if position_id in self.long_positions:
            self.long_positions[position_id]['spread_cost'] = spread_cost
            self.long_positions[position_id]['total_cost'] = (
                self.long_positions[position_id].get('swap_cost', 0.0) +
                self.long_positions[position_id].get('commission', 0.0) +
                spread_cost
            )
            self.long_stats.total_spread_cost += spread_cost
        elif position_id in self.short_positions:
            self.short_positions[position_id]['spread_cost'] = spread_cost
            self.short_positions[position_id]['total_cost'] = (
                self.short_positions[position_id].get('swap_cost', 0.0) +
                self.short_positions[position_id].get('commission', 0.0) +
                spread_cost
            )
            self.short_stats.total_spread_cost += spread_cost
    
    
    def get_direction_for_symbol(self, symbol: str) -> Tuple[int, int]:
        """Get count of LONG and SHORT positions for a symbol"""
        long_count = sum(1 for p in self.long_positions.values() if p['symbol'] == symbol)
        short_count = sum(1 for p in self.short_positions.values() if p['symbol'] == symbol)
        return long_count, short_count
    
    def get_net_exposure(self) -> Dict[str, float]:
        """Get net exposure by symbol (LONG qty - SHORT qty)"""
        exposure = {}
        
        # Add LONG exposures
        for position in self.long_positions.values():
            sym = position['symbol']
            exposure[sym] = exposure.get(sym, 0) + position['quantity']
        
        # Subtract SHORT exposures
        for position in self.short_positions.values():
            sym = position['symbol']
            exposure[sym] = exposure.get(sym, 0) - position['quantity']
        
        return exposure
    
    def log_direction_summary(self):
        """Log a detailed summary of LONG vs SHORT positions"""
        summary = self.get_position_summary()
        
        logger.info(
            f"[LONG POSITIONS] Count: {summary['long_count']} | "
            f"Win Rate: {summary['long']['win_rate']} | "
            f"Gross P&L: ${summary['long']['unrealized_pnl']:.2f} | "
            f"Spread: ${summary['long'].get('total_spread_cost', 0.0):.2f} | "
            f"Swap: ${summary['long'].get('total_swap_cost', 0.0):.2f} | "
            f"Commission: ${summary['long'].get('total_commission', 0.0):.2f} | "
            f"Net P&L: ${summary['long'].get('net_pnl_including_spread', summary['long']['unrealized_pnl']):.2f}"
        )
        
        logger.info(
            f"[SHORT POSITIONS] Count: {summary['short_count']} | "
            f"Win Rate: {summary['short']['win_rate']} | "
            f"Gross P&L: ${summary['short']['unrealized_pnl']:.2f} | "
            f"Spread: ${summary['short'].get('total_spread_cost', 0.0):.2f} | "
            f"Swap: ${summary['short'].get('total_swap_cost', 0.0):.2f} | "
            f"Commission: ${summary['short'].get('total_commission', 0.0):.2f} | "
            f"Net P&L: ${summary['short'].get('net_pnl_including_spread', summary['short']['unrealized_pnl']):.2f}"
        )
        
        total_swap = summary['long'].get('total_swap_cost', 0.0) + summary['short'].get('total_swap_cost', 0.0)
        total_commission = summary['long'].get('total_commission', 0.0) + summary['short'].get('total_commission', 0.0)
        total_spread = summary['long'].get('total_spread_cost', 0.0) + summary['short'].get('total_spread_cost', 0.0)
        total_net_pnl = summary['total_unrealized'] - total_swap - total_commission - total_spread
        
        logger.info(
            f"[POSITION STATS] Total Open: {summary['total_open']} | "
            f"Total Unr PnL: ${summary['total_unrealized']:.2f} (Gross) | "
            f"Spread Cost: ${total_spread:.2f} | "
            f"Swap Cost: ${total_swap:.2f} | "
            f"Commission: ${total_commission:.2f} | "
            f"NET PnL: ${total_net_pnl:.2f} (After All Costs)"
        )
    
    def get_directional_risk_info(self) -> Dict:
        """Get risk information by direction"""
        long_unrealized = self.long_stats.total_unrealized_pnl
        short_unrealized = self.short_stats.total_unrealized_pnl
        total = long_unrealized + short_unrealized
        
        return {
            'long': {
                'count': self.long_stats.open_positions,
                'unrealized_pnl': long_unrealized,
                'percentage_of_portfolio': (long_unrealized / total * 100) if total != 0 else 0
            },
            'short': {
                'count': self.short_stats.open_positions,
                'unrealized_pnl': short_unrealized,
                'percentage_of_portfolio': (short_unrealized / total * 100) if total != 0 else 0
            }
        }
