"""
Data models for RL strategy management system.

This module contains data classes and enums for strategy registry,
versioning, and performance tracking.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Any
import uuid


class StrategyStatus(Enum):
    """Strategy deployment status."""
    TRAINING = "TRAINING"
    VALIDATION = "VALIDATION"
    APPROVED = "APPROVED"
    DEPLOYED = "DEPLOYED"
    DEPRECATED = "DEPRECATED"
    FAILED = "FAILED"


class AgentType(Enum):
    """RL agent types."""
    DQN = "DQN"
    PPO = "PPO"
    A3C = "A3C"
    SAC = "SAC"


@dataclass
class PerformanceMetrics:
    """Performance metrics for strategy evaluation."""
    total_return: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    profit_factor: float
    calmar_ratio: float
    sortino_ratio: float
    num_trades: int
    avg_trade_duration: float
    volatility: float
    beta: Optional[float] = None
    alpha: Optional[float] = None
    information_ratio: Optional[float] = None
    
    def __post_init__(self):
        """Validate performance metrics."""
        if self.win_rate < 0 or self.win_rate > 1:
            raise ValueError(f"Win rate must be between 0 and 1: {self.win_rate}")
        if self.num_trades < 0:
            raise ValueError(f"Number of trades cannot be negative: {self.num_trades}")
        if self.avg_trade_duration < 0:
            raise ValueError(f"Average trade duration cannot be negative: {self.avg_trade_duration}")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'total_return': self.total_return,
            'sharpe_ratio': self.sharpe_ratio,
            'max_drawdown': self.max_drawdown,
            'win_rate': self.win_rate,
            'profit_factor': self.profit_factor,
            'calmar_ratio': self.calmar_ratio,
            'sortino_ratio': self.sortino_ratio,
            'num_trades': self.num_trades,
            'avg_trade_duration': self.avg_trade_duration,
            'volatility': self.volatility,
            'beta': self.beta,
            'alpha': self.alpha,
            'information_ratio': self.information_ratio
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PerformanceMetrics':
        """Create from dictionary."""
        return cls(**data)


@dataclass
class StrategyMetadata:
    """Metadata for RL strategy."""
    strategy_id: str
    name: str
    description: str
    agent_type: AgentType
    version: str
    status: StrategyStatus
    created_at: datetime
    updated_at: datetime
    created_by: str
    tags: List[str] = field(default_factory=list)
    currency_pairs: List[str] = field(default_factory=list)
    timeframe: str = "1H"
    model_path: Optional[str] = None
    config_path: Optional[str] = None
    training_data_period: Optional[str] = None
    validation_data_period: Optional[str] = None
    
    def __post_init__(self):
        """Validate metadata."""
        if not self.strategy_id:
            raise ValueError("Strategy ID cannot be empty")
        if not self.name:
            raise ValueError("Strategy name cannot be empty")
        if not isinstance(self.agent_type, AgentType):
            raise ValueError(f"Invalid agent type: {self.agent_type}")
        if not isinstance(self.status, StrategyStatus):
            raise ValueError(f"Invalid status: {self.status}")
        # Allow 1 day in future for historical data and server time differences
        max_future_time = datetime.now() + timedelta(days=1)
        if self.created_at > max_future_time:
            raise ValueError("Created timestamp cannot be in the future")
        if self.updated_at > max_future_time:
            raise ValueError("Updated timestamp cannot be in the future")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'strategy_id': self.strategy_id,
            'name': self.name,
            'description': self.description,
            'agent_type': self.agent_type.value,
            'version': self.version,
            'status': self.status.value,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'created_by': self.created_by,
            'tags': self.tags,
            'currency_pairs': self.currency_pairs,
            'timeframe': self.timeframe,
            'model_path': self.model_path,
            'config_path': self.config_path,
            'training_data_period': self.training_data_period,
            'validation_data_period': self.validation_data_period
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'StrategyMetadata':
        """Create from dictionary."""
        data = data.copy()
        data['agent_type'] = AgentType(data['agent_type'])
        data['status'] = StrategyStatus(data['status'])
        data['created_at'] = datetime.fromisoformat(data['created_at'])
        data['updated_at'] = datetime.fromisoformat(data['updated_at'])
        return cls(**data)


@dataclass
class RLStrategy:
    """Complete RL strategy with metadata and performance."""
    metadata: StrategyMetadata
    performance_metrics: Optional[PerformanceMetrics] = None
    config: Dict[str, Any] = field(default_factory=dict)
    training_history: List[Dict[str, Any]] = field(default_factory=list)
    validation_results: List[Dict[str, Any]] = field(default_factory=list)
    deployment_history: List[Dict[str, Any]] = field(default_factory=list)
    
    def __post_init__(self):
        """Validate strategy."""
        if not isinstance(self.metadata, StrategyMetadata):
            raise ValueError("Metadata must be StrategyMetadata instance")
        if self.performance_metrics and not isinstance(self.performance_metrics, PerformanceMetrics):
            raise ValueError("Performance metrics must be PerformanceMetrics instance")
    
    @property
    def strategy_id(self) -> str:
        """Get strategy ID."""
        return self.metadata.strategy_id
    
    @property
    def name(self) -> str:
        """Get strategy name."""
        return self.metadata.name
    
    @property
    def version(self) -> str:
        """Get strategy version."""
        return self.metadata.version
    
    @property
    def status(self) -> StrategyStatus:
        """Get strategy status."""
        return self.metadata.status
    
    def update_status(self, new_status: StrategyStatus, updated_by: str) -> None:
        """Update strategy status."""
        old_status = self.metadata.status
        self.metadata.status = new_status
        self.metadata.updated_at = datetime.now()
        
        # Record status change in deployment history
        self.deployment_history.append({
            'timestamp': datetime.now().isoformat(),
            'action': 'status_change',
            'old_status': old_status.value,
            'new_status': new_status.value,
            'updated_by': updated_by
        })
    
    def update_performance(self, metrics: PerformanceMetrics) -> None:
        """Update performance metrics."""
        self.performance_metrics = metrics
        self.metadata.updated_at = datetime.now()
    
    def add_training_record(self, record: Dict[str, Any]) -> None:
        """Add training history record."""
        record['timestamp'] = datetime.now().isoformat()
        self.training_history.append(record)
    
    def add_validation_record(self, record: Dict[str, Any]) -> None:
        """Add validation results record."""
        record['timestamp'] = datetime.now().isoformat()
        self.validation_results.append(record)
    
    def is_deployable(self) -> bool:
        """Check if strategy is ready for deployment."""
        return (
            self.metadata.status == StrategyStatus.APPROVED and
            self.performance_metrics is not None and
            self.metadata.model_path is not None
        )
    
    def get_latest_performance(self) -> Optional[PerformanceMetrics]:
        """Get latest performance metrics."""
        return self.performance_metrics
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'metadata': self.metadata.to_dict(),
            'performance_metrics': self.performance_metrics.to_dict() if self.performance_metrics else None,
            'config': self.config,
            'training_history': self.training_history,
            'validation_results': self.validation_results,
            'deployment_history': self.deployment_history
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RLStrategy':
        """Create from dictionary."""
        data = data.copy()
        data['metadata'] = StrategyMetadata.from_dict(data['metadata'])
        if data.get('performance_metrics'):
            data['performance_metrics'] = PerformanceMetrics.from_dict(data['performance_metrics'])
        return cls(**data)


def generate_strategy_id() -> str:
    """Generate unique strategy ID."""
    return f"rl_strategy_{uuid.uuid4().hex[:8]}"


def create_strategy_metadata(
    name: str,
    description: str,
    agent_type: AgentType,
    created_by: str,
    version: str = "1.0.0",
    tags: Optional[List[str]] = None,
    currency_pairs: Optional[List[str]] = None,
    timeframe: str = "1H"
) -> StrategyMetadata:
    """Create strategy metadata with defaults."""
    now = datetime.now()
    return StrategyMetadata(
        strategy_id=generate_strategy_id(),
        name=name,
        description=description,
        agent_type=agent_type,
        version=version,
        status=StrategyStatus.TRAINING,
        created_at=now,
        updated_at=now,
        created_by=created_by,
        tags=tags or [],
        currency_pairs=currency_pairs or [],
        timeframe=timeframe
    )