"""
Strategy update mechanism for hot-swapping trading strategies without stopping the system
"""

import asyncio
import json
import logging
import importlib
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, Callable, List
from dataclasses import dataclass, asdict
from enum import Enum
import threading


class UpdateStatus(Enum):
    """Status of strategy update"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


@dataclass
class StrategyUpdate:
    """Information about a strategy update"""
    update_id: str
    strategy_name: str
    version: str
    timestamp: datetime
    status: UpdateStatus
    description: str
    rollback_version: Optional[str] = None
    error_message: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class StrategyUpdater:
    """Manages hot updates of trading strategies"""
    
    def __init__(self, strategies_dir: str = "src/strategies"):
        self.strategies_dir = Path(strategies_dir)
        self.strategies_dir.mkdir(exist_ok=True)
        self.logger = logging.getLogger(__name__)
        
        # Active strategies and their instances
        self.active_strategies: Dict[str, Any] = {}
        self.strategy_versions: Dict[str, str] = {}
        self.update_history: List[StrategyUpdate] = []
        
        # Update callbacks
        self.update_callbacks: List[Callable[[str, Any], None]] = []
        
        # Thread safety
        self._update_lock = threading.RLock()
        
        # Load update history
        self._load_update_history()
    
    def _load_update_history(self):
        """Load update history from file"""
        history_file = self.strategies_dir / "update_history.json"
        if history_file.exists():
            try:
                with open(history_file, 'r') as f:
                    data = json.load(f)
                    self.update_history = [
                        StrategyUpdate(
                            update_id=item['update_id'],
                            strategy_name=item['strategy_name'],
                            version=item['version'],
                            timestamp=datetime.fromisoformat(item['timestamp']),
                            status=UpdateStatus(item['status']),
                            description=item['description'],
                            rollback_version=item.get('rollback_version'),
                            error_message=item.get('error_message'),
                            metadata=item.get('metadata')
                        )
                        for item in data
                    ]
            except Exception as e:
                self.logger.error(f"Failed to load update history: {e}")
    
    def _save_update_history(self):
        """Save update history to file"""
        history_file = self.strategies_dir / "update_history.json"
        try:
            data = []
            for update in self.update_history:
                item = asdict(update)
                item['status'] = update.status.value
                item['timestamp'] = update.timestamp.isoformat()
                data.append(item)
            
            with open(history_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            self.logger.error(f"Failed to save update history: {e}")
    
    def register_strategy(self, name: str, strategy_instance: Any, version: str = "1.0.0"):
        """Register a strategy for hot updates"""
        with self._update_lock:
            self.active_strategies[name] = strategy_instance
            self.strategy_versions[name] = version
            self.logger.info(f"Registered strategy '{name}' version {version}")
    
    def unregister_strategy(self, name: str):
        """Unregister a strategy"""
        with self._update_lock:
            if name in self.active_strategies:
                del self.active_strategies[name]
                del self.strategy_versions[name]
                self.logger.info(f"Unregistered strategy '{name}'")
    
    def add_update_callback(self, callback: Callable[[str, Any], None]):
        """Add callback to be called when strategy is updated"""
        self.update_callbacks.append(callback)
    
    def remove_update_callback(self, callback: Callable[[str, Any], None]):
        """Remove update callback"""
        if callback in self.update_callbacks:
            self.update_callbacks.remove(callback)
    
    async def update_strategy(self, strategy_name: str, strategy_file: str, 
                            version: str, description: str = "") -> StrategyUpdate:
        """Update a strategy with hot-swapping"""
        update_id = f"{strategy_name}_{version}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        update_info = StrategyUpdate(
            update_id=update_id,
            strategy_name=strategy_name,
            version=version,
            timestamp=datetime.now(),
            status=UpdateStatus.PENDING,
            description=description,
            rollback_version=self.strategy_versions.get(strategy_name)
        )
        
        self.update_history.append(update_info)
        self._save_update_history()
        
        try:
            await self._perform_strategy_update(update_info, strategy_file)
            return update_info
        except Exception as e:
            update_info.status = UpdateStatus.FAILED
            update_info.error_message = str(e)
            self._save_update_history()
            self.logger.error(f"Strategy update failed: {e}")
            raise
    
    async def _perform_strategy_update(self, update_info: StrategyUpdate, strategy_file: str):
        """Perform the actual strategy update"""
        strategy_name = update_info.strategy_name
        
        with self._update_lock:
            update_info.status = UpdateStatus.IN_PROGRESS
            self._save_update_history()
            
            self.logger.info(f"Starting strategy update: {strategy_name} -> {update_info.version}")
            
            # Backup current strategy if it exists
            old_strategy = None
            if strategy_name in self.active_strategies:
                old_strategy = self.active_strategies[strategy_name]
                self.logger.info(f"Backing up current strategy: {strategy_name}")
            
            try:
                # Load new strategy module
                new_strategy = await self._load_strategy_module(strategy_file, strategy_name)
                
                # Validate new strategy
                await self._validate_strategy(new_strategy, strategy_name)
                
                # Perform hot swap
                await self._hot_swap_strategy(strategy_name, new_strategy, old_strategy)
                
                # Update version tracking
                self.strategy_versions[strategy_name] = update_info.version
                
                # Notify callbacks
                for callback in self.update_callbacks:
                    try:
                        callback(strategy_name, new_strategy)
                    except Exception as e:
                        self.logger.error(f"Error in update callback: {e}")
                
                update_info.status = UpdateStatus.COMPLETED
                self.logger.info(f"Strategy update completed: {strategy_name} -> {update_info.version}")
                
            except Exception as e:
                # Rollback on failure
                if old_strategy:
                    try:
                        await self._hot_swap_strategy(strategy_name, old_strategy, None)
                        self.logger.info(f"Rolled back strategy: {strategy_name}")
                        update_info.status = UpdateStatus.ROLLED_BACK
                    except Exception as rollback_error:
                        self.logger.error(f"Rollback failed: {rollback_error}")
                        update_info.status = UpdateStatus.FAILED
                else:
                    update_info.status = UpdateStatus.FAILED
                
                update_info.error_message = str(e)
                raise
            
            finally:
                self._save_update_history()
    
    async def _load_strategy_module(self, strategy_file: str, strategy_name: str) -> Any:
        """Load strategy module from file"""
        strategy_path = Path(strategy_file)
        if not strategy_path.exists():
            raise FileNotFoundError(f"Strategy file not found: {strategy_file}")
        
        # Copy strategy file to strategies directory
        target_file = self.strategies_dir / f"{strategy_name}.py"
        target_file.parent.mkdir(exist_ok=True)
        
        import shutil
        shutil.copy2(strategy_path, target_file)
        
        # Import the module
        spec = importlib.util.spec_from_file_location(strategy_name, target_file)
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not load strategy module: {strategy_file}")
        
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        # Get strategy class (assume it's named after the strategy)
        strategy_class_name = ''.join(word.capitalize() for word in strategy_name.split('_'))
        if not hasattr(module, strategy_class_name):
            # Try common naming patterns
            for name in [strategy_class_name, f"{strategy_class_name}Strategy", "Strategy"]:
                if hasattr(module, name):
                    strategy_class_name = name
                    break
            else:
                raise AttributeError(f"Strategy class not found in module: {strategy_file}")
        
        strategy_class = getattr(module, strategy_class_name)
        return strategy_class()
    
    async def _validate_strategy(self, strategy: Any, strategy_name: str):
        """Validate that the strategy has required methods"""
        required_methods = ['generate_signal', 'update_parameters']
        
        for method in required_methods:
            if not hasattr(strategy, method):
                raise AttributeError(f"Strategy {strategy_name} missing required method: {method}")
            
            if not callable(getattr(strategy, method)):
                raise TypeError(f"Strategy {strategy_name} method {method} is not callable")
        
        # Test basic functionality
        try:
            # This would test the strategy with sample data
            self.logger.info(f"Strategy validation passed: {strategy_name}")
        except Exception as e:
            raise ValueError(f"Strategy validation failed: {e}")
    
    async def _hot_swap_strategy(self, strategy_name: str, new_strategy: Any, old_strategy: Any):
        """Perform hot swap of strategy"""
        # Pause strategy execution temporarily
        if old_strategy and hasattr(old_strategy, 'pause'):
            await old_strategy.pause()
        
        # Transfer state if possible
        if old_strategy and hasattr(old_strategy, 'get_state') and hasattr(new_strategy, 'set_state'):
            try:
                state = old_strategy.get_state()
                new_strategy.set_state(state)
                self.logger.info(f"Transferred state for strategy: {strategy_name}")
            except Exception as e:
                self.logger.warning(f"Could not transfer state for {strategy_name}: {e}")
        
        # Replace strategy
        self.active_strategies[strategy_name] = new_strategy
        
        # Resume execution
        if hasattr(new_strategy, 'resume'):
            await new_strategy.resume()
        
        self.logger.info(f"Hot swap completed for strategy: {strategy_name}")
    
    async def rollback_strategy(self, update_id: str) -> bool:
        """Rollback a strategy update"""
        update_info = self.get_update_info(update_id)
        if not update_info:
            self.logger.error(f"Update not found: {update_id}")
            return False
        
        if not update_info.rollback_version:
            self.logger.error(f"No rollback version available for update: {update_id}")
            return False
        
        try:
            # Find the rollback strategy file
            rollback_file = self.strategies_dir / f"{update_info.strategy_name}_v{update_info.rollback_version}.py"
            if not rollback_file.exists():
                self.logger.error(f"Rollback file not found: {rollback_file}")
                return False
            
            # Perform rollback update
            rollback_update = await self.update_strategy(
                strategy_name=update_info.strategy_name,
                strategy_file=str(rollback_file),
                version=update_info.rollback_version,
                description=f"Rollback from {update_info.version}"
            )
            
            # Mark original update as rolled back
            update_info.status = UpdateStatus.ROLLED_BACK
            self._save_update_history()
            
            self.logger.info(f"Strategy rollback completed: {update_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"Strategy rollback failed: {e}")
            return False
    
    def get_update_info(self, update_id: str) -> Optional[StrategyUpdate]:
        """Get information about a specific update"""
        for update in self.update_history:
            if update.update_id == update_id:
                return update
        return None
    
    def list_updates(self, strategy_name: Optional[str] = None) -> List[StrategyUpdate]:
        """List strategy updates"""
        if strategy_name:
            return [u for u in self.update_history if u.strategy_name == strategy_name]
        return self.update_history.copy()
    
    def get_active_strategies(self) -> Dict[str, str]:
        """Get list of active strategies and their versions"""
        return self.strategy_versions.copy()
    
    def get_strategy_instance(self, strategy_name: str) -> Optional[Any]:
        """Get active strategy instance"""
        return self.active_strategies.get(strategy_name)
    
    async def update_strategy_parameters(self, strategy_name: str, parameters: Dict[str, Any]) -> bool:
        """Update strategy parameters without full reload"""
        if strategy_name not in self.active_strategies:
            self.logger.error(f"Strategy not found: {strategy_name}")
            return False
        
        try:
            strategy = self.active_strategies[strategy_name]
            if hasattr(strategy, 'update_parameters'):
                await strategy.update_parameters(parameters)
                self.logger.info(f"Updated parameters for strategy: {strategy_name}")
                return True
            else:
                self.logger.error(f"Strategy {strategy_name} does not support parameter updates")
                return False
        except Exception as e:
            self.logger.error(f"Failed to update parameters for {strategy_name}: {e}")
            return False
    
    def get_update_statistics(self) -> Dict[str, Any]:
        """Get update statistics"""
        stats = {
            "total_updates": len(self.update_history),
            "successful_updates": len([u for u in self.update_history if u.status == UpdateStatus.COMPLETED]),
            "failed_updates": len([u for u in self.update_history if u.status == UpdateStatus.FAILED]),
            "rollbacks": len([u for u in self.update_history if u.status == UpdateStatus.ROLLED_BACK]),
            "active_strategies": len(self.active_strategies),
            "by_strategy": {}
        }
        
        # Statistics by strategy
        for strategy_name in set(u.strategy_name for u in self.update_history):
            strategy_updates = [u for u in self.update_history if u.strategy_name == strategy_name]
            stats["by_strategy"][strategy_name] = {
                "total_updates": len(strategy_updates),
                "current_version": self.strategy_versions.get(strategy_name, "unknown"),
                "last_update": max(u.timestamp for u in strategy_updates).isoformat() if strategy_updates else None
            }
        
        return stats


# Global strategy updater instance
_strategy_updater: Optional[StrategyUpdater] = None


def get_strategy_updater(strategies_dir: str = "src/strategies") -> StrategyUpdater:
    """Get global strategy updater instance"""
    global _strategy_updater
    if _strategy_updater is None:
        _strategy_updater = StrategyUpdater(strategies_dir)
    return _strategy_updater