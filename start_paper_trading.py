#!/usr/bin/env python3
"""
Paper Trading Launcher
Starts the bot in paper trading mode with safety limits and monitoring
"""

import asyncio
import sys
import logging
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from deployment_config import PaperTradingConfig, print_config_info
from src.bot_main import AIForexTradingBot

class PaperTradingLauncher:
    """Manages paper trading execution"""
    
    def __init__(self, config=None):
        self.config = config or PaperTradingConfig
        self.setup_logging()
        self.bot = None
        self.start_time = None
        self.stats = {
            'trades_executed': 0,
            'wins': 0,
            'losses': 0,
            'pnl': 0,
            'max_drawdown': 0,
            'session_pnl': 0,
        }
    
    def setup_logging(self):
        """Configure logging for paper trading"""
        log_dir = Path(self.config.LOG_FILE_PATH).parent
        log_dir.mkdir(exist_ok=True)
        
        logging.basicConfig(
            level=getattr(logging, self.config.LOG_LEVEL),
            format='%(asctime)s | [%(levelname)s] %(name)s | %(message)s',
            handlers=[
                logging.FileHandler(self.config.LOG_FILE_PATH),
                logging.StreamHandler()
            ]
        )
        
        self.logger = logging.getLogger(__name__)
        self.logger.info("=" * 70)
        self.logger.info("PAPER TRADING SESSION STARTED")
        self.logger.info("=" * 70)
    
    def validate_configuration(self) -> bool:
        """Validate configuration before starting"""
        self.logger.info("\n[VALIDATION] Checking configuration...")
        
        checks = {
            "Environment": self.config.ENVIRONMENT == "PAPER_TRADING",
            "Lot Size": self.config.LOT_SIZE_BASE > 0,
            "Risk Limit": self.config.MAX_RISK_PER_TRADE > 0,
            "Symbols": len(self.config.ENABLED_SYMBOLS) > 0,
            "Exit Strategies": self.config.EXIT_STRATEGIES is not None,
        }
        
        all_passed = True
        for check_name, result in checks.items():
            status = "✓" if result else "✗"
            self.logger.info(f"  {status} {check_name}")
            if not result:
                all_passed = False
        
        return all_passed
    
    def print_startup_summary(self):
        """Print startup information"""
        print("\n" + "=" * 70)
        print("PAPER TRADING CONFIGURATION")
        print("=" * 70)
        print(f"Environment:        {self.config.ENVIRONMENT}")
        print(f"Start Time:         {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print(f"Lot Size:           {self.config.LOT_SIZE_BASE}")
        print(f"Risk per Trade:     ${self.config.MAX_RISK_PER_TRADE}")
        print(f"Daily Loss Limit:   ${self.config.MAX_DAILY_LOSS}")
        print(f"Max Drawdown:       {self.config.MAX_DRAWDOWN_PERCENT}%")
        print(f"Symbols:            {', '.join(self.config.ENABLED_SYMBOLS)}")
        print(f"Monitoring:         {self.config.ENABLE_LIVE_MONITORING}")
        print(f"Emergency Stop:     {self.config.EMERGENCY_STOP_ENABLED}")
        print("\nTarget Metrics (from backtesting):")
        print(f"  Win Rate:         {self.config.TARGET_WIN_RATE:.1%}")
        print(f"  Profit Factor:    {self.config.EXPECTED_PROFIT_FACTOR}")
        print(f"  Max Drawdown:     {self.config.ACCEPTABLE_DRAWDOWN:.1%}")
        print("\nPhase Timeline:")
        print("  Week 1: Validation phase (0.1 lot, $100 risk/trade)")
        print("  If WR ≥ 52%: Continue")
        print("  Week 2: Extended validation")
        print("  If still profitable: Upgrade to LIVE_MICRO (0.5 lot)")
        print("\n" + "=" * 70 + "\n")
    
    async def start(self):
        """Start paper trading session"""
        try:
            self.start_time = datetime.now()
            
            # Print configuration
            print_config_info()
            self.print_startup_summary()
            
            # Validate
            if not self.validate_configuration():
                self.logger.error("Configuration validation failed")
                return False
            
            self.logger.info("\n[START] Initializing AI Forex Trading Bot...")
            
            # Initialize bot
            self.bot = AIForexTradingBot(
                symbols=self.config.ENABLED_SYMBOLS,
                verbose=True
            )
            
            self.logger.info("[START] Bot initialized successfully")
            self.logger.info(f"[START] Paper Trading session started at {self.start_time}")
            self.logger.info(f"[START] Monitoring enabled: {self.config.ENABLE_LIVE_MONITORING}")
            
            # Run bot
            await self.bot.run()
            
            return True
            
        except KeyboardInterrupt:
            self.logger.info("\n[STOP] Paper trading stopped by user (Ctrl+C)")
            await self.shutdown()
            return True
            
        except Exception as e:
            self.logger.error(f"[ERROR] Unexpected error: {str(e)}", exc_info=True)
            await self.shutdown()
            return False
    
    async def shutdown(self):
        """Graceful shutdown"""
        if self.bot:
            self.logger.info("[SHUTDOWN] Closing all open positions...")
            # Bot should have its own shutdown method
            if hasattr(self.bot, 'shutdown'):
                await self.bot.shutdown()
        
        elapsed = datetime.now() - self.start_time if self.start_time else None
        self.logger.info(f"[SHUTDOWN] Session ended at {datetime.now()}")
        if elapsed:
            self.logger.info(f"[SHUTDOWN] Session duration: {elapsed}")
        
        self.logger.info("=" * 70)
        self.logger.info("PAPER TRADING SESSION CLOSED")
        self.logger.info("=" * 70)

def main():
    """Main entry point"""
    print("\n" + "=" * 70)
    print("AI FOREX TRADING BOT - PAPER TRADING MODE")
    print("=" * 70)
    print(f"Version: 1.0.0")
    print(f"Mode: PAPER TRADING (Demo Account)")
    print(f"Start: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 70 + "\n")
    
    # Create launcher
    launcher = PaperTradingLauncher()
    
    # Run async bot
    try:
        asyncio.run(launcher.start())
    except Exception as e:
        print(f"[FATAL ERROR] {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
