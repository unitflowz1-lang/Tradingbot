# Parameter Sweep - Quick Reference Card

## 🚀 30-Second Start

```bash
# Test mode (5 min)
python launch_sweep.py --quick

# Full sweep (2-4 hours)
python launch_sweep.py --full --plot --save

# Extract best params
python extract_best_params.py

# Deploy to bot
# Edit: config_optimized_params.json
# See: PARAMETER_INTEGRATION_GUIDE.md
```

---

## 📊 Results Interpretation Cheat Sheet

After sweep runs, open `sweep_results.json` and look at result #1:

```json
{
  "combined_score": 0.7845,        // ← Higher is better (0.6+ is good)
  "metrics": {
    "sharpe": 1.82,                // ← Should be 1.5+ (risk-adjusted return)
    "win_rate": 58,                // ← Should be 50%+ (consistency)
    "profit_factor": 2.1,          // ← Should be 1.5+ (profit/loss ratio)
    "recovery": 3.2,               // ← Should be 2.0+ (recovery from drawdown)
    "total_pnl": 2345,             // ← Actual profit in backtest
    "max_drawdown": 450            // ← Largest loss
  },
  "params": {
    "weight_technical": 0.50,      // ← Signal weights
    "weight_ml": 0.50,
    "weight_mtf": 0.0,
    "tp_multiplier": 2.0,          // ← Exit parameters
    "trailing_activation_r": 1.0,
    "time_exit_bars": 20,
    "partial_profit_levels": [[1.0, 0.3]]
  }
}
```

---

## ⚙️ Parameter Meaning Quick Reference

| Parameter | Range | Meaning | Recommendation |
|-----------|-------|---------|---|
| `weight_technical` | 0.2-0.8 | RSI/ADX/Vol weight | 0.5 |
| `weight_ml` | 0.2-0.8 | ML confidence weight | 0.5 |
| `weight_mtf` | 0.0-0.4 | Multi-timeframe weight | 0.0-0.2 |
| `tp_multiplier` | 1.5-3.0R | Take-profit target | 2.0R |
| `trailing_activation_r` | 0.5-1.5R | When to start trailing | 1.0R |
| `time_exit_bars` | 10-30 | Max bars in trade | 20 |
| `partial_profit_levels` | [(1.0R, 0.3)] | Close X% at YR | (1.0, 0.3) + (1.5, 0.2) |

**Color Codes:**
- 🟢 Keep as-is
- 🟡 May need adjustment for your trading style
- 🔴 If all tests show this severely underperforms

---

## 🎯 Decision Tree: Which Result to Pick?

```
START: Looking at sweep results

├─ Highest "combined_score"? → Use #1 ✅ (Recommended)
│
├─ Want MAXIMUM PROFIT?
│  └─ Pick by highest "total_pnl" (risk: high drawdown)
│
├─ Want STABILITY? (Recommended for live)
│  └─ Pick by highest "sharpe" with WR > 55%
│
└─ Want CONSERVATIVE?
   └─ Pick by highest "win_rate" with lowest "max_drawdown"
```

**Golden Rule:** Top 3 results should have similar parameter values. If wildly different → likely overfitting → pick more conservative result.

---

## 📉 Metric Cheat Sheet

| Metric | Good | Excellent | Interpretation |
|--------|------|-----------|---|
| **Sharpe Ratio** | 1.0-1.5 | 2.0+ | Risk-adjusted return (higher = smoother profit curve) |
| **Win Rate** | 45-55% | 60%+ | % of trades that close with profit |
| **Profit Factor** | 1.5+ | 2.0+ | Ratio of wins:losses (2.0 = 2x more profit than loss) |
| **Recovery** | 1.5-2.0 | 3.0+ | How well profits recover from drawdowns |
| **Combined Score** | 0.5-0.6 | 0.75+ | Overall quality (weighted average of above) |

---

## 🔧 3-Step Integration

### Step 1: Extract (after sweep completes)
```bash
python extract_best_params.py
# Creates: optimal_params_deployed.json
```

### Step 2: Create Config
Create `config_optimized_params.json`:
```json
{
  "signal_weights": {
    "weight_technical": 0.50,
    "weight_ml": 0.50,
    "weight_mtf": 0.0
  },
  "exit_config": {
    "tp_multiplier": 2.0,
    "trailing_activation_r": 1.0,
    "time_exit_bars": 20,
    "partial_profit_levels": [[1.0, 0.3]]
  }
}
```

### Step 3: Deploy
In `main.py`:
```python
import json
with open('config_optimized_params.json') as f:
    cfg = json.load(f)

strategy.weight_technical = cfg['signal_weights']['weight_technical']
strategy.weight_ml = cfg['signal_weights']['weight_ml']
strategy.tp_multiplier = cfg['exit_config']['tp_multiplier']
# ... etc (see PARAMETER_INTEGRATION_GUIDE.md for full code)
```

---

## 🧪 Validation Checklist (Before Live Trading)

- [ ] Does result #1 have "combined_score" > 0.6?
- [ ] Total PnL > $500?
- [ ] Sharpe > 1.0?
- [ ] Win Rate > 45%?
- [ ] Configuration file created and valid JSON?
- [ ] Bot loads config successfully?
- [ ] Paper trading for 1 week shows ±15% variance?
- [ ] No consecutive losses > 5 in paper trading?

---

## ⚠️ Red Flags

Watch out for these:

| Flag | Cause | Fix |
|------|-------|-----|
| Combined score < 0.4 | Bad parameters + market | Re-run with adjusted grid |
| Result #1-5 all different params | Overfitting | Pick more conservative (#3-5 range) |
| Sharpe < 0.8 | High variance | Increase `tp_multiplier` |
| Win Rate < 40% | Too many losers | Increase `weight_technical` |
| Total PnL low ($0-100) | Insufficient trades | Decrease `time_exit_bars` |
| Very few trades (5 total) | Parameters too tight | Loosen `tp_multiplier` |

---

## 📊 Example Top 3 (What You Want to See)

```
[1] Score: 0.7845 | Sharpe: 1.82 | WR: 58% | PF: 2.1 | PnL: $2,345
    TP: 2.0R | Trailing: 1.0R | Time: 20 bars | Tech: 0.50 | ML: 0.50
    >>> DEPLOY THIS ✅

[2] Score: 0.7721 | Sharpe: 1.78 | WR: 59% | PF: 2.0 | PnL: $2,180
    TP: 2.0R | Trailing: 1.0R | Time: 20 bars | Tech: 0.48 | ML: 0.52
    >>> Similar to #1, good sign ✅

[3] Score: 0.7612 | Sharpe: 1.74 | WR: 61% | PF: 1.9 | PnL: $2,020
    TP: 1.9R | Trailing: 1.0R | Time: 21 bars | Tech: 0.52 | ML: 0.48
    >>> Stable cluster, any works ✅
```

**Good sign:** Top 3 have similar TP (1.9-2.0R), similar Trailing (1.0R), similar Time (20-21b)

---

## ❌ Example Bad Results

```
[1] Score: 0.3821 | Sharpe: 0.42 | WR: 52% | PF: 1.1 | PnL: $145
[2] Score: 0.2104 | Sharpe: 0.18 | WR: 48% | PF: 0.9 | PnL: -$50
[3] Score: 0.1945 | Sharpe: 0.15 | WR: 46% | PF: 0.8 | PnL: -$200

>>> DON'T USE - Re-run sweep with better parameters
```

---

## 🚀 Live Deployment Checklist

After paper trading validation:

```bash
# Set position multiplier (start conservative)
export POSITION_SIZE_MULTIPLIER=0.25

# Start live trading
LIVE_TRADING=true python main.py

# Monitor for 1 week - watch for:
# ✅ Win rate > 45%
# ✅ Sharpe > 0.8
# ✅ Daily loss < $500 (backtest max × 2)

# If good: Scale to 0.50, then 1.00
# If bad: Rollback to previous config
```

---

## 📁 Key Files

| File | Purpose |
|------|---------|
| `run_parameter_sweep.py` | Main sweep engine |
| `launch_sweep.py` | Quick launcher (use this!) |
| `extract_best_params.py` | Extract #1 result to JSON |
| `config_optimized_params.json` | Config file for bot |
| `sweep_results.csv` | All results (ranked) |
| `sweep_results.json` | Detailed metrics per config |
| `heatmaps_*.png` | Visualizations (if --plot used) |

---

## 🔗 Further Reading

- **Full Guide:** [PARAMETER_SWEEP_GUIDE.md](PARAMETER_SWEEP_GUIDE.md) (40 pages, detailed)
- **Integration:** [PARAMETER_INTEGRATION_GUIDE.md](PARAMETER_INTEGRATION_GUIDE.md) (step-by-step deployment)
- **Bot Fixes:** [FILES_MODIFIED_EXACT_CHANGES.md](FILES_MODIFIED_EXACT_CHANGES.md) (previous optimizations)

---

## 🎓 Learning: What Each Parameter Does

### Signal Weights Example
**Scenario:** ML model has been trained well, gives good signals

- Set `weight_ml=0.8, weight_technical=0.2, weight_mtf=0.0`
- Result: 80% of final score comes from ML, only 20% from technicals
- Benefit: ML's accurate signals dominate
- Risk: If ML breaks, whole strategy breaks

**Scenario:** Markets are choppy, multi-timeframe confluence is critical

- Set `weight_technical=0.4, weight_ml=0.3, weight_mtf=0.3`
- Result: All 3 signals equally important (each 33%)
- Benefit: Robust across conditions
- Risk: Slower signal generation (must wait for all 3)

### Exit Parameters Example
**Scalping (tight risk/reward):**
```
tp_multiplier: 1.5R
trailing_activation: 0.3R
time_exit: 10 bars
partial_profit_levels: [(0.75R, 0.5), (1.0R, 0.3)]
```

**Trend-following (loose risk/reward):**
```
tp_multiplier: 2.5R
trailing_activation: 1.0R
time_exit: 30 bars
partial_profit_levels: [(1.5R, 0.2), (2.0R, 0.2)]
```

---

## 💡 Pro Tips

1. **Run sweep at market close** → Don't interrupt live trading
2. **Use --quick first** → Verify everything works before 2-4 hour run
3. **Compare to previous params** → Is new config really better? By how much?
4. **Paper trade 1-2 weeks** → Crucial validation step!
5. **Monitor Sharpe most closely** → Best predictor of live performance
6. **Re-optimize monthly** → Markets change; your params should too

---

## 🆘 Quick Troubleshooting

| Problem | Check | Fix |
|---------|-------|-----|
| Sweep hangs | CPU/Memory | Close other apps, reduce parameter grid |
| All cores stuck at 100% | Normal! | Just take a while for full sweep |
| Results look bad | Market data | Verify backtest data quality |
| Paper trading ≠ backtest | Spread/conditions | Use realistic spread in backtest params |
| Can't find best result | Need to export | Run: `python extract_best_params.py` |

---

**Ready?** Start with: `python launch_sweep.py --quick`

