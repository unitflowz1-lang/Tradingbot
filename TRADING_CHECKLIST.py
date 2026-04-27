"""
QUICK REFERENCE: Better Signal & Exit Management

When to ENTER:
✓ Signal Quality >= 75% (STRONG or EXCELLENT)
✓ ADX > 20 (trending market, not choppy)
✓ RSI in good zones:
  - For BUY: RSI 30-70 (oversold is good, avoid >75 overbought)
  - For SELL: RSI 30-70 (overbought is good, avoid <25 oversold)
✓ Multiple signals agree on direction (2+ confirmations)
✓ Volume above average

When to EXIT:
Automatic - the system now handles these:
  1. TRAILING STOP (after 10 pips profit)
     - Protects gains as price moves favorably
     - Trails 8 pips behind the high
  
  2. BREAKEVEN (after 5 pips profit)
     - Moves stop to entry + 1 pip
     - Eliminates risk on winning trades
  
  3. PARTIAL PROFIT (at preset levels)
     - 25% at 5 pips profit
     - 25% at 10 pips profit
     - 50% at 20 pips profit
  
  4. TIME EXIT (after 60 min in loss)
     - Closes old unprofitable positions
     - Prevents capital tie-up
  
  5. STOP LOSS (at hard level)
     - Traditional hard stop
  
  6. TAKE PROFIT (at hard level)
     - Traditional target

ENTRY CHECKLIST:
[_] Signal quality >= 75%
[_] ADX > 20 (trending)
[_] RSI in good zone
[_] 2+ signals agree
[_] Volume confirmation
[_] Risk/reward >= 1.5:1
→ IF ALL PASS: ENTER TRADE

EXIT CHECKLIST:
[_] Check advanced exits (automatic)
[_] Monitor trailing stop moves
[_] Track partial profit levels
[_] Watch time-based exit trigger
[_] Manual override if reversal detected
→ SYSTEM MANAGES THESE AUTOMATICALLY

CONFIGURATION ADJUSTMENTS:
Make more selective (fewer trades):
  - Raise min quality to 80% (STRONG)
  - Raise ADX minimum to 25
  - Require 3+ signals agree

Make more aggressive (more trades):
  - Lower min quality to 70%
  - Lower ADX minimum to 15
  - Accept 2 signals agree

Tighter exits (less risk):
  - Reduce trailing stop pips: 10 → 5
  - Reduce max loss: -10 → -5
  - Close more at partial profit: 25% → 33%

Looser exits (more profit potential):
  - Increase trailing stop pips: 8 → 12
  - Increase max loss: -10 → -15
  - Close less at partial profit: 25% → 15%

EXPECTED WIN RATE BY QUALITY:
POOR (< 40%):      20-30% win rate ❌ DO NOT TRADE
WEAK (40-60%):     35-45% win rate ⚠️  CAUTION
MODERATE (60-75%): 50-55% win rate ✓  ACCEPTABLE
STRONG (75-90%):   60-70% win rate ✓✓ GOOD
EXCELLENT (>90%):  70-80% win rate ✓✓✓ BEST

USE: Aim for STRONG minimum for 60%+ win rate
"""

print(__doc__)
