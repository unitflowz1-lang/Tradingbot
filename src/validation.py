"""Validation utilities for the AI Forex Trading Bot"""

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Union, Callable
from src.exceptions import DataValidationError


class ValidationRules:
    """Collection of validation rules and utilities"""
    
    # Forex symbol pattern
    FOREX_SYMBOL_PATTERN = r'^[A-Z]{3}/[A-Z]{3}$'
    
    # Major forex pairs
    MAJOR_PAIRS = {
        'EUR/USD', 'GBP/USD', 'USD/JPY', 'USD/CHF',
        'AUD/USD', 'USD/CAD', 'NZD/USD'
    }
    
    # Minor pairs
    MINOR_PAIRS = {
        'EUR/GBP', 'EUR/JPY', 'EUR/CHF', 'EUR/AUD',
        'EUR/CAD', 'EUR/NZD', 'GBP/JPY', 'GBP/CHF',
        'GBP/AUD', 'GBP/CAD', 'GBP/NZD', 'AUD/JPY',
        'AUD/CHF', 'AUD/CAD', 'AUD/NZD', 'CAD/JPY',
        'CAD/CHF', 'CHF/JPY', 'NZD/JPY', 'NZD/CHF',
        'NZD/CAD'
    }
    
    @staticmethod
    def validate_forex_symbol(symbol: str) -> bool:
        """Validate forex symbol format"""
        if not isinstance(symbol, str):
            return False
        return bool(re.match(ValidationRules.FOREX_SYMBOL_PATTERN, symbol))
    
    @staticmethod
    def is_major_pair(symbol: str) -> bool:
        """Check if symbol is a major forex pair"""
        return symbol in ValidationRules.MAJOR_PAIRS
    
    @staticmethod
    def is_minor_pair(symbol: str) -> bool:
        """Check if symbol is a minor forex pair"""
        return symbol in ValidationRules.MINOR_PAIRS
    
    @staticmethod
    def validate_price(price: float, min_value: float = 0.0001) -> bool:
        """Validate price value"""
        if not isinstance(price, (int, float)):
            return False
        return price >= min_value and price < float('inf')
    
    @staticmethod
    def validate_percentage(value: float, min_val: float = 0.0, max_val: float = 1.0) -> bool:
        """Validate percentage value"""
        if not isinstance(value, (int, float)):
            return False
        return min_val <= value <= max_val
    
    @staticmethod
    def validate_timestamp(timestamp: datetime, allow_future: bool = False) -> bool:
        """Validate timestamp"""
        if not isinstance(timestamp, datetime):
            return False
        
        if not allow_future and timestamp > datetime.now(timezone.utc):
            return False
        
        # Check if timestamp is not too old (more than 10 years)
        ten_years_ago = datetime.now(timezone.utc) - timedelta(days=365 * 10)
        return timestamp >= ten_years_ago
    
    @staticmethod
    def validate_non_empty_string(value: str) -> bool:
        """Validate non-empty string"""
        return isinstance(value, str) and bool(value.strip())
    
    @staticmethod
    def validate_positive_number(value: Union[int, float]) -> bool:
        """Validate positive number"""
        if not isinstance(value, (int, float)):
            return False
        return value > 0 and value < float('inf')
    
    @staticmethod
    def validate_non_negative_number(value: Union[int, float]) -> bool:
        """Validate non-negative number"""
        if not isinstance(value, (int, float)):
            return False
        return value >= 0 and value < float('inf')


class DataValidator:
    """Generic data validator with custom rules"""
    
    def __init__(self):
        self.rules: Dict[str, List[Callable]] = {}
        self.errors: List[str] = []
    
    def add_rule(self, field_name: str, validator: Callable[[Any], bool], error_message: str):
        """Add validation rule for a field"""
        if field_name not in self.rules:
            self.rules[field_name] = []
        
        def rule_wrapper(value):
            if not validator(value):
                self.errors.append(f"{field_name}: {error_message}")
                return False
            return True
        
        self.rules[field_name].append(rule_wrapper)
    
    def validate(self, data: Dict[str, Any]) -> bool:
        """Validate data against all rules"""
        self.errors.clear()
        is_valid = True
        
        for field_name, validators in self.rules.items():
            if field_name in data:
                value = data[field_name]
                for validator in validators:
                    if not validator(value):
                        is_valid = False
            else:
                self.errors.append(f"{field_name}: Field is required")
                is_valid = False
        
        return is_valid
    
    def get_errors(self) -> List[str]:
        """Get validation errors"""
        return self.errors.copy()


class MarketDataValidator(DataValidator):
    """Specialized validator for market data"""
    
    def __init__(self):
        super().__init__()
        self._setup_rules()
    
    def _setup_rules(self):
        """Setup market data validation rules"""
        self.add_rule('symbol', ValidationRules.validate_forex_symbol, 
                     "Invalid forex symbol format")
        self.add_rule('timestamp', lambda x: ValidationRules.validate_timestamp(x, False),
                     "Invalid timestamp")
        self.add_rule('open', ValidationRules.validate_positive_number,
                     "Open price must be positive")
        self.add_rule('high', ValidationRules.validate_positive_number,
                     "High price must be positive")
        self.add_rule('low', ValidationRules.validate_positive_number,
                     "Low price must be positive")
        self.add_rule('close', ValidationRules.validate_positive_number,
                     "Close price must be positive")
        self.add_rule('volume', ValidationRules.validate_non_negative_number,
                     "Volume must be non-negative")
        self.add_rule('bid', ValidationRules.validate_positive_number,
                     "Bid price must be positive")
        self.add_rule('ask', ValidationRules.validate_positive_number,
                     "Ask price must be positive")
        self.add_rule('spread', ValidationRules.validate_non_negative_number,
                     "Spread must be non-negative")
    
    def validate_ohlc_relationship(self, data: Dict[str, Any]) -> bool:
        """Validate OHLC price relationships"""
        try:
            open_price = data['open']
            high = data['high']
            low = data['low']
            close = data['close']
            
            if not (low <= open_price <= high and low <= close <= high):
                self.errors.append("Invalid OHLC relationship: low <= open,close <= high")
                return False
            
            return True
        except KeyError as e:
            self.errors.append(f"Missing required field: {e}")
            return False
    
    def validate_bid_ask_relationship(self, data: Dict[str, Any]) -> bool:
        """Validate bid/ask relationship"""
        try:
            bid = data['bid']
            ask = data['ask']
            spread = data['spread']
            
            if bid >= ask:
                self.errors.append("Bid must be less than ask")
                return False
            
            calculated_spread = ask - bid
            symbol = data.get('symbol', '')
            pip_size = 0.01 if 'JPY' in symbol else 0.0001
            tolerance = 5.0 * pip_size  # FIX: Standardized spread tolerance for all validation layers

            if abs(spread - calculated_spread) > tolerance + 1e-7:
                self.errors.append(f"Spread mismatch exceeds 10.0 pip tolerance (Diff: {abs(spread - calculated_spread):.6f})")
                return False
            
            return True
        except KeyError as e:
            self.errors.append(f"Missing required field: {e}")
            return False
    
    def validate(self, data: Dict[str, Any]) -> bool:
        """Validate market data with additional relationship checks"""
        is_valid = super().validate(data)
        
        if is_valid:
            is_valid &= self.validate_ohlc_relationship(data)
            is_valid &= self.validate_bid_ask_relationship(data)
        
        return is_valid


class TradingSignalValidator(DataValidator):
    """Specialized validator for trading signals"""
    
    def __init__(self):
        super().__init__()
        self._setup_rules()
    
    def _setup_rules(self):
        """Setup trading signal validation rules"""
        self.add_rule('symbol', ValidationRules.validate_forex_symbol,
                     "Invalid forex symbol format")
        self.add_rule('entry_price', ValidationRules.validate_positive_number,
                     "Entry price must be positive")
        self.add_rule('stop_loss', ValidationRules.validate_positive_number,
                     "Stop loss must be positive")
        self.add_rule('take_profit', ValidationRules.validate_positive_number,
                     "Take profit must be positive")
        self.add_rule('position_size', lambda x: ValidationRules.validate_percentage(x, 0.0001, 1.0),
                     "Position size must be between 0.0001 and 1.0")
        self.add_rule('confidence', lambda x: ValidationRules.validate_percentage(x, 0.0, 1.0),
                     "Confidence must be between 0.0 and 1.0")
        self.add_rule('reasoning', ValidationRules.validate_non_empty_string,
                     "Reasoning cannot be empty")
        self.add_rule('timestamp', lambda x: ValidationRules.validate_timestamp(x, False),
                     "Invalid timestamp")
    
    def validate_stop_take_relationship(self, data: Dict[str, Any]) -> bool:
        """Validate stop loss and take profit relationships"""
        try:
            direction = data['direction']
            entry_price = data['entry_price']
            stop_loss = data['stop_loss']
            take_profit = data['take_profit']
            
            if direction.value == 'LONG':
                if stop_loss >= entry_price:
                    self.errors.append("For LONG positions, stop loss must be below entry price")
                    return False
                if take_profit <= entry_price:
                    self.errors.append("For LONG positions, take profit must be above entry price")
                    return False
            else:  # SHORT
                if stop_loss <= entry_price:
                    self.errors.append("For SHORT positions, stop loss must be above entry price")
                    return False
                if take_profit >= entry_price:
                    self.errors.append("For SHORT positions, take profit must be below entry price")
                    return False
            
            return True
        except (KeyError, AttributeError) as e:
            self.errors.append(f"Missing or invalid field: {e}")
            return False
    
    def validate(self, data: Dict[str, Any]) -> bool:
        """Validate trading signal with additional relationship checks"""
        is_valid = super().validate(data)
        
        if is_valid:
            is_valid &= self.validate_stop_take_relationship(data)
        
        return is_valid


def validate_model_data(model_instance: Any, validator_class: type = None) -> bool:
    """Validate model instance data"""
    try:
        # Try to call the model's validate method if it exists
        if hasattr(model_instance, 'validate'):
            model_instance.validate()
            return True
        
        # If no validate method, use provided validator
        if validator_class:
            validator = validator_class()
            data = model_instance.__dict__
            return validator.validate(data)
        
        return True
    
    except DataValidationError:
        return False
    except Exception:
        return False


def create_validation_summary(errors: List[str]) -> Dict[str, Any]:
    """Create validation summary from errors"""
    return {
        'is_valid': len(errors) == 0,
        'error_count': len(errors),
        'errors': errors,
        'timestamp': datetime.now()
    }