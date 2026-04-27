# Hyperparameter Optimization Sweep - Complete Guide

## Overview

The `run_parameter_sweep.py` script performs an exhaustive grid search over signal weights, exit parameters, and other critical trading bot knobs to find the optimal configuration. It uses **walk-forward validation** to avoid overfitting on historical data.

---

## Quick Start

### 1. Run a Quick Test (5-10 minutes)
```bash
python run_parameter_sweep.py --quick
```

This tests a reduced parameter set to verify everything works. Use this first.

### 2. Run Full Sweep (2-4 hours)
```bash
python run_parameter_sweep.py --save-results --plot
```

Flags:
- `--quick`: Reduce grid size for testing (default: False)
- `--save-results`: Export results to CSV and JSON (default: False)
- `--plot`: Generate heatmap and scatter plots (default: False, needs matplotlib)

---

## Understanding the Parameters

### Signal Weights (Impact: HIGH)

| Parameter | Range | Meaning | Recommendation |
|-----------|-------|---------|-----------------|
| `weight_technical` | 0.2-0.8 | Importance of RSI, ADX, volume signals | Start: 0.5 |
| `weight_ml` | 0.2-0.8 | Importance of ML model confidence | Start: 0.5 |
| `weight_mtf` | 0.0-0.4 | Importance of multi-timeframe confluence | Start: 0.2 |

**How they work:**
- Weights are **normalized to sum to 1.0** before use
- Higher weight = more influence on signal score
- Example: `(tech=0.5, ml=0.4, mtf=0.1)` → final score is 50% technical, 40% ML, 10% multi-timeframe

**Good starting point:**
```
weight_technical=0.5, weight_ml=0.5, weight_mtf=0.0  # Classic dual-signal blend
```

---

### Exit Parameters (Impact: VERY HIGH)

#### A. Take-Profit Multiplier (`tp_multiplier`)
| Value | Behavior | Win Rate | Avg Win | Best For |
|-------|----------|----------|---------|----------|
| 1.5R | Very tight TP | HIGH (70-80%) | Small | Scalping |
| 2.0R | Balanced | MEDIUM (55-65%) | Medium | Trend-following |
| 2.5R | Loose TP | LOW (45-55%) | Large | Mean-reversion |
| 3.0R | Very loose TP | VERY LOW (35-50%) | Very Large | Strong trends |

**Interpretation:**
- **Tighter TP** (1.5R) = More trades close at profit, but miss big moves
- **Looser TP** (3.0R) = Catch big moves but experience more stopouts
- **Sharpe ratio favors 2.0-2.5R** (best risk-adjusted returns)

**Choose based on:**
- Scalping/quick profits → 1.5R
- Trend-following → 2.0-2.5R
- Swing trading → 2.5-3.0R

---

#### B. Trailing Stop Activation (`trailing_activation_r`)
| Value | Activation Point | Behavior | Use Case |
|-------|------------------|----------|----------|
| 0.5R | Activate after 0.5R profit | Aggressive; locks in early gains | Choppy markets |
| 1.0R | Activate after 1.0R profit | Balanced; lets winners grow | All markets |
| 1.5R | Activate after 1.5R profit | Conservative; maximizes large moves | Strong trends |

**How it works:**
- Once profit reaches activation point, trailing stop moves with price
- Prevents giving back large profits
- Example: Entry at 1.0000, SL at 0.9950, TP at 1.0200 (2.0R)
  - At 1.0050 (0.5R profit), if `trailing_activation=0.5R` → trailing stop activates
  - If price pulls back to 1.0000, trade closes with small profit

**Best practices:**
- **Choppy markets** → 0.5R (don't let small profits turn into losses)
- **Trending markets** → 1.0-1.5R (let big moves develop)

---

#### C. Time-Based Exit (`time_exit_bars`)
| Value | Meaning | Behavior | Use Case |
|-------|---------|----------|----------|
| 10 | Close after 10 bars | Very short-term | Scalping |
| 20 | Close after 20 bars (if no profit) | Short-term | Active trading |
| 30 | Close after 30 bars | Medium-term | Swing trading |

**How it works:**
- If trade has been open for N bars AND hasn't hit TP, close at market
- Prevents "stuck" trades from sitting idle
- Example: At 15 bars, if profit is still 0.3R (not hitting 2.0R TP) → don't wait, close

**Best for:**
- Scalping: 10 bars
- Active intraday: 20 bars
- Swing/medium-term: 30+ bars

---

#### D. Partial Profit Levels (`partial_profit_levels`)
| Config | Meaning | Behavior |
|--------|---------|----------|
| `((0.5R, 0.2), (1.0R, 0.3))` | Close 20% @ 0.5R, 30% @ 1.0R | Bank profits early, let winners run |
| `((1.0R, 0.4),)` | Close 40% @ 1.0R only | Simpler; one partial |
| `((1.5R, 0.3), (2.0R, 0.3))` | Close 30% @ 1.5R, 30% @ 2.0R | Multiple partial levels |

**How it works:**
- Close X% of position when price hits YR profit level
- Remainder follows TP/trailing stop
- Example: Entry = 1 lot, `(1.0R, 0.4)` means close 0.4 lots at 1.0R, let 0.6 remain

**Pros & Cons:**
- ✅ Banks guaranteed profit
- ✅ Reduces risk of large pullbacks
- ❌ May exit too early on big moves
- ❌ Multiple partials = more transaction costs

---

## Interpreting Results

### Key Metrics Explained

#### 1. **Combined Score** (0.0 - 1.0) ⭐ PRIMARY METRIC
```
Combined Score = 0.40 × Sharpe + 0.30 × WinRate + 0.20 × ProfitFactor + 0.10 × Recovery
```

| Score Range | Quality | Action |
|-------------|---------|--------|
| 0.8-1.0 | Excellent | Use immediately |
| 0.6-0.8 | Good | Consider, validate more |
| 0.4-0.6 | Fair | May need adjustment |
| <0.4 | Poor | Skip |

**Why this weighting?**
- **Sharpe (40%)**: Most important - risk-adjusted returns matter most
- **Win Rate (30%)**: Trading consistency - losing more than winning is bad
- **Profit Factor (20%)**: Profitability - total profits vs total losses
- **Recovery (10%)**: Efficiency - how well you recover from drawdowns

---

#### 2. **Sharpe Ratio** (Higher is Better)
Risk-adjusted return metric.

| Value | Interpretation |
|-------|-----------------|
| > 2.0 | Excellent (exceptional) |
| 1.5-2.0 | Very Good |
| 1.0-1.5 | Good |
| 0.5-1.0 | Fair |
| < 0.5 | Poor |

**Example:**
- Strategy A: 20% return, Sharpe 0.8 (high variance)
- Strategy B: 15% return, Sharpe 1.5 (low variance)
- **Strategy B is better** (more consistent)

---

#### 3. **Win Rate** (0-100%)
Percentage of trades that close with profit.

| Win Rate | Interpretation | Type |
|----------|---|------|
| 70-80% | High | Scalping (many small wins) |
| 55-65% | Good | Balanced |
| 45-55% | Fair | Big-move capturing |
| <45% | Poor | Might need adjustment |

**Note:** Low win rate can still be good if average winner >> average loser (e.g., 40% WR with 3R:1R RR = positive)

---

#### 4. **Profit Factor** (Higher is Better)
Ratio of gross profit to gross loss.

| Value | Interpretation |
|-------|---|
| > 2.0 | Excellent (2× more profit than loss) |
| 1.5-2.0 | Good |
| 1.0-1.5 | Fair |
| < 1.0 | Loss-making |

Formula: `PF = Total Wins / Total Losses`

Example:
- 10 trades, 6 wins @ 100 pips each, 4 losses @ 50 pips each
- `PF = (6 × 100) / (4 × 50) = 600 / 200 = 3.0` ✅ Excellent

---

#### 5. **Recovery Factor** (Higher is Better)
How efficiently profits recover from drawdowns.

| Value | Interpretation |
|-------|---|
| > 5.0 | Exceptional |
| 2.0-5.0 | Good |
| 1.0-2.0 | Fair |
| < 1.0 | Drawdown exceeds profit |

Formula: `RF = Total PnL / Max Drawdown`

Example:
- Total profit: $5,000
- Max drawdown: $1,000
- `RF = 5,000 / 1,000 = 5.0x` ✅ Good recovery

---

## Process: Choosing the Best Parameters

### Step 1: Identify Top Candidates
After sweep completes, look at top 5-10 results:
```
[1] Score: 0.7845 ⭐
    PnL: $2,345 | Sharpe: 1.82 | WR: 58% | PF: 2.1
    tp_multiplier: 2.0 | trailing_activation: 1.0 | time_exit: 20

[2] Score: 0.7623
    PnL: $2,180 | Sharpe: 1.76 | WR: 61% | PF: 1.9
    tp_multiplier: 2.0 | trailing_activation: 0.5 | time_exit: 20
```

### Step 2: Check for Consistency
Do the top results share similar parameters?

✅ **Good sign**: Similar tp_multiplier, trailing_activation values
- Suggests configuration is stable across different weight combinations
- Less likely to be overfitted quirk

❌ **Red flag**: Wildly different parameters in top results
- May indicate overfitting
- Be more conservative in final selection

### Step 3: Validate Robustness
Check if top result is robust across different timeframes:

```
Train Period Score: 0.78
Test Period Score: 0.76  ← Should be close (within 5%)

If Test >> Train or Test << Train, watch out for overfitting
```

### Step 4: Final Selection Criteria

Choose based on **priority** (pick one):

#### For Maximum Profit
```python
# Select based on:
1. Highest Total PnL
2. Sharpe > 1.0
3. Win Rate > 50%
Risk: Drawdown might be large
```

#### For Stability (Recommended for live trading)
```python
# Select based on:
1. Highest Sharpe Ratio
2. Win Rate 55-65% (sweet spot)
3. Recovery Factor > 2.0
4. Profit Factor > 1.5
Risk: Lower profit potential
```

#### For Consistency (Conservative)
```python
# Select based on:
1. Highest Win Rate
2. Lowest Max Drawdown
3. Profit Factor > 1.2
Risk: Smaller trades (missed big moves)
```

---

## Example Decision Tree

```
Run Sweep
    ↓
Look at Top 10 Results
    ↓
Do top params cluster? (same TP, trailing, etc.)
    ├─ YES → Likely stable ✅
    └─ NO → Likely overfit ⚠️
    ↓
Apply Priority Filter (choose your goal)
    ├─ Max Profit → Pick #1 by PnL
    ├─ Stability → Pick #1 by Sharpe
    └─ Conservative → Pick #1 by WinRate
    ↓
Validate on NEW data
    ├─ Performance similar? → Deploy ✅
    └─ Significantly worse? → Try #2-3 from list
    ↓
Live Testing (Demo/Paper)
    ├─ Matches backtest? → Scale to real ✅
    └─ Worse than backtest? → Adjust & retry
```

---

## Common Findings & Recommendations

### Finding 1: Higher TP Multiplier Wins
**Observation:** Best Sharpe comes from TP = 2.5-3.0R

**Recommendation:**
- Use 2.5-3.0R for trend-following
- Accept lower win rate (more frequent exits)
- Ensure trailing stop is aggressive (0.5-1.0R) to lock profits

---

### Finding 2: Partial Profits Reduce Drawdown
**Observation:** Configs with `(1.0R, 0.3)` partial show lower drawdown

**Recommendation:**
- Close 20-40% of position early
- Let remainder run for bigger moves
- Reduces psychological pressure

---

### Finding 3: ML Weight Outperforms Technical
**Observation:** Configs with `weight_ml > weight_technical` score higher

**Recommendation:**
- Your ML model is strong ✅
- Allocate more weight: `ml=0.6, tech=0.4, mtf=0.0`
- Consider retraining ML model monthly

---

### Finding 4: Time-Exit Too Aggressive
**Observation:** `time_exit_bars=10` shows many premature exits

**Recommendation:**
- Increase to 20-30 bars
- Remove time exit if Sharpe is high enough
- Let profitable trades run longer

---

## Saving & Deploying Results

### Save Best Configuration
```bash
# After sweep completes, export top result:
python -c "
import json
best = {
    'weight_technical': 0.50,
    'weight_ml': 0.50,
    'weight_mtf': 0.0,
    'tp_multiplier': 2.0,
    'trailing_activation_r': 1.0,
    'time_exit_bars': 20,
    'partial_profit_levels': [(1.0, 0.3)]
}
with open('optimal_params.json', 'w') as f:
    json.dump(best, f)
print('✅ Saved to optimal_params.json')
"
```

### Load in Your Bot
```python
# In main.py or strategy.py
import json

with open('optimal_params.json') as f:
    params = json.load(f)

# Apply to strategy
strategy.weight_technical = params['weight_technical']
strategy.weight_ml = params['weight_ml']
strategy.tp_multiplier = params['tp_multiplier']
# ... etc
```

---

## Troubleshooting

### Problem: All scores are very low (<0.4)
**Causes:**
- Data quality issue (gaps, wrong format)
- Strategy misconfigured
- Parameters too extreme

**Fix:**
```bash
python run_parameter_sweep.py --quick  # Check with smaller grid
# Review logs for errors
```

### Problem: Huge difference between top results
**Cause:** Likely overfitting to quirks in data

**Fix:**
- Increase test period size (e.g., `test_bars=1000`)
- Use multiple different data periods
- Pick more conservative middle-ranked result

### Problem: Best result has very few trades
**Observation:** `total_trades=5`

**Risk:** Score might not be statistically significant

**Fix:**
- Filter results: only consider `total_trades > 20`
- Requires more lenient parameters (lower TP, shorter time exit)

---

## Next Steps

1. **Run quick sweep** → `python run_parameter_sweep.py --quick`
2. **Interpret results** → Pick top 3 candidates
3. **Validate** → Run on new/out-of-sample data
4. **Paper trade** → 1-2 weeks with optimal params
5. **Go live** → If paper trading matches backtest closely

---

**Questions?** Check logs in console output or open `sweep_results.json` for detailed metrics.

