"""
Deployment Configuration
Controls bot behavior for paper trading and live deployment
"""

class DeploymentConfig:
    """Deployment environment and risk parameters"""
    
    # === ENVIRONMENT ===
    ENVIRONMENT = "PAPER_TRADING"  # Options: PAPER_TRADING, LIVE_MICRO, LIVE_FULL
    PAPER_TRADING_ACCOUNT_NAME = "TradingBot3_Demo"
    
    # === POSITION SIZING ===
    # Paper Trading: Start conservative
    LOT_SIZE_BASE = 0.1  # Paper: 0.1 lot per trade ($100 risk)
    LOT_SIZE_AGGRESSIVE = 0.15  # After 1 week of 54%+ WR
    LOT_SIZE_MICRO = 0.5  # Live micro: $5-10 risk
    LOT_SIZE_STANDARD = 1.0  # Live standard: $10-50 risk
    
    # === RISK LIMITS ===
    MAX_RISK_PER_TRADE = 100.0  # $ risk per trade (paper)
    MAX_DAILY_LOSS = 500.0  # Daily loss limit ($)
    MAX_WEEKLY_LOSS = 2500.0  # Weekly loss limit ($)
    MAX_MONTHLY_LOSS = 10000.0  # Monthly loss limit ($)
    MAX_DRAWDOWN_PERCENT = 2.0  # Max portfolio drawdown %
    
    # === POSITION MANAGEMENT ===
    MAX_CONCURRENT_POSITIONS = 4  # Max positions open simultaneously
    MAX_POS_PER_SYMBOL = 1  # Max position per symbol
    MAX_SAME_DIRECTION = 2  # Max same direction (LONG or SHORT)
    
    # === MONITORING ===
    # Real-time monitoring (live trading)
    ENABLE_LIVE_MONITORING = True
    MONITOR_INTERVAL_SECONDS = 60  # Check every 60 seconds
    
    # Daily reporting (email/log)
    ENABLE_DAILY_REPORT = True
    DAILY_REPORT_TIME = "17:00"  # 5 PM UTC (after NY close)
    
    # P&L tracking
    ENABLE_PNL_TRACKING = True
    PNL_TRACKING_INTERVAL = 3600  # Every hour
    
    # === ALERTS ===
    ALERT_WIN_RATE_THRESHOLD_LOW = 0.50  # Alert if WR < 50%
    ALERT_DRAWDOWN_THRESHOLD = 0.015  # Alert if DD > 1.5%
    ALERT_LOSING_STREAK = 5  # Alert after 5 consecutive losses
    
    # === SYMBOL TRADING ===
    ENABLED_SYMBOLS = [
        'EUR/USD',
        'GBP/USD', 
        'AUD/USD',
        'USD/JPY'
    ]
    
    # Symbol-specific settings (can override global)
    SYMBOL_SETTINGS = {
        'EUR/USD': {
            'enabled': True,
            'lot_size_multiplier': 1.0,  # Trade at base lot size
            'max_positions': 1,
            'min_quality_threshold': 0.75,
        },
        'GBP/USD': {
            'enabled': True,
            'lot_size_multiplier': 1.0,
            'max_positions': 1,
            'min_quality_threshold': 0.75,
        },
        'AUD/USD': {
            'enabled': True,
            'lot_size_multiplier': 1.0,
            'max_positions': 1,
            'min_quality_threshold': 0.60,  # ===== FIX #1: GLOBAL QUALITY RESET 76% -> 60% =====
        },
        'USD/JPY': {
            'enabled': True,
            'lot_size_multiplier': 0.9,  # Slightly smaller for high volatility
            'max_positions': 1,
            'min_quality_threshold': 0.60,  # ===== FIX #1: GLOBAL QUALITY RESET 77% -> 60% =====
        },
    }
    
    # === EXIT STRATEGIES ===
    EXIT_STRATEGIES = {
        'trailing_stop': {
            'enabled': True,
            'atr_multiplier': 0.5,
            'min_profit_pips': 10,
        },
        'breakeven_stop': {
            'enabled': True,
            'activation_ratio': 0.7,
            'buffer_pips': 2,
        },
        'time_based_exit': {
            'enabled': True,
            'max_hold_bars': 72,  # 3 days on 1H
        },
        'partial_profits': {
            'enabled': True,
            'levels': [
                {'profit_ratio': 1.0, 'close_percent': 0.30},  # 30% at 1R
                {'profit_ratio': 2.0, 'close_percent': 0.30},  # 30% at 2R
                {'profit_ratio': 3.0, 'close_percent': 0.40},  # 40% at 3R
            ],
        },
    }
    
    # === LOGGING & DEBUGGING ===
    LOG_LEVEL = "INFO"  # DEBUG, INFO, WARNING, ERROR
    LOG_FILE_PATH = "logs/trading_bot.log"
    LOG_SIGNAL_DETAILS = True
    LOG_EXIT_DETAILS = True
    LOG_PNL_DETAILS = True
    
    # === SAFETY PARAMETERS ===
    # Kill switch: Stop trading if conditions met
    EMERGENCY_STOP_ENABLED = True
    EMERGENCY_STOP_LOSS_THRESHOLD = 0.25  # Stop if loss > 25%
    EMERGENCY_STOP_DAILY_LOSS = 1000.0  # Stop if daily loss > $1000
    
    # Pause signal generation if data quality poor
    PAUSE_IF_NO_DATA = True
    PAUSE_IF_HIGH_LATENCY = True
    MAX_LATENCY_MS = 5000  # Pause if latency > 5 seconds
    
    # === PERFORMANCE EXPECTATIONS ===
    TARGET_WIN_RATE = 0.546  # 54.6% from backtesting
    EXPECTED_PROFIT_FACTOR = 9.25
    ACCEPTABLE_WIN_RATE = 0.50  # Minimum acceptable WR
    ACCEPTABLE_DRAWDOWN = 0.02  # 2% max drawdown acceptable
    
    @classmethod
    def get_lot_size(cls, environment: str = None) -> float:
        """Get lot size for current environment"""
        env = environment or cls.ENVIRONMENT
        if env == "PAPER_TRADING":
            return cls.LOT_SIZE_BASE
        elif env == "LIVE_MICRO":
            return cls.LOT_SIZE_MICRO
        else:  # LIVE_FULL
            return cls.LOT_SIZE_STANDARD
    
    @classmethod
    def is_paper_trading(cls) -> bool:
        """Check if in paper trading mode"""
        return cls.ENVIRONMENT == "PAPER_TRADING"
    
    @classmethod
    def get_symbol_settings(cls, symbol: str) -> dict:
        """Get symbol-specific settings"""
        return cls.SYMBOL_SETTINGS.get(symbol, {
            'enabled': True,
            'lot_size_multiplier': 1.0,
            'max_positions': 1,
            'min_quality_threshold': 0.75,
        })

class PaperTradingConfig(DeploymentConfig):
    """Paper Trading specific configuration"""
    ENVIRONMENT = "PAPER_TRADING"
    LOT_SIZE_BASE = 0.1
    MAX_RISK_PER_TRADE = 100.0
    ENABLE_LIVE_MONITORING = True
    EMERGENCY_STOP_ENABLED = True
    
    @classmethod
    def get_description(cls) -> str:
        return """
        === PAPER TRADING CONFIGURATION ===
        Environment: Demo/Paper Trading
        Lot Size: 0.1 (small for validation)
        Risk/Trade: $100
        Daily Loss Limit: $500
        Duration: 1-2 weeks
        Goal: Validate 54.6% WR and advanced exits
        
        Once validated, upgrade to LIVE_MICRO for real money.
        """

class LiveMicroConfig(DeploymentConfig):
    """Live Micro Account configuration"""
    ENVIRONMENT = "LIVE_MICRO"
    LOT_SIZE_BASE = 0.5
    MAX_RISK_PER_TRADE = 25.0  # Smaller risk
    MAX_DAILY_LOSS = 250.0
    MAX_WEEKLY_LOSS = 1000.0
    ENABLE_LIVE_MONITORING = True
    EMERGENCY_STOP_ENABLED = True
    
    @classmethod
    def get_description(cls) -> str:
        return """
        === LIVE MICRO CONFIGURATION ===
        Environment: Live Trading - Micro Account
        Lot Size: 0.5 (real money)
        Risk/Trade: $25
        Daily Loss Limit: $250
        Duration: 2-4 weeks
        Goal: Test with real money at small scale
        
        Proceed to LIVE_FULL after 4 weeks of positive returns.
        """

class LiveFullConfig(DeploymentConfig):
    """Live Full Account configuration"""
    ENVIRONMENT = "LIVE_FULL"
    LOT_SIZE_BASE = 1.0
    MAX_RISK_PER_TRADE = 100.0
    MAX_DAILY_LOSS = 500.0
    MAX_WEEKLY_LOSS = 2500.0
    ENABLE_LIVE_MONITORING = True
    EMERGENCY_STOP_ENABLED = True
    
    @classmethod
    def get_description(cls) -> str:
        return """
        === LIVE FULL CONFIGURATION ===
        Environment: Live Trading - Full Account
        Lot Size: 1.0 (full position)
        Risk/Trade: $100
        Daily Loss Limit: $500
        Duration: Ongoing
        Goal: Normal trading operation
        
        Maintain daily monitoring and weekly reviews.
        """

# Default configuration
CURRENT_CONFIG = PaperTradingConfig

def print_config_info():
    """Print current configuration info"""
    config = CURRENT_CONFIG
    print(f"\n{'='*60}")
    print(f"Current Configuration: {config.ENVIRONMENT}")
    print(f"{'='*60}")
    print(f"Lot Size: {config.LOT_SIZE_BASE}")
    print(f"Risk/Trade: ${config.MAX_RISK_PER_TRADE}")
    print(f"Daily Loss Limit: ${config.MAX_DAILY_LOSS}")
    print(f"Max Drawdown: {config.MAX_DRAWDOWN_PERCENT}%")
    print(f"Enabled Symbols: {', '.join(config.ENABLED_SYMBOLS)}")
    print(f"Emergency Stop: {config.EMERGENCY_STOP_ENABLED}")
    print(f"\nTarget Metrics:")
    print(f"  Win Rate: {config.TARGET_WIN_RATE:.1%}")
    print(f"  Profit Factor: {config.EXPECTED_PROFIT_FACTOR}")
    print(f"  Max Drawdown: {config.ACCEPTABLE_DRAWDOWN:.1%}")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    print_config_info()
    print("\nAvailable configurations:")
    print("  - PaperTradingConfig (demo trading, 0.1 lot)")
    print("  - LiveMicroConfig (real money, 0.5 lot)")
    print("  - LiveFullConfig (real money, 1.0 lot)")
