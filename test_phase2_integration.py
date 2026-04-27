"""
Phase 2 Integration Tests - All Risk Management Components
Tests Dynamic Position Sizing, Advanced Stop Loss, and Correlation Analysis
"""

import sys
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_dynamic_position_sizer():
    """Test DynamicPositionSizer functionality"""
    logger.info("\n" + "="*60)
    logger.info("TEST 1: Dynamic Position Sizer")
    logger.info("="*60)
    
    from src.risk.dynamic_position_sizer import DynamicPositionSizer, PositionSizingConfig
    
    sizer = DynamicPositionSizer(
        PositionSizingConfig(
            base_risk_pct=2.0,
            account_balance=10000.0,
        )
    )
    
    # Test 1a: Excellent signal, normal volatility, strong trend
    pos_size, details = sizer.calculate_position_size(
        signal_score=85,
        volatility_regime='NORMAL_VOL',
        trend_strength='STRONG_TREND',
    )
    assert pos_size > 0, "Position size should be positive"
    assert details['quality_multiplier'] == 1.5, "Quality multiplier wrong"
    assert details['volatility_multiplier'] == 1.0, "Volatility multiplier wrong"
    logger.info(f"✓ Test 1a passed: Excellent signal = {pos_size:.2f} lots")
    
    # Test 1b: Good signal, high volatility, weak trend
    pos_size2, details2 = sizer.calculate_position_size(
        signal_score=70,
        volatility_regime='HIGH_VOL',
        trend_strength='WEAK_TREND',
    )
    assert pos_size2 < pos_size, "High volatility should reduce position"
    logger.info(f"✓ Test 1b passed: Good signal + high vol = {pos_size2:.2f} lots (reduced)")
    
    # Test 1c: Precise position sizing with entry/SL
    pos_size3, details3 = sizer.calculate_position_size(
        signal_score=80,
        volatility_regime='NORMAL_VOL',
        trend_strength='STRONG_TREND',
        entry_price=1.0950,
        stop_loss=1.0850,
    )
    assert pos_size3 > 0, "Position size with entry/SL should be positive"
    logger.info(f"✓ Test 1c passed: With entry/SL = {pos_size3:.2f} lots")
    
    # Test 1d: Drawdown adjustment
    adjusted = sizer.adjust_for_drawdown(15, pos_size)
    assert adjusted < pos_size, "Drawdown should reduce position"
    logger.info(f"✓ Test 1d passed: After 15% drawdown = {adjusted:.2f} lots (reduced)")
    
    return True


def test_advanced_stop_loss():
    """Test Advanced Stop Loss functionality"""
    logger.info("\n" + "="*60)
    logger.info("TEST 2: Advanced Stop Loss Manager")
    logger.info("="*60)
    
    from src.risk.advanced_stop_loss import StopLossManager, StopLossConfig
    
    manager = StopLossManager(
        StopLossConfig(
            hard_stop_atr_multiple=1.5,
            trailing_stop_activation_pips=50,
            breakeven_activation_pips=30,
        )
    )
    
    # Test 2a: Hard stop calculation
    hard_stop = manager.calculate_hard_stop(
        entry_price=1.0950,
        direction='LONG',
        atr=0.0050,
    )
    expected_stop = 1.0950 - (0.0050 * 1.5)
    assert abs(hard_stop - expected_stop) < 0.00001, f"Hard stop calculation wrong: {hard_stop} vs {expected_stop}"
    logger.info(f"✓ Test 2a passed: Hard stop = {hard_stop:.5f}")
    
    # Test 2b: Trailing stop activation check
    current_price = 1.1000  # +50 pips
    should_activate = manager.should_activate_trailing_stop(
        current_price=current_price,
        entry_price=1.0950,
        direction='LONG',
    )
    assert should_activate, "Trailing stop should activate at +50 pips"
    logger.info(f"✓ Test 2b passed: Trailing stop activation at +50 pips")
    
    # Test 2c: Trailing stop calculation
    new_stop = manager.calculate_trailing_stop(
        current_price=current_price,
        direction='LONG',
        current_stop=hard_stop,
    )
    assert new_stop > hard_stop, "Trailing stop should move up"
    logger.info(f"✓ Test 2c passed: Trailing stop = {new_stop:.5f}")
    
    # Test 2d: Breakeven stop activation
    current_price_be = 1.0980  # +30 pips
    should_be = manager.should_activate_breakeven_stop(
        current_price=current_price_be,
        entry_price=1.0950,
        direction='LONG',
    )
    assert should_be, "Breakeven stop should activate at +30 pips"
    logger.info(f"✓ Test 2d passed: Breakeven stop activation at +30 pips")
    
    # Test 2e: Full stop update logic
    updated_stop, stop_type = manager.update_stop_loss(
        trade_id='TEST_LONG_001',
        current_price=1.1000,
        entry_price=1.0950,
        direction='LONG',
        current_stop=hard_stop,
        atr=0.0050,
    )
    assert updated_stop > hard_stop, "Stop should update"
    logger.info(f"✓ Test 2e passed: Stop updated to {updated_stop:.5f} ({stop_type})")
    
    return True


def test_correlation_analyzer():
    """Test Correlation Analyzer functionality"""
    logger.info("\n" + "="*60)
    logger.info("TEST 3: Correlation Analyzer")
    logger.info("="*60)
    
    import numpy as np
    from src.risk.correlation_analyzer import CorrelationAnalyzer, CorrelationConfig
    
    analyzer = CorrelationAnalyzer(
        CorrelationConfig(
            high_correlation_threshold=0.80,
            medium_correlation_threshold=0.60,
            lookback_periods=50,
        )
    )
    
    # Test 3a: Add price data
    np.random.seed(42)
    base_price = 1.0950
    
    for i in range(50):
        # EUR/USD
        eur_usd = base_price + np.random.randn() * 0.005
        analyzer.add_price_data("EUR/USD", eur_usd)
        
        # EUR/GBP (highly correlated - move together)
        eur_gbp = 0.85 + np.random.randn() * 0.003 + (eur_usd - base_price) * 0.8
        analyzer.add_price_data("EUR/GBP", eur_gbp)
        
        # USD/JPY (less correlated - move opposite)
        usdjpy = 155 + np.random.randn() * 0.3 - (eur_usd - base_price) * 100
        analyzer.add_price_data("USD/JPY", usdjpy)
    
    logger.info(f"✓ Test 3a passed: Added 50 bars of price data")
    
    # Test 3b: Calculate correlations
    corr_eur = analyzer.calculate_correlation("EUR/USD", "EUR/GBP")
    corr_usd = analyzer.calculate_correlation("EUR/USD", "USD/JPY")
    
    assert corr_eur > 0.5, f"EUR pairs should be correlated, got {corr_eur}"
    logger.info(f"✓ Test 3b passed: EUR/USD ↔ EUR/GBP correlation = {corr_eur:.3f}")
    logger.info(f"✓ Test 3b passed: EUR/USD ↔ USD/JPY correlation = {corr_usd:.3f}")
    
    # Test 3c: Check if position can open (no violations)
    open_positions = {}  # Empty - should allow anything
    can_open, reason = analyzer.can_open_position("EUR/USD", open_positions)
    assert can_open, "Should allow opening first position"
    logger.info(f"✓ Test 3c passed: Can open EUR/USD (no violations): {reason}")
    
    # Test 3d: Check with correlated position open
    open_positions = {"EUR/GBP": {"size": 0.5}}
    can_open, reason = analyzer.can_open_position("EUR/USD", open_positions)
    # May or may not allow depending on correlation threshold
    logger.info(f"✓ Test 3d passed: EUR/USD check with EUR/GBP open: {can_open}")
    
    # Test 3e: Uncorrelated pair should always be allowed
    open_positions = {"EUR/GBP": {"size": 0.5}}
    can_open, reason = analyzer.can_open_position("USD/JPY", open_positions)
    assert can_open, "Should allow uncorrelated pair"
    logger.info(f"✓ Test 3e passed: Can open USD/JPY (uncorrelated): {reason}")
    
    return True


def test_integrated_flow():
    """Test complete Phase 2 integrated flow"""
    logger.info("\n" + "="*60)
    logger.info("TEST 4: Integrated Phase 2 Flow")
    logger.info("="*60)
    
    from src.risk.dynamic_position_sizer import DynamicPositionSizer, PositionSizingConfig
    from src.risk.advanced_stop_loss import StopLossManager
    from src.risk.correlation_analyzer import CorrelationAnalyzer
    
    # Scenario: New signal for EUR/USD
    symbol = "EUR/USD"
    entry_price = 1.0950
    signal_score = 75
    atr = 0.0050
    volatility_regime = "NORMAL_VOL"
    trend_strength = "STRONG_TREND"
    account_balance = 10000.0
    open_positions = {}  # No positions open
    
    logger.info(f"\n--- Scenario: New {symbol} signal ---")
    logger.info(f"Entry: {entry_price}, Signal Score: {signal_score}/100")
    logger.info(f"ATR: {atr}, Volatility: {volatility_regime}, Trend: {trend_strength}")
    
    # Step 1: Calculate position size
    sizer = DynamicPositionSizer(
        PositionSizingConfig(base_risk_pct=2.0, account_balance=account_balance)
    )
    
    sl_price = entry_price - atr * 1.5
    position_size, sizing_details = sizer.calculate_position_size(
        signal_score=signal_score,
        volatility_regime=volatility_regime,
        trend_strength=trend_strength,
        entry_price=entry_price,
        stop_loss=sl_price,
    )
    logger.info(f"✓ Position Size: {position_size:.2f} lots")
    
    # Step 2: Calculate stop loss
    stop_manager = StopLossManager()
    hard_stop = stop_manager.calculate_hard_stop(
        entry_price=entry_price,
        direction='LONG',
        atr=atr,
        volatility_regime=volatility_regime,
    )
    logger.info(f"✓ Hard Stop: {hard_stop:.5f}")
    
    # Step 3: Check correlations
    analyzer = CorrelationAnalyzer()
    can_open, reason = analyzer.can_open_position(symbol, open_positions)
    assert can_open, f"Should allow opening: {reason}"
    logger.info(f"✓ Correlation check passed: {reason}")
    
    # Step 4: Simulate trade movement
    logger.info(f"\n--- Trade Update: Price moves to 1.1000 ---")
    current_price = 1.1000
    
    updated_stop, stop_type = stop_manager.update_stop_loss(
        trade_id=f"{symbol}_001",
        current_price=current_price,
        entry_price=entry_price,
        direction='LONG',
        current_stop=hard_stop,
        atr=atr,
        volatility_regime=volatility_regime,
    )
    logger.info(f"✓ Stop updated: {updated_stop:.5f} ({stop_type})")
    
    logger.info(f"\n✓ TEST 4 PASSED: Complete flow works!")
    return True


def main():
    """Run all tests"""
    logger.info("\n" + "#"*60)
    logger.info("# PHASE 2 INTEGRATION TESTS")
    logger.info("#"*60)
    logger.info(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    try:
        all_passed = True
        
        # Test 1
        if not test_dynamic_position_sizer():
            all_passed = False
            logger.error("✗ Test 1 FAILED")
        
        # Test 2
        if not test_advanced_stop_loss():
            all_passed = False
            logger.error("✗ Test 2 FAILED")
        
        # Test 3
        if not test_correlation_analyzer():
            all_passed = False
            logger.error("✗ Test 3 FAILED")
        
        # Test 4
        if not test_integrated_flow():
            all_passed = False
            logger.error("✗ Test 4 FAILED")
        
        # Summary
        logger.info("\n" + "#"*60)
        if all_passed:
            logger.info("# ✓ ALL PHASE 2 TESTS PASSED!")
            logger.info("#"*60)
            return 0
        else:
            logger.error("# ✗ SOME TESTS FAILED")
            logger.info("#"*60)
            return 1
            
    except Exception as e:
        logger.error(f"\n✗ TEST ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
