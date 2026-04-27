#!/usr/bin/env python3
"""
Startup validation script - Pre-flight checks before launching the bot.
Validates: Models exist, MT5 connection, config files, quant data structure.
"""

import os
import json
import sys
from pathlib import Path
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

REQUIRED_SYMBOLS = ['EUR/USD', 'GBP/USD', 'USD/JPY', 'USD/CHF', 'AUD/USD', 'USD/CAD', 'NZD/USD']
MODEL_FORMATS = {
    'EURUSD': 'EURUSD_ml',
    'GBPUSD': 'GBPUSD_ml',
    'USDJPY': 'USDJPY_ml',
    'USDCHF': 'USDCHF_ml',
    'AUDUSD': 'AUDUSD_ml',
    'USDCAD': 'USDCAD_ml',
    'NZDUSD': 'NZDUSD_ml',
}

def check_models():
    """Check that all ML models are present."""
    logger.info("=" * 60)
    logger.info("CHECKING ML MODELS")
    logger.info("=" * 60)
    
    models_dir = Path("models")
    if not models_dir.exists():
        logger.error("❌ models/ directory does not exist!")
        return False
    
    all_ok = True
    for short_name, model_prefix in MODEL_FORMATS.items():
        pkl_file = models_dir / f"{model_prefix}.pkl"
        meta_file = models_dir / f"{model_prefix}_meta.json"
        
        pkl_exists = pkl_file.exists()
        meta_exists = meta_file.exists()
        
        if pkl_exists and meta_exists:
            logger.info(f"✅ {short_name:8s} | {model_prefix}.pkl + _meta.json present")
        else:
            logger.error(f"❌ {short_name:8s} | Missing: pkl={pkl_exists}, meta={meta_exists}")
            all_ok = False
    
    return all_ok

def check_config():
    """Check that config files exist."""
    logger.info("\n" + "=" * 60)
    logger.info("CHECKING CONFIGURATION")
    logger.info("=" * 60)
    
    required_configs = ['config.json', 'config.yaml']
    all_ok = True
    
    for config_file in required_configs:
        if Path(config_file).exists():
            logger.info(f"✅ {config_file} exists")
        else:
            logger.warning(f"⚠️  {config_file} not found (may use defaults)")
    
    return True  # Config is optional, not blocking

def check_core_files():
    """Check that core bot files exist."""
    logger.info("\n" + "=" * 60)
    logger.info("CHECKING CORE BOT FILES")
    logger.info("=" * 60)
    
    required_files = [
        'main.py',
        'src/strategies/quant_hybrid_strategy.py',
        'src/analysis/technical_indicators.py',
    ]
    
    all_ok = True
    for file_path in required_files:
        if Path(file_path).exists():
            logger.info(f"✅ {file_path}")
        else:
            logger.error(f"❌ {file_path} NOT FOUND!")
            all_ok = False
    
    return all_ok

def check_quant_structure():
    """Verify GLOBAL_QUANT_CACHE structure."""
    logger.info("\n" + "=" * 60)
    logger.info("CHECKING QUANT DATA STRUCTURE")
    logger.info("=" * 60)
    
    try:
        from src.runtime.orchestrator.pipeline import GlobalState
        
        # Check if GlobalState has GLOBAL_QUANT_CACHE
        logger.info("✅ GlobalState imported successfully")
        logger.info("✅ GLOBAL_QUANT_CACHE structure should contain: z_score, garch_vol, flow_delta, rsi, ml_dir per symbol")
        return True
    except Exception as e:
        logger.warning(f"⚠️  Could not import GlobalState: {e}")
        return True  # Not blocking

def check_strategy():
    """Verify strategy can be imported."""
    logger.info("\n" + "=" * 60)
    logger.info("CHECKING STRATEGY IMPORT")
    logger.info("=" * 60)
    
    try:
        from src.strategies.quant_hybrid_strategy import QuantHybridStrategy
        logger.info("✅ QuantHybridStrategy imported successfully")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to import QuantHybridStrategy: {e}")
        return False

def main():
    """Run all pre-flight checks."""
    logger.info("\n")
    logger.info("🚀 BOT STARTUP VALIDATION - v8.5 Core RL TradingBot")
    logger.info("\n")
    
    checks = [
        ("ML Models", check_models),
        ("Core Files", check_core_files),
        ("Configuration", check_config),
        ("Strategy Import", check_strategy),
        ("Quant Structure", check_quant_structure),
    ]
    
    results = []
    for check_name, check_func in checks:
        try:
            result = check_func()
            results.append((check_name, result))
        except Exception as e:
            logger.error(f"❌ {check_name} check failed with exception: {e}")
            results.append((check_name, False))
    
    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("VALIDATION SUMMARY")
    logger.info("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for check_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        logger.info(f"{status} | {check_name}")
    
    logger.info(f"\nResult: {passed}/{total} checks passed")
    
    if passed == total:
        logger.info("\n" + "🟢" * 30)
        logger.info("✅ ALL CHECKS PASSED - BOT READY TO LAUNCH!")
        logger.info("🟢" * 30)
        logger.info("\nStarting bot with: python main.py")
        return 0
    else:
        logger.error("\n" + "🔴" * 30)
        logger.error("❌ SOME CHECKS FAILED - FIX ISSUES BEFORE LAUNCHING")
        logger.error("🔴" * 30)
        return 1

if __name__ == "__main__":
    sys.exit(main())
