"""
Strategy Registry for RL System

This module contains the StrategyRegistry class for managing
multiple trained RL strategies with versioning and metadata.
"""

import json
import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime
import logging

from .models import (
    RLStrategy, StrategyMetadata, PerformanceMetrics,
    StrategyStatus, AgentType, generate_strategy_id
)


logger = logging.getLogger(__name__)


class StrategyValidationError(Exception):
    """Exception raised when strategy validation fails."""
    pass


class StrategyRegistry:
    """
    Central registry for all trained RL strategies.
    
    Manages strategy storage, versioning, metadata, and validation
    with support for deployment approval workflows.
    """
    
    def __init__(self, registry_path: str = "data/rl_strategies"):
        """
        Initialize strategy registry.
        
        Args:
            registry_path: Path to store strategy files and metadata
        """
        self.registry_path = Path(registry_path)
        self.registry_path.mkdir(parents=True, exist_ok=True)
        
        # Create subdirectories
        self.models_path = self.registry_path / "models"
        self.metadata_path = self.registry_path / "metadata"
        self.configs_path = self.registry_path / "configs"
        
        for path in [self.models_path, self.metadata_path, self.configs_path]:
            path.mkdir(exist_ok=True)
        
        # In-memory cache for fast access
        self._strategies: Dict[str, RLStrategy] = {}
        self._load_all_strategies()
        
        # Validation rules
        self._validation_rules: List[Callable[[RLStrategy], bool]] = []
        self._setup_default_validation_rules()
    
    def register_strategy(
        self,
        strategy: RLStrategy,
        model_file_path: Optional[str] = None,
        config_file_path: Optional[str] = None,
        overwrite: bool = False
    ) -> str:
        """
        Register a new strategy in the registry.
        
        Args:
            strategy: RLStrategy instance to register
            model_file_path: Path to model file to copy to registry
            config_file_path: Path to config file to copy to registry
            overwrite: Whether to overwrite existing strategy
            
        Returns:
            Strategy ID of registered strategy
            
        Raises:
            StrategyValidationError: If strategy validation fails
            ValueError: If strategy already exists and overwrite=False
        """
        strategy_id = strategy.strategy_id
        
        # Check if strategy already exists
        if strategy_id in self._strategies and not overwrite:
            raise ValueError(f"Strategy {strategy_id} already exists. Use overwrite=True to replace.")
        
        # Validate strategy
        self._validate_strategy(strategy)
        
        try:
            # Copy model file if provided
            if model_file_path and os.path.exists(model_file_path):
                model_filename = f"{strategy_id}_model.pkl"
                model_dest = self.models_path / model_filename
                shutil.copy2(model_file_path, model_dest)
                strategy.metadata.model_path = str(model_dest)
            
            # Copy config file if provided
            if config_file_path and os.path.exists(config_file_path):
                config_filename = f"{strategy_id}_config.json"
                config_dest = self.configs_path / config_filename
                shutil.copy2(config_file_path, config_dest)
                strategy.metadata.config_path = str(config_dest)
            
            # Save metadata
            self._save_strategy_metadata(strategy)
            
            # Add to cache
            self._strategies[strategy_id] = strategy
            
            logger.info(f"Successfully registered strategy: {strategy_id}")
            return strategy_id
            
        except Exception as e:
            logger.error(f"Failed to register strategy {strategy_id}: {e}")
            # Cleanup on failure
            self._cleanup_strategy_files(strategy_id)
            raise
    
    def get_strategy(self, strategy_id: str) -> Optional[RLStrategy]:
        """
        Retrieve strategy by ID.
        
        Args:
            strategy_id: Unique strategy identifier
            
        Returns:
            RLStrategy instance or None if not found
        """
        return self._strategies.get(strategy_id)
    
    def list_strategies(
        self,
        status: Optional[StrategyStatus] = None,
        agent_type: Optional[AgentType] = None,
        currency_pairs: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        created_by: Optional[str] = None,
        limit: Optional[int] = None
    ) -> List[StrategyMetadata]:
        """
        List strategies with optional filtering.
        
        Args:
            status: Filter by strategy status
            agent_type: Filter by agent type
            currency_pairs: Filter by currency pairs (any match)
            tags: Filter by tags (any match)
            created_by: Filter by creator
            limit: Maximum number of results
            
        Returns:
            List of strategy metadata matching filters
        """
        strategies = list(self._strategies.values())
        
        # Apply filters
        if status:
            strategies = [s for s in strategies if s.metadata.status == status]
        
        if agent_type:
            strategies = [s for s in strategies if s.metadata.agent_type == agent_type]
        
        if currency_pairs:
            strategies = [
                s for s in strategies
                if any(pair in s.metadata.currency_pairs for pair in currency_pairs)
            ]
        
        if tags:
            strategies = [
                s for s in strategies
                if any(tag in s.metadata.tags for tag in tags)
            ]
        
        if created_by:
            strategies = [s for s in strategies if s.metadata.created_by == created_by]
        
        # Sort by updated_at (most recent first)
        strategies.sort(key=lambda s: s.metadata.updated_at, reverse=True)
        
        # Apply limit
        if limit:
            strategies = strategies[:limit]
        
        return [s.metadata for s in strategies]
    
    def update_strategy_status(
        self,
        strategy_id: str,
        new_status: StrategyStatus,
        updated_by: str,
        notes: Optional[str] = None
    ) -> bool:
        """
        Update strategy status.
        
        Args:
            strategy_id: Strategy to update
            new_status: New status to set
            updated_by: User making the update
            notes: Optional notes about the status change
            
        Returns:
            True if update successful, False if strategy not found
        """
        strategy = self._strategies.get(strategy_id)
        if not strategy:
            return False
        
        old_status = strategy.metadata.status
        strategy.update_status(new_status, updated_by)
        
        # Add notes to deployment history if provided
        if notes:
            strategy.deployment_history[-1]['notes'] = notes
        
        # Save updated metadata
        self._save_strategy_metadata(strategy)
        
        logger.info(f"Updated strategy {strategy_id} status: {old_status.value} -> {new_status.value}")
        return True
    
    def update_performance(
        self,
        strategy_id: str,
        performance_metrics: PerformanceMetrics
    ) -> bool:
        """
        Update strategy performance metrics.
        
        Args:
            strategy_id: Strategy to update
            performance_metrics: New performance metrics
            
        Returns:
            True if update successful, False if strategy not found
        """
        strategy = self._strategies.get(strategy_id)
        if not strategy:
            return False
        
        strategy.update_performance(performance_metrics)
        self._save_strategy_metadata(strategy)
        
        logger.info(f"Updated performance metrics for strategy {strategy_id}")
        return True
    
    def delete_strategy(self, strategy_id: str) -> bool:
        """
        Delete strategy from registry.
        
        Args:
            strategy_id: Strategy to delete
            
        Returns:
            True if deletion successful, False if strategy not found
        """
        if strategy_id not in self._strategies:
            return False
        
        # Remove from cache
        del self._strategies[strategy_id]
        
        # Remove files
        self._cleanup_strategy_files(strategy_id)
        
        logger.info(f"Deleted strategy: {strategy_id}")
        return True
    
    def get_deployable_strategies(self) -> List[RLStrategy]:
        """
        Get all strategies ready for deployment.
        
        Returns:
            List of strategies with APPROVED status and valid model paths
        """
        return [
            strategy for strategy in self._strategies.values()
            if strategy.is_deployable()
        ]
    
    def get_performance_leaderboard(
        self,
        metric: str = "sharpe_ratio",
        limit: int = 10,
        agent_type: Optional[AgentType] = None
    ) -> List[Dict[str, Any]]:
        """
        Get performance leaderboard for strategies.
        
        Args:
            metric: Performance metric to rank by
            limit: Maximum number of results
            agent_type: Filter by agent type
            
        Returns:
            List of strategy performance data sorted by metric
        """
        strategies = list(self._strategies.values())
        
        # Filter by agent type if specified
        if agent_type:
            strategies = [s for s in strategies if s.metadata.agent_type == agent_type]
        
        # Filter strategies with performance metrics
        strategies_with_metrics = [
            s for s in strategies
            if s.performance_metrics and hasattr(s.performance_metrics, metric)
        ]
        
        # Sort by metric (descending)
        strategies_with_metrics.sort(
            key=lambda s: getattr(s.performance_metrics, metric),
            reverse=True
        )
        
        # Build leaderboard
        leaderboard = []
        for i, strategy in enumerate(strategies_with_metrics[:limit]):
            leaderboard.append({
                'rank': i + 1,
                'strategy_id': strategy.strategy_id,
                'name': strategy.name,
                'agent_type': strategy.metadata.agent_type.value,
                'version': strategy.version,
                'metric_value': getattr(strategy.performance_metrics, metric),
                'total_return': strategy.performance_metrics.total_return,
                'sharpe_ratio': strategy.performance_metrics.sharpe_ratio,
                'max_drawdown': strategy.performance_metrics.max_drawdown,
                'updated_at': strategy.metadata.updated_at.isoformat()
            })
        
        return leaderboard
    
    def add_validation_rule(self, rule: Callable[[RLStrategy], bool]) -> None:
        """
        Add custom validation rule.
        
        Args:
            rule: Function that takes RLStrategy and returns True if valid
        """
        self._validation_rules.append(rule)
    
    def validate_strategy(self, strategy: RLStrategy) -> bool:
        """
        Validate strategy against all rules.
        
        Args:
            strategy: Strategy to validate
            
        Returns:
            True if all validation rules pass
            
        Raises:
            StrategyValidationError: If validation fails
        """
        return self._validate_strategy(strategy)
    
    def export_registry(self, export_path: str) -> None:
        """
        Export entire registry to file.
        
        Args:
            export_path: Path to export file
        """
        export_data = {
            'export_timestamp': datetime.now().isoformat(),
            'strategies': {
                strategy_id: strategy.to_dict()
                for strategy_id, strategy in self._strategies.items()
            }
        }
        
        with open(export_path, 'w') as f:
            json.dump(export_data, f, indent=2)
        
        logger.info(f"Exported registry to {export_path}")
    
    def import_registry(self, import_path: str, overwrite: bool = False) -> int:
        """
        Import strategies from file.
        
        Args:
            import_path: Path to import file
            overwrite: Whether to overwrite existing strategies
            
        Returns:
            Number of strategies imported
        """
        with open(import_path, 'r') as f:
            import_data = json.load(f)
        
        imported_count = 0
        for strategy_data in import_data.get('strategies', {}).values():
            try:
                strategy = RLStrategy.from_dict(strategy_data)
                self.register_strategy(strategy, overwrite=overwrite)
                imported_count += 1
            except Exception as e:
                logger.warning(f"Failed to import strategy {strategy_data.get('metadata', {}).get('strategy_id')}: {e}")
        
        logger.info(f"Imported {imported_count} strategies from {import_path}")
        return imported_count
    
    def _load_all_strategies(self) -> None:
        """Load all strategies from disk into memory."""
        if not self.metadata_path.exists():
            return
        
        for metadata_file in self.metadata_path.glob("*.json"):
            try:
                with open(metadata_file, 'r') as f:
                    strategy_data = json.load(f)
                
                strategy = RLStrategy.from_dict(strategy_data)
                self._strategies[strategy.strategy_id] = strategy
                
            except Exception as e:
                logger.warning(f"Failed to load strategy from {metadata_file}: {e}")
    
    def _save_strategy_metadata(self, strategy: RLStrategy) -> None:
        """Save strategy metadata to disk."""
        metadata_file = self.metadata_path / f"{strategy.strategy_id}.json"
        
        with open(metadata_file, 'w') as f:
            json.dump(strategy.to_dict(), f, indent=2)
    
    def _cleanup_strategy_files(self, strategy_id: str) -> None:
        """Remove all files associated with a strategy."""
        # Remove metadata file
        metadata_file = self.metadata_path / f"{strategy_id}.json"
        if metadata_file.exists():
            metadata_file.unlink()
        
        # Remove model file
        model_file = self.models_path / f"{strategy_id}_model.pkl"
        if model_file.exists():
            model_file.unlink()
        
        # Remove config file
        config_file = self.configs_path / f"{strategy_id}_config.json"
        if config_file.exists():
            config_file.unlink()
    
    def _validate_strategy(self, strategy: RLStrategy) -> bool:
        """
        Validate strategy against all rules.
        
        Args:
            strategy: Strategy to validate
            
        Returns:
            True if all validation rules pass
            
        Raises:
            StrategyValidationError: If validation fails
        """
        for rule in self._validation_rules:
            try:
                if not rule(strategy):
                    raise StrategyValidationError(f"Strategy validation failed: {rule.__name__}")
            except Exception as e:
                raise StrategyValidationError(f"Validation rule {rule.__name__} failed: {e}")
        
        return True
    
    def _setup_default_validation_rules(self) -> None:
        """Setup default validation rules."""
        
        def validate_metadata(strategy: RLStrategy) -> bool:
            """Validate strategy metadata."""
            metadata = strategy.metadata
            return (
                bool(metadata.strategy_id) and
                bool(metadata.name) and
                bool(metadata.description) and
                bool(metadata.created_by) and
                isinstance(metadata.agent_type, AgentType) and
                isinstance(metadata.status, StrategyStatus)
            )
        
        def validate_performance_metrics(strategy: RLStrategy) -> bool:
            """Validate performance metrics if present."""
            if strategy.performance_metrics is None:
                return True  # Optional for training strategies
            
            metrics = strategy.performance_metrics
            return (
                -1.0 <= metrics.win_rate <= 1.0 and
                metrics.num_trades >= 0 and
                metrics.avg_trade_duration >= 0
            )
        
        def validate_model_path(strategy: RLStrategy) -> bool:
            """Validate model path for deployed strategies."""
            if strategy.metadata.status == StrategyStatus.DEPLOYED:
                return strategy.metadata.model_path is not None
            return True
        
        self._validation_rules.extend([
            validate_metadata,
            validate_performance_metrics,
            validate_model_path
        ])