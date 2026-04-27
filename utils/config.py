"""
Configuration management system for the trading bot.
Supports YAML, JSON, and environment variables.
All parameters are loaded from config files - no hardcoding.
"""

import yaml
import json
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any
from pathlib import Path
from enum import Enum


class RiskMode(str, Enum):
    """Risk management modes."""
    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    AGGRESSIVE = "aggressive"


@dataclass
class RiskSettings:
    """Risk management configuration."""
    mode: str = "balanced"
    max_position_size: float = 0.02  # 2% per trade
    max_daily_loss: float = 0.05  # 5% max daily loss
    max_drawdown: float = 0.20  # 20% max drawdown
    max_open_trades: int = 10
    
    # Position sizing modes
    position_sizing: str = "fixed"  # fixed, equity_risk, atr_based, kelly
    fixed_lot: float = 0.01
    equity_risk_percent: float = 2.0
    
    # Stop loss types
    sl_type: str = "atr"  # fixed, atr, trailing, breakeven
    atr_multiple: float = 2.0
    
    # Take profit types
    tp_type: str = "fixed"  # fixed, volatility_adjusted, partial
    tp_multiple: float = 2.0
    
    # Protection
    trailing_stop: bool = True
    trailing_stop_atr: float = 1.5
    break_even_enabled: bool = True
    partial_profit_points: List[float] = field(default_factory=lambda: [0.5, 0.75, 1.0])


@dataclass
class StrategyConfig:
    """Strategy configuration."""
    name: str
    enabled: bool = True
    weight: float = 1.0  # For multi-strategy allocation
    
    # Strategy-specific parameters
    sma_short: int = 20
    sma_long: int = 50
    
    bollinger_period: int = 20
    bollinger_std: float = 2.0
    
    rsi_period: int = 14
    rsi_oversold: float = 25.0
    rsi_overbought: float = 70.0
    
    breakout_period: int = 20
    breakout_min_range: float = 0.002


@dataclass
class MLConfig:
    """Machine learning configuration."""
    enabled: bool = True
    model_type: str = "xgboost"  # xgboost, random_forest, lstm
    retrain_frequency: str = "weekly"  # daily, weekly, monthly
    confidence_threshold: float = 0.65
    
    # Training parameters
    train_size: float = 0.7
    test_size: float = 0.15
    val_size: float = 0.15
    
    # Model parameters
    n_estimators: int = 100
    max_depth: int = 10
    learning_rate: float = 0.01
    
    # Features
    use_technical: bool = True
    use_volatility: bool = True
    use_returns: bool = True
    use_time_features: bool = True


@dataclass
class BacktestConfig:
    """Backtesting configuration."""
    enabled: bool = True
    start_date: str = "2023-01-01"
    end_date: str = "2024-12-31"
    initial_capital: float = 10000.0
    
    # Simulation parameters
    spread_bps: float = 2.0  # Bid-ask spread in basis points
    slippage_bps: float = 1.0
    commission_pct: float = 0.001
    latency_ms: int = 100
    
    # Optimization
    optimization_enabled: bool = True
    optimization_method: str = "grid"  # grid, genetic, bayesian
    walk_forward_enabled: bool = True
    monte_carlo_enabled: bool = True


@dataclass
class BrokerSettings:
    """Broker connection settings."""
    broker: str = "mt5"  # mt5, oanda, etc.
    login: Optional[int] = None
    password: Optional[str] = None
    server: Optional[str] = None
    
    # Connection parameters
    timeout: int = 30
    max_retries: int = 3
    retry_delay: int = 5


@dataclass
class DataSettings:
    """Data management settings."""
    cache_enabled: bool = True
    cache_dir: str = "data/cache"
    historical_dir: str = "data/historical"
    
    # Data parameters
    granularity: str = "H1"  # H1, H4, D1, etc.
    lookback_candles: int = 500
    
    # Trading pairs
    pairs: List[str] = field(default_factory=lambda: ["EURUSD", "GBPUSD", "USDJPY"])


@dataclass
class MonitoringSettings:
    """Monitoring and alerting settings."""
    log_level: str = "INFO"
    json_log: bool = True
    
    # Alerts
    telegram_enabled: bool = False
    telegram_token: str = ""
    telegram_chat_id: str = ""
    
    discord_enabled: bool = False
    discord_webhook: str = ""
    
    # Metrics
    dashboard_enabled: bool = False
    dashboard_port: int = 8000


@dataclass
class TradingConfig:
    """Complete trading configuration."""
    app_name: str = "AlgoTradingBot"
    version: str = "2.0.0"
    
    risk: RiskSettings = field(default_factory=RiskSettings)
    strategies: List[StrategyConfig] = field(default_factory=lambda: [])
    ml: MLConfig = field(default_factory=MLConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)
    broker: BrokerSettings = field(default_factory=BrokerSettings)
    data: DataSettings = field(default_factory=DataSettings)
    monitoring: MonitoringSettings = field(default_factory=MonitoringSettings)


class ConfigManager:
    """
    Centralized configuration manager.
    Loads from YAML/JSON and manages parameter validation.
    """
    
    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize ConfigManager.
        
        Args:
            config_path: Path to config file (YAML or JSON)
        """
        self.config_path = config_path or "config.yaml"
        self.config: Optional[TradingConfig] = None
        self.load_config()
    
    def load_config(self) -> TradingConfig:
        """Load configuration from file."""
        config_file = Path(self.config_path)
        
        if not config_file.exists():
            print(f"Config file {self.config_path} not found. Using defaults.")
            self.config = TradingConfig()
            return self.config
        
        try:
            if self.config_path.endswith('.yaml') or self.config_path.endswith('.yml'):
                with open(config_file) as f:
                    data = yaml.safe_load(f)
            else:
                with open(config_file) as f:
                    data = json.load(f)
            
            self.config = self._dict_to_config(data)
            return self.config
        
        except Exception as e:
            print(f"Error loading config: {e}. Using defaults.")
            self.config = TradingConfig()
            return self.config
    
    def _dict_to_config(self, data: Dict[str, Any]) -> TradingConfig:
        """Convert dictionary to TradingConfig object."""
        config_dict = {}
        
        # Map dictionary to dataclass fields
        if 'risk' in data:
            config_dict['risk'] = RiskSettings(**data['risk'])
        if 'strategies' in data:
            config_dict['strategies'] = [
                StrategyConfig(**s) for s in data['strategies']
            ]
        if 'ml' in data:
            config_dict['ml'] = MLConfig(**data['ml'])
        if 'backtest' in data:
            config_dict['backtest'] = BacktestConfig(**data['backtest'])
        if 'broker' in data:
            config_dict['broker'] = BrokerSettings(**data['broker'])
        if 'data' in data:
            config_dict['data'] = DataSettings(**data['data'])
        if 'monitoring' in data:
            config_dict['monitoring'] = MonitoringSettings(**data['monitoring'])
        
        # Top-level fields
        for key in ['app_name', 'version']:
            if key in data:
                config_dict[key] = data[key]
        
        return TradingConfig(**config_dict)
    
    def get_config(self) -> TradingConfig:
        """Get the loaded configuration."""
        return self.config or TradingConfig()
    
    def save_config(self, output_path: Optional[str] = None):
        """Save current configuration to file."""
        output_file = output_path or self.config_path
        
        # Convert to dictionary
        config_dict = self._config_to_dict(self.config)
        
        try:
            if output_file.endswith('.yaml') or output_file.endswith('.yml'):
                with open(output_file, 'w') as f:
                    yaml.dump(config_dict, f, default_flow_style=False)
            else:
                with open(output_file, 'w') as f:
                    json.dump(config_dict, f, indent=2)
            print(f"Config saved to {output_file}")
        except Exception as e:
            print(f"Error saving config: {e}")
    
    def _config_to_dict(self, config: TradingConfig) -> Dict[str, Any]:
        """Convert config object to dictionary."""
        return asdict(config)
    
    def validate(self) -> bool:
        """Validate configuration parameters."""
        config = self.get_config()
        
        # Validate risk settings
        if config.risk.max_position_size <= 0 or config.risk.max_position_size > 0.1:
            print(f"Invalid max_position_size: {config.risk.max_position_size}")
            return False
        
        if config.risk.max_daily_loss <= 0 or config.risk.max_daily_loss > 1.0:
            print(f"Invalid max_daily_loss: {config.risk.max_daily_loss}")
            return False
        
        if config.risk.max_drawdown <= 0 or config.risk.max_drawdown > 1.0:
            print(f"Invalid max_drawdown: {config.risk.max_drawdown}")
            return False
        
        # Validate strategy weights sum to valid amount
        if config.strategies:
            total_weight = sum(s.weight for s in config.strategies)
            if total_weight <= 0:
                print(f"Invalid strategy weights sum: {total_weight}")
                return False
        
        return True


def create_default_config(output_path: str = "config.yaml") -> TradingConfig:
    """Create a default configuration file."""
    config = TradingConfig(
        strategies=[
            StrategyConfig(name="sma_crossover", weight=0.4),
            StrategyConfig(name="mean_reversion", weight=0.3),
            StrategyConfig(name="breakout", weight=0.3),
        ]
    )
    
    manager = ConfigManager()
    manager.config = config
    manager.save_config(output_path)
    
    return config
