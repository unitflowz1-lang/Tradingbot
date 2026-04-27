// Safety Guardrails Implementation for StrategyController
// Add this code to StrategyController.mqh

// ===== STEP 1: Add to private section (after m_last_bar_time) =====
   // Safety Guardrails
   int                m_max_trades_per_day;
   double             m_max_daily_loss_pct;
   int                m_cooldown_minutes;

// ===== STEP 2: Add SetSafetyLimits method (after SetRiskSettings) =====
   void SetSafetyLimits(int maxTradesDay, double maxDailyLossPct, int cooldownMin)
     {
      m_max_trades_per_day = maxTradesDay;
      m_max_daily_loss_pct = maxDailyLossPct;
      m_cooldown_minutes = cooldownMin;
     }

// ===== STEP 3: Add CheckSafetyGuardrails method (before OnTick or in private section) =====
   bool CheckSafetyGuardrails()
     {
      datetime currentTime = TimeCurrent();
      MqlDateTime dt;
      TimeToStruct(currentTime, dt);
      
      // 1. Reset Daily Counter at Midnight
      datetime todayDate = currentTime - (dt.hour * 3600 + dt.min * 60 + dt.sec);
      if(m_currentState.lastTradeDate != todayDate)
        {
         m_currentState.dailyTradeCount = 0;
         m_currentState.lastTradeDate = todayDate;
         m_currentState.sessionStartEquity = AccountInfoDouble(ACCOUNT_EQUITY);
         m_currentState.tradingHalted = false;
         m_currentState.haltReason = "";
         PrintFormat("[SAFETY] New trading day. Daily counter reset. Start Equity: %.2f", m_currentState.sessionStartEquity);
        }
      
      // 2. Check if Trading is Halted
      if(m_currentState.tradingHalted)
        {
         PrintFormat("[SAFETY] Trading HALTED: %s", m_currentState.haltReason);
         return false;
        }
      
      // 3. Max Trades Per Day
      if(m_currentState.dailyTradeCount >= m_max_trades_per_day)
        {
         m_currentState.tradingHalted = true;
         m_currentState.haltReason = StringFormat("Max trades/day reached (%d/%d)", m_currentState.dailyTradeCount, m_max_trades_per_day);
         PrintFormat("[SAFETY] %s - Trading halted until tomorrow", m_currentState.haltReason);
         m_state.Save(m_currentState);
         return false;
        }
      
      // 4. Equity Protection (Daily Max Loss)
      double currentEquity = AccountInfoDouble(ACCOUNT_EQUITY);
      double equityLoss = m_currentState.sessionStartEquity - currentEquity;
      double lossPercent = (equityLoss / m_currentState.sessionStart Equity) * 100.0;
      
      if(lossPercent >= m_max_daily_loss_pct)
        {
         m_currentState.tradingHalted = true;
         m_currentState.haltReason = StringFormat("Daily max loss hit: %.2f%% (Limit: %.2f%%)", lossPercent, m_max_daily_loss_pct);
         PrintFormat("[SAFETY] %s - Emergency stop activated!", m_currentState.haltReason);
         m_state.Save(m_currentState);
         return false;
        }
      
      // 5. Trade Cooldown After Loss
      if(m_currentState.lastLossTime > 0)
        {
         int minutesSinceLoss = (int)((currentTime - m_currentState.lastLossTime) / 60);
         if(minutesSinceLoss < m_cooldown_minutes)
           {
            PrintFormat("[SAFETY] Cooldown active: %d/%d minutes since last loss", minutesSinceLoss, m_cooldown_minutes);
            return false;
           }
        }
      
      return true; // All safety checks passed
     }

// ===== STEP 4: Modify OnTick (add safety check after IsNewBar) =====
   void OnTick()
     {
      // 1. Manage Open Positions (Every tick)
      ManagePositions();
      
      // 2. Check for New Bar
      if(!IsNewBar()) return;
      
      // 3. SAFETY GUARDRAILS (CRITICAL)
      if(!CheckSafetyGuardrails()) return;
      
      // Rest of OnTick code...
      if(Bars(Symbol(), Period()) < 100) return;
      
      double confidence = 0;
      ENUM_SIGNAL_TYPE signal = m_signal.GetSignal(confidence);
      
      if(signal == SIGNAL_NONE) return;
      
      double sl = 0, tp = 0;
      m_signal.GetOptimalStops(signal, sl, tp);
      
      if(signal == SIGNAL_BUY) ProcessEntry(ORDER_TYPE_BUY, sl, tp);
      else if(signal == SIGNAL_SELL) ProcessEntry(ORDER_TYPE_SELL, sl, tp);
        
      if(TimeCurrent() - m_currentState.lastTickTime > 60)
         m_currentState.lastTickTime = TimeCurrent();
     }

// ===== STEP 5: Modify ProcessEntry to update trade count =====
   void ProcessEntry(ENUM_ORDER_TYPE orderType, double sl, double tp)
     {
      // [Existing code for checking pyramiding, position count, etc.]
      
      // Calculate lot size
      double lot = m_risk.CalculateLotSize(entry_price, sl);
      
      // Execute trade
      TradeResult result;
      if(orderType == ORDER_TYPE_BUY)
         result = m_exec.Buy(lot, sl, tp, "Smart Money BOS");
      else
         result = m_exec.Sell(lot, sl, tp, "Smart Money BOS");
      
      if(result.success)
        {
         // Update counters
         m_currentState.totalTrades++;
         m_currentState.dailyTradeCount++;  // INCREMENT DAILY COUNT
         m_state.Save(m_currentState);
         
         PrintFormat("[ENTRY] Trade %d executed (Daily: %d/%d)", 
                     m_currentState.totalTrades, 
                     m_currentState.dailyTradeCount, 
                     m_max_trades_per_day);
        }
     }

// ===== STEP 6: Track Losses in ManagePositions (when position closes with loss) =====
   void ManagePositions()
     {
      for(int i=PositionsTotal()-1; i>=0; i--)
        {
         ulong ticket = PositionGetTicket(i);
         if(ticket <= 0) continue;
         
         // [Existing position management code]
         
         // When closing a position manually or via SL:
         if(shouldClose)
           {
            bool closed = m_trade_manager.PositionClose(ticket);
            if(closed)
              {
               // Check if it was a loss
               double profit = PositionGetDouble(POSITION_PROFIT);
               if(profit < 0)
                 {
                  m_currentState.lastLossTime = TimeCurrent();
                  m_state.Save(m_currentState);
                  PrintFormat("[LOSS] Loss recorded. Cooldown activated for %d minutes", m_cooldown_minutes);
                 }
              }
           }
        }
     }
