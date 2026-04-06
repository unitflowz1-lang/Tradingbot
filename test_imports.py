#!/usr/bin/env python3
"""
Quick import test to verify all modules can be imported
"""
import sys
import os

os.chdir("c:\\Users\\macki\\Desktop\\TradingBot")
sys.path.insert(0, "c:\\Users\\macki\\Desktop\\TradingBot")

try:
    print("Testing imports...")
    
    print("  Importing config...", end=" ")
    from src.config import ConfigManager
    print("✓")
    
    print("  Importing MT5 broker...", end=" ")
    from src.data.mt5_broker import create_mt5_broker, MT5BrokerInterface
    print("✓")
    
    print("  Importing execution engine...", end=" ")
    from src.trading.execution_engine import ExecutionEngine
    print("✓")
    
    print("  Importing position manager...", end=" ")
    from src.trading.position_manager import PositionManager
    print("✓")
    
    print("  Importing strategy...", end=" ")
    from src.strategies.trend_strategy import SimpleTrendStrategy
    print("✓")
    
    print("  Importing risk calculator...", end=" ")
    from src.risk.risk_calculator import RiskCalculator, RiskConfig
    print("✓")
    
    print("  Importing SL/TP calculator...", end=" ")
    from src.risk.sl_tp_calculator import StopLossTakeProfitCalculator
    print("✓")
    
    print("  Importing health checker...", end=" ")
    from src.health_check import HealthChecker
    print("✓")
    
    print("\n✅ All imports successful!")
    print("\nNext steps:")
    print("  1. Set environment variables:")
    print("     set MT5_LOGIN=your_login")
    print("     set MT5_PASSWORD=your_password")
    print("     set MT5_SERVER=your_server")
    print("  2. Run: python main.py")
    
except Exception as e:
    print(f"\n❌ Import failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
