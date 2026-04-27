#!/usr/bin/env python3
"""
ML Model Retraining Script
Retrains price movement predictor models with current optimized dataset
"""

import os
import sys
import asyncio
from datetime import datetime
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from src.models import MarketData
from src.analysis.technical_indicators import IndicatorCalculator
from src.analysis.ml_model import PriceMovementPredictor
from src.broker.mt5_broker import MT5Broker

async def retrain_models():
    """Retrain ML models for all symbols"""
    
    symbols = ['EUR/USD', 'GBP/USD', 'AUD/USD', 'USD/JPY']
    models_dir = Path('models')
    models_dir.mkdir(exist_ok=True)
    
    print("\n" + "="*70)
    print("ML MODEL RETRAINING - Optimized Dataset")
    print("="*70)
    
    results = {}
    
    # Initialize broker
    print(f"\n[INIT] Connecting to MT5...")
    broker = MT5Broker()
    
    try:
        for symbol in symbols:
            print(f"\n[TRAINING] {symbol}")
            print("-" * 70)
            
            try:
                # Load historical data
                print(f"  → Loading historical data...")
                historical_data = await broker.get_historical_data(symbol, timeframe=16385, count=2000)
                
                if not historical_data or len(historical_data) < 100:
                    print(f"  ✗ Insufficient data: {len(historical_data) if historical_data else 0} bars")
                    results[symbol] = {'status': 'failed', 'reason': 'insufficient_data'}
                    continue
                
                print(f"  ✓ Loaded {len(historical_data):,} bars")
                
                # Calculate indicators
                print(f"  → Calculating technical indicators...")
                indicator_calc = IndicatorCalculator()
                indicators_list = []
                for i, bar in enumerate(historical_data):
                    indicators = indicator_calc.calculate(bar, historical_data[:i + 1])
                    indicators_list.append(indicators)
                
                print(f"  ✓ Calculated indicators for {len(indicators_list)} bars")
                
                # Train model
                print(f"  → Training ML model...")
                predictor = PriceMovementPredictor(symbol, horizon=3)
                predictor.train(historical_data, indicators_list)
                
                if predictor.is_trained:
                    # Save model
                    safe_symbol = symbol.replace('/', '')
                    model_path = models_dir / f"{safe_symbol}_ml.pkl"
                    predictor.save_model(str(model_path))
                    
                    print(f"  ✓ Model trained and saved to {model_path}")
                    
                    results[symbol] = {
                        'status': 'success',
                        'trained_at': datetime.now().isoformat(),
                        'data_points': len(historical_data)
                    }
                else:
                    print(f"  ✗ Training failed")
                    results[symbol] = {'status': 'failed', 'reason': 'training_failed'}
                    
            except Exception as e:
                print(f"  ✗ Error: {str(e)}")
                results[symbol] = {'status': 'failed', 'reason': str(e)}
    
    finally:
        broker.shutdown()
    
    # Summary
    print("\n" + "="*70)
    print("RETRAINING SUMMARY")
    print("="*70)
    
    for symbol, result in results.items():
        status_icon = "✓" if result['status'] == 'success' else "✗"
        if result['status'] == 'success':
            print(f"{status_icon} {symbol:<15} TRAINED | {result['data_points']:,} bars")
        else:
            print(f"{status_icon} {symbol:<15} FAILED  | Reason: {result.get('reason', 'unknown')}")
    
    success_count = sum(1 for r in results.values() if r['status'] == 'success')
    print(f"\nResult: {success_count}/{len(symbols)} models successfully trained")
    
    return success_count == len(symbols)

if __name__ == "__main__":
    success = asyncio.run(retrain_models())
    sys.exit(0 if success else 1)
