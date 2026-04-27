"""Stop-loss and take-profit management for risk control"""

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from src.models import TradingSignal, MarketData, Direction, Position
from src.exceptions import DataValidationError


@dataclass
class StopLossTakeProfitConfig:
    """Configuration for stop-loss and take-profit calculations"""
    # Volatility-based stop loss settings
    volatility_multiplier: float = 2.0  # ATR multiplier for stop distance
    volatility_lookback: int = 14       # Periods for volatility calculation
    min_stop_distance_pips: int = 10    # Minimum stop distance in pips
    max_stop_distance_pips: int = 100   # Maximum stop distance in pips
    
    # Risk-reward ratio settings
    default_risk_reward_ratio: float = 2.0  # Default 1:2 risk-reward
    min_risk_reward_ratio: float = 1.0      # Minimum acceptable ratio
    max_risk_reward_ratio: float = 5.0      # Maximum ratio
    
    # Trailing stop settings
    trailing_stop_activation_pips: int = 20  # Pips profit before trailing starts
    trailing_stop_distance_pips: int = 15    # Distance to maintain from high/low
    trailing_step_pips: int = 5              # Minimum movement to update trail
    
    # Support/resistance settings
    support_resistance_lookback: int = 50    # Periods to look for S/R levels
    support_resistance_tolerance_pips: int = 5  # Tolerance around S/R levels
    
    def __post_init__(self):
        """Validate configuration after initialization"""
        self.validate()
    
    def validate(self) -> None:
        """Validate stop-loss take-profit configuration"""
        if not 0.5 <= self.volatility_multiplier <= 5.0:
            raise DataValidationError(
                f"Volatility multiplier must be between 0.5 and 5.0: {self.volatility_multiplier}",
                error_code="INVALID_VOLATILITY_MULTIPLIER",
                context={"volatility_multiplier": self.volatility_multiplier}
            )
        
        if not 5 <= self.volatility_lookback <= 100:
            raise DataValidationError(
                f"Volatility lookback must be between 5 and 100: {self.volatility_lookback}",
                error_code="INVALID_VOLATILITY_LOOKBACK",
                context={"volatility_lookback": self.volatility_lookback}
            )
        
        if not 1 <= self.min_stop_distance_pips <= 50:
            raise DataValidationError(
                f"Min stop distance must be between 1 and 50 pips: {self.min_stop_distance_pips}",
                error_code="INVALID_MIN_STOP_DISTANCE",
                context={"min_stop_distance_pips": self.min_stop_distance_pips}
            )
        
        if not 20 <= self.max_stop_distance_pips <= 500:
            raise DataValidationError(
                f"Max stop distance must be between 20 and 500 pips: {self.max_stop_distance_pips}",
                error_code="INVALID_MAX_STOP_DISTANCE",
                context={"max_stop_distance_pips": self.max_stop_distance_pips}
            )
        
        if self.min_stop_distance_pips >= self.max_stop_distance_pips:
            raise DataValidationError(
                "Min stop distance must be less than max stop distance",
                error_code="INVALID_STOP_DISTANCE_RANGE",
                context={
                    "min_stop_distance_pips": self.min_stop_distance_pips,
                    "max_stop_distance_pips": self.max_stop_distance_pips
                }
            )
        
        if not 1.0 <= self.default_risk_reward_ratio <= 10.0:
            raise DataValidationError(
                f"Default risk-reward ratio must be between 1.0 and 10.0: {self.default_risk_reward_ratio}",
                error_code="INVALID_DEFAULT_RISK_REWARD",
                context={"default_risk_reward_ratio": self.default_risk_reward_ratio}
            )
        
        if self.min_risk_reward_ratio >= self.max_risk_reward_ratio:
            raise DataValidationError(
                "Min risk-reward ratio must be less than max risk-reward ratio",
                error_code="INVALID_RISK_REWARD_RANGE",
                context={
                    "min_risk_reward_ratio": self.min_risk_reward_ratio,
                    "max_risk_reward_ratio": self.max_risk_reward_ratio
                }
            )
        
        if not 0.5 <= self.min_risk_reward_ratio <= 2.0:
            raise DataValidationError(
                f"Min risk-reward ratio must be between 0.5 and 2.0: {self.min_risk_reward_ratio}",
                error_code="INVALID_MIN_RISK_REWARD",
                context={"min_risk_reward_ratio": self.min_risk_reward_ratio}
            )
        
        if not 2.0 <= self.max_risk_reward_ratio <= 20.0:
            raise DataValidationError(
                f"Max risk-reward ratio must be between 2.0 and 20.0: {self.max_risk_reward_ratio}",
                error_code="INVALID_MAX_RISK_REWARD",
                context={"max_risk_reward_ratio": self.max_risk_reward_ratio}
            )


@dataclass
class SupportResistanceLevel:
    """Support or resistance level with strength"""
    price: float
    strength: float  # 0.0 to 1.0
    level_type: str  # "SUPPORT" or "RESISTANCE"
    touches: int     # Number of times price touched this level
    
    def __post_init__(self):
        """Validate support/resistance level after initialization"""
        self.validate()
    
    def validate(self) -> None:
        """Validate support/resistance level"""
        if self.price <= 0:
            raise DataValidationError(
                f"Price must be positive: {self.price}",
                error_code="INVALID_PRICE",
                context={"price": self.price}
            )
        
        if not 0.0 <= self.strength <= 1.0:
            raise DataValidationError(
                f"Strength must be between 0.0 and 1.0: {self.strength}",
                error_code="INVALID_STRENGTH",
                context={"strength": self.strength}
            )
        
        if self.level_type not in ["SUPPORT", "RESISTANCE"]:
            raise DataValidationError(
                f"Level type must be SUPPORT or RESISTANCE: {self.level_type}",
                error_code="INVALID_LEVEL_TYPE",
                context={"level_type": self.level_type}
            )
        
        if self.touches < 1:
            raise DataValidationError(
                f"Touches must be at least 1: {self.touches}",
                error_code="INVALID_TOUCHES",
                context={"touches": self.touches}
            )


@dataclass
class StopLossTakeProfitLevels:
    """Calculated stop-loss and take-profit levels"""
    stop_loss: float
    take_profit: float
    risk_reward_ratio: float
    calculation_method: str
    confidence: float  # 0.0 to 1.0
    
    def __post_init__(self):
        """Validate levels after initialization"""
        self.validate()
    
    def validate(self) -> None:
        """Validate stop-loss and take-profit levels"""
        if self.stop_loss <= 0:
            raise DataValidationError(
                f"Stop loss must be positive: {self.stop_loss}",
                error_code="INVALID_STOP_LOSS",
                context={"stop_loss": self.stop_loss}
            )
        
        if self.take_profit <= 0:
            raise DataValidationError(
                f"Take profit must be positive: {self.take_profit}",
                error_code="INVALID_TAKE_PROFIT",
                context={"take_profit": self.take_profit}
            )
        
        if self.risk_reward_ratio <= 0:
            raise DataValidationError(
                f"Risk-reward ratio must be positive: {self.risk_reward_ratio}",
                error_code="INVALID_RISK_REWARD_RATIO",
                context={"risk_reward_ratio": self.risk_reward_ratio}
            )
        
        if not 0.0 <= self.confidence <= 1.0:
            raise DataValidationError(
                f"Confidence must be between 0.0 and 1.0: {self.confidence}",
                error_code="INVALID_CONFIDENCE",
                context={"confidence": self.confidence}
            )
        
        if not self.calculation_method:
            raise DataValidationError(
                "Calculation method cannot be empty",
                error_code="EMPTY_CALCULATION_METHOD",
                context={"calculation_method": self.calculation_method}
            )


@dataclass
class TrailingStopState:
    """State tracking for trailing stop functionality"""
    position_id: str
    symbol: str
    direction: Direction
    entry_price: float
    current_stop_loss: float
    highest_price: float  # For LONG positions
    lowest_price: float   # For SHORT positions
    is_active: bool
    last_updated: datetime
    
    def __post_init__(self):
        """Validate trailing stop state after initialization"""
        self.validate()
    
    def validate(self) -> None:
        """Validate trailing stop state"""
        if not self.position_id:
            raise DataValidationError(
                "Position ID cannot be empty",
                error_code="EMPTY_POSITION_ID",
                context={"position_id": self.position_id}
            )
        
        if not self.symbol:
            raise DataValidationError(
                "Symbol cannot be empty",
                error_code="EMPTY_SYMBOL",
                context={"symbol": self.symbol}
            )
        
        if self.entry_price <= 0:
            raise DataValidationError(
                f"Entry price must be positive: {self.entry_price}",
                error_code="INVALID_ENTRY_PRICE",
                context={"entry_price": self.entry_price}
            )
        
        if self.current_stop_loss <= 0:
            raise DataValidationError(
                f"Current stop loss must be positive: {self.current_stop_loss}",
                error_code="INVALID_CURRENT_STOP_LOSS",
                context={"current_stop_loss": self.current_stop_loss}
            )


class StopLossTakeProfitCalculator(ABC):
    """Abstract base class for stop-loss and take-profit calculations"""
    
    def __init__(self, config: StopLossTakeProfitConfig):
        self.config = config
    
    @abstractmethod
    def calculate_levels(
        self,
        signal: TradingSignal,
        market_data: List[MarketData],
        support_resistance: Optional[List[SupportResistanceLevel]] = None
    ) -> StopLossTakeProfitLevels:
        """Calculate stop-loss and take-profit levels"""
        pass
    
    def _validate_inputs(
        self,
        signal: TradingSignal,
        market_data: List[MarketData]
    ) -> None:
        """Validate common inputs"""
        if not isinstance(signal, TradingSignal):
            raise DataValidationError(
                "Signal must be a TradingSignal instance",
                error_code="INVALID_SIGNAL_TYPE",
                context={"signal_type": type(signal)}
            )
        
        if not market_data:
            raise DataValidationError(
                "Market data cannot be empty",
                error_code="EMPTY_MARKET_DATA",
                context={"market_data_length": len(market_data)}
            )
        
        if len(market_data) < self.config.volatility_lookback:
            raise DataValidationError(
                f"Insufficient market data: need at least {self.config.volatility_lookback} periods",
                error_code="INSUFFICIENT_MARKET_DATA",
                context={
                    "available_periods": len(market_data),
                    "required_periods": self.config.volatility_lookback
                }
            )
    
    def _calculate_atr(self, market_data: List[MarketData]) -> float:
        """Calculate Average True Range for volatility-based stops"""
        if len(market_data) < 2:
            return 0.0
        
        true_ranges = []
        
        for i in range(1, min(len(market_data), self.config.volatility_lookback + 1)):
            current = market_data[i]
            previous = market_data[i - 1]
            
            # True Range = max(high-low, |high-prev_close|, |low-prev_close|)
            tr1 = current.high - current.low
            tr2 = abs(current.high - previous.close)
            tr3 = abs(current.low - previous.close)
            
            true_range = max(tr1, tr2, tr3)
            true_ranges.append(true_range)
        
        # Calculate ATR as simple moving average of true ranges
        return sum(true_ranges) / len(true_ranges) if true_ranges else 0.0
    
    def _pips_to_price(self, price: float, pips: int, symbol: str) -> float:
        """Convert pips to price difference"""
        # For most major pairs, 1 pip = 0.0001
        # For JPY pairs, 1 pip = 0.01
        if "JPY" in symbol:
            pip_value = 0.01
        else:
            pip_value = 0.0001
        
        return pips * pip_value
    
    def _price_to_pips(self, price_diff: float, symbol: str) -> int:
        """Convert price difference to pips"""
        if "JPY" in symbol:
            pip_value = 0.01
        else:
            pip_value = 0.0001
        
        return int(abs(price_diff) / pip_value)


class VolatilityBasedCalculator(StopLossTakeProfitCalculator):
    """Calculate stop-loss and take-profit based on market volatility"""
    
    def calculate_levels(
        self,
        signal: TradingSignal,
        market_data: List[MarketData],
        support_resistance: Optional[List[SupportResistanceLevel]] = None
    ) -> StopLossTakeProfitLevels:
        """Calculate levels based on ATR volatility"""
        self._validate_inputs(signal, market_data)
        
        # Calculate ATR
        atr = self._calculate_atr(market_data)
        
        if atr == 0:
            raise DataValidationError(
                "Cannot calculate ATR from market data",
                error_code="ZERO_ATR",
                context={"market_data_length": len(market_data)}
            )
        
        # Calculate stop distance based on ATR
        stop_distance = atr * self.config.volatility_multiplier
        
        # Convert to pips and apply limits
        stop_distance_pips = self._price_to_pips(stop_distance, signal.symbol)
        stop_distance_pips = max(
            self.config.min_stop_distance_pips,
            min(stop_distance_pips, self.config.max_stop_distance_pips)
        )
        
        # Convert back to price
        stop_distance = self._pips_to_price(
            signal.entry_price, stop_distance_pips, signal.symbol
        )
        
        # Calculate stop loss
        if signal.direction == Direction.LONG:
            stop_loss = signal.entry_price - stop_distance
        else:
            stop_loss = signal.entry_price + stop_distance
        
        # Calculate take profit using risk-reward ratio
        risk_reward_ratio = self.config.default_risk_reward_ratio
        profit_distance = stop_distance * risk_reward_ratio
        
        if signal.direction == Direction.LONG:
            take_profit = signal.entry_price + profit_distance
        else:
            take_profit = signal.entry_price - profit_distance
        
        # Adjust for support/resistance if provided
        if support_resistance:
            stop_loss, take_profit = self._adjust_for_support_resistance(
                signal, stop_loss, take_profit, support_resistance
            )
            
            # Recalculate risk-reward ratio after adjustments
            if signal.direction == Direction.LONG:
                risk = signal.entry_price - stop_loss
                reward = take_profit - signal.entry_price
            else:
                risk = stop_loss - signal.entry_price
                reward = signal.entry_price - take_profit
            
            risk_reward_ratio = reward / risk if risk > 0 else 0.0
        
        # Calculate confidence based on ATR consistency
        confidence = self._calculate_confidence(market_data, atr)
        
        return StopLossTakeProfitLevels(
            stop_loss=stop_loss,
            take_profit=take_profit,
            risk_reward_ratio=risk_reward_ratio,
            calculation_method="VOLATILITY_ATR",
            confidence=confidence
        )
    
    def _adjust_for_support_resistance(
        self,
        signal: TradingSignal,
        stop_loss: float,
        take_profit: float,
        support_resistance: List[SupportResistanceLevel]
    ) -> Tuple[float, float]:
        """Adjust levels based on support/resistance"""
        tolerance = self._pips_to_price(
            signal.entry_price, 
            self.config.support_resistance_tolerance_pips, 
            signal.symbol
        )
        
        if signal.direction == Direction.LONG:
            # For LONG positions, look for support below entry for stop loss
            # and resistance above entry for take profit
            
            # Find strongest support below current stop loss
            supports_below = [
                level for level in support_resistance
                if level.level_type == "SUPPORT" and level.price < stop_loss
            ]
            
            if supports_below:
                # Use the strongest support level
                strongest_support = max(supports_below, key=lambda x: x.strength)
                stop_loss = strongest_support.price - tolerance
            
            # Find resistance above current take profit
            resistances_above = [
                level for level in support_resistance
                if level.level_type == "RESISTANCE" and level.price > signal.entry_price
            ]
            
            if resistances_above:
                # Use the nearest significant resistance
                nearest_resistance = min(resistances_above, key=lambda x: x.price)
                if nearest_resistance.strength > 0.5:  # Only use strong resistance
                    take_profit = min(take_profit, nearest_resistance.price - tolerance)
        
        else:  # SHORT position
            # For SHORT positions, look for resistance above entry for stop loss
            # and support below entry for take profit
            
            # Find strongest resistance above current stop loss
            resistances_above = [
                level for level in support_resistance
                if level.level_type == "RESISTANCE" and level.price > stop_loss
            ]
            
            if resistances_above:
                strongest_resistance = max(resistances_above, key=lambda x: x.strength)
                stop_loss = strongest_resistance.price + tolerance
            
            # Find support below current take profit
            supports_below = [
                level for level in support_resistance
                if level.level_type == "SUPPORT" and level.price < signal.entry_price
            ]
            
            if supports_below:
                nearest_support = max(supports_below, key=lambda x: x.price)
                if nearest_support.strength > 0.5:
                    take_profit = max(take_profit, nearest_support.price + tolerance)
        
        return stop_loss, take_profit
    
    def _calculate_confidence(self, market_data: List[MarketData], current_atr: float) -> float:
        """Calculate confidence based on ATR consistency"""
        if len(market_data) < self.config.volatility_lookback * 2:
            return 0.5  # Default confidence
        
        # Calculate ATR for different periods to check consistency
        recent_atr = self._calculate_atr(market_data[:self.config.volatility_lookback])
        older_atr = self._calculate_atr(
            market_data[self.config.volatility_lookback:self.config.volatility_lookback * 2]
        )
        
        if older_atr == 0:
            return 0.5
        
        # Confidence is higher when ATR is consistent
        atr_ratio = min(recent_atr, older_atr) / max(recent_atr, older_atr)
        confidence = 0.3 + (atr_ratio * 0.7)  # Scale to 0.3-1.0 range
        
        return min(1.0, max(0.0, confidence))


class TrailingStopManager:
    """Manages trailing stop functionality for open positions"""
    
    def __init__(self, config: StopLossTakeProfitConfig):
        self.config = config
        self.trailing_stops: Dict[str, TrailingStopState] = {}
    
    def initialize_trailing_stop(self, position: Position) -> None:
        """Initialize trailing stop for a position"""
        if not isinstance(position, Position):
            raise DataValidationError(
                "Position must be a Position instance",
                error_code="INVALID_POSITION_TYPE",
                context={"position_type": type(position)}
            )
        
        # Check if position is profitable enough to start trailing
        profit_pips = self._calculate_profit_pips(position)
        
        if profit_pips < self.config.trailing_stop_activation_pips:
            return  # Not profitable enough to start trailing
        
        trailing_state = TrailingStopState(
            position_id=position.position_id,
            symbol=position.symbol,
            direction=position.direction,
            entry_price=position.entry_price,
            current_stop_loss=position.stop_loss or 0.0,
            highest_price=position.current_price if position.direction == Direction.LONG else position.entry_price,
            lowest_price=position.current_price if position.direction == Direction.SHORT else position.entry_price,
            is_active=True,
            last_updated=datetime.now(timezone.utc)
        )
        
        self.trailing_stops[position.position_id] = trailing_state
    
    def update_trailing_stop(
        self, 
        position_id: str, 
        current_price: float
    ) -> Optional[float]:
        """Update trailing stop and return new stop loss if changed"""
        if position_id not in self.trailing_stops:
            return None
        
        trailing_state = self.trailing_stops[position_id]
        
        if not trailing_state.is_active:
            return None
        
        new_stop_loss = None
        
        if trailing_state.direction == Direction.LONG:
            # For LONG positions, trail stop up as price moves higher
            if current_price > trailing_state.highest_price:
                # Price made new high, check if we should update stop
                price_move_pips = self._price_to_pips(
                    current_price - trailing_state.highest_price,
                    trailing_state.symbol
                )
                
                if price_move_pips >= self.config.trailing_step_pips:
                    # Update highest price and calculate new stop loss
                    trailing_state.highest_price = current_price
                    
                    # New stop loss is trailing distance below current price
                    trailing_distance = self._pips_to_price(
                        current_price,
                        self.config.trailing_stop_distance_pips,
                        trailing_state.symbol
                    )
                    
                    potential_stop = current_price - trailing_distance
                    
                    # Only move stop loss up, never down
                    if potential_stop > trailing_state.current_stop_loss:
                        trailing_state.current_stop_loss = potential_stop
                        trailing_state.last_updated = datetime.now(timezone.utc)
                        new_stop_loss = potential_stop
        
        else:  # SHORT position
            # For SHORT positions, trail stop down as price moves lower
            if current_price < trailing_state.lowest_price:
                # Price made new low, check if we should update stop
                price_move_pips = self._price_to_pips(
                    trailing_state.lowest_price - current_price,
                    trailing_state.symbol
                )
                
                if price_move_pips >= self.config.trailing_step_pips:
                    # Update lowest price and calculate new stop loss
                    trailing_state.lowest_price = current_price
                    
                    # New stop loss is trailing distance above current price
                    trailing_distance = self._pips_to_price(
                        current_price,
                        self.config.trailing_stop_distance_pips,
                        trailing_state.symbol
                    )
                    
                    potential_stop = current_price + trailing_distance
                    
                    # Only move stop loss down, never up
                    if potential_stop < trailing_state.current_stop_loss:
                        trailing_state.current_stop_loss = potential_stop
                        trailing_state.last_updated = datetime.now(timezone.utc)
                        new_stop_loss = potential_stop
        
        return new_stop_loss
    
    def deactivate_trailing_stop(self, position_id: str) -> None:
        """Deactivate trailing stop for a position"""
        if position_id in self.trailing_stops:
            self.trailing_stops[position_id].is_active = False
    
    def remove_trailing_stop(self, position_id: str) -> None:
        """Remove trailing stop completely"""
        if position_id in self.trailing_stops:
            del self.trailing_stops[position_id]
    
    def get_trailing_stop_state(self, position_id: str) -> Optional[TrailingStopState]:
        """Get current trailing stop state"""
        return self.trailing_stops.get(position_id)
    
    def _calculate_profit_pips(self, position: Position) -> int:
        """Calculate current profit in pips"""
        if position.direction == Direction.LONG:
            profit_price = position.current_price - position.entry_price
        else:
            profit_price = position.entry_price - position.current_price
        
        return self._price_to_pips(profit_price, position.symbol)
    
    def _pips_to_price(self, price: float, pips: int, symbol: str) -> float:
        """Convert pips to price difference"""
        if "JPY" in symbol:
            pip_value = 0.01
        else:
            pip_value = 0.0001
        
        return pips * pip_value
    
    def _price_to_pips(self, price_diff: float, symbol: str) -> int:
        """Convert price difference to pips"""
        if "JPY" in symbol:
            pip_value = 0.01
        else:
            pip_value = 0.0001
        
        return int(abs(price_diff) / pip_value)


class SupportResistanceDetector:
    """Detects support and resistance levels from market data"""
    
    def __init__(self, config: StopLossTakeProfitConfig):
        self.config = config
    
    def detect_levels(self, market_data: List[MarketData]) -> List[SupportResistanceLevel]:
        """Detect support and resistance levels from market data"""
        if len(market_data) < self.config.support_resistance_lookback:
            return []
        
        levels = []
        
        # Use recent data for analysis
        recent_data = market_data[:self.config.support_resistance_lookback]
        
        # Find pivot highs and lows
        pivot_highs = self._find_pivot_highs(recent_data)
        pivot_lows = self._find_pivot_lows(recent_data)
        
        # Convert pivot highs to resistance levels
        for price, strength in pivot_highs:
            levels.append(SupportResistanceLevel(
                price=price,
                strength=strength,
                level_type="RESISTANCE",
                touches=max(1, int(strength * 5))  # Estimate touches from strength
            ))
        
        # Convert pivot lows to support levels
        for price, strength in pivot_lows:
            levels.append(SupportResistanceLevel(
                price=price,
                strength=strength,
                level_type="SUPPORT",
                touches=max(1, int(strength * 5))
            ))
        
        return levels
    
    def _find_pivot_highs(self, market_data: List[MarketData]) -> List[Tuple[float, float]]:
        """Find pivot high points that could act as resistance"""
        pivot_highs = []
        window = 3  # Reduced window size for better detection
        
        for i in range(window, len(market_data) - window):
            current_high = market_data[i].high
            
            # Check if this is a local high
            is_pivot_high = True
            for j in range(i - window, i + window + 1):
                if j != i and market_data[j].high >= current_high:
                    is_pivot_high = False
                    break
            
            if is_pivot_high:
                # Calculate strength based on how many times price tested this level
                strength = self._calculate_level_strength(market_data, current_high, "HIGH")
                if strength >= 0.1:  # Only include significant levels
                    pivot_highs.append((current_high, strength))
        
        return pivot_highs
    
    def _find_pivot_lows(self, market_data: List[MarketData]) -> List[Tuple[float, float]]:
        """Find pivot low points that could act as support"""
        pivot_lows = []
        window = 3  # Reduced window size for better detection
        
        for i in range(window, len(market_data) - window):
            current_low = market_data[i].low
            
            # Check if this is a local low
            is_pivot_low = True
            for j in range(i - window, i + window + 1):
                if j != i and market_data[j].low <= current_low:
                    is_pivot_low = False
                    break
            
            if is_pivot_low:
                # Calculate strength
                strength = self._calculate_level_strength(market_data, current_low, "LOW")
                if strength >= 0.1:
                    pivot_lows.append((current_low, strength))
        
        return pivot_lows
    
    def _calculate_level_strength(
        self, 
        market_data: List[MarketData], 
        level_price: float, 
        level_type: str
    ) -> float:
        """Calculate the strength of a support/resistance level"""
        touches = 0
        tolerance = level_price * 0.002  # 0.2% tolerance for better detection
        
        for data in market_data:
            if level_type == "HIGH":
                if abs(data.high - level_price) <= tolerance:
                    touches += 1
            else:  # LOW
                if abs(data.low - level_price) <= tolerance:
                    touches += 1
        
        # Strength increases with more touches, capped at 1.0
        # Start with base strength of 0.2 for any detected level
        strength = min(1.0, 0.2 + (touches / 3.0))
        return strength