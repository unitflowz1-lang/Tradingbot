"""
Safe formatting utilities for numerical values.
Prevents NoneType formatting crashes and provides controlled defaults.
"""
import logging

logger = logging.getLogger(__name__)

def safe_float(val, default=0.0):
    """
    Converts None or invalid values to a controlled default float.
    
    Args:
        val: The value to convert.
        default: The default value to return if val is None or invalid.
        
    Returns:
        float: The converted value or default.
    """
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default

def format_float(val, spec=".2f", default_str="N/A"):
    """
    Safely formats a float value. If val is None or invalid, returns default_str.
    
    Args:
        val: The value to format.
        spec: The format specifier (e.g., ".2f").
        default_str: The string to return if formatting fails or val is None.
        
    Returns:
        str: The formatted string.
    """
    if val is None:
        return default_str
    try:
        # Check if the value is actually a number
        f_val = float(val)
        return f"{f_val:{spec}}"
    except (ValueError, TypeError):
        return default_str
    except Exception as e:
        logger.error(f"Unexpected error formatting float {val} with spec {spec}: {e}")
        return default_str
