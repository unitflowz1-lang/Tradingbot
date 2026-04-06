"""
Example demonstrating the RL data management pipeline.

This example shows how to use the data loader, preprocessor, 
batch manager, and augmentation components together.
"""

import numpy as np
from datetime import datetime, timezone, timedelta
from typing import List

# Import our data management components
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.models import MarketData
from src.rl.data.loader import HistoricalDataLoader, DataLoaderConfig
from src.rl.data.preprocessor import DataPreprocessor, PreprocessorConfig
from src.rl.data.batch_manager import BatchManager, BatchConfig
from src.rl.data.augmentation import DataAugmentation, AugmentationConfig


def create_sample_data(num_samples: int = 1000) -> List[MarketData]:
    """Create sample market data for demonstration."""
    data = []
    base_time = datetime(2023, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    
    for i in range(num_samples):
        timestamp = base_time + timedelta(hours=i)
        
        # Simulate realistic price movement
        base_price = 1.1000
        trend = 0.0001 * i  # Slight upward trend
        noise = 0.001 * np.sin(i * 0.1) + 0.0005 * np.random.randn()
        price = base_price + trend + noise
        
        # Ensure realistic OHLC relationships
        spread = 0.0002
        volatility = 0.0005 + 0.0002 * np.random.randn()
        
        high = price + abs(volatility)
        low = price - abs(volatility)
        open_price = low + (high - low) * np.random.random()
        close_price = low + (high - low) * np.random.random()
        
        # Ensure OHLC constraints
        high = max(high, open_price, close_price)
        low = min(low, open_price, close_price)
        
        volume = int(1000 + 500 * np.random.randn())
        volume = max(100, volume)  # Ensure positive volume
        
        bid = close_price - spread / 2
        ask = close_price + spread / 2
        
        market_data = MarketData(
            symbol="EUR/USD",
            timestamp=timestamp,
            open=open_price,
            high=high,
            low=low,
            close=close_price,
            volume=volume,
            bid=bid,
            ask=ask,
            spread=spread
        )
        
        data.append(market_data)
    
    return data


def demonstrate_data_loading():
    """Demonstrate data loading functionality."""
    print("=== Data Loading Demo ===")
    
    # Create sample data
    sample_data = create_sample_data(500)
    print(f"Created {len(sample_data)} sample data points")
    
    # Configure data loader
    config = DataLoaderConfig(
        data_directory="temp_data",
        symbols=["EUR/USD"],
        timeframes=["1H"],
        enable_caching=True,
        validate_data=True,
        fill_missing_data=True
    )
    
    # Initialize loader
    loader = HistoricalDataLoader(config)
    
    # Simulate loading (in practice, this would load from files/database)
    print(f"Data validation: {'enabled' if config.validate_data else 'disabled'}")
    print(f"Caching: {'enabled' if config.enable_caching else 'disabled'}")
    
    # Get cache statistics
    stats = loader.get_cache_stats()
    print(f"Cache stats: {stats}")
    
    return sample_data


def demonstrate_preprocessing(data: List[MarketData]):
    """Demonstrate data preprocessing functionality."""
    print("\n=== Data Preprocessing Demo ===")
    
    # Configure preprocessor
    config = PreprocessorConfig(
        normalization_method="standard",
        enable_technical_indicators=True,
        enable_price_features=True,
        enable_volume_features=True,
        enable_time_features=True,
        enable_lag_features=True,
        lag_periods=[1, 2, 3],
        enable_rolling_stats=True,
        rolling_windows=[5, 10, 20],
        rolling_stats=["mean", "std"],
        remove_outliers=True,
        outlier_method="iqr"
    )
    
    # Initialize preprocessor
    preprocessor = DataPreprocessor(config)
    
    # Fit and transform data
    print("Fitting preprocessor...")
    features = preprocessor.fit_transform(data)
    
    print(f"Original data points: {len(data)}")
    print(f"Feature matrix shape: {features.shape}")
    print(f"Number of features: {len(preprocessor.get_feature_names())}")
    
    # Show some feature names
    feature_names = preprocessor.get_feature_names()
    print(f"Sample features: {feature_names[:10]}")
    
    # Get preprocessing statistics
    stats = preprocessor.get_preprocessing_stats()
    print(f"Preprocessing stats: {stats}")
    
    return preprocessor


def demonstrate_batching(data: List[MarketData], preprocessor: DataPreprocessor):
    """Demonstrate batch management functionality."""
    print("\n=== Batch Management Demo ===")
    
    # Configure batch manager
    batch_config = BatchConfig(
        batch_size=16,
        sequence_length=50,
        overlap_ratio=0.1,
        sampling_strategy="sequential",
        shuffle_batches=True,
        validation_split=0.2,
        test_split=0.1,
        enable_augmentation=False  # We'll demo augmentation separately
    )
    
    # Create mock data loader (in practice, use real loader)
    class MockDataLoader:
        def load_data(self, symbol, timeframe, start_date=None, end_date=None):
            return data
    
    # Initialize batch manager
    batch_manager = BatchManager(batch_config, MockDataLoader(), preprocessor)
    
    # Prepare data
    print("Preparing data splits...")
    batch_manager.prepare_data(["EUR/USD"], ["1H"])
    
    # Get batch statistics
    stats = batch_manager.get_batch_statistics()
    print(f"Data splits - Train: {stats['train_samples']}, "
          f"Val: {stats['val_samples']}, Test: {stats['test_samples']}")
    
    # Create a single batch
    print("Creating sample batch...")
    batch_data = data[:200]  # Use subset for batch creation
    states, next_states = batch_manager.create_single_batch(batch_data)
    
    print(f"Batch shape - States: {states.shape}, Next states: {next_states.shape}")
    
    # Show batch creation statistics
    batch_stats = batch_manager.get_batch_statistics()
    print(f"Batch creation stats: {batch_stats}")
    
    return batch_manager, states, next_states


def demonstrate_augmentation(states: np.ndarray, next_states: np.ndarray):
    """Demonstrate data augmentation functionality."""
    print("\n=== Data Augmentation Demo ===")
    
    # Configure augmentation
    config = AugmentationConfig(
        augmentation_probability=0.8,
        max_augmentations_per_sample=2,
        enable_noise=True,
        enable_scaling=True,
        enable_jittering=True,
        enable_time_warping=True,
        enable_magnitude_warping=True,
        noise_std=0.01,
        scaling_range=(0.98, 1.02),
        jitter_strength=0.005
    )
    
    # Initialize augmentation
    augmentation = DataAugmentation(config)
    
    print(f"Original batch size: {states.shape[0]}")
    
    # Apply augmentation
    aug_states, aug_next_states = augmentation.augment_batch(states, next_states)
    
    print(f"Augmented batch size: {aug_states.shape[0]}")
    print(f"Augmentation ratio: {aug_states.shape[0] / states.shape[0]:.2f}x")
    
    # Show augmentation statistics
    stats = augmentation.get_augmentation_stats()
    print(f"Augmentation stats: {stats}")
    
    # Show technique usage
    print("Technique usage:")
    for technique, count in stats['technique_usage'].items():
        if count > 0:
            print(f"  {technique}: {count} times")
    
    return augmentation


def demonstrate_complete_pipeline():
    """Demonstrate the complete data management pipeline."""
    print("=== Complete Data Management Pipeline Demo ===")
    
    # Step 1: Data Loading
    data = demonstrate_data_loading()
    
    # Step 2: Data Preprocessing
    preprocessor = demonstrate_preprocessing(data)
    
    # Step 3: Batch Management
    batch_manager, states, next_states = demonstrate_batching(data, preprocessor)
    
    # Step 4: Data Augmentation
    augmentation = demonstrate_augmentation(states, next_states)
    
    print("\n=== Pipeline Summary ===")
    print(f"✓ Loaded and validated {len(data)} market data points")
    print(f"✓ Generated {len(preprocessor.get_feature_names())} features per sample")
    print(f"✓ Created batches with shape {states.shape}")
    print(f"✓ Applied {len(augmentation.techniques)} augmentation techniques")
    
    # Show memory usage estimation
    feature_size = states.nbytes + next_states.nbytes
    print(f"✓ Memory usage for batch: {feature_size / 1024 / 1024:.2f} MB")
    
    return {
        'data': data,
        'preprocessor': preprocessor,
        'batch_manager': batch_manager,
        'augmentation': augmentation,
        'sample_batch': (states, next_states)
    }


if __name__ == "__main__":
    # Set random seed for reproducible results
    np.random.seed(42)
    
    try:
        # Run the complete demonstration
        results = demonstrate_complete_pipeline()
        
        print("\n🎉 Data management pipeline demonstration completed successfully!")
        print("\nThis pipeline provides:")
        print("- Efficient historical data loading with caching")
        print("- Comprehensive feature engineering and normalization")
        print("- Flexible batch creation for RL training")
        print("- Robust data augmentation for improved generalization")
        
    except Exception as e:
        print(f"\n❌ Error during demonstration: {e}")
        import traceback
        traceback.print_exc()