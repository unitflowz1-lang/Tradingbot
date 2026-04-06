"""
Phase 3 Integration Tests - Exit Optimization
Tests all 4 Phase 3 components (Multi-Level, Reversal, Mode, Breakout)
"""

import sys
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(message)s', datefmt='%H:%M:%S')
logger = logging.getLogger(__name__)


def test_multi_level_profit_taker():
    """Test MultiLevelProfitTaker functionality"""
    logger.info("\n" + "="*60)
    logger.info("TEST 1: Multi-Level Profit Taker")
    logger.info("="*60)
    
    from src.exit.multi_level_profit_taker import (
        MultiLevelProfitTaker,
        ProfitLevel,
        MultiLevelConfig,
    )
    
    config = MultiLevelConfig(
        levels=[
            ProfitLevel(0.5, 20, "Quick Profit"),
            ProfitLevel(1.0, 35, "Half Position"),
            ProfitLevel(1.5, 30, "Lock Gains"),
            ProfitLevel(2.0, 0, "Trail Rest"),
        ]
    )
    
    taker = MultiLevelProfitTaker(config)
    
    # Test 1a: No profit yet
    level, pct = taker.should_take_profit(
        current_price=1.0950,  # At entry
        entry_price=1.0950,
        stop_loss=1.0850,
    )
    assert level is None, "Should not trigger at entry price"
    logger.info("[PASS] Test 1a: No profit yet (correctly blocked)")
    
    # Test 1b: First level (0.5R)
    # Risk = 1.0950 - 1.0850 = 0.0100 (100 pips)
    # 0.5R = 0.0100 * 0.5 = 0.0050 (50 pips)
    # Price at 0.5R = 1.0950 + 0.0050 = 1.1000
    
    level, pct = taker.should_take_profit(
        current_price=1.1000,  # At 0.5R (50 pips up)
        entry_price=1.0950,
        stop_loss=1.0850,
    )
    assert level is not None, "Should trigger at 0.5R"
    assert level.profit_target == 0.5, "Should be 0.5R level"
    assert pct == 20, "Should exit 20%"
    logger.info(f"[PASS] Test 1b: Level 1 triggered at 0.5R (exit 20%)")
    
    # Test 1c: Second level (1.0R)
    level, pct = taker.should_take_profit(
        current_price=1.1050,  # +100 pips = +1.0R (entry 1.0950 + 0.01)
        entry_price=1.0950,
        stop_loss=1.0850,
    )
    assert level is not None, "Should trigger at 1.0R"
    assert level.profit_target == 1.0, "Should be 1.0R level"
    assert pct == 35, "Should exit 35%"
    logger.info(f"[PASS] Test 1c: Level 2 triggered at 1.0R (exit 35%)")
    
    # Test 1d: Remaining position (after 2 levels: 20% + 35% = 55% exited, 45% remains)
    remaining = taker.get_remaining_position()
    assert remaining == 45, f"Should have 45% remaining after 2 levels, got {remaining}%"
    logger.info(f"[PASS] Test 1d: Remaining position = {remaining}% after levels 1 & 2")
    
    # Test 1e: Summary
    summary = taker.summary()
    assert "45%" in summary, "Summary should show remaining %"
    logger.info(f"[PASS] Test 1e: Summary generated")
    
    return True


def test_reversal_exit_detector():
    """Test ReversalExitDetector functionality"""
    logger.info("\n" + "="*60)
    logger.info("TEST 2: Reversal Exit Detector")
    logger.info("="*60)
    
    from src.exit.reversal_exit_detector import (
        ReversalExitDetector,
        ReversalExitConfig,
        ReversalType,
    )
    
    # Test config initialization
    config = ReversalExitConfig(
        enable_3candle_reversal=True,
        enable_opposite_signal=True,
        enable_rsi_divergence=True,
        enable_price_action=True,
        enable_momentum_loss=True,
    )
    
    detector = ReversalExitDetector(config)
    logger.info(f"[PASS] Test 2a: ReversalExitDetector initialized with all detections enabled")
    
    # Test that detector has all required methods
    assert hasattr(detector, 'should_exit_on_reversal'), "Should have should_exit_on_reversal method"
    assert hasattr(detector, 'detect_3candle_reversal'), "Should have detect_3candle_reversal method"
    assert hasattr(detector, 'detect_rsi_divergence'), "Should have detect_rsi_divergence method"
    logger.info(f"[PASS] Test 2b: All required methods exist")
    
    # Test ReversalType enum
    assert ReversalType.THREE_CANDLE_REVERSAL.value == "3-candle reversal pattern"
    assert ReversalType.OPPOSITE_SIGNAL.value == "opposite entry signal triggered"
    assert ReversalType.RSI_DIVERGENCE.value == "RSI divergence (bearish/bullish)"
    logger.info(f"[PASS] Test 2c: ReversalType enum has all required values")
    
    return True


def test_market_mode_detector():
    """Test MarketModeDetector functionality"""
    logger.info("\n" + "="*60)
    logger.info("TEST 3: Market Mode Detector")
    logger.info("="*60)
    
    from src.exit.market_mode_detector import (
        MarketModeDetector,
        MarketModeConfig,
        MarketMode,
    )
    
    config = MarketModeConfig()
    detector = MarketModeDetector(config)
    
    # Test 3a: BREAKOUT mode (high volatility, strong trend)
    mode = detector.detect_market_mode(
        volatility_regime='HIGH_VOL',
        trend_strength=35.0,  # High ADX
        recent_range=0.003,
    )
    assert mode == MarketMode.BREAKOUT, f"Expected BREAKOUT, got {mode}"
    assert detector.get_tp_multiplier(MarketMode.BREAKOUT) == 3.0, "BREAKOUT should have 3.0R TP"
    assert detector.get_sl_multiplier(MarketMode.BREAKOUT) == 0.5, "BREAKOUT should have 0.5R SL"
    logger.info(f"[PASS] Test 3a: BREAKOUT mode detected (TP=3.0R, SL=0.5R)")
    
    # Test 3b: BOUNCE mode (normal volatility)
    mode = detector.detect_market_mode(
        volatility_regime='NORMAL_VOL',
        trend_strength=20.0,  # Medium ADX
        recent_range=0.002,
    )
    assert mode == MarketMode.BOUNCE, f"Expected BOUNCE, got {mode}"
    assert detector.get_tp_multiplier(MarketMode.BOUNCE) == 2.0, "BOUNCE should have 2.0R TP"
    assert detector.get_sl_multiplier(MarketMode.BOUNCE) == 1.0, "BOUNCE should have 1.0R SL"
    logger.info(f"[PASS] Test 3b: BOUNCE mode detected (TP=2.0R, SL=1.0R)")
    
    # Test 3c: RANGE mode (low volatility, choppy)
    mode = detector.detect_market_mode(
        volatility_regime='LOW_VOL',
        trend_strength=10.0,  # Low ADX
        recent_range=0.001,
    )
    assert mode == MarketMode.RANGE, f"Expected RANGE, got {mode}"
    assert detector.get_tp_multiplier(MarketMode.RANGE) == 1.5, "RANGE should have 1.5R TP"
    assert detector.get_sl_multiplier(MarketMode.RANGE) == 0.75, "RANGE should have 0.75R SL"
    logger.info(f"[PASS] Test 3c: RANGE mode detected (TP=1.5R, SL=0.75R)")
    
    # Test 3d: Summary
    summary = detector.get_mode_summary()
    assert 'mode' in summary, "Summary should contain mode info"
    logger.info(f"[PASS] Test 3d: Mode summary generated")
    
    return True


def test_breakout_tp_calculator():
    """Test BreakoutTPCalculator functionality"""
    logger.info("\n" + "="*60)
    logger.info("TEST 4: Breakout TP Calculator")
    logger.info("="*60)
    
    from src.exit.breakout_tp_calculator import (
        BreakoutTPCalculator,
        BreakoutTPConfig,
    )
    from src.exit.market_mode_detector import MarketMode
    
    config = BreakoutTPConfig()
    calculator = BreakoutTPCalculator(config)
    
    # Test 4a: LONG breakout (3R target, 0.5R stop)
    targets = calculator.calculate_targets(
        entry_price=1.0950,
        direction='LONG',
        atr=100,  # 100 pips ATR
        market_mode='BREAKOUT',
    )
    assert targets.entry_price == 1.0950, "Entry should be 1.0950"
    assert targets.take_profit > targets.entry_price, "TP should be above entry for LONG"
    assert targets.stop_loss < targets.entry_price, "SL should be below entry for LONG"
    assert targets.risk_reward_ratio > 2.0, "Breakout R:R should be > 2.0"
    logger.info(f"[PASS] Test 4a: LONG breakout | Entry={targets.entry_price:.5f}, TP={targets.take_profit:.5f}, SL={targets.stop_loss:.5f}, R:R={targets.risk_reward_ratio:.2f}")
    
    # Test 4b: SHORT bounce (2R target, 1R stop)
    targets = calculator.calculate_targets(
        entry_price=1.0950,
        direction='SHORT',
        atr=100,
        market_mode='BOUNCE',
    )
    assert targets.entry_price == 1.0950, "Entry should be 1.0950"
    assert targets.take_profit < targets.entry_price, "TP should be below entry for SHORT"
    assert targets.stop_loss > targets.entry_price, "SL should be above entry for SHORT"
    logger.info(f"[PASS] Test 4b: SHORT bounce | Entry={targets.entry_price:.5f}, TP={targets.take_profit:.5f}, SL={targets.stop_loss:.5f}, R:R={targets.risk_reward_ratio:.2f}")
    
    # Test 4c: LONG range (1.5R target, 0.75R stop)
    targets = calculator.calculate_targets(
        entry_price=1.0950,
        direction='LONG',
        atr=100,
        market_mode='RANGE',
    )
    assert targets.entry_price == 1.0950, "Entry should be 1.0950"
    assert targets.take_profit > targets.entry_price, "TP should be above entry for LONG"
    assert targets.risk > 0, "Risk should be positive"
    logger.info(f"[PASS] Test 4c: LONG range | Entry={targets.entry_price:.5f}, TP={targets.take_profit:.5f}, SL={targets.stop_loss:.5f}, R:R={targets.risk_reward_ratio:.2f}")
    
    # Test 4d: Custom stop loss
    targets = calculator.calculate_targets(
        entry_price=1.0950,
        direction='LONG',
        atr=100,
        market_mode='BREAKOUT',
        base_stop_loss=1.0850,
    )
    assert targets.stop_loss == 1.0850, "Should use provided stop loss"
    assert targets.risk > 0, "Risk should be positive"
    logger.info(f"[PASS] Test 4d: Using provided stop loss | Risk={targets.risk:.5f}, R:R={targets.risk_reward_ratio:.2f}")
    
    return True


def test_integrated_phase3_flow():
    """Test complete Phase 3 integrated flow"""
    logger.info("\n" + "="*60)
    logger.info("TEST 5: Complete Phase 3 Integrated Flow")
    logger.info("="*60)
    
    from src.exit.multi_level_profit_taker import MultiLevelProfitTaker, MultiLevelConfig
    from src.exit.reversal_exit_detector import ReversalExitDetector, ReversalExitConfig
    from src.exit.market_mode_detector import MarketModeDetector, MarketModeConfig, MarketMode
    from src.exit.breakout_tp_calculator import BreakoutTPCalculator, BreakoutTPConfig
    
    # Initialize all Phase 3 components
    taker_config = MultiLevelConfig()
    reversal_config = ReversalExitConfig()
    mode_config = MarketModeConfig()
    tp_config = BreakoutTPConfig()
    
    taker = MultiLevelProfitTaker(taker_config)
    detector = ReversalExitDetector(reversal_config)
    mode_detector = MarketModeDetector(mode_config)
    calculator = BreakoutTPCalculator(tp_config)
    
    # Simulate a trade scenario
    entry_price = 1.0950
    stop_loss = 1.0850
    current_price = 1.1050  # 1.0R profit
    
    # 1. Check if should take profit (multi-level)
    level, pct = taker.should_take_profit(
        current_price=current_price,
        entry_price=entry_price,
        stop_loss=stop_loss,
    )
    assert level is not None, "Should have triggered profit level"
    
    # 2. Detect market mode
    mode = mode_detector.detect_market_mode(
        volatility_regime='NORMAL_VOL',
        trend_strength=22.0,
        recent_range=0.002,
    )
    assert mode == MarketMode.BOUNCE, "Should detect BOUNCE mode"
    
    # 3. Calculate targets
    targets = calculator.calculate_targets(
        entry_price=entry_price,
        direction='LONG',
        atr=100,
        market_mode='BOUNCE',
        base_stop_loss=stop_loss,
    )
    assert targets.risk_reward_ratio > 1.0, "R:R should be positive"
    
    logger.info(f"[PASS] Complete Phase 3 flow executed")
    logger.info(f"  - Profit level triggered: {level.comment}")
    logger.info(f"  - Market mode: {mode.value}")
    logger.info(f"  - TP/SL calculated: {targets.take_profit:.5f}/{targets.stop_loss:.5f}")
    return True


def main():
    """Run all Phase 3 integration tests"""
    logger.info("\n")
    logger.info("############################################################")
    logger.info("# PHASE 3 INTEGRATION TESTS")
    logger.info("############################################################")
    logger.info(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("")
    
    tests = [
        ("Multi-Level Profit Taker", test_multi_level_profit_taker),
        ("Reversal Exit Detector", test_reversal_exit_detector),
        ("Market Mode Detector", test_market_mode_detector),
        ("Breakout TP Calculator", test_breakout_tp_calculator),
        ("Integrated Phase 3 Flow", test_integrated_phase3_flow),
    ]
    
    passed = 0
    failed = 0
    
    for test_name, test_func in tests:
        try:
            if test_func():
                passed += 1
        except Exception as e:
            logger.error(f"\n[FAIL] {test_name} ERROR: {e}")
            failed += 1
            import traceback
            traceback.print_exc()
    
    logger.info("\n" + "="*60)
    logger.info(f"PHASE 3 TEST RESULTS: {passed} PASSED, {failed} FAILED")
    logger.info("="*60)
    
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
