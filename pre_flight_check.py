"""
Pre-Flight Check Script
Validates environment, dependencies, and configuration before bot startup.
"""

import os
import sys
import yaml
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


class PreFlightCheck:
    """Comprehensive pre-flight validation for the trading bot."""

    def __init__(self):
        self.base_path = Path(__file__).parent
        self.checks_passed = 0
        self.checks_failed = 0
        self.critical_errors = []

    def run_all_checks(self):
        """Run all pre-flight checks."""
        logger.info("=" * 80)
        logger.info("PRE-FLIGHT CHECK: Trading Bot Startup Validation")
        logger.info("=" * 80)

        # Critical checks (must pass)
        logger.info("\n[CRITICAL CHECKS]")
        self._check_config_yaml()
        self._check_models_directory()
        self._check_mt5_terminal()
        self._check_dependencies()

        # Strategy checks
        logger.info("\n[STRATEGY CHECKS]")
        self._check_strategies()

        # Configuration validation
        logger.info("\n[CONFIGURATION VALIDATION]")
        self._check_broker_config()
        self._check_trading_pairs()

        # Summary
        self._print_summary()

        return len(self.critical_errors) == 0

    def _check_config_yaml(self):
        """Validate config.yaml syntax and content."""
        logger.info("Checking config.yaml...")

        config_path = self.base_path / "config.yaml"

        # Check file exists
        if not config_path.exists():
            self._fail_critical("config.yaml not found at " + str(config_path))
            return

        # Check YAML syntax
        try:
            with open(config_path, 'r') as f:
                content = f.read()

                # Check for invalid docstring at start
                if content.strip().startswith('"""'):
                    self._fail_critical("config.yaml starts with Python docstring. Remove lines 1-4.")
                    return

                # Parse YAML
                config = yaml.safe_load(content)

                if config is None:
                    self._fail_critical("config.yaml is empty or invalid")
                    return

                logger.info("  ✓ config.yaml syntax valid")
                logger.info(f"  ✓ App name: {config.get('app_name', 'UNKNOWN')}")
                logger.info(f"  ✓ Version: {config.get('version', 'UNKNOWN')}")
                self.checks_passed += 1

        except yaml.YAMLError as e:
            self._fail_critical(f"YAML parsing error: {str(e)[:100]}")
        except Exception as e:
            self._fail_critical(f"Config file error: {str(e)}")

    def _check_models_directory(self):
        """Verify models directory and required model files."""
        logger.info("Checking models directory...")

        models_path = self.base_path / "models"

        if not models_path.exists():
            logger.warning(f"  ⚠ models/ directory not found at {models_path}")
            logger.info("    Creating directory...")
            models_path.mkdir(parents=True, exist_ok=True)
            logger.info("  ✓ models/ directory created")

        # Check for model files
        model_file = models_path / "xgboost_latest.pkl"

        if model_file.exists():
            file_size = model_file.stat().st_size
            logger.info(f"  ✓ Found xgboost_latest.pkl ({file_size} bytes)")
            self.checks_passed += 1
        else:
            logger.warning(f"  ⚠ xgboost_latest.pkl not found")
            logger.info("    This is OK for first run - model will be trained")

    def _check_mt5_terminal(self):
        """Check if MetaTrader5 terminal is accessible."""
        logger.info("Checking MT5 Terminal...")

        try:
            import MetaTrader5 as mt5

            # Try to initialize
            result = mt5.initialize()

            if result:
                logger.info("  ✓ MT5 initialized successfully")

                # Get account info
                account = mt5.account_info()
                if account:
                    logger.info(f"  ✓ MT5 Account: {account.login}")
                    logger.info(f"  ✓ Balance: {account.balance}")
                    logger.info(f"  ✓ Equity: {account.equity}")

                # Check EURUSD
                eurusd = mt5.symbol_info("EURUSD")
                if eurusd:
                    logger.info(f"  ✓ EURUSD available (stops_level: {eurusd.trade_stops_level})")
                else:
                    logger.warning("  ⚠ EURUSD not found (add to Market Watch)")

                mt5.shutdown()
                self.checks_passed += 1

            else:
                self._fail_critical("MT5 initialization failed. Check if Terminal is running.")

        except ImportError:
            self._fail_critical("MetaTrader5 module not installed. Run: pip install MetaTrader5")
        except Exception as e:
            self._fail_critical(f"MT5 error: {str(e)}")

    def _check_dependencies(self):
        """Verify all required Python packages are installed."""
        logger.info("Checking Python dependencies...")

        required_packages = {
            'pandas': 'pandas',
            'numpy': 'numpy',
            'yaml': 'PyYAML',
            'asyncio': 'asyncio (built-in)',
            'logging': 'logging (built-in)',
        }

        missing = []

        for import_name, display_name in required_packages.items():
            try:
                __import__(import_name)
                logger.info(f"  ✓ {display_name}")
            except ImportError:
                logger.warning(f"  ✗ {display_name} NOT FOUND")
                missing.append(display_name)

        if missing:
            logger.warning(f"\n  Missing packages: {', '.join(missing)}")
            logger.info("  Install with: pip install -r requirements.txt")
        else:
            logger.info("  ✓ All dependencies installed")
            self.checks_passed += 1

    def _check_strategies(self):
        """Verify strategies are defined and importable."""
        logger.info("Checking strategies...")

        strategies_to_check = [
            "sma_crossover",
            "mean_reversion",
            "breakout"
        ]

        found_strategies = []

        try:
            # Try importing from strategies module
            strategies_path = self.base_path / "strategies"

            for strategy_name in strategies_to_check:
                strategy_file = strategies_path / f"{strategy_name}.py"

                if strategy_file.exists():
                    logger.info(f"  ✓ {strategy_name} defined")
                    found_strategies.append(strategy_name)
                else:
                    logger.warning(f"  ⚠ {strategy_name} not found at {strategy_file}")

            if found_strategies:
                logger.info(f"  ✓ Found {len(found_strategies)} strategies")
                self.checks_passed += 1

        except Exception as e:
            logger.warning(f"  Strategy check error: {str(e)}")

    def _check_broker_config(self):
        """Validate broker configuration."""
        logger.info("Checking broker configuration...")

        config_path = self.base_path / "config.yaml"

        try:
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)

            broker_config = config.get('broker', {})

            broker_type = broker_config.get('broker', 'unknown')
            logger.info(f"  ✓ Broker type: {broker_type}")

            login = broker_config.get('login')
            if login and login != 123456789:
                logger.info(f"  ✓ MT5 Login: {login}")
            else:
                logger.warning("  ⚠ MT5 Login is default (123456789) - Update in config.yaml")

            password = broker_config.get('password')
            if password and password != "your_password":
                logger.info("  ✓ Password configured")
            else:
                logger.warning("  ⚠ Password is default - Update in config.yaml")

            server = broker_config.get('server')
            logger.info(f"  ✓ Server: {server}")

            self.checks_passed += 1

        except Exception as e:
            logger.warning(f"  Broker config error: {str(e)}")

    def _check_trading_pairs(self):
        """Validate trading pairs configuration."""
        logger.info("Checking trading pairs...")

        config_path = self.base_path / "config.yaml"

        try:
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)

            pairs = config.get('data', {}).get('pairs', [])

            if pairs:
                logger.info(f"  ✓ Configured pairs: {', '.join(pairs)}")
                self.checks_passed += 1
            else:
                logger.warning("  ⚠ No trading pairs configured")

        except Exception as e:
            logger.warning(f"  Pairs config error: {str(e)}")

    def _fail_critical(self, message):
        """Record a critical failure."""
        logger.error(f"  ✗ {message}")
        self.checks_failed += 1
        self.critical_errors.append(message)

    def _print_summary(self):
        """Print final summary."""
        logger.info("\n" + "=" * 80)
        logger.info("PRE-FLIGHT CHECK SUMMARY")
        logger.info("=" * 80)

        logger.info(f"Checks Passed:  {self.checks_passed}")
        logger.info(f"Checks Failed:  {self.checks_failed}")

        if self.critical_errors:
            logger.error("\n[CRITICAL ERRORS - BOT CANNOT START]")
            for i, error in enumerate(self.critical_errors, 1):
                logger.error(f"  {i}. {error}")

            logger.error("\n[ACTION REQUIRED]")
            logger.error("Fix the critical errors above and run this check again.")

        else:
            logger.info("\n✅ ALL CHECKS PASSED - BOT READY FOR STARTUP")

        logger.info("=" * 80)


if __name__ == "__main__":
    check = PreFlightCheck()
    success = check.run_all_checks()

    # Exit with appropriate code
    sys.exit(0 if success else 1)
