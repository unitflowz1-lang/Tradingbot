//+------------------------------------------------------------------+
//|                                                       Common.mqh |
//|                                  Copyright 2026, MetaQuotes Ltd. |
//|                                             https://www.mql5.com |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, MetaQuotes Ltd."
#property link      "https://www.mql5.com"

// Signal directions
enum ENUM_SIGNAL_TYPE
  {
   SIGNAL_NONE,
   SIGNAL_BUY,
   SIGNAL_SELL,
   SIGNAL_CLOSE_BUY,
   SIGNAL_CLOSE_SELL
  };

// Market regimes
enum ENUM_MARKET_REGIME
  {
   REGIME_TRENDING,
   REGIME_RANGING,
   REGIME_LOW_VOLATILITY
  };

// Trade quality tiers
enum ENUM_TRADE_TIER
  {
   TIER_A, // Elite
   TIER_B, // Standard
   TIER_C  // Exploratory
  };

// Execution results
struct TradeResult
  {
   bool              success;
   ulong             ticket;
   double            price;
   double            volume;
   string            comment;
  };

// Performance metrics for auto-tuning
struct PerformanceStats
  {
   int               trades;
   int               wins;
   double            profit;
   double            win_rate;
   double            expectancy;        // Avg profit per trade
   double            learnedRR;         // Self-optimized RR multiplier
   double            learnedRisk;       // Self-optimized Risk multiplier
  };

// State structure for persistence
struct StrategyState
  {
   datetime          lastTickTime;
   int               totalTrades;
   double            accumulatedProfit;
   
   // Safety Guardrails
   int               dailyTradeCount;        // Trades executed today
   datetime          lastTradeDate;          // Date of last trade (for daily reset)
   double            sessionStartEquity;     // Equity at session start (for max loss check)
   datetime          lastLossTime;           // Timestamp of last losing trade (for cooldown)
   bool              tradingHalted;          // Emergency stop flag
   string            haltReason;             // Why trading was halted

   // Adaptive Strictness (Task 3)
   double            adaptiveConfidence;     // Current threshold, auto-adjusted
   int               lastTuneTrades;         // Trade count when last tuned
   PerformanceStats  regimeStats[3][3];      // [Regime][Tier]

   // Task Refinement 4+: Regime Transition & Smoothing
   ENUM_MARKET_REGIME stableRegime;          // The regime we are "stable" in
   int               regimeStabilityCounter; // Bars remaining in stabilization window
   
   // Task Refinement 4+: Equity-Curve Aggression
   double            equitySlope;            // Rolling performance slope
   double            rollingResults[30];     // Last 30 trade results (1.0 = win, -1.0 = loss/scaled)
   int               rollingIdx;             
   double            currentAggression;      // Calculated multiplier (0.7x - 1.2x)
  };
