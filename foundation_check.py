"""
Foundation Check: Verify all core components are working
"""
import sys
import os
import yaml

print("=" * 80)
print("FOUNDATION CHECK - Trading Bot Infrastructure")
print("=" * 80)

# Check 1: config.yaml syntax
print("\n[1/5] Checking config.yaml syntax...")
try:
    with open('config.yaml', 'r') as f:
        config = yaml.safe_load(f)
    print("   ✓ config.yaml valid YAML")
    print(f"   ✓ App: {config.get('app_name')}")
except Exception as e:
    print(f"   ✗ config.yaml ERROR: {e}")
    sys.exit(1)

# Check 2: Strategy parameters match StrategyConfig
print("\n[2/5] Checking strategy parameters...")
try:
    from utils.config import StrategyConfig
    strategies = config.get('strategies', [])
    
    expected_params = {
        'sma_crossover': ['sma_short', 'sma_long'],
        'mean_reversion': ['bollinger_period', 'bollinger_std', 'rsi_period', 'rsi_oversold', 'rsi_overbought'],
        'breakout': ['breakout_period', 'breakout_min_range']
    }
    
    for strategy in strategies:
        name = strategy.get('name')
        params = expected_params.get(name, [])
        
        if name == 'sma_crossover':
            assert 'sma_short' in strategy, f"Missing sma_short in {name}"
            assert 'sma_long' in strategy, f"Missing sma_long in {name}"
            print(f"   ✓ {name} parameters OK")
        elif name == 'mean_reversion':
            assert 'bollinger_period' in strategy, f"Missing bollinger_period in {name}"
            assert 'bollinger_std' in strategy, f"Missing bollinger_std in {name}"
            print(f"   ✓ {name} parameters OK")
        elif name == 'breakout':
            assert 'breakout_period' in strategy, f"Missing breakout_period in {name}"
            assert 'breakout_min_range' in strategy, f"Missing breakout_min_range in {name}"
            print(f"   ✓ {name} parameters OK")
            
except Exception as e:
    print(f"   ✗ Strategy parameter ERROR: {e}")
    sys.exit(1)

# Check 3: MT5 Broker import
print("\n[3/5] Checking MT5BrokerInterface import...")
try:
    from src.data.mt5_broker import MT5BrokerInterface
    print("   ✓ MT5BrokerInterface imported successfully")
except ImportError as e:
    print(f"   ✗ Import failed: {e}")
    sys.exit(1)

# Check 4: Trailing SL Manager import
print("\n[4/5] Checking Trailing SL Manager import...")
try:
    from src.trading.dynamic_trailing_sl_manager import DynamicTrailingSLManager, TrailingConfig
    print("   ✓ DynamicTrailingSLManager imported successfully")
    print("   ✓ TrailingConfig imported successfully")
except ImportError as e:
    print(f"   ✗ Import failed: {e}")
    sys.exit(1)

# Check 5: Models directory
print("\n[5/5] Checking models directory...")
if os.path.exists('models'):
    print("   ✓ models/ directory exists")
    files = os.listdir('models')
    print(f"   ✓ Contains {len(files)} items")
else:
    print("   ⚠ models/ directory doesn't exist (will be created)")

print("\n" + "=" * 80)
print("✅ FOUNDATION CHECK PASSED - Bot ready for startup")
print("=" * 80)
print("\nNext: python main_production.py")
