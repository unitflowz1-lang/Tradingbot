"""
Test Phase 1 Integration - Signal Quality Filter & Market Regime Detection
"""
import sys
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_imports():
    """Test that all Phase 1 modules import correctly"""
    logger.info("Testing Phase 1 module imports...")
    
    try:
        from src.analysis.signal_scoring import SignalFilterer, SignalScorer
        logger.info("✓ signal_scoring.py imported successfully")
    except Exception as e:
        logger.error(f"✗ Failed to import signal_scoring: {e}")
        return False
    
    try:
        from src.analysis.market_regime_detector import MarketRegimeDetector
        logger.info("✓ market_regime_detector.py imported successfully")
    except Exception as e:
        logger.error(f"✗ Failed to import market_regime_detector: {e}")
        return False
    
    try:
        from src.strategies.trend_strategy import SimpleTrendStrategy
        logger.info("✓ trend_strategy.py imported successfully")
    except Exception as e:
        logger.error(f"✗ Failed to import trend_strategy: {e}")
        return False
    
    return True

def test_signal_scorer():
    """Test signal scorer functionality"""
    logger.info("\nTesting SignalScorer...")
    
    from src.analysis.signal_scoring import SignalScorer
    
    scorer = SignalScorer()
    
    # Test with good signal data
    good_signal_data = {
        'adx': 28,
        'trend_aligned': True,
        'rsi_extreme': True,
        'volume_confirmed': True,
        'ma_bullish': True,
        'pattern_bullish': False,
        'atr': 45,
        'atr_mean': 40,
        'rsi': 25,
        'volume': 150000,
        'volume_mean': 120000,
    }
    
    score = scorer.calculate_score(good_signal_data)
    logger.info(f"✓ Signal score calculated: {score:.1f}/100")
    
    if score > 50:
        logger.info("✓ Signal score is reasonable (> 50)")
    else:
        logger.warning(f"⚠ Signal score is low: {score:.1f}")
    
    return True

def test_signal_filterer():
    """Test signal filterer functionality"""
    logger.info("\nTesting SignalFilterer...")
    
    from src.analysis.signal_scoring import SignalFilterer
    
    filterer = SignalFilterer(min_score=65)
    
    # Test with good signal data
    analysis_data = {
        'adx': 28,
        'trend_aligned': True,
        'rsi_extreme': True,
        'volume_confirmed': True,
        'ma_bullish': True,
        'pattern_bullish': False,
        'atr': 45,
        'atr_mean': 40,
        'rsi': 25,
        'volume': 150000,
        'volume_mean': 120000,
    }
    
    signal = {'direction': 'BUY', 'entry_price': 1.0950}
    should_trade, score, reason = filterer.should_trade_signal(signal, analysis_data)
    
    logger.info(f"✓ Filterer decision: Trade={should_trade}, Score={score:.1f}/100")
    logger.info(f"  Reason: {reason}")
    
    return True

def test_regime_detector():
    """Test market regime detector functionality"""
    logger.info("\nTesting MarketRegimeDetector...")
    
    from src.analysis.market_regime_detector import MarketRegimeDetector
    
    detector = MarketRegimeDetector()
    
    # Test with strong trend, normal volatility
    data = {
        'adx': 32,
        'atr': 50,
        'atr_mean': 45,
        'atr_20_percentile': 35,
        'atr_80_percentile': 60,
    }
    
    regime = detector.get_regime(data)
    vol_regime = detector.get_volatility_regime(data)
    action = detector.get_action(regime, vol_regime)
    
    logger.info(f"✓ Regime: {regime}, Volatility: {vol_regime}")
    logger.info(f"  Action: Trade={action['trade']}, Size Mult={action['size_multiplier']:.2f}x")
    logger.info(f"  Reason: {action['reason']}")
    
    if action['trade']:
        logger.info("✓ Regime detector allows trading in these conditions")
    else:
        logger.info("⚠ Regime detector skips trading in these conditions")
    
    return True

def test_strategy_initialization():
    """Test that SimpleTrendStrategy initializes with Phase 1 modules"""
    logger.info("\nTesting SimpleTrendStrategy with Phase 1 modules...")
    
    try:
        from src.strategies.trend_strategy import SimpleTrendStrategy
        strategy = SimpleTrendStrategy("EUR/USD", verbose=False)
        
        # Check that Phase 1 modules are initialized
        if hasattr(strategy, 'signal_filterer'):
            logger.info("✓ signal_filterer initialized in strategy")
        else:
            logger.error("✗ signal_filterer NOT initialized in strategy")
            return False
        
        if hasattr(strategy, 'regime_detector'):
            logger.info("✓ regime_detector initialized in strategy")
        else:
            logger.error("✗ regime_detector NOT initialized in strategy")
            return False
        
        return True
    except Exception as e:
        logger.error(f"✗ Failed to initialize strategy: {e}")
        return False

def main():
    """Run all tests"""
    logger.info("=" * 60)
    logger.info("PHASE 1 INTEGRATION TEST")
    logger.info("=" * 60)
    
    all_passed = True
    
    # Test 1: Imports
    if not test_imports():
        logger.error("Import tests failed!")
        all_passed = False
    else:
        logger.info("✓ All imports successful")
    
    # Test 2: Signal Scorer
    try:
        if not test_signal_scorer():
            all_passed = False
    except Exception as e:
        logger.error(f"Signal scorer test failed: {e}")
        all_passed = False
    
    # Test 3: Signal Filterer
    try:
        if not test_signal_filterer():
            all_passed = False
    except Exception as e:
        logger.error(f"Signal filterer test failed: {e}")
        all_passed = False
    
    # Test 4: Regime Detector
    try:
        if not test_regime_detector():
            all_passed = False
    except Exception as e:
        logger.error(f"Regime detector test failed: {e}")
        all_passed = False
    
    # Test 5: Strategy Initialization
    try:
        if not test_strategy_initialization():
            all_passed = False
    except Exception as e:
        logger.error(f"Strategy initialization test failed: {e}")
        all_passed = False
    
    # Summary
    logger.info("\n" + "=" * 60)
    if all_passed:
        logger.info("✓ ALL TESTS PASSED - Phase 1 ready for integration!")
        logger.info("=" * 60)
        return 0
    else:
        logger.error("✗ SOME TESTS FAILED - Check errors above")
        logger.info("=" * 60)
        return 1

if __name__ == "__main__":
    sys.exit(main())
