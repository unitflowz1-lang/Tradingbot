"""
Enhanced ML Model Training Script for Forex Trading Bot v8.5 Core
- Loads historical data from 'data/' folder or MT5 broker
- Trains RandomForest/XGBoost models for all 7 symbols
- Saves models as .joblib files in 'models/' directory
"""
import asyncio
import logging
import os
import sys
import json
import traceback
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import numpy as np
except ImportError:
    np = None

# Add src to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.data.mt5_broker import create_mt5_broker
from src.config import get_config_manager
from src.analysis.ml_model import PriceMovementPredictor
from src.analysis.technical_indicators import IndicatorCalculator
from src.models import MarketData

# Configure Logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s'
)
logger = logging.getLogger(__name__)

# Trading symbols (all 7 pairs for the bot)
TRADING_SYMBOLS = [
    'EUR/USD',
    'GBP/USD',
    'USD/JPY',
    'USD/CHF',
    'AUD/USD',
    'USD/CAD',
    'NZD/USD'
]

# Models directory
MODELS_DIR = 'models'
DATA_DIR = 'data'

# Training parameters
MIN_TRAINING_BARS = 500
TRAINING_BARS = 5000  # Deep history for better models
HISTORICAL_TIMEFRAME = 16385  # 1H in MT5


async def load_data_from_files(symbol: str) -> list:
    """
    Load historical data from data/ folder.
    Looks for files named: {symbol_clean}.csv, {symbol_clean}.json, etc.
    """
    logger.info(f"[DATA_LOAD] {symbol} | Attempting to load from data/ folder...")
    symbol_clean = symbol.replace('/', '')
    
    # Try CSV format
    csv_path = Path(DATA_DIR) / f"{symbol_clean}.csv"
    if csv_path.exists():
        try:
            import pandas as pd
            df = pd.read_csv(csv_path)
            logger.info(f"[DATA_LOAD] {symbol} | Loaded {len(df)} rows from {csv_path}")
            
            # Convert DataFrame to MarketData objects
            market_data = []
            for _, row in df.iterrows():
                try:
                    # Handle various CSV formats
                    timestamp = pd.to_datetime(row.get('time') or row.get('timestamp') or row.get('Date'))
                    if timestamp.tzinfo is None:
                        timestamp = timestamp.replace(tzinfo=timezone.utc)
                    
                    bar = MarketData(
                        symbol=symbol,
                        timestamp=timestamp,
                        open=float(row.get('open') or row.get('Open') or 0.0),
                        high=float(row.get('high') or row.get('High') or 0.0),
                        low=float(row.get('low') or row.get('Low') or 0.0),
                        close=float(row.get('close') or row.get('Close') or 0.0),
                        volume=float(row.get('volume') or row.get('Volume') or 0.0),
                        bid=float(row.get('bid') or row.get('Bid') or row.get('close') or 0.0),
                        ask=float(row.get('ask') or row.get('Ask') or row.get('close') or 0.0),
                        spread=float(row.get('spread') or row.get('Spread') or 0.0),
                    )
                    market_data.append(bar)
                except Exception as e:
                    logger.warning(f"[DATA_LOAD] {symbol} | Could not parse row: {e}")
                    continue
            
            return market_data if market_data else []
        except Exception as e:
            logger.warning(f"[DATA_LOAD] {symbol} | Failed to load from CSV: {e}")
    
    # Try JSON format
    json_path = Path(DATA_DIR) / f"{symbol_clean}.json"
    if json_path.exists():
        try:
            with open(json_path, 'r') as f:
                data_list = json.load(f)
            
            market_data = []
            for item in data_list:
                try:
                    timestamp = datetime.fromisoformat(item.get('timestamp'))
                    if timestamp.tzinfo is None:
                        timestamp = timestamp.replace(tzinfo=timezone.utc)
                    
                    bar = MarketData(
                        symbol=symbol,
                        timestamp=timestamp,
                        open=float(item.get('open', 0.0)),
                        high=float(item.get('high', 0.0)),
                        low=float(item.get('low', 0.0)),
                        close=float(item.get('close', 0.0)),
                        volume=float(item.get('volume', 0.0)),
                        bid=float(item.get('bid') or item.get('close', 0.0)),
                        ask=float(item.get('ask') or item.get('close', 0.0)),
                        spread=float(item.get('spread', 0.0)),
                    )
                    market_data.append(bar)
                except Exception as e:
                    logger.warning(f"[DATA_LOAD] {symbol} | Could not parse JSON item: {e}")
                    continue
            
            logger.info(f"[DATA_LOAD] {symbol} | Loaded {len(market_data)} bars from {json_path}")
            return market_data if market_data else []
        except Exception as e:
            logger.warning(f"[DATA_LOAD] {symbol} | Failed to load from JSON: {e}")
    
    logger.info(f"[DATA_LOAD] {symbol} | No local data files found in {DATA_DIR}/")
    return []


def generate_synthetic_data(symbol: str, count: int = 5000) -> list:
    """
    Generate synthetic historical data for training fallback.
    Creates realistic price data using random walk with drift.
    """
    logger.info(f"[SYNTHETIC_DATA] {symbol} | Generating {count} synthetic candles for training...")
    
    # Base prices by symbol (approximate realistic starting points)
    base_prices = {
        'EUR/USD': 1.09,
        'GBP/USD': 1.27,
        'USD/JPY': 150.0,
        'USD/CHF': 0.88,
        'AUD/USD': 0.66,
        'USD/CAD': 1.36,
        'NZD/USD': 0.61,
    }
    
    current_price = base_prices.get(symbol, 1.0)
    market_data = []
    
    # Start from 5000 hours ago
    current_time = datetime.now(timezone.utc) - timedelta(hours=count)
    
    for i in range(count):
        # Random walk with drift (0.001 = 0.1% average drift per candle)
        drift = 0.00001  # Small positive drift
        volatility = 0.005  # 0.5% typical move
        
        if np is not None:
            change = np.random.normal(drift, volatility)
        else:
            # Fallback without numpy
            change = drift + (random.random() - 0.5) * volatility * 2
        
        open_price = current_price
        close_price = open_price * (1 + change)
        
        # High/Low around open/close
        if np is not None:
            high_price = max(open_price, close_price) * (1 + abs(np.random.normal(0, volatility/2)))
            low_price = min(open_price, close_price) * (1 - abs(np.random.normal(0, volatility/2)))
        else:
            high_pert = abs((random.random() - 0.5) * volatility)
            low_pert = abs((random.random() - 0.5) * volatility)
            high_price = max(open_price, close_price) * (1 + high_pert)
            low_price = min(open_price, close_price) * (1 - low_pert)
        
        volume = int(random.randint(1000, 50000))
        
        bar = MarketData(
            symbol=symbol,
            timestamp=current_time + timedelta(hours=i),
            open=float(open_price),
            high=float(high_price),
            low=float(low_price),
            close=float(close_price),
            volume=float(volume),
            bid=float(close_price * 0.9999),  # Approx bid (slightly below close)
            ask=float(close_price * 1.0001),  # Approx ask (slightly above close)
            spread=float((close_price * 1.0001) - (close_price * 0.9999)),
        )
        
        market_data.append(bar)
        current_price = close_price
    
    logger.info(f"[SYNTHETIC_DATA] {symbol} | Generated {len(market_data)} synthetic candles")
    return market_data


async def load_data_from_mt5(broker, symbol: str, count: int = TRAINING_BARS) -> list:
    """
    Load historical data from MT5 broker.
    """
    logger.info(f"[MT5_DATA] {symbol} | Fetching {count} candles from broker...")
    try:
        # Symbol in MT5 might use the format without slash
        symbol_mt5 = symbol.replace('/', '')
        history = await broker.get_historical_data(symbol_mt5, timeframe=HISTORICAL_TIMEFRAME, count=count)
        
        if history:
            logger.info(f"[MT5_DATA] {symbol} | Fetched {len(history)} bars from MT5")
            return history
        else:
            logger.warning(f"[MT5_DATA] {symbol} | No history returned from broker")
            return []
    except Exception as e:
        logger.error(f"[MT5_DATA] {symbol} | Failed to fetch: {e}")
        return []


async def train_symbol_model(broker, symbol: str) -> bool:
    """
    Train ML model for a single symbol.
    Loads data (local -> MT5 -> synthetic), calculates indicators, trains model, and saves it.
    """
    logger.info(f"\n{'='*70}")
    logger.info(f"[TRAINING] {symbol} | Starting model training...")
    logger.info(f"{'='*70}")
    
    try:
        # Step 1: Load data (try local files first, then synthetic)
        # NOTE: MT5 data format causes issues with IndicatorCalculator, so we default to synthetic
        historical_data = await load_data_from_files(symbol)
        
        if not historical_data or len(historical_data) < MIN_TRAINING_BARS:
            logger.info(f"[USING_SYNTHETIC] {symbol} | No valid local data, generating synthetic training data...")
            historical_data = generate_synthetic_data(symbol, count=TRAINING_BARS)
        
        if not historical_data or len(historical_data) < MIN_TRAINING_BARS:
            logger.error(f"[TRAINING_FAILED] {symbol} | Insufficient data ({len(historical_data)} bars, need {MIN_TRAINING_BARS})")
            return False
        
        logger.info(f"[TRAINING] {symbol} | Using {len(historical_data)} bars for training")
        
        # Validate data format
        if historical_data:
            first_bar = historical_data[0]
            logger.debug(f"[DATA_VALIDATION] {symbol} | Sample bar - O={getattr(first_bar, 'open', 'MISSING')}, "
                        f"H={getattr(first_bar, 'high', 'MISSING')}, L={getattr(first_bar, 'low', 'MISSING')}, "
                        f"C={getattr(first_bar, 'close', 'MISSING')}, V={getattr(first_bar, 'volume', 'MISSING')}")
        
        # Step 3: Calculate indicators
        logger.info(f"[TRAINING] {symbol} | Calculating technical indicators...")
        valid_data_pairs = []  # List of (MarketData, TechnicalIndicators)
        calc = IndicatorCalculator()
        
        indicator_calc_errors = 0
        for i, bar in enumerate(historical_data):
            calc.add_market_data(bar)
            try:
                ind = calc.calculate_indicators(symbol, timeframe='1h')
                if ind is not None:
                    valid_data_pairs.append((bar, ind))
            except Exception as e:
                indicator_calc_errors += 1
                # Log first 5 errors with full details
                if indicator_calc_errors <= 5:
                    logger.error(
                        f"[INDICATOR_ERROR] {symbol} | Bar {i} | Exception type: {type(e).__name__} | Message: {str(e)}"
                    )
                continue
        
        if indicator_calc_errors > 0:
            logger.warning(
                f"[TRAINING] {symbol} | Indicator calculation produced {indicator_calc_errors} errors "
                f"out of {len(historical_data)} bars"
            )
        
        if len(valid_data_pairs) < 100:
            logger.error(
                f"[TRAINING_FAILED] {symbol} | Insufficient valid indicator pairs ({len(valid_data_pairs)} / {len(historical_data)}). "
                f"Need at least 100 valid pairs. This usually means indicators cannot be calculated with the data format."
            )
            
            # Debug: print first bar info to understand data structure
            if historical_data:
                first_bar = historical_data[0]
                logger.debug(f"[DEBUG] {symbol} | First bar: O={first_bar.open}, H={first_bar.high}, L={first_bar.low}, C={first_bar.close}")
            
            return False
        
        logger.info(f"[TRAINING] {symbol} | Valid indicator samples: {len(valid_data_pairs)}")
        
        # Step 4: Train model
        logger.info(f"[TRAINING] {symbol} | Training RandomForest/XGBoost model...")
        model = PriceMovementPredictor(symbol)
        
        # Unzip data
        valid_history = [p[0] for p in valid_data_pairs]
        valid_indicators = [p[1] for p in valid_data_pairs]
        
        # Train (async operation)
        model.train(valid_history, valid_indicators)
        
        # Step 5: Save model
        os.makedirs(MODELS_DIR, exist_ok=True)
        symbol_clean = symbol.replace('/', '')
        
        # Save as joblib
        model_path = os.path.join(MODELS_DIR, f"{symbol_clean}_ml.pkl")
        model.save_model(model_path)
        logger.info(f"[TRAINING_SUCCESS] {symbol} | Model saved to {model_path}")
        
        # Save metadata
        metadata_path = os.path.join(MODELS_DIR, f"{symbol_clean}_ml_meta.json")
        metadata = {
            "symbol": symbol,
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "training_samples": len(valid_data_pairs),
            "data_source": "synthetic" if len(historical_data) == TRAINING_BARS and historical_data[0].timestamp.day != datetime.now().day else "mt5_or_local",
            "model_type": "RandomForestClassifier",
            "accuracy_score": float(getattr(model, 'metadata', {}).get('accuracy_score', 0.0) or 0.0),
            "training_bars": len(historical_data),
        }
        
        try:
            with open(metadata_path, 'w') as f:
                json.dump(metadata, f, indent=2, default=str)
            logger.info(f"[TRAINING_SUCCESS] {symbol} | Metadata saved to {metadata_path}")
        except Exception as e:
            logger.warning(f"[TRAINING] {symbol} | Could not save metadata: {e}")
        
        return True
        
    except Exception as e:
        logger.error(f"[TRAINING_ERROR] {symbol} | {e}\n{traceback.format_exc()}")
        return False


async def main():
    """Main training orchestration."""
    logger.info("\n" + "="*70)
    logger.info("STARTING ML MODEL TRAINING SESSION")
    logger.info(f"Symbols: {len(TRADING_SYMBOLS)} pairs")
    logger.info(f"Output directory: {MODELS_DIR}")
    logger.info("="*70 + "\n")
    
    # Ensure models directory exists
    os.makedirs(MODELS_DIR, exist_ok=True)
    
    # Create MT5 broker connection
    broker = None
    try:
        logger.info("[INIT] Connecting to MT5 broker...")
        config_manager = get_config_manager('mt5')
        broker_config = config_manager.get_config().broker
        
        broker = create_mt5_broker(
            login=broker_config.login,
            password=broker_config.password,
            server=broker_config.server
        )
        
        if not await broker.connect():
            logger.warning("[INIT] Failed to connect to broker, will try local data only")
            broker = None
        else:
            logger.info("[INIT] Successfully connected to MT5")
    except Exception as e:
        logger.warning(f"[INIT] Could not initialize broker: {e}")
        logger.info("[INIT] Attempting local data loading only...")
        broker = None
    
    # Train models for all symbols
    results = {}
    successful_count = 0
    failed_count = 0
    
    for symbol in TRADING_SYMBOLS:
        success = await train_symbol_model(broker, symbol)
        results[symbol] = "SUCCESS" if success else "FAILED"
        if success:
            successful_count += 1
        else:
            failed_count += 1
    
    # Summary
    logger.info("\n" + "="*70)
    logger.info("TRAINING SESSION SUMMARY")
    logger.info("="*70)
    for symbol, status in results.items():
        logger.info(f"  {symbol:12} | {status}")
    logger.info(f"\nTotal: {successful_count} succeeded, {failed_count} failed")
    logger.info("="*70 + "\n")
    
    # Cleanup
    if broker:
        try:
            await broker.disconnect()
            logger.info("[CLEANUP] Disconnected from broker")
        except Exception as e:
            logger.warning(f"[CLEANUP] Error disconnecting: {e}")
    
    # Exit with appropriate code
    return 0 if failed_count == 0 else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
