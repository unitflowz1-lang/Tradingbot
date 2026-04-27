"""
Platform-specific utilities for cross-platform test compatibility.
"""

import platform
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


def is_windows() -> bool:
    """Check if running on Windows."""
    return platform.system().lower() == 'windows'


def is_unix() -> bool:
    """Check if running on Unix-like system."""
    return platform.system().lower() in ('linux', 'darwin')


def get_cleanup_strategy() -> str:
    """Get appropriate cleanup strategy for current platform."""
    if is_windows():
        return 'windows_retry'
    else:
        return 'unix_standard'


def handle_permission_error(error: PermissionError, path: str) -> None:
    """
    Handle permission errors in a platform-appropriate way.
    
    Args:
        error: The permission error that occurred
        path: Path that caused the error
    """
    if is_windows():
        logger.warning(
            f"Windows file permission error for {path}: {error}. "
            f"This is often caused by antivirus software or file handles "
            f"not being released immediately. The test will continue."
        )
    else:
        logger.warning(
            f"Permission error for {path}: {error}. "
            f"Check file permissions and ownership."
        )


def force_close_handles_windows(path: str) -> bool:
    """
    Attempt to force close file handles on Windows.
    
    Args:
        path: Path to close handles for
        
    Returns:
        True if successful, False otherwise
    """
    if not is_windows():
        return False
        
    try:
        # On Windows, we can try to use handle.exe if available
        # For now, we'll just return False as this requires external tools
        return False
    except Exception as e:
        logger.debug(f"Could not force close handles for {path}: {e}")
        return False


def get_temp_dir_prefix() -> str:
    """Get appropriate temporary directory prefix for platform."""
    if is_windows():
        return "pytest_temp_"
    else:
        return "pytest_temp_"