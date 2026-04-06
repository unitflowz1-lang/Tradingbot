"""
User Trade Learner Module (ENHANCED v2.0)
Enables the bot to learn from manual trader decisions by:
1. Capturing entries with rejection memory (conviction mapping)
2. Analyzing manual exits (momentum vs news classification)
3. Tracking directional bias and win rates
4. Adjusting signal weights and quality floors dynamically

Key Mechanisms:
- 60-minute rejection window for conviction delta tracking
- Exit classification: MOMENTUM_SHIFT, NEWS_SPIKE, PROFIT_TAKING
- Sensitivity weight boosting based on exit patterns
- Dynamic quality floor recommendations
"""

import os
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, asdict, field
from enum import Enum
import math

from src.models import Position, Direction

class ExitType(Enum):
    """Classification of manual exits"""
    MOMENTUM_SHIFT = "momentum_shift"
    NEWS_SPIKE = "news_spike"
    PROFIT_TAKING = "profit_taking"
    UNKNOWN = "unknown"

@dataclass
class UserTradeRecord:
    symbol: str
    direction: str
    entry_price: float
    entry_time: float
    market_context: Dict[str, Any]
    outcome: Optional[float] = None
    exit_time: Optional[float] = None
    position_id: str = ""
    exit_type: Optional[str] = None  # Classified exit type
    exit_context: Optional[Dict[str, Any]] = None  # Market state at exit

@dataclass
class RejectionRecord:
    """Track bot rejections for conviction delta calculation"""
    timestamp: float
    symbol: str
    reason: str
    required_score: float
    market_context: Dict[str, Any] = field(default_factory=dict)

class UserTradeLearner:
    """
    ENHANCED: Captures and learns from manual trader decisions.
    
    Four Learning Pathways:
    1. Conviction Mapping: Rejection memory + conviction delta
    2. Exit Analysis: Classify exits and boost indicator sensitivity
    3. Directional Bias: Weight boost for proven user preferences
    4. Quality Floor: Recommend thresholds based on striking frequency
    """
    
    def __init__(self, bot_magic: int = 234000, 
                 storage_dir: str = "src/analysis/learning"):
        self.bot_magic = bot_magic
        self.storage_dir = storage_dir
        os.makedirs(storage_dir, exist_ok=True)
        
        self.trades_path = os.path.join(storage_dir, "user_trades.json")
        self.weights_path = os.path.join(storage_dir, "learned_weights.json")
        self.rejection_log_path = os.path.join(storage_dir, "rejection_history.json")
        self.exit_patterns_path = os.path.join(storage_dir, "exit_patterns.json")
        
        self.logger = logging.getLogger(__name__)
        self.trades: Dict[str, UserTradeRecord] = self._load_trades()
        self.active_weights: Dict[str, float] = self._load_weights()
        self.rejection_history: Dict[str, List[RejectionRecord]] = self._load_rejections()
        self.exit_patterns: Dict[str, Dict] = self._load_exit_patterns()
        
        self.logger.info(
            f"[INIT] UserTradeLearner v2.0 active | "
            f"Trades: {len(self.trades)} | "
            f"Rejection history: {sum(len(v) for v in self.rejection_history.values())} entries"
        )

    def _load_trades(self) -> Dict[str, UserTradeRecord]:
        """Load trade history from disk"""
        if os.path.exists(self.trades_path):
            try:
                with open(self.trades_path, 'r') as f:
                    data = json.load(f)
                    return {k: UserTradeRecord(**v) for k, v in data.items()}
            except Exception as e:
                self.logger.error(f"Failed to load user trades: {e}")
        return {}

    def _load_weights(self) -> Dict[str, float]:
        """Load learned weights or return defaults"""
        defaults = {
            "mtf": 0.25,
            "volatility": 0.15,
            "momentum": 0.20,
            "liquidity": 0.15,
            "indicators": 0.15,
            "risk": 0.10
        }
        if os.path.exists(self.weights_path):
            try:
                with open(self.weights_path, 'r') as f:
                    weights = json.load(f)
                    # Normalize in case out of sync
                    total = sum(weights.values())
                    if total > 0:
                        return {k: v/total for k, v in weights.items()}
                    return weights
            except Exception as e:
                self.logger.error(f"Failed to load learned weights: {e}")
        return defaults

    def _load_rejections(self) -> Dict[str, List[RejectionRecord]]:
        """Load rejection history for conviction tracking"""
        if os.path.exists(self.rejection_log_path):
            try:
                with open(self.rejection_log_path, 'r') as f:
                    data = json.load(f)
                    return {
                        k: [RejectionRecord(**r) for r in v] 
                        for k, v in data.items()
                    }
            except Exception as e:
                self.logger.error(f"Failed to load rejection history: {e}")
        return {}

    def _load_exit_patterns(self) -> Dict[str, Dict]:
        """Load exit pattern statistics"""
        if os.path.exists(self.exit_patterns_path):
            try:
                with open(self.exit_patterns_path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                self.logger.error(f"Failed to load exit patterns: {e}")
        return {
            'momentum_shift_count': 0,
            'news_spike_count': 0,
            'profit_taking_count': 0,
            'sensitivity_adjustments': {
                'momentum': 0.0,
                'liquidity': 0.0,
                'volatility': 0.0
            }
        }

    def _save_trades(self):
        """Save trade history to disk"""
        try:
            with open(self.trades_path, 'w') as f:
                json.dump({k: asdict(v) for k, v in self.trades.items()}, f, indent=4)
        except Exception as e:
            self.logger.error(f"Failed to save user trades: {e}")

    def _validate_trade_record(self, record: UserTradeRecord) -> None:
        if not str(record.position_id or "").strip():
            raise ValueError("position_id is required")
        if not str(record.symbol or "").strip():
            raise ValueError("symbol is required")
        if record.entry_price is None or float(record.entry_price) <= 0:
            raise ValueError(f"entry_price must be positive, got {record.entry_price}")
        if record.entry_time is None:
            raise ValueError("entry_time is required")
        if record.market_context is None or not isinstance(record.market_context, dict):
            raise ValueError("market_context must be a dict")

    def store_trade(self, record: UserTradeRecord) -> bool:
        """Validate and persist a learner trade record."""
        try:
            record.position_id = str(record.position_id)
            self._validate_trade_record(record)
            self.trades[record.position_id] = record
            self._save_trades()
            return True
        except Exception as exc:
            self.logger.error(
                "[LEARNER_STORE_ERROR] Failed to store trade %s on %s: %s | payload=%s",
                getattr(record, "position_id", "unknown"),
                getattr(record, "symbol", "unknown"),
                exc,
                asdict(record) if hasattr(record, "__dataclass_fields__") else record,
            )
            return False

    def _save_rejections(self):
        """Save rejection history"""
        try:
            with open(self.rejection_log_path, 'w') as f:
                json.dump(
                    {k: [asdict(r) for r in v] for k, v in self.rejection_history.items()},
                    f, indent=4
                )
        except Exception as e:
            self.logger.error(f"Failed to save rejection history: {e}")

    def _save_exit_patterns(self):
        """Save exit pattern statistics"""
        try:
            with open(self.exit_patterns_path, 'w') as f:
                json.dump(self.exit_patterns, f, indent=4)
        except Exception as e:
            self.logger.error(f"Failed to save exit patterns: {e}")

    # =====================================================================
    # PATHWAY 1: CONVICTION MAPPING (Manual Entry Analysis)
    # =====================================================================

    def record_bot_rejection(self, symbol: str, reason: str, required_score: float, 
                            market_context: Dict[str, Any]):
        """
        Record when the bot rejects a signal (for 60-minute conviction window)
        """
        if symbol not in self.rejection_history:
            self.rejection_history[symbol] = []
        
        record = RejectionRecord(
            timestamp=datetime.now(timezone.utc).timestamp(),
            symbol=symbol,
            reason=reason,
            required_score=required_score,
            market_context=market_context
        )
        self.rejection_history[symbol].append(record)
        
        # Keep only last 100 rejections per symbol
        if len(self.rejection_history[symbol]) > 100:
            self.rejection_history[symbol] = self.rejection_history[symbol][-100:]
        
        self._save_rejections()

    def query_rejection_history(self, symbol: str, window_minutes: int = 60) -> Optional[Dict]:
        """
        Query bot rejections for a symbol within time window
        Returns the most recent rejection if found
        """
        if symbol not in self.rejection_history:
            return None
        
        now_ts = datetime.now(timezone.utc).timestamp()
        cutoff_ts = now_ts - (window_minutes * 60)
        
        recent = [
            r for r in self.rejection_history[symbol]
            if r.timestamp >= cutoff_ts
        ]
        
        if not recent:
            return None
        
        last_rejection = recent[-1]
        return {
            'timestamp': last_rejection.timestamp,
            'reason': last_rejection.reason,
            'required_score': last_rejection.required_score,
            'market_context': last_rejection.market_context
        }

    def analyze_manual_entry_conviction(self, position: Position, 
                                       market_context: Dict[str, Any]) -> Dict:
        """
        CONVICTION MAPPING: Compare user entry to bot's prior rejections (60-min window)
        
        Returns:
        {
            'conviction_delta': float,  # Magnitude of belief difference
            'bot_rejected_recently': bool,
            'rejection_reason': str,
            'striking_zone_params': {...},
            'recommendation': 'INCREASE_THRESHOLD' | 'CREATE_STRIKING_ZONE' 
        }
        """
        symbol = position.symbol
        rejection = self.query_rejection_history(symbol, window_minutes=60)
        
        if not rejection:
            return {
                'conviction_delta': 0.0,
                'bot_rejected_recently': False,
                'striking_zone_params': None
            }
        
        # Reconstruct what signal score would have been at user entry
        user_entry_score = self._estimate_signal_score(market_context)
        conviction_delta = user_entry_score - rejection['required_score']
        
        result = {
            'conviction_delta': max(0, conviction_delta),
            'bot_rejected_recently': True,
            'rejection_reason': rejection['reason'],
            'striking_zone_params': {
                'adx': market_context.get('adx', 0),
                'rsi': market_context.get('rsi', 50),
                'atr': market_context.get('atr', 0),
                'price_action': market_context.get('price_pattern', 'unknown'),
                'mtf_aligned': market_context.get('mtf_aligned', False)
            },
            'recommendation': 'INCREASE_THRESHOLD' if conviction_delta > 5 else 'CREATE_STRIKING_ZONE'
        }
        
        if conviction_delta > 0:
            self.logger.info(
                f"[CONVICTION_DELTA] {symbol} | User conviction +{conviction_delta:.1f} pts "
                f"over bot rejection | Recommendation: {result['recommendation']}"
            )
        
        return result

    # =====================================================================
    # PATHWAY 2: EXIT ANALYSIS (Manual Exit Classification)
    # =====================================================================

    def analyze_manual_exit(self, position_id: str, exit_price: float,
                           market_context_at_entry: Dict[str, Any],
                           market_context_at_exit: Dict[str, Any]) -> Dict:
        """
        RISK PERCEPTION: Classify WHY user exited before SL/TP hit
        
        Three scenarios:
        1. MOMENTUM_SHIFT: RSI reversal detected at exit
        2. NEWS_SPIKE: Price spike beyond normal ATR
        3. PROFIT_TAKING: Reached profit target (normal)
        """
        
        trade = self.trades.get(position_id)
        if not trade:
            return {'exit_type': 'unknown'}
        
        exit_analysis = {
            'position_id': position_id,
            'symbol': trade.symbol,
            'profit': trade.outcome,
            'exit_type': ExitType.UNKNOWN.value,
            'sensitivity_adjustment': {}
        }
        
        # Scenario 1: MOMENTUM_SHIFT
        if self._detect_momentum_reversal(market_context_at_entry, market_context_at_exit, trade.direction):
            exit_analysis['exit_type'] = ExitType.MOMENTUM_SHIFT.value
            
            # User detected momentum reversal faster than bot
            # Boost RSI divergence tracking
            sensitivity_boost = 0.10
            exit_analysis['sensitivity_adjustment'] = {
                'indicator': 'momentum',
                'boost': sensitivity_boost,
                'reason': f"User detected RSI reversal at {market_context_at_exit.get('rsi', 0):.0f}"
            }
            
            self.exit_patterns['momentum_shift_count'] += 1
            self.exit_patterns['sensitivity_adjustments']['momentum'] += sensitivity_boost
            
            self.logger.info(
                f"[EXIT_MOMENTUM] {trade.symbol} | User exited on RSI reversal "
                f"| BOOST momentum weight +{sensitivity_boost*100:.0f}%"
            )
        
        # Scenario 2: NEWS_SPIKE
        elif self._detect_price_spike(market_context_at_entry, market_context_at_exit):
            exit_analysis['exit_type'] = ExitType.NEWS_SPIKE.value
            
            # MACRO_SHIELD was slow, boost liquidity/macro monitoring
            sensitivity_boost = 0.08
            exit_analysis['sensitivity_adjustment'] = {
                'indicator': 'liquidity',
                'boost': sensitivity_boost,
                'reason': 'Price spike detected; macro monitoring too slow'
            }
            
            self.exit_patterns['news_spike_count'] += 1
            self.exit_patterns['sensitivity_adjustments']['liquidity'] += sensitivity_boost
            
            self.logger.warning(
                f"[EXIT_NEWS] {trade.symbol} | Spike detected at exit "
                f"| BOOST liquidity gate +{sensitivity_boost*100:.0f}%"
            )
        
        # Scenario 3: PROFIT_TAKING
        else:
            exit_analysis['exit_type'] = ExitType.PROFIT_TAKING.value
            self.exit_patterns['profit_taking_count'] += 1
        
        self._save_exit_patterns()
        return exit_analysis

    def _detect_momentum_reversal(self, entry_ctx: Dict, exit_ctx: Dict, direction: str) -> bool:
        """Check if RSI reversed sharply at exit"""
        entry_rsi = entry_ctx.get('rsi', 50)
        exit_rsi = exit_ctx.get('rsi', 50)
        
        # LONG trade: RSI dropped >10 pts? → User escaped early
        if direction == 'LONG' or str(direction).upper() == 'LONG':
            return exit_rsi < (entry_rsi - 10)
        # SHORT trade: RSI gained >10 pts? → User escaped early
        else:
            return exit_rsi > (entry_rsi + 10)

    def _detect_price_spike(self, entry_ctx: Dict, exit_ctx: Dict) -> bool:
        """Check if price moved >2x normal ATR at exit"""
        entry_atr = entry_ctx.get('atr', 1.0)
        entry_price = entry_ctx.get('price', 0)
        exit_price = exit_ctx.get('price', 0)
        
        if entry_atr <= 0:
            return False
        
        price_move = abs(exit_price - entry_price)
        spike_threshold = entry_atr * 2.0
        
        return price_move > spike_threshold

    # =====================================================================
    # PATHWAY 3: DIRECTIONAL BIAS TRACKING
    # =====================================================================

    def calculate_performance_metrics(self, symbol: str) -> Dict:
        """
        Calculate win rates and profit factors for a symbol
        to detect user's directional bias
        """
        trades = [t for t in self.trades.values() if t.symbol == symbol and t.outcome is not None]
        
        if not trades:
            return {
                'symbol': symbol,
                'total_trades': 0,
                'win_rate': 0.0,
                'profit_factor': 0.0,
                'long_wr': 0.0,
                'short_wr': 0.0,
                'directional_bias': 'NEUTRAL',
                'bias_confidence': 0.0
            }
        
        wins = [t for t in trades if t.outcome > 0]
        losses = [t for t in trades if t.outcome < 0]
        
        win_rate = len(wins) / len(trades) if trades else 0
        
        gross_profit = sum(t.outcome for t in wins if t.outcome > 0)
        gross_loss = abs(sum(t.outcome for t in losses if t.outcome < 0))
        
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else (1.0 if gross_profit > 0 else 0.0)
        
        # Directional bias
        long_trades = [t for t in trades if t.direction == 'LONG' or str(t.direction).upper() == 'LONG']
        short_trades = [t for t in trades if t.direction == 'SHORT' or str(t.direction).upper() == 'SHORT']
        
        long_wins = len([t for t in long_trades if t.outcome > 0])
        short_wins = len([t for t in short_trades if t.outcome > 0])
        
        long_wr = long_wins / len(long_trades) if long_trades else 0
        short_wr = short_wins / len(short_trades) if short_trades else 0
        
        bias = 'NEUTRAL'
        if long_wr > short_wr * 1.15:
            bias = 'LONG_BIAS'
        elif short_wr > long_wr * 1.15:
            bias = 'SHORT_BIAS'
        
        return {
            'symbol': symbol,
            'total_trades': len(trades),
            'win_rate': win_rate,
            'profit_factor': profit_factor,
            'long_wr': long_wr,
            'short_wr': short_wr,
            'directional_bias': bias,
            'bias_confidence': abs(long_wr - short_wr)
        }

    # =====================================================================
    # PATHWAY 4: QUALITY FLOOR CALIBRATION
    # =====================================================================

    def analyze_striking_frequency(self, bot_trades: List[Dict], 
                                   user_trades: Optional[List[Dict]] = None) -> Dict:
        """
        Compare striking frequency to recommend quality floor adjustments
        
        If user finding 3x+ more trades, suggest temp floor lowering
        """
        user_trades = user_trades or [t for t in self.trades.values() if t.outcome is not None]
        
        if not bot_trades or not user_trades:
            return {
                'recommendation': 'HOLD',
                'bot_strikes_per_hour': 0,
                'user_strikes_per_hour': 0
            }
        
        # Simple frequency calculation (would be more sophisticated in production)
        frequency_ratio = len(user_trades) / len(bot_trades) if bot_trades else 0
        
        analysis = {
            'bot_strikes': len(bot_trades),
            'user_strikes': len(user_trades),
            'frequency_ratio': frequency_ratio,
            'recommendation': 'HOLD'
        }
        
        if frequency_ratio >= 2.5:
            # User finding significantly more trades
            optimal_floor = self._calculate_optimal_quality_floor()
            analysis['recommendation'] = 'LOWER_FLOOR'
            analysis['suggest_floor'] = optimal_floor
            analysis['suggest_duration_hours'] = 4
            analysis['reason'] = (
                f"User striking {frequency_ratio:.1f}x more often. "
                f"Suggest temp floor {optimal_floor:.1f} for 4h"
            )
            
            self.logger.critical(
                f"[QUALITY_FLOOR_ALERT] {analysis['reason']}"
            )
        
        return analysis

    def _calculate_optimal_quality_floor(self, base_floor: float = 65.0) -> float:
        """
        Calculate what quality score would admit user's recent trades
        """
        recent_trades = [
            t for t in self.trades.values() 
            if t.outcome is not None
        ][-10:]
        
        if not recent_trades:
            return base_floor
        
        # Estimate scores for these trades
        scores = [
            self._estimate_signal_score(t.market_context)
            for t in recent_trades
        ]
        
        scores = sorted(scores)
        # 5th percentile of user scores (admit ~95% of what user admits)
        optimal = scores[max(0, len(scores) - 5)]
        
        # Never go below base_floor - 15
        return max(base_floor - 15, optimal)

    # =====================================================================
    # INTEGRATION HELPERS
    # =====================================================================

    def capture_trade_entry(self, position: Position, market_context: Dict[str, Any],
                           source: str = 'manual'):
        """
        Record a new trade (manual or bot-generated)
        """
        position_id = str(position.position_id)
        if position_id not in self.trades:
            record = UserTradeRecord(
                symbol=position.symbol,
                direction=position.direction.value if hasattr(position.direction, 'value') else str(position.direction),
                entry_price=position.entry_price,
                entry_time=position.opened_at.timestamp() if hasattr(position.opened_at, 'timestamp') else datetime.now().timestamp(),
                market_context=market_context,
                position_id=position_id
            )
            if self.store_trade(record):
                self.logger.info(
                    f"[LEARNER] Captured {source} trade {position_id} on {position.symbol}"
                )

    def capture_trade_exit(self, position_id: str, profit: float, exit_time: datetime,
                          market_context_at_exit: Optional[Dict[str, Any]] = None):
        """
        Record trade exit and trigger learning
        """
        position_key = str(position_id)
        if position_key in self.trades:
            record = self.trades[position_key]
            record.outcome = profit
            record.exit_time = exit_time.timestamp()
            
            # Classify exit if we have context
            if market_context_at_exit:
                exit_analysis = self.analyze_manual_exit(
                    position_key, 0, record.market_context, market_context_at_exit
                )
                record.exit_type = exit_analysis.get('exit_type')
                record.exit_context = market_context_at_exit
            
            if self.store_trade(record):
                self.logger.info(
                    f"[LEARNER] Recorded exit for {position_key} | "
                    f"Profit: ${profit:.2f} | ExitType: {record.exit_type}"
                )
            
            # Periodically re-learn
            completed_count = len([t for t in self.trades.values() if t.outcome is not None])
            if completed_count > 0 and completed_count % 3 == 0:
                self.optimize_weights()

    def optimize_weights(self):
        """
        Analyze user trade performance and adjust weights
        Apply exit pattern learnings
        """
        completed_trades = [t for t in self.trades.values() if t.outcome is not None]
        if len(completed_trades) < 3:
            return

        profitable_trades = [t for t in completed_trades if t.outcome > 0]
        if not profitable_trades:
            return

        self.logger.info(
            f"[LEARNER] Optimizing weights based on {len(completed_trades)} trades "
            f"({len(profitable_trades)} profitable)"
        )
        
        new_weights = self.active_weights.copy()
        
        # 1. Boost weights for strong components in profitable trades
        for trade in profitable_trades:
            ctx = trade.market_context
            mappings = {
                'mtf_score': 'mtf',
                'volatility_score': 'volatility',
                'momentum_score': 'momentum',
                'liquidity_score': 'liquidity',
                'indicator_score': 'indicators',
                'risk_score': 'risk'
            }
            
            for ctx_key, weight_key in mappings.items():
                if ctx.get(ctx_key, 0) > 70 and weight_key in new_weights:
                    new_weights[weight_key] += 0.01
        
        # 2. Apply exit pattern learnings
        # Boost momentum if we've seen momentum shifts
        if self.exit_patterns['momentum_shift_count'] >= 3:
            momentum_boost = min(0.08, self.exit_patterns['sensitivity_adjustments']['momentum'])
            new_weights['momentum'] += momentum_boost
            self.logger.info(f"[LEARNING] Momentum boost: +{momentum_boost:.3f}")
        
        # Boost liquidity if we've seen news spikes
        if self.exit_patterns['news_spike_count'] >= 2:
            liquidity_boost = min(0.06, self.exit_patterns['sensitivity_adjustments']['liquidity'])
            new_weights['liquidity'] += liquidity_boost
            self.logger.info(f"[LEARNING] Liquidity boost: +{liquidity_boost:.3f}")
        
        # Normalize weights
        total = sum(new_weights.values())
        for k in new_weights:
            new_weights[k] /= total
        
        self.active_weights = new_weights
        
        try:
            with open(self.weights_path, 'w') as f:
                json.dump(new_weights, f, indent=4)
            self.logger.info(f"[LEARNER] Applied new weights: {new_weights}")
        except Exception as e:
            self.logger.error(f"Failed to save optimized weights: {e}")

    def _estimate_signal_score(self, market_context: Dict[str, Any]) -> float:
        """
        Estimate what the signal score would have been
        (rough approximation based on context indicators)
        """
        score = 50.0
        
        adx = market_context.get('adx', 12.0)
        if adx < 12.0:
            score -= 15
        elif adx >= 20.0:
            score += 15
        
        if market_context.get('mtf_aligned'):
            score += 15
        
        rsi = market_context.get('rsi', 50)
        if 40 < rsi < 60:
            score += 10
        
        atr_percentile = market_context.get('atr_percentile', 50)
        if atr_percentile > 80:
            score -= 10
        elif atr_percentile < 30:
            score += 5
        
        return min(100, max(0, score))

    def get_weights(self) -> Dict[str, float]:
        """Return the current learned weights"""
        return self.active_weights.copy()

    def get_learning_summary(self) -> Dict[str, Any]:
        """Generate summary of learning progress"""
        completed_trades = [t for t in self.trades.values() if t.outcome is not None]
        profitable = [t for t in completed_trades if t.outcome > 0]
        
        return {
            'total_trades': len(self.trades),
            'completed_trades': len(completed_trades),
            'profitable_trades': len(profitable),
            'win_rate': len(profitable) / len(completed_trades) if completed_trades else 0,
            'exit_patterns': self.exit_patterns,
            'learned_weights': self.active_weights,
            'rejection_history_depth': sum(len(v) for v in self.rejection_history.values())
        }
