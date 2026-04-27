//+------------------------------------------------------------------+
//|                                              SignalGenerator.mqh |
//|                                  Copyright 2026, MetaQuotes Ltd. |
//|                                             https://www.mql5.com |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, MetaQuotes Ltd."
#property link      "https://www.mql5.com"

#include "Common.mqh"

class CSignalGenerator
  {
private:
   int               m_handle_fast;
   int               m_handle_slow;
   int               m_handle_trend;     // H1 200 EMA
   int               m_handle_atr;       // ATR Volatility
   int               m_handle_adx;       // ADX Trend Strength
   int               m_handle_rsi;       // RSI Overbought/Oversold
   int               m_handle_trend_htf; // H4 Trend Filter (200 EMA)
   int               m_handle_fractals;  // Bill Williams Fractals for Structure
   
   double            m_buffer_fast[];
   double            m_buffer_slow[];
   double            m_buffer_trend[];
   double            m_buffer_atr[];
   double            m_buffer_adx[];
   double            m_buffer_rsi[];
   double            m_buffer_trend_htf[];
   // Fractals buffers are read on-demand
   
   int               m_fast_period;
   int               m_slow_period;
   int               m_adx_period;
   int               m_rsi_period;
   
   // Filter Settings
   double            m_min_volatility; // Min ATR value
   int               m_min_adx;        // Min ADX for trend strength
   int               m_rsi_upper;      // RSI overbought level
   int               m_rsi_lower;      // RSI oversold level
   double            m_max_spread_pts; // Max spread in points
   int               m_start_hour;     // Session Start
   int               m_end_hour;       // Session End
   
   // High-Prob Settings
   double            m_min_confidence; // Minimum confidence score (0-100)
   
public:
                     CSignalGenerator() : m_fast_period(10), m_slow_period(20), m_adx_period(14), m_rsi_period(14),
                                          m_handle_fast(INVALID_HANDLE), m_handle_slow(INVALID_HANDLE),
                                          m_handle_trend(INVALID_HANDLE), m_handle_atr(INVALID_HANDLE),
                                          m_handle_adx(INVALID_HANDLE), m_handle_rsi(INVALID_HANDLE), 
                                          m_handle_trend_htf(INVALID_HANDLE), m_handle_fractals(INVALID_HANDLE),
                                          m_min_volatility(0.00010), m_min_adx(20), m_rsi_upper(70), m_rsi_lower(30),
                                          m_max_spread_pts(50), m_start_hour(8), m_end_hour(17),
                                          m_min_confidence(70.0) {}
                                          
                    ~CSignalGenerator() { ReleaseIndicators(); }

   bool              Init(int fastPeriod, int slowPeriod, double minAtr, int startHour, int endHour,
                           int adxPeriod=14, int rsiPeriod=14, double maxSpreadPts=50, int minAdx=20, double minConfidence=70.0)
     {
      m_fast_period = fastPeriod;
      m_slow_period = slowPeriod;
      m_min_volatility = minAtr;
      m_adx_period = adxPeriod;
      m_rsi_period = rsiPeriod;
      m_max_spread_pts = maxSpreadPts;
      m_min_adx = minAdx;
      m_min_confidence = minConfidence;
      
      ReleaseIndicators();
      
      // Strategy Indicators
      m_handle_fast = iMA(Symbol(), Period(), m_fast_period, 0, MODE_SMA, PRICE_CLOSE);
      m_handle_slow = iMA(Symbol(), Period(), m_slow_period, 0, MODE_SMA, PRICE_CLOSE);
      
      // Filters
      m_handle_trend = iMA(Symbol(), PERIOD_H1, 200, 0, MODE_EMA, PRICE_CLOSE);
      m_handle_atr = iATR(Symbol(), Period(), 14);
      m_handle_adx = iADX(Symbol(), Period(), m_adx_period);
      m_handle_rsi = iRSI(Symbol(), Period(), m_rsi_period, PRICE_CLOSE);
      m_handle_trend_htf = iMA(Symbol(), PERIOD_H4, 200, 0, MODE_EMA, PRICE_CLOSE);
      m_handle_fractals = iFractals(Symbol(), Period());
      
      if(m_handle_fast == INVALID_HANDLE || m_handle_slow == INVALID_HANDLE || 
         m_handle_trend == INVALID_HANDLE || m_handle_atr == INVALID_HANDLE ||
         m_handle_adx == INVALID_HANDLE || m_handle_rsi == INVALID_HANDLE || 
         m_handle_trend_htf == INVALID_HANDLE || m_handle_fractals == INVALID_HANDLE)
         return false;
         
      ArraySetAsSeries(m_buffer_fast, true);
      ArraySetAsSeries(m_buffer_slow, true);
      ArraySetAsSeries(m_buffer_trend, true);
      ArraySetAsSeries(m_buffer_atr, true);
      ArraySetAsSeries(m_buffer_adx, true);
      ArraySetAsSeries(m_buffer_rsi, true);
      ArraySetAsSeries(m_buffer_trend_htf, true);
      
      return true;
     }

   double            GetATR()
     {
      if(CopyBuffer(m_handle_atr, 0, 0, 1, m_buffer_atr) < 1) return 0.0;
      return m_buffer_atr[0];
     }

   ENUM_MARKET_REGIME GetMarketRegime()
     {
      double adx = 0;
      if(CopyBuffer(m_handle_adx, 0, 0, 1, m_buffer_adx) >= 1) adx = m_buffer_adx[0];
      
      double atr = GetATR();
      // Calculate a simple moving average of ATR if not available, but for now use current vs min_volatility
      // In a real scenario we'd use a longer ATR buffer.
      
      if(adx >= 25) return REGIME_TRENDING;
      if(atr < m_min_volatility * 1.2) return REGIME_LOW_VOLATILITY;
      return REGIME_RANGING;
     }

   ENUM_SIGNAL_TYPE  GetSignal(double &confidence_out, ENUM_TRADE_TIER &tier_out)
     {
      confidence_out = 0.0;
      tier_out = TIER_C;
      
      // 1. Mandatory Hard Filters
      if(!IsSessionOpen()) return SIGNAL_NONE;
      
      long spread = SymbolInfoInteger(Symbol(), SYMBOL_SPREAD);
      if(m_max_spread_pts > 0 && spread > m_max_spread_pts) return SIGNAL_NONE;
      
      if(CopyBuffer(m_handle_atr, 0, 0, 1, m_buffer_atr) < 1) return SIGNAL_NONE;
      if(m_buffer_atr[0] < m_min_volatility) return SIGNAL_NONE;
      
      // Update Buffers
      if(CopyBuffer(m_handle_fast, 0, 0, 2, m_buffer_fast) < 2) return SIGNAL_NONE;
      if(CopyBuffer(m_handle_slow, 0, 0, 2, m_buffer_slow) < 2) return SIGNAL_NONE;
      if(CopyBuffer(m_handle_trend, 0, 0, 1, m_buffer_trend) < 1) return SIGNAL_NONE;
      if(CopyBuffer(m_handle_adx, 0, 0, 1, m_buffer_adx) < 1) return SIGNAL_NONE;
      if(CopyBuffer(m_handle_rsi, 0, 0, 1, m_buffer_rsi) < 1) return SIGNAL_NONE;
      if(CopyBuffer(m_handle_trend_htf, 0, 0, 1, m_buffer_trend_htf) < 1) return SIGNAL_NONE;
      
      // Smart Money Trigger Logic: Trend + BOS Event
      ENUM_SIGNAL_TYPE candidate = SIGNAL_NONE;
      double closing_price = iClose(Symbol(), Period(), 1); // Last closed bar
      double prior_price = iClose(Symbol(), Period(), 2);   // Bar before that
      
      // Bullish Trend Check
      if(m_buffer_fast[0] > m_buffer_slow[0])
        {
         double swing_high = FindRecentSwing(1);
         if(swing_high > 0 && closing_price > swing_high && prior_price <= swing_high)
           {
            // Valid BOS Event (Break out)
            candidate = SIGNAL_BUY;
           }
        }
      // Bearish Trend Check
      else if(m_buffer_fast[0] < m_buffer_slow[0])
        {
         double swing_low = FindRecentSwing(-1);
         if(swing_low > 0 && closing_price < swing_low && prior_price >= swing_low)
           {
            // Valid BOS Event (Break down)
            candidate = SIGNAL_SELL;
           }
        }
      
      if(candidate == SIGNAL_NONE) return SIGNAL_NONE; 
      
      // Calculate Confidence (Must exceed threshold AND confirm BOS)
      double score = CalculateConfidence(candidate);
      confidence_out = score;
      
      // Tier Classification
      if(score >= 80) tier_out = TIER_A;
      else if(score >= 70) tier_out = TIER_B;
      else tier_out = TIER_C;
      
      if(score >= m_min_confidence)
         return candidate;
         
      return SIGNAL_NONE;
     }

    // Get Optimal SL/TP based on Swing Points & Market Context
   void GetOptimalStops(ENUM_SIGNAL_TYPE type, double &sl, double &tp, ENUM_MARKET_REGIME regime)
     {
      double point = SymbolInfoDouble(Symbol(), SYMBOL_POINT);
      int digits = (int)SymbolInfoInteger(Symbol(), SYMBOL_DIGITS);
      double ask = SymbolInfoDouble(Symbol(), SYMBOL_ASK);
      double bid = SymbolInfoDouble(Symbol(), SYMBOL_BID);
      double current_price = (type == SIGNAL_BUY) ? ask : bid;
      
      double stop_level = SymbolInfoInteger(Symbol(), SYMBOL_TRADE_STOPS_LEVEL) * point;
      double min_stop_dist = stop_level + point; // Add 1 point buffer

      // Find recent swing
      double swing_point = FindRecentSwing(type == SIGNAL_BUY ? -1 : 1); // -1 for Low, 1 for High
      
      double atr = GetATR();
      
      // Calculate SL first
      if(type == SIGNAL_BUY)
        {
         if(swing_point > 0 && swing_point < current_price) 
            sl = swing_point - (atr * 0.2); 
         else 
            sl = current_price - (atr * 3.0);
         if(current_price - sl < min_stop_dist) sl = current_price - min_stop_dist;
        }
      else
        {
         if(swing_point > 0 && swing_point > current_price) 
            sl = swing_point + (atr * 0.2); 
         else 
            sl = current_price + (atr * 3.0);
         if(sl - current_price < min_stop_dist) sl = current_price + min_stop_dist;
        }
      sl = NormalizeDouble(sl, digits);
      double risk_dist = MathAbs(current_price - sl);

      // --- NEW: Dynamic R:R based on Regime & Volatility ---
      double rr_base = 2.5; // Default
      if(regime == REGIME_TRENDING) rr_base = 3.5;       // Let winners run in trends
      else if(regime == REGIME_RANGING) rr_base = 2.0;   // Capture mid-range moves
      else if(regime == REGIME_LOW_VOLATILITY) rr_base = 1.5; // Quick exit in flat markets

      // Volatility Offset: Increase RR slightly if ATR is expanding (momentum)
      // (Very simple implementation: if ATR > previous normalized ATR, +0.2 RR)
      // For now, keep it simple with Regime-based.
      
      if(type == SIGNAL_BUY)
         tp = NormalizeDouble(current_price + (risk_dist * rr_base), digits);
      else
         tp = NormalizeDouble(current_price - (risk_dist * rr_base), digits);
         
      // Final Validation against minimum stop level
      if(type == SIGNAL_BUY)
        {
         if(ask - sl < stop_level) sl = NormalizeDouble(ask - min_stop_dist, digits);
         if(tp - ask < stop_level) tp = NormalizeDouble(ask + min_stop_dist * rr_base, digits);
        }
      else
        {
         if(sl - bid < stop_level) sl = NormalizeDouble(bid + min_stop_dist, digits);
         if(bid - tp < stop_level) tp = NormalizeDouble(bid - min_stop_dist * rr_base, digits);
        }
        
      double risk_pts = MathAbs(current_price - sl) / point;
      double reward_pts = MathAbs(tp - current_price) / point;
      PrintFormat("[DYNAMIC R:R] %s Regime: %.1fx target | Risk: %.1f pts, Reward: %.1f pts", 
                  EnumToString(regime), rr_base, risk_pts, reward_pts);
     }
      
private:
   double CalculateConfidence(ENUM_SIGNAL_TYPE type)
     {
      double score = 0;
      double h1_trend = m_buffer_trend[0];
      double h4_trend = m_buffer_trend_htf[0];
      double current_price = (type == SIGNAL_BUY) ? SymbolInfoDouble(Symbol(), SYMBOL_BID) : SymbolInfoDouble(Symbol(), SYMBOL_ASK);
      
      // 1. Multi-Timeframe Trend Alignment (+30)
      bool h1_aligned = (type == SIGNAL_BUY && current_price > h1_trend) || (type == SIGNAL_SELL && current_price < h1_trend);
      bool h4_aligned = (type == SIGNAL_BUY && current_price > h4_trend) || (type == SIGNAL_SELL && current_price < h4_trend);
      
      if(h1_aligned) score += 15;
      if(h4_aligned) score += 15;
      
      // 2. Momentum & RSI (+20)
      // ADX Strong Trend
      if(m_buffer_adx[0] > m_min_adx) score += 10;
      
      // RSI Logic: Buying in 40-60 is trending, Overbought (>70) is risky for breakout unless strong momentum.
      // Ideal Buy: 40 < RSI < 65. Ideal Sell: 35 < RSI < 60.
      bool rsi_good = false;
      if(type == SIGNAL_BUY && m_buffer_rsi[0] > 40 && m_buffer_rsi[0] < 68) rsi_good = true;
      if(type == SIGNAL_SELL && m_buffer_rsi[0] < 60 && m_buffer_rsi[0] > 32) rsi_good = true;
      
      if(rsi_good) score += 10;
      
      // 3. Structure Break (+40) - STRICT BOS ONLY AND REQUIRED
      double recent_resistance = FindRecentSwing(1); // Swing High (for Buy break)
      double recent_support = FindRecentSwing(-1);   // Swing Low (for Sell break)
      
      bool structure_break = false;
      if(type == SIGNAL_BUY)
        {
         // Break of Structure: Price > Recent High
         if(recent_resistance > 0 && current_price > recent_resistance) 
           {
            score += 40; // Significant weight for BOS
            structure_break = true;
           }
        }
      else
        {
         // Break of Structure: Price < Recent Low
         if(recent_support > 0 && current_price < recent_support) 
           {
            score += 40; // Significant weight for BOS
            structure_break = true;
           }
        }
        
      // CRITICAL: Reject if no BOS
      if(!structure_break) return 0.0;
        
      // 4. Activity & Stability Check (+10)
      // Ensure market is active but not erratic (Spike protection)
      // We need previous ATR to detect massive spike, but for now we rely on logical constraints.
      // If ATR is reasonable (not 0), pass.
      if(m_buffer_atr[0] > m_min_volatility) score += 10;
      
      // ERRATIC CHECK: If valid BOS but spread is crazy or other factors? Spread checked in GetSignal.
      
      
      // Logging
      string trendStr = (h1_aligned ? "H1 " : "") + (h4_aligned ? "H4" : "");
      if(score >= m_min_confidence)
         PrintFormat("CONFIDENCE ACCEPTED: Score=%.1f | Direction=%s | Trend=%s | ADX=%.1f | RSI=%.1f | BOS=%s", 
                     score, EnumToString(type), trendStr, m_buffer_adx[0], m_buffer_rsi[0], structure_break ? "Yes (+40)" : "No");
      
      return score;
     }

   // Direction: 1 for High, -1 for Low
   double FindRecentSwing(int direction) 
     {
      double buffer[];
      ArraySetAsSeries(buffer, true);
      int buffer_index = (direction == 1) ? 0 : 1; // 0 for High, 1 for Low in iFractals
      
      // Read 30 bars (enough for recent swing)
      if(CopyBuffer(m_handle_fractals, buffer_index, 0, 30, buffer) < 30) return 0.0;
      
      // Check bars 3 to 29 (skip 0,1,2 as determining fractal takes time/repaint protection)
      for(int i=3; i<30; i++) 
        {
         if(buffer[i] != DBL_MAX && buffer[i] != EMPTY_VALUE && buffer[i] != 0)
            return buffer[i];
        }
      return 0.0;
     }

   bool              IsSessionOpen()
     {
      datetime now = TimeCurrent();
      MqlDateTime dt;
      TimeToStruct(now, dt);
      if(dt.hour >= m_start_hour && dt.hour <= m_end_hour) return true;
      return false;
     }

    void              ReleaseIndicators()
     {
      if(m_handle_fast != INVALID_HANDLE) IndicatorRelease(m_handle_fast);
      if(m_handle_slow != INVALID_HANDLE) IndicatorRelease(m_handle_slow);
      if(m_handle_trend != INVALID_HANDLE) IndicatorRelease(m_handle_trend);
      if(m_handle_atr != INVALID_HANDLE) IndicatorRelease(m_handle_atr);
      if(m_handle_adx != INVALID_HANDLE) IndicatorRelease(m_handle_adx);
      if(m_handle_rsi != INVALID_HANDLE) IndicatorRelease(m_handle_rsi);
      if(m_handle_trend_htf != INVALID_HANDLE) IndicatorRelease(m_handle_trend_htf);
      if(m_handle_fractals != INVALID_HANDLE) IndicatorRelease(m_handle_fractals);
     }
  };
