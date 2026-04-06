# Advanced Controls - Integration Guide for Bot Developer

## Quick Start: 5-Minute Integration

### Step 1: Update Bot Initialization (Do Once)

In your main bot setup (where you create admission_controller and model_trainer):

```python
from src.ml.trade_admission_controller import TradeAdmissionController
from ml.model_trainer import ModelTrainer

# Create controllers
admission_controller = TradeAdmissionController(data_dir=".")
model_trainer = ModelTrainer(model_type="xgboost")

# Controllers are now ready with all 3 features enabled
```

### Step 2: Add 6 Calls to Your Bot Cycle

Find your main trading cycle where signals are evaluated per symbol. Add these 6 calls:

```python
# ============================================================================
# START: Advanced Trading Controls Integration (Add to each symbol cycle)
# ============================================================================

# CALL #1: Track accuracy and check for learning window trigger
learning_status = admission_controller.update_accuracy_tracking(
    symbol=symbol,
    current_accuracy=ml_accuracy  # Current model accuracy for this symbol
)

# CALL #2: Check if symbol is in forced learning window
if admission_controller.is_in_forced_learning_window(symbol):
    logger.warning(f"[BLOCKED] {symbol} in learning window, skipping entry signals")
    continue  # Skip to next symbol in cycle

# CALL #3: Handle learning window trigger (if just triggered)
if learning_status == "LEARNING_WINDOW_TRIGGERED":
    logger.critical(f"[FORCED_TRAINING] Triggering forced retraining for {symbol}")
    
    # Get last 500 bars of historical data
    try:
        historical_data = get_historical_data(symbol, bars=500)  # YOUR METHOD
        X = historical_data[feature_columns]  # YOUR FEATURES
        y = historical_data['label']  # YOUR LABELS
        
        # Force retraining
        metrics = model_trainer.force_train_on_historical_bars(
            X_historical=X,
            y_historical=y,
            symbol=symbol,
            max_bars=500
        )
        
        logger.critical(
            f"[TRAINING_COMPLETE] {symbol} | "
            f"Test Accuracy: {metrics.get('test_accuracy', 0):.1%}"
        )
    except Exception as e:
        logger.error(f"[TRAINING_ERROR] {symbol}: {e}")

# CALL #4: Evaluate admission (existing code, now with advanced controls)
admission_decision = admission_controller.evaluate_admission(
    symbol=symbol,
    regime=regime,
    expectancy=expectancy,
    confidence=ml_confidence,
    exit_policy=exit_policy,
    position_size_multiplier=position_size_multiplier,
    real_risk_reward_ratio=rr_ratio,
    forced_execution=False,
    striking_mode_active=striking_mode,
    synthetic_present=False,
    direction=direction,
    current_positions=current_positions,
    min_confidence_threshold=None,  # Let controller use adaptive
    current_spread=current_spread,
    current_atr=current_atr,
    structure_override_active=False,
    raw_ml_confidence=ml_confidence,
    high_impact_news_pending=news_pending,
    ml_accuracy=ml_accuracy,
    historical_trade_count=total_historical_trades,
    low_accuracy_cycle_count=low_accuracy_cycle_count,
    bot_cycle_count=bot_cycle_count,
    trade_tier=trade_tier,
    signal_score=signal_score,
    signal_type=signal_type,
    direction_matches_trend=direction_matches_trend,
    trend_following=trend_following,
    technical_only_mode=technical_only_mode,
    desperation_mode=desperation_mode,
)

# Check admission result
if not admission_decision.admitted:
    logger.info(f"[REJECTED] {symbol}: {admission_decision.reason}")
    # CALL #5: Update stagnation counter (even for rejected trades!)
    admission_controller.update_stagnation_counter(symbol)
    continue  # Skip to next symbol

# CALL #5B: Register accepted trade (called when trade is admitted)
admission_controller.register_accepted_trade(
    symbol=symbol,
    confidence=ml_confidence
)

# CALL #6: Update stagnation counter (after trade decision)
stagnation_status = admission_controller.update_stagnation_counter(symbol)
if stagnation_status == "STAGNATION_THRESHOLD_REDUCED":
    logger.warning(f"[STAGNATION] {symbol} threshold reduced to escape trap")

# Now execute the trade if admitted
if admission_decision.admitted:
    logger.info(
        f"[ADMITTED] {symbol} | Confidence: {ml_confidence:.2%} | "
        f"Expectancy: {expectancy:.2f} | Size: {admission_decision.final_position_multiplier:.2f}x"
    )
    # Execute your trade here...
    execute_trade(symbol, direction, position_size, ...)

# ============================================================================
# END: Advanced Trading Controls Integration
# ============================================================================
```

## How the 6 Calls Work Together

```
Cycle Start
    ↓
[1] update_accuracy_tracking() ← Tracks accuracy, may trigger learning window
    ↓
[2] is_in_forced_learning_window() ← Check if trading is blocked
    ├─ YES → SKIP TO NEXT SYMBOL (window blocks all trades)
    └─ NO → Continue
    ↓
[3] Learning window handler ← If triggered, run forced training
    ↓
[4] evaluate_admission() ← Main admission gate (now with dynamic threshold)
    ├─ REJECTED → [5] update_stagnation_counter() → NEXT SYMBOL
    └─ ADMITTED:
        ↓
    [5B] register_accepted_trade() ← Record confidence for rolling mean
        ↓
    [6] update_stagnation_counter() ← Reset if trade accepted
        ↓
    EXECUTE TRADE
```

## Common Integration Patterns

### Pattern 1: Simple Existing Bot (Minimal Changes)

If you already call `evaluate_admission()`, just wrap it:

```python
# Before:
admission = admission_controller.evaluate_admission(symbol, ...)

# After:
learning_status = admission_controller.update_accuracy_tracking(symbol, ml_accuracy)
if not admission_controller.is_in_forced_learning_window(symbol):
    admission = admission_controller.evaluate_admission(symbol, ...)
    if admission.admitted:
        admission_controller.register_accepted_trade(symbol, ml_confidence)
    admission_controller.update_stagnation_counter(symbol)
```

### Pattern 2: Complex Bot with Multiple Modes

```python
# For each trading mode/symbol:
for symbol in trading_symbols:
    # Step 1: Check basics
    if admission_controller.is_in_forced_learning_window(symbol):
        logger.debug(f"Learning window active for {symbol}")
        continue
    
    # Step 2: Generate signal
    signal = generate_signal(symbol)
    
    # Step 3: Evaluate
    learning_status = admission_controller.update_accuracy_tracking(symbol, signal.ml_accuracy)
    
    if learning_status == "LEARNING_WINDOW_TRIGGERED":
        handle_forced_training(symbol)
    
    admission = admission_controller.evaluate_admission(...)
    
    # Step 4: Execute
    if admission.admitted:
        admission_controller.register_accepted_trade(symbol, signal.confidence)
        execute_trade(signal)
    else:
        logger.debug(f"Rejected: {admission.reason}")
    
    # Step 5: Record cycle
    admission_controller.update_stagnation_counter(symbol)
```

## Where to Get Historical Data

The `force_train_on_historical_bars()` method needs 500 bars of historical data. If your bot has access to OHLC data:

```python
def get_historical_data(symbol: str, bars: int = 500):
    """Get historical bars with features."""
    # Load from your data source (MT5, CSV, cache, etc)
    df = load_ohlc_data(symbol, timeframe=YOUR_TIMEFRAME, barlimit=bars)
    
    # Generate/load features
    features = calculate_features(df)  # ADX, RSI, ATR, etc
    
    # Generate labels (e.g., win/loss based on next bar)
    labels = generate_labels(df)  # 1 for win, 0 for loss
    
    return pd.concat([features, pd.Series(labels, name='label')], axis=1)
```

## What to Monitor in Logs

### Good Signs ✅
```
[DYNAMIC_THRESHOLD_APPLIED] EURUSD | Adaptive threshold: 0.68 | Final: 0.68
[ADMITTED] EURUSD | Confidence: 68% | Expectancy: 2.15 | Size: 1.0x
```

### Warning Signs ⚠️
```
[FORCED_LEARNING_WINDOW_TRIGGERED] EURUSD | Accuracy 42.0% < 45%
→ Model quality degraded, retraining forced

[STAGNATION_TRAP_RECOVERY] EURUSD | No trades accepted for 110 cycles
→ No winning signals, progressively lowering threshold to escape

[BOOTSTRAP_NO_OVERRIDE] EURUSD | Bootstrap mode prevents exploration override
→ Model not ready yet, waiting for legitimately high confidence
```

## Testing Before Deployment

### Test 1: Learning Window Trigger
```python
# Force low accuracy to trigger window
admission_controller.update_accuracy_tracking("EURUSD", 0.42)
# Repeat 20 times

# Verify window is active
assert admission_controller.is_in_forced_learning_window("EURUSD") == True

# Verify trading is blocked
result = admission_controller.evaluate_admission(...)
assert result.admitted == False
assert "LEARNING_WINDOW" in result.reason
```

### Test 2: Adaptive Threshold
```python
# Accept 10 trades with known confidences
for conf in [0.60, 0.65, 0.70, 0.62, 0.68, 0.61, 0.69, 0.64, 0.67, 0.63]:
    admission_controller.register_accepted_trade("EURUSD", conf)

# Verify rolling mean is calculated
threshold = admission_controller.get_adaptive_confidence_threshold("EURUSD")
expected_mean = np.mean([0.60, 0.65, 0.70, 0.62, 0.68, 0.61, 0.69, 0.64, 0.67, 0.63])
assert abs(threshold - expected_mean) < 0.01
```

### Test 3: Bootstrap Disable
```python
# Create scenario: bootstrap_mode=true, confidence=0.35, gate=0.60
# Call evaluate_trade_permission with bootstrap_override_disabled=True
result = admission_controller.evaluate_trade_permission(
    ...,
    bootstrap_override_disabled=True,
    technical_only_mode=True,
)

# Verify override is blocked
assert result.allowed == False
assert result.reason == "BOOTSTRAP_OVERRIDE_DISABLED"
```

## Common Issues & Fixes

### Issue 1: "Learning window never triggers"
**Fix:** Call `update_accuracy_tracking()` every cycle with actual accuracy values
```python
# ❌ Wrong: Only calling when accuracy is good
if ml_accuracy >= 0.45:
    admission_controller.update_accuracy_tracking(symbol, ml_accuracy)

# ✅ Right: Always call with current accuracy
admission_controller.update_accuracy_tracking(symbol, ml_accuracy)
```

### Issue 2: "Adaptive threshold not changing"
**Fix:** Call `register_accepted_trade()` ONLY when `admitted=True`
```python
# ❌ Wrong: Calling for all trades
for trade in all_trades:
    admission_controller.register_accepted_trade(symbol, confidence)

# ✅ Right: Only when admitted
if admission_decision.admitted:
    admission_controller.register_accepted_trade(symbol, ml_confidence)
```

### Issue 3: "Bootstrap override still allowing trades"
**Fix:** Pass `bootstrap_override_disabled=True` to evaluation
```python
# ❌ Wrong: Not passing the flag
admission = evaluate_admission(...)

# ✅ Right: Passing the flag
bootstrap_override_disabled = (bootstrap_mode_active and confidence < 0.60)
admission = evaluate_admission(..., bootstrap_override_disabled=bootstrap_override_disabled)
```

## Performance Checklist

- [ ] Verify cycle overhead < 1ms (should be < 0.5ms)
- [ ] Verify forced training only runs during learning windows
- [ ] Verify no memory leaks in deque tracking
- [ ] Verify log spam is reasonable (not too many messages)
- [ ] Verify stagnation doesn't permanently trap symbols

## Deployment Checklist

- [ ] All 6 integration calls added to bot cycle
- [ ] Historical data retrieval working for all symbols
- [ ] Forced training metrics logged for review
- [ ] Log messages monitored in production
- [ ] Backtest passes with all features enabled
- [ ] Live trading monitored for first 24 hours
- [ ] Learning window behavior verified in logs
- [ ] Stagnation escape verified with test symbols
- [ ] Bootstrap disable verified to prevent bad trades

