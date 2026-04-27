//+------------------------------------------------------------------+
//|                                                  RiskManager.mqh |
//|                                  Copyright 2026, MetaQuotes Ltd. |
//|                                             https://www.mql5.com |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, MetaQuotes Ltd."
#property link      "https://www.mql5.com"

class CRiskManager
  {
private:
   double            m_fixed_lot;
   double            m_risk_percent;
   bool              m_use_risk_percent;
   
public:
                     CRiskManager() : m_fixed_lot(0.01), m_risk_percent(1.0), m_use_risk_percent(false) {}
                    ~CRiskManager() {}

   void              SetFixedLot(double lots) { m_fixed_lot = lots; m_use_risk_percent = false; }
   void              SetRiskPercent(double percent) { m_risk_percent = percent; m_use_risk_percent = true; }

   double            CalculateLotSize(double entryPrice, double stopLoss, ENUM_MARKET_REGIME regime, ENUM_TRADE_TIER tier)
     {
      double base_lot = 0;
      if(!m_use_risk_percent)
         base_lot = m_fixed_lot;
      else
        {
         // Calculate based on risk % of equity
         double equity = AccountInfoDouble(ACCOUNT_EQUITY);
         double riskAmount = equity * (m_risk_percent / 100.0);
         
         double tickValue = SymbolInfoDouble(Symbol(), SYMBOL_TRADE_TICK_VALUE);
         double tickSize = SymbolInfoDouble(Symbol(), SYMBOL_TRADE_TICK_SIZE);
         
         if(tickSize == 0 || tickValue == 0) base_lot = m_fixed_lot; // Safety fallback
         else
           {
            double pointsRisk = MathAbs(entryPrice - stopLoss) / tickSize;
            base_lot = riskAmount / (pointsRisk * tickValue);
           }
        }
      
      // Dynamic Scaling based on Context
      double multiplier = 1.0;
      if(tier == TIER_A) multiplier *= 1.2;
      if(tier == TIER_C) multiplier *= 0.5;
      if(regime == REGIME_TRENDING) multiplier *= 1.3;
      if(regime == REGIME_RANGING)  multiplier *= 0.8;

      double final_lot = NormalizeLot(base_lot * multiplier);
      
      // Logging for accountability
      double riskVal = MathAbs(entryPrice - stopLoss) * final_lot * SymbolInfoDouble(Symbol(), SYMBOL_TRADE_TICK_VALUE) / SymbolInfoDouble(Symbol(), SYMBOL_TRADE_TICK_SIZE);
      double actualPct = (AccountInfoDouble(ACCOUNT_EQUITY) > 0) ? (riskVal / AccountInfoDouble(ACCOUNT_EQUITY) * 100.0) : 0;
      
      PrintFormat("[ADAPTIVE RISK] Equity: %.2f | Risk: %.2f%% | Tier: %s | Regime: %s | Final Lot: %.2f", 
                  AccountInfoDouble(ACCOUNT_EQUITY), actualPct, EnumToString(tier), EnumToString(regime), final_lot);

      return final_lot;
     }
     
   bool              CheckMargin(double lots, ENUM_ORDER_TYPE orderType)
     {
      double margin_required = 0.0;
      if(!OrderCalcMargin(orderType, Symbol(), lots, SymbolInfoDouble(Symbol(), SYMBOL_ASK), margin_required))
         return false;
         
      double free_margin = AccountInfoDouble(ACCOUNT_MARGIN_FREE);
      return (free_margin > margin_required);
     }

   double            NormalizeLot(double lot)
     {
      double step = SymbolInfoDouble(Symbol(), SYMBOL_VOLUME_STEP);
      double min = SymbolInfoDouble(Symbol(), SYMBOL_VOLUME_MIN);
      double max = SymbolInfoDouble(Symbol(), SYMBOL_VOLUME_MAX);
      
      // Round to step
      lot = step * MathFloor(lot / step);
      
      if(lot < min) lot = min;
      if(lot > max) lot = max;
      
      return lot;
     }

private:
  };
