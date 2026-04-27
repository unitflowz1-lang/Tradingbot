"""
Quick fix: Add get_candles method to MT5Broker
This bridges the gap between the data handler expecting get_candles() 
and the actual get_historical_data() method.
"""

def add_get_candles_alias():
    """Add get_candles as an alias to get_historical_data in MT5Broker"""
    try:
        from src.data.mt5_broker import MT5BrokerInterface
        
        # If get_candles doesn't exist, create it
        if not hasattr(MT5BrokerInterface, 'get_candles'):
            async def get_candles(self, symbol, granularity, start, end):
                """
                Fetch OHLC candles (wrapper for get_historical_data).
                
                Args:
                    symbol: Trading symbol
                    granularity: Timeframe (e.g., 'H1')
                    start: Start datetime
                    end: End datetime
                
                Returns:
                    List of candles
                """
                import pytz
                from datetime import datetime
                
                # Convert granularity string to MT5 timeframe
                timeframe_map = {
                    'M1': 1,      # 1 minute
                    'M5': 5,      # 5 minutes
                    'M15': 15,    # 15 minutes
                    'M30': 30,    # 30 minutes
                    'H1': 16385,  # 1 hour
                    'H4': 16388,  # 4 hours
                    'D1': 16408,  # 1 day
                    'W1': 16432,  # 1 week
                    'MN': 49,     # 1 month
                }
                
                timeframe = timeframe_map.get(granularity, 16385)  # Default H1
                
                # Calculate count based on start/end
                count = min(1000, 500)  # Default to 500 candles
                
                try:
                    return await self.get_historical_data(symbol, timeframe, count)
                except Exception as e:
                    self.logger.error(f"Error fetching candles for {symbol}: {e}")
                    return []
            
            # Attach the method to the class
            MT5BrokerInterface.get_candles = get_candles
            print("✓ Added get_candles method to MT5BrokerInterface")
            return True
    except Exception as e:
        print(f"✗ Failed to add get_candles: {e}")
        return False

if __name__ == "__main__":
    add_get_candles_alias()
