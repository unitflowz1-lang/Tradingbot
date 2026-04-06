"""
Robust cleanup utilities for cross-platform test compatibility.
"""

import os
import shutil
import time
import logging
import tempfile
from pathlib import Path
from typing import Optional, Union
from contextlib import contextmanager

from .platform_utils import is_windows, handle_permission_error, get_temp_dir_prefix

logger = logging.getLogger(__name__)


def safe_rmtree(path: Union[str, Path], max_retries: int = 3, delay: float = 0.1) -> bool:
    """
    Safely remove directory tree with retries for Windows file locking.
    
    Args:
        path: Path to directory to remove
        max_retries: Maximum number of retry attempts
        delay: Delay between retries in seconds
        
    Returns:
        True if successful, False otherwise
    """
    path = Path(path)
    
    if not path.exists():
        return True
        
    for attempt in range(max_retries + 1):
        try:
            shutil.rmtree(str(path))
            return True
        except (PermissionError, OSError) as e:
            if attempt == max_retries:
                handle_permission_error(e, str(path))
                return False
            else:
                logger.debug(f"Cleanup attempt {attempt + 1} failed for {path}: {e}")
                time.sleep(delay * (2 ** attempt))  # Exponential backoff
                
    return False


def wait_for_file_release(filepath: Union[str, Path], timeout: float = 5.0) -> bool:
    """
    Wait for file to be released by other processes.
    
    Args:
        filepath: Path to file to check
        timeout: Maximum time to wait in seconds
        
    Returns:
        True if file is released, False if timeout
    """
    filepath = Path(filepath)
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        try:
            # Try to open the file exclusively
            if filepath.exists():
                with open(filepath, 'r+b') as f:
                    pass
            return True
        except (PermissionError, OSError):
            time.sleep(0.1)
            
    return False


def safe_remove_file(filepath: Union[str, Path], max_retries: int = 3) -> bool:
    """
    Safely remove a single file with retries.
    
    Args:
        filepath: Path to file to remove
        max_retries: Maximum number of retry attempts
        
    Returns:
        True if successful, False otherwise
    """
    filepath = Path(filepath)
    
    if not filepath.exists():
        return True
        
    for attempt in range(max_retries + 1):
        try:
            filepath.unlink()
            return True
        except (PermissionError, OSError) as e:
            if attempt == max_retries:
                handle_permission_error(e, str(filepath))
                return False
            else:
                time.sleep(0.1 * (2 ** attempt))
                
    return False


@contextmanager
def temporary_directory(cleanup_retries: int = 3, prefix: Optional[str] = None):
    """
    Context manager for temporary directories with robust cleanup.
    
    Args:
        cleanup_retries: Number of cleanup retry attempts
        prefix: Prefix for temporary directory name
        
    Yields:
        Path to temporary directory
    """
    if prefix is None:
        prefix = get_temp_dir_prefix()
        
    temp_dir = tempfile.mkdtemp(prefix=prefix)
    temp_path = Path(temp_dir)
    
    try:
        yield temp_dir
    finally:
        # Attempt cleanup with retries
        success = safe_rmtree(temp_path, max_retries=cleanup_retries)
        if not success:
            logger.warning(
                f"Could not fully clean up temporary directory: {temp_path}. "
                f"Manual cleanup may be required."
            )


def cleanup_tensorboard_logs(log_dir: Union[str, Path], max_retries: int = 3) -> bool:
    """
    Clean up TensorBoard log files with special handling.
    
    Args:
        log_dir: Directory containing TensorBoard logs
        max_retries: Maximum number of retry attempts
        
    Returns:
        True if successful, False otherwise
    """
    log_dir = Path(log_dir)
    
    if not log_dir.exists():
        return True
        
    # First, try to wait for any TensorBoard processes to release files
    for file_path in log_dir.rglob('*'):
        if file_path.is_file():
            wait_for_file_release(file_path, timeout=2.0)
    
    # Then attempt cleanup
    return safe_rmtree(log_dir, max_retries=max_retries)


def ensure_directory_writable(path: Union[str, Path]) -> bool:
    """
    Ensure directory is writable, creating it if necessary.
    
    Args:
        path: Directory path to check/create
        
    Returns:
        True if directory is writable, False otherwise
    """
    path = Path(path)
    
    try:
        path.mkdir(parents=True, exist_ok=True)
        
        # Test write access
        test_file = path / '.write_test'
        test_file.write_text('test')
        test_file.unlink()
        
        return True
    except (PermissionError, OSError) as e:
        logger.warning(f"Directory {path} is not writable: {e}")
        return False