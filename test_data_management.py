"""
Unit tests for RL data management components.

Tests data loading, preprocessing, batching, and augmentation functionality.
"""

import pytest
import numpy as np
import pandas as pd
import tempfile
import os
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock
from typing import List

from src.models import MarketData
from src.rl.data.loader import HistoricalDataLoader, DataLoaderConfig
from src.rl.data.preprocessor import DataPreprocessor, PreprocessorConfig
from src.rl.data.batch_manager import BatchManager, BatchConfig
from src.rl.data.augmentation import DataAugmentation, AugmentationConfig
from src.rl.data.augmentation import (
    NoiseAugmentation, TimeWarpingAugmentation, ScalingAugmentation,
    JitteringAugmentation, MagnitudeWarpingAugmentation
)


class TestHistoricalDataLoader:
    """Test cases for HistoricalDataLoader."""
    
    @pytest.fixture
    def sample_market_data(self) -> List[MarketData]:
        """Create sample market data for testing."""
        from datetime import timezone
        data = []
        base_time = datetime(2023, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        
        for i in range(100):
            timestamp = base_time + timedelta(hours=i)
            price = 1.1000 + 0.001 * np.sin(i * 0.1) + 0.0001 * np.random.randn()
            
            market_data = MarketData(
                symbol="EUR/USD",
                timestamp=timestamp,
                open=price,
                high=price + 0.0005,
                low=price - 0.0005,
                close=price + 0.0001,
                volume=1000 + int(100 * np.random.randn()),
                bid=price - 0.0001,
                ask=price + 0.0001,
                spread=0.0002
            )
            data.append(market_data)
            
        return data
    
    @pytest.fixture
    def temp_data_dir(self):
        """Create temporary directory for test data."""
        with tempfile.TemporaryDirectory() as temp_dir:
            yield temp_dir
    
    @pytest.fixture
    def data_loader_config(self, temp_data_dir):
        """Create data loader configuration."""
        return DataLoaderConfig(
            data_directory=temp_data_dir,
            cache_directory=os.path.join(temp_data_dir, "cache"),
            symbols=["EUR/USD"],
            timeframes=["1H"],
            chunk_size=50,
            enable_caching=True
        )
    
    def test_data_loader_initialization(self, data_loader_config):
        """Test data loader initialization."""
        loader = HistoricalDataLoader(data_loader_config)
        
        assert loader.config == data_loader_config
        assert loader._cache == {}
        assert loader._cache_stats["hits"] == 0
        assert loader._cache_stats["misses"] == 0
    
    def test_config_validation(self, temp_data_dir):
        """Test configuration validation."""
        # Test empty symbols
        with pytest.raises(ValueError, match="At least one symbol must be specified"):
            config = DataLoaderConfig(data_directory=temp_data_dir, symbols=[])
            HistoricalDataLoader(config)
        
        # Test empty timeframes
        with pytest.raises(ValueError, match="At least one timeframe must be specified"):
            config = DataLoaderConfig(data_directory=temp_data_dir, timeframes=[])
            HistoricalDataLoader(config)
        
        # Test invalid chunk size
        with pytest.raises(ValueError, match="Chunk size must be positive"):
            config = DataLoaderConfig(data_directory=temp_data_dir, chunk_size=0)
            HistoricalDataLoader(config)
    
    def test_cache_key_generation(self, data_loader_config):
        """Test cache key generation."""
        loader = HistoricalDataLoader(data_loader_config)
        
        start_date = datetime(2023, 1, 1)
        end_date = datetime(2023, 1, 31)
        
        key1 = loader._generate_cache_key("EUR/USD", "1H", start_date, end_date)
        key2 = loader._generate_cache_key("EUR/USD", "1H", start_date, end_date)
        key3 = loader._generate_cache_key("GBP/USD", "1H", start_date, end_date)
        
        assert key1 == key2  # Same parameters should generate same key
        assert key1 != key3  # Different parameters should generate different keys
        assert len(key1) == 32  # MD5 hash length
    
    def test_timeframe_parsing(self, data_loader_config):
        """Test timeframe parsing to minutes."""
        loader = HistoricalDataLoader(data_loader_config)
        
        assert loader._parse_timeframe_minutes("1M") == 1
        assert loader._parse_timeframe_minutes("5M") == 5
        assert loader._parse_timeframe_minutes("1H") == 60
        assert loader._parse_timeframe_minutes("4H") == 240
        assert loader._parse_timeframe_minutes("1D") == 1440
        
        with pytest.raises(ValueError, match="Unsupported timeframe format"):
            loader._parse_timeframe_minutes("1X")
    
    def test_data_validation_and_cleaning(self, data_loader_config, sample_market_data):
        """Test data validation and cleaning."""
        loader = HistoricalDataLoader(data_loader_config)
        
        # Add some invalid data
        invalid_data = MarketData(
            symbol="INVALID",
            timestamp=datetime(2023, 1, 1),
            open=-1.0,  # Invalid negative price
            high=1.1,
            low=1.0,
            close=1.05,
            volume=1000,
            bid=1.04,
            ask=1.06,
            spread=0.02
        )
        
        test_data = sample_market_data + [invalid_data]
        
        with patch.object(loader.logger, 'warning') as mock_warning:
            cleaned_data = loader._validate_and_clean_data(test_data)
            
            # Should remove invalid data
            assert len(cleaned_data) == len(sample_market_data)
            mock_warning.assert_called()
    
    def test_missing_data_interpolation(self, data_loader_config):
        """Test missing data interpolation."""
        loader = HistoricalDataLoader(data_loader_config)
        
        # Create data with gaps
        from datetime import timezone
        base_time = datetime(2023, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        data = [
            MarketData(
                symbol="EUR/USD",
                timestamp=base_time,
                open=1.1000, high=1.1005, low=1.0995, close=1.1002,
                volume=1000, bid=1.0999, ask=1.1001, spread=0.0002
            ),
            MarketData(
                symbol="EUR/USD",
                timestamp=base_time + timedelta(hours=3),  # 2-hour gap
                open=1.1010, high=1.1015, low=1.1005, close=1.1012,
                volume=1100, bid=1.1009, ask=1.1011, spread=0.0002
            )
        ]
        
        filled_data = loader._fill_missing_data(data, "1H")
        
        # Should have interpolated data points
        assert len(filled_data) > len(data)
        
        # Check timestamps are sequential
        for i in range(1, len(filled_data)):
            time_diff = (filled_data[i].timestamp - filled_data[i-1].timestamp).total_seconds()
            assert time_diff == 3600  # 1 hour in seconds
    
    def test_cache_operations(self, data_loader_config, sample_market_data):
        """Test cache save and load operations."""
        loader = HistoricalDataLoader(data_loader_config)
        
        cache_key = "test_key"
        
        # Test save to cache
        loader._save_to_cache(cache_key, sample_market_data)
        
        # Test load from cache
        loaded_data = loader._load_from_cache(cache_key)
        
        assert loaded_data is not None
        assert len(loaded_data) == len(sample_market_data)
        assert loaded_data[0].symbol == sample_market_data[0].symbol
    
    def test_cache_statistics(self, data_loader_config):
        """Test cache statistics tracking."""
        loader = HistoricalDataLoader(data_loader_config)
        
        # Simulate cache hits and misses
        loader._cache_stats["hits"] = 10
        loader._cache_stats["misses"] = 5
        
        stats = loader.get_cache_stats()
        
        assert stats["cache_hits"] == 10
        assert stats["cache_misses"] == 5
        assert stats["hit_rate"] == 10 / 15
        assert stats["cached_items"] == 0  # No items in memory cache
    
    def test_clear_cache(self, data_loader_config, sample_market_data):
        """Test cache clearing."""
        loader = HistoricalDataLoader(data_loader_config)
        
        # Add data to cache
        loader._cache["test"] = sample_market_data
        loader._cache_stats["hits"] = 5
        
        # Clear cache
        loader.clear_cache()
        
        assert len(loader._cache) == 0
        assert loader._cache_stats["hits"] == 0
        assert loader._cache_stats["misses"] == 0


class TestDataPreprocessor:
    """Test cases for DataPreprocessor."""
    
    @pytest.fixture
    def sample_market_data(self) -> List[MarketData]:
        """Create sample market data for testing."""
        from datetime import timezone
        data = []
        base_time = datetime(2023, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        
        for i in range(50):
            timestamp = base_time + timedelta(hours=i)
            price = 1.1000 + 0.001 * np.sin(i * 0.1)
            
            market_data = MarketData(
                symbol="EUR/USD",
                timestamp=timestamp,
                open=price,
                high=price + 0.0005,
                low=price - 0.0005,
                close=price + 0.0001,
                volume=1000 + i * 10,
                bid=price - 0.0001,
                ask=price + 0.0001,
                spread=0.0002
            )
            data.append(market_data)
            
        return data
    
    @pytest.fixture
    def preprocessor_config(self):
        """Create preprocessor configuration."""
        return PreprocessorConfig(
            normalization_method="standard",
            enable_technical_indicators=True,
            enable_price_features=True,
            enable_volume_features=True,
            enable_time_features=True,
            enable_lag_features=True,
            lag_periods=[1, 2, 3],
            enable_rolling_stats=True,
            rolling_windows=[5, 10],
            rolling_stats=["mean", "std"]
        )
    
    def test_preprocessor_initialization(self, preprocessor_config):
        """Test preprocessor initialization."""
        preprocessor = DataPreprocessor(preprocessor_config)
        
        assert preprocessor.config == preprocessor_config
        assert not preprocessor.is_fitted
        assert len(preprocessor.scalers) == 0
        assert len(preprocessor.feature_names) == 0
    
    def test_market_data_to_dataframe(self, preprocessor_config, sample_market_data):
        """Test conversion of MarketData to DataFrame."""
        preprocessor = DataPreprocessor(preprocessor_config)
        
        df = preprocessor._convert_to_dataframe(sample_market_data)
        
        assert len(df) == len(sample_market_data)
        assert 'timestamp' in df.columns
        assert 'symbol' in df.columns
        assert 'open' in df.columns
        assert 'close' in df.columns
        assert df['timestamp'].dtype == 'datetime64[ns]'
    
    def test_price_features_generation(self, preprocessor_config, sample_market_data):
        """Test price features generation."""
        preprocessor = DataPreprocessor(preprocessor_config)
        
        df = preprocessor._convert_to_dataframe(sample_market_data)
        features_df = pd.DataFrame(index=df.index)
        
        features_df = preprocessor._add_price_features(features_df, df)
        
        expected_features = [
            'open', 'high', 'low', 'close', 'hl_ratio', 'oc_ratio', 'price_range',
            'price_change', 'price_change_abs', 'log_return', 'typical_price', 'weighted_close'
        ]
        
        for feature in expected_features:
            assert feature in features_df.columns
            
        # Check calculations
        assert not features_df['hl_ratio'].isna().all()
        assert not features_df['price_change'].isna().all()
    
    def test_volume_features_generation(self, preprocessor_config, sample_market_data):
        """Test volume features generation."""
        preprocessor = DataPreprocessor(preprocessor_config)
        
        df = preprocessor._convert_to_dataframe(sample_market_data)
        features_df = pd.DataFrame(index=df.index)
        
        features_df = preprocessor._add_volume_features(features_df, df)
        
        expected_features = ['volume', 'volume_change', 'volume_ma', 'volume_ratio', 'price_volume', 'vwap']
        
        for feature in expected_features:
            assert feature in features_df.columns
    
    def test_time_features_generation(self, preprocessor_config, sample_market_data):
        """Test time features generation."""
        preprocessor = DataPreprocessor(preprocessor_config)
        
        df = preprocessor._convert_to_dataframe(sample_market_data)
        features_df = pd.DataFrame(index=df.index)
        
        features_df = preprocessor._add_time_features(features_df, df)
        
        expected_features = [
            'hour', 'day_of_week', 'day_of_month', 'month', 'quarter',
            'hour_sin', 'hour_cos', 'dow_sin', 'dow_cos',
            'asian_session', 'european_session', 'american_session'
        ]
        
        for feature in expected_features:
            assert feature in features_df.columns
            
        # Check cyclical encoding
        assert features_df['hour_sin'].between(-1, 1).all()
        assert features_df['hour_cos'].between(-1, 1).all()
    
    def test_lag_features_generation(self, preprocessor_config, sample_market_data):
        """Test lag features generation."""
        preprocessor = DataPreprocessor(preprocessor_config)
        
        df = preprocessor._convert_to_dataframe(sample_market_data)
        features_df = pd.DataFrame(index=df.index)
        
        features_df = preprocessor._add_lag_features(features_df, df)
        
        # Check lag features exist
        for lag in preprocessor_config.lag_periods:
            assert f'close_lag_{lag}' in features_df.columns
            assert f'volume_lag_{lag}' in features_df.columns
            
        # Check lag values
        assert features_df['close_lag_1'].iloc[1] == df['close'].iloc[0]
    
    def test_rolling_statistics_generation(self, preprocessor_config, sample_market_data):
        """Test rolling statistics generation."""
        preprocessor = DataPreprocessor(preprocessor_config)
        
        df = preprocessor._convert_to_dataframe(sample_market_data)
        features_df = pd.DataFrame(index=df.index)
        
        features_df = preprocessor._add_rolling_statistics(features_df, df)
        
        # Check rolling features exist
        for window in preprocessor_config.rolling_windows:
            for stat in preprocessor_config.rolling_stats:
                assert f'close_rolling_{stat}_{window}' in features_df.columns
                assert f'volume_rolling_{stat}_{window}' in features_df.columns
    
    def test_missing_values_handling(self, preprocessor_config, sample_market_data):
        """Test missing values handling."""
        preprocessor = DataPreprocessor(preprocessor_config)
        
        # Create DataFrame with missing values
        df = preprocessor._convert_to_dataframe(sample_market_data)
        features_df = preprocessor._generate_features(df)
        
        # Introduce some NaN values
        features_df.iloc[5:10, 0] = np.nan
        
        cleaned_df = preprocessor._handle_missing_values(features_df)
        
        # Should have no NaN values
        assert not cleaned_df.isna().any().any()
    
    def test_outlier_removal_iqr(self, preprocessor_config, sample_market_data):
        """Test outlier removal using IQR method."""
        config = preprocessor_config
        config.remove_outliers = True
        config.outlier_method = "iqr"
        
        preprocessor = DataPreprocessor(config)
        
        # Create data with outliers
        df = preprocessor._convert_to_dataframe(sample_market_data)
        features_df = preprocessor._generate_features(df)
        
        # Add outliers
        features_df.iloc[0, 0] = features_df.iloc[0, 0] * 10  # Extreme outlier
        
        original_length = len(features_df)
        cleaned_df = preprocessor._remove_outliers_iqr(features_df)
        
        # Should remove outliers
        assert len(cleaned_df) < original_length
    
    def test_outlier_removal_zscore(self, preprocessor_config, sample_market_data):
        """Test outlier removal using Z-score method."""
        config = preprocessor_config
        config.remove_outliers = True
        config.outlier_method = "zscore"
        config.outlier_threshold = 2.0
        
        preprocessor = DataPreprocessor(config)
        
        # Create data with outliers
        df = preprocessor._convert_to_dataframe(sample_market_data)
        features_df = preprocessor._generate_features(df)
        
        # Add outliers
        features_df.iloc[0, 0] = features_df.iloc[0, 0] * 5  # Outlier
        
        original_length = len(features_df)
        cleaned_df = preprocessor._remove_outliers_zscore(features_df)
        
        # Should remove outliers
        assert len(cleaned_df) < original_length
    
    def test_scaler_fitting(self, preprocessor_config, sample_market_data):
        """Test scaler fitting."""
        preprocessor = DataPreprocessor(preprocessor_config)
        
        df = preprocessor._convert_to_dataframe(sample_market_data)
        features_df = preprocessor._generate_features(df)
        features_df = preprocessor._handle_missing_values(features_df)
        
        preprocessor._fit_scalers(features_df)
        
        # Should have scalers for each feature
        assert len(preprocessor.scalers) > 0
        
        # Test scaler functionality
        for column in features_df.columns:
            if column in preprocessor.scalers:
                scaler = preprocessor.scalers[column]
                assert hasattr(scaler, 'transform')
    
    def test_fit_transform_pipeline(self, preprocessor_config, sample_market_data):
        """Test complete fit and transform pipeline."""
        preprocessor = DataPreprocessor(preprocessor_config)
        
        # Fit and transform
        features = preprocessor.fit_transform(sample_market_data)
        
        assert preprocessor.is_fitted
        assert isinstance(features, np.ndarray)
        assert features.shape[0] == len(sample_market_data)
        assert features.shape[1] > 0
        assert len(preprocessor.feature_names) == features.shape[1]
    
    def test_transform_without_fit_raises_error(self, preprocessor_config, sample_market_data):
        """Test that transform without fit raises error."""
        preprocessor = DataPreprocessor(preprocessor_config)
        
        with pytest.raises(RuntimeError, match="Preprocessor must be fitted before transform"):
            preprocessor.transform(sample_market_data)
    
    def test_feature_names_tracking(self, preprocessor_config, sample_market_data):
        """Test feature names tracking."""
        preprocessor = DataPreprocessor(preprocessor_config)
        
        preprocessor.fit(sample_market_data)
        feature_names = preprocessor.get_feature_names()
        
        assert len(feature_names) > 0
        assert all(isinstance(name, str) for name in feature_names)
    
    def test_preprocessing_statistics(self, preprocessor_config, sample_market_data):
        """Test preprocessing statistics tracking."""
        preprocessor = DataPreprocessor(preprocessor_config)
        
        preprocessor.fit_transform(sample_market_data)
        stats = preprocessor.get_preprocessing_stats()
        
        assert 'total_samples' in stats
        assert 'feature_count' in stats
        assert stats['total_samples'] > 0
        assert stats['feature_count'] > 0


class TestBatchManager:
    """Test cases for BatchManager."""
    
    @pytest.fixture
    def sample_market_data(self) -> List[MarketData]:
        """Create sample market data for testing."""
        from datetime import timezone
        data = []
        base_time = datetime(2023, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        
        for i in range(200):
            timestamp = base_time + timedelta(hours=i)
            price = 1.1000 + 0.001 * np.sin(i * 0.1)
            
            market_data = MarketData(
                symbol="EUR/USD",
                timestamp=timestamp,
                open=price,
                high=price + 0.0005,
                low=price - 0.0005,
                close=price + 0.0001,
                volume=1000 + i * 10,
                bid=price - 0.0001,
                ask=price + 0.0001,
                spread=0.0002
            )
            data.append(market_data)
            
        return data
    
    @pytest.fixture
    def batch_config(self):
        """Create batch configuration."""
        return BatchConfig(
            batch_size=16,
            sequence_length=50,
            overlap_ratio=0.1,
            sampling_strategy="sequential",
            shuffle_batches=False,
            validation_split=0.2,
            test_split=0.1
        )
    
    @pytest.fixture
    def mock_data_loader(self, sample_market_data):
        """Create mock data loader."""
        loader = Mock()
        loader.load_data.return_value = sample_market_data
        return loader
    
    @pytest.fixture
    def mock_preprocessor(self):
        """Create mock preprocessor."""
        preprocessor = Mock()
        preprocessor.is_fitted = False
        
        # Mock transform to return dummy features
        def mock_transform(data):
            return np.random.randn(len(data), 10)
        
        preprocessor.transform = mock_transform
        preprocessor.fit.return_value = preprocessor
        
        return preprocessor
    
    def test_batch_manager_initialization(self, batch_config, mock_data_loader, mock_preprocessor):
        """Test batch manager initialization."""
        batch_manager = BatchManager(batch_config, mock_data_loader, mock_preprocessor)
        
        assert batch_manager.config == batch_config
        assert batch_manager.data_loader == mock_data_loader
        assert batch_manager.preprocessor == mock_preprocessor
        assert len(batch_manager.train_data) == 0
        assert len(batch_manager.val_data) == 0
        assert len(batch_manager.test_data) == 0
    
    def test_data_preparation(self, batch_config, mock_data_loader, mock_preprocessor, sample_market_data):
        """Test data preparation and splitting."""
        batch_manager = BatchManager(batch_config, mock_data_loader, mock_preprocessor)
        
        batch_manager.prepare_data(["EUR/USD"], ["1H"])
        
        # Check data was loaded
        mock_data_loader.load_data.assert_called()
        
        # Check data was split
        total_samples = len(batch_manager.train_data) + len(batch_manager.val_data) + len(batch_manager.test_data)
        assert total_samples == len(sample_market_data)
        
        # Check split ratios approximately correct
        assert len(batch_manager.test_data) / total_samples == pytest.approx(0.1, abs=0.05)
        assert len(batch_manager.val_data) / total_samples == pytest.approx(0.2, abs=0.05)
    
    def test_single_batch_creation(self, batch_config, mock_data_loader, mock_preprocessor, sample_market_data):
        """Test single batch creation."""
        batch_manager = BatchManager(batch_config, mock_data_loader, mock_preprocessor)
        
        # Use subset of data for batch
        batch_data = sample_market_data[:100]
        
        states, next_states = batch_manager.create_single_batch(batch_data)
        
        assert isinstance(states, np.ndarray)
        assert isinstance(next_states, np.ndarray)
        assert states.shape[0] == next_states.shape[0]  # Same batch size
        assert states.shape[1] == batch_config.sequence_length
        assert next_states.shape[1] == batch_config.sequence_length
    
    def test_sequence_creation(self, batch_config, mock_data_loader, mock_preprocessor):
        """Test sequence creation from features."""
        batch_manager = BatchManager(batch_config, mock_data_loader, mock_preprocessor)
        
        # Create dummy features
        features = np.random.randn(100, 10)
        
        sequences = batch_manager._create_sequences(features)
        
        assert len(sequences) > 0
        assert len(sequences) <= batch_config.batch_size
        
        for sequence in sequences:
            assert sequence.shape[0] == batch_config.sequence_length + 1  # +1 for next state
            assert sequence.shape[1] == 10  # Feature dimension
    
    def test_batch_indices_creation_sequential(self, batch_config, mock_data_loader, mock_preprocessor):
        """Test sequential batch indices creation."""
        batch_config.sampling_strategy = "sequential"
        batch_manager = BatchManager(batch_config, mock_data_loader, mock_preprocessor)
        
        data_length = 1000
        indices = batch_manager._create_batch_indices(data_length)
        
        assert len(indices) > 0
        
        for start, end in indices:
            assert 0 <= start < end <= data_length
            assert end - start > 0
    
    def test_batch_indices_creation_random(self, batch_config, mock_data_loader, mock_preprocessor):
        """Test random batch indices creation."""
        batch_config.sampling_strategy = "random"
        batch_manager = BatchManager(batch_config, mock_data_loader, mock_preprocessor)
        
        data_length = 1000
        indices = batch_manager._create_batch_indices(data_length)
        
        assert len(indices) > 0
        
        for start, end in indices:
            assert 0 <= start < end <= data_length
    
    def test_batch_statistics(self, batch_config, mock_data_loader, mock_preprocessor, sample_market_data):
        """Test batch statistics tracking."""
        batch_manager = BatchManager(batch_config, mock_data_loader, mock_preprocessor)
        
        # Prepare data
        batch_manager.prepare_data(["EUR/USD"], ["1H"])
        
        # Create some batches
        batch_data = sample_market_data[:100]
        batch_manager.create_single_batch(batch_data)
        batch_manager.create_single_batch(batch_data)
        
        stats = batch_manager.get_batch_statistics()
        
        assert 'total_batches_created' in stats
        assert 'avg_batch_creation_time' in stats
        assert 'total_sequences' in stats
        assert stats['total_batches_created'] == 2
    
    def test_cache_operations(self, batch_config, mock_data_loader, mock_preprocessor):
        """Test batch cache operations."""
        batch_manager = BatchManager(batch_config, mock_data_loader, mock_preprocessor)
        
        # Cache should start empty
        assert len(batch_manager._batch_cache) == 0
        
        # Clear cache should work
        batch_manager.clear_cache()
        assert len(batch_manager._batch_cache) == 0
    
    def test_empty_data_handling(self, batch_config, mock_data_loader, mock_preprocessor):
        """Test handling of empty data."""
        batch_manager = BatchManager(batch_config, mock_data_loader, mock_preprocessor)
        
        # Test with empty data
        states, next_states = batch_manager.create_single_batch([])
        
        assert states.shape[0] == 0
        assert next_states.shape[0] == 0
    
    def test_insufficient_data_handling(self, batch_config, mock_data_loader, mock_preprocessor, sample_market_data):
        """Test handling of insufficient data for sequences."""
        batch_manager = BatchManager(batch_config, mock_data_loader, mock_preprocessor)
        
        # Use very small dataset
        small_data = sample_market_data[:10]  # Less than sequence_length
        
        states, next_states = batch_manager.create_single_batch(small_data)
        
        # Should return empty batch
        assert states.shape[0] == 0
        assert next_states.shape[0] == 0


class TestDataAugmentation:
    """Test cases for DataAugmentation."""
    
    @pytest.fixture
    def augmentation_config(self):
        """Create augmentation configuration."""
        return AugmentationConfig(
            augmentation_probability=1.0,  # Always augment for testing
            enable_noise=True,
            enable_scaling=True,
            enable_jittering=True,
            enable_time_warping=True,
            enable_magnitude_warping=True,
            noise_std=0.01,
            scaling_range=(0.95, 1.05),
            jitter_strength=0.005
        )
    
    @pytest.fixture
    def sample_sequences(self):
        """Create sample sequence data."""
        batch_size = 4
        seq_len = 20
        features = 5
        
        states = np.random.randn(batch_size, seq_len, features)
        next_states = np.random.randn(batch_size, seq_len, features)
        
        return states, next_states
    
    def test_augmentation_initialization(self, augmentation_config):
        """Test augmentation initialization."""
        augmentation = DataAugmentation(augmentation_config)
        
        assert augmentation.config == augmentation_config
        assert len(augmentation.techniques) > 0
        assert 'total_augmentations' in augmentation.augmentation_stats
    
    def test_noise_augmentation(self):
        """Test noise augmentation technique."""
        noise_aug = NoiseAugmentation(std=0.01)
        
        data = np.random.randn(10, 5)
        augmented = noise_aug.apply(data)
        
        assert augmented.shape == data.shape
        assert not np.array_equal(data, augmented)  # Should be different
        assert noise_aug.get_name() == "noise"
    
    def test_time_warping_augmentation(self):
        """Test time warping augmentation technique."""
        warp_aug = TimeWarpingAugmentation(max_warp_ratio=0.1)
        
        data = np.random.randn(20, 5)
        augmented = warp_aug.apply(data)
        
        assert augmented.shape == data.shape
        assert warp_aug.get_name() == "time_warping"
    
    def test_scaling_augmentation(self):
        """Test scaling augmentation technique."""
        scale_aug = ScalingAugmentation(scaling_range=(0.9, 1.1))
        
        data = np.random.randn(10, 5)
        augmented = scale_aug.apply(data)
        
        assert augmented.shape == data.shape
        assert not np.array_equal(data, augmented)
        assert scale_aug.get_name() == "scaling"
    
    def test_jittering_augmentation(self):
        """Test jittering augmentation technique."""
        jitter_aug = JitteringAugmentation(strength=0.01)
        
        data = np.random.randn(10, 5)
        augmented = jitter_aug.apply(data)
        
        assert augmented.shape == data.shape
        assert not np.array_equal(data, augmented)
        assert jitter_aug.get_name() == "jittering"
    
    def test_magnitude_warping_augmentation(self):
        """Test magnitude warping augmentation technique."""
        mag_warp_aug = MagnitudeWarpingAugmentation(sigma=0.2)
        
        data = np.random.randn(20, 5)
        augmented = mag_warp_aug.apply(data)
        
        assert augmented.shape == data.shape
        assert mag_warp_aug.get_name() == "magnitude_warping"
    
    def test_batch_augmentation(self, augmentation_config, sample_sequences):
        """Test batch augmentation."""
        augmentation = DataAugmentation(augmentation_config)
        
        states, next_states = sample_sequences
        aug_states, aug_next_states = augmentation.augment_batch(states, next_states)
        
        # Should have more samples due to augmentation
        assert aug_states.shape[0] >= states.shape[0]
        assert aug_next_states.shape[0] >= next_states.shape[0]
        assert aug_states.shape[0] == aug_next_states.shape[0]
        
        # Sequence length and features should remain the same
        assert aug_states.shape[1:] == states.shape[1:]
        assert aug_next_states.shape[1:] == next_states.shape[1:]
    
    def test_augmentation_statistics(self, augmentation_config, sample_sequences):
        """Test augmentation statistics tracking."""
        augmentation = DataAugmentation(augmentation_config)
        
        states, next_states = sample_sequences
        augmentation.augment_batch(states, next_states)
        
        stats = augmentation.get_augmentation_stats()
        
        assert 'total_augmentations' in stats
        assert 'technique_usage' in stats
        assert stats['total_augmentations'] > 0
    
    def test_augmentation_probability_zero(self, sample_sequences):
        """Test augmentation with zero probability."""
        config = AugmentationConfig(augmentation_probability=0.0)
        augmentation = DataAugmentation(config)
        
        states, next_states = sample_sequences
        aug_states, aug_next_states = augmentation.augment_batch(states, next_states)
        
        # Should return original data unchanged
        assert np.array_equal(states, aug_states)
        assert np.array_equal(next_states, aug_next_states)
    
    def test_statistics_reset(self, augmentation_config, sample_sequences):
        """Test statistics reset functionality."""
        augmentation = DataAugmentation(augmentation_config)
        
        # Generate some statistics
        states, next_states = sample_sequences
        augmentation.augment_batch(states, next_states)
        
        # Reset statistics
        augmentation.reset_stats()
        
        stats = augmentation.get_augmentation_stats()
        assert stats['total_augmentations'] == 0
        assert all(count == 0 for count in stats['technique_usage'].values())
    
    def test_market_data_augmentation(self, augmentation_config):
        """Test market data augmentation."""
        augmentation = DataAugmentation(augmentation_config)
        
        # Create sample market data
        from datetime import timezone
        base_time = datetime(2023, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        data = []
        
        for i in range(10):
            market_data = MarketData(
                symbol="EUR/USD",
                timestamp=base_time + timedelta(hours=i),
                open=1.1000,
                high=1.1005,
                low=1.0995,
                close=1.1002,
                volume=1000,
                bid=1.0999,
                ask=1.1001,
                spread=0.0002
            )
            data.append(market_data)
        
        augmented_data = augmentation.augment_market_data(data)
        
        assert len(augmented_data) == len(data)
        assert all(isinstance(item, MarketData) for item in augmented_data)
        
        # Prices should remain positive
        for market_data in augmented_data:
            assert market_data.open > 0
            assert market_data.high > 0
            assert market_data.low > 0
            assert market_data.close > 0
            assert market_data.bid > 0
            assert market_data.ask > 0
            assert market_data.spread >= 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])