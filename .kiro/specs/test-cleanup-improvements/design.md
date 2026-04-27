# Test Cleanup Improvements Design

## Overview

This design addresses Windows-specific file permission issues in our test suite by implementing robust cleanup mechanisms, proper resource management, and cross-platform compatibility improvements.

## Architecture

### Core Components

1. **Robust Cleanup Utilities**
   - Retry-based directory removal
   - Platform-specific file handling
   - Graceful error handling

2. **TensorBoard Resource Manager**
   - Context manager for TensorBoard writers
   - Automatic resource cleanup
   - Error-tolerant closing

3. **Enhanced Test Fixtures**
   - Improved temporary directory management
   - Resource tracking and cleanup
   - Cross-platform compatibility

4. **Cleanup Helpers**
   - Utility functions for safe file operations
   - Logging and error reporting
   - Timeout-based operations

## Components and Interfaces

### 1. Cleanup Utilities Module

```python
# test_utils/cleanup.py

import os
import shutil
import time
import logging
from pathlib import Path
from typing import Optional, Callable
from contextlib import contextmanager

def safe_rmtree(path: str, max_retries: int = 3, delay: float = 0.1) -> bool:
    """Safely remove directory tree with retries for Windows file locking."""
    
def force_close_handles(path: str) -> None:
    """Force close file handles on Windows (if possible)."""
    
def wait_for_file_release(filepath: str, timeout: float = 5.0) -> bool:
    """Wait for file to be released by other processes."""

@contextmanager
def temporary_directory(cleanup_retries: int = 3):
    """Context manager for temporary directories with robust cleanup."""
```

### 2. TensorBoard Resource Manager

```python
# test_utils/tensorboard_manager.py

from contextlib import contextmanager
from typing import Optional
import logging

@contextmanager
def managed_tensorboard_writer(log_dir: str):
    """Context manager for TensorBoard writers with guaranteed cleanup."""
    
class TensorBoardTestCallback:
    """Test-friendly TensorBoard callback with proper resource management."""
    
    def __enter__(self):
        """Enter context manager."""
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context manager with cleanup."""
```

### 3. Enhanced Test Fixtures

```python
# Improved test fixtures in test_agent_trainer.py

@pytest.fixture
def safe_temp_dir():
    """Create temporary directory with robust cleanup."""
    
@pytest.fixture
def tensorboard_callback_manager():
    """Managed TensorBoard callback for testing."""
    
@pytest.fixture
def agent_trainer_with_cleanup():
    """Agent trainer with proper resource management."""
```

### 4. Platform Detection and Handling

```python
# test_utils/platform_utils.py

import platform
import sys

def is_windows() -> bool:
    """Check if running on Windows."""
    
def get_cleanup_strategy() -> str:
    """Get appropriate cleanup strategy for current platform."""
    
def handle_permission_error(error: PermissionError, path: str) -> None:
    """Handle permission errors in a platform-appropriate way."""
```

## Data Models

### Cleanup Configuration

```python
@dataclass
class CleanupConfig:
    """Configuration for cleanup operations."""
    max_retries: int = 3
    retry_delay: float = 0.1
    timeout: float = 5.0
    force_cleanup: bool = True
    log_failures: bool = True
```

### Resource Tracker

```python
@dataclass
class ResourceTracker:
    """Track resources for cleanup."""
    temp_dirs: List[Path]
    tensorboard_writers: List[Any]
    open_files: List[Any]
    cleanup_callbacks: List[Callable]
```

## Error Handling

### 1. Permission Error Handling

- Catch `PermissionError` and `OSError` during cleanup
- Log warnings instead of failing tests
- Implement retry logic with exponential backoff
- Use platform-specific cleanup strategies

### 2. Resource Leak Prevention

- Track all created resources
- Ensure cleanup in finally blocks
- Use context managers where possible
- Implement timeout-based cleanup

### 3. Graceful Degradation

- Continue test execution even if cleanup fails
- Provide detailed logging for debugging
- Offer manual cleanup utilities
- Document known limitations

## Testing Strategy

### 1. Unit Tests for Cleanup Utilities

- Test retry logic with simulated file locks
- Verify cross-platform compatibility
- Test timeout handling
- Validate error logging

### 2. Integration Tests

- Test with actual TensorBoard writers
- Verify cleanup in various scenarios
- Test resource tracking
- Validate cross-platform behavior

### 3. Stress Tests

- Test with many temporary files
- Simulate file locking scenarios
- Test cleanup under load
- Verify memory usage

## Implementation Plan

### Phase 1: Core Cleanup Utilities
- Implement safe_rmtree with retry logic
- Add platform detection utilities
- Create basic resource tracking

### Phase 2: TensorBoard Management
- Implement TensorBoard context manager
- Update callback classes
- Add resource cleanup hooks

### Phase 3: Test Fixture Updates
- Update existing test fixtures
- Add new managed fixtures
- Implement resource tracking

### Phase 4: Integration and Testing
- Update all affected tests
- Add comprehensive test coverage
- Validate cross-platform behavior

## Cross-Platform Considerations

### Windows-Specific Issues
- File locking by antivirus software
- Process handle inheritance
- Path length limitations
- Permission model differences

### Unix-Specific Considerations
- Signal handling
- File descriptor limits
- Permission inheritance
- Symbolic link handling

### Common Solutions
- Use pathlib for path operations
- Implement timeout-based operations
- Provide platform-specific fallbacks
- Use appropriate file modes