"""Core data models for the AI Forex Trading Bot"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional
from src.exceptions import DataValidationError


logger = logging.getLogger(__name__)


class SignalType(Enum):
    """Trading signal types"""
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class Direction(Enum):
    """Trading direction"""
    LONG = "LONG"
    SHORT = "SHORT"


class OrderType(Enum):
    """Order types"""
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"


class OrderStatus(Enum):
    """Order status"""
    PENDING = "PENDING"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class ExitPolicy(Enum):
    """
    Defines distinct trade management behaviors/strategies.
    """
    STANDARD = "STANDARD"          # Balanced approach (default)
    SCALP = "SCALP"                # Tight stops, quick profit taking (conf < 0.6)
    TREND_FOLLOW = "TREND_FOLLOW"  # Loose trailing, varying TP (conf > 0.8)
    MEAN_REVERT = "MEAN_REVERT"    # Fixed targets, tight invalidation
    
    
@dataclass
class MarketData:
    """Market data structure with validation"""
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    bid: float
    ask: float
    spread: float
    
    def __post_init__(self):
        """Validate market data after initialization"""
        self.validate()
    
    def validate(self) -> None:
        """Validate market data integrity"""
        # Validate symbol format (e.g., EUR/USD, GBP/JPY)
        if not self._is_valid_symbol(self.symbol):
            raise DataValidationError(
                f"Invalid symbol format: {self.symbol}",
                error_code="INVALID_SYMBOL",
                context={"symbol": self.symbol}
            )
        
        # Validate timestamp is not too far in future (allow for server time differences and historical data)
        max_future_time = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=1)
        if self.timestamp > max_future_time:
            raise DataValidationError(
                f"Timestamp too far in the future: {self.timestamp}",
                error_code="FUTURE_TIMESTAMP",
                context={"timestamp": self.timestamp}
            )
        
        # Validate OHLC relationships
        if not (self.low <= self.open <= self.high and 
                self.low <= self.close <= self.high):
            raise DataValidationError(
                "Invalid OHLC relationship: low <= open,close <= high",
                error_code="INVALID_OHLC",
                context={
                    "open": self.open, "high": self.high,
                    "low": self.low, "close": self.close
                }
            )
        
        # Validate positive values
        prices = [self.open, self.high, self.low, self.close, self.bid, self.ask]
        if any(val <= 0 for val in prices):
            raise DataValidationError(
                "Price values must be positive",
                error_code="NEGATIVE_PRICE",
                context={"prices": prices},
            )
        
        # Validate volume is non-negative
        if self.volume < 0:
            raise DataValidationError(
                f"Volume cannot be negative: {self.volume}",
                error_code="NEGATIVE_VOLUME",
                context={"volume": self.volume}
            )
        
        # Validate bid/ask relationship
        if self.bid >= self.ask:
            raise DataValidationError(
                "Bid must be less than ask",
                error_code="INVALID_BID_ASK",
                context={"bid": self.bid, "ask": self.ask}
            )
        
        # Validate spread calculation with 5.0 pip tolerance to allow for 
        # high-frequency broker feed drift and spread floors during volatility.
        calculated_spread = self.ask - self.bid
        pip_size = 0.01 if 'JPY' in self.symbol else 0.0001
        tolerance = 5.0 * pip_size  # FIX: Standardized to 5.0 pips
        
        if abs(self.spread - calculated_spread) > tolerance + 1e-7:
            raise DataValidationError(
                "Spread mismatch exceeds 5.0 pip tolerance",
                error_code="INVALID_SPREAD",
                context={
                    "spread": self.spread,
                    "calculated_spread": calculated_spread,
                    "tolerance": tolerance,
                    "bid": self.bid,
                    "ask": self.ask,
                },
            )
    
    def _is_valid_symbol(self, symbol: str) -> bool:
        """Validate forex symbol format - accepts both USD/JPY and USDJPY formats"""
        # Pattern accepts standard format (EUR/USD) or MT5 format (EURUSD)
        pattern = r'^[A-Z]{3}/?[A-Z]{3}$'
        return bool(re.match(pattern, symbol))
    
    def get_mid_price(self) -> float:
        """Calculate mid price from bid/ask"""
        return (self.bid + self.ask) / 2
    
    def is_stale(self, max_age_seconds: int = 60) -> bool:
        """Check if data is stale"""
        age = (datetime.now(timezone.utc) - self.timestamp).total_seconds()
        return age > max_age_seconds


@dataclass
class SentimentResult:
    """Sentiment analysis result with validation"""
    symbol: str
    sentiment_score: float  # -1.0 to 1.0
    confidence: float      # 0.0 to 1.0
    reasoning: str
    sources: List[str]
    timestamp: datetime
    
    def __post_init__(self):
        """Validate sentiment result after initialization"""
        self.validate()
    
    def validate(self) -> None:
        """Validate sentiment analysis result"""
        # Validate symbol format
        if not self._is_valid_symbol(self.symbol):
            raise DataValidationError(
                f"Invalid symbol format: {self.symbol}",
                error_code="INVALID_SYMBOL",
                context={"symbol": self.symbol}
            )
        
        # Validate sentiment score range
        if not -1.0 <= self.sentiment_score <= 1.0:
            raise DataValidationError(
                f"Sentiment score out of range: {self.sentiment_score}",
                error_code="INVALID_SENTIMENT_RANGE",
                context={"sentiment_score": self.sentiment_score},
            )
        
        # Validate confidence range
        if not 0.0 <= self.confidence <= 1.0:
            raise DataValidationError(
                f"Confidence must be between 0.0 and 1.0: {self.confidence}",
                error_code="INVALID_CONFIDENCE_RANGE",
                context={"confidence": self.confidence},
            )
        
        # Validate reasoning is not empty
        if not self.reasoning or not self.reasoning.strip():
            raise DataValidationError(
                "Reasoning cannot be empty",
                error_code="EMPTY_REASONING",
                context={"reasoning": self.reasoning}
            )
        
        # Validate sources list
        if not self.sources:
            raise DataValidationError(
                "Sources list cannot be empty",
                error_code="EMPTY_SOURCES",
                context={"sources": self.sources}
            )
        
        # Validate each source is not empty
        for i, source in enumerate(self.sources):
            if not source or not source.strip():
                raise DataValidationError(
                    f"Source at index {i} cannot be empty",
                    error_code="EMPTY_SOURCE",
                    context={"source_index": i, "source": source}
                )
        
        # Validate timestamp (allow 1 day in future for historical data and server time differences)
        max_future_time = datetime.now(timezone.utc) + timedelta(days=1)
        if self.timestamp > max_future_time:
            raise DataValidationError(
                f"Timestamp cannot be in the future: {self.timestamp}",
                error_code="FUTURE_TIMESTAMP",
                context={"timestamp": self.timestamp}
            )
    
    def _is_valid_symbol(self, symbol: str) -> bool:
        """Validate forex symbol format - accepts both USD/JPY and USDJPY formats"""
        # Pattern accepts standard format (EUR/USD) or MT5 format (EURUSD)
        pattern = r'^[A-Z]{3}/?[A-Z]{3}$'
        return bool(re.match(pattern, symbol))
    
    def is_bullish(self, threshold: float = 0.1) -> bool:
        """Check if sentiment is bullish"""
        return self.sentiment_score > threshold
    
    def is_bearish(self, threshold: float = -0.1) -> bool:
        """Check if sentiment is bearish"""
        return self.sentiment_score < threshold
    
    def is_neutral(self, threshold: float = 0.1) -> bool:
        """Check if sentiment is neutral"""
        return abs(self.sentiment_score) <= threshold
    
    def is_high_confidence(self, threshold: float = 0.7) -> bool:
        """Check if confidence is high"""
        return self.confidence >= threshold


@dataclass
class TechnicalSignal:
    """Technical analysis signal with validation"""
    symbol: str
    signal_type: SignalType
    strength: float         # 0.0 to 1.0
    indicators: Dict[str, float]
    timestamp: datetime
    
    def __post_init__(self):
        """Validate technical signal after initialization"""
        self.validate()
    
    def validate(self) -> None:
        """Validate technical signal"""
        # Validate symbol format
        if not self._is_valid_symbol(self.symbol):
            raise DataValidationError(
                f"Invalid symbol format: {self.symbol}",
                error_code="INVALID_SYMBOL",
                context={"symbol": self.symbol}
            )
        
        # Validate signal type
        if not isinstance(self.signal_type, SignalType):
            raise DataValidationError(
                f"Invalid signal type: {self.signal_type}",
                error_code="INVALID_SIGNAL_TYPE",
                context={"signal_type": self.signal_type}
            )
        
        # Validate strength range
        if not 0.0 <= self.strength <= 1.0:
            raise DataValidationError(
                f"Strength must be between 0.0 and 1.0: {self.strength}",
                error_code="INVALID_STRENGTH_RANGE",
                context={"strength": self.strength}
            )
        
        # Validate indicators dictionary
        if not self.indicators:
            raise DataValidationError(
                "Indicators dictionary cannot be empty",
                error_code="EMPTY_INDICATORS",
                context={"indicators": self.indicators}
            )
        
        # Validate indicator values are numeric
        for name, value in self.indicators.items():
            if not isinstance(value, (int, float)):
                raise DataValidationError(
                    f"Indicator '{name}' must be numeric: {value}",
                    error_code="NON_NUMERIC_INDICATOR",
                    context={"indicator_name": name, "indicator_value": value}
                )
            
            # Check for NaN or infinite values
            if not (-float('inf') < value < float('inf')):
                raise DataValidationError(
                    f"Indicator '{name}' has invalid value: {value}",
                    error_code="INVALID_INDICATOR_VALUE",
                    context={"indicator_name": name, "indicator_value": value}
                )
        
        # Validate timestamp (allow 1 day in future for historical data and server time differences)
        max_future_time = datetime.now(timezone.utc) + timedelta(days=1)
        if self.timestamp > max_future_time:
            raise DataValidationError(
                f"Timestamp cannot be in the future: {self.timestamp}",
                error_code="FUTURE_TIMESTAMP",
                context={"timestamp": self.timestamp}
            )
    
    def _is_valid_symbol(self, symbol: str) -> bool:
        """Validate forex symbol format - accepts both USD/JPY and USDJPY formats"""
        # Pattern accepts standard format (EUR/USD) or MT5 format (EURUSD)
        pattern = r'^[A-Z]{3}/?[A-Z]{3}$'
        return bool(re.match(pattern, symbol))
    
    def is_strong_signal(self, threshold: float = 0.7) -> bool:
        """Check if signal is strong"""
        return self.strength >= threshold
    
    def get_indicator(self, name: str) -> Optional[float]:
        """Get specific indicator value"""
        return self.indicators.get(name)


@dataclass
class TradingSignal:
    """Combined trading signal with validation"""
    symbol: str
    direction: Direction
    entry_price: float
    stop_loss: float
    take_profit: float
    position_size: float
    confidence: float
    reasoning: str
    timestamp: datetime
    rr_ratio: float = 0.0
    market_condition: Optional[str] = None
    is_ml_override: bool = False
    trade_tier: str = "REJECTED"
    exit_policy: ExitPolicy = ExitPolicy.STANDARD
    predicted_exit_policy: Optional[ExitPolicy] = None # ML Prediction
    policy_confidence: float = 0.0                     # ML Confidence
    entry_features: Optional[List[float]] = None       # Features used for ML
    regime_label: str = "NEUTRAL"                      # Market regime label
    price_action_score: float = 0.0                   # Mathematical price action conviction
    pa_type: str = "NONE"                             # Price action classifier label
    ml_accuracy: float = 0.5                           # ML model accuracy (PATCH: Force-Sync)
    quality_score: float = 0.0                         # Quality score (PATCH: Force-Sync)
    forced_execution: bool = False                     # Force admission for high conf (PATCH: Force-Sync)
    expectancy: Optional[float] = None                 # TOTAL TRIGGER RELEASE: Explicit expectancy sync to prevent 1.00R default
    source: str = "standard"                           # signal origin tag (e.g., synthetic/standard)
    rl_action: Optional[str] = None                    # RL tactic action name
    rl_action_id: Optional[int] = None                 # RL tactic action id
    rl_multiplier: Optional[float] = None              # RL size multiplier
    rl_decision_id: Optional[str] = None               # RL decision id for outcome mapping
    rl_shadow_mode: bool = False                       # RL shadow mode active
    rl_warmup_complete: bool = False                   # RL warm-up gate status
    levels_finalized: bool = False                     # Hard-lock signal levels after admission
    locked: bool = False                               # Alias: immutable SL/TP after admission (V12)
    admission_locked: bool = False                     # NEW: Bypasses "Admission Tug-of-War" downstream validators
    # ===== FIX #1: INDICATOR_CONFLUENCE ATTRIBUTE =====
    indicator_confluence: float = 0.0                  # Indicator confluence score (prevents AttributeError)
    # ISSUE #2 FIX: Locked RR ratio to prevent drift during execution
    locked_rr_ratio: float = 0.0                       # Immutable RR ratio after finalize_levels()

    def __setattr__(self, name: str, value: Any) -> None:
        if name in {"stop_loss", "take_profit"} and (
            bool(getattr(self, "level_lock_enabled", False))
            or bool(getattr(self, "levels_finalized", False))
            or bool(getattr(self, "locked", False))
        ):
            locked_name = "locked_stop_loss" if name == "stop_loss" else "locked_take_profit"
            locked_value = getattr(self, locked_name, None)
            if locked_value is not None:
                try:
                    incoming = float(value)
                    locked = float(locked_value)
                    if abs(incoming - locked) > 1e-10:
                        logger.critical(
                            "[LEVEL_LOCK_ENFORCED] %s | REJECTED %s mutation after admission. Locked=%.5f Incoming=%.5f | IMMUTABLE ENFORCEMENT ACTIVE",
                            getattr(self, "symbol", "UNKNOWN"),
                            name,
                            locked,
                            incoming,
                        )
                        value = locked_value
                except Exception:
                    logger.critical(
                        "[LEVEL_LOCK_ENFORCED] %s | REJECTED %s mutation after admission. Enforcing locked value.",
                        getattr(self, "symbol", "UNKNOWN"),
                        name,
                    )
                    value = locked_value
        object.__setattr__(self, name, value)

    def finalize_levels(self) -> None:
        """
        Hard-lock SL/TP/RR after admission. This enforces a linear execution path:
        Accept -> Lock -> Execute. Any recalculation attempts are refused.
        
        CRITICAL FIX: Sets admission_locked=True to bypass "Admission Tug-of-War"
        where downstream validators (AccuracyGate, RiskGuard) would reject admitted trades.
        
        Also locks RR ratio to prevent "Recalculation Drift" where R:R changes mid-execution.
        """
        try:
            object.__setattr__(self, "locked_stop_loss", float(getattr(self, "stop_loss", 0.0) or 0.0))
            object.__setattr__(self, "locked_take_profit", float(getattr(self, "take_profit", 0.0) or 0.0))
            object.__setattr__(self, "locked_rr_ratio", float(getattr(self, "rr_ratio", 1.0) or 1.0))
        except Exception:
            pass
        object.__setattr__(self, "level_lock_enabled", True)
        object.__setattr__(self, "levels_finalized", True)
        object.__setattr__(self, "locked", True)
        object.__setattr__(self, "admission_locked", True)  # NEW: Bypass Tug-of-War
        
        logger.critical(
            "[LEVEL_LOCK_ENFORCED] %s | SL=%.5f TP=%.5f RR=%.3fR | IMMUTABLE LOCK ACTIVATED | admission_locked=True bypasses downstream veto | RR DRIFT PREVENTED",
            getattr(self, "symbol", "UNKNOWN"),
            self.locked_stop_loss,
            self.locked_take_profit,
            self.locked_rr_ratio,
        )

    @property
    def sl(self) -> float:
        return self.stop_loss

    @sl.setter
    def sl(self, value: float) -> None:
        self.stop_loss = value

    @property
    def tp(self) -> float:
        return self.take_profit

    @tp.setter
    def tp(self, value: float) -> None:
        self.take_profit = value
    
    def __post_init__(self):
        """Validate trading signal after initialization"""
        if float(getattr(self, "rr_ratio", 0.0) or 0.0) <= 0.0:
            object.__setattr__(self, "rr_ratio", float(self.calculate_risk_reward_ratio()))
        self.validate()
    
    def validate(self) -> None:
        """Validate trading signal"""
        # Validate symbol format
        if not self._is_valid_symbol(self.symbol):
            raise DataValidationError(
                f"Invalid symbol format: {self.symbol}",
                error_code="INVALID_SYMBOL",
                context={"symbol": self.symbol}
            )
        
        # Validate direction
        if not isinstance(self.direction, Direction):
            raise DataValidationError(
                f"Invalid direction: {self.direction}",
                error_code="INVALID_DIRECTION",
                context={"direction": self.direction}
            )
        
        # Validate positive prices
        prices = [self.entry_price, self.stop_loss, self.take_profit]
        if any(price <= 0 for price in prices):
            raise DataValidationError(
                "All prices must be positive",
                error_code="NEGATIVE_PRICE",
                context={
                    "entry_price": self.entry_price,
                    "stop_loss": self.stop_loss,
                    "take_profit": self.take_profit
                }
            )
        
        # Validate stop loss and take profit relationships
        if self.direction == Direction.LONG:
            if self.stop_loss >= self.entry_price:
                raise DataValidationError(
                    "For LONG positions, stop loss must be below entry price",
                    error_code="INVALID_STOP_LOSS",
                    context={
                        "direction": self.direction.value,
                        "entry_price": self.entry_price,
                        "stop_loss": self.stop_loss
                    }
                )
            if self.take_profit <= self.entry_price:
                raise DataValidationError(
                    "For LONG positions, take profit must be above entry price",
                    error_code="INVALID_TAKE_PROFIT",
                    context={
                        "direction": self.direction.value,
                        "entry_price": self.entry_price,
                        "take_profit": self.take_profit
                    }
                )
        else:  # SHORT position
            if self.stop_loss <= self.entry_price:
                raise DataValidationError(
                    "For SHORT positions, stop loss must be above entry price",
                    error_code="INVALID_STOP_LOSS",
                    context={
                        "direction": self.direction.value,
                        "entry_price": self.entry_price,
                        "stop_loss": self.stop_loss
                    }
                )
            if self.take_profit >= self.entry_price:
                raise DataValidationError(
                    "For SHORT positions, take profit must be below entry price",
                    error_code="INVALID_TAKE_PROFIT",
                    context={
                        "direction": self.direction.value,
                        "entry_price": self.entry_price,
                        "take_profit": self.take_profit
                    }
                )
        
        # Validate position size
        if not 0.0 < self.position_size <= 1.0:
            raise DataValidationError(
                f"Position size must be between 0.0 and 1.0: {self.position_size}",
                error_code="INVALID_POSITION_SIZE",
                context={"position_size": self.position_size}
            )
        
        # Validate confidence
        if not 0.0 <= self.confidence <= 1.0:
            raise DataValidationError(
                f"Confidence must be between 0.0 and 1.0: {self.confidence}",
                error_code="INVALID_CONFIDENCE_RANGE",
                context={"confidence": self.confidence}
            )
        
        # Validate reasoning
        if not self.reasoning or not self.reasoning.strip():
            raise DataValidationError(
                "Reasoning cannot be empty",
                error_code="EMPTY_REASONING",
                context={"reasoning": self.reasoning}
            )
        
        # Validate timestamp (allow 1 day in future for historical data and server time differences)
        max_future_time = datetime.now(timezone.utc) + timedelta(days=1)
        if self.timestamp > max_future_time:
            raise DataValidationError(
                f"Timestamp cannot be in the future: {self.timestamp}",
                error_code="FUTURE_TIMESTAMP",
                context={"timestamp": self.timestamp}
            )
    
    def _is_valid_symbol(self, symbol: str) -> bool:
        """Validate forex symbol format - accepts both USD/JPY and USDJPY formats"""
        # Pattern accepts standard format (EUR/USD) or MT5 format (EURUSD)
        pattern = r'^[A-Z]{3}/?[A-Z]{3}$'
        return bool(re.match(pattern, symbol))
    
    def calculate_risk_reward_ratio(self) -> float:
        """Calculate risk-reward ratio"""
        if self.direction == Direction.LONG:
            risk = self.entry_price - self.stop_loss
            reward = self.take_profit - self.entry_price
        else:  # SHORT
            risk = self.stop_loss - self.entry_price
            reward = self.entry_price - self.take_profit
        
        return reward / risk if risk > 0 else 0.0
    
    def is_high_confidence(self, threshold: float = 0.7) -> bool:
        """Check if signal has high confidence"""
        return self.confidence >= threshold


@dataclass
class Order:
    """Trading order with validation"""
    order_id: str
    symbol: str
    order_type: OrderType
    direction: Direction
    quantity: float
    price: Optional[float]
    stop_loss: Optional[float]
    take_profit: Optional[float]
    status: OrderStatus
    created_at: datetime
    exit_policy: ExitPolicy = ExitPolicy.STANDARD
    predicted_exit_policy: Optional[ExitPolicy] = None
    policy_confidence: float = 0.0
    entry_features: Optional[List[float]] = None
    regime_label: str = "NEUTRAL"
    forced_execution: bool = False  # TOTAL TRIGGER RELEASE V10: Immediate-MT5 bypass

    def __setattr__(self, name: str, value: Any) -> None:
        if name in {"stop_loss", "take_profit"} and bool(getattr(self, "level_lock_enabled", False)):
            locked_name = "locked_stop_loss" if name == "stop_loss" else "locked_take_profit"
            locked_value = getattr(self, locked_name, None)
            if locked_value is not None:
                try:
                    incoming = float(value)
                    locked = float(locked_value)
                    if abs(incoming - locked) > 1e-10:
                        value = locked_value
                except Exception:
                    value = locked_value
        object.__setattr__(self, name, value)
    
    def __post_init__(self):
        """Validate order after initialization"""
        self.validate()
    
    def validate(self) -> None:
        """Validate trading order"""
        # Validate order ID
        if not self.order_id or not self.order_id.strip():
            raise DataValidationError(
                "Order ID cannot be empty",
                error_code="EMPTY_ORDER_ID",
                context={"order_id": self.order_id}
            )
        
        # Validate symbol format
        if not self._is_valid_symbol(self.symbol):
            raise DataValidationError(
                f"Invalid symbol format: {self.symbol}",
                error_code="INVALID_SYMBOL",
                context={"symbol": self.symbol}
            )
        
        # Validate enums
        if not isinstance(self.order_type, OrderType):
            raise DataValidationError(
                f"Invalid order type: {self.order_type}",
                error_code="INVALID_ORDER_TYPE",
                context={"order_type": self.order_type}
            )
        
        if not isinstance(self.direction, Direction):
            raise DataValidationError(
                f"Invalid direction: {self.direction}",
                error_code="INVALID_DIRECTION",
                context={"direction": self.direction}
            )
        
        if not isinstance(self.status, OrderStatus):
            raise DataValidationError(
                f"Invalid order status: {self.status}",
                error_code="INVALID_ORDER_STATUS",
                context={"status": self.status}
            )
        
        # Validate quantity
        if self.quantity <= 0:
            raise DataValidationError(
                f"Quantity must be positive: {self.quantity}",
                error_code="INVALID_QUANTITY",
                context={"quantity": self.quantity}
            )
        
        # Validate price for limit orders
        if self.order_type == OrderType.LIMIT and (
            self.price is None or self.price <= 0
        ):
            raise DataValidationError(
                "Limit orders must have a positive price",
                error_code="MISSING_LIMIT_PRICE",
                context={
                    "order_type": self.order_type.value,
                    "price": self.price,
                },
            )
        
        # Validate stop loss and take profit if provided
        if self.stop_loss is not None and self.stop_loss <= 0:
            raise DataValidationError(
                f"Stop loss must be positive: {self.stop_loss}",
                error_code="INVALID_STOP_LOSS",
                context={"stop_loss": self.stop_loss}
            )
        
        if self.take_profit is not None and self.take_profit <= 0:
            raise DataValidationError(
                f"Take profit must be positive: {self.take_profit}",
                error_code="INVALID_TAKE_PROFIT",
                context={"take_profit": self.take_profit}
            )
        
        # Validate timestamp
        if self.created_at > datetime.now(timezone.utc):
            raise DataValidationError(
                f"Created timestamp cannot be in the future: {self.created_at}",
                error_code="FUTURE_TIMESTAMP",
                context={"created_at": self.created_at}
            )
    
    def _is_valid_symbol(self, symbol: str) -> bool:
        """Validate forex symbol format - accepts both USD/JPY and USDJPY formats"""
        # Pattern accepts standard format (EUR/USD) or MT5 format (EURUSD)
        pattern = r'^[A-Z]{3}/?[A-Z]{3}$'
        return bool(re.match(pattern, symbol))
    
    def is_pending(self) -> bool:
        """Check if order is pending"""
        return self.status == OrderStatus.PENDING
    
    def is_filled(self) -> bool:
        """Check if order is filled"""
        return self.status == OrderStatus.FILLED
    
    def is_cancelled(self) -> bool:
        """Check if order is cancelled"""
        return self.status == OrderStatus.CANCELLED


@dataclass
class Position:
    """Trading position with validation"""
    position_id: str
    symbol: str
    direction: Direction
    quantity: float
    entry_price: float
    current_price: float
    unrealized_pnl: float
    stop_loss: Optional[float]
    take_profit: Optional[float]
    opened_at: datetime
    magic: Optional[int] = None
    contract_size: float = 100000.0
    exit_policy: ExitPolicy = ExitPolicy.STANDARD
    predicted_exit_policy: Optional[ExitPolicy] = None
    policy_confidence: float = 0.0
    entry_features: Optional[List[float]] = None
    regime_label: str = "NEUTRAL"
    swap: float = 0.0
    commission: float = 0.0
    tick_value: Optional[float] = None
    tick_size: Optional[float] = None
    strategy_meta: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Validate position after initialization"""
        self.validate()
    
    def validate(self) -> None:
        """Validate trading position"""
        # Validate position ID
        if not self.position_id or not self.position_id.strip():
            raise DataValidationError(
                "Position ID cannot be empty",
                error_code="EMPTY_POSITION_ID",
                context={"position_id": self.position_id}
            )
        
        # Validate symbol format
        if not self._is_valid_symbol(self.symbol):
            raise DataValidationError(
                f"Invalid symbol format: {self.symbol}",
                error_code="INVALID_SYMBOL",
                context={"symbol": self.symbol}
            )
        
        # Validate direction
        if not isinstance(self.direction, Direction):
            raise DataValidationError(
                f"Invalid direction: {self.direction}",
                error_code="INVALID_DIRECTION",
                context={"direction": self.direction}
            )
        
        # Validate quantity
        if self.quantity <= 0:
            raise DataValidationError(
                f"Quantity must be positive: {self.quantity}",
                error_code="INVALID_QUANTITY",
                context={"quantity": self.quantity}
            )
        
        # Validate prices
        if self.entry_price <= 0:
            raise DataValidationError(
                f"Entry price must be positive: {self.entry_price}",
                error_code="INVALID_ENTRY_PRICE",
                context={"entry_price": self.entry_price}
            )
        
        if self.current_price <= 0:
            raise DataValidationError(
                f"Current price must be positive: {self.current_price}",
                error_code="INVALID_CURRENT_PRICE",
                context={"current_price": self.current_price}
            )
        
        # Validate stop loss and take profit if provided
        if self.stop_loss is not None and self.stop_loss <= 0:
            raise DataValidationError(
                f"Stop loss must be positive: {self.stop_loss}",
                error_code="INVALID_STOP_LOSS",
                context={"stop_loss": self.stop_loss}
            )
        
        if self.take_profit is not None and self.take_profit <= 0:
            raise DataValidationError(
                f"Take profit must be positive: {self.take_profit}",
                error_code="INVALID_TAKE_PROFIT",
                context={"take_profit": self.take_profit}
            )
        
        # Validate PnL calculation (allow small broker-side differences from swaps/commissions/rounding)
        calculated_pnl = self._calculate_pnl()
        # Trigger integrity errors only when drift exceeds $2.00.
        tolerance = 2.0
        if abs(self.unrealized_pnl - calculated_pnl) > tolerance:
            raise DataValidationError(
                "Unrealized PnL does not match calculated value",
                error_code="INVALID_PNL",
                context={
                    "unrealized_pnl": self.unrealized_pnl,
                    "calculated_pnl": calculated_pnl,
                    "tolerance": tolerance,
                    "difference": abs(self.unrealized_pnl - calculated_pnl)
                }
            )
        
        # Validate timestamp (allow 1 day in future for historical data and server time differences)
        max_future_time = datetime.now(timezone.utc) + timedelta(days=1)
        if self.opened_at > max_future_time:
            raise DataValidationError(
                f"Opened timestamp cannot be in the future: {self.opened_at}",
                error_code="FUTURE_TIMESTAMP",
                context={"opened_at": self.opened_at}
            )
    
    def _is_valid_symbol(self, symbol: str) -> bool:
        """Validate forex symbol format - accepts both USD/JPY and USDJPY formats"""
        # Pattern accepts standard format (EUR/USD) or MT5 format (EURUSD)
        pattern = r'^[A-Z]{3}/?[A-Z]{3}$'
        return bool(re.match(pattern, symbol))
    
    def _calculate_pnl(self) -> float:
        """Calculate unrealized PnL"""
        price_diff = (self.current_price - self.entry_price) if self.direction == Direction.LONG else (self.entry_price - self.current_price)
        tick_size = float(self.tick_size or 0.0)
        tick_value = float(self.tick_value or 0.0)
        if tick_size > 0.0 and tick_value > 0.0:
            raw_pnl = (price_diff / tick_size) * tick_value * self.quantity
        else:
            raw_pnl = price_diff * self.quantity * self.contract_size
            if 'JPY' in self.symbol.upper():
                raw_pnl = raw_pnl / self.current_price
        return raw_pnl + float(self.swap or 0.0) + float(self.commission or 0.0)
    
    def update_current_price(self, new_price: float) -> None:
        """Update current price and recalculate PnL"""
        if new_price <= 0:
            raise DataValidationError(
                f"New price must be positive: {new_price}",
                error_code="INVALID_PRICE",
                context={"new_price": new_price}
            )
        
        self.current_price = new_price
        self.unrealized_pnl = self._calculate_pnl()
    
    def is_profitable(self) -> bool:
        """Check if position is profitable"""
        return self.unrealized_pnl > 0


@dataclass
class Portfolio:
    """Portfolio information with validation"""
    account_id: str
    balance: float
    equity: float
    margin_used: float
    margin_available: float
    positions: List[Position]
    updated_at: datetime
    
    def __post_init__(self):
        """Validate portfolio after initialization"""
        self.validate()
    
    def validate(self) -> None:
        """Validate portfolio information"""
        # Validate account ID
        if not self.account_id or not self.account_id.strip():
            raise DataValidationError(
                "Account ID cannot be empty",
                error_code="EMPTY_ACCOUNT_ID",
                context={"account_id": self.account_id}
            )
        
        # Validate balance
        if self.balance < 0:
            raise DataValidationError(
                f"Balance cannot be negative: {self.balance}",
                error_code="NEGATIVE_BALANCE",
                context={"balance": self.balance}
            )
        
        # Validate equity
        if self.equity < 0:
            raise DataValidationError(
                f"Equity cannot be negative: {self.equity}",
                error_code="NEGATIVE_EQUITY",
                context={"equity": self.equity}
            )
        
        # Validate margin values
        if self.margin_used < 0:
            raise DataValidationError(
                f"Margin used cannot be negative: {self.margin_used}",
                error_code="NEGATIVE_MARGIN_USED",
                context={"margin_used": self.margin_used}
            )
        
        # NOTE: Margin available CAN be negative in real trading (margin call situations)
        # Allow negative margin to prevent blocking on real accounts in drawdown
        
        # Validate margin relationship (disabled - MT5 has floating point precision issues)
        # total_margin = self.margin_used + self.margin_available
        # if abs(total_margin - self.equity) > 0.01:
        #     raise DataValidationError(...)
        
        # Validate positions list
        if not isinstance(self.positions, list):
            raise DataValidationError(
                "Positions must be a list",
                error_code="INVALID_POSITIONS_TYPE",
                context={"positions_type": type(self.positions)}
            )
        
        # Validate each position
        for i, position in enumerate(self.positions):
            if not isinstance(position, Position):
                raise DataValidationError(
                    f"Position at index {i} is not a Position object",
                    error_code="INVALID_POSITION_TYPE",
                    context={"position_index": i, "position_type": type(position)}
                )
        
        # Validate timestamp (allow 1 day in future for historical data and server time differences)
        max_future_time = datetime.now(timezone.utc) + timedelta(days=1)
        if self.updated_at > max_future_time:
            raise DataValidationError(
                f"Updated timestamp cannot be in the future: {self.updated_at}",
                error_code="FUTURE_TIMESTAMP",
                context={"updated_at": self.updated_at}
            )
    
    def get_total_unrealized_pnl(self) -> float:
        """Calculate total unrealized PnL from all positions"""
        return sum(position.unrealized_pnl for position in self.positions)
    
    def get_position_count(self) -> int:
        """Get number of open positions"""
        return len(self.positions)
    
    def get_margin_level(self) -> float:
        """Calculate margin level percentage"""
        if self.margin_used == 0:
            return float('inf')
        return (self.equity / self.margin_used) * 100
    
    def has_available_margin(self, required_margin: float) -> bool:
        """Check if sufficient margin is available"""
        return self.margin_available >= required_margin


@dataclass
class RiskAssessment:
    """Risk assessment result with validation"""
    is_valid: bool
    risk_score: float
    position_size: float
    warnings: List[str]
    timestamp: datetime
    
    def __post_init__(self):
        """Validate risk assessment after initialization"""
        self.validate()
    
    def validate(self) -> None:
        """Validate risk assessment"""
        # Validate risk score range
        if not 0.0 <= self.risk_score <= 1.0:
            raise DataValidationError(
                f"Risk score out of range: {self.risk_score}",
                error_code="INVALID_RISK_SCORE",
                context={"risk_score": self.risk_score},
            )
        
        # Validate position size
        if not 0.0 <= self.position_size <= 1.0:
            raise DataValidationError(
                f"Position size out of range: {self.position_size}",
                error_code="INVALID_POSITION_SIZE",
                context={"position_size": self.position_size},
            )
        
        # Validate warnings list
        if not isinstance(self.warnings, list):
            raise DataValidationError(
                "Warnings must be a list",
                error_code="INVALID_WARNINGS_TYPE",
                context={"warnings_type": type(self.warnings)}
            )
        
        # Validate each warning is a string
        for i, warning in enumerate(self.warnings):
            if not isinstance(warning, str):
                raise DataValidationError(
                    f"Warning at index {i} must be a string",
                    error_code="INVALID_WARNING_TYPE",
                    context={"warning_index": i, "warning_type": type(warning)}
                )
        
        # Validate timestamp (allow 1 day in future for historical data and server time differences)
        max_future_time = datetime.now(timezone.utc) + timedelta(days=1)
        if self.timestamp > max_future_time:
            raise DataValidationError(
                f"Timestamp cannot be in the future: {self.timestamp}",
                error_code="FUTURE_TIMESTAMP",
                context={"timestamp": self.timestamp}
            )
        
        # Logical validation: if not valid, position size should be 0
        if not self.is_valid and self.position_size > 0:
            raise DataValidationError(
                "Invalid trades should have zero position size",
                error_code="INVALID_TRADE_WITH_POSITION",
                context={
                    "is_valid": self.is_valid,
                    "position_size": self.position_size
                }
            )
    
    def is_high_risk(self, threshold: float = 0.7) -> bool:
        """Check if risk is high"""
        return self.risk_score >= threshold
    
    def has_warnings(self) -> bool:
        """Check if there are any warnings"""
        return len(self.warnings) > 0


@dataclass
class ExecutionResult:
    """Trade execution result with validation"""
    success: bool
    order_id: str
    executed_price: Optional[float]
    executed_quantity: Optional[float]
    error_message: Optional[str]
    timestamp: datetime
    
    def __post_init__(self):
        """Validate execution result after initialization"""
        self.validate()
    
    def validate(self) -> None:
        """Validate execution result"""
        # Validate order ID
        if not self.order_id or not self.order_id.strip():
            raise DataValidationError(
                "Order ID cannot be empty",
                error_code="EMPTY_ORDER_ID",
                context={"order_id": self.order_id}
            )
        
        # Validate success-dependent fields
        if self.success:
            # Successful executions must have price and quantity
            if self.executed_price is None or self.executed_price <= 0:
                raise DataValidationError(
                    "Successful executions must have a positive price",
                    error_code="MISSING_EXECUTED_PRICE",
                    context={
                        "success": self.success,
                        "executed_price": self.executed_price,
                    },
                )
            
            if self.executed_quantity is None or self.executed_quantity <= 0:
                raise DataValidationError(
                    "Successful executions must have a positive quantity",
                    error_code="MISSING_EXECUTED_QUANTITY",
                    context={
                        "success": self.success,
                        "executed_quantity": self.executed_quantity,
                    },
                )
            
            # Successful executions should not have error messages
            if self.error_message is not None and self.error_message.strip():
                raise DataValidationError(
                    "Successful executions should not have error messages",
                    error_code="SUCCESS_WITH_ERROR",
                    context={
                        "success": self.success,
                        "error_message": self.error_message
                    }
                )
        else:
            # Failed executions must have error message
            if not self.error_message or not self.error_message.strip():
                raise DataValidationError(
                    "Failed executions must have error message",
                    error_code="FAILURE_WITHOUT_ERROR",
                    context={
                        "success": self.success,
                        "error_message": self.error_message
                    }
                )
        
        # Validate timestamp (allow 1 day in future for historical data and server time differences)
        max_future_time = datetime.now(timezone.utc) + timedelta(days=1)
        if self.timestamp > max_future_time:
            raise DataValidationError(
                f"Timestamp cannot be in the future: {self.timestamp}",
                error_code="FUTURE_TIMESTAMP",
                context={"timestamp": self.timestamp}
            )
    
    def is_successful(self) -> bool:
        """Check if execution was successful"""
        return self.success
    
    def get_slippage(self, expected_price: float) -> Optional[float]:
        """Calculate slippage if execution was successful"""
        if not self.success or self.executed_price is None:
            return None
        return abs(self.executed_price - expected_price)
