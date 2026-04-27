# CIRCUIT BREAKER RULES - QUICK REFERENCE
## Real-Time Overfitting Detection & Emergency Halt

**Generated**: 2026-04-15  
**Purpose**: One-page operational guide for halting bot on overfitting detection

---

## MASTER CIRCUIT BREAKER RULE

```
IF (Signal_Confluence < 40%) 
   AND 
   (ML_Accuracy < 40% OR API_Latency_P99 > 1200ms OR Spread_CV > 0.55)

THEN
   IMMEDIATE HALT
   CLOSE ALL POSITIONS (if open >5 minutes)
   ALERT OPERATOR
```

**English**: "If market signals stop agreeing (regime shift) AND infrastructure breaks down, STOP immediately."

**Expected Trigger Frequency**: 1-2 times per month (healthy, means protection working)

---

## SECONDARY CIRCUIT BREAKERS

| # | Condition | Threshold | Action | Severity |
|---|-----------|-----------|--------|----------|
| **1** | Signal Confluence Critical Low | <35% | HALT_TRADING | 🔴 CRITICAL |
| **2** | ML Accuracy Collapse | <30% | HALT_TRADING | 🔴 CRITICAL |
| **3** | API Latency P99 Extreme | >2000ms | HALT_TRADING | 🔴 CRITICAL |
| **4** | Spread Volatility Extreme | CV >0.60 | HALT_TRADING | 🔴 CRITICAL |
| **5** | Max Daily Loss Hit | -1.0% | HALT_NEW_ENTRIES | 🟠 WARNING |
| **6** | Max Drawdown Hit | -12% | HALT_ALL_TRADING | 🔴 CRITICAL |
| **7** | Quality Floor Collapse | <0.55 | REDUCE_SIZE_50% | 🟡 CAUTION |
| **8** | Regime Uncertain (ADX 20-30, RSI 40-60) | N/A | REDUCE_SIZE_25% | 🟡 CAUTION |

---

## METRIC REFERENCE TABLE

### Spread Volatility Coefficient of Variation (CV)

```
Recent 20 Trade Spreads Example:
[1.5, 1.6, 1.8, 2.1, 2.8, 3.2, 3.5, 3.8, 4.0, 4.1]

Calculation:
├─ Mean: (1.5+1.6+1.8+2.1+2.8+3.2+3.5+3.8+4.0+4.1) / 10 = 2.84
├─ Std Dev: 0.95
└─ CV = Std Dev / Mean = 0.95 / 2.84 = 0.335

Status: HEALTHY (< 0.40)
Action: CONTINUE_TRADING
```

**Alert Thresholds**:
- **< 0.25**: Healthy, stable spreads
- **0.25-0.40**: Warning, monitor
- **0.40-0.55**: Caution, reduce size
- **> 0.55**: Critical, HALT

---

### API Latency P99 Percentile

```
Recent 100 Order Latencies (milliseconds):
[45, 48, 52, 50, ..., 800, 850, 950, 1200, 1500]

Calculation:
├─ Sort all 100 values ascending
├─ P99 = Value at position 99 (99th percentile)
└─ = 1200ms (99% of orders are faster)

Status: CRITICAL (> 1200ms threshold)
Action: HALT_TRADING
```

**Alert Thresholds**:
- **< 300ms**: Healthy, instant execution
- **300-600ms**: Warning, acceptable
- **600-1200ms**: Caution, reduce frequency
- **> 1200ms**: Critical, HALT

---

### Signal Confluence Percentage

```
Recent 50 Trades - Signal Direction Agreement:

Trade 1: Tech=BUY, ML=BUY, MTF=BUY ✓ Confluent
Trade 2: Tech=BUY, ML=BUY, MTF=SELL ✗ Not confluent
Trade 3: Tech=BUY, ML=SELL, MTF=SELL ✗ Not confluent
Trade 4: Tech=SELL, ML=SELL, MTF=SELL ✓ Confluent
... (46 more trades)

Confluent Trades: 38 / 50 = 76%

Status: HEALTHY (> 70%)
Action: CONTINUE_TRADING
```

**Alert Thresholds**:
- **> 70%**: Healthy, strong signals
- **50-70%**: Warning, regime uncertainty
- **40-50%**: Caution, approaching regime shift
- **< 40%**: Critical, regime shift detected

---

### ML Accuracy Tracking

```
Last 50 Predictions vs. Actuals:

Correct: 22 predictions
Incorrect: 28 predictions
Accuracy: 22 / 50 = 44%

Status: WARNING (44% < 45% threshold)
Action: REDUCE_ML_WEIGHT, BOOST_TECHNICAL_WEIGHT
```

**Alert Thresholds**:
- **> 55%**: Excellent, high ML weight
- **50-55%**: Good, standard weights
- **45-50%**: Below breakeven, reduce ML
- **40-45%**: Low, minimize ML
- **< 40%**: Critical, ML nearly useless

---

## OPERATIONAL CHECKLIST

### Every Hour (Automated)
- [ ] Check Signal Confluence % ← Alert if <50%
- [ ] Check ML Accuracy ← Alert if <45%
- [ ] Check API Latency P99 ← Alert if >800ms
- [ ] Check Spread CV ← Alert if >0.40

### Every 4 Hours (Manual Review)
- [ ] Review circuit breaker alerts ← Any triggers?
- [ ] Check regime classification ← TRENDING or MEAN_REVERSION?
- [ ] Verify weight adjustments ← Reflect current ML accuracy?
- [ ] Inspect equity curve ← Any unexpected drawdown?

### Daily (End-of-Day)
- [ ] Review all alerts triggered today
- [ ] Check circuit breaker frequency (should be <1 per week healthy)
- [ ] Verify all positions closed correctly
- [ ] Log any manual interventions needed
- [ ] Compare backtest assumptions vs. live execution

---

## EXAMPLE ALERT SCENARIOS

### Scenario 1: Normal Operation (Green Light ✓)
```
[09:00 UTC] Hourly Metrics Check:
├─ Confluence: 72% (✓ Healthy)
├─ ML Accuracy: 53% (✓ Good)
├─ Latency P99: 250ms (✓ Fast)
├─ Spread CV: 0.28 (✓ Stable)
└─ Action: CONTINUE_TRADING (no alerts)

Expected: Smooth profits, normal drawdown
```

### Scenario 2: Regime Transition (Yellow Alert ⚠️)
```
[13:00 UTC] Hourly Metrics Check:
├─ Confluence: 62% (⚠️ Warning: declining from 72%)
├─ ML Accuracy: 48% (⚠️ Warning: approaching 45%)
├─ Latency P99: 450ms (⚠️ Warning: increased from 250ms)
├─ Spread CV: 0.38 (⚠️ Warning: approaching 0.40)
└─ Action: MONITOR_CLOSELY (no halt yet)

[13:30 UTC] Follow-up Check:
├─ Confluence: 58% (still above 40%)
├─ ML Accuracy: 46% (still above 40%)
├─ Status: YELLOW → No halt, but reduce position size by 25%
```

### Scenario 3: Market Regime Shift + Infrastructure Breakdown (Red Alert 🔴)
```
[15:00 UTC] Hourly Metrics Check:
├─ Confluence: 38% (🔴 CRITICAL: below 40% threshold)
├─ ML Accuracy: 38% (🔴 CRITICAL: below 40%)
├─ Latency P99: 1400ms (🔴 CRITICAL: above 1200ms)
├─ Spread CV: 0.58 (🔴 CRITICAL: above 0.55)

[CIRCUIT BREAKER TRIGGERS]
└─ Action: IMMEDIATE HALT
   ├─ STOP all new trades
   ├─ CLOSE positions open >5 min
   ├─ ALERT OPERATOR: "Overfitting detected - regime shift + infrastructure failure"
   └─ Reason: Master rule triggered
      (Confluence LOW AND ML_Accuracy LOW AND Latency HIGH AND Spread HIGH)

[15:05 UTC] Manual Intervention:
├─ Operator investigates broker infrastructure
├─ Discovers: Market stress event (4pm data release)
├─ Decision: Wait 30 minutes for normalization
└─ Status: HALTED (awaiting manual resume)

[15:35 UTC] Market Normalizes:
├─ Latency P99: 380ms (recovered)
├─ Spread CV: 0.32 (recovered)
├─ Confluence: 64% (recovered)
├─ ML Accuracy: 51% (recovered)
└─ Operator Decision: RESUME_TRADING (reduced size +25%)
```

---

## DEAD MAN'S SWITCH

**Condition**: Circuit breaker halted trading >60 minutes ago

**Automatic Action**:
```
[60 minutes after halt]

IF no manual RESUME_TRADING command received:
THEN
  ├─ Close all open positions (market order)
  ├─ Disable trading for 24 hours
  ├─ Alert: "DEAD_MANS_SWITCH activated - unattended halt"
  └─ Reason: Operator intervention required but not provided
```

**Prevents**: Unattended bot sitting idle during critical event, missing recovery

---

## TROUBLESHOOTING

### Q: Why did the circuit breaker halt trading?
**A**: Check the alert reason:
- `CONFLUENCE_CRITICAL`: Market regime shifted (unusual signal disagreement)
- `ML_ACCURACY_CRITICAL`: Model completely broken (retrain needed)
- `LATENCY_CRITICAL`: Broker infrastructure failing
- `SPREAD_CRITICAL`: Extreme market volatility (execution friction too high)

### Q: How do I resume trading after halt?
**A**: 
```python
# After investigating and confirming fix:
MANUAL_OVERRIDE_RESUME_TRADING = True
# OR in code:
TRADING_ENABLED = True
# Bot will resume with size reduced 50% (conservative)
```

### Q: How often should circuit breaker trigger?
**A**: Healthy frequency = **1-2 times per month**
- If 0 times per month: Maybe too loose, consider tightening
- If >4 times per month: Too many false alarms, relax thresholds
- If daily: Critical issue, investigate immediately

### Q: Can I disable the circuit breaker?
**A**: **NOT RECOMMENDED**, but possible:
```python
ANTI_OVERFITTING_CIRCUIT_BREAKER = False  # Dangerous!
# You lose protection against regime shifts
```

---

## PRODUCTION DEPLOYMENT VERIFICATION

Before going live, verify:

```
☑️ All 3 hidden variables reporting (Spread, Latency, Confluence)
☑️ Circuit breaker thresholds logged (first 5 triggers confirm thresholds)
☑️ Dead man's switch tested (halt for 61 min, verify position closure)
☑️ Alerts reaching operator (Telegram/Slack/Email working)
☑️ Regime switching working (ADX changes trigger regime switches)
☑️ Weight adjustments logging (ML accuracy changes → weight shifts visible)
☑️ Overfitting risk score calculating (showing ~7.6 for this config)
```

If all checks pass → 🚀 Production ready

---

**Document Version**: 1.0  
**Last Updated**: 2026-04-15  
**Status**: ACTIVE (Live Production)

