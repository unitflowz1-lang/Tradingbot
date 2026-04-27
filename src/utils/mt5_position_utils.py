"""
MT5 Position Utilities
=====================

Safe attribute access for both raw MT5 position objects and internal Position model objects.
Handles the distinction between:
- Raw MT5 objects (use .price_open for entry price)
- Position model objects (use .entry_price for entry price)

PROBLEM SOLVED:
- 'TradePosition' object has no attribute 'entry_price' errors
- Safe fallback for attribute access patterns
- Clear logging of which attribute was used

USAGE:
    from src.utils.mt5_position_utils import safe_get_entry_price
    
    # Works with both MT5 raw objects and Position model objects
    entry = safe_get_entry_price(position)  # Returns float or 0.0
    
    # Can also be used generically for any attribute
    sl = safe_get_position_attr(position, 'stop_loss', 'sl', default=0.0)
"""

import logging
from typing import Any, Optional, Union
from dataclasses import is_dataclass

logger = logging.getLogger(__name__)


def safe_get_entry_price(position: Any, default: float = 0.0) -> float:
    """
    Safely get entry price from MT5 position object or Position model.
    
    Handles both:
    - Raw MT5 TradePosition objects (uses .price_open)
    - Internal Position model objects (uses .entry_price)
    
    Args:
        position: Position object (MT5 raw or Position model)
        default: Default value if attribute not found
        
    Returns:
        float: Entry price, or default value if not found
        
    Example:
        >>> entry = safe_get_entry_price(position)
        >>> sl = safe_get_entry_price(raw_mt5_obj, default=1.0)
    """
    if position is None:
        logger.warning("[SAFE_GET] Position is None, returning default: %.5f", default)
        return float(default)
    
    try:
        # Try Position model first (.entry_price)
        if hasattr(position, 'entry_price'):
            value = getattr(position, 'entry_price', None)
            if value is not None:
                logger.debug("[SAFE_GET_ENTRY_PRICE] Using .entry_price: %.5f", float(value))
                return float(value)
        
        # Fallback to MT5 raw object (.price_open)
        if hasattr(position, 'price_open'):
            value = getattr(position, 'price_open', None)
            if value is not None:
                logger.debug("[SAFE_GET_ENTRY_PRICE] Using .price_open (MT5 raw): %.5f", float(value))
                return float(value)
        
        # Last resort: return default
        logger.warning(
            "[SAFE_GET_ENTRY_PRICE] Neither .entry_price nor .price_open found on %s. Returning default: %.5f",
            type(position).__name__,
            default
        )
        return float(default)
        
    except Exception as e:
        logger.error(
            "[SAFE_GET_ENTRY_PRICE] Error extracting entry price from %s: %s. Returning default: %.5f",
            type(position).__name__,
            str(e),
            default
        )
        return float(default)


def safe_get_stop_loss(position: Any, default: float = 0.0) -> float:
    """
    Safely get stop loss from MT5 position object or Position model.
    
    Tries .stop_loss, then .sl.
    
    Args:
        position: Position object (MT5 raw or Position model)
        default: Default value if attribute not found
        
    Returns:
        float: Stop loss value, or default value if not found
    """
    if position is None:
        return float(default)
    
    try:
        # Try .stop_loss first
        if hasattr(position, 'stop_loss'):
            value = getattr(position, 'stop_loss', None)
            if value is not None:
                logger.debug("[SAFE_GET_SL] Using .stop_loss: %.5f", float(value))
                return float(value)
        
        # Try .sl (MT5 abbreviation)
        if hasattr(position, 'sl'):
            value = getattr(position, 'sl', None)
            if value is not None:
                logger.debug("[SAFE_GET_SL] Using .sl: %.5f", float(value))
                return float(value)
        
        return float(default)
        
    except Exception as e:
        logger.error("[SAFE_GET_SL] Error extracting stop loss: %s. Returning default: %.5f", str(e), default)
        return float(default)


def safe_get_take_profit(position: Any, default: float = 0.0) -> float:
    """
    Safely get take profit from MT5 position object or Position model.
    
    Tries .take_profit, then .tp.
    
    Args:
        position: Position object (MT5 raw or Position model)
        default: Default value if attribute not found
        
    Returns:
        float: Take profit value, or default value if not found
    """
    if position is None:
        return float(default)
    
    try:
        # Try .take_profit first
        if hasattr(position, 'take_profit'):
            value = getattr(position, 'take_profit', None)
            if value is not None:
                logger.debug("[SAFE_GET_TP] Using .take_profit: %.5f", float(value))
                return float(value)
        
        # Try .tp (MT5 abbreviation)
        if hasattr(position, 'tp'):
            value = getattr(position, 'tp', None)
            if value is not None:
                logger.debug("[SAFE_GET_TP] Using .tp: %.5f", float(value))
                return float(value)
        
        return float(default)
        
    except Exception as e:
        logger.error("[SAFE_GET_TP] Error extracting take profit: %s. Returning default: %.5f", str(e), default)
        return float(default)


def safe_get_position_attr(
    position: Any,
    *attr_names: str,
    default: Any = None,
    return_type: type = None
) -> Any:
    """
    Generic safe attribute getter for position objects.
    
    Tries multiple attribute names in order until one is found.
    
    Args:
        position: Position object
        *attr_names: Attribute names to try (in order)
        default: Default value if none found
        return_type: Type to cast result to (e.g., float, str)
        
    Returns:
        Attribute value, or default if not found
        
    Example:
        >>> entry = safe_get_position_attr(pos, 'entry_price', 'price_open', default=0.0, return_type=float)
        >>> symbol = safe_get_position_attr(pos, 'symbol', 'pair', default='UNKNOWN')
    """
    if position is None:
        logger.warning("[SAFE_GET_ATTR] Position is None, returning default: %s", default)
        return default
    
    for attr_name in attr_names:
        try:
            if hasattr(position, attr_name):
                value = getattr(position, attr_name, None)
                if value is not None:
                    result = return_type(value) if return_type else value
                    logger.debug("[SAFE_GET_ATTR] Using .%s: %s", attr_name, result)
                    return result
        except Exception as e:
            logger.debug("[SAFE_GET_ATTR] Error getting .%s: %s", attr_name, str(e))
            continue
    
    logger.warning(
        "[SAFE_GET_ATTR] None of %s found on %s. Returning default: %s",
        attr_names,
        type(position).__name__,
        default
    )
    return default


def get_position_info_safe(position: Any) -> dict:
    """
    Extract all important position info safely from either MT5 or Position model object.
    
    Returns a dictionary with standardized keys:
    - entry_price: Entry price
    - stop_loss: Stop loss level
    - take_profit: Take profit level
    - current_price: Current market price
    - symbol: Symbol name
    - ticket: Position ticket/ID
    - direction: LONG or SHORT
    - volume: Quantity/volume
    
    Args:
        position: Position object (MT5 raw or Position model)
        
    Returns:
        dict: Standardized position information
        
    Example:
        >>> info = get_position_info_safe(position)
        >>> print(info['entry_price'])
        1.08500
    """
    return {
        'entry_price': safe_get_entry_price(position, default=0.0),
        'stop_loss': safe_get_stop_loss(position, default=0.0),
        'take_profit': safe_get_take_profit(position, default=0.0),
        'current_price': safe_get_position_attr(position, 'current_price', 'price_current', default=0.0, return_type=float),
        'symbol': safe_get_position_attr(position, 'symbol', 'pair', default='UNKNOWN'),
        'ticket': safe_get_position_attr(position, 'position_id', 'ticket', default=''),
        'direction': safe_get_position_attr(position, 'direction', 'type', default='UNKNOWN'),
        'volume': safe_get_position_attr(position, 'quantity', 'volume', default=0.0, return_type=float),
    }


if __name__ == '__main__':
    # Example usage and testing
    print("MT5 Position Utilities - Safe Attribute Access")
    print("=" * 50)
    print("\nUsage Examples:")
    print("1. safe_get_entry_price(position)")
    print("2. safe_get_stop_loss(position)")
    print("3. safe_get_take_profit(position)")
    print("4. safe_get_position_attr(position, 'attr1', 'attr2', default=0.0, return_type=float)")
    print("5. get_position_info_safe(position)")
    print("\nAll functions handle both:")
    print("- Raw MT5 TradePosition objects")
    print("- Internal Position model objects")
