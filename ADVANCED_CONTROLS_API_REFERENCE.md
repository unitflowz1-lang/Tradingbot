# Advanced Trading Controls - Quick API Reference

## TradeAdmissionController Methods

### Learning Window Management

#### `update_accuracy_tracking(symbol: str, current_accuracy: float) -> Optional[str]`
**Purpose:** Track accuracy cycles and trigger forced learning window
**Called:** Every bot cycle
**Returns:**
- `"LEARNING_WINDOW_TRIGGERED"` - Just triggered (first cycle of window)
- `"LEARNING_WINDOW_ACTIVE"` - Already in window
- `None` - Normal operation

**Example:**
```python
status = admission_controller.update_accuracy_tracking(
    symbol="EURUSD",
    current_accuracy=0.42
)
if status == "LEARNING_WINDOW_TRIGGERED":
    # Call ModelTrainer.force_train_on_historical_bars()
    pass
```

---

#### `is_in_forced_learning_window(symbol: str) -> bool`
**Purpose:** Check if symbol is currently in learning window
**Called:** During admission evaluation
**Returns:** `True` if trading should be blocked, `False` otherwise

**Example:**
```python
if admission_controller.is_in_forced_learning_window("EURUSD"):
    # Return REJECTED decision
    return AdmissionDecision(admitted=False, ...)
```

---

### Dynamic Thresholding Management

#### `register_accepted_trade(symbol: str, confidence: float) -> None`
**Purpose:** Register a newly admitted trade to update rolling mean threshold
**Called:** Immediately after `evaluate_admission()` returns `admitted=True`
**Parameters:**
- `symbol`: Trading symbol
- `confidence`: ML confidence of the admitted trade (0.0 - 1.0)

**Example:**
```python
if admission_decision.admitted:
    admission_controller.register_accepted_trade(
        symbol="EURUSD",
        confidence=0.68
    )
```

---

#### `update_stagnation_counter(symbol: str) -> Optional[str]`
**Purpose:** Track cycles without accepted trades and reduce threshold during stagnation
**Called:** Every bot cycle (regardless of outcome)
**Returns:**
- `"STAGNATION_THRESHOLD_REDUCED"` - Threshold was just reduced
- `None` - No reduction this cycle

**Example:**
```python
stagnation_status = admission_controller.update_stagnation_counter("EURUSD")
if stagnation_status == "STAGNATION_THRESHOLD_REDUCED":
    logger.info(f"Threshold reduced for EURUSD to escape stagnation trap")
```

---

#### `get_adaptive_confidence_threshold(symbol: str) -> float`
**Purpose:** Get current adaptive threshold for a symbol
**Called:** For monitoring/debugging
**Returns:** Current threshold (default 0.42, adjusted based on accepted trades and stagnation)

**Example:**
```python
current_threshold = admission_controller.get_adaptive_confidence_threshold("EURUSD")
logger.info(f"EURUSD adaptive threshold: {current_threshold:.2f}")
```

---

### Bootstrap Override Disable

#### `evaluate_admission(..., bootstrap_override_disabled: bool = False)`
**Purpose:** Admission evaluation with bootstrap override disabling
**Parameters:** 
- `bootstrap_override_disabled`: Set to `True` when in bootstrap mode AND confidence < 60%

**Example:**
```python
# In evaluate_admission() implementation:
bootstrap_override_disabled = False
if bootstrap_mode_active and raw_ml_confidence < effective_min_confidence_threshold:
    bootstrap_override_disabled = True

admission = evaluate_admission(
    ...,
    bootstrap_override_disabled=bootstrap_override_disabled
)
```

---

#### `evaluate_trade_permission(..., bootstrap_override_disabled: bool = False)`
**Purpose:** Permission evaluation with bootstrap override check
**Parameters:**
- `bootstrap_override_disabled`: Prevents exploration override if True

**Returns:** `TradePermissionDecision` with `allowed=False` if bootstrap override is disabled

**Example:**
```python
permission = admission_controller.evaluate_trade_permission(
    symbol="EURUSD",
    ...,
    bootstrap_override_disabled=bootstrap_override_disabled
)
if not permission.allowed and permission.reason == "BOOTSTRAP_OVERRIDE_DISABLED":
    logger.warning(f"Bootstrap prevents entry for {symbol}")
```

---

## ModelTrainer Methods

### Forced Training

#### `force_train_on_historical_bars(X_historical: pd.DataFrame, y_historical: pd.Series, symbol: str = "", max_bars: int = 500) -> Dict`
**Purpose:** Force immediate model retraining on last N historical bars
**Called:** When learning window is triggered (accuracy < 45% for 20 cycles)
**Parameters:**
- `X_historical`: Historical feature DataFrame
- `y_historical`: Historical label Series
- `symbol`: Symbol name (for logging)
- `max_bars`: Max bars to use (default 500)

**Returns:** Dictionary with training metrics:
```python
{
    'train_accuracy': float,
    'val_accuracy': float,
    'test_accuracy': float,
    'test_precision': float,
    'test_recall': float,
    'test_f1': float
}
```

**Example:**
```python
learning_status = admission_controller.update_accuracy_tracking("EURUSD", 0.40)

if learning_status == "LEARNING_WINDOW_TRIGGERED":
    # Gather last 500 bars
    last_500 = get_last_500_bars("EURUSD")
    X = last_500[features]
    y = last_500['label']
    
    # Force training
    metrics = model_trainer.force_train_on_historical_bars(
        X_historical=X,
        y_historical=y,
        symbol="EURUSD",
        max_bars=500
    )
    
    logger.info(f"Forced training complete. New accuracy: {metrics['test_accuracy']:.2%}")
```

---

## Integration Flow (Step-by-Step)

### Setup (Bot Initialization)
```python
# Create controllers
admission_controller = TradeAdmissionController(data_dir=".")
model_trainer = ModelTrainer(model_type="xgboost")
```

### Every Trading Cycle

#### Step 1: Update Accuracy Tracking
```python
learning_status = admission_controller.update_accuracy_tracking(
    symbol=symbol,
    current_accuracy=current_ml_accuracy
)
```

#### Step 2: Check Learning Window
```python
if admission_controller.is_in_forced_learning_window(symbol):
    logger.warning(f"{symbol} in learning window, all trades blocked")
    continue  # Go to next symbol in cycle
```

#### Step 3: Evaluate Admission
```python
# Determine bootstrap override disabled flag
bootstrap_override_disabled = (
    bootstrap_mode_active and 
    raw_ml_confidence < 0.60
)

admission_decision = admission_controller.evaluate_admission(
    symbol=symbol,
    regime=regime,
    expectancy=expectancy,
    confidence=confidence,
    ...,
    technical_only_mode=technical_only_mode,
    low_accuracy_cycle_count=low_accuracy_cycles,
    bot_cycle_count=bot_cycle_count,
    ml_accuracy=ml_accuracy,
)
```

#### Step 4: Register Accepted Trade (if admitted)
```python
if admission_decision.admitted:
    admission_controller.register_accepted_trade(
        symbol=symbol,
        confidence=raw_ml_confidence
    )
    # Execute the trade...
```

#### Step 5: Update Stagnation Counter
```python
stagnation_status = admission_controller.update_stagnation_counter(symbol)
if stagnation_status == "STAGNATION_THRESHOLD_REDUCED":
    logger.info(f"Threshold reduced for {symbol}")
```

#### Step 6: Handle Learning Window Triggers
```python
if learning_status == "LEARNING_WINDOW_TRIGGERED":
    # Get last 500 bars of data for this symbol
    historical_data = get_last_500_bars(symbol)
    X = historical_data[feature_columns]
    y = historical_data['label']
    
    # Force retraining
    metrics = model_trainer.force_train_on_historical_bars(
        X_historical=X,
        y_historical=y,
        symbol=symbol,
        max_bars=500
    )
    
    if metrics.get('test_accuracy', 0) > 0.45:
        logger.critical(f"{symbol} recovered to {metrics['test_accuracy']:.1%}")
    else:
        logger.critical(f"{symbol} still low at {metrics['test_accuracy']:.1%}, staying in learning window")
```

---

## Configuration Constants

### In TradeAdmissionController.__init__()

```python
# Learning Window Settings
self.LOW_ACCURACY_THRESHOLD = 0.45  # 45% accuracy triggers window
self.LOW_ACCURACY_CONSECUTIVE_CYCLES = 20  # Track for 20 cycles
self.LEARNING_WINDOW_DURATION_MINUTES = 60  # 60-minute freeze

# Dynamic Thresholding Settings
self.ACCEPTED_TRADES_LOOKBACK = 10  # Rolling mean of last 10 trades
self.STAGNATION_CYCLE_THRESHOLD = 100  # After 100 cycles without trades
self.THRESHOLD_REDUCTION_PER_CYCLE = 0.01  # Reduce by 0.01 per cycle
```

### To Modify:
```python
# Example: Make learning window shorter (30 minutes)
admission_controller.LEARNING_WINDOW_DURATION_MINUTES = 30

# Example: Stricter stagnation recovery (200 cycles, 0.005 reduction)
admission_controller.STAGNATION_CYCLE_THRESHOLD = 200
admission_controller.THRESHOLD_REDUCTION_PER_CYCLE = 0.005

# Example: More aggressive accuracy threshold (60%)
admission_controller.LOW_ACCURACY_THRESHOLD = 0.60
```

---

## Monitoring & Alerts

### Log Message Patterns

**Learning Window Triggered:**
```
[FORCED_LEARNING_WINDOW_TRIGGERED] EURUSD | Accuracy 42.0% < 45% for 20 consecutive cycles.
```

**Learning Window Active:**
```
[FORCED_LEARNING_WINDOW_ACTIVE] EURUSD | Still in learning window. Trading BLOCKED for 58.3 more minutes.
```

**Forced Training Started:**
```
[FORCED_TRAINING_START] EURUSD | Training on 500 historical bars
```

**Stagnation Recovery:**
```
[STAGNATION_TRAP_RECOVERY] EURUSD | No trades accepted for 110 cycles. 
Progressively lowering confidence threshold: 0.42 → 0.32
```

**Bootstrap Override Disabled:**
```
[BOOTSTRAP_NO_OVERRIDE] EURUSD | Bootstrap mode active + confidence 0.38 < gate 0.60 | 
Exploration override DISABLED.
```

**Dynamic Threshold Applied:**
```
[DYNAMIC_THRESHOLD_APPLIED] EURUSD | Base threshold: 0.42 | 
Adaptive threshold: 0.68 | Final: 0.68
```

---

## Troubleshooting

### Problem: Symbol stuck in learning window
**Solution:** Ensure `force_train_on_historical_bars()` is actually being called and returns improved accuracy

### Problem: Stagnation never breaks
**Solution:** Check that `register_accepted_trade()` is being called when trades are admitted

### Problem: Bootstrap override still allowing trades
**Solution:** Verify `bootstrap_override_disabled` flag is being set correctly in evaluate_admission()

### Problem: Adaptive threshold not updating
**Solution:** Call `register_accepted_trade()` immediately after admission, not later in cycle

---

## Performance Notes

- **Learning window check:** O(1) dict lookup
- **Stagnation counter:** O(1) increment
- **Adaptive threshold:** O(10) deque mean, O(1) once mean is calculated
- **Forced training:** O(N*F) where N=bars, F=features (only during learning window, rare)

**Total overhead per cycle:** < 1ms (negligible)

