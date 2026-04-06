"""
Exit Reason Tracking and Classification
Logs why each trade was exited to ensure training data remains unbiased
"""

from enum import Enum
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
import logging


class ExitReason(Enum):
    """
    Categorizes HOW a trade was exited to separate market-driven vs administrative exits.
    
    MARKET-DRIVEN (Feed to ML training):
    - These exits are based on actual price action and should be included in training
    
    ADMINISTRATIVE (Exclude from training):
    - These exits are NOT based on market behavior and would bias the model
    """
    
    # MARKET-DRIVEN EXITS (Include in Training)
    TP_HIT = "tp_hit"                          # Position hit take-profit (price action)
    PARTIAL_TP = "partial_tp"                  # Partial profit taken (price action)
    SL_HIT = "sl_hit"                          # Position hit stop-loss (price action)
    TRAILING_STOP_HIT = "trailing_stop_hit"    # Trailing stop was triggered (price action)
    BREAKEVEN_STOP_HIT = "breakeven_stop_hit"  # Breakeven stop was hit (price action)
    
    # ADMINISTRATIVE EXITS (Exclude from Training)
    MANUAL_CLOSE_TP = "manual_close_tp"        # Manually closed at take-profit
    MANUAL_CLOSE_SL = "manual_close_sl"        # Manually closed at stop-loss
    MANUAL_CLOSE_OTHER = "manual_close_other"  # Manually closed for other reasons
    SIGNAL_INVALIDATION = "signal_invalidation" # Signal invalidated (e.g. regime change)
    EQUITY_LOCK = "equity_lock"                # Closed to lock equity target
    TIME_EXIT = "time_exit"                    # Closed due to time-based exit rule
    RISK_HALT_DAILY = "risk_halt_daily"        # Closed by risk governor (daily P&L limit)
    RISK_HALT_DRAWDOWN = "risk_halt_drawdown"  # Closed by risk governor (drawdown limit)
    RISK_HALT_EQUITY = "risk_halt_equity"      # Closed by risk governor (equity limit)
    MARGIN_CALL = "margin_call"                # Closed due to margin shortage
    CONNECTION_LOST = "connection_lost"        # Closed due to connection issue
    UNDEFINED = "undefined"                    # Exit reason not recorded
    
    @property
    def is_market_driven(self) -> bool:
        """Returns True if this exit should be included in training data"""
        market_driven = {
            ExitReason.TP_HIT,
            ExitReason.PARTIAL_TP,
            ExitReason.SL_HIT,
            ExitReason.TRAILING_STOP_HIT,
            ExitReason.BREAKEVEN_STOP_HIT,
        }
        return self in market_driven
    
    @property
    def is_administrative(self) -> bool:
        """Returns True if this exit should be EXCLUDED from training data"""
        return not self.is_market_driven
    
    @property
    def is_risk_governor_halt(self) -> bool:
        """Returns True if this exit was triggered by the risk governor"""
        risk_exits = {
            ExitReason.RISK_HALT_DAILY,
            ExitReason.RISK_HALT_DRAWDOWN,
            ExitReason.RISK_HALT_EQUITY,
        }
        return self in risk_exits


@dataclass
class ExitRecord:
    """Complete record of how and why a trade was exited"""
    
    position_id: str
    symbol: str
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    direction: str  # "LONG" or "SHORT"
    quantity: float
    reason: ExitReason
    
    # Exit details
    profit_loss: float  # Final P&L in account currency
    profit_loss_pips: float  # P&L in pips
    hold_time_seconds: int  # How long trade was held
    
    # Detailed Attribution Metrics
    r_multiple: float = 0.0          # R-Multiple achieved
    mfe: float = 0.0                 # Maximum Favorable Excursion (highest floating profit)
    mae: float = 0.0                 # Maximum Adverse Excursion (highest floating loss)
    
    # Context for investigation
    was_manual: bool = False  # Was manually closed
    manual_user: Optional[str] = None  # Which user/system closed it
    notes: Optional[str] = None  # Additional context
    parent_trade_id: Optional[str] = None # For partial exits, link to parent trade
    
    # Training metadata
    training_excluded: bool = False  # If True, don't use in ML training
    training_exclusion_reason: Optional[str] = None  # Why excluded
    
    # Legacy fields (mapped to MFE/MAE if not provided)
    max_profit_during_hold: float = 0.0 
    max_loss_during_hold: float = 0.0 
    
    # Policy and Quality
    exit_policy: str = "STANDARD"  # Strategy used to manage the trade
    exit_quality: float = 0.0      # Score of exit efficiency (0.0 to 1.0+) 
    
    # ML Tracking
    predicted_exit_policy: Optional[str] = None
    policy_confidence: float = 0.0
    policy_regret: float = 0.0
    entry_features: Optional[list] = None 
    regime_label: Optional[str] = "NEUTRAL" # Detailed regime when trade was opened 
    
    def __post_init__(self):
        """Validate and set training exclusion"""
        self.training_excluded = self.reason.is_administrative
        if self.training_excluded:
            self.training_exclusion_reason = (
                f"Administrative exit ({self.reason.value}) - "
                f"not based on market behavior"
            )
        
        # Backward compatibility / Sync fields
        if self.mfe == 0.0 and self.max_profit_during_hold != 0.0:
            self.mfe = self.max_profit_during_hold
        if self.mae == 0.0 and self.max_loss_during_hold != 0.0:
            self.mae = self.max_loss_during_hold
            
    def to_dict(self) -> dict:
        """Convert to dictionary for logging/storage"""
        return {
            'position_id': self.position_id,
            'symbol': self.symbol,
            'entry_time': self.entry_time.isoformat() if isinstance(self.entry_time, datetime) else self.entry_time,
            'exit_time': self.exit_time.isoformat() if isinstance(self.exit_time, datetime) else self.exit_time,
            'entry_price': self.entry_price,
            'exit_price': self.exit_price,
            'direction': self.direction,
            'quantity': self.quantity,
            'reason': self.reason.value,
            'profit_loss': self.profit_loss,
            'profit_loss_pips': self.profit_loss_pips,
            'hold_time_seconds': self.hold_time_seconds,
            'r_multiple': self.r_multiple,
            'mfe': self.mfe,
            'mae': self.mae,
            'was_manual': self.was_manual,
            'manual_user': self.manual_user,
            'notes': self.notes,
            'parent_trade_id': self.parent_trade_id,
            'exit_policy': self.exit_policy,
            'exit_quality': self.exit_quality,
            'predicted_exit_policy': self.predicted_exit_policy,
            'policy_confidence': self.policy_confidence,
            'policy_regret': self.policy_regret,
            'entry_features': self.entry_features,
            'training_excluded': self.training_excluded,
            'training_exclusion_reason': self.training_exclusion_reason,
            'regime_label': self.regime_label
        }


class ExitLogger:
    """Logs all trade exits with reasons for audit and analysis - SINGLETON pattern"""

    _instance = None
    _initialized = False
    _exit_records: list[ExitRecord] = []
    _records_loaded: bool = False
    _load_log_emitted: bool = False
    _ensemble = None
    _logger = None
    
    def __new__(cls, logger: Optional[logging.Logger] = None):
        """Singleton factory - ensures only ONE instance exists globally"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            # Store the logger for the singleton
            cls._logger = logger or logging.getLogger(__name__)
        return cls._instance
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        """Initialize only once on first instantiation (subsequent calls are no-ops)"""
        # Skip re-initialization if already done
        if self.__class__._initialized:
            return
        
        self.__class__._initialized = True
        self.logger = self.__class__._logger
        self.exit_records = self.__class__._exit_records
        
        # Import ensemble here to avoid circular dependency
        if self.__class__._ensemble is None:
            try:
                from src.ml.exit_policy_ensemble import ExitPolicyEnsemble
                self.__class__._ensemble = ExitPolicyEnsemble()
            except ImportError:
                self.logger.warning("Could not import ExitPolicyEnsemble - performance tracking disabled")
                self.__class__._ensemble = None
        self.ensemble = self.__class__._ensemble

        # Load records only once on first instantiation
        if not self.__class__._records_loaded:
            self.load_records()
    
    def log_exit(self, record: ExitRecord) -> None:
        """Record a trade exit"""
        self.exit_records.append(record)
        
        # Update ensemble performance matrix
        if self.ensemble:
            try:
                self.ensemble.update_performance(record.to_dict())
            except Exception as e:
                self.logger.error(f"Failed to update ensemble: {e}")
        
        self.save_records() # Auto save on log
        
        # Log with different severity based on exit type
        emoji = "[WIN]" if record.profit_loss > 0 else "[LOSS]" if record.profit_loss < 0 else "[BREAK]"
        source = f" [MANUAL: {record.manual_user}]" if record.was_manual else ""
        training_note = " [TRAINING EXCLUDED]" if record.training_excluded else " [TRAINING INCLUDED]"
        
        self.logger.info(
            "%s [EXIT] %s | Reason: %s | PnL: $%.2f (%+.1f pips) | "
            "Hold: %dm | Entry: %.5f -> Exit: %.5f%s%s",
            emoji,
            record.symbol,
            record.reason.value,
            record.profit_loss,
            record.profit_loss_pips,
            record.hold_time_seconds // 60,
            record.entry_price,
            record.exit_price,
            source,
            training_note
        )
    
    def get_market_driven_exits(self) -> list[ExitRecord]:
        """Get only market-driven exits (suitable for training)"""
        return [r for r in self.exit_records if r.reason.is_market_driven]
    
    def get_administrative_exits(self) -> list[ExitRecord]:
        """Get only administrative exits (should be excluded from training)"""
        return [r for r in self.exit_records if r.reason.is_administrative]
    
    def get_risk_governor_exits(self) -> list[ExitRecord]:
        """Get exits triggered by risk governor"""
        return [r for r in self.exit_records if r.reason.is_risk_governor_halt]
    
    def get_summary(self) -> dict:
        """Summary statistics about exits"""
        market_driven = self.get_market_driven_exits()
        admin = self.get_administrative_exits()
        risk_halts = self.get_risk_governor_exits()
        
        return {
            'total_exits': len(self.exit_records),
            'market_driven_exits': len(market_driven),
            'administrative_exits': len(admin),
            'risk_governor_exits': len(risk_halts),
            'market_driven_pnl': sum(r.profit_loss for r in market_driven),
            'administrative_pnl': sum(r.profit_loss for r in admin),
            'risk_governor_pnl': sum(r.profit_loss for r in risk_halts),
            'pct_market_driven': len(market_driven) / len(self.exit_records) * 100 if self.exit_records else 0,
        }

    def get_policy_performance(self) -> dict:
        """
        Analyze performance by ExitPolicy
        Returns: {policy_name: {count, win_rate, avg_r, avg_quality, expectancy}}
        """
        stats = {}
        for record in self.exit_records:
            if not record.reason.is_market_driven:
                continue
                
            policy = record.exit_policy or "STANDARD"
            if policy not in stats:
                stats[policy] = {
                    'count': 0, 'wins': 0, 'total_r': 0.0, 'total_quality': 0.0, 'total_pnl': 0.0
                }
            
            s = stats[policy]
            s['count'] += 1
            if record.profit_loss > 0:
                s['wins'] += 1
            s['total_r'] += record.r_multiple
            s['total_quality'] += record.exit_quality
            s['total_pnl'] += record.profit_loss
            
        # Compile final metrics
        results = {}
        for policy, s in stats.items():
            count = s['count']
            if count == 0: continue
            
            results[policy] = {
                'trades': count,
                'win_rate': s['wins'] / count,
                'avg_r': s['total_r'] / count,
                'avg_quality': s['total_quality'] / count,
                'total_pnl': s['total_pnl'],
                'expectancy': s['total_pnl'] / count 
            }
        return results

    def save_records(self, filepath: str = "exit_history.json"):
        """Save exit records to JSON"""
        import json
        try:
            data = [r.to_dict() for r in self.exit_records]
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            self.logger.error(f"Failed to save exit history: {e}")

    def load_records(self, filepath: str = "exit_history.json"):
        """Load exit records from JSON (called only once during singleton initialization)"""
        import json
        import os
        
        # FIX: Guard against duplicate loading - check if already loaded
        if self.__class__._records_loaded:
            return
        
        if not os.path.exists(filepath):
            self.__class__._records_loaded = True
            return
            
        try:
            self.exit_records.clear()
            with open(filepath, 'r') as f:
                data = json.load(f)
            for item in data:
                # Reconstruct ExitRecord (handling basic types)
                # Need to convert string enums back to Enum
                try:
                    reason_enum = ExitReason(item['reason'])
                except ValueError:
                    reason_enum = ExitReason.UNDEFINED
                
                # timestamps
                entry_time = item['entry_time']
                if isinstance(entry_time, str):
                    try:
                        entry_time = datetime.fromisoformat(entry_time)
                    except:
                        entry_time = datetime.now(timezone.utc)

                exit_time = item['exit_time']
                if isinstance(exit_time, str):
                    try:
                        exit_time = datetime.fromisoformat(exit_time)
                    except:
                        exit_time = datetime.now(timezone.utc)

                record = ExitRecord(
                    position_id=item['position_id'],
                    symbol=item['symbol'],
                    entry_time=entry_time,
                    exit_time=exit_time,
                    entry_price=item['entry_price'],
                    exit_price=item['exit_price'],
                    direction=item['direction'],
                    quantity=item['quantity'],
                    reason=reason_enum,
                    profit_loss=item['profit_loss'],
                    profit_loss_pips=item.get('profit_loss_pips', 0.0),
                    hold_time_seconds=item.get('hold_time_seconds', 0),
                    r_multiple=item.get('r_multiple', 0.0),
                    mfe=item.get('mfe', 0.0),
                    mae=item.get('mae', 0.0),
                    parent_trade_id=item.get('parent_trade_id'),
                    exit_policy=item.get('exit_policy', "STANDARD"),
                    exit_quality=item.get('exit_quality', 0.0),
                    was_manual=item.get('was_manual', False),
                    manual_user=item.get('manual_user'),
                    notes=item.get('notes'),
                    predicted_exit_policy=item.get('predicted_exit_policy'),
                    policy_confidence=item.get('policy_confidence', 0.0),
                    policy_regret=item.get('policy_regret', 0.0),
                    entry_features=item.get('entry_features'),
                    regime_label=item.get('regime_label', 'NEUTRAL')
                )
                self.exit_records.append(record)
            
            # Log once when records are loaded (singleton initialization)
            self.logger.info(f"Loaded {len(self.exit_records)} exit records")
            self.__class__._records_loaded = True
        except Exception as e:
            self.logger.error(f"Failed to load exit history: {e}")
            self.__class__._records_loaded = True
