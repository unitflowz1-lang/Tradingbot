"""
TensorBoard resource management utilities for testing.
"""

import logging
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, Any

from .cleanup import cleanup_tensorboard_logs, ensure_directory_writable

logger = logging.getLogger(__name__)


@contextmanager
def managed_tensorboard_writer(log_dir: Optional[str] = None):
    """
    Context manager for TensorBoard writers with guaranteed cleanup.
    
    Args:
        log_dir: Directory for TensorBoard logs. If None, creates temporary directory.
        
    Yields:
        TensorBoard SummaryWriter instance or None if import fails
    """
    writer = None
    temp_dir_created = False
    
    try:
        # Import TensorBoard
        try:
            from torch.utils.tensorboard import SummaryWriter
        except ImportError:
            try:
                from tensorboard import SummaryWriter
            except ImportError:
                logger.warning("TensorBoard not available for testing")
                yield None
                return
        
        # Create log directory if needed
        if log_dir is None:
            log_dir = tempfile.mkdtemp(prefix='tensorboard_test_')
            temp_dir_created = True
        else:
            ensure_directory_writable(log_dir)
        
        # Create writer
        writer = SummaryWriter(log_dir=log_dir)
        yield writer
        
    except Exception as e:
        logger.warning(f"Error creating TensorBoard writer: {e}")
        yield None
        
    finally:
        # Clean up writer
        if writer is not None:
            try:
                writer.close()
            except Exception as e:
                logger.warning(f"Error closing TensorBoard writer: {e}")
        
        # Clean up temporary directory
        if temp_dir_created and log_dir:
            success = cleanup_tensorboard_logs(log_dir)
            if not success:
                logger.warning(f"Could not clean up TensorBoard logs: {log_dir}")


class TensorBoardTestCallback:
    """
    Test-friendly TensorBoard callback with proper resource management.
    
    This is a drop-in replacement for the regular TensorBoardCallback
    that ensures proper cleanup in test environments.
    """
    
    def __init__(self, log_dir: str):
        """
        Initialize TensorBoard test callback.
        
        Args:
            log_dir: Directory for TensorBoard logs
        """
        self.log_dir = Path(log_dir)
        self.writer = None
        self._context_manager = None
        
    def __enter__(self):
        """Enter context manager."""
        self._context_manager = managed_tensorboard_writer(str(self.log_dir))
        self.writer = self._context_manager.__enter__()
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context manager with cleanup."""
        if self._context_manager:
            self._context_manager.__exit__(exc_type, exc_val, exc_tb)
        self.writer = None
        
    def on_training_start(self, trainer) -> None:
        """Initialize TensorBoard logging."""
        if self.writer:
            try:
                # Log training configuration if available
                if hasattr(trainer, 'config'):
                    config_text = str(trainer.config)
                    self.writer.add_text("config", config_text, 0)
            except Exception as e:
                logger.warning(f"Error logging training start: {e}")
                
    def on_training_end(self, trainer) -> None:
        """Log training completion."""
        if self.writer:
            try:
                self.writer.add_text("status", "Training completed", 0)
            except Exception as e:
                logger.warning(f"Error logging training end: {e}")
                
    def on_episode_start(self, trainer, episode: int) -> None:
        """Log episode start."""
        pass  # Usually no logging needed at episode start
        
    def on_episode_end(self, trainer, episode: int, metrics) -> None:
        """Log episode metrics."""
        if not self.writer:
            return
            
        try:
            # Log basic metrics
            if hasattr(metrics, 'total_reward'):
                self.writer.add_scalar("reward/total", metrics.total_reward, episode)
            if hasattr(metrics, 'average_reward'):
                self.writer.add_scalar("reward/average", metrics.average_reward, episode)
            if hasattr(metrics, 'episode_length'):
                self.writer.add_scalar("episode/length", metrics.episode_length, episode)
            if hasattr(metrics, 'episode_time'):
                self.writer.add_scalar("episode/time", metrics.episode_time, episode)
            if hasattr(metrics, 'loss') and metrics.loss is not None:
                self.writer.add_scalar("training/loss", metrics.loss, episode)
                
        except Exception as e:
            logger.warning(f"Error logging episode metrics: {e}")
            
    def on_evaluation_start(self, trainer, episode: int) -> None:
        """Log evaluation start."""
        if self.writer:
            try:
                self.writer.add_text("evaluation", f"Starting evaluation at episode {episode}", episode)
            except Exception as e:
                logger.warning(f"Error logging evaluation start: {e}")
                
    def on_evaluation_end(self, trainer, episode: int, results: dict) -> None:
        """Log evaluation results."""
        if not self.writer:
            return
            
        try:
            for key, value in results.items():
                if isinstance(value, (int, float)):
                    self.writer.add_scalar(f"evaluation/{key}", value, episode)
        except Exception as e:
            logger.warning(f"Error logging evaluation results: {e}")


@contextmanager
def tensorboard_callback_for_testing(log_dir: Optional[str] = None):
    """
    Context manager that provides a TensorBoard callback for testing.
    
    Args:
        log_dir: Directory for TensorBoard logs
        
    Yields:
        TensorBoardTestCallback instance
    """
    if log_dir is None:
        log_dir = tempfile.mkdtemp(prefix='tensorboard_callback_test_')
        
    callback = TensorBoardTestCallback(log_dir)
    
    try:
        with callback:
            yield callback
    except Exception as e:
        logger.warning(f"Error in TensorBoard callback context: {e}")
        yield callback  # Still yield callback even if setup failed