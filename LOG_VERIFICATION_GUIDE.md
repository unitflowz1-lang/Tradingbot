# Log Verification Guide: Confidence Data-Loss Fix

This guide shows the exact log signatures you should see AFTER the fixes are applied.

---

## Before Fix (BROKEN - What You're Seeing Now)

```
13:00:00 | [TRADE_ADMISSION] USD/CHF | ... Conf: 63.4% (Admission controller has the correct confidence)
13:00:00 | [ENHANCED FILTER] USD/CHF LONG APPROVED | Score: 100.0/100
13:00:01 | [SIGNAL] USD/CHF | LONG | Entry=1.08501 | SL=1.08250 | TP=1.08752 | Confidence=0.00 ❌❌❌ (WRONG!)
13:00:01 | [POSITION_SIZING_CALC] USD/CHF | Base Size: 0.7523 lots | Confidence: 0.00x (Multiplied by ZERO!)
13:00:02 | [ZERO_SIZE_SKIPPED] USD/CHF | Position size 0.0000 <= 0. (0-lot abort!)
```

**Problem**: Confidence dropped from 63.4% → 0.00% during signal creation

---

## After Fix (CORRECT - What You'll See Post-Fix)

### ✅ Part 1: Confidence Flows Through Admission

```
13:00:00 | [TRADE_ADMISSION] USD/CHF | Regime: TRENDING | 
         | Expectancy: 2.15R | Confidence: 63.4% | 
         | Action: ADMITTED | 
         | Authority: LEVEL_3 | Depth: 40 basis points above reference
13:00:00 | [TRADE_ADMISSION] USD/CHF | RR: 2.143R | 
         | Admission Status: ADMITTED | EV: 2.15R | 
         | Penalty: 0.050 | AdjProb: 0.650
```

**Key Point**: Confidence 63.4% goes INTO the TradeAdmissionController

### ✅ Part 2: Modified Confidence Returned

```
13:00:00 | [HARD_MAPPING_RR] USD/CHF | Direct assignment: 
         | real_risk_reward_ratio = 2.143R (NO default fallback allowed) | 
         | Type: <class 'float'> | 
         | Confidence: 0.634(float from admission) ← USING ADMISSION VALUE
         | Accuracy: 0.500(float) | Value guaranteed non-default
```

**Key Point**: Signal now uses confidence value FROM the admission decision

### ✅ Part 3: SIGNAL Logs With Correct Confidence

```
13:00:01 | [SIGNAL] USD/CHF | LONG | Entry=1.08501 | SL=1.08250 | TP=1.08752 | Confidence=0.63 ✅✅✅
```

**Key Point**: Confidence did NOT drop to 0.00. It stayed at 0.63 (63%)

### ✅ Part 4: Position Opens With Correct ML Confidence Recorded

```
13:00:02 | [ML_DECAY_CTRL] Registered #56080177656 USD/CHF (ML conf: 63.4%) ✅
13:00:02 | [READY_TO_STRIKE] Risking $254.00 | USD/CHF | Size: 0.2877 lots
13:00:02 | [ACTION] Risk OK | Final Size: 0.2877 lots
```

**Key Point**: ML confidence is 63.4%, NOT 0.0%

### ✅ Part 5: Position Survives Spread, Protected By Min-Bars-Alive

```
Time 0 (Cycle 0): Trade just opened
13:00:03 | [POSITION SNAPSHOT] USD/CHF #56080177656 | Entry: 1.08501 | Current: 1.08515 (spread) | 
         | Unrealized PnL: -$2.10 (due to -1.4 pips spread loss) | Status: MonitoredStatus: Monitored

Time 1 hour later (Cycle 1):
14:01:00 | [POSITION MONITOR] USD/CHF #56080177656 | Bars Alive: 1 | PnL: -$1.80 | Status: Young, protecting...
14:01:00 | [HARVEST_BYPASS_DEFERRED] USD/CHF ID:56080177656 | Position age 1 bars < min_bars_alive 3. 
         | Skipping harvest bypass close until position establishes. ✅ PROTECTED

Time 2 hours later (Cycle 2):
15:02:00 | [POSITION MONITOR] USD/CHF #56080177656 | Bars Alive: 2 | PnL: -$0.50 | Status: Young, protecting...
15:02:00 | [HARVEST_BYPASS_DEFERRED] USD/CHF ID:56080177656 | Position age 2 bars < min_bars_alive 3. 
         | Skipping harvest bypass close until position establishes. ✅ PROTECTED

Time 3 hours later (Cycle 3):
16:03:00 | [POSITION MONITOR] USD/CHF #56080177656 | Bars Alive: 3 | PnL: +$1.45 | Status: Established, monitoring...
16:03:00 | [HARVEST_SIGNAL_STILL_VALID] USD/CHF ID:56080177656 | Negative for 0 cycles but ML confidence 63.4% 
         | has not invalidated the trade. ✅ ALIVE & PROFITABLE
```

**Key Point**: Trade survived spread slippage, position protected while young, recovered to profit

### ✅ Part 6: Position Eventually Closes At Profit

```
20:15:00 | [TP_HIT] USD/CHF #56080177656 | Closing at Take Profit: 1.08752 | PnL: +$254.07 | Bars Held: 7
```

**Key Point**: Trade held long enough to hit profit target, NOT closed at -$2 spread loss

---

## Search Patterns for Log Verification

Use these grep patterns to verify the fix is working:

### Pattern 1: Confidence Should NOT Drop to 0.00

```bash
# WRONG - Do NOT see this:
grep "\\[SIGNAL\\].*Confidence=0.00" logs/forex_bot.log
# Result should be: (no output) ✅

# RIGHT - You SHOULD see this:
grep "\\[SIGNAL\\].*Confidence=[0-9]\\.[0-9][0-9]" logs/forex_bot.log | head -5
# Result should match [TRADE_ADMISSION] confidence value
```

### Pattern 2: ML Decay Controller Should Register Non-Zero Confidence

```bash
# WRONG - Do NOT see this:
grep "\\[ML_DECAY_CTRL\\].*ML conf: 0\\.0%" logs/forex_bot.log
# Result should be: (no output) ✅

# RIGHT - You SHOULD see this:
grep "\\[ML_DECAY_CTRL\\]" logs/forex_bot.log | head -5
# Result should show: (ML conf: 42.3%) or similar non-zero values
```

### Pattern 3: Harvest Bypass Should Defer Young Positions

```bash
# RIGHT - You SHOULD see this for positions < 3 bars old:
grep "\\[HARVEST_BYPASS_DEFERRED\\].*age [012] bars" logs/forex_bot.log | head -5
# Result should show multiple deferred closes on young positions

# WRONG - Do NOT see this for positions < 3 bars:
grep "\\[HARVEST_BYPASS_CLOSE\\].*ID.*age [012]" logs/forex_bot.log
# Result should be: (no output) ✅
```

### Pattern 4: Position Sizes Should Respect Equity Calculations

```bash
# RIGHT - You SHOULD see final position sizes matching equity-based calculations:
grep "\\[POSITION_SIZE_FINAL\\].*lots" logs/forex_bot.log
# Example: [POSITION_SIZE_FINAL] USD/CHF | EquityBased: 0.2877 lots | After Floor: 0.2877 lots

# WRONG - Do NOT see artificial caps:
grep "\\[POSITION_FLOOR_ENFORCED\\]" logs/forex_bot.log
# Result should be: (no output) - floor should NOT be applied unless below 0.05
```

---

## Example: Complete Signal Flow (After Fix)

Here's the exact sequence you should see for a successful trade:

```
=== SIGNAL GENERATION (1300 UTC) ===
13:00:00 | [TRADE_ADMISSION] USD/CHF | Regime: TRENDING | Confidence: 63.4%
13:00:00 | [HARD_MAPPING_RR] USD/CHF | Confidence: 0.634(float from admission)
13:00:01 | [SIGNAL] USD/CHF | LONG | Confidence=0.63
13:00:01 | [ENHANCED FILTER] USD/CHF LONG APPROVED | Score: 100.0/100

=== POSITION SIZING (1300 UTC) ===
13:00:02 | [POSITION_SIZE_FINAL] USD/CHF | EquityBased: 0.2877 lots | After Floor: 0.2877 lots
13:00:02 | [FINAL_SIZE] USD/CHF | PositionSizer Final Output: 0.2877 lots
13:00:02 | [ACTION] Risk OK | Final Size: 0.2877 lots

=== TRADE EXECUTION (1300 UTC) ===
13:00:03 | [READY_TO_STRIKE] Risking $254.07 | USD/CHF | Size: 0.2877 lots
13:00:04 | [MT5_OPEN_TRADE] USD/CHF | Ticket: 56080177656 | Volume: 0.2877 lots | PnL: -$2.10

=== ML TRACKING (1300 UTC) ===
13:00:05 | [ML_DECAY_CTRL] Registered #56080177656 USD/CHF (ML conf: 63.4%)

=== CYCLE 1: ONE HOUR LATER (1400 UTC) ===
14:01:00 | [POSITION_MONITOR] USD/CHF #56080177656 | Bars Alive: 1 | PnL: -$1.80
14:01:00 | [HARVEST_CHECK] Unrealized: -$1.80 | Cycles negative: 1 | Threshold: 60
14:01:00 | [HARVEST_BYPASS_DEFERRED] Position age 1 bars < min_bars_alive 3

=== CYCLE 3: THREE HOURS LATER (1600 UTC) ===
16:03:00 | [POSITION_MONITOR] USD/CHF #56080177656 | Bars Alive: 3 | PnL: +$1.45 ← RECOVERED!
16:03:00 | [HARVEST_CHECK] Unrealized: +$1.45 | Status: Profitable
```

---

## Troubleshooting

### Issue: Confidence Still Shows 0.00

**Diagnosis**:
```bash
grep "\\[SIGNAL\\].*Confidence=0.00" logs/forex_bot.log | wc -l
# If count > 0: Fix not applied correctly
```

**Solution**:
1. Verify line 1210-1220 in signal_combiner.py has the fix
2. Verify line ~2192 in trade_admission_controller.py returns final_confidence
3. Check that AdmissionDecision dataclass has final_confidence field

### Issue: Positions Still Closing at 1-2 Bars

**Diagnosis**:
```bash
grep "\\[HARVEST_BYPASS_CLOSE\\]" logs/forex_bot.log | grep "age [012] bars"
# If results > 0: Min-bars-alive fix not working
```

**Solution**:
1. Verify min_bars_alive_harvest_bypass setting exists on line ~115 of profit_protection_module.py
2. Verify bars_since_opened check is between lines 913-940
3. Check for exceptions in logs: `grep "\\[HARVEST_BYPASS\\].*Failed to calculate"`

### Issue: Position Sizes Still Capped at 0.2

**Diagnosis**:
```bash
grep "\\[POSITION_SIZE_FINAL\\]" logs/forex_bot.log | awk '{print $NF}'
# If many results show 0.2: Cap not removed
```

**Solution**:
1. Verify line 6799 in main.py has `max(0.05, round(...))` WITHOUT `min(0.2, ...)`
2. Verify no other caps exist downstream

---

## Success Criteria

✅ **All of these should be TRUE after fix**:

```
1. [SIGNAL] logs show Confidence matching [TRADE_ADMISSION] value
   └─ No 0.00 confidence values
   
2. [ML_DECAY_CTRL] registers trades with non-zero ML confidence
   └─ All positions have (ML conf: XX%)
   
3. [HARVEST_BYPASS_DEFERRED] appears for positions 0-2 bars old
   └─ At least 3-5 per cycle on new trades
   
4. Trades survive 3+ bars on spread alone
   └─ Recover from initial -$2 loss to near breakeven in bars 1-2
   
5. Position sizes match PositionSizer output
   └─ No artificial 0.2 lot cap
   └─ USD/CHF trades 0.28-0.30 lots (not 0.20)
   └─ AUD/USD trades 0.30-0.35 lots (not 0.20)
   
6. Trades that recover profitable stay open
   └─ Hit take profit for +2.0-3.0R gains
   └─ Not closed at -0.5% loss after 1 bar
```

---

**Created**: April 5, 2026  
**Fix Status**: ✅ DEPLOYED & SYNTAX VALIDATED  
**Next Step**: Monitor logs during staging backtest

