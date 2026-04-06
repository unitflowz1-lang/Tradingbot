"""Configuration management system for the AI Forex Trading Bot"""

import os
import json
import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional, Callable, Any
from datetime import time as dt_time
from pathlib import Path
import logging
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


@dataclass
class TradingConfig:
    """Trading configuration"""
    supported_pairs: List[str]
    max_daily_trades: int
    risk_per_trade: float
    max_drawdown: float
    trading_hours: Dict[str, Tuple[dt_time, dt_time]]
    max_total_positions: int = 7
    max_trades_per_symbol: int = 2
    max_direction_positions: int = 7
    max_tier_c_trades: int = 2              # NEW: Guard against Tier C dominance
    max_correlated_exposure: int = 7


@dataclass
class LLMConfig:
    """LLM configuration"""
    provider: str
    model: str
    api_key: str
    max_tokens: int
    temperature: float
    timeout: int


@dataclass
class RiskConfig:
    """Risk management configuration"""
    max_position_size: float
    stop_loss_pct: float
    take_profit_pct: float
    max_correlation: float
    drawdown_limit: float


@dataclass
class BrokerConfig:
    """Broker configuration"""
    broker_name: str
    api_key: str
    api_secret: str
    base_url: str
    timeout: int
    login: Optional[int] = None
    password: Optional[str] = None
    server: Optional[str] = None
    symbol_suffix: str = ""


@dataclass
class DatabaseConfig:
    """Database configuration"""
    host: str
    port: int
    database: str
    username: str
    password: str


@dataclass
class CerebrasConfig:
    """Cerebras configuration"""
    api_key: str
    model: str


@dataclass
class NotificationConfig:
    """Notification configuration"""
    webhook_url: str = ""
    smtp_server: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    from_email: str = ""
    to_email: str = ""
    use_tls: bool = True
    enabled: bool = False


@dataclass
class NewsConfig:
    """News configuration"""
    api_key: str = ""
    provider: str = "newsapi"
    min_impact: str = "HIGH"
    enabled: bool = True
    mock_mode: bool = False
    require_live_data: bool = False


@dataclass
class Config:
    """Main configuration class combining all configs"""
    trading: TradingConfig
    llm: LLMConfig
    risk: RiskConfig
    broker: BrokerConfig
    database: DatabaseConfig
    cerebras: CerebrasConfig
    notification: NotificationConfig
    news: NewsConfig
    
    # Market data specific settings
    market_data_cache_ttl: int = 60  # seconds
    api_timeout: int = 30  # seconds
    max_data_age_seconds: int = 300  # 5 minutes
    max_spread_threshold: float = 0.01  # 100 pips
    api_max_retries: int = 3
    api_retry_delay: int = 1  # seconds


class ConfigFileHandler(FileSystemEventHandler):
    """File system event handler for configuration file changes"""
    
    def __init__(self, config_manager: 'ConfigManager'):
        self.config_manager = config_manager
        
    def on_modified(self, event):
        if not event.is_directory and event.src_path == self.config_manager.config_file:
            self.config_manager._reload_config()


class ConfigManager:
    """Enhanced configuration manager with hot-reloading and validation"""
    
    def __init__(self, environment: str = None, config_dir: str = "config"):
        self.environment = environment or os.getenv('ENVIRONMENT', 'dev')
        self.config_dir = Path(config_dir)
        self.config_file = str(self.config_dir / f"config.{self.environment}.json")
        self.base_config_file = str(self.config_dir / "config.base.json")
        
        self._config = {}
        self._config_lock = threading.RLock()
        self._observers = []
        self._change_callbacks: List[Callable[[Dict[str, Any]], None]] = []
        self._logger = logging.getLogger(__name__)
        
        # Initialize configuration
        self._ensure_config_directory()
        self.load_config()
        
        # Setup hot-reloading
        self._setup_hot_reload()
    
    def _ensure_config_directory(self) -> None:
        """Ensure configuration directory exists"""
        self.config_dir.mkdir(exist_ok=True)
        
        # Create base configuration if it doesn't exist
        if not Path(self.base_config_file).exists():
            self._create_base_config()
        
        # Create environment-specific config if it doesn't exist
        if not Path(self.config_file).exists():
            self._create_environment_config()
    
    def _create_base_config(self) -> None:
        """Create base configuration file"""
        base_config = {
            "trading": {
                "supported_pairs": ["EUR/USD", "GBP/USD", "USD/JPY"],
                "max_total_positions": 7,
                "max_daily_trades": 10,
                "max_trades_per_symbol": 2,
                "max_direction_positions": 7,
                "max_tier_c_trades": 2,
                "max_correlated_exposure": 7,
                "risk_per_trade": 0.01,
                "max_drawdown": 0.10,
                "trading_hours": {
                    "monday": ["00:00", "23:59"],
                    "tuesday": ["00:00", "23:59"],
                    "wednesday": ["00:00", "23:59"],
                    "thursday": ["00:00", "23:59"],
                    "friday": ["00:00", "21:00"]
                }
            },
            "llm": {
                "provider": "openai",
                "model": "gpt-4",
                "max_tokens": 1000,
                "temperature": 0.1,
                "timeout": 30
            },
            "risk": {
                "max_position_size": 0.05,
                "stop_loss_pct": 0.02,
                "take_profit_pct": 0.04,
                "max_correlation": 0.7,
                "drawdown_limit": 0.10
            },
            "market_data_cache_ttl": 60,
            "api_timeout": 30,
            "max_data_age_seconds": 300,
            "max_spread_threshold": 0.01,
            "api_max_retries": 3,
            "api_retry_delay": 1
        }
        
        with open(self.base_config_file, 'w', encoding='utf-8') as f:
            json.dump(base_config, f, indent=2)
    
    def _create_environment_config(self) -> None:
        """Create environment-specific configuration file"""
        env_configs = {
            "dev": {
                "broker": {
                    "broker_name": "demo-broker",
                    "base_url": "https://demo-api.broker.com",
                    "timeout": 30
                },
                "database": {
                    "host": "localhost",
                    "port": 5432,
                    "database": "forex_bot_dev"
                },
                "logging_level": "DEBUG"
            },
            "staging": {
                "broker": {
                    "broker_name": "staging-broker",
                    "base_url": "https://staging-api.broker.com",
                    "timeout": 30
                },
                "database": {
                    "host": "staging-db",
                    "port": 5432,
                    "database": "forex_bot_staging"
                },
                "logging_level": "INFO"
            },
            "prod": {
                "broker": {
                    "broker_name": "production-broker",
                    "base_url": "https://api.broker.com",
                    "timeout": 30
                },
                "database": {
                    "host": "prod-db",
                    "port": 5432,
                    "database": "forex_bot_prod"
                },
                "logging_level": "WARNING",
                "trading": {
                    "max_total_positions": 7,
                    "max_direction_positions": 7,
                    "risk_per_trade": 0.01
                }
            }
        }
        
        config = env_configs.get(self.environment, env_configs["dev"])
        
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2)
    
    def _setup_hot_reload(self) -> None:
        """Setup file system monitoring for hot-reloading"""
        try:
            self.observer = Observer()
            event_handler = ConfigFileHandler(self)
            self.observer.schedule(event_handler, str(self.config_dir), recursive=False)
            self.observer.start()
            self._logger.info(f"Hot-reload enabled for configuration files in {self.config_dir}")
        except Exception as e:
            self._logger.warning(f"Could not setup hot-reload: {e}")
    
    def add_change_callback(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """Add callback to be called when configuration changes"""
        self._change_callbacks.append(callback)
    
    def remove_change_callback(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """Remove configuration change callback"""
        if callback in self._change_callbacks:
            self._change_callbacks.remove(callback)
    
    def _reload_config(self) -> None:
        """Reload configuration from files"""
        try:
            old_config = self._config.copy()
            self.load_config()
            
            # Notify callbacks of configuration change
            for callback in self._change_callbacks:
                try:
                    callback(self._config)
                except Exception as e:
                    self._logger.error(f"Error in configuration change callback: {e}")
            
            self._logger.info("Configuration reloaded successfully")
        except Exception as e:
            self._logger.error(f"Failed to reload configuration: {e}")
    
    def load_config(self) -> None:
        """Load configuration from base and environment-specific files"""
        with self._config_lock:
            self._config = {}
            
            # Load base configuration
            if os.path.exists(self.base_config_file):
                try:
                    with open(self.base_config_file, 'r', encoding='utf-8') as f:
                        base_config = json.load(f)
                        self._config.update(base_config)
                except Exception as e:
                    self._logger.error(f"Failed to load base config: {e}")
            
            # Load environment-specific configuration
            if os.path.exists(self.config_file):
                try:
                    with open(self.config_file, 'r', encoding='utf-8') as f:
                        env_config = json.load(f)
                        self._deep_merge(self._config, env_config)
                except Exception as e:
                    self._logger.error(f"Failed to load environment config: {e}")
            
            # Override with environment variables
            self._load_env_variables()
            
            # Validate configuration
            validation_errors = self.validate_config()
            if validation_errors:
                self._logger.warning(f"Configuration validation errors: {validation_errors}")
    
    def _deep_merge(self, base: Dict[str, Any], override: Dict[str, Any]) -> None:
        """Deep merge override dictionary into base dictionary"""
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_merge(base[key], value)
            else:
                base[key] = value
    
    def _load_env_variables(self) -> None:
        """Load configuration from environment variables"""
        env_mappings = {
            'TRADING_MAX_TOTAL_POSITIONS': ('trading.max_total_positions', int),
            'TRADING_MAX_DAILY_TRADES': ('trading.max_daily_trades', int),
            'TRADING_MAX_TRADES_PER_SYMBOL': ('trading.max_trades_per_symbol', int),
            'TRADING_MAX_DIRECTION_POSITIONS': ('trading.max_direction_positions', int),
            'TRADING_MAX_TI_C_TRADES': ('trading.max_tier_c_trades', int),
            'TRADING_MAX_CORRELATED_EXPOSURE': ('trading.max_correlated_exposure', int),
            'TRADING_RISK_PER_TRADE': ('trading.risk_per_trade', float),
            'TRADING_MAX_DRAWDOWN': ('trading.max_drawdown', float),
            'LLM_PROVIDER': ('llm.provider', str),
            'LLM_MODEL': ('llm.model', str),
            'LLM_API_KEY': ('llm.api_key', str),
            'LLM_MAX_TOKENS': ('llm.max_tokens', int),
            'LLM_TEMPERATURE': ('llm.temperature', float),
            'LLM_TIMEOUT': ('llm.timeout', int),
            'RISK_MAX_POSITION_SIZE': ('risk.max_position_size', float),
            'RISK_STOP_LOSS_PCT': ('risk.stop_loss_pct', float),
            'RISK_TAKE_PROFIT_PCT': ('risk.take_profit_pct', float),
            'RISK_MAX_CORRELATION': ('risk.max_correlation', float),
            'RISK_DRAWDOWN_LIMIT': ('risk.drawdown_limit', float),
            'BROKER_NAME': ('broker.broker_name', str),
            'BROKER_API_KEY': ('broker.api_key', str),
            'BROKER_API_SECRET': ('broker.api_secret', str),
            'BROKER_BASE_URL': ('broker.base_url', str),
            'BROKER_TIMEOUT': ('broker.timeout', int),
            'BROKER_LOGIN': ('broker.login', int),
            'BROKER_PASSWORD': ('broker.password', str),
            'BROKER_SERVER': ('broker.server', str),
            'MT5_SYMBOL_SUFFIX': ('broker.symbol_suffix', str),
            'DB_HOST': ('database.host', str),
            'DB_PORT': ('database.port', int),
            'DB_DATABASE': ('database.database', str),
            'DB_USERNAME': ('database.username', str),
            'DB_PASSWORD': ('database.password', str),
            'NOTIFY_WEBHOOK_URL': ('notification.webhook_url', str),
            'NOTIFY_SMTP_SERVER': ('notification.smtp_server', str),
            'NOTIFY_SMTP_PORT': ('notification.smtp_port', int),
            'NOTIFY_SMTP_USER': ('notification.smtp_user', str),
            'NOTIFY_SMTP_PASSWORD': ('notification.smtp_password', str),
            'NOTIFY_FROM': ('notification.from_email', str),
            'NOTIFY_TO': ('notification.to_email', str),
            'NOTIFY_ENABLED': ('notification.enabled', lambda x: x.lower() == 'true'),
            'NEWS_API_KEY': ('news.api_key', str),
            'NEWS_PROVIDER': ('news.provider', str),
            'NEWS_MIN_IMPACT': ('news.min_impact', str),
            'NEWS_ENABLED': ('news.enabled', lambda x: x.lower() == 'true'),
            # ===== ISSUE #2 FIX: Add NEWS_MOCK_MODE boolean parser =====
            # Environment variable NEWS_MOCK_MODE comes as string "true"/"false"
            # Must convert "false" string to boolean False, not leave as truthy string
            'NEWS_MOCK_MODE': ('news.mock_mode', lambda x: x.lower() in ('true', '1', 't', 'yes')),
        }
        
        for env_var, (config_path, value_type) in env_mappings.items():
            value = os.getenv(env_var)
            if value is not None:
                try:
                    self._set_nested_config(config_path, value_type(value))
                except (ValueError, TypeError) as e:
                    self._logger.error(f"Invalid environment variable {env_var}: {e}")
    
    def _set_nested_config(self, path: str, value: Any) -> None:
        """Set nested configuration value"""
        keys = path.split('.')
        config = self._config
        
        for key in keys[:-1]:
            if key not in config:
                config[key] = {}
            config = config[key]
        
        config[keys[-1]] = value
    
    def get_nested_config(self, path: str, default: Any = None) -> Any:
        """Get nested configuration value"""
        keys = path.split('.')
        config = self._config
        
        try:
            for key in keys:
                config = config[key]
            return config
        except (KeyError, TypeError):
            return default
    
    def update_config(self, updates: Dict[str, Any], persist: bool = True) -> None:
        """Update configuration values"""
        with self._config_lock:
            self._deep_merge(self._config, updates)
            
            if persist:
                self._save_environment_config()
            
            # Notify callbacks
            for callback in self._change_callbacks:
                try:
                    callback(self._config)
                except Exception as e:
                    self._logger.error(f"Error in configuration change callback: {e}")
    
    def _save_environment_config(self) -> None:
        """Save current configuration to environment-specific file"""
        try:
            # Extract environment-specific overrides
            env_config = {}
            
            # Only save non-base configuration values
            base_config = {}
            if os.path.exists(self.base_config_file):
                with open(self.base_config_file, 'r', encoding='utf-8') as f:
                    base_config = json.load(f)
            
            # Find differences from base config
            self._extract_differences(base_config, self._config, env_config)
            
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(env_config, f, indent=2)
                
        except Exception as e:
            self._logger.error(f"Failed to save environment config: {e}")
    
    def _extract_differences(self, base: Dict[str, Any], current: Dict[str, Any], result: Dict[str, Any]) -> None:
        """Extract differences between base and current configuration"""
        for key, value in current.items():
            if key not in base:
                result[key] = value
            elif isinstance(value, dict) and isinstance(base[key], dict):
                nested_result = {}
                self._extract_differences(base[key], value, nested_result)
                if nested_result:
                    result[key] = nested_result
            elif value != base[key]:
                result[key] = value
    
    def stop_hot_reload(self) -> None:
        """Stop hot-reload file monitoring"""
        if hasattr(self, 'observer'):
            self.observer.stop()
            self.observer.join()
    
    def get_trading_config(self) -> TradingConfig:
        """Get trading configuration"""
        with self._config_lock:
            trading_config = self._config.get('trading', {})
            
            # Parse trading hours
            trading_hours = {}
            hours_config = trading_config.get('trading_hours', {})
            default_hours = {
                'monday': (dt_time(0, 0), dt_time(23, 59)),
                'tuesday': (dt_time(0, 0), dt_time(23, 59)),
                'wednesday': (dt_time(0, 0), dt_time(23, 59)),
                'thursday': (dt_time(0, 0), dt_time(23, 59)),
                'friday': (dt_time(0, 0), dt_time(21, 0)),
            }
            
            for day, hours in hours_config.items():
                if isinstance(hours, list) and len(hours) == 2:
                    try:
                        start_time = dt_time.fromisoformat(hours[0])
                        end_time = dt_time.fromisoformat(hours[1])
                        trading_hours[day] = (start_time, end_time)
                    except ValueError:
                        trading_hours[day] = default_hours.get(day, (dt_time(0, 0), dt_time(23, 59)))
                else:
                    trading_hours[day] = default_hours.get(day, (dt_time(0, 0), dt_time(23, 59)))
            
            # Fill in missing days with defaults
            for day, default_time in default_hours.items():
                if day not in trading_hours:
                    trading_hours[day] = default_time
            
            return TradingConfig(
                supported_pairs=trading_config.get('supported_pairs', ['EUR/USD', 'GBP/USD', 'USD/JPY']),
                max_total_positions=trading_config.get('max_total_positions', 7),
                max_daily_trades=trading_config.get('max_daily_trades', 10),
                max_trades_per_symbol=trading_config.get('max_trades_per_symbol', 2),
                max_direction_positions=trading_config.get('max_direction_positions', 7),
                max_tier_c_trades=trading_config.get('max_tier_c_trades', 2),
                max_correlated_exposure=trading_config.get('max_correlated_exposure', 7),
                risk_per_trade=trading_config.get('risk_per_trade', 0.01),
                max_drawdown=trading_config.get('max_drawdown', 0.10),
                trading_hours=trading_hours
            )
    
    def get_llm_config(self) -> LLMConfig:
        """Get LLM configuration"""
        with self._config_lock:
            llm_config = self._config.get('llm', {})
            
            return LLMConfig(
                provider=llm_config.get('provider', 'openai'),
                model=llm_config.get('model', 'gpt-4'),
                api_key=llm_config.get('api_key', ''),
                max_tokens=llm_config.get('max_tokens', 1000),
                temperature=llm_config.get('temperature', 0.1),
                timeout=llm_config.get('timeout', 30)
            )
    
    def get_risk_config(self) -> RiskConfig:
        """Get risk management configuration"""
        with self._config_lock:
            risk_config = self._config.get('risk', {})
            
            return RiskConfig(
                max_position_size=risk_config.get('max_position_size', 0.05),
                stop_loss_pct=risk_config.get('stop_loss_pct', 0.02),
                take_profit_pct=risk_config.get('take_profit_pct', 0.04),
                max_correlation=risk_config.get('max_correlation', 0.7),
                drawdown_limit=risk_config.get('drawdown_limit', 0.10)
            )
    
    def get_broker_config(self) -> BrokerConfig:
        """Get broker configuration"""
        with self._config_lock:
            broker_config = self._config.get('broker', {})
            
            return BrokerConfig(
                broker_name=broker_config.get('broker_name', ''),
                api_key=broker_config.get('api_key', ''),
                api_secret=broker_config.get('api_secret', ''),
                base_url=broker_config.get('base_url', ''),
                timeout=broker_config.get('timeout', 30),
                login=broker_config.get('login'),
                password=broker_config.get('password'),
                server=broker_config.get('server'),
                symbol_suffix=broker_config.get('symbol_suffix', '')
            )
    
    def get_database_config(self) -> DatabaseConfig:
        """Get database configuration"""
        with self._config_lock:
            db_config = self._config.get('database', {})
            
            return DatabaseConfig(
                host=db_config.get('host', 'localhost'),
                port=db_config.get('port', 5432),
                database=db_config.get('database', 'forex_bot'),
                username=db_config.get('username', ''),
                password=db_config.get('password', '')
            )
    
    def get_cerebras_config(self) -> CerebrasConfig:
        """Get Cerebras configuration"""
        with self._config_lock:
            cerebras_config = self._config.get('cerebras', {})
            
            return CerebrasConfig(
                api_key=cerebras_config.get('api_key', ''),
                model=cerebras_config.get('model', 'zai-glm-4.7')
            )

    def get_notification_config(self) -> NotificationConfig:
        """Get notification configuration"""
        with self._config_lock:
            notif_config = self._config.get('notification', {})
            return NotificationConfig(
                webhook_url=notif_config.get('webhook_url', ''),
                smtp_server=notif_config.get('smtp_server', ''),
                smtp_port=notif_config.get('smtp_port', 587),
                smtp_user=notif_config.get('smtp_user', ''),
                smtp_password=notif_config.get('smtp_password', ''),
                from_email=notif_config.get('from_email', ''),
                to_email=notif_config.get('to_email', ''),
                use_tls=notif_config.get('use_tls', True),
                enabled=notif_config.get('enabled', False)
            )

    def get_news_config(self) -> NewsConfig:
        """Get news configuration"""
        with self._config_lock:
            news_config = self._config.get('news', {})
            provider = str(news_config.get('provider', '') or '').strip() or 'mock'
            return NewsConfig(
                api_key=news_config.get('api_key', ''),
                provider=provider,
                min_impact=news_config.get('min_impact', 'HIGH'),
                enabled=news_config.get('enabled', False),
                mock_mode=news_config.get('mock_mode', False),
                require_live_data=news_config.get('require_live_data', False),
            )
    
    def get_config(self) -> Config:
        """Get complete configuration object"""
        with self._config_lock:
            return Config(
                trading=self.get_trading_config(),
                llm=self.get_llm_config(),
                risk=self.get_risk_config(),
                broker=self.get_broker_config(),
                database=self.get_database_config(),
                cerebras=self.get_cerebras_config(),
                notification=self.get_notification_config(),
                news=self.get_news_config(),
                market_data_cache_ttl=self._config.get('market_data_cache_ttl', 60),
                api_timeout=self._config.get('api_timeout', 30),
                max_data_age_seconds=self._config.get('max_data_age_seconds', 300),
                max_spread_threshold=self._config.get('max_spread_threshold', 0.01),
                api_max_retries=self._config.get('api_max_retries', 3),
                api_retry_delay=self._config.get('api_retry_delay', 1)
            )
    
    def validate_config(self) -> List[str]:
        """Validate configuration and return list of errors"""
        errors = []
        
        try:
            # Validate LLM config
            llm_config = self.get_llm_config()
            if not llm_config.api_key and self.environment == 'prod':
                errors.append("LLM API key is required for production environment")
            
            if llm_config.temperature < 0 or llm_config.temperature > 2:
                errors.append("LLM temperature must be between 0 and 2")
            
            if llm_config.max_tokens <= 0:
                errors.append("LLM max_tokens must be positive")
            
            # Validate broker config
            broker_config = self.get_broker_config()
            if self.environment == 'prod':
                if not broker_config.api_key or not broker_config.api_secret:
                    errors.append("Broker API credentials are required for production environment")
            
            if broker_config.timeout <= 0:
                errors.append("Broker timeout must be positive")
            
            # Validate risk parameters
            risk_config = self.get_risk_config()
            if risk_config.max_position_size <= 0 or risk_config.max_position_size > 1:
                errors.append("Max position size must be between 0 and 1")
            
            if risk_config.stop_loss_pct <= 0:
                errors.append("Stop loss percentage must be positive")
            
            if risk_config.take_profit_pct <= 0:
                errors.append("Take profit percentage must be positive")
            
            if risk_config.max_correlation < 0 or risk_config.max_correlation > 1:
                errors.append("Max correlation must be between 0 and 1")
            
            if risk_config.drawdown_limit <= 0 or risk_config.drawdown_limit > 1:
                errors.append("Drawdown limit must be between 0 and 1")
            
            # Validate trading config
            trading_config = self.get_trading_config()
            if trading_config.max_total_positions <= 0:
                errors.append("Max total positions must be positive")
            
            if trading_config.max_daily_trades < 0:
                errors.append("Max daily trades must be non-negative")
            
            if trading_config.risk_per_trade <= 0 or trading_config.risk_per_trade > 1:
                errors.append("Risk per trade must be between 0 and 1")
            
            if trading_config.max_drawdown <= 0 or trading_config.max_drawdown > 1:
                errors.append("Max drawdown must be between 0 and 1")
            
            if not trading_config.supported_pairs:
                errors.append("At least one supported currency pair is required")
            
            # Validate database config
            db_config = self.get_database_config()
            if db_config.port <= 0 or db_config.port > 65535:
                errors.append("Database port must be between 1 and 65535")
            
            if not db_config.host:
                errors.append("Database host is required")
            
            if not db_config.database:
                errors.append("Database name is required")
            
        except Exception as e:
            errors.append(f"Configuration validation error: {str(e)}")
        
        return errors
    
    def is_valid(self) -> bool:
        """Check if configuration is valid"""
        return len(self.validate_config()) == 0
    
    def get_validation_summary(self) -> Dict[str, Any]:
        """Get validation summary with errors and warnings"""
        errors = self.validate_config()
        warnings = []
        
        # Add warnings for development environment
        if self.environment == 'dev':
            llm_config = self.get_llm_config()
            if not llm_config.api_key:
                warnings.append("LLM API key not set - some features may not work")
            
            broker_config = self.get_broker_config()
            if not broker_config.api_key:
                warnings.append("Broker API key not set - trading will not work")
        
        return {
            'valid': len(errors) == 0,
            'errors': errors,
            'warnings': warnings,
            'environment': self.environment
        }


# Global configuration manager instance
_config_manager: Optional[ConfigManager] = None


def get_config_manager(environment: str = None, config_dir: str = "config") -> ConfigManager:
    """Get global configuration manager instance"""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager(environment, config_dir)
    return _config_manager


def reset_config_manager() -> None:
    """Reset global configuration manager (mainly for testing)"""
    global _config_manager
    if _config_manager is not None:
        _config_manager.stop_hot_reload()
        _config_manager = None
