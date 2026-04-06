"""
REVERSAL ENGINE - QUICK INTEGRATION CHEATSHEET
==============================================

For developers who need to integrate reversal signals into existing trading loops.
Print this. Keep it on your desk. Reference it constantly.

Version: 1.0.0
Author: Lead Quantitative Developer
"""

# ==============================================================================
# 5-MINUTE SETUP
# ==============================================================================

"""
1. COPY FILES
   ✓ src/trading/reversal_engine.py               (Core)
   ✓ src/trading/reversal_engine_integration.py   (Adapter)
   ✓ src/trading/reversal_engine_test.py          (Tests)

2. RUN TESTS
   python src/trading/reversal_engine_test.py

3. VERIFY OUTPUT
   Should end with: "# ALL TESTS PASSED ✓"

4. YOU'RE DONE
   Ready to integrate into your main loop
"""


# ==============================================================================
# IMPORTS CHEATSHEET
# ==============================================================================

"""
MINIMAL IMPORTS
===============

from src.trading.reversal_engine import (
    MarketAnalyzer,           # Feature extraction
    ReversalEngine,            # Signal generation
    ReversalExitManager,       # Exit decisions
    CooldownManager,           # Frequency control
    MockSRH,                   # Mock SRH (replace with Real SRH)
)

FULL INTEGRATION IMPORTS
========================

from src.trading.reversal_engine_integration import (
    ReversalExecutionPipeline,    # Full orchestration
    RealSRHAdapter,               # Real SRH connection
    ReversalTradeState,           # State tracking
)
from src.trading.reversal_engine import (
    MarketAnalyzer,
    ReversalEngine,
    ReversalExitManager,
    CooldownManager,
)
"""


# ==============================================================================
# MAIN TRADING LOOP TEMPLATE
# ==============================================================================

"""
PSEUDO-CODE TEMPLATE
====================

import logging
from src.trading.reversal_engine_integration import (
    ReversalExecutionPipeline, RealSRHAdapter
)

logger = logging.getLogger(__name__)

# INITIALIZATION (run once at startup)
# ====================================
def initialize_reversal_system():
    '''Initialize reversal engine and connect to SRH.'''
    
    srh_adapter = RealSRHAdapter(
        risk_governor=your_risk_governor,
        regime_detector=your_regime_detector,
        session_manager=your_session_manager,
    )
    
    pipeline = ReversalExecutionPipeline(
        srh_adapter=srh_adapter,
        execution_engine=your_execution_engine,
        position_manager=your_position_manager,
        exit_logger=your_exit_logger,
    )
    
    return pipeline


# MAIN TRADING CYCLE (runs per M1 candle)
# ========================================
def trading_cycle():
    '''Main trading cycle - called every M1 close.'''
    
    symbols = ["EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD"]
    
    # ===== PHASE 1: ENTRY GENERATION =====
    for symbol in symbols:
        # Get fresh market data
        market_df = fetch_market_data(symbol)
        
        # Analyze with reversal engine
        decision = pipeline.analyze_symbol(symbol, market_df)
        
        # If signal generated
        if decision.action != "NO_TRADE":
            logger.info(
                f"[ENTRY] {symbol} | Action: {decision.action} | "
                f"Confidence: {decision.confidence:.3f}"
            )
            
            # Check with admission controller (optional)
            if admission_controller.approve(symbol, decision):
                # Execute reversal
                trade_state = pipeline.execute_reversal(
                    symbol=symbol,
                    decision=decision,
                    entry_price=market_df['close'].iloc[-1],
                    atr=market_df['atr'].iloc[-1],
                )
                logger.info(f"[EXECUTED] {symbol}")
    
    # ===== PHASE 2: EXIT MANAGEMENT =====
    for symbol in list(pipeline.active_reversals.keys()):
        # Get latest data
        market_df = fetch_market_data(symbol)
        
        # Calculate P&L
        unrealized_r = calculate_r_multiple(symbol)
        bars_in_trade = calculate_bars_in_trade(symbol)
        
        # Evaluate exit
        exit_decision = pipeline.evaluate_position_exit(
            symbol=symbol,
            df=market_df,
            unrealized_r=unrealized_r,
            bars_in_trade=bars_in_trade,
        )
        
        # If exit triggered
        if exit_decision:
            logger.info(
                f"[EXIT] {symbol} | Action: {exit_decision.action} | "
                f"Reason: {exit_decision.reason}"
            )
            
            # Execute exit
            if exit_decision.action == "CLOSE_FULL":
                close_position(symbol, order_type="MARKET")
            elif exit_decision.action == "CLOSE_PARTIAL_50":
                close_position(symbol, quantity=size * 0.5)
            elif exit_decision.action == "MOVE_SL_BE":
                modify_stop(symbol, new_sl=entry_price)
            
            # Log exit
            pipeline.record_reversal_exit(
                symbol=symbol,
                exit_price=market_df['close'].iloc[-1],
                exit_reason=exit_decision.reason,
                pnl=calculate_pnl(symbol),
            )


# RUN FOREVER
# ===========
if __name__ == "__main__":
    pipeline = initialize_reversal_system()
    
    while is_trading():
        trading_cycle()
        sleep_until_next_m1_close()  # 60 seconds
"""


# ==============================================================================
# DECISION OUTPUT REFERENCE
# ==============================================================================

"""
ReversalDecision OBJECT
=======================

decision.action: str
  → "BUY" | "SELL" | "NO_TRADE"
  Example: if decision.action != "NO_TRADE": execute()

decision.confidence: float (0.0 to 1.0)
  → Exponential confidence (score^1.4)
  → Higher = more elite signal
  → <0.55 = filtered out (hard floor)
  Example: position_size = base_size * decision.confidence

decision.reversal_score: float (0.0 to 1.0)
  → Base composite score before confidence calculation
  → Used for historical analysis
  Example: log to database for backtesting

decision.entry_type: str
  → "aggressive" (score >= 0.75) | "conservative" | "none"
  → Controls risk sizing
  Example:
    if decision.entry_type == "aggressive":
        risk_mult = 1.5
    else:
        risk_mult = 1.0

decision.reason: str
  → Signal composition string
  → Example: "BearDiv+Climax+LiqSweep"
  → Log and use for signal quality tracking

decision.risk_adjustment: float (0.5 to 1.5 typical)
  → From SRH.get_waterfall_multiplier()
  → Scale position size by this
  → Example: final_size = base_size * risk_adjustment


ExitDecision OBJECT
====================

exit_decision.action: str
  → "CLOSE_FULL" | "CLOSE_PARTIAL_50" | "MOVE_SL_BE" | "HOLD"

exit_decision.reason: str
  → "1.0R_Target" | "1.5R_Target" | "Structural_Failure" | 
    "Time_Stall" | "Opposite_PA" | "RSI_Normalization" | ""
  → Log this for trade attribution

EXECUTION MAPPING
=================

if action == "CLOSE_FULL":
    close_position(symbol, order_type="MARKET")

elif action == "CLOSE_PARTIAL_50":
    qty = get_position_size(symbol) * 0.5
    close_position(symbol, quantity=qty, order_type="MARKET")

elif action == "MOVE_SL_BE":
    entry_price = get_entry_price(symbol)
    modify_stop_loss(symbol, new_sl=entry_price)

elif action == "HOLD":
    pass  # Keep position, continue monitoring
"""


# ==============================================================================
# DATA INPUT FORMAT
# ==============================================================================

"""
DATAFRAME STRUCTURE
===================

Your DataFrame MUST have these columns:
  
  Column         Type      Range          Example
  ─────────────────────────────────────────────────────
  open           float     price          1.0800
  high           float     price          1.0820
  low            float     price          1.0790
  close          float     price          1.0810
  tick_volume    int       >= 0           1200
  atr            float     price > 0      0.0020
  rsi            float     [0, 100]       38.5
  adx            float     [0, 100]       22.0

EXAMPLE DATAFRAME
=================

import pandas as pd

df = pd.DataFrame({
    'open':       [1.0800, 1.0805, 1.0810],
    'high':       [1.0820, 1.0825, 1.0830],
    'low':        [1.0790, 1.0800, 1.0805],
    'close':      [1.0810, 1.0815, 1.0825],
    'tick_volume': [1200, 1500, 1800],
    'atr':        [0.0020, 0.0021, 0.0019],
    'rsi':        [35, 38, 42],
    'adx':        [22, 21, 20],
})

# Calculate features
from src.trading.reversal_engine import MarketAnalyzer
df = MarketAnalyzer.calculate_features(df)

# Now df has 13 additional feature columns
"""


# ==============================================================================
# SRH ADAPTER INTERFACE
# ==============================================================================

"""
CONNECT TO YOUR SRH SYSTEM
==========================

from src.trading.reversal_engine_integration import RealSRHAdapter

srh = RealSRHAdapter(
    risk_governor=your_risk_governor,
    regime_detector=your_regime_detector,
    session_manager=your_session_manager,
)

YOUR ADAPTER MUST IMPLEMENT THESE METHODS
==========================================

1. get_regime(symbol) -> str
   Purpose: Return current market regime
   Options: "RANGING" | "HIGH_VOL" | "VOLATILE" | "STRONG_TREND"
   Effect on threshold: RANGING=0.55, others=0.65
   
   Example implementation (in your regime detector):
   def get_current_regime(symbol):
       volatility = calculate_volatility(symbol)
       trend = check_trend_strength(symbol)
       
       if trend == "STRONG": return "STRONG_TREND"
       if volatility > 2.0: return "HIGH_VOL"
       if volatility > 1.5: return "VOLATILE"
       return "RANGING"

2. get_htf_trend(symbol) -> str
   Purpose: Return higher timeframe trend
   Options: "NEUTRAL" | "STRONG_BULL" | "STRONG_BEAR"
   Effect: Prevents counter-trend reversals
   
   Example: Check 4H or D1 trend; return state

3. get_session(symbol) -> str
   Purpose: Return current trading session
   Options: "ASIA" | "LONDON" | "NEW_YORK" | "LONDON_NY_OVERLAP" | etc.
   Effect on penalty: ASIA gets -10% penalty
   
   Example: Check current hour in UTC

4. news_active(symbol) -> bool
   Purpose: Check if major news event active
   Returns: True if high-impact news
   Effect: Hard veto on ANY reversal trade
   
   Example: Query your news system

5. get_spread_metrics(symbol) -> Tuple[float, float]
   Purpose: Return (current_spread, average_spread)
   Example: (0.2 pips, 0.18 pips)
   Effect: If current > avg*1.5, apply -15% penalty

6. get_waterfall_multiplier(symbol, confidence) -> float
   Purpose: Return risk adjustment multiplier
   Returns: Float, typically 0.5 to 1.2
   Example: Return lower multiplier if portfolio risk high
   Effect: Scale position size post-decision
"""


# ==============================================================================
# COMMON MISTAKES & QUICK FIXES
# ==============================================================================

"""
❌ MISTAKE 1: Fresh DataFrame Every Cycle
──────────────────────────────────────────
WRONG:
  for symbol in symbols:
      df = fetch_last_100_candles(symbol)  # Always refetching

RIGHT:
  # Fetch once, update candle-by-candle
  dfs = {s: fetch_last_100_candles(s) for s in symbols}
  
  while is_trading():
      for symbol in symbols:
          new_candle = get_latest_candle(symbol)
          dfs[symbol] = dfs[symbol].append(new_candle)
          decision = pipeline.analyze_symbol(symbol, dfs[symbol])


❌ MISTAKE 2: Forgetting to Record Trade in Cooldown
─────────────────────────────────────────────────────
WRONG:
  decision = engine.evaluate_symbol(symbol, df)
  if decision.action != "NO_TRADE":
      execute_trade(...)
      # FORGOT cooldown.record_trade()

RIGHT:
  decision = engine.evaluate_symbol(symbol, df)
  if decision.action != "NO_TRADE":
      execute_trade(...)
      cooldown.record_trade(symbol, len(df) - 1)  # ✓


❌ MISTAKE 3: Not Tracking bars_in_trade
────────────────────────────────────────
WRONG:
  exit_decision = evaluate_exit(..., bars_in_trade=0, ...)  # Always 0!

RIGHT:
  entry_index = store_entry_index_when_opening_trade
  bars_in_trade = current_index - entry_index
  exit_decision = evaluate_exit(..., bars_in_trade=bars_in_trade, ...)


❌ MISTAKE 4: Passing Stale DataFrame to Exit Manager
──────────────────────────────────────────────────────
WRONG:
  decision = pipeline.analyze_symbol(symbol, df_from_5_minutes_ago)
  exit_decision = pipeline.evaluate_position_exit(
      ..., current_df=df_from_5_minutes_ago)  # STALE!

RIGHT:
  df_fresh = fetch_latest_data(symbol)
  decision = pipeline.analyze_symbol(symbol, df_fresh)
  exit_decision = pipeline.evaluate_position_exit(
      ..., current_df=df_fresh)  # ✓


❌ MISTAKE 5: Not Deleting from active_reversals on CLOSE_FULL
──────────────────────────────────────────────────────────────
WRONG:
  if exit_decision.action == "CLOSE_FULL":
      close_position(symbol)
      # FORGOT: del pipeline.active_reversals[symbol]

RIGHT:
  if exit_decision.action == "CLOSE_FULL":
      close_position(symbol)
      del pipeline.active_reversals[symbol]  # ✓
"""


# ==============================================================================
# MONITORING & LOGGING
# ==============================================================================

"""
KEY METRICS TO TRACK
====================

logging.info(f"[ENTRY] {symbol} | Action: {decision.action} | Conf: {decision.confidence:.3f}")
logging.info(f"[EXIT] {symbol} | Reason: {exit_decision.reason} | PnL: {pnl:.2f}")

DASHBOARD METRICS
=================

Daily:
  - Total reversals attempted: count(entries logged)
  - Success rate: count(profitable exits) / count(all exits)
  - Average win/loss: mean(winning_trades) / mean(losing_trades)
  - Sharpe ratio: std(returns) / mean(returns)

Per signal type:
  - BullDiv: win rate, avg profit, sample size
  - BearDiv: win rate, avg profit, sample size
  - Climax: win rate, avg profit, sample size
  - LiqSweep: win rate, avg profit, sample size

Risk metrics:
  - Max concurrent positions: max(len(active_reversals))
  - Max drawdown: track peak equity minus trough
  - Position multiplier (risk adjustment) average
  - Cooldown effectiveness (trades blocked)

EXPECTED STATISTICS (First 100 trades)
======================================

Conservative Setup:
  - Win Rate: 50-55%
  - Avg Winner: 1.5R
  - Avg Loser: -1.0R
  - R-multiple: +0.25R to +0.5R per trade

Aggressive Setup:
  - Win Rate: 40-45%
  - Avg Winner: 2.0R
  - Avg Loser: -1.0R
  - R-multiple: +0.4R to +0.6R per trade

If below these, investigate:
  - Is SRH adapter returning correct regime/trend?
  - Are features being calculated properly?
  - Is cooldown too aggressive?
  - Is base_threshold too high?
"""


# ==============================================================================
# INTEGRATION CHECKLIST
# ==============================================================================

"""
PRE-DEPLOYMENT CHECKLIST
========================

CODE INTEGRATION
□ Copied reversal_engine.py
□ Copied reversal_engine_integration.py
□ Ran reversal_engine_test.py (passed)
□ Updated imports in main.py

SRH ADAPTER
□ Created RealSRHAdapter with your systems
□ Implemented get_regime()
□ Implemented get_htf_trend()
□ Implemented get_session()
□ Implemented news_active()
□ Implemented get_spread_metrics()
□ Implemented get_waterfall_multiplier()
□ Tested adapter in isolation

DATA PIPELINE
□ Confirmed DataFrame has all 8 required columns
□ Confirmed features calculated (MarketAnalyzer)
□ Confirmed latest row has non-NaN features
□ Tested with synthetic data (create_synthetic_dataframe)

TRADING LOOP
□ Initialize pipeline once at startup
□ Phase 1: Entry generation per symbol
□ Phase 2: Exit management per position
□ Implemented cooldown.record_trade()
□ Confirmed bars_in_trade tracked correctly
□ Confirmed unrealized_r calculated correctly
□ Cleaning up active_reversals on CLOSE_FULL

MONITORING
□ Log entries: [ENTRY] with confidence
□ Log exits: [EXIT] with reason and PnL
□ Dashboard updating with daily stats
□ Alert system for errors/warnings

TESTING
□ Backtest with 500+ trades
□ Paper trading for 1 week
□ Check stats vs. expected ranges
□ Manual review of 10+ winners/losers
□ Verify no "too good to be true" results (overfitting)

DEPLOYMENT
□ Set initial position size to minimum (0.01 lot)
□ Enable comprehensive logging
□ Monitor hourly for issues
□ Gradually increase position size as confidence builds
□ Document all tweaks and results
"""


# ==============================================================================
# USEFUL ONE-LINERS FOR TESTING
# ==============================================================================

"""
QUICK TESTS (Copy-paste into Python)
=====================================

# Test 1: Run all tests
python src/trading/reversal_engine_test.py

# Test 2: Syntax check
python -m py_compile src/trading/reversal_engine.py

# Test 3: Import check
python -c "from src.trading.reversal_engine import *; print('✓ Imports OK')"

# Test 4: Feature calculation
python -c "
from src.trading.reversal_engine import MarketAnalyzer, create_synthetic_dataframe
df = create_synthetic_dataframe(50)
df = MarketAnalyzer.calculate_features(df)
print(f'✓ Features calculated: {len(df.columns)} columns')
"

# Test 5: Engine initialization
python -c "
from src.trading.reversal_engine import ReversalEngine, MockSRH
engine = ReversalEngine(MockSRH())
print('✓ Engine initialized')
"

# Test 6: Adapter check
python -c "
from src.trading.reversal_engine_integration import RealSRHAdapter
adapter = RealSRHAdapter()
print(f'Regime: {adapter.get_regime(\"EUR/USD\")}')
print(f'HTF: {adapter.get_htf_trend(\"EUR/USD\")}')
print('✓ Adapter responds')
"
"""


# ==============================================================================
# CONTACT & SUPPORT
# ==============================================================================

"""
QUESTIONS?
==========

1. Read REVERSAL_ENGINE_DOCUMENTATION.md (comprehensive guide)
2. Review src/trading/reversal_engine_test.py (test examples)
3. Check docstrings: help(ReversalEngine.evaluate_symbol)
4. Search codebase for similar patterns in existing exit handlers
5. Run tests with high logging verbosity for detailed output

DEBUGGING CHECKLIST
===================

If signals aren't working:
  1. Verify DataFrame columns: print(df.columns.tolist())
  2. Check latest feature values: print(df.iloc[-1])
  3. Verify regime: print(srh_adapter.get_regime(symbol))
  4. Check base_threshold: print(f"Base: {base_threshold}")
  5. Manual evaluation: decision = engine.evaluate_symbol(...)

If exits aren't triggering:
  1. Log bars_in_trade: print(f"Bars: {bars_in_trade}")
  2. Log unrealized_r: print(f"R: {unrealized_r}")
  3. Check exit conditions are met exactly
  4. Add print statements to ReversalExitManager.evaluate_exit()

Success indicators:
  ✓ Signals generated on first few trades
  ✓ Confidence values in 0.5-0.9 range
  ✓ Win rate 40-55%
  ✓ Exits triggering as expected
  ✓ Logs showing [REVERSAL_DETECTED] and [DYNAMIC_EXIT]
"""
