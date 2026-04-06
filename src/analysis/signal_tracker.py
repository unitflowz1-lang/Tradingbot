"""Signal persistence and tracking for performance analysis"""

import sqlite3
import uuid
from typing import Dict, Optional, Any, List
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import stdev
from src.models import TradingSignal
from src.analysis.confidence_calculator import ConfidenceResult
from src.exceptions import DataValidationError
from src.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class SignalOutcome:
    """Outcome of a trading signal"""
    signal_id: str
    symbol: str
    direction: str
    entry_price: float
    exit_price: Optional[float]
    exit_reason: str  # "TAKE_PROFIT", "STOP_LOSS", "MANUAL", "EXPIRED"
    pnl: Optional[float]
    pnl_percentage: Optional[float]
    duration_minutes: Optional[int]
    max_favorable_excursion: Optional[float]  # Best price reached
    max_adverse_excursion: Optional[float]    # Worst price reached
    outcome_timestamp: datetime
    was_successful: Optional[bool]


@dataclass
class SignalPerformanceMetrics:
    """Performance metrics for signals"""
    total_signals: int
    successful_signals: int
    failed_signals: int
    pending_signals: int
    win_rate: float
    average_pnl: float
    average_pnl_percentage: float
    best_trade_pnl: float
    worst_trade_pnl: float
    average_duration_minutes: float
    sharpe_ratio: Optional[float]
    max_drawdown: float
    profit_factor: float  # Gross profit / Gross loss


@dataclass
class SignalHistoryEntry:
    """Historical signal entry"""
    signal_id: str
    symbol: str
    direction: str
    entry_price: float
    stop_loss: float
    take_profit: float
    confidence: float
    reasoning: str
    created_timestamp: datetime
    expiry_timestamp: datetime
    is_active: bool
    confidence_factors: Dict[str, float]
    market_conditions: Dict[str, Any]


class SignalTracker:
    """Track signal persistence and performance for analysis"""
    
    def __init__(self, 
                 db_path: str = "data/signal_tracking.db",
                 signal_expiry_hours: int = 24,
                 max_active_signals: int = 50):
        """Initialize signal tracker"""
        self.db_path = Path(db_path)
        self.signal_expiry_hours = signal_expiry_hours
        self.max_active_signals = max_active_signals
        
        # Create data directory if it doesn't exist
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Initialize database
        self._init_database()
        
        # In-memory cache for active signals
        self.active_signals: Dict[str, SignalHistoryEntry] = {}
        self._load_active_signals()
    
    def _init_database(self) -> None:
        """Initialize SQLite database for signal tracking"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Create signals table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS signals (
                    signal_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    stop_loss REAL NOT NULL,
                    take_profit REAL NOT NULL,
                    confidence REAL NOT NULL,
                    reasoning TEXT,
                    created_timestamp TEXT NOT NULL,
                    expiry_timestamp TEXT NOT NULL,
                    is_active INTEGER NOT NULL,
                    confidence_factors TEXT,
                    market_conditions TEXT
                )
            """)
            
            # Create outcomes table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS signal_outcomes (
                    outcome_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    signal_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL,
                    exit_reason TEXT NOT NULL,
                    pnl REAL,
                    pnl_percentage REAL,
                    duration_minutes INTEGER,
                    max_favorable_excursion REAL,
                    max_adverse_excursion REAL,
                    outcome_timestamp TEXT NOT NULL,
                    was_successful INTEGER,
                    FOREIGN KEY (signal_id) REFERENCES signals (signal_id)
                )
            """)
            
            # Create performance summary table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS performance_summary (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT,
                    direction TEXT,
                    date_range_start TEXT,
                    date_range_end TEXT,
                    total_signals INTEGER,
                    successful_signals INTEGER,
                    failed_signals INTEGER,
                    win_rate REAL,
                    average_pnl REAL,
                    sharpe_ratio REAL,
                    max_drawdown REAL,
                    created_timestamp TEXT
                )
            """)
            
            # Create indexes for better performance
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals (symbol)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_signals_created ON signals (created_timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_outcomes_signal ON signal_outcomes (signal_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_outcomes_timestamp ON signal_outcomes (outcome_timestamp)")
            
            conn.commit()
            
        logger.info(f"Signal tracking database initialized at {self.db_path}")
    
    def _load_active_signals(self) -> None:
        """Load active signals from database into memory"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT signal_id, symbol, direction, entry_price, stop_loss,
                       take_profit, confidence, reasoning, created_timestamp,
                       expiry_timestamp, is_active, confidence_factors,
                       market_conditions
                FROM signals 
                WHERE is_active = 1
            """)
            
            results = cursor.fetchall()
            
            for row in results:
                try:
                    confidence_factors = eval(row[11]) if row[11] else {}
                    market_conditions = eval(row[12]) if row[12] else {}
                    
                    entry = SignalHistoryEntry(
                        signal_id=row[0],
                        symbol=row[1],
                        direction=row[2],
                        entry_price=row[3],
                        stop_loss=row[4],
                        take_profit=row[5],
                        confidence=row[6],
                        reasoning=row[7],
                        created_timestamp=datetime.fromisoformat(row[8]),
                        expiry_timestamp=datetime.fromisoformat(row[9]),
                        is_active=bool(row[10]),
                        confidence_factors=confidence_factors,
                        market_conditions=market_conditions
                    )
                    
                    self.active_signals[row[0]] = entry
                except Exception as e:
                    logger.warning(f"Error loading active signal: {e}")
                    continue
        
        logger.info(f"Loaded {len(self.active_signals)} active signals")
    
    def track_signal(self,
                    trading_signal: TradingSignal,
                    confidence_result: ConfidenceResult,
                    market_conditions: Dict[str, Any] = None) -> str:
        """Track a new trading signal"""
        
        signal_id = self._generate_signal_id(trading_signal)
        expiry_timestamp = datetime.now(timezone.utc) + timedelta(hours=self.signal_expiry_hours)
        
        # Create history entry
        history_entry = SignalHistoryEntry(
            signal_id=signal_id,
            symbol=trading_signal.symbol,
            direction=trading_signal.direction.value,
            entry_price=trading_signal.entry_price,
            stop_loss=trading_signal.stop_loss,
            take_profit=trading_signal.take_profit,
            confidence=trading_signal.confidence,
            reasoning=trading_signal.reasoning,
            created_timestamp=trading_signal.timestamp,
            expiry_timestamp=expiry_timestamp,
            is_active=True,
            confidence_factors=confidence_result.confidence_breakdown,
            market_conditions=market_conditions or {}
        )
        
        # Store in database
        self._store_signal_in_db(history_entry)
        
        # Add to active signals cache
        self.active_signals[signal_id] = history_entry
        
        # Clean up expired signals
        self._cleanup_expired_signals()
        
        # Limit active signals
        self._limit_active_signals()
        
        logger.info(f"Tracking signal {signal_id} for {trading_signal.symbol} {trading_signal.direction.value}")
        
        return signal_id
    
    def record_signal_outcome(self,
                            signal_id: str,
                            exit_price: float,
                            exit_reason: str,
                            max_favorable_excursion: float = None,
                            max_adverse_excursion: float = None) -> SignalOutcome:
        """Record the outcome of a tracked signal"""
        
        if signal_id not in self.active_signals:
            # Try to load from database
            signal_entry = self._load_signal_from_db(signal_id)
            if not signal_entry:
                raise DataValidationError(
                    f"Signal {signal_id} not found in tracking system",
                    error_code="SIGNAL_NOT_FOUND",
                    context={"signal_id": signal_id}
                )
        else:
            signal_entry = self.active_signals[signal_id]
        
        # Calculate outcome metrics
        outcome = self._calculate_signal_outcome(
            signal_entry, exit_price, exit_reason,
            max_favorable_excursion, max_adverse_excursion
        )
        
        # Store outcome in database
        self._store_outcome_in_db(outcome)
        
        # Mark signal as inactive
        signal_entry.is_active = False
        self._update_signal_in_db(signal_entry)
        
        # Remove from active signals
        if signal_id in self.active_signals:
            del self.active_signals[signal_id]
        
        logger.info(f"Recorded outcome for signal {signal_id}: {exit_reason}, PnL: {outcome.pnl:.4f}")
        
        return outcome
    
    def get_signal_performance(self,
                             symbol: str = None,
                             direction: str = None,
                             days_back: int = 30) -> SignalPerformanceMetrics:
        """Get performance metrics for signals"""
        
        start_date = datetime.now() - timedelta(days=days_back)
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Build query with optional filters
            query = """
                SELECT 
                    COUNT(*) as total_signals,
                    SUM(CASE WHEN was_successful = 1 THEN 1 ELSE 0 END) as successful_signals,
                    SUM(CASE WHEN was_successful = 0 THEN 1 ELSE 0 END) as failed_signals,
                    AVG(pnl) as avg_pnl,
                    AVG(pnl_percentage) as avg_pnl_pct,
                    MAX(pnl) as best_pnl,
                    MIN(pnl) as worst_pnl,
                    AVG(duration_minutes) as avg_duration,
                    GROUP_CONCAT(pnl) as all_pnls
                FROM signal_outcomes 
                WHERE outcome_timestamp >= ?
            """
            
            params = [start_date.isoformat()]
            
            if symbol:
                query += " AND symbol = ?"
                params.append(symbol)
            
            if direction:
                query += " AND direction = ?"
                params.append(direction)
            
            cursor.execute(query, params)
            result = cursor.fetchone()
            
            if not result or result[0] == 0:
                return SignalPerformanceMetrics(
                    total_signals=0, successful_signals=0, failed_signals=0,
                    pending_signals=len(self.active_signals), win_rate=0.0,
                    average_pnl=0.0, average_pnl_percentage=0.0,
                    best_trade_pnl=0.0, worst_trade_pnl=0.0,
                    average_duration_minutes=0.0, sharpe_ratio=None,
                    max_drawdown=0.0, profit_factor=0.0
                )
            
            total, successful, failed, avg_pnl, avg_pnl_pct, best_pnl, worst_pnl, avg_duration, all_pnls = result
            
            # Calculate additional metrics
            win_rate = successful / total if total > 0 else 0.0
            
            # Calculate Sharpe ratio and max drawdown
            sharpe_ratio = None
            max_drawdown = 0.0
            profit_factor = 0.0
            
            if all_pnls:
                pnl_list = [float(x) for x in all_pnls.split(',') if x]
                if len(pnl_list) > 1:
                    pnl_std = stdev(pnl_list)
                    if pnl_std > 0:
                        sharpe_ratio = (avg_pnl or 0.0) / pnl_std
                
                # Calculate max drawdown
                cumulative_pnl = 0.0
                peak = 0.0
                for pnl in pnl_list:
                    cumulative_pnl += pnl
                    if cumulative_pnl > peak:
                        peak = cumulative_pnl
                    drawdown = peak - cumulative_pnl
                    if drawdown > max_drawdown:
                        max_drawdown = drawdown
                
                # Calculate profit factor
                gross_profit = sum(pnl for pnl in pnl_list if pnl > 0)
                gross_loss = abs(sum(pnl for pnl in pnl_list if pnl < 0))
                profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
            
            return SignalPerformanceMetrics(
                total_signals=total or 0,
                successful_signals=successful or 0,
                failed_signals=failed or 0,
                pending_signals=len(self.active_signals),
                win_rate=win_rate,
                average_pnl=avg_pnl or 0.0,
                average_pnl_percentage=avg_pnl_pct or 0.0,
                best_trade_pnl=best_pnl or 0.0,
                worst_trade_pnl=worst_pnl or 0.0,
                average_duration_minutes=avg_duration or 0.0,
                sharpe_ratio=sharpe_ratio,
                max_drawdown=max_drawdown,
                profit_factor=profit_factor
            )  
  
    def get_active_signals(self, symbol: str = None) -> List[SignalHistoryEntry]:
        """Get currently active signals"""
        active = list(self.active_signals.values())
        
        if symbol:
            active = [s for s in active if s.symbol == symbol]
        
        return active
    
    def expire_signal(self, signal_id: str, reason: str = "EXPIRED") -> bool:
        """Manually expire a signal"""
        if signal_id in self.active_signals:
            signal_entry = self.active_signals[signal_id]
            
            # Record outcome as expired
            outcome = SignalOutcome(
                signal_id=signal_id,
                symbol=signal_entry.symbol,
                direction=signal_entry.direction,
                entry_price=signal_entry.entry_price,
                exit_price=None,
                exit_reason=reason,
                pnl=None,
                pnl_percentage=None,
                duration_minutes=None,
                max_favorable_excursion=None,
                max_adverse_excursion=None,
                outcome_timestamp=datetime.now(),
                was_successful=None
            )
            
            # Store outcome
            self._store_outcome_in_db(outcome)
            
            # Mark as inactive
            signal_entry.is_active = False
            self._update_signal_in_db(signal_entry)
            
            # Remove from active signals
            del self.active_signals[signal_id]
            
            logger.info(f"Expired signal {signal_id}: {reason}")
            return True
        
        return False
    
    def refresh_signal(self, signal_id: str, new_expiry_hours: int = None) -> bool:
        """Refresh a signal's expiry time"""
        if signal_id in self.active_signals:
            signal_entry = self.active_signals[signal_id]
            
            # Update expiry time
            hours = new_expiry_hours or self.signal_expiry_hours
            signal_entry.expiry_timestamp = datetime.now(timezone.utc) + timedelta(hours=hours)
            
            # Update in database
            self._update_signal_in_db(signal_entry)
            
            logger.info(f"Refreshed signal {signal_id} for {hours} hours")
            return True
        
        return False
    
    def get_signal_history(self,
                          symbol: Optional[str] = None,
                          days_back: int = 30,
                          limit: int = 100) -> List[SignalHistoryEntry]:
        """Get historical signals"""
        start_date = datetime.now() - timedelta(days=days_back)
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            query = """
                SELECT signal_id, symbol, direction, entry_price, stop_loss, 
                       take_profit, confidence, reasoning, created_timestamp,
                       expiry_timestamp, is_active, confidence_factors, 
                       market_conditions
                FROM signals 
                WHERE created_timestamp >= ?
            """
            params = [start_date.isoformat()]
            
            if symbol:
                query += " AND symbol = ?"
                params.append(symbol)
            
            query += " ORDER BY created_timestamp DESC LIMIT ?"
            params.append(limit)
            
            cursor.execute(query, params)
            results = cursor.fetchall()
            
            history = []
            for row in results:
                try:
                    confidence_factors = eval(row[11]) if row[11] else {}
                    market_conditions = eval(row[12]) if row[12] else {}
                    
                    entry = SignalHistoryEntry(
                        signal_id=row[0],
                        symbol=row[1],
                        direction=row[2],
                        entry_price=row[3],
                        stop_loss=row[4],
                        take_profit=row[5],
                        confidence=row[6],
                        reasoning=row[7],
                        created_timestamp=datetime.fromisoformat(row[8]),
                        expiry_timestamp=datetime.fromisoformat(row[9]),
                        is_active=bool(row[10]),
                        confidence_factors=confidence_factors,
                        market_conditions=market_conditions
                    )
                    history.append(entry)
                except Exception as e:
                    logger.warning(f"Error parsing signal history entry: {e}")
                    continue
            
            return history
    
    def get_signal_outcomes(self,
                           symbol: Optional[str] = None,
                           days_back: int = 30,
                           limit: int = 100) -> List[SignalOutcome]:
        """Get signal outcomes"""
        start_date = datetime.now() - timedelta(days=days_back)
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            query = """
                SELECT signal_id, symbol, direction, entry_price, exit_price,
                       exit_reason, pnl, pnl_percentage, duration_minutes,
                       max_favorable_excursion, max_adverse_excursion,
                       outcome_timestamp, was_successful
                FROM signal_outcomes 
                WHERE outcome_timestamp >= ?
            """
            params = [start_date.isoformat()]
            
            if symbol:
                query += " AND symbol = ?"
                params.append(symbol)
            
            query += " ORDER BY outcome_timestamp DESC LIMIT ?"
            params.append(limit)
            
            cursor.execute(query, params)
            results = cursor.fetchall()
            
            outcomes = []
            for row in results:
                try:
                    outcome = SignalOutcome(
                        signal_id=row[0],
                        symbol=row[1],
                        direction=row[2],
                        entry_price=row[3],
                        exit_price=row[4],
                        exit_reason=row[5],
                        pnl=row[6],
                        pnl_percentage=row[7],
                        duration_minutes=row[8],
                        max_favorable_excursion=row[9],
                        max_adverse_excursion=row[10],
                        outcome_timestamp=datetime.fromisoformat(row[11]),
                        was_successful=bool(row[12]) if row[12] is not None else None
                    )
                    outcomes.append(outcome)
                except Exception as e:
                    logger.warning(f"Error parsing signal outcome: {e}")
                    continue
            
            return outcomes
    
    def cleanup_old_data(self, days_to_keep: int = 90) -> int:
        """Clean up old signal data"""
        cutoff_date = datetime.now() - timedelta(days=days_to_keep)
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Delete old outcomes
            cursor.execute(
                "DELETE FROM signal_outcomes WHERE outcome_timestamp < ?",
                [cutoff_date.isoformat()]
            )
            outcomes_deleted = cursor.rowcount
            
            # Delete old inactive signals
            cursor.execute(
                "DELETE FROM signals WHERE created_timestamp < ? AND is_active = 0",
                [cutoff_date.isoformat()]
            )
            signals_deleted = cursor.rowcount
            
            conn.commit()
            
        logger.info(f"Cleaned up {signals_deleted} old signals and {outcomes_deleted} outcomes")
        return signals_deleted + outcomes_deleted
    
    def _load_active_signals(self) -> None:
        """Load active signals from database into memory"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT signal_id, symbol, direction, entry_price, stop_loss,
                       take_profit, confidence, reasoning, created_timestamp,
                       expiry_timestamp, is_active, confidence_factors,
                       market_conditions
                FROM signals 
                WHERE is_active = 1
            """)
            
            results = cursor.fetchall()
            
            for row in results:
                try:
                    confidence_factors = eval(row[11]) if row[11] else {}
                    market_conditions = eval(row[12]) if row[12] else {}
                    
                    entry = SignalHistoryEntry(
                        signal_id=row[0],
                        symbol=row[1],
                        direction=row[2],
                        entry_price=row[3],
                        stop_loss=row[4],
                        take_profit=row[5],
                        confidence=row[6],
                        reasoning=row[7],
                        created_timestamp=datetime.fromisoformat(row[8]),
                        expiry_timestamp=datetime.fromisoformat(row[9]),
                        is_active=bool(row[10]),
                        confidence_factors=confidence_factors,
                        market_conditions=market_conditions
                    )
                    
                    self.active_signals[row[0]] = entry
                except Exception as e:
                    logger.warning(f"Error loading active signal: {e}")
                    continue
        
        logger.info(f"Loaded {len(self.active_signals)} active signals")
    
    def _generate_signal_id(self, trading_signal: TradingSignal) -> str:
        """Generate unique signal ID"""
        timestamp_str = trading_signal.timestamp.strftime("%Y%m%d_%H%M%S")
        unique_id = str(uuid.uuid4())[:8]
        return f"{trading_signal.symbol}_{timestamp_str}_{unique_id}"
    
    def _store_signal_in_db(self, signal_entry: SignalHistoryEntry) -> None:
        """Store signal in database"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT OR REPLACE INTO signals 
                (signal_id, symbol, direction, entry_price, stop_loss, take_profit,
                 confidence, reasoning, created_timestamp, expiry_timestamp,
                 is_active, confidence_factors, market_conditions)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                signal_entry.signal_id,
                signal_entry.symbol,
                signal_entry.direction,
                signal_entry.entry_price,
                signal_entry.stop_loss,
                signal_entry.take_profit,
                signal_entry.confidence,
                signal_entry.reasoning,
                signal_entry.created_timestamp.isoformat(),
                signal_entry.expiry_timestamp.isoformat(),
                int(signal_entry.is_active),
                str(signal_entry.confidence_factors),
                str(signal_entry.market_conditions)
            ])
            
            conn.commit()
    
    def _update_signal_in_db(self, signal_entry: SignalHistoryEntry) -> None:
        """Update signal in database"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                UPDATE signals 
                SET is_active = ?, expiry_timestamp = ?, confidence = ?, reasoning = ?
                WHERE signal_id = ?
            """, [
                int(signal_entry.is_active),
                signal_entry.expiry_timestamp.isoformat(),
                signal_entry.confidence,
                signal_entry.reasoning,
                signal_entry.signal_id
            ])
            
            conn.commit()
    
    def _load_signal_from_db(self, signal_id: str) -> Optional[SignalHistoryEntry]:
        """Load signal from database"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT signal_id, symbol, direction, entry_price, stop_loss,
                       take_profit, confidence, reasoning, created_timestamp,
                       expiry_timestamp, is_active, confidence_factors,
                       market_conditions
                FROM signals 
                WHERE signal_id = ?
            """, [signal_id])
            
            row = cursor.fetchone()
            if not row:
                return None
            
            try:
                confidence_factors = eval(row[11]) if row[11] else {}
                market_conditions = eval(row[12]) if row[12] else {}
                
                return SignalHistoryEntry(
                    signal_id=row[0],
                    symbol=row[1],
                    direction=row[2],
                    entry_price=row[3],
                    stop_loss=row[4],
                    take_profit=row[5],
                    confidence=row[6],
                    reasoning=row[7],
                    created_timestamp=datetime.fromisoformat(row[8]),
                    expiry_timestamp=datetime.fromisoformat(row[9]),
                    is_active=bool(row[10]),
                    confidence_factors=confidence_factors,
                    market_conditions=market_conditions
                )
            except Exception as e:
                logger.warning(f"Error loading signal from DB: {e}")
                return None
    
    def _calculate_signal_outcome(self,
                                 signal_entry: SignalHistoryEntry,
                                 exit_price: float,
                                 exit_reason: str,
                                 max_favorable_excursion: Optional[float] = None,
                                 max_adverse_excursion: Optional[float] = None) -> SignalOutcome:
        """Calculate signal outcome metrics"""
        
        # Calculate PnL
        if signal_entry.direction == "LONG":
            pnl = exit_price - signal_entry.entry_price
        else:  # SHORT
            pnl = signal_entry.entry_price - exit_price
        
        # Calculate PnL percentage
        pnl_percentage = (pnl / signal_entry.entry_price) * 100
        
        # Calculate duration
        duration_minutes = int(
            (datetime.now(timezone.utc) - signal_entry.created_timestamp).total_seconds() / 60
        )
        
        # Determine if successful
        was_successful = None
        if exit_reason in ["TAKE_PROFIT"]:
            was_successful = True
        elif exit_reason in ["STOP_LOSS"]:
            was_successful = False
        # For MANUAL or EXPIRED, we determine based on PnL
        elif pnl is not None:
            was_successful = pnl > 0
        
        return SignalOutcome(
            signal_id=signal_entry.signal_id,
            symbol=signal_entry.symbol,
            direction=signal_entry.direction,
            entry_price=signal_entry.entry_price,
            exit_price=exit_price,
            exit_reason=exit_reason,
            pnl=pnl,
            pnl_percentage=pnl_percentage,
            duration_minutes=duration_minutes,
            max_favorable_excursion=max_favorable_excursion,
            max_adverse_excursion=max_adverse_excursion,
            outcome_timestamp=datetime.now(timezone.utc),
            was_successful=was_successful
        )
    
    def _store_outcome_in_db(self, outcome: SignalOutcome) -> None:
        """Store signal outcome in database"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO signal_outcomes 
                (signal_id, symbol, direction, entry_price, exit_price,
                 exit_reason, pnl, pnl_percentage, duration_minutes,
                 max_favorable_excursion, max_adverse_excursion,
                 outcome_timestamp, was_successful)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                outcome.signal_id,
                outcome.symbol,
                outcome.direction,
                outcome.entry_price,
                outcome.exit_price,
                outcome.exit_reason,
                outcome.pnl,
                outcome.pnl_percentage,
                outcome.duration_minutes,
                outcome.max_favorable_excursion,
                outcome.max_adverse_excursion,
                outcome.outcome_timestamp.isoformat(),
                int(outcome.was_successful) if outcome.was_successful is not None else None
            ])
            
            conn.commit()
    
    def _cleanup_expired_signals(self) -> None:
        """Clean up expired signals"""
        current_time = datetime.now(timezone.utc)
        expired_signals = []
        
        for signal_id, signal_entry in self.active_signals.items():
            if current_time > signal_entry.expiry_timestamp:
                expired_signals.append(signal_id)
        
        for signal_id in expired_signals:
            self.expire_signal(signal_id, "AUTO_EXPIRED")
        
        if expired_signals:
            logger.info(f"Auto-expired {len(expired_signals)} signals")
    
    def _limit_active_signals(self) -> None:
        """Limit number of active signals"""
        if len(self.active_signals) > self.max_active_signals:
            # Sort by creation time and expire oldest
            sorted_signals = sorted(
                self.active_signals.items(),
                key=lambda x: x[1].created_timestamp
            )
            
            excess_count = len(self.active_signals) - self.max_active_signals
            for i in range(excess_count):
                signal_id = sorted_signals[i][0]
                self.expire_signal(signal_id, "CAPACITY_LIMIT")
            
            logger.info(f"Expired {excess_count} signals due to capacity limit")