# Dynamic Profit Position Exit Suite - Implementation Complete ✅

## Overview
The Dynamic Profit Position Exit Suite has been successfully implemented in `src/trading/profit_protection_module.py` with **zero changes to entry logic**. This suite adds four intelligent profit-taking strategies while maintaining the existing risk protection mechanisms.

---

## 4 Exit Strategies Implemented

### 1. **Profit Shaving** (Partial Exits at 1.5R)
- **Trigger**: When trade reaches 1.5R (halfway to 3.0R target)
- **Action**: Automatically close 50% of position volume
- **Benefit**: Ensures every significantly profitable trade locks in at least 50% of gains
- **Even if** remaining 50% hits breakeven trailing stop, 50% profit is secured

**Configuration Settings:**
```python
use_profit_shaving: bool = True
profit_shaving_trigger_r: float = 1.5  # Trigger at 1.5R
profit_shaving_close_percent: float = 0.5  # Close 50%
```

**Log Entry Format:**
```
[DYNAMIC_EXIT] Type: PARTIAL_SHAVE | PnL Secured: ${value} | {SYMBOL} #{POSITION_ID}
```

---

### 2. **RSI-Based Exhaustion Exit** (The "Clipping" Logic)
- **For LONGs**: RSI (14) crosses **above 75** (overbought), then ticks downward
- **For SHORTs**: RSI (14) crosses **below 25** (oversold), then ticks upward  
- **Constraint**: Only triggers if profit > 0.5R (configurable threshold)
- **Action**: Close **entire position** immediately at market
- **Reason**: Simulates the user "seeing the peak" and getting out before retracement

**Key Implementation Details:**
- Tracks previous RSI value to detect state transitions
- Maintains separate flags for LONG crossing above 75 and SHORT crossing below 25
- Waits for tick reversal before executing (2-candle pattern detection)
- One-time per trade (prevents re-triggering)

**Configuration Settings:**
```python
use_rsi_exhaustion: bool = True
rsi_exhaustion_threshold_min_profit_r: float = 0.5  # Only if profit > 0.5R
rsi_exhaustion_long_overbought: float = 75.0  # LONG overbought threshold
rsi_exhaustion_short_oversold: float = 25.0  # SHORT oversold threshold
```

**Log Entry Format:**
```
[DYNAMIC_EXIT] Type: RSI_EXHAUSTION | PnL Secured: ${value} | {SYMBOL} #{POSITION_ID}
```

---

### 3. **Momentum Stall Detection** (Time-VPT Logic)
- **Trigger**: Price remains within **10 pips** for **3+ consecutive** 5-minute candles while trade is in profit
- **Action**: Tighten trailing stop from 0.4R → **0.1R** (hard lock on current price)
- **Reason**: If market stops moving, bot stops "hoping" and starts "locking"
- **Effect**: Converts trailing stop into a break-glass "market won't move, so capture gains now"

**Key Implementation Details:**
- Maintains price history (last 200 candles)
- Calculates price range (high - low) across last N candles
- Compares range to configured pip threshold
- Applies special momentum stall SL modification when stall detected
- One-time per trade (prevents repeated tightening)

**Configuration Settings:**
```python
use_momentum_stall: bool = True
momentum_stall_range_pips: float = 10.0  # Price within X pips
momentum_stall_candles: int = 3  # For N consecutive candles
momentum_stall_velocity_multiplier: float = 0.1  # Tighten to 0.1R
```

**Log Entry Format:**
```
[DYNAMIC_EXIT] Type: MOMENTUM_STALL | PnL Secured: ${value} | {SYMBOL} #{POSITION_ID}
```

---

### 4. **EV-Decay Exit** (ML Sentiment Shift)
- **Trigger 1**: ML Confidence for trade direction drops below **5%** (0.05)
- **Trigger 2**: ML Confidence **flips to opposite direction** (e.g., from +0.7 to -0.3)
- **Action**: Close trade at market price if currently in **any amount of profit** (>0R)
- **Reason**: If AI no longer believes in trade direction, exit with current gain rather than risk reversal

**Key Implementation Details:**
- Tracks both absolute confidence value and direction (sign)
- Detects confidence floor breach (< 5%)
- Detects confidence crossover (positive → negative or vice versa)
- Closes full position at market (not just modifying stops)
- One-time per trade execution

**Configuration Settings:**
```python
use_ev_decay_exit: bool = True
ev_decay_confidence_floor: float = 0.05  # Exit if ML conf < 5%
```

**Log Entry Format:**
```
[DYNAMIC_EXIT] Type: ML_DECAY | PnL Secured: ${value} | {SYMBOL} #{POSITION_ID}
```

---

## Integration Points

### Position State Tracking
Enhanced position state to track dynamic exit strategy data:

```python
'profit_shaving_done': False,      # Tracks if strategy executed
'rsi_exhaustion_done': False,
'momentum_stall_done': False,
'ev_decay_done': False,

'prev_rsi': None,                  # RSI crossing detection
'rsi_crossed_above': False,        # LONG overbought flag
'rsi_crossed_below': False,        # SHORT oversold flag

'price_history': [],               # Momentum stall detection
'ml_confidence': 0.0,              # Current ML confidence
'prev_ml_confidence': 0.0,         # Previous ML confidence (flip detection)
```

### Function Signature Update
The `manage_position` method now accepts optional indicator parameters:

```python
async def manage_position(
    self, 
    position: Position, 
    market_data: MarketData, 
    atr: float,
    regime: Optional[str] = None,
    volatility_regime: Optional[str] = None,
    rsi: Optional[float] = None,           # NEW: Optional RSI value
    ml_confidence: Optional[float] = None  # NEW: Optional ML confidence
) -> bool:
```

### Data Flow
```
Input: market_data (with indicators)
  ↓
Extract RSI, ML confidence from market_data
  ↓
Check enter position state
  ↓
Calculate current_R (profit multiple)
  ↓
Run Dynamic Exit Suite:
  ├─ Profit Shaving (if R >= 1.5)
  ├─ RSI Exhaustion (if 0.5R > profit > 0, RSI reversal)
  ├─ Momentum Stall (if profit > 0, price stalled)
  └─ EV-Decay (if profit > 0, ML confidence issues)
  ↓
Return action_taken flag
```

---

## Logging Format

All dynamic exits follow a consistent logging pattern:

**Execution Log** (INFO level):
```
[DYNAMIC_EXIT] Type: {STRATEGY_TYPE} | {SYMBOL} ID:{POS_ID} | Details...
```

**Confirmation Log** (CRITICAL level):
```
[DYNAMIC_EXIT] Type: {STRATEGY_TYPE} | PnL Secured: ${value} | {SYMBOL} #{POSITION_ID}
```

**Example Output:**
```
[DYNAMIC_EXIT] Type: PARTIAL_SHAVE | PnL Secured: $125.50 | EURUSD #123456
[DYNAMIC_EXIT] Type: RSI_EXHAUSTION | PnL Secured: $287.30 | GBPJPY #789012
[DYNAMIC_EXIT] Type: MOMENTUM_STALL | PnL Secured: $45.25 | USDJPY #345678
[DYNAMIC_EXIT] Type: ML_DECAY | PnL Secured: $156.75 | AUDUSD #901234
```

---

## Calling Convention

To enable the dynamic exit suite in your trading loop, call `manage_position` with RSI and ML confidence:

```python
# Example from trading engine:
from src.analysis.technical_indicators import IndicatorCalculator
from src.ml.ml_models import MLConfidenceCalculator

# During each trade management cycle:
indicator_calc = IndicatorCalculator()
ml_calc = MLConfidenceCalculator()

for position in active_positions:
    market_data = get_market_data(position.symbol)
    atr = calculate_atr(position.symbol)
    rsi = indicator_calc.calculate_rsi(position.symbol, period=14)
    ml_conf = ml_calc.get_direction_confidence(position.symbol, position.direction)
    
    # Call with new parameters
    action = await profit_protection.manage_position(
        position=position,
        market_data=market_data,
        atr=atr,
        regime=regime_detector.current_regime,
        volatility_regime=vol_detector.current_vol_regime,
        rsi=rsi,                    # NEW
        ml_confidence=ml_conf       # NEW
    )
```

---

## Configuration Guide

### Enable/Disable Strategies
```python
# In TradeManagementSettings:
use_profit_shaving = True          # Global enable/disable
use_rsi_exhaustion = True
use_momentum_stall = True
use_ev_decay_exit = True
```

### Adjust Thresholds
```python
# Profit Shaving
profit_shaving_trigger_r = 1.5     # Change trigger level
profit_shaving_close_percent = 0.5 # Change close percentage

# RSI Exhaustion
rsi_exhaustion_threshold_min_profit_r = 0.5  # Min profit to trigger
rsi_exhaustion_long_overbought = 75.0        # LONG peak threshold
rsi_exhaustion_short_oversold = 25.0         # SHORT trough threshold

# Momentum Stall
momentum_stall_range_pips = 10.0   # Change stall detection range
momentum_stall_candles = 3         # Change candle count
momentum_stall_velocity_multiplier = 0.1  # Change tightening factor

# EV-Decay
ev_decay_confidence_floor = 0.05   # Change confidence floor (5%)
```

---

## State Persistence

All strategy states are persisted to `profit_protection_state.json`:
- Tracks which strategies have executed per position
- Allows recovery if bot restarts mid-trade
- Prevents duplicate executions (one-time per trade per strategy)

---

## Interaction with Existing Strategies

**Priority Order:**
1. Take Profit (MT5 server-side)
2. Stop Loss (MT5 server-side)
3. Scale-Out + Breakeven (existing module)
4. Partial Profits (existing module, legacy path)
5. Velocity Trailing (existing module)
6. Breakeven Move (existing module)
7. **Dynamic Exit Suite** ← Applied in profit management cycle

The dynamic exit suite operates **after** existing strategies and can:
- Close positions (strategies 1, 2, 4)
- Modify stop losses (strategy 3)
- Work in parallel with trailing stops

No existing entry or risk protection logic was modified.

---

## Testing & Validation

### Manual Testing
1. Enable one strategy at a time
2. Verify log format matches expected output
3. Check that position states are persisted correctly
4. Confirm PnL calculations

### Integration Testing
- Verify RSI and ML confidence data is correctly extracted
- Test state transitions across multiple trades
- Validate one-time execution per strategy per trade
- Confirm position tracking cleanup on exit

### Performance Considerations
- Price history maintained at max 200 candles (configurable)
- RSI and ML confidence lookup is O(1) via direct attribute access
- State persistence happens only on strategy execution (not every cycle)

---

## Summary of Changes

### Files Modified
- `src/trading/profit_protection_module.py`
  - Added 4 strategy methods
  - Enhanced position state tracking
  - Updated manage_position signature
  - Added configuration settings

### Backward Compatibility
✅ **Fully backward compatible** - all new parameters are optional
✅ **Zero entry logic changes** - entry code untouched
✅ **Existing strategies unaffected** - new suite runs after

### Lines of Code
- Configuration: ~30 lines
- State tracking: ~20 lines
- Strategic methods: ~400 lines
- Integration: ~20 lines

---

## Next Steps

1. **Data Integration**: Ensure RSI and ML confidence are calculated and passed to `manage_position`
2. **Testing**: Run on paper trading to validate strategy behavior
3. **Tuning**: Adjust thresholds based on historical backtest results
4. **Monitoring**: Watch logs for `[DYNAMIC_EXIT]` entries

---

## Reference Configuration

```python
# Recommended starting configuration for paper trading

use_profit_shaving = True
profit_shaving_trigger_r = 1.5
profit_shaving_close_percent = 0.5

use_rsi_exhaustion = True
rsi_exhaustion_threshold_min_profit_r = 0.5
rsi_exhaustion_long_overbought = 75.0
rsi_exhaustion_short_oversold = 25.0

use_momentum_stall = True
momentum_stall_range_pips = 10.0
momentum_stall_candles = 3
momentum_stall_velocity_multiplier = 0.1

use_ev_decay_exit = True
ev_decay_confidence_floor = 0.05
```

---

**Implementation Date**: 2026-03-19
**Status**: ✅ Complete & Ready for Integration
