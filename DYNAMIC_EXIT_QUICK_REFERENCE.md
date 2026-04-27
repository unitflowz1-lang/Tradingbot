# Dynamic Profit Exit Suite - Quick Reference

## ⚡ Quick Start

### 1. Enable Strategies
All 4 strategies are enabled by default. Customize in `TradeManagementSettings`:

```python
settings = TradeManagementSettings(
    use_profit_shaving=True,         # 1.5R → close 50%
    use_rsi_exhaustion=True,         # RSI peak reversal exit
    use_momentum_stall=True,         # Price stall detection
    use_ev_decay_exit=True,          # ML confidence drop exit
)
```

### 2. Pass Data to manage_position()

```python
# During trade management loop:
await profit_protection.manage_position(
    position=position_obj,
    market_data=current_market_data,
    atr=atr_value,
    rsi=rsi_14_value,              # NEW: Required for RSI exit
    ml_confidence=ml_conf_value,    # NEW: Required for ML exit
    regime=regime_label,
    volatility_regime=vol_label
)
```

### 3. Extract RSI from Your Data Source

```python
# From technical indicators module
from src.analysis.technical_indicators import IndicatorCalculator

calc = IndicatorCalculator()
indicators = calc.calculate_indicators(symbol='EURUSD', timeframe='5m')
rsi_value = indicators.rsi  # Extract RSI(14)
```

### 4. Extract ML Confidence

```python
# From your ML models
ml_conf = get_direction_confidence(
    symbol=position.symbol,
    direction=position.direction
)  # Returns float 0.0 - 1.0 (or negative for opposite direction)
```

---

## 📊 Strategy Behavior Chart

| Strategy | Trigger | Action | Constraint | Output |
|----------|---------|--------|-----------|--------|
| **Profit Shaving** | R ≥ 1.5 | Close 50% | Once per trade | PARTIAL_SHAVE |
| **RSI Exhaustion** | RSI peak reversal | Close 100% | Profit > 0.5R | RSI_EXHAUSTION |
| **Momentum Stall** | Price stalled 10 pips, 3 candles | Tighten SL to 0.1R | Any profit | MOMENTUM_STALL |
| **EV-Decay** | ML conf < 5% OR flips | Close 100% | Any profit | ML_DECAY |

---

## 🎯 Configuration Examples

### Conservative (Paper Trading)
```python
profit_shaving_trigger_r = 2.0         # Wait for 2R before shaving
momentum_stall_range_pips = 15.0       # Require bigger stall
momentum_stall_candles = 5             # Require longer stall
```

### Aggressive (Live Trading)
```python
profit_shaving_trigger_r = 1.2         # Early shaving at 1.2R
momentum_stall_range_pips = 8.0        # Detect smaller stalls
momentum_stall_candles = 2             # Quick response
```

---

## 📋 Log Monitoring

### Watch for These Log Lines

```
# Profit Shaving triggered
[DYNAMIC_EXIT] Type: PARTIAL_SHAVE | PnL Secured: $150.25 | EURUSD #123456

# RSI Exhaustion detected
[DYNAMIC_EXIT] Type: RSI_EXHAUSTION | PnL Secured: $450.50 | GBPJPY #234567

# Momentum stall detected and SL tightened
[DYNAMIC_EXIT] Type: MOMENTUM_STALL | PnL Secured: $89.75 | USDJPY #345678

# ML confidence dropped, position closed
[DYNAMIC_EXIT] Type: ML_DECAY | PnL Secured: $320.00 | AUDUSD #456789
```

### Check State File

```bash
# View current state of all tracked positions
cat profit_protection_state.json
```

---

## 🔧 Troubleshooting

### RSI Exhaustion Not Triggering
- **Check**: Is RSI data being passed correctly?
- **Check**: Is profit > threshold (default 0.5R)?
- **Check**: Is RSI actually crossing threshold and reversing?

```python
# Debug: Log RSI values
if current_rsi is not None:
    logger.info(f"RSI Debug: Symbol={symbol}, RSI={current_rsi:.1f}, "
                f"Threshold={threshold}, PrevRSI={prev_rsi}")
```

### Momentum Stall Not Working
- **Check**: Are you passing 5-minute candle data consistently?
- **Check**: Is price_history being populated?
- **Check**: Is pip calculation correct for your symbol?

```python
# Debug: Log price history
logger.info(f"Price History: {state['price_history'][-3:]}, "
            f"Range: {max-min:.5f}, Threshold: {stall_range_pips * pip_value:.5f}")
```

### ML Decay Not Executing
- **Check**: Is ML confidence being passed (not None)?
- **Check**: Is it actually dropping below 5% or flipping sign?

```python
# Debug: Log ML confidence
logger.info(f"ML Conf: Current={current_ml:.3f}, Prev={prev_ml:.3f}, "
            f"Below5%={current_ml < 0.05}, Flipped={sign(current_ml) != sign(prev_ml)}")
```

---

## 📈 Performance Expectations

After implementation, you should see:

### Profit Realization Improvements
- More consistent profit locking
- Reduced manual intervention for taking profits
- Better handling of market reversals

### Risk Metrics Changes
- Slightly lower average trade duration (earlier exits)
- More partial exits, fewer full-position liquidations
- Better win rate on "locked in" trades

### Trading Statistics
- Expect 3-5 DYNAMIC_EXIT events per 50 trades
- ~70% from Profit Shaving
- ~15% from RSI Exhaustion
- ~10% from Momentum Stall
- ~5% from EV-Decay

---

## ✅ Integration Checklist

- [ ] RSI calculation integrated and passed to manage_position
- [ ] ML confidence available and passed to manage_position
- [ ] All 4 strategies enabled (or selectively disabled)
- [ ] Log file monitored for [DYNAMIC_EXIT] entries
- [ ] Paper trading running for 100+ trades
- [ ] Thresholds tuned to match your market conditions
- [ ] Profit_protection_state.json tracked for debugging
- [ ] Live trading ready

---

## 🚀 Deployment Steps

1. **Current Step**: Implementation Complete ✅
2. **Next**: Integrate RSI and ML confidence data sources
3. **Then**: Run paper trading for validation
4. **Finally**: Deploy to live trading with monitoring

---

**For detailed strategy documentation, see: DYNAMIC_PROFIT_EXIT_SUITE_IMPLEMENTATION.md**
