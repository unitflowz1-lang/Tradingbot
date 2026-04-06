//+------------------------------------------------------------------+
//|                                               StatePersister.mqh |
//|                                  Copyright 2026, MetaQuotes Ltd. |
//|                                             https://www.mql5.com |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, MetaQuotes Ltd."
#property link      "https://www.mql5.com"

#include "Common.mqh"

class CStatePersister
  {
private:
   string            m_filename;
   
public:
                     CStatePersister(string symbol)
     {
      // Unique filename per symbol/magic
      m_filename = "StrategyState_" + symbol + ".bin";
     }
                    ~CStatePersister() {}

   // Save state to disk
   bool Save(const StrategyState &state)
     {
      int handle = FileOpen(m_filename, FILE_WRITE|FILE_BIN);
      if(handle == INVALID_HANDLE)
         return false;
         
      if(FileWriteStruct(handle, state) == 0)
        {
         FileClose(handle);
         return false;
        }
        
      FileClose(handle);
      return true;
     }

   // Load state from disk
   bool Load(StrategyState &state)
     {
      // Check if file exists
      if(!FileIsExist(m_filename))
         return false;
         
      int handle = FileOpen(m_filename, FILE_READ|FILE_BIN);
      if(handle == INVALID_HANDLE)
         return false;
         
      if(FileReadStruct(handle, state) == 0)
        {
         FileClose(handle);
         return false;
        }
        
      FileClose(handle);
      return true;
     }
  };
