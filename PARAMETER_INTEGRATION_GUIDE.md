# Parameter Sweep Integration Guide

## Overview

This document explains how to:
1. Extract optimal parameters from sweep results
2. Integrate them into your trading bot
3. Test and validate in live/demo trading

---

## Step 1: Run the Sweep

```bash
# Quick test (5-10 min)
python run_parameter_sweep.py --quick --save-results

# Full sweep (2-4 hours)
python run_parameter_sweep.py --save-results --plot
```

**Output files:**
- `sweep_results.csv` - All configurations ranked by score
- `sweep_results.json` - Detailed metrics and parameters
- `heatmaps_*.png` (if `--plot` used) - Visual analysis

---

## Step 2: Extract Best Parameters

### Option A: Automatic Extraction (Recommended)

```python
# extract_best_params.py
import json
import pandas as pd
from datetime import datetime

# Read results
results_df = pd.read_csv('sweep_results.csv')
results_json = json.load(open('sweep_results.json'))

# Get top result
top_config = results_json[0]  # Highest combined_score

# Extract parameters
best_params = {
    'timestamp': datetime.now().isoformat(),
    'combined_score': top_config['combined_score'],
    'sharpe': top_config['metrics']['sharpe'],
    'win_rate': top_config['metrics']['win_rate'],
    'profit_factor': top_config['metrics']['profit_factor'],
    'total_pnl': top_config['metrics']['total_pnl'],
    
    # Signal weights
    'weight_technical': top_config['params']['weight_technical'],
    'weight_ml': top_config['params']['weight_ml'],
    'weight_mtf': top_config['params']['weight_mtf'],
    
    # Exit parameters
    'tp_multiplier': top_config['params']['tp_multiplier'],
    'trailing_activation_r': top_config['params']['trailing_activation_r'],
    'time_exit_bars': top_config['params']['time_exit_bars'],
    'partial_profit_levels': top_config['params']['partial_profit_levels'],
}

# Save for later reference
with open('optimal_params_deployed.json', 'w') as f:
    json.dump(best_params, f, indent=2)

print(f"✅ Best parameters saved:")
print(f"   Score: {best_params['combined_score']:.4f}")
print(f"   Sharpe: {best_params['sharpe']:.2f}")
print(f"   Win Rate: {best_params['win_rate']:.1f}%")
print(f"   Total PnL: ${best_params['total_pnl']:.2f}")
```

**Run it:**
```bash
python extract_best_params.py
```

### Option B: Manual Selection

If you prefer specific top-N candidates:

```python
import json

results = json.load(open('sweep_results.json'))

# Show top 5
for i, config in enumerate(results[:5], 1):
    metrics = config['metrics']
    params = config['params']
    print(f"\n[{i}] Score: {config['combined_score']:.4f} ⭐")
    print(f"    Profit: ${metrics['total_pnl']:.0f} | "
          f"Sharpe: {metrics['sharpe']:.2f} | "
          f"WR: {metrics['win_rate']:.1f}%")
    print(f"    TP: {params['tp_multiplier']}R | "
          f"Trailing: {params['trailing_activation_r']}R | "
          f"TimeExit: {params['time_exit_bars']}b")
```

---

## Step 3: Integrate into Trading Bot

### Method 1: Configuration File (Easiest)

**1a. Create params config:**
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
    "partial_profit_levels": [
      [1.0, 0.3],
      [1.5, 0.2]
    ]
  }
}
```

Save as `config_optimized_params.json`

**1b. Load in main bot:**

In `main.py` or your strategy initialization:

```python
import json

# Load optimized parameters
with open('config_optimized_params.json') as f:
    optimization_config = json.load(f)

# Apply signal weights
strategy.weight_technical = optimization_config['signal_weights']['weight_technical']
strategy.weight_ml = optimization_config['signal_weights']['weight_ml']
strategy.weight_mtf = optimization_config['signal_weights']['weight_mtf']

# Apply exit parameters
exit_config = optimization_config['exit_config']
strategy.tp_multiplier = exit_config['tp_multiplier']
strategy.trailing_activation_r = exit_config['trailing_activation_r']
strategy.time_exit_bars = exit_config['time_exit_bars']
strategy.partial_profit_levels = exit_config['partial_profit_levels']

logger.info(f"✅ Loaded optimized parameters: "
            f"TP={strategy.tp_multiplier}R, "
            f"Trailing={strategy.trailing_activation_r}R, "
            f"TimeExit={strategy.time_exit_bars}b")
```

---

### Method 2: Direct Code Modification

Find these sections in your bot and update:

**In `SimpleTrendStrategy` class initialization:**
```python
class SimpleTrendStrategy:
    def __init__(self):
        # Signal weights (OPTIMIZED)
        self.weight_technical = 0.50    # ← UPDATE HERE
        self.weight_ml = 0.50           # ← UPDATE HERE
        self.weight_mtf = 0.0           # ← UPDATE HERE
        
        # Exit parameters (OPTIMIZED)
        self.tp_multiplier = 2.0        # ← UPDATE HERE
        self.trailing_activation_r = 1.0  # ← UPDATE HERE
        self.time_exit_bars = 20        # ← UPDATE HERE
        self.partial_profit_levels = [  # ← UPDATE HERE
            (1.0, 0.3),
            (1.5, 0.2)
        ]
```

---

### Method 3: Environment Variables

**3a. Create `.env.production`:**
```bash
# Signal Weights
SIGNAL_WEIGHT_TECHNICAL=0.50
SIGNAL_WEIGHT_ML=0.50
SIGNAL_WEIGHT_MTF=0.0

# Exit Parameters
EXIT_TP_MULTIPLIER=2.0
EXIT_TRAILING_ACTIVATION_R=1.0
EXIT_TIME_EXIT_BARS=20
EXIT_PARTIAL_PROFIT_LEVELS='[[1.0, 0.3], [1.5, 0.2]]'
```

**3b. Load in bot:**
```python
import os
import json

strategy.weight_technical = float(os.getenv('SIGNAL_WEIGHT_TECHNICAL', 0.5))
strategy.weight_ml = float(os.getenv('SIGNAL_WEIGHT_ML', 0.5))
strategy.weight_mtf = float(os.getenv('SIGNAL_WEIGHT_MTF', 0.0))

strategy.tp_multiplier = float(os.getenv('EXIT_TP_MULTIPLIER', 2.0))
strategy.trailing_activation_r = float(os.getenv('EXIT_TRAILING_ACTIVATION_R', 1.0))
strategy.time_exit_bars = int(os.getenv('EXIT_TIME_EXIT_BARS', 20))
partial_str = os.getenv('EXIT_PARTIAL_PROFIT_LEVELS', '[[1.0, 0.3]]')
strategy.partial_profit_levels = json.loads(partial_str)
```

**3c. Launch bot with production config:**
```bash
source .env.production
python main.py
```

---

## Step 4: Validation Checklist

Before deploying to live trading:

- [ ] **Syntax Check**: Config file valid JSON/YAML
- [ ] **Value Ranges**: All parameters in expected ranges
  - `weight_*` between 0.0 and 1.0 ✅
  - `tp_multiplier` between 1.5R and 3.5R ✅
  - `trailing_activation_r` between 0.1R and 2.0R ✅
  - `time_exit_bars` between 10 and 50 ✅
- [ ] **Parameter Normalization**: Signal weights sum to 1.0 ✅
- [ ] **Backtest Metrics**: All > 0 significantly
  - Total PnL > $100 ✅
  - Sharpe > 1.0 ✅
  - Win Rate > 45% ✅
- [ ] **Data Points**: At least 20+ trades in backtest ✅

---

## Step 5: Paper Trading (Demo Account)

### 5a. Deploy to demo:
```bash
# Update config_optimized_params.json with optimal values
# Set PAPER_TRADING=true in .env

PAPER_TRADING=true python main.py
```

### 5b. Monitor for 1-2 weeks:
```python
# In your monitoring dashboard, track:
Backtest Metrics   vs   Paper Trading Results
───────────────────────────────────────────────
Sharpe: 1.82       vs   Actual: 1.65-1.95 ✅ (within 20%)
Win Rate: 58%      vs   Actual: 55-61% ✅ (within 5%)
PnL: $2,345        vs   Actual: $1,800-2,900 ✅ (not exact, varies)
Max DD: -$450      vs   Actual: -$400-550 ✅ (similar)
```

### 5c. Decision Matrix:
```
Paper Trading matches Backtest ±15%?
    ├─ YES → Deploy to live ✅
    ├─ NO (better) → Market is favorable, monitor closely
    └─ NO (worse) → Review market conditions, recheck config
```

---

## Step 6: Live Trading Deployment

### 6a. Initial Deployment (Conservative)
```bash
# Set LIVE_TRADING=true, POSITION_SIZE_MULTIPLIER=0.25 (start with 25%)
LIVE_TRADING=true POSITION_SIZE_MULTIPLIER=0.25 python main.py
```

Monitor for 1 week (aim for ~$500-1000/week at 25%).

### 6b. Scale if Profitable
```bash
# After week 1: If profitable and stable
LIVE_TRADING=true POSITION_SIZE_MULTIPLIER=0.50 python main.py  # Scale to 50%

# After week 2: If still profitable
LIVE_TRADING=true POSITION_SIZE_MULTIPLIER=1.00 python main.py  # Full size
```

### 6c. Abort Signals
Stop and debug if ANY of these occur:
- Daily loss > $2,000 (exceed optimization's max DD × 2)
- Win rate < 40% (drop > 15% from backtest)
- Sharpe drops below 0.8 (> 50% worse than backtest)
- Consecutive losses > 5 trades

```bash
# Emergency stop
pkill -f "python main.py"
# Review configuration and restart
```

---

## Backup & Rollback Procedure

### Save Current Working Config
```bash
# Before deploying new params, backup current state
cp config.json config.json.backup.$(date +%Y%m%d_%H%M%S)
cp .env .env.backup.$(date +%Y%m%d_%H%M%S)
```

### Rollback if Issues Occur
```bash
# Revert to previous known-good config
cp config.json.backup.[TIMESTAMP] config.json
pkill -f "python main.py"
python main.py  # Restart with previous parameters
```

---

## Monitoring & Adjustment

### Daily Monitoring
```python
# Track these metrics daily
daily_metrics = {
    'date': datetime.now().date(),
    'trades_executed': total_trades_today,
    'win_rate_today': wins_today / total_trades_today,
    'pnl_today': cumulative_pnl_today,
    'drawdown_today': max_drawdown_today,
    'avg_trade_duration': average_duration_bars,
}

# Expected ranges (from backtest)
expected = {
    'win_rate': 0.58,  # ±10%
    'pnl_per_trade': backtest_total_pnl / backtest_trades,  # ±20%
    'max_dd': 450,  # ±30%
}
```

### Weekly Review
```
At end of week:
├─ Compare 7-day metrics vs backtest
├─ If <10% variance → Continue ✅
├─ If 10-25% variance → Monitor another week
└─ If >25% variance → Debug & adjust
```

### Monthly Reoptimization
**Every 4 weeks:**
1. Re-run sweep with latest market data
2. Check if optimal parameters changed significantly
3. If Sharpe drops > 0.3 points → Update parameters
4. If parameters stable → No change needed

```bash
# Monthly reoptimization
python run_parameter_sweep.py --save-results
# Review sweep_results.json
# If top score > current score, deploy new params
```

---

## Example: Complete Integration Demo

```python
# complete_integration_example.py

import json
import logging
from typing import Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)

class OptimizedStrategyLoader:
    """Manages loading and deploying optimized parameters"""
    
    def __init__(self, params_file='config_optimized_params.json'):
        self.params_file = params_file
        self.deployed_at = None
        self.params = None
    
    def load_params(self) -> Dict[str, Any]:
        """Load optimized parameters from JSON"""
        try:
            with open(self.params_file) as f:
                self.params = json.load(f)
            logger.info(f"✅ Loaded optimized params from {self.params_file}")
            return self.params
        except FileNotFoundError:
            logger.error(f"❌ {self.params_file} not found!")
            raise
    
    def apply_to_strategy(self, strategy) -> None:
        """Apply loaded parameters to strategy object"""
        if not self.params:
            self.load_params()
        
        signal_cfg = self.params['signal_weights']
        exit_cfg = self.params['exit_config']
        
        # Apply signal weights
        strategy.weight_technical = signal_cfg['weight_technical']
        strategy.weight_ml = signal_cfg['weight_ml']
        strategy.weight_mtf = signal_cfg['weight_mtf']
        
        # Apply exit parameters
        strategy.tp_multiplier = exit_cfg['tp_multiplier']
        strategy.trailing_activation_r = exit_cfg['trailing_activation_r']
        strategy.time_exit_bars = exit_cfg['time_exit_bars']
        strategy.partial_profit_levels = exit_cfg['partial_profit_levels']
        
        self.deployed_at = datetime.now()
        
        logger.info(f"✅ Optimized params deployed at {self.deployed_at}")
        logger.info(f"   Signal Weights: "
                   f"Tech={strategy.weight_technical:.2f}, "
                   f"ML={strategy.weight_ml:.2f}, "
                   f"MTF={strategy.weight_mtf:.2f}")
        logger.info(f"   Exit Config: "
                   f"TP={strategy.tp_multiplier}R, "
                   f"Trailing={strategy.trailing_activation_r}R, "
                   f"TimeExit={strategy.time_exit_bars}b")
    
    def validate_parameters(self) -> bool:
        """Validate parameter ranges"""
        if not self.params:
            return False
        
        signal_cfg = self.params['signal_weights']
        exit_cfg = self.params['exit_config']
        
        # Check signal weights
        weights = [signal_cfg['weight_technical'], 
                  signal_cfg['weight_ml'], 
                  signal_cfg['weight_mtf']]
        
        if sum(weights) < 0.99 or sum(weights) > 1.01:
            logger.error(f"❌ Signal weights don't sum to 1.0: {sum(weights)}")
            return False
        
        # Check exit parameters
        if not (1.5 <= exit_cfg['tp_multiplier'] <= 3.5):
            logger.error(f"❌ TP multiplier out of range: {exit_cfg['tp_multiplier']}")
            return False
        
        if not (0.1 <= exit_cfg['trailing_activation_r'] <= 2.0):
            logger.error(f"❌ Trailing activation out of range")
            return False
        
        if not (10 <= exit_cfg['time_exit_bars'] <= 50):
            logger.error(f"❌ Time exit bars out of range")
            return False
        
        logger.info("✅ All parameters valid")
        return True


# Usage in main.py:
if __name__ == '__main__':
    # Initialize strategy
    strategy = SimpleTrendStrategy()
    
    # Load and apply optimized parameters
    loader = OptimizedStrategyLoader('config_optimized_params.json')
    loader.load_params()
    
    if loader.validate_parameters():
        loader.apply_to_strategy(strategy)
        # Start trading with optimized parameters
        # ...
    else:
        logger.error("Failed parameter validation!")
        exit(1)
```

---

## Troubleshooting Integration Issues

### Issue 1: "config_optimized_params.json not found"
```bash
# Make sure you ran the sweep and extraction
python run_parameter_sweep.py --save-results
python extract_best_params.py
# Check file exists:
ls -lh config_optimized_params.json
```

### Issue 2: "Invalid JSON in parameter file"
```bash
# Validate JSON syntax
python -m json.tool config_optimized_params.json
# If error shows, fix the JSON (check quotes, commas, brackets)
```

### Issue 3: "Strategy parameters don't update"
```python
# Debug: Print loaded values
with open('config_optimized_params.json') as f:
    params = json.load(f)
print("Loaded params:", params)  # Verify loaded
print("Applied to strategy:", strategy.tp_multiplier)  # Verify applied
```

### Issue 4: Paper trading performance far from backtest
Possible causes:
- **Spread changes**: Real spread ≠ backtesting spread
- **Slippage**: Live execution worse than simulated
- **Time of day**: Different market conditions vs backtest period
- **Data quality**: Backtest data unrealistic

Solution:
```bash
# Re-run sweep with realistic parameters:
# - spread_multiplier = 1.5 (if was 0.5)
# - slippage_pips = 2.0 (if was 1.0)
python run_parameter_sweep.py --save-results
python extract_best_params.py
```

---

## Success Checklist

After deployment, you should see:

- [ ] Bot loads optimized parameters on startup
- [ ] Parameters match config file values
- [ ] Paper trading for 1-2 weeks shows ±15% variance from backtest
- [ ] No errors in logs related to parameters
- [ ] Daily metrics track close to expected ranges
- [ ] Can easily switch between old/new parameters via config file
- [ ] Rollback procedure tested and working

---

**Next Steps:** Run the sweep, extract best params, and deploy to demo account!

