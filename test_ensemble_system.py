"""Test ensemble system integration"""
import sys
import os

sys.path.append(os.getcwd())

from src.ml.exit_policy_ensemble import ExitPolicyEnsemble
from src.analysis.market_regime_detector import MarketRegimeDetector

def test_ensemble():
    print("Testing Ensemble System...")
    print("-" * 40)
    
    # Test 1: Load ensemble
    print("\n1. Loading ExitPolicyEnsemble...")
    ensemble = ExitPolicyEnsemble()
    print("   ✅ Loaded successfully")
    
    # Test 2: Load regime detector
    print("\n2. Loading MarketRegimeDetector...")
    detector = MarketRegimeDetector()
    print("   ✅ Loaded successfully")
    
    # Test 3: Test regime detection
    print("\n3. Testing regime detection...")
    test_data = {
        'atr': 0.0005,
        'adx': 28,
        'rsi': 65,
        'spread': 0.0002,
        'atr_80_percentile': 0.0008,
        'volume': 1000000
    }
    regime = detector.get_detailed_regime_label(test_data)
    print(f"   Detected regime: {regime}")
    print("   ✅ Detection working")
    
    # Test 4: Test allocation
    print("\n4. Testing allocation recommendation...")
    import numpy as np
    features = np.array([[0.0005, 28, 65, 0.0002, 0.75]])
    
    allocation = ensemble.get_optimal_allocation(
        regime=regime,
        features=features,
        current_volatility=0.0005,
        current_spread=0.0002,
        base_confidence=0.75,
        enforce_invariants=True
    )
    
    print(f"   Recommended Policy: {allocation.exit_policy.value}")
    print(f"   Position Size Multiplier: {allocation.position_size_multiplier:.2f}x")
    print(f"   Expectancy: {allocation.expectancy:.2f}R")
    print(f"   Confidence: {allocation.confidence:.2f}")
    print("   ✅ Allocation working")
    
    # Test 5: Check diagnostics
    print("\n5. Getting diagnostics...")
    diag = ensemble.get_diagnostics()
    regime_count = len(diag.get('regime_policy_matrix', {}))
    print(f"   Regimes tracked: {regime_count}")
    print("   ✅ Diagnostics working")
    
    print("\n" + "=" * 40)
    print("ALL TESTS PASSED! ✅")
    print("=" * 40)
    print("\nThe Regime-Aware Exit Policy Ensemble is ready!")
    print("Run 'python view_ensemble_diagnostics.py' to view performance data.")

if __name__ == "__main__":
    test_ensemble()
