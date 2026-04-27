"""
JSON Utility Functions - Safe file handling with robust error recovery

Provides safe JSON loading/saving with:
- Empty file detection
- Graceful error handling
- Automatic file recovery
- Logging of issues without raising exceptions
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def safe_json_load(
    file_path: str,
    default: Optional[Dict[str, Any]] = None,
    auto_recover: bool = True,
) -> Dict[str, Any]:
    """
    Safely load a JSON file with robust error handling.
    
    FEATURES:
    - Checks file existence before attempting load
    - Detects and handles empty files gracefully
    - Catches JSON decode errors
    - Automatically recovers corrupted files by rewriting with default value
    - Returns default dict on any error
    - Logs warnings (not errors) to avoid alarming operators
    
    Args:
        file_path: Path to JSON file to load
        default: Default dict to return on error (default: {})
        auto_recover: If True, overwrite corrupted files with default value
        
    Returns:
        Loaded JSON dict, or default dict if file doesn't exist or is corrupted
        
    Example:
        # Load with automatic recovery
        cache = safe_json_load("data/macro_risk_cache.json", default={})
        state = safe_json_load("data/state.json", default={"positions": []})
    """
    if default is None:
        default = {}
    
    # ─────────────────────────────────────────────────────────────────────
    # Step 1: Validate file existence
    # ─────────────────────────────────────────────────────────────────────
    if not os.path.exists(file_path):
        logger.debug(
            f"[JSON_UTILS] File not found: {file_path}. Returning default value."
        )
        return default.copy() if default else {}
    
    # ─────────────────────────────────────────────────────────────────────
    # Step 2: Check file size (detect empty files)
    # ─────────────────────────────────────────────────────────────────────
    try:
        file_size = os.path.getsize(file_path)
        if file_size == 0:
            logger.warning(
                f"[JSON_UTILS] Empty JSON file detected: {file_path}. "
                f"File size is 0 bytes. Reinitializing with default value."
            )
            if auto_recover:
                _safe_json_write(file_path, default)
            return default.copy() if default else {}
    except OSError as e:
        logger.warning(
            f"[JSON_UTILS] Cannot check file size for {file_path}: {str(e)}. "
            f"Returning default value."
        )
        return default.copy() if default else {}
    
    # ─────────────────────────────────────────────────────────────────────
    # Step 3: Read file content
    # ─────────────────────────────────────────────────────────────────────
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            raw_content = f.read()
    except (IOError, OSError) as e:
        logger.warning(
            f"[JSON_UTILS] Cannot read file {file_path}: {str(e)}. "
            f"Returning default value."
        )
        return default.copy() if default else {}
    
    # ─────────────────────────────────────────────────────────────────────
    # Step 4: Check if content is just whitespace
    # ─────────────────────────────────────────────────────────────────────
    if not raw_content.strip():
        logger.warning(
            f"[JSON_UTILS] JSON file contains only whitespace: {file_path}. "
            f"Reinitializing with default value."
        )
        if auto_recover:
            _safe_json_write(file_path, default)
        return default.copy() if default else {}
    
    # ─────────────────────────────────────────────────────────────────────
    # Step 5: Parse JSON with error handling
    # ─────────────────────────────────────────────────────────────────────
    try:
        data = json.loads(raw_content)
        
        # Validate that parsed data is a dict
        if not isinstance(data, dict):
            logger.warning(
                f"[JSON_UTILS] JSON file does not contain a dict (got {type(data).__name__}): {file_path}. "
                f"Reinitializing with default value."
            )
            if auto_recover:
                _safe_json_write(file_path, default)
            return default.copy() if default else {}
        
        logger.debug(f"[JSON_UTILS] Successfully loaded {file_path} ({len(data)} keys)")
        return data
        
    except json.JSONDecodeError as e:
        logger.warning(
            f"[JSON_UTILS] JSON decode error in {file_path}: {str(e)} "
            f"(line {e.lineno}, column {e.colno}). "
            f"Content preview: {raw_content[:100]}... "
            f"Reinitializing with default value."
        )
        if auto_recover:
            _safe_json_write(file_path, default)
        return default.copy() if default else {}
    except Exception as e:
        logger.warning(
            f"[JSON_UTILS] Unexpected error loading {file_path}: {str(e)}. "
            f"Returning default value."
        )
        return default.copy() if default else {}


def safe_json_load_list(
    file_path: str,
    default: Optional[list] = None,
    auto_recover: bool = True,
) -> list:
    """
    Safely load a JSON file that contains a list.
    
    Similar to safe_json_load but for files containing lists instead of dicts.
    
    Args:
        file_path: Path to JSON file to load
        default: Default list to return on error (default: [])
        auto_recover: If True, overwrite corrupted files with default value
        
    Returns:
        Loaded JSON list, or default list if file doesn't exist or is corrupted
    """
    if default is None:
        default = []
    
    # ─────────────────────────────────────────────────────────────────────
    # Step 1: Check file existence and size
    # ─────────────────────────────────────────────────────────────────────
    if not os.path.exists(file_path):
        logger.debug(f"[JSON_UTILS] List file not found: {file_path}. Returning default.")
        return default.copy() if isinstance(default, list) else []
    
    try:
        file_size = os.path.getsize(file_path)
        if file_size == 0:
            logger.warning(f"[JSON_UTILS] Empty list JSON file: {file_path}. Reinitializing.")
            if auto_recover:
                _safe_json_write(file_path, default)
            return default.copy() if isinstance(default, list) else []
    except OSError as e:
        logger.warning(f"[JSON_UTILS] Cannot check file size for {file_path}: {str(e)}")
        return default.copy() if isinstance(default, list) else []
    
    # ─────────────────────────────────────────────────────────────────────
    # Step 2: Read and parse JSON
    # ─────────────────────────────────────────────────────────────────────
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            raw_content = f.read()
        
        if not raw_content.strip():
            logger.warning(f"[JSON_UTILS] List JSON file is empty/whitespace: {file_path}")
            if auto_recover:
                _safe_json_write(file_path, default)
            return default.copy() if isinstance(default, list) else []
        
        data = json.loads(raw_content)
        
        if not isinstance(data, list):
            logger.warning(
                f"[JSON_UTILS] JSON file is not a list (got {type(data).__name__}): {file_path}"
            )
            if auto_recover:
                _safe_json_write(file_path, default)
            return default.copy() if isinstance(default, list) else []
        
        logger.debug(f"[JSON_UTILS] Successfully loaded list from {file_path} ({len(data)} items)")
        return data
        
    except json.JSONDecodeError as e:
        logger.warning(
            f"[JSON_UTILS] JSON decode error in list file {file_path}: {str(e)} "
            f"(line {e.lineno}, col {e.colno}). Reinitializing."
        )
        if auto_recover:
            _safe_json_write(file_path, default)
        return default.copy() if isinstance(default, list) else []
    except Exception as e:
        logger.warning(f"[JSON_UTILS] Error loading list from {file_path}: {str(e)}")
        return default.copy() if isinstance(default, list) else []


def safe_json_write(
    file_path: str,
    data: Any,
    indent: int = 2,
    create_backup: bool = True,
) -> bool:
    """
    Safely write JSON data to file with backup support.
    
    FEATURES:
    - Creates parent directories if needed
    - Creates backup of existing file before overwrite
    - Uses atomic write pattern (temp file + rename)
    - Graceful error handling
    
    Args:
        file_path: Path to JSON file to write
        data: Data to serialize as JSON
        indent: JSON indentation level (default: 2)
        create_backup: If True, keep .bak of previous file
        
    Returns:
        True if successful, False otherwise
        
    Example:
        success = safe_json_write("data/state.json", {"key": "value"})
        if not success:
            logger.error("Failed to save state")
    """
    return _safe_json_write(
        file_path=file_path,
        data=data,
        indent=indent,
        create_backup=create_backup,
    )


# ───────────────────────────────────────────────────────────────────────────
# Private Helper Functions
# ───────────────────────────────────────────────────────────────────────────


def _safe_json_write(
    file_path: str,
    data: Any,
    indent: int = 2,
    create_backup: bool = True,
) -> bool:
    """Internal implementation of safe JSON write."""
    try:
        # ─────────────────────────────────────────────────────────────
        # Step 1: Create parent directories
        # ─────────────────────────────────────────────────────────────
        parent_dir = os.path.dirname(file_path)
        if parent_dir:
            Path(parent_dir).mkdir(parents=True, exist_ok=True)
        
        # ─────────────────────────────────────────────────────────────
        # Step 2: Create backup if existing file exists
        # ─────────────────────────────────────────────────────────────
        if create_backup and os.path.exists(file_path):
            backup_path = f"{file_path}.bak"
            try:
                if os.path.exists(backup_path):
                    os.remove(backup_path)
                os.rename(file_path, backup_path)
                logger.debug(f"[JSON_UTILS] Created backup: {backup_path}")
            except Exception as e:
                logger.warning(f"[JSON_UTILS] Failed to create backup: {str(e)}")
                # Continue anyway, backup is optional
        
        # ─────────────────────────────────────────────────────────────
        # Step 3: Write to temporary file (atomic write)
        # ─────────────────────────────────────────────────────────────
        temp_path = f"{file_path}.tmp"
        try:
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=indent, ensure_ascii=False)
            
            # ─────────────────────────────────────────────────────────
            # Step 4: Atomic rename
            # ─────────────────────────────────────────────────────────
            os.replace(temp_path, file_path)
            logger.debug(f"[JSON_UTILS] Successfully wrote JSON to {file_path}")
            return True
            
        except Exception as e:
            # Clean up temp file if it exists
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
            raise
    
    except Exception as e:
        logger.error(
            f"[JSON_UTILS] Failed to write JSON to {file_path}: {str(e)}"
        )
        return False


__all__ = [
    'safe_json_load',
    'safe_json_load_list',
    'safe_json_write',
]
