//+------------------------------------------------------------------+
//|                                                ModularExpert.mq5 |
//|                                  Copyright 2026, MetaQuotes Ltd. |
//|                                             https://www.mql5.com |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, MetaQuotes Ltd."
#property link      "https://www.mql5.com"
#property version   "1.20"

// Include the Strategy Controller
#include "..\..\Include\ModularEA\StrategyController.mqh"

// Inputs
input group "--- Strategy Settings ---"
input int      InpFastPeriod  = 10;          // Fast MA Period
input int      InpSlowPeriod  = 50;          // Slow MA Period
input double   InpMinAtr      = 0.00010;     // Min ATR Volatility (Filter)
input int      InpAdxPeriod   = 14;          // ADX Period
input int      InpMinAdx      = 20;          // Min ADX Value
input int      InpRsiPeriod   = 14;          // RSI Period
input double   InpMaxSpread   = 30;          // Max Spread in Points
input int      InpSlippage    = 10;          // Slippage Tolerance (Points)
input double   InpConfidence  = 70.0;        // Min Confidence Score (0-100)

input group "--- Session Settings ---"
input int      InpStartHour   = 8;           // Start Hour (Broker Time)
input int      InpEndHour     = 17;          // End Hour (Broker Time)

input group "--- Risk Management ---"
input double   InpRiskPercent = 1.0;         // Risk Percent per Trade
input bool     InpUseRiskPct  = true;        // Use Risk Percent?
input double   InpFixedLot    = 0.1;         // Fallback Fixed Lot
input int      InpMagic       = 123456;      // Magic Number
input bool     InpPyramiding  = true;        // Allow Pyramiding (Add to Winners)

input group "--- Trade Management ---"
input double   InpTrailPoints = 200;         // Trailing Stop Distance (Points)
input double   InpTrailStart  = 300;         // Trailing Stop Activation (Points Profit)
input double   InpBETrigger   = 150;         // Break-even Trigger Points
input double   InpBEStep      = 10;          // Break-even Step (Profit Lock)
// Dynamic SL/TP are now calculated automatically based on Structure

input group "--- Safety Guardrails ---"
input int      InpMaxTradesDay  = 5;         // Max Trades Per Day
input double   InpMaxDailyLoss  = 3.0;       // Max Daily Loss (% of Equity)
input int      InpCooldownMin   = 30;        // Cooldown After Loss (Minutes)

input group "--- Advanced Risk Context ---"
input double   InpMaxCurrLot    = 5.0;       // Max Net Lot per Currency
input int      InpRegimeWait    = 10;        // Regime Stabilization Bars

// Global Controller Instance
CStrategyController *ExtStrategy;

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
  {
   // Initialize Strategy Controller
   ExtStrategy = new CStrategyController(InpMagic);
   
   // Configure Risk
   ExtStrategy.SetRiskSettings(InpRiskPercent, InpUseRiskPct);
   
   // Configure Safety Guardrails
   ExtStrategy.SetSafetyLimits(InpMaxTradesDay, InpMaxDailyLoss, InpCooldownMin);
   
   // Configure Advanced Contexts
   ExtStrategy.SetAdvancedContextSettings(InpMaxCurrLot, InpRegimeWait);
   
   // Configure parameters
   // Init call matched to StrategyController::Init signature
   if(!ExtStrategy.Init(InpFastPeriod, InpSlowPeriod, InpMinAtr, InpStartHour, InpEndHour, 
                        InpTrailPoints, InpTrailStart, InpBETrigger, InpBEStep,
                        InpPyramiding, InpSlippage,
                        InpAdxPeriod, InpRsiPeriod, InpMaxSpread, InpMinAdx, InpConfidence))
     {
      Print("Failed to initialize Strategy Controller");
      return INIT_FAILED;
     }

   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   if(ExtStrategy)
     {
      delete ExtStrategy;
      ExtStrategy = NULL;
     }
  }

//+------------------------------------------------------------------+
//| Expert tick function                                             |
//+------------------------------------------------------------------+
void OnTick()
  {
   if(ExtStrategy)
     {
      ExtStrategy.OnTick();
     }
  }
//+------------------------------------------------------------------+
