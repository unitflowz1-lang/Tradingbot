"""
Unit tests for RL Strategy Registry system.

Tests strategy registration, versioning, metadata management,
and validation workflows.
"""

import pytest
import tempfile
import shutil
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.rl.strategies.registry import StrategyRegistry, StrategyValidationError
from src.rl.strategies.models import (
    RLStrategy, StrategyMetadata, PerformanceMetrics,
    StrategyStatus, AgentType, create_strategy_metadata
)


class TestStrategyRegistry:
    """Test cases for StrategyRegistry class."""
    
    @pytest.fixture
    def temp_registry_path(self):
        """Create temporary directory for registry."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)
    
    @pytest.fixture
    def registry(self, temp_registry_path):
        """Create StrategyRegistry instance."""
        return StrategyRegistry(temp_registry_path)
    
    @pytest.fixture
    def sample_metadata(self):
        """Create sample strategy metadata."""
        return create_strategy_metadata(
            name="Test DQN Strategy",
            description="Test strategy for unit testing",
            agent_type=AgentType.DQN,
            created_by="test_user",
            tags=["test", "dqn"],
            currency_pairs=["EUR/USD", "GBP/USD"]
        )
    
    @pytest.fixture
    def sample_performance(self):
        """Create sample performance metrics."""
        return PerformanceMetrics(
            total_return=0.15,
            sharpe_ratio=1.2,
            max_drawdown=0.08,
            win_rate=0.65,
            profit_factor=1.8,
            calmar_ratio=1.5,
            sortino_ratio=1.4,
            num_trades=100,
            avg_trade_duration=2.5,
            volatility=0.12
        )
    
    @pytest.fixture
    def sample_strategy(self, sample_metadata, sample_performance):
        """Create sample RLStrategy."""
        return RLStrategy(
            metadata=sample_metadata,
            performance_metrics=sample_performance,
            config={"learning_rate": 0.001, "batch_size": 32}
        )
    
    def test_registry_initialization(self, temp_registry_path):
        """Test registry initialization creates required directories."""
        registry = StrategyRegistry(temp_registry_path)
        
        assert registry.registry_path.exists()
        assert registry.models_path.exists()
        assert registry.metadata_path.exists()
        assert registry.configs_path.exists()
        assert isinstance(registry._strategies, dict)
    
    def test_register_strategy_success(self, registry, sample_strategy):
        """Test successful strategy registration."""
        strategy_id = registry.register_strategy(sample_strategy)
        
        assert strategy_id == sample_strategy.strategy_id
        assert strategy_id in registry._strategies
        
        # Check metadata file was created
        metadata_file = registry.metadata_path / f"{strategy_id}.json"
        assert metadata_file.exists()
        
        # Verify strategy can be retrieved
        retrieved = registry.get_strategy(strategy_id)
        assert retrieved is not None
        assert retrieved.name == sample_strategy.name
    
    def test_register_strategy_with_files(self, registry, sample_strategy, temp_registry_path):
        """Test strategy registration with model and config files."""
        # Create temporary model and config files
        model_file = Path(temp_registry_path) / "test_model.pkl"
        config_file = Path(temp_registry_path) / "test_config.json"
        
        model_file.write_text("fake model data")
        config_file.write_text('{"test": "config"}')
        
        strategy_id = registry.register_strategy(
            sample_strategy,
            model_file_path=str(model_file),
            config_file_path=str(config_file)
        )
        
        # Check files were copied
        expected_model = registry.models_path / f"{strategy_id}_model.pkl"
        expected_config = registry.configs_path / f"{strategy_id}_config.json"
        
        assert expected_model.exists()
        assert expected_config.exists()
        
        # Check paths were updated in metadata
        retrieved = registry.get_strategy(strategy_id)
        assert retrieved.metadata.model_path == str(expected_model)
        assert retrieved.metadata.config_path == str(expected_config)
    
    def test_register_duplicate_strategy_fails(self, registry, sample_strategy):
        """Test registering duplicate strategy fails without overwrite."""
        registry.register_strategy(sample_strategy)
        
        with pytest.raises(ValueError, match="already exists"):
            registry.register_strategy(sample_strategy)
    
    def test_register_duplicate_strategy_with_overwrite(self, registry, sample_strategy):
        """Test registering duplicate strategy succeeds with overwrite."""
        strategy_id = registry.register_strategy(sample_strategy)
        
        # Modify strategy
        sample_strategy.metadata.description = "Updated description"
        
        # Should succeed with overwrite
        new_id = registry.register_strategy(sample_strategy, overwrite=True)
        assert new_id == strategy_id
        
        # Check description was updated
        retrieved = registry.get_strategy(strategy_id)
        assert retrieved.metadata.description == "Updated description"
    
    def test_get_nonexistent_strategy(self, registry):
        """Test getting non-existent strategy returns None."""
        result = registry.get_strategy("nonexistent_id")
        assert result is None
    
    def test_list_strategies_no_filters(self, registry, sample_strategy):
        """Test listing all strategies without filters."""
        registry.register_strategy(sample_strategy)
        
        strategies = registry.list_strategies()
        assert len(strategies) == 1
        assert strategies[0].strategy_id == sample_strategy.strategy_id
    
    def test_list_strategies_with_status_filter(self, registry, sample_metadata):
        """Test listing strategies filtered by status."""
        # Create strategies with different statuses
        strategy1 = RLStrategy(metadata=sample_metadata)
        strategy1.metadata.strategy_id = "strategy1"
        strategy1.metadata.status = StrategyStatus.TRAINING
        
        strategy2_metadata = create_strategy_metadata(
            name="Strategy 2", description="Test", agent_type=AgentType.PPO, created_by="test"
        )
        strategy2 = RLStrategy(metadata=strategy2_metadata)
        strategy2.metadata.status = StrategyStatus.APPROVED  # Use APPROVED instead of DEPLOYED
        
        registry.register_strategy(strategy1)
        registry.register_strategy(strategy2)
        
        # Filter by TRAINING status
        training_strategies = registry.list_strategies(status=StrategyStatus.TRAINING)
        assert len(training_strategies) == 1
        assert training_strategies[0].strategy_id == "strategy1"
        
        # Filter by APPROVED status
        approved_strategies = registry.list_strategies(status=StrategyStatus.APPROVED)
        assert len(approved_strategies) == 1
        assert approved_strategies[0].strategy_id == strategy2.strategy_id
    
    def test_list_strategies_with_agent_type_filter(self, registry, sample_metadata):
        """Test listing strategies filtered by agent type."""
        # Create DQN strategy
        dqn_strategy = RLStrategy(metadata=sample_metadata)
        dqn_strategy.metadata.agent_type = AgentType.DQN
        
        # Create PPO strategy
        ppo_metadata = create_strategy_metadata(
            name="PPO Strategy", description="Test", agent_type=AgentType.PPO, created_by="test"
        )
        ppo_strategy = RLStrategy(metadata=ppo_metadata)
        
        registry.register_strategy(dqn_strategy)
        registry.register_strategy(ppo_strategy)
        
        # Filter by DQN
        dqn_strategies = registry.list_strategies(agent_type=AgentType.DQN)
        assert len(dqn_strategies) == 1
        assert dqn_strategies[0].agent_type == AgentType.DQN
        
        # Filter by PPO
        ppo_strategies = registry.list_strategies(agent_type=AgentType.PPO)
        assert len(ppo_strategies) == 1
        assert ppo_strategies[0].agent_type == AgentType.PPO
    
    def test_list_strategies_with_currency_pairs_filter(self, registry, sample_strategy):
        """Test listing strategies filtered by currency pairs."""
        # Strategy with EUR/USD and GBP/USD
        sample_strategy.metadata.currency_pairs = ["EUR/USD", "GBP/USD"]
        registry.register_strategy(sample_strategy)
        
        # Strategy with USD/JPY
        other_metadata = create_strategy_metadata(
            name="JPY Strategy", description="Test", agent_type=AgentType.DQN, created_by="test"
        )
        other_metadata.currency_pairs = ["USD/JPY"]
        other_strategy = RLStrategy(metadata=other_metadata)
        registry.register_strategy(other_strategy)
        
        # Filter by EUR/USD
        eur_strategies = registry.list_strategies(currency_pairs=["EUR/USD"])
        assert len(eur_strategies) == 1
        assert sample_strategy.strategy_id in [s.strategy_id for s in eur_strategies]
        
        # Filter by USD/JPY
        jpy_strategies = registry.list_strategies(currency_pairs=["USD/JPY"])
        assert len(jpy_strategies) == 1
        assert other_strategy.strategy_id in [s.strategy_id for s in jpy_strategies]
    
    def test_list_strategies_with_limit(self, registry, sample_metadata):
        """Test listing strategies with limit."""
        # Create multiple strategies
        for i in range(5):
            metadata = create_strategy_metadata(
                name=f"Strategy {i}", description="Test", agent_type=AgentType.DQN, created_by="test"
            )
            strategy = RLStrategy(metadata=metadata)
            registry.register_strategy(strategy)
        
        # Test limit
        strategies = registry.list_strategies(limit=3)
        assert len(strategies) == 3
    
    def test_update_strategy_status(self, registry, sample_strategy):
        """Test updating strategy status."""
        strategy_id = registry.register_strategy(sample_strategy)
        
        # Update status
        success = registry.update_strategy_status(
            strategy_id, StrategyStatus.APPROVED, "test_user", "Ready for deployment"
        )
        assert success
        
        # Verify status was updated
        updated_strategy = registry.get_strategy(strategy_id)
        assert updated_strategy.metadata.status == StrategyStatus.APPROVED
        
        # Check deployment history was recorded
        assert len(updated_strategy.deployment_history) == 1
        history_entry = updated_strategy.deployment_history[0]
        assert history_entry['action'] == 'status_change'
        assert history_entry['new_status'] == StrategyStatus.APPROVED.value
        assert history_entry['updated_by'] == 'test_user'
        assert history_entry['notes'] == 'Ready for deployment'
    
    def test_update_nonexistent_strategy_status(self, registry):
        """Test updating status of non-existent strategy."""
        success = registry.update_strategy_status(
            "nonexistent", StrategyStatus.APPROVED, "test_user"
        )
        assert not success
    
    def test_update_performance(self, registry, sample_strategy, sample_performance):
        """Test updating strategy performance metrics."""
        strategy_id = registry.register_strategy(sample_strategy)
        
        # Create new performance metrics
        new_performance = PerformanceMetrics(
            total_return=0.25,
            sharpe_ratio=1.5,
            max_drawdown=0.06,
            win_rate=0.70,
            profit_factor=2.0,
            calmar_ratio=2.0,
            sortino_ratio=1.8,
            num_trades=150,
            avg_trade_duration=2.0,
            volatility=0.10
        )
        
        # Update performance
        success = registry.update_performance(strategy_id, new_performance)
        assert success
        
        # Verify performance was updated
        updated_strategy = registry.get_strategy(strategy_id)
        assert updated_strategy.performance_metrics.total_return == 0.25
        assert updated_strategy.performance_metrics.sharpe_ratio == 1.5
    
    def test_delete_strategy(self, registry, sample_strategy):
        """Test deleting strategy."""
        strategy_id = registry.register_strategy(sample_strategy)
        
        # Verify strategy exists
        assert registry.get_strategy(strategy_id) is not None
        
        # Delete strategy
        success = registry.delete_strategy(strategy_id)
        assert success
        
        # Verify strategy was deleted
        assert registry.get_strategy(strategy_id) is None
        
        # Verify metadata file was deleted
        metadata_file = registry.metadata_path / f"{strategy_id}.json"
        assert not metadata_file.exists()
    
    def test_delete_nonexistent_strategy(self, registry):
        """Test deleting non-existent strategy."""
        success = registry.delete_strategy("nonexistent")
        assert not success
    
    def test_get_deployable_strategies(self, registry, sample_strategy):
        """Test getting deployable strategies."""
        # Create approved strategy with model path
        sample_strategy.metadata.status = StrategyStatus.APPROVED
        sample_strategy.metadata.model_path = "/path/to/model.pkl"
        strategy_id = registry.register_strategy(sample_strategy)
        
        # Create training strategy (not deployable)
        training_metadata = create_strategy_metadata(
            name="Training Strategy", description="Test", agent_type=AgentType.DQN, created_by="test"
        )
        training_strategy = RLStrategy(metadata=training_metadata)
        registry.register_strategy(training_strategy)
        
        # Get deployable strategies
        deployable = registry.get_deployable_strategies()
        assert len(deployable) == 1
        assert deployable[0].strategy_id == strategy_id
    
    def test_get_performance_leaderboard(self, registry, sample_metadata):
        """Test getting performance leaderboard."""
        # Create strategies with different performance
        strategies_data = [
            {"name": "Strategy A", "sharpe": 1.5, "return": 0.20},
            {"name": "Strategy B", "sharpe": 1.2, "return": 0.15},
            {"name": "Strategy C", "sharpe": 1.8, "return": 0.25},
        ]
        
        for data in strategies_data:
            metadata = create_strategy_metadata(
                name=data["name"], description="Test", agent_type=AgentType.DQN, created_by="test"
            )
            performance = PerformanceMetrics(
                total_return=data["return"],
                sharpe_ratio=data["sharpe"],
                max_drawdown=0.08,
                win_rate=0.65,
                profit_factor=1.5,
                calmar_ratio=1.2,
                sortino_ratio=1.3,
                num_trades=100,
                avg_trade_duration=2.0,
                volatility=0.12
            )
            strategy = RLStrategy(metadata=metadata, performance_metrics=performance)
            registry.register_strategy(strategy)
        
        # Get leaderboard by Sharpe ratio
        leaderboard = registry.get_performance_leaderboard(metric="sharpe_ratio", limit=3)
        
        assert len(leaderboard) == 3
        assert leaderboard[0]['name'] == "Strategy C"  # Highest Sharpe
        assert leaderboard[0]['rank'] == 1
        assert leaderboard[0]['metric_value'] == 1.8
        assert leaderboard[1]['name'] == "Strategy A"
        assert leaderboard[2]['name'] == "Strategy B"
    
    def test_validation_rules(self, registry):
        """Test strategy validation rules."""
        # Test with invalid metadata (empty name) - this should fail at metadata creation
        with pytest.raises(ValueError, match="Strategy name cannot be empty"):
            create_strategy_metadata(
                name="", description="Test", agent_type=AgentType.DQN, created_by="test"
            )
        
        # Test with strategy missing model path for deployed status
        valid_metadata = create_strategy_metadata(
            name="Test Strategy", description="Test", agent_type=AgentType.DQN, created_by="test"
        )
        deployed_strategy = RLStrategy(metadata=valid_metadata)
        deployed_strategy.metadata.status = StrategyStatus.DEPLOYED
        
        with pytest.raises(StrategyValidationError):
            registry.register_strategy(deployed_strategy)
    
    def test_custom_validation_rule(self, registry, sample_strategy):
        """Test adding custom validation rule."""
        def custom_rule(strategy: RLStrategy) -> bool:
            return "test" in strategy.metadata.tags
        
        registry.add_validation_rule(custom_rule)
        
        # Strategy without "test" tag should fail
        sample_strategy.metadata.tags = ["other"]
        with pytest.raises(StrategyValidationError):
            registry.register_strategy(sample_strategy)
        
        # Strategy with "test" tag should succeed
        sample_strategy.metadata.tags = ["test"]
        strategy_id = registry.register_strategy(sample_strategy)
        assert strategy_id is not None
    
    def test_export_import_registry(self, registry, sample_strategy, temp_registry_path):
        """Test exporting and importing registry."""
        # Register strategy
        strategy_id = registry.register_strategy(sample_strategy)
        
        # Export registry
        export_path = Path(temp_registry_path) / "export.json"
        registry.export_registry(str(export_path))
        assert export_path.exists()
        
        # Create new registry and import
        new_registry_path = Path(temp_registry_path) / "new_registry"
        new_registry = StrategyRegistry(str(new_registry_path))
        
        imported_count = new_registry.import_registry(str(export_path))
        assert imported_count == 1
        
        # Verify strategy was imported
        imported_strategy = new_registry.get_strategy(strategy_id)
        assert imported_strategy is not None
        assert imported_strategy.name == sample_strategy.name
    
    def test_persistence_across_instances(self, temp_registry_path, sample_strategy):
        """Test that strategies persist across registry instances."""
        # Create registry and register strategy
        registry1 = StrategyRegistry(temp_registry_path)
        strategy_id = registry1.register_strategy(sample_strategy)
        
        # Create new registry instance
        registry2 = StrategyRegistry(temp_registry_path)
        
        # Verify strategy was loaded
        loaded_strategy = registry2.get_strategy(strategy_id)
        assert loaded_strategy is not None
        assert loaded_strategy.name == sample_strategy.name


class TestStrategyModels:
    """Test cases for strategy data models."""
    
    def test_performance_metrics_validation(self):
        """Test PerformanceMetrics validation."""
        # Valid metrics
        metrics = PerformanceMetrics(
            total_return=0.15,
            sharpe_ratio=1.2,
            max_drawdown=0.08,
            win_rate=0.65,
            profit_factor=1.8,
            calmar_ratio=1.5,
            sortino_ratio=1.4,
            num_trades=100,
            avg_trade_duration=2.5,
            volatility=0.12
        )
        assert metrics.win_rate == 0.65
        
        # Invalid win rate
        with pytest.raises(ValueError, match="Win rate must be between 0 and 1"):
            PerformanceMetrics(
                total_return=0.15, sharpe_ratio=1.2, max_drawdown=0.08,
                win_rate=1.5, profit_factor=1.8, calmar_ratio=1.5,
                sortino_ratio=1.4, num_trades=100, avg_trade_duration=2.5,
                volatility=0.12
            )
        
        # Invalid number of trades
        with pytest.raises(ValueError, match="Number of trades cannot be negative"):
            PerformanceMetrics(
                total_return=0.15, sharpe_ratio=1.2, max_drawdown=0.08,
                win_rate=0.65, profit_factor=1.8, calmar_ratio=1.5,
                sortino_ratio=1.4, num_trades=-10, avg_trade_duration=2.5,
                volatility=0.12
            )
    
    def test_strategy_metadata_validation(self):
        """Test StrategyMetadata validation."""
        now = datetime.now()
        
        # Valid metadata
        metadata = StrategyMetadata(
            strategy_id="test_id",
            name="Test Strategy",
            description="Test description",
            agent_type=AgentType.DQN,
            version="1.0.0",
            status=StrategyStatus.TRAINING,
            created_at=now,
            updated_at=now,
            created_by="test_user"
        )
        assert metadata.name == "Test Strategy"
        
        # Empty strategy ID
        with pytest.raises(ValueError, match="Strategy ID cannot be empty"):
            StrategyMetadata(
                strategy_id="",
                name="Test Strategy",
                description="Test description",
                agent_type=AgentType.DQN,
                version="1.0.0",
                status=StrategyStatus.TRAINING,
                created_at=now,
                updated_at=now,
                created_by="test_user"
            )
        
        # Future timestamp
        future_time = now + timedelta(days=1)
        with pytest.raises(ValueError, match="Created timestamp cannot be in the future"):
            StrategyMetadata(
                strategy_id="test_id",
                name="Test Strategy",
                description="Test description",
                agent_type=AgentType.DQN,
                version="1.0.0",
                status=StrategyStatus.TRAINING,
                created_at=future_time,
                updated_at=now,
                created_by="test_user"
            )
    
    def test_rl_strategy_operations(self):
        """Test RLStrategy operations."""
        metadata = create_strategy_metadata(
            name="Test Strategy", description="Test", agent_type=AgentType.DQN, created_by="test"
        )
        strategy = RLStrategy(metadata=metadata)
        
        # Test status update
        old_status = strategy.status
        strategy.update_status(StrategyStatus.APPROVED, "test_user")
        
        assert strategy.status == StrategyStatus.APPROVED
        assert len(strategy.deployment_history) == 1
        assert strategy.deployment_history[0]['old_status'] == old_status.value
        assert strategy.deployment_history[0]['new_status'] == StrategyStatus.APPROVED.value
        
        # Test performance update
        performance = PerformanceMetrics(
            total_return=0.15, sharpe_ratio=1.2, max_drawdown=0.08,
            win_rate=0.65, profit_factor=1.8, calmar_ratio=1.5,
            sortino_ratio=1.4, num_trades=100, avg_trade_duration=2.5,
            volatility=0.12
        )
        strategy.update_performance(performance)
        assert strategy.performance_metrics == performance
        
        # Test deployability
        strategy.metadata.model_path = "/path/to/model.pkl"
        assert strategy.is_deployable()
    
    def test_serialization(self):
        """Test strategy serialization and deserialization."""
        metadata = create_strategy_metadata(
            name="Test Strategy", description="Test", agent_type=AgentType.DQN, created_by="test"
        )
        performance = PerformanceMetrics(
            total_return=0.15, sharpe_ratio=1.2, max_drawdown=0.08,
            win_rate=0.65, profit_factor=1.8, calmar_ratio=1.5,
            sortino_ratio=1.4, num_trades=100, avg_trade_duration=2.5,
            volatility=0.12
        )
        strategy = RLStrategy(metadata=metadata, performance_metrics=performance)
        
        # Serialize to dict
        strategy_dict = strategy.to_dict()
        assert isinstance(strategy_dict, dict)
        assert strategy_dict['metadata']['name'] == "Test Strategy"
        
        # Deserialize from dict
        restored_strategy = RLStrategy.from_dict(strategy_dict)
        assert restored_strategy.name == strategy.name
        assert restored_strategy.performance_metrics.sharpe_ratio == performance.sharpe_ratio


if __name__ == "__main__":
    pytest.main([__file__])