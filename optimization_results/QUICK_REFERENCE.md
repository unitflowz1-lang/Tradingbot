# 🎯 OPTIMIZED PARAMETERS - QUICK REFERENCE CARD
## Updated: 2026-04-24 20:18:28 UTC

---

## ⚡ KEY CHANGES FROM PREVIOUS

| Parameter | OLD | NEW | Change |
|-----------|-----|-----|--------|
| ML Weight | 0.50 | **0.40** | ↓ -20% |
| Technical Weight | 0.50 | **0.55** | ↑ +10% |
| Quality Floor | 65% | **75%** | ↑ +10% |
| ADX Min | 15 | **18** | ↑ +3 |
| RSI Upper | 70 | **60** | ↓ -10 |
| ATR SL Multiplier | 2.0 | **2.5** | ↑ +25% |
| ATR TP Multiplier | 2.0 | **2.5** | ↑ +25% |
| Auto-Rotation Score | 80 | **85** | ↑ +5 |

---

## 📊 PERFORMANCE TARGETS

| Metric | Expected | Alert If | Critical If |
|--------|----------|----------|-------------|
| **Win Rate** | 60% | < 55% | < 50% |
| **Profit Factor** | 2.0 | < 1.5 | < 1.2 |
| **Sharpe Ratio** | 2.5 | < 1.8 | < 1.5 |
| **Max Drawdown** | 10% | > 12% | > 15% |
| **Monthly Trades** | 60 | < 40 | < 20 |

---

## 🎯 PAIR CLASSIFICATIONS

### 🟢 ALPHA PAIRS (Full Aggression)
- **EUR/USD** - 100% position size
- **GBP/USD** - 100% position size

### 🟡 LOW-AGGRESSION PAIRS
- **USD/JPY** - 50% position size, 80% quality floor

---

## ✅ DEPLOYMENT CHECKLIST

### Paper Trading (1-2 weeks)
- [ ] Deploy with optimized parameters
- [ ] Monitor win rate (target: 60%)
- [ ] Track max drawdown (alert: >12%)
- [ ] Verify profit factor > 1.5
- [ ] Log all trades for analysis

### Live Trading (Cautious Start)
- [ ] Start with 50% position sizes
- [ ] Run for 1 month
- [ ] Verify metrics match paper trading
- [ ] Scale to 100% if stable

---

## 🔴 STOP TRADING IF
- Drawdown > 15%
- Win Rate < 45% (30 trade rolling)
- Profit Factor < 1.2 (50 trade rolling)
- 5 consecutive losses with quality > 75%

---

## 📋 CONFIG SNIPPET

```json
{
  "signal_weights": {
    "ml_weight": 0.40,
    "technical_weight": 0.55
  },
  "entry_filters": {
    "quality_floor": 0.75,
    "adx_min": 18,
    "rsi_lower": 30,
    "rsi_upper": 60
  },
  "risk_management": {
    "atr_sl_multiplier": 2.5,
    "atr_tp_multiplier": 2.5
  },
  "logic_tuning": {
    "auto_rotation_score": 85
  }
}
```

---

## 📈 EXPECTED MONTHLY PERFORMANCE

**Account: $10,000 | Risk: 1% per trade**

| Scenario | Trades | Win Rate | Net P&L | Max DD |
|----------|--------|----------|---------|--------|
| Conservative | 40 | 58% | +$1,800 | 8% |
| **Expected** | **60** | **60%** | **+$3,600** | **10%** |
| Optimistic | 80 | 62% | +$5,600 | 12% |

---

## 🔍 MONITORING DASHBOARD

**Check Daily:**
- Current drawdown %
- Rolling win rate (last 30 trades)
- Today's P&L
- Open positions count

**Check Weekly:**
- Profit factor (last 50 trades)
- Sharpe ratio (last 100 trades)
- Alpha pair performance
- Low-aggression pair performance

**Check Monthly:**
- Total return %
- Re-optimization needed?
- Parameter drift analysis
- Alpha pair reclassification

---

## 📞 EMERGENCY CONTACTS

**If metrics breach thresholds:**
1. Reduce position sizes by 50%
2. Increase quality floor to 80%
3. Review recent trades for patterns
4. Consider pausing if drawdown > 15%
5. Re-run optimization with recent data

---

**Full Report**: optimization_results/WFA_RESULTS_SUMMARY.md  
**Detailed JSON**: optimization_results/wfa_report.json  
**Config File**: config/optimized_params.json
