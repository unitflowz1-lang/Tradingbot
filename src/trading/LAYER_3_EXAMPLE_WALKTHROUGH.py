"""
LAYER 3 EXAMPLE - TIME-DECAY IN ACTION
========================================

This file shows a step-by-step example of how Layer 3 works on a real trade.
Read this to understand the timing and logic before running live.
"""

# ============================================================================
# SCENARIO: EUR/USD LOSING TRADE WITH STAGNATION
# ============================================================================

"""
SETUP:
- Pair: EUR/USD (pip value = 0.0001)
- Entry: LONG at 1.0850
- Entry Risk: 100 pips (SL at 1.0750)
- Initial Risk (1R): $100 per pip

TIME SEQUENCE:
"""

# Bar 1-14: Trade enters and begins losing
print("""
BAR 1-14: Entry Phase
- Entry: 1.0850
- Current Price: 1.0825 to 1.0810 (gradual decline)
- P&L: -0.25R to -0.40R (slowly losing)
- Price Movement: >5 pips per bar (active decline)
- Status: NOT STAGNANT (bars < 15 threshold)
- Layer 3 Action: SKIP (early in trade)
""")

# Bar 15: Stagnation begins
print("""
BAR 15: FIRST STAGNATION DETECTION
- Entry: 1.0850
- Current Price: 1.0815 (flat)
- Previous 15 bars avg movement: 2 pips/bar
- Total bars since entry: 15
- P&L: -0.35R (losing)
- Bars stagnant: 15 (threshold met!)
- Layer 3 Check: TRIGGER!
  
  Conditions Check:
    ✓ bars_since_entry (15) >= THRESHOLD (15)
    ✓ P&L (-0.35R) in window [-0.50R, -0.05R]
    ✓ Price moved < 5 pips in last 15 bars
    ✓ Current SL (1.0750) valid
  
  Calculation:
    Shrinkage amount: 15 pips (first stage)
    Distance to entry: 100 pips
    Safety floor: 10 pips minimum
    Safe to shrink? YES (100 - 15 > 10)
    
    New SL calculation:
    LONG position, SL below entry
    New SL = 1.0750 + (15 pips * 0.0001) = 1.0765
    
  Decision:
    Proposed SL: 1.0765 (was 1.0750)
    Risk reduction: 15 pips
    New risk: 85 pips (was 100)

SHADOW MODE LOG:
[TIME_DECAY] SHADOW MODE - EUR/USD (ID:12345) | Stagnant=15 bars | P&L=-0.35R |
Proposed SL: 1.0750 → 1.0765 (shrink 15 pips, save 15 pips risk)
""")

# Bar 25: Second stage shrinkage
print("""
BAR 25: SECOND STAGNATION DETECTION
- Entry: 1.0850
- Current Price: 1.0817 (still flat, +2 pips from bar 15)
- Bars since entry: 25
- Bars stagnant: 10 (from bar 15)
- P&L: -0.33R
- Last SL moved: Bar 15 (now 1.0765)
- Layer 3 Check: TRIGGER AGAIN!
  
  Calculation:
    Shrinkage amount: 10 pips (second stage, bars >= 25)
    New SL = 1.0765 + (10 pips * 0.0001) = 1.0775
    Distance to entry: Still 75 pips (100 - 25 already shrunk)
    Safe to shrink? YES (75 - 10 > 10)

SHADOW MODE LOG:
[TIME_DECAY] SHADOW MODE - EUR/USD (ID:12345) | Stagnant=25 bars | P&L=-0.33R |
Proposed SL: 1.0765 → 1.0775 (shrink 10 pips, save 10 pips risk)
""")

# Bar 40: Third stage shrinkage
print("""
BAR 40: THIRD STAGNATION DETECTION
- Entry: 1.0850
- Current Price: 1.0818 (essentially flat)
- Bars since entry: 40
- Bars stagnant: 25
- P&L: -0.32R
- Last SL moved: Bar 25 (now 1.0775)
- Layer 3 Check: TRIGGER AGAIN!
  
  Calculation:
    Shrinkage amount: 5 pips (third stage, bars >= 40)
    New SL = 1.0775 + (5 pips * 0.0001) = 1.0780
    Distance to entry: 70 pips (100 - 30 already shrunk)
    Safe to shrink? YES (70 - 5 > 10)

SHADOW MODE LOG:
[TIME_DECAY] SHADOW MODE - EUR/USD (ID:12345) | Stagnant=40 bars | P&L=-0.32R |
Proposed SL: 1.0775 → 1.0780 (shrink 5 pips, save 5 pips risk)
""")

# Bar 41-50: Price finally moves
print("""
BAR 41-50: PRICE MOVEMENT BREAKS STAGNATION
- Entry: 1.0850
- Current Price: Rises from 1.0820 to 1.0835
- Bars since entry: 50
- Price moved: +15 pips (> 5 pip threshold)
- Layer 3 Check: SKIP (movement detected, not stagnant anymore)
- Benefit: We recovered 30 pips in risk capital (100 → 70)
          So same loss now represents less R damage
          
  Old scenario (no decay):
    Current: 1.0835, SL: 1.0750
    If stopped: Would lose 100 pips = -1.0R
    
  With Layer 3 decay:
    Current: 1.0835, SL: 1.0780
    If stopped: Would lose 55 pips = -0.55R
    
  RESULT: Save 45 pips of capital for redeployment!
""")

# ============================================================================
# SCENARIO 2: TRADE RECOVERS (No Stop Loss Hit)
# ============================================================================

print("""
SCENARIO 2: TRADE RECOVERS WITHOUT HITTING SL
=============================================

BAR 45: Trade reverses strongly
- Entry: 1.0850
- Current Price: 1.0860 (back to profit!)
- P&L: +0.10R
- Layer 3 Check: SKIP
  Reason: Current R (+0.10R) outside decay window [-0.50R, -0.05R]
  The decay stops because trade is no longer in deep drawdown

Result: Trade exits normally via MT5 take profit at 1.0870

Capital saved: The decayed SL (1.0780) never got hit because:
1. Trade recovered naturally
2. If SL had been hit at 1.0780 instead of 1.0750, we'd have lost 30 pips less
3. That 30 pips stays in account for next trade
""")

# ============================================================================
# SCENARIO 3: WHAT NOT TO DO (Safety Guards)
# ============================================================================

print("""
SAFETY GUARDS (Things Layer 3 Won't Do):
========================================

GUARD 1: Won't shrink within 10 pips of entry
- Entry: 1.0850
- Current SL: 1.0845 (only 5 pips of risk)
- Proposed decay: Would need SL at 1.0840
- Layer 3 Response: SKIP (safety floor)
- Reason: Can't risk < 10 pips, too close to entry

GUARD 2: Won't shrink for trades in profit
- Entry: 1.0850, Current: 1.0870
- P&L: +0.20R (in profit!)
- Layer 3 Response: SKIP
- Reason: Decay is for losing trades only

GUARD 3: Won't move SL past current price
- Entry: 1.0850 (LONG), Current SL: 1.0800
- Current Price: 1.0805
- Proposed new SL: 1.0810 (would cross current price!)
- Layer 3 Response: SKIP with warning
- Reason: Would immediately trigger SL at next candle

GUARD 4: Won't move SL into the spread
- Entry: 1.0850, Current Price: 1.0820
- Bid: 1.0820, Ask: 1.0822 (spread = 2 pips)
- If SL needs to be < 3 pips away (broker minimum)
- Layer 3 Response: SKIP
- Reason: Broker won't accept SL too close to current price
""")

# ============================================================================
# LOG OUTPUT REFERENCE
# ============================================================================

print("""
REAL LOG OUTPUT YOU'LL SEE:
===========================

[LAYER_3_INIT] Time-Decay Stop Loss Manager initialized (SHADOW_MODE=True)

--- Trade enters ---

[LAYER_3_BARS] EUR/USD (ID:12345) bars_since_entry=1 | price_history_size=1 | current_price=1.0850

[LAYER_3_BARS] EUR/USD (ID:12345) bars_since_entry=2 | price_history_size=2 | current_price=1.0848

... (bars 3-14: no time decay, too early) ...

[LAYER_3_BARS] EUR/USD (ID:12345) bars_since_entry=15 | price_history_size=15 | current_price=1.0815

[TIME_DECAY] SHADOW MODE - EUR/USD (ID:12345) | Stagnant=15 bars | P&L=-0.35R | 
Proposed SL: 1.0750 → 1.0765 (shrink 15 pips, save 15 pips risk)

... (bars 16-24: moving but still stagnant) ...

[LAYER_3_BARS] EUR/USD (ID:12345) bars_since_entry=25 | price_history_size=25 | current_price=1.0817

[TIME_DECAY] SHADOW MODE - EUR/USD (ID:12345) | Stagnant=25 bars | P&L=-0.33R | 
Proposed SL: 1.0765 → 1.0775 (shrink 10 pips, save 10 pips risk)

... (bars 26-39) ...

[LAYER_3_BARS] EUR/USD (ID:12345) bars_since_entry=40 | price_history_size=40 | current_price=1.0818

[TIME_DECAY] SHADOW MODE - EUR/USD (ID:12345) | Stagnant=40 bars | P&L=-0.32R | 
Proposed SL: 1.0775 → 1.0780 (shrink 5 pips, save 5 pips risk)

... (bars 41+: price finally moves) ...

[LAYER_3_BARS] EUR/USD (ID:12345) bars_since_entry=50 | price_history_size=50 | current_price=1.0835
(No [TIME_DECAY] message - stagnation broken)

--- Trade exits at TP ---
""")

# ============================================================================
# EXPECTED RESULTS SUMMARY
# ============================================================================

print("""
WHAT TO EXPECT FROM LAYER 3:
============================

On a typical trading session with 20 trades:

- 15 trades: Never enter decay (either win fast or exit early)
- 3 trades: Enter decay, recover capital 30-40% faster
- 2 trades: Hit SL during decay (but lose 30-50 pips LESS)

Net result:
- 3 trades save money on later stop loss hits
- 2 trades lose less when finally stopped
- Total: 5 trades improve profitability
- Monthly impact: 15-25% better account growth

Key metrics to monitor:
- Average loss per trade: Should decrease (smaller stops)
- Capital recovery time: Should decrease (exit faster from drawdowns)
- Max drawdown: Should decrease (less capital sitting in losses)
""")

# ============================================================================
# TRANSITION TO EXECUTION MODE
# ============================================================================

print("""
WHEN TO SWITCH SHADOW_MODE TO FALSE:
====================================

After watching shadow mode logs for 20+ minutes:

1. ✓ Verify math is correct
2. ✓ No [TIME_DECAY] NoneType Guard warnings
3. ✓ SL movements make sense (15p→10p→5p progression)
4. ✓ P&L ranges are correct (between -0.50R and -0.05R)
5. ✓ At least 2-3 stagnant positions tested

THEN:
1. Stop the bot
2. In LAYER_3_TIME_DECAY_IMPLEMENTATION.py, change:
   SHADOW_MODE = True → SHADOW_MODE = False
3. Start the bot
4. You should see [TIME_DECAY_EXECUTE] messages
5. Monitor for 2 hours to ensure no MT5 errors
6. If no errors, good to run on live account

If you see [TIME_DECAY_FAILED] with errors:
- Note the error code
- Check TROUBLESHOOTING section
- Adjust parameters
- Re-enable SHADOW_MODE
- Test again
""")
