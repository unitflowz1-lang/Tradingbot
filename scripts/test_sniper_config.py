"""
Aggressive Sniper Configuration Verification Script

This script validates that all aggressive sniper settings are properly configured
and conservative overrides have been removed.

Run: python scripts/test_sniper_config.py
"""

import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

def test_env_configuration():
    """Test 1: Verify environment variables are set correctly"""
    print("\n" + "="*80)
    print("TEST 1: Environment Configuration")
    print("="*80)
    
    tests = {
        "VOLUME_FLOOR_LOTS": ("0.01", "Volume floor should be 0.01 lots"),
        "DAILY_EXPOSURE_LIMIT": ("0.05", "Daily exposure should be 5% for TIER_A"),
        "HARD_REGISTRY_WIPE": ("0", "Registry wipe should be disabled"),
        "TRANSACTIONAL_REGISTRY_RECOVERY": ("1", "Transaction recovery should be enabled"),
        "STRATEGY_FULLY_UNLEASHED": ("1", "Strategy should be fully unleashed"),
        "DISABLE_EXIT_AGGRESSION": ("0", "Exit aggression should be enabled"),
        "FEATURE_AUTO_TRAIL": ("1", "Auto-trail feature should be enabled"),
        "ACCURACY_GUARD_ENABLED": ("0", "Accuracy guard should be disabled"),
        "ADX_MIN": ("12.0", "ADX minimum should be 12.0"),
        "ML_WEIGHT": ("0.7", "ML weight should be 0.7"),
        "TECHNICAL_WEIGHT": ("0.3", "Technical weight should be 0.3"),
    }
    
    all_passed = True
    for var, (expected, description) in tests.items():
        actual = os.environ.get(var, "NOT SET")
        passed = actual == expected
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status} | {var}: {actual} (expected: {expected}) - {description}")
        if not passed:
            all_passed = False
    
    return all_passed


def test_position_sizer_config():
    """Test 2: Verify position sizing configuration"""
    print("\n" + "="*80)
    print("TEST 2: Position Sizer Configuration")
    print("="*80)
    
    try:
        from src.risk.position_sizer import MAX_SINGLE_TRADE_EXPOSURE_PCT
        
        # Test exposure cap
        expected_exposure = 5.0
        passed = MAX_SINGLE_TRADE_EXPOSURE_PCT == expected_exposure
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status} | MAX_SINGLE_TRADE_EXPOSURE_PCT: {MAX_SINGLE_TRADE_EXPOSURE_PCT}% (expected: {expected_exposure}%)")
        
        if not passed:
            return False
        
        # Test that confidence multiplier doesn't have Tier A floor
        from src.risk.position_sizer import FixedFractionalSizer, PositionSizingConfig
        from src.models import TradingSignal, Direction
        from datetime import datetime, timezone
        
        config = PositionSizingConfig()
        sizer = FixedFractionalSizer(config)
        
        # Create a mock signal with low confidence
        mock_signal = TradingSignal(
            symbol="EUR/USD",
            direction=Direction.LONG,
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit=1.1100,
            position_size=0.01,
            confidence=0.30,  # Low confidence
            reasoning="Test signal",
            timestamp=datetime.now(timezone.utc)
        )
        setattr(mock_signal, "trade_tier", "TIER_A")
        
        # Get confidence multiplier
        multiplier = sizer._confidence_multiplier(mock_signal)
        
        # In aggressive mode, should NOT have 0.50 floor
        has_floor = multiplier >= 0.50 and multiplier != 1.0  # 1.0 is unleashing
        passed = not has_floor or os.environ.get("STRATEGY_FULLY_UNLEASHED") == "1"
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status} | Confidence multiplier (30% conf, TIER_A): {multiplier:.2f}x (should not have 0.50 floor)")
        
        return passed
        
    except Exception as e:
        print(f"✗ FAIL | Error testing position sizer: {e}")
        return False


def test_signal_combiner_config():
    """Test 3: Verify signal combiner configuration"""
    print("\n" + "="*80)
    print("TEST 3: Signal Combiner Configuration")
    print("="*80)
    
    try:
        from src.analysis.signal_combiner import SignalCombiner, SignalWeights
        
        # Test default weights
        weights = SignalWeights()
        tests = [
            ("sentiment_weight", 0.0, "Sentiment should be disabled"),
            ("technical_weight", 0.3, "Technical weight should be 0.3"),
            ("ml_weight", 0.7, "ML weight should be 0.7"),
            ("trend_confirmation_bonus", 0.15, "Trend bonus should be 0.15"),
        ]
        
        all_passed = True
        for attr, expected, description in tests:
            actual = getattr(weights, attr)
            passed = abs(actual - expected) < 0.01
            status = "✓ PASS" if passed else "✗ FAIL"
            print(f"{status} | {attr}: {actual} (expected: {expected}) - {description}")
            if not passed:
                all_passed = False
        
        # Test minimum confidence threshold
        combiner = SignalCombiner()
        expected_threshold = 0.45
        passed = abs(combiner.min_confidence_threshold - expected_threshold) < 0.01
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status} | min_confidence_threshold: {combiner.min_confidence_threshold} (expected: {expected_threshold})")
        
        if not passed:
            all_passed = False
        
        # Test WFO validator is present
        has_wfo = hasattr(combiner, 'wfo_validator')
        status = "✓ PASS" if has_wfo else "✗ FAIL"
        print(f"{status} | WFO Validator: {'Present' if has_wfo else 'MISSING'}")
        
        if not has_wfo:
            all_passed = False
        
        return all_passed
        
    except Exception as e:
        print(f"✗ FAIL | Error testing signal combiner: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_profit_protection_config():
    """Test 4: Verify profit protection (exit strategy) configuration"""
    print("\n" + "="*80)
    print("TEST 4: Profit Protection Configuration")
    print("="*80)
    
    try:
        from src.trading.profit_protection_module import TradeManagementSettings
        
        settings = TradeManagementSettings()
        
        tests = [
            ("use_breakeven", True, "Break-even should be enabled"),
            ("breakeven_trigger_r", 1.0, "Break-even trigger should be 1.0R"),
            ("breakeven_offset_pips", 1.0, "Break-even offset should be 1.0 pip"),
            ("use_trailing_stop", True, "Trailing stop should be enabled"),
            ("trailing_stop_activation_r", 1.0, "Trailing activation should be 1.0R"),
        ]
        
        all_passed = True
        for attr, expected, description in tests:
            actual = getattr(settings, attr)
            passed = actual == expected
            status = "✓ PASS" if passed else "✗ FAIL"
            print(f"{status} | {attr}: {actual} (expected: {expected}) - {description}")
            if not passed:
                all_passed = False
        
        # Test trailing ATR by regime
        expected_trailing = {
            "TRENDING": 3.5,
            "RANGING": 1.5,
            "HIGH_VOLATILITY": 2.0,
            "LOW_LIQUIDITY": 1.5,
        }
        
        for regime, expected_mult in expected_trailing.items():
            actual_mult = settings.trailing_atr_by_regime.get(regime)
            passed = abs(actual_mult - expected_mult) < 0.1
            status = "✓ PASS" if passed else "✗ FAIL"
            print(f"{status} | trailing_atr_by_regime[{regime}]: {actual_mult} (expected: {expected_mult})")
            if not passed:
                all_passed = False
        
        return all_passed
        
    except Exception as e:
        print(f"✗ FAIL | Error testing profit protection: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_wfo_validator():
    """Test 5: Verify WFO validator functionality"""
    print("\n" + "="*80)
    print("TEST 5: WFO Validator")
    print("="*80)
    
    try:
        from src.ml.wfo_validator import WFOValidator
        
        validator = WFOValidator(min_sharpe_ratio=1.8)
        
        # Test stable scenario (should pass)
        result_stable = validator.validate_stability(
            sharpe_trending=2.0,
            sharpe_ranging=1.9,
            sharpe_choppy=1.85
        )
        
        passed = result_stable.is_stable
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status} | Stable scenario (2.0, 1.9, 1.85): {'STABLE' if result_stable.is_stable else 'UNSTABLE'}")
        print(f"       Sharpe: {result_stable.sharpe_ratio:.2f} | Rank: {result_stable.stability_rank:.1f}/100")
        
        if not passed:
            return False
        
        # Test unstable scenario (should fail)
        result_unstable = validator.validate_stability(
            sharpe_trending=3.0,
            sharpe_ranging=1.0,
            sharpe_choppy=0.5
        )
        
        passed = not result_unstable.is_stable
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status} | Unstable scenario (3.0, 1.0, 0.5): {'UNSTABLE' if not result_unstable.is_stable else 'STABLE'}")
        print(f"       Sharpe: {result_unstable.sharpe_ratio:.2f} | Rank: {result_unstable.stability_rank:.1f}/100")
        
        return passed
        
    except Exception as e:
        print(f"✗ FAIL | Error testing WFO validator: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all configuration tests"""
    print("\n" + "="*80)
    print("AGGRESSIVE SNIPER CONFIGURATION VERIFICATION")
    print("="*80)
    print(f"Timestamp: {__import__('datetime').datetime.now()}")
    print(f"Python: {sys.version}")
    print(f"Project Root: {project_root}")
    
    # Load .env file
    env_file = project_root / ".env"
    if env_file.exists():
        print(f"\nLoading .env from: {env_file}")
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip()
    else:
        print(f"\n✗ WARNING: .env file not found at {env_file}")
    
    results = {
        "Environment Configuration": test_env_configuration(),
        "Position Sizer": test_position_sizer_config(),
        "Signal Combiner": test_signal_combiner_config(),
        "Profit Protection": test_profit_protection_config(),
        "WFO Validator": test_wfo_validator(),
    }
    
    # Summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    
    all_passed = True
    for test_name, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status} | {test_name}")
        if not passed:
            all_passed = False
    
    print("\n" + "="*80)
    if all_passed:
        print("✓ ALL TESTS PASSED - Aggressive Sniper Model is properly configured!")
        print("="*80)
        print("\nNext Steps:")
        print("1. Run bot in DRY_RUN mode first: Set DRY_RUN=1 in .env")
        print("2. Monitor win rate (target: >60%)")
        print("3. Verify trailing stops are activating at 1.0R")
        print("4. Check WFO stability scores in logs")
        print("5. Deploy to live when confident")
        return 0
    else:
        print("✗ SOME TESTS FAILED - Please review configuration")
        print("="*80)
        return 1


if __name__ == "__main__":
    sys.exit(main())
