"""
Pip/Point Standardization Utility
Handles decimal point conversion across different broker types and currency pairs.
Eliminates SPREAD_MISMATCH by normalizing all calculations to a standard 'pip' unit.

FIX #2: SPREAD_MISMATCH - Pip/Spread Calculation Bug
"""

import logging
from typing import Any, Dict, Optional, Tuple
from enum import Enum

logger = logging.getLogger(__name__)


class BrokerType(Enum):
    """Broker decimal precision"""
    FOUR_DIGIT = "4digit"   # EUR/USD = 1.2345
    FIVE_DIGIT = "5digit"   # EUR/USD = 1.23450


class PipStandardizer:
    """
    Normalize pip calculations across broker types.
    
    Key Rules:
    1. All internal calculations use "standard pips" (1 pip = 0.0001 for standard pairs)
    2. JPY pairs: 1 pip = 0.01 (only 2 decimal places)
    3. Convert broker-reported values to standard pips
    4. Convert standard pips back to broker format for API submission
    """
    
    # Standard definitions (USD pairs except JPY)
    STANDARD_PIP_VALUE = 0.0001  # 4 decimal places
    JPY_PIP_VALUE = 0.01          # 2 decimal places
    
    # Currency pairs to decimal places (standard pairs)
    PAIR_DECIMAL_PLACES = {
        # Major pairs (USD base)
        'EURUSD': 5,
        'GBPUSD': 5,
        'AUDUSD': 5,
        'NZDUSD': 5,
        'USDCAD': 5,
        'USDCHF': 5,
        
        # JPY pairs (only 2-3 decimal places)
        'USDJPY': 3,
        'EURJPY': 3,
        'GBPJPY': 3,
        'AUDJPY': 3,
        'CADJPY': 3,
        'CHFJPY': 3,
        'NZDJPY': 3,
        
        # Cross pairs
        'EURGBP': 5,
        'EURCHF': 5,
        'EURCAD': 5,
        'EURAUD': 5,
        'EURNZD': 5,
        'GBPCHF': 5,
        'GBPCAD': 5,
        'GBPAUD': 5,
        'AUDNZD': 5,
        'AUDCHF': 5,
        'AUDCAD': 5,
    }
    
    @staticmethod
    def normalize_symbol(symbol: str, suffix: str = "") -> str:
        """
        Normalize a broker/user symbol into MT5 format.

        Examples:
        - EUR/USD -> EURUSD
        - usd/jpy -> USDJPY
        - USDCAD + '.a' -> USDCAD.a
        """
        base_symbol = str(symbol or "").strip().upper().replace("/", "").replace("-", "")
        broker_suffix = str(suffix or "").strip()
        if broker_suffix and not base_symbol.endswith(broker_suffix.upper()):
            return f"{base_symbol}{broker_suffix}"
        return base_symbol

    @staticmethod
    def get_pair_decimal_places(symbol: str) -> int:
        """
        Get number of decimal places for a symbol.
        
        Args:
            symbol: Symbol (e.g., 'EURUSD', 'EUR/USD')
            
        Returns:
            Number of decimal places (3-5)
        """
        # Normalize symbol (remove slash)
        clean_symbol = PipStandardizer.normalize_symbol(symbol)
        
        # Return from map, default to 5 for unknown pairs
        return PipStandardizer.PAIR_DECIMAL_PLACES.get(clean_symbol, 5)

    @staticmethod
    def get_decimal_places(symbol: str) -> int:
        """
        Backward-compatible alias used by older execution/orchestrator paths.
        """
        return PipStandardizer.get_pair_decimal_places(symbol)
    
    @staticmethod
    def is_jpy_pair(symbol: str) -> bool:
        """Check if symbol is a JPY pair"""
        clean_symbol = PipStandardizer.normalize_symbol(symbol)
        return 'JPY' in clean_symbol
    
    @staticmethod
    def get_pip_value_for_pair(symbol: str) -> float:
        """
        Get the pip value (1 pip in decimal form) for a pair.
        
        Args:
            symbol: Forex pair
            
        Returns:
            Pip value (0.01 for JPY, 0.0001 for others)
        """
        if PipStandardizer.is_jpy_pair(symbol):
            return PipStandardizer.JPY_PIP_VALUE  # 0.01
        return PipStandardizer.STANDARD_PIP_VALUE  # 0.0001

    @staticmethod
    def get_pip_value_from_digits(
        digits: Optional[int],
        point: Optional[float] = None,
        symbol: Optional[str] = None,
    ) -> float:
        """
        Resolve the decimal value of 1 pip using broker digits when available.

        Rules:
        - 5-digit symbols: 1 pip = 10 points
        - 3-digit symbols: 1 pip = 10 points
        - 4-digit symbols: 1 pip = 1 point
        - 2-digit symbols: 1 pip = 1 point
        """
        try:
            digits_int = int(digits) if digits is not None else None
        except Exception:
            digits_int = None

        try:
            point_value = abs(float(point)) if point is not None else None
        except Exception:
            point_value = None

        if digits_int in {3, 5} and point_value and point_value > 0:
            return point_value * 10.0
        if digits_int in {2, 4} and point_value and point_value > 0:
            return point_value

        if digits_int == 3:
            return PipStandardizer.JPY_PIP_VALUE
        if digits_int == 5:
            return PipStandardizer.STANDARD_PIP_VALUE
        if digits_int == 2 and point_value and point_value > 0:
            return point_value
        if digits_int == 4 and point_value and point_value > 0:
            return point_value

        if symbol:
            return PipStandardizer.get_pip_value_for_pair(symbol)
        return PipStandardizer.STANDARD_PIP_VALUE
    
    @staticmethod
    def broker_value_to_pips(value: float, symbol: str) -> float:
        """
        Convert broker-reported value to standardized pips.
        
        Args:
            value: Broker value (what MT5 returns)
            symbol: Currency pair
            
        Returns:
            Value in standard pips
            
        Example:
            GBP/USD spread 0.00009 (5-digit) -> 0.9 pips
            spread_pips = broker_value_to_pips(0.00009, 'GBPUSD')  # Returns 0.9
        """
        pip_value = PipStandardizer.get_pip_value_for_pair(symbol)
        
        # Avoid division by zero
        if pip_value == 0:
            logger.warning(f"[PIP_STANDARDIZER] Invalid pip_value for {symbol}")
            return 0.0
        
        pips = value / pip_value
        return pips

    @staticmethod
    def broker_value_to_pips_by_digits(
        value: float,
        digits: Optional[int],
        point: Optional[float] = None,
        symbol: Optional[str] = None,
    ) -> float:
        """
        Convert a raw broker price delta to pips using symbol digits/point.
        """
        pip_value = PipStandardizer.get_pip_value_from_digits(
            digits=digits,
            point=point,
            symbol=symbol,
        )
        if pip_value <= 0:
            logger.warning("[PIP_STANDARDIZER] Invalid digit-based pip_value for %s", symbol or "UNKNOWN")
            return 0.0
        return float(value) / pip_value

    @staticmethod
    def spread_to_pips(
        ask: float,
        bid: float,
        *,
        digits: Optional[int] = None,
        point: Optional[float] = None,
        symbol: Optional[str] = None,
        symbol_info: Optional[Any] = None,
    ) -> float:
        """
        Convert a raw ask/bid spread into standard pips using MT5 symbol metadata.
        """
        if symbol_info is not None:
            digits = getattr(symbol_info, "digits", digits)
            point = getattr(symbol_info, "point", point)
        spread = float(ask or 0.0) - float(bid or 0.0)
        if spread <= 0:
            return 0.0
        return PipStandardizer.broker_value_to_pips_by_digits(
            value=spread,
            digits=digits,
            point=point,
            symbol=symbol,
        )
    
    @staticmethod
    def pips_to_broker_value(pips: float, symbol: str) -> float:
        """
        Convert standard pips back to broker format.
        
        Args:
            pips: Number of standard pips
            symbol: Currency pair
            
        Returns:
            Broker decimal value
            
        Example:
            Spread tolerance = 2.0 pips -> 0.0002 (standard pair) or 0.02 (JPY)
            broker_value = pips_to_broker_value(2.0, 'EURUSD')  # Returns 0.0002
        """
        pip_value = PipStandardizer.get_pip_value_for_pair(symbol)
        return pips * pip_value
    
    @staticmethod
    def normalize_spread_check(
        broker_spread: float,
        symbol: str,
        max_pips_tolerance: float
    ) -> Tuple[bool, Dict]:
        """
        Check if spread is acceptable using normalized pip values.
        
        Args:
            broker_spread: Raw spread from broker
            symbol: Currency pair
            max_pips_tolerance: Maximum acceptable spread in pips
            
        Returns:
            (is_acceptable, details_dict)
        """
        spread_pips = PipStandardizer.broker_value_to_pips(broker_spread, symbol)
        is_ok = spread_pips <= max_pips_tolerance
        
        return is_ok, {
            'symbol': symbol,
            'broker_spread': broker_spread,
            'spread_pips': spread_pips,
            'max_pips_tolerance': max_pips_tolerance,
            'is_acceptable': is_ok,
            'excess_pips': max(0, spread_pips - max_pips_tolerance)
        }
    
    @staticmethod
    def normalize_sl_tp_distance(
        entry_price: float,
        sl_price: float,
        tp_price: float,
        symbol: str,
        direction: str
    ) -> Dict:
        """
        Calculate SL/TP distances in standard pips.
        
        Args:
            entry_price: Entry price
            sl_price: Stop loss price
            tp_price: Take profit price
            symbol: Currency pair
            direction: 'BUY' or 'SELL'
            
        Returns:
            Dictionary with pip distances
        """
        pip_value = PipStandardizer.get_pip_value_for_pair(symbol)
        
        if direction.upper() == 'BUY':
            sl_pips = (entry_price - sl_price) / pip_value
            tp_pips = (tp_price - entry_price) / pip_value
        else:  # SELL
            sl_pips = (sl_price - entry_price) / pip_value
            tp_pips = (entry_price - tp_price) / pip_value
        
        return {
            'symbol': symbol,
            'direction': direction,
            'entry_price': entry_price,
            'sl_price': sl_price,
            'tp_price': tp_price,
            'sl_distance_pips': abs(sl_pips),
            'tp_distance_pips': abs(tp_pips),
            'risk_reward_ratio': abs(tp_pips) / abs(sl_pips) if sl_pips != 0 else 0
        }


def get_pip_multiplier(symbol: str) -> float:
    """Compatibility helper returning the standard pip size for a symbol."""
    return PipStandardizer.get_pip_value_for_pair(symbol)


def calculate_true_spread_pips(
    symbol: str,
    ask: float,
    bid: float,
    *,
    digits: Optional[int] = None,
    point: Optional[float] = None,
    symbol_info: Optional[Any] = None,
) -> float:
    """Calculate live spread in standard pips using broker digits/point when available."""
    return round(
        PipStandardizer.spread_to_pips(
            ask=ask,
            bid=bid,
            digits=digits,
            point=point,
            symbol=symbol,
            symbol_info=symbol_info,
        ),
        2,
    )


# ============================================================================
# Quick Reference Examples
# ============================================================================

if __name__ == "__main__":
    # Example 1: Spread check (GBPUSD)
    print("=== Example 1: Spread Normalization ===")
    is_ok, details = PipStandardizer.normalize_spread_check(
        broker_spread=0.00009,  # 0.9 pips in 5-digit broker format
        symbol='GBPUSD',
        max_pips_tolerance=2.0
    )
    print(f"Spread acceptable: {is_ok}")
    print(f"Details: {details}")
    
    # Example 2: JPY pair spread
    print("\n=== Example 2: JPY Pair Spread ===")
    is_ok, details = PipStandardizer.normalize_spread_check(
        broker_spread=0.015,  # 1.5 pips in JPY format
        symbol='USDJPY',
        max_pips_tolerance=3.0
    )
    print(f"Spread acceptable: {is_ok}")
    print(f"Spread in pips: {details['spread_pips']}")
    
    # Example 3: SL/TP distances
    print("\n=== Example 3: SL/TP Distance Calculation ===")
    distances = PipStandardizer.normalize_sl_tp_distance(
        entry_price=1.2345,
        sl_price=1.2300,
        tp_price=1.2400,
        symbol='EURUSD',
        direction='BUY'
    )
    print(f"SL distance: {distances['sl_distance_pips']:.1f} pips")
    print(f"TP distance: {distances['tp_distance_pips']:.1f} pips")
    print(f"R:R ratio: {distances['risk_reward_ratio']:.2f}")
