//+------------------------------------------------------------------+
//|                                                TradeExecutor.mqh |
//|                                  Copyright 2026, MetaQuotes Ltd. |
//|                                             https://www.mql5.com |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, MetaQuotes Ltd."
#property link      "https://www.mql5.com"

#include <Trade\Trade.mqh>
#include "Common.mqh"

class CTradeExecutor
  {
private:
   CTrade            m_trade;
   ulong             m_magic;
   int               m_max_retries;

public:
                     CTradeExecutor(ulong magic, int slippage=10) : m_magic(magic), m_max_retries(3)
     {
      m_trade.SetExpertMagicNumber(m_magic);
      m_trade.SetMarginMode();
      m_trade.SetTypeFillingBySymbol(Symbol());
      m_trade.SetDeviationInPoints(slippage);
     }
                    ~CTradeExecutor() {}

   void              SetExpertMagicNumber(ulong magic) { m_magic = magic; m_trade.SetExpertMagicNumber(magic); }
   ulong             Magic() const { return m_magic; }

    // Execute a market buy
   TradeResult Buy(double volume, double sl, double tp, string comment="")
     {
      TradeResult result;
      result.success = false;

      // Ensure stop levels are strictly respected
      double point = SymbolInfoDouble(Symbol(), SYMBOL_POINT);
      double stop_level = SymbolInfoInteger(Symbol(), SYMBOL_TRADE_STOPS_LEVEL) * point;
      double ask = SymbolInfoDouble(Symbol(), SYMBOL_ASK);
      
      // Validation: Abort if SL is too tight or missing
      if(sl > 0 && ask - sl < stop_level) 
        {
         PrintFormat("[ERROR] SL too tight for BUY. SL=%.5f, Ask=%.5f, Level=%.5f", sl, ask, stop_level);
         return result;
        }

      // Retry loop for execution
      for(int i=0; i<m_max_retries; i++)
        {
         // Attempt to open with SL/TP
         if(m_trade.Buy(volume, Symbol(), 0, sl, tp, comment))
           {
            result.success = true;
            result.ticket = m_trade.ResultOrder();
            result.price = m_trade.ResultPrice();
            result.volume = m_trade.ResultVolume();
            
            // Post-entry Check & Fix
            VerifyAndFixStops(result.ticket, sl, tp);
            
            result.comment = "Buy Executed with Stop Protection";
            return result;
           }
         else
           {
            int error = m_trade.ResultRetcode();
            // Handle Stop Level rejections by opening without stops then modifying
            if(error == TRADE_RETCODE_INVALID_STOPS)
              {
               Print("[WARNING] Stops rejected. Opening without SL/TP and fixing...");
               if(m_trade.Buy(volume, Symbol(), 0, 0, 0, comment))
                 {
                  result.success = true;
                  result.ticket = m_trade.ResultOrder();
                  result.price = m_trade.ResultPrice();
                  result.volume = m_trade.ResultVolume();
                  VerifyAndFixStops(result.ticket, sl, tp);
                  return result;
                 }
              }

            PrintFormat("Error opening BUY: %d - %s. Retry %d/%d", error, m_trade.ResultRetcodeDescription(), i+1, m_max_retries);
            if(error == TRADE_RETCODE_REQUOTE || error == TRADE_RETCODE_PRICE_OFF) { RefreshRates(); continue; }
            break;
           }
        }
      return result;
     }

   // Execute a market sell
   TradeResult Sell(double volume, double sl, double tp, string comment="")
     {
      TradeResult result;
      result.success = false;
      
      double point = SymbolInfoDouble(Symbol(), SYMBOL_POINT);
      double stop_level = SymbolInfoInteger(Symbol(), SYMBOL_TRADE_STOPS_LEVEL) * point;
      double bid = SymbolInfoDouble(Symbol(), SYMBOL_BID);
      
      if(sl > 0 && sl - bid < stop_level)
        {
         PrintFormat("[ERROR] SL too tight for SELL. SL=%.5f, Bid=%.5f, Level=%.5f", sl, bid, stop_level);
         return result;
        }
      
      for(int i=0; i<m_max_retries; i++)
        {
         if(m_trade.Sell(volume, Symbol(), 0, sl, tp, comment))
           {
            result.success = true;
            result.ticket = m_trade.ResultOrder();
            result.price = m_trade.ResultPrice();
            result.volume = m_trade.ResultVolume();
            VerifyAndFixStops(result.ticket, sl, tp);
            result.comment = "Sell Executed with Stop Protection";
            return result;
           }
         else
           {
            int error = m_trade.ResultRetcode();
            if(error == TRADE_RETCODE_INVALID_STOPS)
              {
               Print("[WARNING] Stops rejected. Opening without SL/TP and fixing...");
               if(m_trade.Sell(volume, Symbol(), 0, 0, 0, comment))
                 {
                  result.success = true;
                  result.ticket = m_trade.ResultOrder();
                  result.price = m_trade.ResultPrice();
                  result.volume = m_trade.ResultVolume();
                  VerifyAndFixStops(result.ticket, sl, tp);
                  return result;
                 }
              }

            PrintFormat("Error opening SELL: %d - %s. Retry %d/%d", error, m_trade.ResultRetcodeDescription(), i+1, m_max_retries);
            if(error == TRADE_RETCODE_REQUOTE || error == TRADE_RETCODE_PRICE_OFF) { RefreshRates(); continue; }
            break;
           }
        }
      return result;
     }

   // Verification Logic for Missing SL/TP
   void VerifyAndFixStops(ulong ticket, double sl, double tp)
     {
      if(ticket <= 0) return;
      Sleep(100); // Wait for position to be registered
      
      if(!PositionSelectByTicket(ticket)) return;
      
      double currentSL = PositionGetDouble(POSITION_SL);
      double currentTP = PositionGetDouble(POSITION_TP);
      
      if((sl > 0 && currentSL == 0) || (tp > 0 && currentTP == 0))
        {
         PrintFormat("[ERROR] Missing SL/TP on Ticket %d. Retrying modification...", ticket);
         for(int r=0; r<3; r++) // 3 retries for modification
           {
            if(m_trade.PositionModify(ticket, sl, tp))
              {
               PrintFormat("[FIXED] Stop protection added to Ticket %d", ticket);
               return;
              }
            Sleep(200);
           }
         PrintFormat("[CRITICAL] Failed to attach SL/TP to Ticket %d after multiple retries", ticket);
        }
     }
     
private:
   void RefreshRates()
     {
      // Helper to refresh symbol info
      SymbolInfoDouble(Symbol(), SYMBOL_BID);
      SymbolInfoDouble(Symbol(), SYMBOL_ASK);
     }
  };
