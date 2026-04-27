
import asyncio
import logging
import os
import sys

# Add src to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.data.mt5_broker import create_mt5_broker
from src.config import get_config_manager
from src.analysis.ml_model import PriceMovementPredictor
from src.analysis.technical_indicators import IndicatorCalculator

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger(__name__)

async def train_models():
    logger.info("Starting ML Training Session...")
    
    # Load config to get credentials (FORCE 'mt5' environment)
    try:
        config_manager = get_config_manager('mt5')
        broker_config = config_manager.get_config().broker
        
        login = broker_config.login
        password = broker_config.password
        server = broker_config.server
        
        logger.info(f"Connecting with Login: {login} (Server: {server})")

        broker = create_mt5_broker(
            login=login,
            password=password,
            server=server
        )
    except Exception as e:
        logger.error(f"Failed to create broker from config: {e}")
        return

    if not await broker.connect():
        logger.error("Failed to connect to Broker/MT5")
        return

    # Symbols to train
    symbols = ['EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD']
    training_bars = 5000  # Deep history for better simple models
    
    # Ensure models directory exists
    os.makedirs('models', exist_ok=True)
    
    for symbol in symbols:
        logger.info(f"--- Training {symbol} ---")
        try:
            # 1. Fetch Data
            # Use a slightly longer timeout for big data
            logger.info(f"Fetching {training_bars} candles...")
            history = await broker.get_historical_data(symbol, timeframe=16385, count=training_bars) # H1
            
            if not history or len(history) < 1000:
                logger.warning(f"Insufficient data for {symbol}, skipping.")
                continue
                
            logger.info(f"Data fetched: {len(history)} bars. Calculating indicators...")
            
            # 2. Calculate Indicators (Robust Loop)
            valid_data_pairs = [] # List of (MarketData, TechnicalIndicators)
            calc = IndicatorCalculator()
            
            for bar in history:
                calc.add_market_data(bar)
                try:
                    ind = calc.calculate_indicators(symbol, timeframe='1h')
                    valid_data_pairs.append((bar, ind))
                except Exception:
                    # Skip bars where indicators cannot be calculated (insufficient history)
                    continue
            
            if len(valid_data_pairs) < 100:
                logger.warning(f"Insufficient valid data pairs for {symbol} after calculation.")
                continue

            logger.info(f"Valid samples: {len(valid_data_pairs)}. Training Random Forest...")

            # Unzip valid pairs
            valid_history = [p[0] for p in valid_data_pairs]
            valid_indicators = [p[1] for p in valid_data_pairs]
            
            # 3. Train
            model = PriceMovementPredictor(symbol)
            model.train(valid_history, valid_indicators)
            
            # 4. Save
            safe_symbol = symbol.replace('/', '')
            model_path = f"models/{safe_symbol}_ml.pkl"
            model.save_model(model_path)
            
            # Log Insightful Statistics
            meta = getattr(model, 'metadata', {})
            acc = meta.get('accuracy_score', 0.0)
            top_features = meta.get('top_features', {})
            best_feature = list(top_features.keys())[0] if top_features else "None"
            
            logger.info(f"✓ Training complete for {symbol}")
            logger.info(f"   » Accuracy: {acc:.1%}")
            logger.info(f"   » Key Driver: {best_feature}")
            logger.info(f"   » Metadata saved to models/{safe_symbol}_ml_meta.json")
            
        except Exception as e:
            logger.error(f"Failed to train {symbol}: {e}")
            continue
            
    await broker.disconnect()
    logger.info("Training Session Complete. All models saved.")

if __name__ == "__main__":
    asyncio.run(train_models())
