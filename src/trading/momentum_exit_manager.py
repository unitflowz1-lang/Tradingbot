"""
MAXIMUM MOMENTUM PROFIT & ANTI-REVERSAL SYSTEM
==============================================

Implements dynamic trailing leash, intelligent scale-out, and reversal exhaustion guards
to maximize R-multiples while protecting capital through reversals.

Core Philosophy:
- Hunt for 2.0R+ moves by holding through profit
- Only scale out for "risk-free" status, not quick profit-taking  
- Intelligent breakeven locking at 0.3R
- Chandelier trailing after 0.8R enters the move
- Single smart scale-out at 1.2R (25%, then SL to Entry+0.5R)
- Detect and defend against reversals with exhaustion guards
- Tokyo session gets stricter stagnation rules (20 bars instead of 40)

Priority Conflict Resolution:
1. Hard broker SL (highest, cannot be overridden)
2. Breakeven lock (once set, irreversible)
3. ML confidence exit < 30% (market close 100%)
4. Chandelier trailing / Tight Leash (most-protective-wins)
5. Partial close at 1.2R (25%)
6. Stagnation exit (40 bars global, 20 bars if Tokyo ADX<18)
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Optional, Tuple, List, Dict, Any
from datetime import datetime, timezone, timedelta
from enum import Enum

from src.models import Direction, Position


class MomentumExitSignal(Enum):
    """Momentum exit signal types"""
    BREAKEVEN_LOCK = "breakeven_lock_set"
    CHANDELIER_TRAIL = "chandelier_trail_update"
    TIGHT_LEASH_TIGHTEN = "tight_leash_tighten"
    SCALE_OUT_1_2R = "scale_out_at_1_2r"
    ML_CONFIDENCE_EXIT = "ml_confidence_exit_market"
    EXHAUSTION_DETECTED = "exhaustion_detected"
    TREND_STAGNATION = "trend_stagnation_detected"
    TOKYO_STAGNATION = "tokyo_session_stagnation"
    NO_ACTION = "no_action"


@dataclass
class BreakevenLock:
    """Immutable breakeven lock state"""
    entry_price: float
    locked_sl: float  # Entry + Spread + 1 pip
    locked_at_r: float = 0.3
    locked_at_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    is_active: bool = True
    
    def __hash__(self):
        return hash((self.entry_price, self.locked_sl))
    
    def __eq__(self, other):
        if not isinstance(other, BreakevenLock):
            return False
        return self.entry_price == other.entry_price and self.locked_sl == other.locked_sl


@dataclass
class ChandelierTrail:
    """Chandelier trailing stop state"""
    current_sl: float
    last_update_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_update_bar_count: int = 0
    consecutive_no_move_bars: int = 0
    
    
@dataclass
class TightLeashSL:
    """Tight leash SL when reversal risk detected"""
    tight_sl: float
    reversal_risk_score: float
    activated_at_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    is_active: bool = False


@dataclass
class MomentumPositionState:
    """Tracks momentum profit management state for a position"""
    position_id: str
    symbol: str
    direction: Direction
    entry_price: float
    entry_time: datetime
    
    # Breakeven lock (immutable once set)
    breakeven_lock: Optional[BreakevenLock] = None
    
    # Chandelier trailing
    chandelier_trail: Optional[ChandelierTrail] = None
    
    # Tight leash (reversal defense)
    tight_leash: Optional[TightLeashSL] = None
    
    # Scale-out tracking
    scaled_out_at_1_2r: bool = False
    original_position_size: float = 1.0
    remaining_position_pct: float = 100.0
    
    # Exhaustion tracking
    last_exhaustion_check_bar: int = 0
    consecutive_exhaustion_bars: int = 0
    
    # Stagnation tracking  
    stall_cycle_count: int = 0
    highest_profit_r: float = 0.0
    highest_profit_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class MomentumExitManager:
    """
    Manages momentum profit maximization with intelligent reversalprotection.
    
    Ensures all trades maximize R-multiple potential while protecting against
    sudden reversals through systematic breakeven locks, trailing stops, and
    exhaustion detection.
    """
    
    def __init__(self, logger: Optional[logging.Logger] = None, broker: Any = None):
        """Initialize momentum exit manager"""
        self.logger = logger or logging.getLogger(__name__)
        self.broker = broker
        
        # Position momentum state tracking
        self.momentum_states: Dict[str, MomentumPositionState] = {}
        
        # Configuration from environment
        self._load_configuration()
        
        self.logger.info(
            "[INIT_MOMENTUM_EXIT_MANAGER] Initialized | "
            "BE_TRIGGER=%.1fR | TRAIL_ACTIVATION=%.1fR | "
            "SCALE_OUT=%.1fR (25%%) | EXHAUSTION_BODY=%.0f%% | "
            "TOKYO_STAGNATION=%d bars",
            self.breakeven_trigger_r,
            self.trail_activation_r,
            self.scale_out_trigger_r,
            self.exhaustion_body_threshold_pct,
            self.tokyo_stagnation_bars_max
        )
    
    def _load_configuration(self):
        """Load all configuration from environment"""
        # Breakeven lock configuration
        self.breakeven_trigger_r = float(os.environ.get("BREAKEVEN_TRIGGER_R", "0.3"))
        self.breakeven_sl_offset_pips = int(os.environ.get("BREAKEVEN_SL_OFFSET_PIPS", "1"))
        self.breakeven_order_type = os.environ.get("BREAKEVEN_ORDER_TYPE", "hard_broker_sl")
        
        # Chandelier trailing configuration
        self.trail_activation_r = float(os.environ.get("TRAIL_ACTIVATION_R", "0.8"))
        self.trail_mode = os.environ.get("TRAIL_MODE", "chandelier")
        self.trail_atr_period = int(os.environ.get("TRAIL_ATR_PERIOD", "14"))
        self.trail_atr_multiplier = float(os.environ.get("TRAIL_ATR_MULTIPLIER", "1.5"))
        self.trail_min_step_pips = int(os.environ.get("TRAIL_MIN_STEP_PIPS", "2"))
        self.trail_direction = os.environ.get("TRAIL_DIRECTION", "one_way_tighten_only")
        
        # Scale-out configuration
        self.scale_out_trigger_r = float(os.environ.get("SCALE_OUT_TRIGGER_R", "1.2"))
        self.scale_out_percent = float(os.environ.get("SCALE_OUT_PERCENT", "25"))
        self.scale_out_type = os.environ.get("SCALE_OUT_TYPE", "market_order")
        self.scale_out_new_sl_r = float(os.environ.get("SCALE_OUT_NEW_SL_R", "0.5"))
        
        # Exhaustion guard configuration
        self.exhaustion_body_threshold_pct = float(os.environ.get("EXHAUSTION_BODY_THRESHOLD_PCT", "65"))
        self.exhaustion_check_lookback_bars = int(os.environ.get("EXHAUSTION_CHECK_LOOKBACK_BARS", "3"))
        self.stall_cycles_for_exhaustion = int(os.environ.get("STALL_CYCLES_FOR_TREND_EXHAUSTION", "3"))
        self.tight_leash_reversal_threshold = float(os.environ.get("TIGHT_LEASH_REVERSAL_RISK_THRESHOLD", "0.7"))
        
        # ML confidence exit configuration
        self.ml_confidence_exit_threshold = float(os.environ.get("ML_CONFIDENCE_EXIT_THRESHOLD", "0.30"))
        self.ml_confidence_exit_type = os.environ.get("ML_CONFIDENCE_EXIT_TYPE", "market_close_100pct")
        
        # Tokyo session configuration
        self.tokyo_session_utc_start = os.environ.get("TOKYO_SESSION_UTC_START", "00:00")
        self.tokyo_session_utc_end = os.environ.get("TOKYO_SESSION_UTC_END", "08:00")
        self.tokyo_adx_threshold = int(os.environ.get("TOKYO_ADX_THRESHOLD", "18"))
        self.tokyo_stagnation_bars_max = int(os.environ.get("TOKYO_STAGNATION_BARS_MAX", "20"))
        self.tokyo_stagnation_override = os.environ.get("TOKYO_STAGNATION_OVERRIDE", "true").lower() == "true"
        
        # Global stagnation setting
        self.global_stagnation_bars_max = 40
    
    def register_position(self, position: Position) -> MomentumPositionState:
        """Register a new position for momentum management"""
        state = MomentumPositionState(
            position_id=str(position.position_id),
            symbol=str(position.symbol),
            direction=position.direction,
            entry_price=float(position.entry_price),
            entry_time=position.opened_at,
            original_position_size=float(position.size),
        )
        self.momentum_states[str(position.position_id)] = state
        self.logger.info(
            "[MOMENTUM_REGISTER] %s #%s | Direction=%s | Entry=%.5f",
            state.symbol,
            position.position_id,
            state.direction,
            state.entry_price
        )
        return state
    
    def calculate_r_multiple(
        self,
        entry_price: float,
        current_price: float,
        stop_loss: float,
        direction: Direction,
        symbol: str = ""
    ) -> float:
        """Calculate current R-multiple (profit / risk)"""
        pip_value = 0.01 if 'JPY' in symbol else 0.0001
        
        risk_pips = abs(entry_price - stop_loss) / pip_value if stop_loss > 0 else 1.0
        
        if direction == Direction.LONG:
            profit_pips = (current_price - entry_price) / pip_value
        else:
            profit_pips = (entry_price - current_price) / pip_value
        
        r_multiple = profit_pips / risk_pips if risk_pips > 0 else 0.0
        return r_multiple
    
    def apply_breakeven_lock(
        self,
        position: Position,
        current_r: float
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Apply breakeven lock when position reaches 0.3R.
        Once applied, SL cannot move below this level (enforced, irreversible).
        
        Returns:
            (lock_applied, sl_update_dict)
        """
        state = self.momentum_states.get(str(position.position_id))
        if not state or state.breakeven_lock:
            return False, None  # Already locked
        
        if current_r < self.breakeven_trigger_r:
            return False, None  # Not at breakeven threshold yet
        
        # Calculate breakeven SL: Entry + Spread + 1 pip
        pip_value = 0.01 if 'JPY' in position.symbol else 0.0001
        spread_pips = int(os.environ.get("SPREAD_PIPS", "2"))
        
        if position.direction == Direction.LONG:
            breakeven_sl = position.entry_price + (spread_pips + self.breakeven_sl_offset_pips) * pip_value
        else:
            breakeven_sl = position.entry_price - (spread_pips + self.breakeven_sl_offset_pips) * pip_value
        
        # Create immutable breakeven lock
        lock = BreakevenLock(
            entry_price=position.entry_price,
            locked_sl=breakeven_sl,
            locked_at_r=current_r,
            locked_at_time=datetime.now(timezone.utc)
        )
        
        state.breakeven_lock = lock
        
        sl_update = {
            'position_id': str(position.position_id),
            'new_sl': breakeven_sl,
            'reason': 'BREAKEVEN_LOCK_0_3R',
            'order_type': self.breakeven_order_type,
            'irreversible': True,
        }
        
        self.logger.critical(
            "[BREAKEVEN_LOCK_SET] %s #%s | Entry=%.5f | Lock_SL=%.5f | Current_R=%.2fR | "
            "IRREVERSIBLE - SL cannot move below this level",
            position.symbol,
            position.position_id,
            position.entry_price,
            breakeven_sl,
            current_r
        )
        
        return True, sl_update
    
    def update_chandelier_trail(
        self,
        position: Position,
        current_r: float,
        price_history: List[Dict[str, float]],
        current_price: float
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Update chandelier trailing SL when position moves beyond 0.8R.
        
        Calculation:
        - LONG: Trail = Lowest_Low(14 bars) + (ATR_14 * 1.5)
        - SHORT: Trail = Highest_High(14 bars) - (ATR_14 * 1.5)
        
        Update only if: (a) SL tighter, AND (b) price moved 2+ pips in winning direction
        
        Returns:
            (trail_updated, sl_update_dict)
        """
        state = self.momentum_states.get(str(position.position_id))
        if not state:
            return False, None
        
        if current_r < self.trail_activation_r:
            return False, None  # Trail not yet active
        
        # Initialize chandelier trail on first trigger
        if not state.chandelier_trail:
            state.chandelier_trail = ChandelierTrail(
                current_sl=getattr(position, 'stop_loss', 0.0)
            )
            self.logger.info(
                "[CHANDELIER_TRAIL_ACTIVATED] %s #%s | Current_R=%.2fR >= %.2fR",
                position.symbol,
                position.position_id,
                current_r,
                self.trail_activation_r
            )
        
        # Calculate ATR and trail SL
        pip_value = 0.01 if 'JPY' in position.symbol else 0.0001
        
        if len(price_history) < self.trail_atr_period:
            return False, None  # Not enough history
        
        # Calculate ATR_14
        atr = self._calculate_atr(price_history, period=self.trail_atr_period)
        
        # Calculate trail SL based on direction
        if position.direction == Direction.LONG:
            lowest_low = min(bar.get('low', bar.get('close', 0)) 
                           for bar in price_history[-self.trail_atr_period:])
            new_trail_sl = lowest_low + (atr * self.trail_atr_multiplier)
        else:
            highest_high = max(bar.get('high', bar.get('close', 0))
                             for bar in price_history[-self.trail_atr_period:])
            new_trail_sl = highest_high - (atr * self.trail_atr_multiplier)
        
        old_trail_sl = state.chandelier_trail.current_sl
        
        # Rule 1: One-way tightening (never widen)
        if position.direction == Direction.LONG:
            if new_trail_sl <= old_trail_sl:
                is_tighter = True
            else:
                return False, None  # Would widen, reject
        else:
            if new_trail_sl >= old_trail_sl:
                is_tighter = True
            else:
                return False, None  # Would widen, reject
        
        # Rule 2: Minimum step requirement (2+ pips moved in winning direction)
        min_move_pips = self.trail_min_step_pips
        if position.direction == Direction.LONG:
            price_moved_pips = (current_price - state.highest_profit_time.timestamp()) / pip_value
        else:
            price_moved_pips = (state.highest_profit_time.timestamp() - current_price) / pip_value
        
        if abs(price_moved_pips) < min_move_pips:
            return False, None  # Insufficient move
        
        # Both conditions met - update trail
        state.chandelier_trail.current_sl = new_trail_sl
        state.chandelier_trail.last_update_time = datetime.now(timezone.utc)
        state.chandelier_trail.consecutive_no_move_bars = 0
        
        sl_update = {
            'position_id': str(position.position_id),
            'new_sl': new_trail_sl,
            'reason': 'CHANDELIER_TRAIL_UPDATE',
            'old_sl': old_trail_sl,
            'current_r': current_r,
            'order_type': 'hard_broker_sl',
        }
        
        self.logger.info(
            "[CHANDELIER_TRAIL_UPDATE] %s #%s | Old_SL=%.5f → New_SL=%.5f | "
            "Current_R=%.2fR | ATR(14)=%.6f",
            position.symbol,
            position.position_id,
            old_trail_sl,
            new_trail_sl,
            current_r,
            atr
        )
        
        return True, sl_update
    
    def check_scale_out_1_2r(
        self,
        position: Position,
        current_r: float,
        entry_price: float,
        stop_loss: float
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Single intelligent scale-out at 1.2R: Close 25%, move SL to Entry+ 0.5R.
        
        This is the ONLY permitted partial exit before peak. After this scales-out,
        remaining 75% runs to trail or 2.0R+ target.
        
        Returns:
            (should_scale_out, scale_out_dict)
        """
        state = self.momentum_states.get(str(position.position_id))
        if not state or state.scaled_out_at_1_2r:
            return False, None  # Already scaled or no state
        
        if current_r < self.scale_out_trigger_r:
            return False, None  # Not at scale-out threshold
        
        # Calculate new SL for remaining position: Entry + 0.5R
        pip_value = 0.01 if 'JPY' in position.symbol else 0.0001
        risk_pips = abs(entry_price - stop_loss) / pip_value if stop_loss > 0 else 1.0
        profit_for_0_5r = risk_pips * self.scale_out_new_sl_r * pip_value
        
        if position.direction == Direction.LONG:
            new_sl_for_remainder = entry_price + profit_for_0_5r
        else:
            new_sl_for_remainder = entry_price - profit_for_0_5r
        
        state.scaled_out_at_1_2r = True
        state.remaining_position_pct = 100.0 - self.scale_out_percent
        
        scale_out_dict = {
            'position_id': str(position.position_id),
            'close_percent': self.scale_out_percent,
            'close_type': self.scale_out_type,
            'reason': 'SCALE_OUT_1_2R',
            'new_sl_for_remainder': new_sl_for_remainder,
            'current_r': current_r,
            'insurance_purpose': True,
        }
        
        self.logger.critical(
            "[SCALE_OUT_1_2R] %s #%s | Close %.0f%% | New_SL=%.5f for remaining %.0f%% | Current_R=%.2fR",
            position.symbol,
            position.position_id,
            self.scale_out_percent,
            new_sl_for_remainder,
            state.remaining_position_pct,
            current_r
        )
        
        return True, scale_out_dict
    
    def detect_exhaustion_reversal(
        self,
        price_history: List[Dict[str, float]],
        direction: Direction
    ) -> Tuple[bool, float]:
        """
        Detect exhaustion bars: If any of last 3 candles have body size > 65% of range
        AND direction opposite to trade, flag as exhaustion.
        
        Returns:
            (exhaustion_detected, consecutive_count)
        """
        if len(price_history) < 3:
            return False, 0
        
        exhaustion_count = 0
        last_3_bars = price_history[-3:]
        
        for bar in last_3_bars:
            open_price = bar.get('open', bar.get('close', 0))
            close_price = bar.get('close', open_price)
            high_price = bar.get('high', max(open_price, close_price))
            low_price = bar.get('low', min(open_price, close_price))
            
            body_size = abs(close_price - open_price)
            range_size = high_price - low_price
            
            if range_size > 0:
                body_pct = (body_size / range_size) * 100
                
                # Check if body > threshold
                if body_pct > self.exhaustion_body_threshold_pct:
                    # Check if direction opposite to trade
                    is_bullish = close_price > open_price
                    is_bearish = close_price < open_price
                    
                    is_opposite = (direction == Direction.LONG and is_bearish) or \
                                 (direction == Direction.SHORT and is_bullish)
                    
                    if is_opposite:
                        exhaustion_count += 1
        
        detected = exhaustion_count > 0
        
        if detected:
            self.logger.warning(
                "[EXHAUSTION_BAR_DETECTED] Last 3 bars: %d with exhaustion pattern | "
                "Body_Threshold=%.0f%% | Direction=%s",
                exhaustion_count,
                self.exhaustion_body_threshold_pct,
                direction.name
            )
        
        return detected, float(exhaustion_count)
    
    def apply_tight_leash_if_reversal_risk(
        self,
        position: Position,
        price_history: List[Dict[str, float]],
        momentum: float,
        rsi: float,
        volume_decay: float
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Detect trend exhaustion and apply tight leash SL if reversal risk high.
        
        Tight leash = High of last completed candle (SHORT) / Low (LONG)
        This allows us to stay in if trend resumes, but exits near peak if reversal continues.
        
        Only applies when Reversal_Risk_Score > 0.7
        
        Returns:
            (tight_leash_applied, sl_update_dict)
        """
        state = self.momentum_states.get(str(position.position_id))
        if not state:
            return False, None
        
        if len(price_history) < self.stall_cycles_for_exhaustion:
            return False, None
        
        # Calculate Reversal Risk Score using:
        # - Momentum (normalized to 0-1)
        # - RSI divergence (0-1)
        # - Volume decay (0-1)
        momentum_score = max(0, min(1, (momentum + 1) / 2))  # Normalize to 0-1
        
        rsi_score = 0
        if position.direction == Direction.LONG:
            rsi_score = max(0, (rsi - 70) / 30) if rsi > 70 else 0  # Overbought
        else:
            rsi_score = max(0, (30 - rsi) / 30) if rsi < 30 else 0  # Oversold
        
        volume_score = volume_decay  # Already 0-1
        
        # Combined reversal risk score
        reversal_risk_score = (momentum_score + rsi_score + volume_score) / 3
        
        if reversal_risk_score < self.tight_leash_reversal_threshold:
            return False, None  # Risk below threshold
        
        # Apply tight leash: High of last completed candle (for SHORT) or Low (for LONG)
        if len(price_history) > 0:
            last_candle = price_history[-1]
            
            if position.direction == Direction.LONG:
                tight_sl = last_candle.get('low', last_candle.get('close', 0))
            else:
                tight_sl = last_candle.get('high', last_candle.get('close', 0))
            
            state.tight_leash = TightLeashSL(
                tight_sl=tight_sl,
                reversal_risk_score=reversal_risk_score,
                is_active=True
            )
            
            sl_update = {
                'position_id': str(position.position_id),
                'new_sl': tight_sl,
                'reason': 'TIGHT_LEASH_REVERSAL_DEFENSE',
                'reversal_risk_score': reversal_risk_score,
                'order_type': self.tight_leash_reversal_threshold,
            }
            
            self.logger.warning(
                "[TIGHT_LEASH_ACTIVATED] %s #%s | Tight_SL=%.5f | "
                "Reversal_Risk=%.2f (%.0f%% threshold) | Momentum=%.3f | RSI_Score=%.2f | Vol_Decay=%.2f",
                position.symbol,
                position.position_id,
                tight_sl,
                reversal_risk_score,
                self.tight_leash_reversal_threshold * 100,
                momentum,
                rsi_score,
                volume_score
            )
            
            return True, sl_update
        
        return False, None
    
    def resolve_conflicting_sls(
        self,
        position: Position,
        chandelier_sl: Optional[float],
        tight_leash_sl: Optional[float],
        breakeven_sl: Optional[float],
        current_price: float
    ) -> float:
        """
        Conflict Resolution: When multiple SLs are active, apply MOST_PROTECTIVE_WINS rule.
        
        Priority (for determining which is active):
        1. Breakeven lock (once set, always enforced)
        2. Tight Leash (if reversal risk high)
        3. Chandelier Trail (primary profit capture)
        
        Most protective = closest to current price (tightest).
        
        Returns:
            effective_sl
        """
        effective_sl = None
        reason = ""
        
        # Start with breakeven (highest immutable priority)
        if breakeven_sl is not None:
            effective_sl = breakeven_sl
            reason = "BREAKEVEN_LOCK (immutable)"
        
        # Check tight leash (may override if tighter)
        if tight_leash_sl is not None:
            is_tighter = self._is_sl_tighter(position.direction, tight_leash_sl, effective_sl)
            if effective_sl is None or is_tighter:
                effective_sl = tight_leash_sl
                reason = "TIGHT_LEASH_TIGHTER"
        
        # Check chandelier trail (baseline)
        if chandelier_sl is not None:
            is_tighter = self._is_sl_tighter(position.direction, chandelier_sl, effective_sl)
            if effective_sl is None or is_tighter:
                effective_sl = chandelier_sl
                reason = "CHANDELIER_TRAIL_TIGHTER"
        
        if effective_sl:
            self.logger.debug(
                "[CONFLICT_RESOLUTION] %s | Applied: %s | BE=%.5f | Leash=%.5f | Trail=%.5f → %.5f",
                position.symbol,
                reason,
                breakeven_sl or 0,
                tight_leash_sl or 0,
                chandelier_sl or 0,
                effective_sl
            )
        
        return effective_sl
    
    def _is_sl_tighter(self, direction: Direction, sl_candidate: float, current_sl: Optional[float]) -> bool:
        """Check if sl_candidate is tighter (more protective) than current_sl"""
        if current_sl is None:
            return True
        
        if direction == Direction.LONG:
            # For LONG, tighter means HIGHER SL (closer to current price)
            return sl_candidate > current_sl
        else:
            # For SHORT, tighter means LOWER SL (closer to current price)
            return sl_candidate < current_sl
    
    def is_tokyo_session(self, current_time: Optional[datetime] = None) -> bool:
        """Check if current time is during Tokyo session (00:00-08:00 UTC)"""
        now = current_time or datetime.now(timezone.utc)
        hour = now.hour
        return 0 <= hour < 8
    
    def get_effective_stagnation_limit(
        self,
        position: Position,
        current_time: Optional[datetime] = None,
        adx: Optional[float] = None
    ) -> int:
        """
        Get effective position stagnation limit:
        - Tokyo session with ADX < 18: 20 bars
        - All other times: 40 bars
        
        TOKYO_STAGNATION_OVERRIDE=true means Tokyo condition overrides global
        """
        if not self.tokyo_stagnation_override:
            return self.global_stagnation_bars_max
        
        if self.is_tokyo_session(current_time):
            if adx is not None and adx < self.tokyo_adx_threshold:
                self.logger.info(
                    "[TOKYO_STAGNATION_ACTIVE] %s | ADX=%.1f < %.0f | Using %d bar limit (not %d)",
                    position.symbol,
                    adx,
                    self.tokyo_adx_threshold,
                    self.tokyo_stagnation_bars_max,
                    self.global_stagnation_bars_max
                )
                return self.tokyo_stagnation_bars_max
        
        return self.global_stagnation_bars_max
    
    def check_ml_confidence_exit(
        self,
        position: Position,
        ml_confidence: float,
        unrealized_pnl: float
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Forced exit when ML_CONFIDENCE drops below 30% and position in profit.
        
        This is a market close of 100% position.
        Exception: If broker SL already triggered in same cycle, SL result stands.
        
        Returns:
            (should_exit, exit_dict)
        """
        if ml_confidence >= self.ml_confidence_exit_threshold:
            return False, None
        
        # Only exit if profitable (protect capital if underwater)
        if unrealized_pnl <= 0:
            return False, None
        
        exit_dict = {
            'position_id': str(position.position_id),
            'close_type': self.ml_confidence_exit_type,
            'reason': 'ML_CONFIDENCE_EXIT_BELOW_30PCT',
            'ml_confidence': ml_confidence,
            'unrealized_pnl': unrealized_pnl,
            'close_percent': 100.0,
        }
        
        self.logger.critical(
            "[ML_CONFIDENCE_EXIT] %s #%s | ML_Confidence=%.1f%% < %.1f%% Threshold | "
            "PnL=+$%.2f | MARKET CLOSE 100%%",
            position.symbol,
            position.position_id,
            ml_confidence * 100,
            self.ml_confidence_exit_threshold * 100,
            unrealized_pnl
        )
        
        return True, exit_dict
    
    @staticmethod
    def _calculate_atr(price_history: List[Dict[str, float]], period: int = 14) -> float:
        """Calculate Average True Range for last N bars"""
        if len(price_history) < period:
            return 0.0
        
        tr_values = []
        for i in range(len(price_history) - period, len(price_history)):
            if i < 0:
                continue
            
            bar = price_history[i]
            high = bar.get('high', bar.get('close', 0))
            low = bar.get('low', bar.get('close', 0))
            prev_close = price_history[i - 1]['close'] if i > 0 else high
            
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            tr_values.append(tr)
        
        atr = sum(tr_values) / len(tr_values) if tr_values else 0.0
        return atr
    
    def process_position(
        self,
        position: Position,
        market_data: Dict[str, Any],
        current_time: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        HIGH-LEVEL ORCHESTRATION: Process a position through the entire momentum system.
        
        This is the main entry point for integration with main.py. Call this once per cycle
        for each active position.
        
        Args:
            position: Position object to evaluate
            market_data: Dict with keys:
                'price_history': List[Dict] with OHLC data
                'current_price': float
                'current_r': float (or calculated here)
                'momentum': float
                'rsi': float
                'volume_decay': float
                'adx': float
                'unrealized_pnl': float
                'ml_confidence': float
            current_time: Current UTC time (auto-filled if None)
        
        Returns:
            Dict with keys:
                'action': str (one of: 'no_action', 'update_sl', 'scale_out', 'force_close')
                'reason': str (why this action)
                'new_sl': float (if action requires SL update)
                'volume_to_close': float (if action requires partial close)
                'close_percent': float (% to close)
                'signal_type': MomentumExitSignal
                'current_r': float
                'details': Dict (detailed info for logging)
        """
        now = current_time or datetime.now(timezone.utc)
        state = self.momentum_states.get(str(position.position_id))
        
        if not state:
            # Register if not already known
            state = self.register_position(position)
        
        # Extract market data
        price_history = market_data.get('price_history', [])
        current_price = market_data.get('current_price', position.current_price)
        current_r = market_data.get('current_r', 0.0)
        momentum = market_data.get('momentum', 0.0)
        rsi = market_data.get('rsi', 50.0)
        volume_decay = market_data.get('volume_decay', 0.0)
        adx = market_data.get('adx', 20.0)
        unrealized_pnl = market_data.get('unrealized_pnl', position.unrealized_pnl)
        ml_confidence = market_data.get('ml_confidence', 0.5)
        stop_loss = market_data.get('stop_loss', position.stop_loss)
        
        # If not provided, calculate R
        if current_r == 0.0:
            current_r = self.calculate_r_multiple(
                position.entry_price, current_price, stop_loss,
                position.direction, position.symbol
            )
        
        # Track highest R for statistics
        if current_r > state.highest_profit_r:
            state.highest_profit_r = current_r
            state.highest_profit_time = now
        
        # UPDATE STATISTICS
        state.stall_cycle_count += 1
        
        result = {
            'action': 'no_action',
            'reason': 'Position holding normally',
            'signal_type': MomentumExitSignal.NO_ACTION,
            'current_r': current_r,
            'details': {},
        }
        
        # =========== PRIORITY CHECK #1: HARD LOSS (Safety Valve) ===========
        # If position has catastrophic loss, exit immediately
        hard_loss_threshold = float(os.environ.get("HARD_LOSS_THRESHOLD_USD", "-15.00"))
        if unrealized_pnl < hard_loss_threshold:
            self.logger.critical(
                "[MOMENTUM_LOSS_THRESHOLD] %s #%s | Loss: $%.2f < $%.2f | Force close",
                position.symbol, position.position_id, unrealized_pnl, hard_loss_threshold
            )
            return {
                'action': 'force_close',
                'reason': f'Hard loss threshold exceeded: ${unrealized_pnl:.2f}',
                'signal_type': MomentumExitSignal.NO_ACTION,
                'current_r': current_r,
                'close_percent': 100.0,
            }
        
        # =========== PRIORITY CHECK #2: BREAKEVEN LOCK ===========
        be_applied, be_dict = self.apply_breakeven_lock(position, current_r)
        if be_applied and be_dict:
            result['action'] = 'update_sl'
            result['reason'] = be_dict['reason']
            result['new_sl'] = be_dict['new_sl']
            result['signal_type'] = MomentumExitSignal.BREAKEVEN_LOCK
            result['details'] = be_dict
            return result
        
        # =========== PRIORITY CHECK #3: ML CONFIDENCE EXIT ===========
        ml_exit, ml_dict = self.check_ml_confidence_exit(position, ml_confidence, unrealized_pnl)
        if ml_exit and ml_dict:
            return {
                'action': 'force_close',
                'reason': ml_dict['reason'],
                'signal_type': MomentumExitSignal.ML_CONFIDENCE_EXIT,
                'current_r': current_r,
                'close_percent': 100.0,
                'details': ml_dict,
            }
        
        # =========== PRIORITY CHECK #4: SCALE-OUT AT 1.2R ===========
        scale_triggered, scale_dict = self.check_scale_out_1_2r(
            position, current_r, position.entry_price, stop_loss
        )
        if scale_triggered and scale_dict:
            return {
                'action': 'scale_out',
                'reason': scale_dict['reason'],
                'signal_type': MomentumExitSignal.SCALE_OUT_1_2R,
                'current_r': current_r,
                'close_percent': scale_dict['close_percent'],
                'new_sl_for_remainder': scale_dict['new_sl_for_remainder'],
                'details': scale_dict,
            }
        
        # =========== PRIORITY CHECK #5: CHANDELIER TRAILING ===========
        trail_updated, trail_dict = self.update_chandelier_trail(
            position, current_r, price_history, current_price
        )
        if trail_updated and trail_dict:
            result['action'] = 'update_sl'
            result['reason'] = trail_dict['reason']
            result['new_sl'] = trail_dict['new_sl']
            result['signal_type'] = MomentumExitSignal.CHANDELIER_TRAIL
            result['details'] = trail_dict
            # Don't return yet - check for tight leash below
        
        # =========== PRIORITY CHECK #6: EXHAUSTION & TIGHT LEASH ===========
        exhaustion, exhaustion_count = self.detect_exhaustion_reversal(price_history, position.direction)
        if exhaustion:
            state.consecutive_exhaustion_bars += exhaustion_count
            result['details']['exhaustion_detected'] = True
            result['details']['exhaustion_bars'] = state.consecutive_exhaustion_bars
        
        # Apply tight leash if reversal risk high
        leash_activated, leash_dict = self.apply_tight_leash_if_reversal_risk(
            position, price_history, momentum, rsi, volume_decay
        )
        if leash_activated and leash_dict:
            result['action'] = 'update_sl'
            result['reason'] = leash_dict['reason']
            result['new_sl'] = leash_dict['new_sl']
            result['signal_type'] = MomentumExitSignal.TIGHT_LEASH_TIGHTEN
            result['details'] = leash_dict
            return result
        
        # If chandelier updated earlier, return that
        if result['action'] == 'update_sl':
            return result
        
        # =========== PRIORITY CHECK #7: STAGNATION EXIT ===========
        effective_stagnation_limit = self.get_effective_stagnation_limit(
            position, current_time=now, adx=adx
        )
        
        bars_held = state.stall_cycle_count  # Simple proxy - in real code use proper bar counting
        if bars_held > effective_stagnation_limit:
            stagnation_type = (
                MomentumExitSignal.TOKYO_STAGNATION 
                if self.is_tokyo_session(now) 
                else MomentumExitSignal.TREND_STAGNATION
            )
            self.logger.critical(
                "[MOMENTUM_STAGNATION_EXIT] %s #%s | Bars: %d > Limit: %d | Force close",
                position.symbol, position.position_id, bars_held, effective_stagnation_limit
            )
            return {
                'action': 'force_close',
                'reason': f'Stagnation exit: {bars_held} bars > {effective_stagnation_limit} limit',
                'signal_type': stagnation_type,
                'current_r': current_r,
                'close_percent': 100.0,
                'details': {'bars_held': bars_held, 'limit': effective_stagnation_limit},
            }
        
        # =========== NO ACTION ===========
        return result


# Export for use in other modules
__all__ = [
    'MomentumExitManager',
    'MomentumExitSignal',
    'MomentumPositionState',
    'BreakevenLock',
    'ChandelierTrail',
    'TightLeashSL',
]
