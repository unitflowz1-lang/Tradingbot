//+------------------------------------------------------------------+
//|                                           StrategyController.mqh |
//|                                  Copyright 2026, MetaQuotes Ltd. |
//|                                             https://www.mql5.com |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, MetaQuotes Ltd."
#property link      "https://www.mql5.com"

#include "Common.mqh"
#include "SignalGenerator.mqh"
#include "RiskManager.mqh"
#include "TradeExecutor.mqh"
#include "StatePersister.mqh"

class CStrategyController
  {
private:
   CSignalGenerator  *m_signal;
   CRiskManager      *m_risk;
   CTradeExecutor    *m_exec;
   CStatePersister   *m_state;
   
   StrategyState      m_currentState;
   
   // Management Settings
   double             m_trailing_stop_points;
   double             m_breakeven_trigger_points;
   double             m_breakeven_step_points;
   
   // New Logic
   double             m_trailing_start_points; // Activation distance for trailing stop
   bool               m_allow_pyramiding;      // Allow adding to winners
   int                m_slippage_points;       // Slippage tolerance
   
   // Dedicated Trade object for Position Modification
   CTrade             m_trade_manager; 
   
   // Optimization: Track new bar
   datetime           m_last_bar_time;
   
   // Safety Guardrails
   int                m_max_trades_per_day;
   double             m_max_daily_loss_pct;
   int                m_cooldown_minutes;
   int                m_max_tier_c_positions; 
   double             m_max_currency_risk_pct;  // Max risk % per currency (Task 4)
   int                m_regime_stabilization;   // Bars for stabilization (Task 5)

public:
                     CStrategyController(ulong rMagic) : m_trailing_stop_points(50), 
                                                         m_breakeven_trigger_points(30), 
                                                         m_breakeven_step_points(10),
                                                         m_trailing_start_points(50),
                                                         m_allow_pyramiding(false),
                                                         m_slippage_points(10),
                                                         m_max_tier_c_positions(2),
                                                         m_max_currency_risk_pct(2.0),
                                                         m_regime_stabilization(10),
                                                         m_exec(NULL)
     {
      m_signal = new CSignalGenerator();
      m_risk = new CRiskManager();
      m_state = new CStatePersister(Symbol());
      m_trade_manager.SetExpertMagicNumber(rMagic);
      m_last_bar_time = 0;
     }

                    ~CStrategyController()
     {
      // Save state on exit
      m_state.Save(m_currentState);
      delete m_signal;
      delete m_risk;
      if(m_exec != NULL) delete m_exec;
      delete m_state;
     }

   bool              Init(int fastPeriod, int slowPeriod, double minAtr, int startHour, int endHour, 
                          double trailPoints, double trailStart, double beTrigger, double beStep,
                          bool allowPyramiding, int slippage,
                          int adxPeriod=14, int rsiPeriod=14, double maxSpread=50, int minAdx=20, double minConfidence=70.0)
     {
      // Pass filter settings to signal generator
      if(!m_signal.Init(fastPeriod, slowPeriod, minAtr, startHour, endHour, adxPeriod, rsiPeriod, maxSpread, minAdx, minConfidence))
         return false;
          
      // Initialize Executor with slippage
      if(m_exec != NULL) delete m_exec;
      m_exec = new CTradeExecutor(m_trade_manager.RequestMagic(), slippage);

      m_trailing_stop_points = trailPoints;
      m_trailing_start_points = trailStart;
      m_breakeven_trigger_points = beTrigger;
      m_breakeven_step_points = beStep;
      
      m_allow_pyramiding = allowPyramiding;
      m_slippage_points = slippage;
      m_trade_manager.SetDeviationInPoints(slippage);

      // Try load existing state
      if(m_state.Load(m_currentState))
        {
         Print("State restored. Total trades: ", m_currentState.totalTrades);
        }
      else
        {
         Print("No state found. Starting fresh.");
         m_currentState.totalTrades = 0;
         m_currentState.accumulatedProfit = 0.0;
         m_currentState.dailyTradeCount = 0;
         m_currentState.lastTradeDate = 0;
         m_currentState.sessionStartEquity = AccountInfoDouble(ACCOUNT_EQUITY);
         m_currentState.lastLossTime = 0;
         m_currentState.tradingHalted = false;
         m_currentState.haltReason = "";
         m_currentState.adaptiveConfidence = minConfidence; // Task 3
         m_currentState.lastTuneTrades = 0;
         
         // Init performance stats
         for(int r=0; r<3; r++)
            for(int t=0; t<3; t++)
              {
               m_currentState.regimeStats[r][t].trades = 0;
               m_currentState.regimeStats[r][t].wins = 0;
               m_currentState.regimeStats[r][t].profit = 0;
               m_currentState.regimeStats[r][t].win_rate = 0;
               m_currentState.regimeStats[r][t].expectancy = 0;
               m_currentState.regimeStats[r][t].learnedRR = 1.0;
               m_currentState.regimeStats[r][t].learnedRisk = 1.0;
              }
          
          m_currentState.stableRegime = REGIME_RANGING;
          m_currentState.regimeStabilityCounter = 0;
          m_currentState.equitySlope = 0.0;
          m_currentState.rollingIdx = 0;
          m_currentState.currentAggression = 1.0;
          for(int i=0; i<30; i++) m_currentState.rollingResults[i] = 0;
        }
        
      return true;
     }

   void              SetSafetyLimits(int maxTrades, double maxLossPct, int cooldownMin)
     {
      m_max_trades_per_day = maxTrades;
      m_max_daily_loss_pct = maxLossPct;
      m_cooldown_minutes = cooldownMin;
     }

   void              SetAdvancedContextSettings(double maxCurrLot, int regimeWait)
     {
      m_max_currency_risk_pct = maxCurrLot;
      m_regime_stabilization = regimeWait;
     }

   void              SetRiskSettings(double riskPercent, bool useRiskPct)
     {
      if(m_risk != NULL)
        {
         if(useRiskPct) m_risk.SetRiskPercent(riskPercent);
         else           m_risk.SetFixedLot(riskPercent); // Assuming fixed lot if not pct
        }
     }

   void              OnTick()
     {
      // 1. Manage existing positions first
      ManagePositions();
      
      // 2. Check for New Bar
      if(!IsNewBar()) return;
      
      // Check if we have enough bars
      if(Bars(Symbol(), Period()) < 100) return;

      // 3. SAFETY GUARDRAILS (CRITICAL)
      if(!CheckSafetyGuardrails()) return;

      // --- Task 5: Regime Transition Smoothing ---
      UpdateRegimeTransition();

      // --- Task 6: Equity Curve Aggression Update ---
      UpdateAggressionMultiplier();

      // --- Task 3: Auto-Tune Thresholds ---
      AutoTuneStrictness();

      double confidence = 0;
      ENUM_TRADE_TIER tier = TIER_C;
      ENUM_SIGNAL_TYPE signal = m_signal.GetSignal(confidence, tier);
      
      // Use stableRegime for most logic, but we can interpolate if needed
      ENUM_MARKET_REGIME regime = m_currentState.stableRegime;
      
      if(signal == SIGNAL_NONE) return;
      
      // Get Optimal Stops (Dynamic Calculation with Regime Context)
      double sl = 0, tp = 0;
      m_signal.GetOptimalStops(signal, sl, tp, regime);
      
      if(sl <= 0) 
        {
         Print("[ABORT] Trade execution cancelled: Invalid Stop Loss level calculated.");
         return;
        }

      // --- SELF-OPTIMIZATION: Apply Learned RR Multiplier ---
      double learnedRR = m_currentState.regimeStats[(int)regime][(int)tier].learnedRR;
      if(learnedRR != 1.0)
        {
         double entry = (signal == SIGNAL_BUY) ? SymbolInfoDouble(Symbol(), SYMBOL_ASK) : SymbolInfoDouble(Symbol(), SYMBOL_BID);
         double rewardDist = MathAbs(tp - entry);
         if(signal == SIGNAL_BUY) tp = NormalizeDouble(entry + (rewardDist * learnedRR), _Digits);
         else                     tp = NormalizeDouble(entry - (rewardDist * learnedRR), _Digits);
         PrintFormat("[LEARNED RR] Adjusted target for %s/%s: %s regime x %.2f -> RR Offset applied.", 
                     EnumToString(tier), EnumToString(regime), EnumToString(regime), learnedRR);
        }
      
      if(signal == SIGNAL_BUY) ProcessEntry(ORDER_TYPE_BUY, sl, tp, tier, regime);
      else if(signal == SIGNAL_SELL) ProcessEntry(ORDER_TYPE_SELL, sl, tp, tier, regime);
        
      // Update state if needed
      if(TimeCurrent() - m_currentState.lastTickTime > 60)
         m_currentState.lastTickTime = TimeCurrent();
     }
     
     void              AutoTuneStrictness()
     {
      // --- Stability Rules (TaskRefinement 3) ---
      // 1. Min total trades before start
      if(m_currentState.totalTrades < 30) return;
      
      // 2. Cooldown: Only tune every 20 trades to prevent oscillation
      if(m_currentState.totalTrades - m_currentState.lastTuneTrades < 20) return;

      // Regime-Segmented Tuning (Task 3)
      ENUM_MARKET_REGIME currentRegime = m_currentState.stableRegime;
      int r = (int)currentRegime;
      
      int totalTrades = 0;
      int totalWins = 0;
      for(int t=0; t<3; t++)
        {
         totalTrades += m_currentState.regimeStats[r][t].trades;
         totalWins += m_currentState.regimeStats[r][t].wins;
        }
        
      if(totalTrades >= 15) // Enough regime-specific data
        {
         double winRate = (double)totalWins / totalTrades;
         double adjustment = 0;
         
         if(winRate < 0.35) adjustment = 1.0; 
         else if(winRate > 0.55) adjustment = -1.0;
         
         if(adjustment != 0)
           {
            double oldConf = m_currentState.adaptiveConfidence;
            m_currentState.adaptiveConfidence = MathMax(60.0, MathMin(85.0, m_currentState.adaptiveConfidence + adjustment));
            
            if(oldConf != m_currentState.adaptiveConfidence)
              {
               PrintFormat("[AUTO-TUNE] %s Regime adjusted: %.1f -> %.1f (WinRate: %.1f%%)", 
                           EnumToString(currentRegime), oldConf, m_currentState.adaptiveConfidence, winRate * 100);
               m_currentState.lastTuneTrades = m_currentState.totalTrades; // Reset cooldown
               m_state.Save(m_currentState);
              }
            
            m_signal.SetMinConfidence(m_currentState.adaptiveConfidence);
           }
        }
     }

   void              ManagePositions()
     {
      for(int i=PositionsTotal()-1; i>=0; i--)
        {
         ulong ticket = PositionGetTicket(i);
         if(ticket <= 0) continue;
         if(!PositionSelectByTicket(ticket)) continue;
         if(m_exec != NULL && PositionGetInteger(POSITION_MAGIC) != m_exec.Magic()) continue; 
         
         ENUM_POSITION_TYPE type = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
         double openPrice = PositionGetDouble(POSITION_PRICE_OPEN);
         double currentSL = PositionGetDouble(POSITION_SL);
         double currentPrice = (type == POSITION_TYPE_BUY) ? SymbolInfoDouble(Symbol(), SYMBOL_BID) : SymbolInfoDouble(Symbol(), SYMBOL_ASK);
         double point = SymbolInfoDouble(Symbol(), SYMBOL_POINT);
         double stop_level = SymbolInfoInteger(Symbol(), SYMBOL_TRADE_STOPS_LEVEL) * point;
         double min_distance = stop_level + point;

         // Get Tier from Comment for Task 2 (IMMUTABLE, TaskRefinement 1)
         string comment = PositionGetString(POSITION_COMMENT);
         ENUM_TRADE_TIER tier = TIER_B; // Fallback
         if(StringFind(comment, "TIER_A") >= 0) tier = TIER_A;
         else if(StringFind(comment, "TIER_C") >= 0) tier = TIER_C;
         else if(StringFind(comment, "TIER_B") >= 0) tier = TIER_B;
         // Note: We never recompute tier here. It's read from the position metadata.

         // --- Task 2: Tier-Aware Exit Logic ---
         double be_trigger = m_breakeven_trigger_points;
         double be_step = m_breakeven_step_points;
         double trail_dist = m_trailing_stop_points;
         double trail_start = m_trailing_start_points;

         if(tier == TIER_A) // Extended runners
           {
            trail_dist *= 1.5;   // Looser trailing stop
            trail_start *= 1.5;  // Delayed activation
            be_trigger *= 2.0;   // Delayed BE to allow room
           }
         else if(tier == TIER_C) // Fast profit taking
           {
            be_trigger *= 0.6;   // Move to BE much earlier
            trail_dist *= 0.8;   // Tighter trailing
           }

         // --- Breakeven Logic ---
         if(be_trigger > 0)
           {
            if(type == POSITION_TYPE_BUY)
              {
               if(currentPrice - openPrice > be_trigger * point)
                 {
                  double newSL = openPrice + be_step * point;
                  if(newSL > currentSL && (currentPrice - newSL > min_distance))
                     m_trade_manager.PositionModify(ticket, newSL, PositionGetDouble(POSITION_TP));
                 }
              }
            else // SELL
              {
               if(openPrice - currentPrice > be_trigger * point)
                 {
                  double newSL = openPrice - be_step * point;
                  if((newSL < currentSL || currentSL == 0) && (newSL - currentPrice > min_distance))
                     m_trade_manager.PositionModify(ticket, newSL, PositionGetDouble(POSITION_TP));
                 }
              }
           }
            
         // --- Trailing Stop Logic ---
         if(trail_dist > 0)
           {
            if(type == POSITION_TYPE_BUY)
              {
               if(currentPrice - openPrice > trail_start * point) 
                 {
                  double newSL = currentPrice - trail_dist * point;
                  if(newSL > currentSL && (currentPrice - newSL > min_distance))
                     m_trade_manager.PositionModify(ticket, newSL, PositionGetDouble(POSITION_TP));
                 }
              }
            else // SELL
              {
               if(openPrice - currentPrice > trail_start * point)
                 {
                  double newSL = currentPrice + trail_dist * point;
                  if((newSL < currentSL || currentSL == 0) && (newSL - currentPrice > min_distance))
                     m_trade_manager.PositionModify(ticket, newSL, PositionGetDouble(POSITION_TP));
                 }
              }
           }
        }
      
      // Task 6: Detect closed trades to update equity metrics
      TrackClosedTrades();
     }

   void              UpdateRegimeTransition()
     {
      ENUM_MARKET_REGIME detected = m_signal.GetMarketRegime();
      
      if(detected != m_currentState.stableRegime)
        {
         if(m_currentState.regimeStabilityCounter <= 0)
           {
            m_currentState.regimeStabilityCounter = m_regime_stabilization;
            PrintFormat("[REGIME TRANSITION] Shift detected: %s -> %s. Stabilizing...", 
                        EnumToString(m_currentState.stableRegime), EnumToString(detected));
           }
         else
           {
            m_currentState.regimeStabilityCounter--;
            if(m_currentState.regimeStabilityCounter <= 0)
              {
               PrintFormat("[REGIME STABLE] Transition complete. New stable regime: %s", EnumToString(detected));
               m_currentState.stableRegime = detected;
              }
           }
        }
      else if(m_currentState.regimeStabilityCounter > 0)
        {
         m_currentState.regimeStabilityCounter = 0;
        }
     }

   void              UpdateAggressionMultiplier()
     {
      double score = 0;
      int count = 0;
      for(int i=0; i<30; i++)
        {
         if(MathAbs(m_currentState.rollingResults[i]) > 0.1)
           {
            score += m_currentState.rollingResults[i];
            count++;
           }
        }
      
      if(count < 10) m_currentState.currentAggression = 1.0;
      else
        {
         double avg = score / count; 
         double target = 1.0 + (avg * 0.2); 
         m_currentState.currentAggression = MathMax(0.7, MathMin(1.2, target));
        }
     }

   void              TrackClosedTrades()
     {
      datetime from = m_currentState.lastTradeDate;
      if(from <= 0) from = iTime(Symbol(), PERIOD_D1, 0);
      
      if(!HistorySelect(from, TimeCurrent() + 3600)) return;
      
      int total = HistoryDealsTotal();
      for(int i=total-1; i>=0; i--)
        {
         ulong dealTicket = HistoryDealGetTicket(i);
         if(dealTicket <= 0) continue;
         
         long magic = HistoryDealGetInteger(dealTicket, DEAL_MAGIC);
         if(magic != m_trade_manager.RequestMagic()) continue;
         
         long entry = HistoryDealGetInteger(dealTicket, DEAL_ENTRY);
         if(entry != DEAL_ENTRY_OUT) continue;
         
         double profit = HistoryDealGetDouble(dealTicket, DEAL_PROFIT) + HistoryDealGetDouble(dealTicket, DEAL_SWAP) + HistoryDealGetDouble(dealTicket, DEAL_COMMISSION);
         
         m_currentState.rollingResults[m_currentState.rollingIdx] = (profit > 0) ? 1.0 : -1.0;
         m_currentState.rollingIdx = (m_currentState.rollingIdx + 1) % 30;
         
         string comment = HistoryDealGetString(dealTicket, DEAL_COMMENT);
         ENUM_TRADE_TIER tier = TIER_B;
         if(StringFind(comment, "TIER_A") >= 0) tier = TIER_A;
         else if(StringFind(comment, "TIER_C") >= 0) tier = TIER_C;
         
         ENUM_MARKET_REGIME r = m_currentState.stableRegime;
         if(profit > 0) m_currentState.regimeStats[(int)r][(int)tier].wins++;
         m_currentState.regimeStats[(int)r][(int)tier].trades++;
         m_currentState.regimeStats[(int)r][(int)tier].profit += profit;
         
         // Update stats on the fly
         int n = m_currentState.regimeStats[(int)r][(int)tier].trades;
         if(n > 0)
           {
            m_currentState.regimeStats[(int)r][(int)tier].win_rate = (double)m_currentState.regimeStats[(int)r][(int)tier].wins / n;
            m_currentState.regimeStats[(int)r][(int)tier].expectancy = m_currentState.regimeStats[(int)r][(int)tier].profit / n;
           }
        }
      
      SelfOptimizeParameters();
     }

   void              SelfOptimizeParameters()
     {
      // Reinforcement Logic: Optimize every 25 total trades
      if(m_currentState.totalTrades > 0 && m_currentState.totalTrades % 25 == 0)
        {
         bool adjusted = false;
         for(int r=0; r<3; r++)
           {
            for(int t=0; t<3; t++)
              {
               PerformanceStats *stats = &m_currentState.regimeStats[r][t];
               if(stats->trades < 10) continue; // Min sample per bucket

               // If expectancy is positive, reinforce (scale up)
               if(stats->expectancy > 0)
                 {
                  stats->learnedRisk = MathMin(1.5, stats->learnedRisk + 0.05);
                  stats->learnedRR = MathMin(1.3, stats->learnedRR + 0.02);
                  adjusted = true;
                 }
               // If expectancy is negative, penalize (scale down)
               else if(stats->expectancy < 0)
                 {
                  stats->learnedRisk = MathMax(0.3, stats->learnedRisk - 0.1);
                  stats->learnedRR = MathMax(0.7, stats->learnedRR - 0.05);
                  adjusted = true;
                 }
              }
           }
         if(adjusted)
           {
            m_state.Save(m_currentState);
            Print("[SELF-OPTIMIZE] Feedback loop complete. Parameters reinforced based on performance.");
           }
        }
     }

   bool              CheckCurrencyExposure(ENUM_TRADE_TIER tier, string symbol, double lot)
     {
      string base="", quote="";
      if(StringLen(symbol) >= 6)
        {
         base = StringSubstr(symbol, 0, 3);
         quote = StringSubstr(symbol, 3, 3);
        }
      else return true; // Can't parse

      double baseExp = 0, quoteExp = 0;
      for(int i=0; i<PositionsTotal(); i++)
        {
         if(PositionSelectByTicket(PositionGetTicket(i)))
           {
            string pSym = PositionGetString(POSITION_SYMBOL);
            double pLot = PositionGetDouble(POSITION_VOLUME);
            ENUM_POSITION_TYPE pType = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
            
            if(StringFind(pSym, base) >= 0) baseExp += (pType == POSITION_TYPE_BUY ? pLot : -pLot);
            if(StringFind(pSym, quote) >= 0) quoteExp += (pType == POSITION_TYPE_BUY ? -pLot : pLot);
           }
        }
      
      // Simple lot-based cap for demonstration, could be converted to % of equity
      double maxLotPerCurr = 5.0; // Configurable
      
      // Tier A is allowed closer to limit (Task 4 requirement)
      double multiplier = (tier == TIER_A) ? 1.2 : (tier == TIER_C ? 0.8 : 1.0);
      double limit = maxLotPerCurr * multiplier;

      if(MathAbs(baseExp) > limit || MathAbs(quoteExp) > limit)
        {
         PrintFormat("[EXPOSURE BLOCK] %s or %s risk exceeded (Limit: %.2f). Tier %s rejected.", base, quote, limit, EnumToString(tier));
         return false;
        }
      return true;
     }

   void              ProcessEntry(ENUM_ORDER_TYPE order_type, double sl_price, double tp_price, ENUM_TRADE_TIER tier, ENUM_MARKET_REGIME regime)
     {
      // --- Task 1: Regime-Weighted Position Caps ---
      int max_positions = 3; // Default
      if(regime == REGIME_TRENDING) max_positions = 2; // Qualify for high risk
      else if(regime == REGIME_RANGING) max_positions = 5; // Diversity for range
      else if(regime == REGIME_LOW_VOLATILITY) max_positions = 4; // Moderate
      
      if(PositionsTotal() >= max_positions) 
        {
         PrintFormat("[REGIME CAP] Rejected entry: %s regime caps at %d positions.", EnumToString(regime), max_positions);
         return; 
        }

      // --- TaskRefinement 2: Tier Exposure Guard ---
      if(tier == TIER_C)
        {
         int tierCCount = 0;
         for(int i=0; i<PositionsTotal(); i++)
           {
            if(PositionSelectByTicket(PositionGetTicket(i)))
              {
               if(StringFind(PositionGetString(POSITION_COMMENT), "TIER_C") >= 0) tierCCount++;
              }
           }
         if(tierCCount >= m_max_tier_c_positions)
           {
            PrintFormat("[TIER GUARD] Rejected Tier C entry: Max Tier C positions (%d) reached.", m_max_tier_c_positions);
            return;
           }
        }

      // --- Pyramiding Logic (Simplified for check) ---
      if(PositionsTotal() > 0 && !m_allow_pyramiding) return;

      // 1. Calculate Risk (Using passed Dynamic SL and Tier Scaling)
      double price = (order_type == ORDER_TYPE_BUY) ? SymbolInfoDouble(Symbol(), SYMBOL_ASK) : SymbolInfoDouble(Symbol(), SYMBOL_BID);
      double lot = m_risk.CalculateLotSize(price, sl_price, regime, tier);
      
      // --- Task 6: Apply Equity-Curve Aggression Multiplier ---
      double oldLot = lot;
      lot = lot * m_currentState.currentAggression;
      
      // --- SELF-OPTIMIZATION: Apply Learned Risk Multiplier ---
      double learnedRisk = m_currentState.regimeStats[(int)regime][(int)tier].learnedRisk;
      lot = lot * learnedRisk;

      // --- Task 4: Currency Exposure Guard ---
      if(!CheckCurrencyExposure(tier, Symbol(), lot)) return;

      if(!m_risk.CheckMargin(lot, order_type)) { Print("Not enough margin."); return; }
        
      if(m_exec == NULL) m_exec = new CTradeExecutor(m_trade_manager.RequestMagic(), m_slippage_points);

      string tierStr = EnumToString(tier);
      string comment = "ModularEA_" + tierStr;

      TradeResult result;
      if(order_type == ORDER_TYPE_BUY) result = m_exec.Buy(lot, sl_price, tp_price, comment);
      else                       result = m_exec.Sell(lot, sl_price, tp_price, comment);
         
      if(result.success)
        {
         m_currentState.totalTrades++;
         m_currentState.dailyTradeCount++;
         m_currentState.regimeStats[(int)regime][(int)tier].trades++;
         m_state.Save(m_currentState);
         PrintFormat("[ENTRY] %s signal executed as %s in %s regime. Lot: %.2f (Base: %.2f, Aggression: %.2fx, LearnedRisk: %.2fx)", 
                     EnumToString(order_type), tierStr, EnumToString(regime), lot, oldLot, m_currentState.currentAggression, learnedRisk);
        }
     }

   bool              CheckSafetyGuardrails()
     {
      // 1. Reset Daily Counter at Midnight
      datetime lastDate = m_currentState.lastTradeDate;
      datetime currentDate = iTime(Symbol(), PERIOD_D1, 0);
      
      if(currentDate > lastDate)
        {
         m_currentState.dailyTradeCount = 0;
         m_currentState.sessionStartEquity = AccountInfoDouble(ACCOUNT_EQUITY);
         m_currentState.lastTradeDate = currentDate;
         m_state.Save(m_currentState);
        }
        
      // 2. Check if Trading is Halted
      if(m_currentState.tradingHalted)
        {
         PrintFormat("[HALT] Trading is halted: %s", m_currentState.haltReason);
         return false;
        }
        
      // 3. Max Trades Per Day
      if(m_currentState.dailyTradeCount >= m_max_trades_per_day)
        {
         return false;
        }
        
      // 4. Equity Protection (Daily Max Loss)
      double currentEquity = AccountInfoDouble(ACCOUNT_EQUITY);
      double startEquity = m_currentState.sessionStartEquity;
      if(startEquity > 0)
        {
         double lossPercent = (startEquity - currentEquity) / startEquity * 100.0;
         if(lossPercent >= m_max_daily_loss_pct)
           {
            m_currentState.tradingHalted = true;
            m_currentState.haltReason = "Max daily loss reached.";
            m_state.Save(m_currentState);
            PrintFormat("[CRITICAL] Max daily loss %.2f%% reached. Trading HALTED.", lossPercent);
            return false;
           }
        }
        
      // 5. Trade Cooldown After Loss
      if(m_currentState.lastLossTime > 0)
        {
         datetime currentTime = TimeCurrent();
         if(currentTime - m_currentState.lastLossTime < m_cooldown_minutes * 60)
           {
            return false;
           }
        }
        
      return true;
     }

private:
   bool              IsNewBar()
     {
      datetime current_time = iTime(Symbol(), Period(), 0);
      if(m_last_bar_time == 0) { m_last_bar_time = current_time; return false; }
      if(m_last_bar_time != current_time) { m_last_bar_time = current_time; return true; }
      return false;
     }
  };
