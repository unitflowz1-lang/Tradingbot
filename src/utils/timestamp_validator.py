"""
Timestamp Validation Utility

Provides one-time startup sanity checks to validate that MT5 broker timestamps
are synchronized with system UTC time. Does NOT apply any offset corrections -
only reports delta for diagnostic purposes.

Key Rule: pos.time from mt5.positions_get() is ALWAYS a Unix timestamp (UTC-based).
No manual offset adjustments should ever be applied.
"""

import logging
from datetime import datetime, timezone
import MetaTrader5 as mt5
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


def validate_mt5_timestamp_sync(symbol: str = "EURUSD") -> Dict[str, Any]:
    """
    One-time startup validation: Check delta between MT5 server time and local UTC.
    
    This is a DIAGNOSTIC ONLY function. It does NOT modify any timestamps or
    apply offsets. It only reports the delta to help diagnose timezone issues.
    
    IMPORTANT: This function should run ONCE at startup. Do NOT use the returned
    delta to adjust position.time values - they are already UTC.
    
    Args:
        symbol: A liquid symbol to get a tick for (default: EURUSD)
    
    Returns:
        Dictionary with validation results:
        {
            'is_synchronized': bool,  # True if delta is < 2 seconds
            'local_utc_time': datetime,  # System UTC time
            'mt5_server_time': datetime,  # MT5 server time (from tick)
            'delta_seconds': float,  # Difference in seconds
            'message': str,  # Human-readable summary
            'recommendation': str,  # Any corrective action needed
        }
    """
    try:
        # Get local UTC time
        local_utc_time = datetime.now(timezone.utc)
        
        # Get MT5 tick to extract server time
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return {
                'is_synchronized': False,
                'local_utc_time': local_utc_time,
                'mt5_server_time': None,
                'delta_seconds': None,
                'message': f'[TIMESTAMP_VALIDATION_ERROR] Could not get tick for {symbol}. MT5 may be disconnected.',
                'recommendation': 'Check MT5 connection and market availability.',
                'error': mt5.last_error(),
            }
        
        # Extract MT5 server time from tick (tick.time is Unix timestamp UTC)
        mt5_server_time = datetime.fromtimestamp(tick.time, tz=timezone.utc)
        
        # Calculate delta
        delta_seconds = (local_utc_time - mt5_server_time).total_seconds()
        
        # Determine if synchronized (allowing 2 second tolerance for network/processing)
        is_synchronized = abs(delta_seconds) < 2.0
        
        if is_synchronized:
            message = (
                f'[TIMESTAMP_SYNC_OK] System UTC and MT5 broker time are synchronized. '
                f'Delta: {delta_seconds:.2f} seconds (tolerance: <2s). '
                f'pos.time values are trustworthy without offset adjustment.'
            )
            recommendation = (
                'No action needed. BROKER_TIMEZONE_OFFSET_HOURS is deprecated and should not be used.'
            )
        else:
            message = (
                f'[TIMESTAMP_DELTA_WARNING] System UTC and MT5 broker differ by {abs(delta_seconds):.2f} seconds. '
                f'Local: {local_utc_time.isoformat()}, MT5: {mt5_server_time.isoformat()}. '
                f'This delta is for diagnostic purposes only - do NOT use it to adjust position.time values.'
            )
            if delta_seconds > 0:
                recommendation = (
                    'System clock appears to be ahead of MT5 broker. This is usually harmless. '
                    'Do NOT apply BROKER_TIMEZONE_OFFSET_HOURS - pos.time is already UTC.'
                )
            else:
                recommendation = (
                    'System clock appears to be behind MT5 broker. This is usually harmless. '
                    'Do NOT apply BROKER_TIMEZONE_OFFSET_HOURS - pos.time is already UTC.'
                )
        
        logger.info(message)
        logger.info(f'[TIMESTAMP_RECOMMENDATION] {recommendation}')
        
        return {
            'is_synchronized': is_synchronized,
            'local_utc_time': local_utc_time,
            'mt5_server_time': mt5_server_time,
            'delta_seconds': delta_seconds,
            'message': message,
            'recommendation': recommendation,
            'error': None,
        }
        
    except Exception as e:
        error_msg = f'[TIMESTAMP_VALIDATION_EXCEPTION] {str(e)}'
        logger.error(error_msg)
        return {
            'is_synchronized': False,
            'local_utc_time': datetime.now(timezone.utc),
            'mt5_server_time': None,
            'delta_seconds': None,
            'message': error_msg,
            'recommendation': 'Check MT5 connection and try again.',
            'error': str(e),
        }


def log_timestamp_deprecation_notice() -> None:
    """
    Log a one-time notice that BROKER_TIMEZONE_OFFSET_HOURS is deprecated.
    
    This should be called once at startup to inform operators that the manual
    timezone offset is no longer needed or used.
    """
    logger.critical(
        '[TIMESTAMP_DEPRECATION_NOTICE] BROKER_TIMEZONE_OFFSET_HOURS environment variable is DEPRECATED. '
        'MT5 position.time values are Unix timestamps (UTC-based) and are treated as UTC directly. '
        'No offset adjustment is applied. If you see POSITION_AGE_SYNC_WARNING messages, '
        'do NOT adjust BROKER_TIMEZONE_OFFSET_HOURS - verify MT5 connection instead.'
    )
