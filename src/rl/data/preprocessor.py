"""
Data Preprocessor for RL Training

Handles preprocessing and normalization of market data for RL training,
including feature engineering and data transformation.
"""

import numpy as np
import pandas as pd
from typing import List, Dict, Optional, Tuple, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
import warnings

# Optional sklearn imports with fallbacks
try:
    from sklearn.preprocessing import StandardScaler, MinMaxScaler, RobustScaler
    from sklearn.decomposition import PCA
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    
    # Fallback implementations
    class StandardScaler:
        def __init__(self):
            self.mean_ = None
            self.scale_ = None
            
        def fit(self, X):
            self.mean_ = np.mean(X, axis=0)
            self.scale_ = np.std(X, axis=0)
            self.scale_[self.scale_ == 0] = 1  # Avoid division by zero
            return self
            
        def transform(self, X):
            return (X - self.mean_) / self.scale_
            
        def inverse_transform(self, X):
            return X * self.scale_ + self.mean_
    
    class MinMaxScaler:
        def __init__(self, feature_range=(-1, 1)):
            self.feature_range = feature_range
            self.min_ = None
            self.scale_ = None
            
        def fit(self, X):
            self.min_ = np.min(X, axis=0)
            self.scale_ = np.max(X, axis=0) - self.min_
            self.scale_[self.scale_ == 0] = 1  # Avoid division by zero
            return self
            
        def transform(self, X):
            X_std = (X - self.min_) / self.scale_
            return X_std * (self.feature_range[1] - self.feature_range[0]) + self.feature_range[0]
            
        def inverse_transform(self, X):
            X_std = (X - self.feature_range[0]) / (self.feature_range[1] - self.feature_range[0])
            return X_std * self.scale_ + self.min_
    
    class RobustScaler:
        def __init__(self):
            self.center_ = None
            self.scale_ = None
            
        def fit(self, X):
            self.center_ = np.median(X, axis=0)
            q75 = np.percentile(X, 75, axis=0)
            q25 = np.percentile(X, 25, axis=0)
            self.scale_ = q75 - q25
            self.scale_[self.scale_ == 0] = 1  # Avoid division by zero
            return self
            
        def transform(self, X):
            return (X - self.center_) / self.scale_
            
        def inverse_transform(self, X):
            return X * self.scale_ + self.center_
    
    class PCA:
        def __init__(self, n_components=None, random_state=None):
            self.n_components = n_components
            self.n_components_ = n_components
            self.explained_variance_ratio_ = None
            
        def fit(self, X):
            # Simple PCA implementation using SVD
            X_centered = X - np.mean(X, axis=0)
            U, s, Vt = np.linalg.svd(X_centered, full_matrices=False)
            
            if self.n_components is None:
                self.n_components_ = min(X.shape)
            else:
                self.n_components_ = min(self.n_components, min(X.shape))
                
            self.components_ = Vt[:self.n_components_]
            
            # Calculate explained variance ratio
            explained_variance = (s ** 2) / (X.shape[0] - 1)
            total_variance = np.sum(explained_variance)
            self.explained_variance_ratio_ = explained_variance[:self.n_components_] / total_variance
            
            return self
            
        def transform(self, X):
            X_centered = X - np.mean(X, axis=0)
            return np.dot(X_centered, self.components_.T)
            
        def inverse_transform(self, X):
            return np.dot(X, self.components_)

from ...models import MarketData
from ..environments.technical_indicators import TechnicalIndicators


@dataclass
class PreprocessorConfig:
    """Configuration for data preprocessor."""
    
    # Normalization settings
    normalization_method: str = "standard"  # "standard", "minmax", "robust", "none"
    feature_range: Tuple[float, float] = (-1.0, 1.0)
    
    # Technical indicators
    enable_technical_indicators: bool = True
    technical_indicators: List[str] = field(default_factory=lambda: [
        "sma_20", "sma_50", "ema_12", "ema_26", "rsi_14", "macd", "bb_upper", "bb_lower", "stoch_k", "stoch_d"
    ])
    
    # Feature engineering
    enable_price_features: bool = True
    enable_volume_features: bool = True
    enable_spread_features: bool = True
    enable_time_features: bool = True
    enable_lag_features: bool = True
    lag_periods: List[int] = field(default_factory=lambda: [1, 2, 3, 5, 10])
    
    # Rolling statistics
    enable_rolling_stats: bool = True
    rolling_windows: List[int] = field(default_factory=lambda: [5, 10, 20])
    rolling_stats: List[str] = field(default_factory=lambda: ["mean", "std", "min", "max"])
    
    # Data filtering
    remove_outliers: bool = True
    outlier_method: str = "iqr"  # "iqr", "zscore", "isolation_forest"
    outlier_threshold: float = 3.0
    
    # Dimensionality reduction
    enable_pca: bool = False
    pca_components: Optional[int] = None
    pca_variance_threshold: float = 0.95
    
    # Missing data handling
    fill_method: str = "forward"  # "forward", "backward", "interpolate", "drop"
    max_missing_ratio: float = 0.05
    
    # Memory optimization
    use_float32: bool = True
    chunk_processing: bool = True
    chunk_size: int = 10000


class DataPreprocessor:
    """
    Comprehensive data preprocessor for RL training data.
    
    Handles normalization, feature engineering, technical indicators,
    and data cleaning for market data.
    """
    
    def __init__(self, config: PreprocessorConfig):
        """
        Initialize data preprocessor.
        
        Args:
            config: Preprocessor configuration
        """
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # Initialize scalers
        self.scalers = {}
        self.is_fitted = False
        
        # Technical indicators calculator
        self.tech_indicators = TechnicalIndicators()
        
        # PCA transformer
        self.pca = None
        if self.config.enable_pca:
            self.pca = PCA(
                n_components=self.config.pca_components,
                random_state=42
            )
            
        # Feature names for tracking
        self.feature_names = []
        
        # Statistics for monitoring
        self.preprocessing_stats = {
            "total_samples": 0,
            "removed_outliers": 0,
            "filled_missing": 0,
            "feature_count": 0
        }
        
    def fit(self, data: List[MarketData]) -> 'DataPreprocessor':
        """
        Fit preprocessor on training data.
        
        Args:
            data: List of MarketData objects for fitting
            
        Returns:
            Self for method chaining
        """
        self.logger.info(f"Fitting preprocessor on {len(data)} samples")
        
        # Convert to DataFrame for easier processing
        df = self._convert_to_dataframe(data)
        
        # Generate features
        features_df = self._generate_features(df)
        
        # Handle missing values
        features_df = self._handle_missing_values(features_df)
        
        # Remove outliers for fitting
        if self.config.remove_outliers:
            features_df = self._remove_outliers(features_df)
            
        # Fit scalers
        self._fit_scalers(features_df)
        
        # Fit PCA if enabled
        if self.config.enable_pca:
            normalized_features = self._apply_normalization(features_df)
            self.pca.fit(normalized_features)
            
            # Update feature count based on PCA components
            if self.config.pca_components is None:
                # Determine components based on variance threshold
                cumsum_ratio = np.cumsum(self.pca.explained_variance_ratio_)
                n_components = np.argmax(cumsum_ratio >= self.config.pca_variance_threshold) + 1
                self.pca.n_components = n_components
                
        self.is_fitted = True
        self.preprocessing_stats["feature_count"] = len(self.feature_names)
        
        self.logger.info(f"Preprocessor fitted with {len(self.feature_names)} features")
        return self
        
    def transform(self, data: List[MarketData]) -> np.ndarray:
        """
        Transform data using fitted preprocessor.
        
        Args:
            data: List of MarketData objects to transform
            
        Returns:
            Preprocessed feature matrix
            
        Raises:
            RuntimeError: If preprocessor not fitted
        """
        if not self.is_fitted:
            raise RuntimeError("Preprocessor must be fitted before transform")
            
        # Convert to DataFrame
        df = self._convert_to_dataframe(data)
        
        # Generate features
        features_df = self._generate_features(df)
        
        # Handle missing values
        features_df = self._handle_missing_values(features_df)
        
        # Apply normalization
        normalized_features = self._apply_normalization(features_df)
        
        # Apply PCA if enabled
        if self.config.enable_pca and self.pca is not None:
            normalized_features = self.pca.transform(normalized_features)
            
        # Convert to appropriate dtype
        if self.config.use_float32:
            normalized_features = normalized_features.astype(np.float32)
            
        self.preprocessing_stats["total_samples"] += len(data)
        
        return normalized_features
        
    def fit_transform(self, data: List[MarketData]) -> np.ndarray:
        """
        Fit preprocessor and transform data in one step.
        
        Args:
            data: List of MarketData objects
            
        Returns:
            Preprocessed feature matrix
        """
        return self.fit(data).transform(data)
        
    def inverse_transform(self, features: np.ndarray) -> np.ndarray:
        """
        Inverse transform normalized features back to original scale.
        
        Args:
            features: Normalized feature matrix
            
        Returns:
            Features in original scale
        """
        if not self.is_fitted:
            raise RuntimeError("Preprocessor must be fitted before inverse transform")
            
        # Inverse PCA if enabled
        if self.config.enable_pca and self.pca is not None:
            features = self.pca.inverse_transform(features)
            
        # Inverse normalization
        result = features.copy()
        
        for i, feature_name in enumerate(self.feature_names):
            if feature_name in self.scalers:
                scaler = self.scalers[feature_name]
                result[:, i] = scaler.inverse_transform(result[:, i].reshape(-1, 1)).flatten()
                
        return result
        
    def get_feature_names(self) -> List[str]:
        """Get names of generated features."""
        if self.config.enable_pca and self.pca is not None:
            n_components = self.pca.n_components_
            return [f"pca_component_{i}" for i in range(n_components)]
        return self.feature_names.copy()
        
    def get_feature_importance(self) -> Dict[str, float]:
        """
        Get feature importance scores (if PCA is used).
        
        Returns:
            Dictionary mapping feature names to importance scores
        """
        if not self.config.enable_pca or self.pca is None:
            return {name: 1.0 for name in self.feature_names}
            
        # Use PCA explained variance as importance
        importance = {}
        for i, variance in enumerate(self.pca.explained_variance_ratio_):
            importance[f"pca_component_{i}"] = variance
            
        return importance
        
    def get_preprocessing_stats(self) -> Dict[str, Any]:
        """Get preprocessing statistics."""
        return self.preprocessing_stats.copy()
        
    def _convert_to_dataframe(self, data: List[MarketData]) -> pd.DataFrame:
        """Convert MarketData list to pandas DataFrame."""
        records = []
        for market_data in data:
            record = {
                'timestamp': market_data.timestamp,
                'symbol': market_data.symbol,
                'open': market_data.open,
                'high': market_data.high,
                'low': market_data.low,
                'close': market_data.close,
                'volume': market_data.volume,
                'bid': market_data.bid,
                'ask': market_data.ask,
                'spread': market_data.spread
            }
            records.append(record)
            
        df = pd.DataFrame(records)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.sort_values('timestamp').reset_index(drop=True)
        
        return df
        
    def _generate_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate all features from market data."""
        features_df = pd.DataFrame(index=df.index)
        self.feature_names = []
        
        # Basic price features
        if self.config.enable_price_features:
            features_df = self._add_price_features(features_df, df)
            
        # Volume features
        if self.config.enable_volume_features:
            features_df = self._add_volume_features(features_df, df)
            
        # Spread features
        if self.config.enable_spread_features:
            features_df = self._add_spread_features(features_df, df)
            
        # Time features
        if self.config.enable_time_features:
            features_df = self._add_time_features(features_df, df)
            
        # Technical indicators
        if self.config.enable_technical_indicators:
            features_df = self._add_technical_indicators(features_df, df)
            
        # Lag features
        if self.config.enable_lag_features:
            features_df = self._add_lag_features(features_df, df)
            
        # Rolling statistics
        if self.config.enable_rolling_stats:
            features_df = self._add_rolling_statistics(features_df, df)
            
        return features_df
        
    def _add_price_features(self, features_df: pd.DataFrame, df: pd.DataFrame) -> pd.DataFrame:
        """Add price-based features."""
        # Basic price features
        features_df['open'] = df['open']
        features_df['high'] = df['high']
        features_df['low'] = df['low']
        features_df['close'] = df['close']
        
        # Price ratios and differences
        features_df['hl_ratio'] = (df['high'] - df['low']) / df['close']
        features_df['oc_ratio'] = (df['close'] - df['open']) / df['open']
        features_df['price_range'] = (df['high'] - df['low']) / df['low']
        
        # Price changes
        features_df['price_change'] = df['close'].pct_change()
        features_df['price_change_abs'] = np.abs(features_df['price_change'])
        
        # Log returns
        features_df['log_return'] = np.log(df['close'] / df['close'].shift(1))
        
        # Typical price
        features_df['typical_price'] = (df['high'] + df['low'] + df['close']) / 3
        
        # Weighted close
        features_df['weighted_close'] = (df['high'] + df['low'] + 2 * df['close']) / 4
        
        self.feature_names.extend([
            'open', 'high', 'low', 'close', 'hl_ratio', 'oc_ratio', 'price_range',
            'price_change', 'price_change_abs', 'log_return', 'typical_price', 'weighted_close'
        ])
        
        return features_df
        
    def _add_volume_features(self, features_df: pd.DataFrame, df: pd.DataFrame) -> pd.DataFrame:
        """Add volume-based features."""
        features_df['volume'] = df['volume']
        features_df['volume_change'] = df['volume'].pct_change()
        features_df['volume_ma'] = df['volume'].rolling(window=20).mean()
        features_df['volume_ratio'] = df['volume'] / features_df['volume_ma']
        
        # Price-volume features
        features_df['price_volume'] = df['close'] * df['volume']
        features_df['vwap'] = (features_df['price_volume'].rolling(window=20).sum() / 
                              df['volume'].rolling(window=20).sum())
        
        self.feature_names.extend([
            'volume', 'volume_change', 'volume_ma', 'volume_ratio', 'price_volume', 'vwap'
        ])
        
        return features_df
        
    def _add_spread_features(self, features_df: pd.DataFrame, df: pd.DataFrame) -> pd.DataFrame:
        """Add spread-based features."""
        features_df['bid'] = df['bid']
        features_df['ask'] = df['ask']
        features_df['spread'] = df['spread']
        features_df['spread_pct'] = df['spread'] / df['close']
        features_df['mid_price'] = (df['bid'] + df['ask']) / 2
        features_df['bid_ask_imbalance'] = (df['ask'] - df['bid']) / (df['ask'] + df['bid'])
        
        self.feature_names.extend([
            'bid', 'ask', 'spread', 'spread_pct', 'mid_price', 'bid_ask_imbalance'
        ])
        
        return features_df
        
    def _add_time_features(self, features_df: pd.DataFrame, df: pd.DataFrame) -> pd.DataFrame:
        """Add time-based features."""
        timestamps = pd.to_datetime(df['timestamp'])
        
        features_df['hour'] = timestamps.dt.hour
        features_df['day_of_week'] = timestamps.dt.dayofweek
        features_df['day_of_month'] = timestamps.dt.day
        features_df['month'] = timestamps.dt.month
        features_df['quarter'] = timestamps.dt.quarter
        
        # Cyclical encoding for time features
        features_df['hour_sin'] = np.sin(2 * np.pi * features_df['hour'] / 24)
        features_df['hour_cos'] = np.cos(2 * np.pi * features_df['hour'] / 24)
        features_df['dow_sin'] = np.sin(2 * np.pi * features_df['day_of_week'] / 7)
        features_df['dow_cos'] = np.cos(2 * np.pi * features_df['day_of_week'] / 7)
        
        # Market session indicators
        features_df['asian_session'] = ((features_df['hour'] >= 0) & (features_df['hour'] < 8)).astype(int)
        features_df['european_session'] = ((features_df['hour'] >= 8) & (features_df['hour'] < 16)).astype(int)
        features_df['american_session'] = ((features_df['hour'] >= 16) & (features_df['hour'] < 24)).astype(int)
        
        self.feature_names.extend([
            'hour', 'day_of_week', 'day_of_month', 'month', 'quarter',
            'hour_sin', 'hour_cos', 'dow_sin', 'dow_cos',
            'asian_session', 'european_session', 'american_session'
        ])
        
        return features_df
        
    def _add_technical_indicators(self, features_df: pd.DataFrame, df: pd.DataFrame) -> pd.DataFrame:
        """Add technical indicators."""
        prices = df['close'].values
        highs = df['high'].values
        lows = df['low'].values
        volumes = df['volume'].values
        
        for indicator in self.config.technical_indicators:
            try:
                if indicator == "sma_20":
                    features_df['sma_20'] = self.tech_indicators.sma(prices, 20)
                elif indicator == "sma_50":
                    features_df['sma_50'] = self.tech_indicators.sma(prices, 50)
                elif indicator == "ema_12":
                    features_df['ema_12'] = self.tech_indicators.ema(prices, 12)
                elif indicator == "ema_26":
                    features_df['ema_26'] = self.tech_indicators.ema(prices, 26)
                elif indicator == "rsi_14":
                    features_df['rsi_14'] = self.tech_indicators.rsi(prices, 14)
                elif indicator == "macd":
                    macd_line, signal_line, histogram = self.tech_indicators.macd(prices)
                    features_df['macd_line'] = macd_line
                    features_df['macd_signal'] = signal_line
                    features_df['macd_histogram'] = histogram
                elif indicator == "bb_upper":
                    upper, middle, lower = self.tech_indicators.bollinger_bands(prices, 20, 2)
                    features_df['bb_upper'] = upper
                    features_df['bb_middle'] = middle
                    features_df['bb_lower'] = lower
                elif indicator == "stoch_k":
                    k_percent, d_percent = self.tech_indicators.stochastic_oscillator(highs, lows, prices, 14, 3)
                    features_df['stoch_k'] = k_percent
                    features_df['stoch_d'] = d_percent
                    
            except Exception as e:
                self.logger.warning(f"Failed to calculate {indicator}: {e}")
                
        # Update feature names based on what was actually added
        current_features = [col for col in features_df.columns if col not in self.feature_names]
        self.feature_names.extend(current_features)
        
        return features_df
        
    def _add_lag_features(self, features_df: pd.DataFrame, df: pd.DataFrame) -> pd.DataFrame:
        """Add lagged features."""
        base_features = ['close', 'volume', 'spread']
        
        for feature in base_features:
            if feature in df.columns:
                for lag in self.config.lag_periods:
                    lag_feature_name = f"{feature}_lag_{lag}"
                    features_df[lag_feature_name] = df[feature].shift(lag)
                    self.feature_names.append(lag_feature_name)
                    
        return features_df
        
    def _add_rolling_statistics(self, features_df: pd.DataFrame, df: pd.DataFrame) -> pd.DataFrame:
        """Add rolling statistics features."""
        base_features = ['close', 'volume']
        
        for feature in base_features:
            if feature in df.columns:
                for window in self.config.rolling_windows:
                    for stat in self.config.rolling_stats:
                        stat_feature_name = f"{feature}_rolling_{stat}_{window}"
                        
                        if stat == "mean":
                            features_df[stat_feature_name] = df[feature].rolling(window=window).mean()
                        elif stat == "std":
                            features_df[stat_feature_name] = df[feature].rolling(window=window).std()
                        elif stat == "min":
                            features_df[stat_feature_name] = df[feature].rolling(window=window).min()
                        elif stat == "max":
                            features_df[stat_feature_name] = df[feature].rolling(window=window).max()
                            
                        self.feature_names.append(stat_feature_name)
                        
        return features_df
        
    def _handle_missing_values(self, features_df: pd.DataFrame) -> pd.DataFrame:
        """Handle missing values in features."""
        missing_ratio = features_df.isnull().sum() / len(features_df)
        
        # Drop features with too many missing values
        features_to_drop = missing_ratio[missing_ratio > self.config.max_missing_ratio].index
        if len(features_to_drop) > 0:
            self.logger.warning(f"Dropping {len(features_to_drop)} features with high missing ratio")
            features_df = features_df.drop(columns=features_to_drop)
            self.feature_names = [name for name in self.feature_names if name not in features_to_drop]
            
        # Fill remaining missing values
        if self.config.fill_method == "forward":
            features_df = features_df.ffill()
        elif self.config.fill_method == "backward":
            features_df = features_df.bfill()
        elif self.config.fill_method == "interpolate":
            features_df = features_df.interpolate()
        elif self.config.fill_method == "drop":
            features_df = features_df.dropna()
            
        # Fill any remaining NaN with 0
        features_df = features_df.fillna(0)
        
        self.preprocessing_stats["filled_missing"] += features_df.isnull().sum().sum()
        
        return features_df
        
    def _remove_outliers(self, features_df: pd.DataFrame) -> pd.DataFrame:
        """Remove outliers from features."""
        if self.config.outlier_method == "iqr":
            return self._remove_outliers_iqr(features_df)
        elif self.config.outlier_method == "zscore":
            return self._remove_outliers_zscore(features_df)
        elif self.config.outlier_method == "isolation_forest":
            return self._remove_outliers_isolation_forest(features_df)
        else:
            return features_df
            
    def _remove_outliers_iqr(self, features_df: pd.DataFrame) -> pd.DataFrame:
        """Remove outliers using IQR method."""
        Q1 = features_df.quantile(0.25)
        Q3 = features_df.quantile(0.75)
        IQR = Q3 - Q1
        
        lower_bound = Q1 - 1.5 * IQR
        upper_bound = Q3 + 1.5 * IQR
        
        # Create mask for outliers
        outlier_mask = ((features_df < lower_bound) | (features_df > upper_bound)).any(axis=1)
        
        self.preprocessing_stats["removed_outliers"] += outlier_mask.sum()
        
        return features_df[~outlier_mask]
        
    def _remove_outliers_zscore(self, features_df: pd.DataFrame) -> pd.DataFrame:
        """Remove outliers using Z-score method."""
        z_scores = np.abs((features_df - features_df.mean()) / features_df.std())
        outlier_mask = (z_scores > self.config.outlier_threshold).any(axis=1)
        
        self.preprocessing_stats["removed_outliers"] += outlier_mask.sum()
        
        return features_df[~outlier_mask]
        
    def _remove_outliers_isolation_forest(self, features_df: pd.DataFrame) -> pd.DataFrame:
        """Remove outliers using Isolation Forest."""
        if not SKLEARN_AVAILABLE:
            self.logger.warning("scikit-learn not available for Isolation Forest, falling back to IQR method")
            return self._remove_outliers_iqr(features_df)
            
        try:
            from sklearn.ensemble import IsolationForest
            
            iso_forest = IsolationForest(contamination=0.1, random_state=42)
            outlier_labels = iso_forest.fit_predict(features_df)
            
            outlier_mask = outlier_labels == -1
            self.preprocessing_stats["removed_outliers"] += outlier_mask.sum()
            
            return features_df[~outlier_mask]
            
        except ImportError:
            self.logger.warning("scikit-learn not available for Isolation Forest, falling back to IQR method")
            return self._remove_outliers_iqr(features_df)
            
    def _fit_scalers(self, features_df: pd.DataFrame) -> None:
        """Fit normalization scalers."""
        for column in features_df.columns:
            if self.config.normalization_method == "standard":
                scaler = StandardScaler()
            elif self.config.normalization_method == "minmax":
                scaler = MinMaxScaler(feature_range=self.config.feature_range)
            elif self.config.normalization_method == "robust":
                scaler = RobustScaler()
            else:
                continue
                
            # Fit scaler on non-null values
            valid_data = features_df[column].dropna().values.reshape(-1, 1)
            if len(valid_data) > 0:
                scaler.fit(valid_data)
                self.scalers[column] = scaler
                
    def _apply_normalization(self, features_df: pd.DataFrame) -> np.ndarray:
        """Apply fitted normalization to features."""
        if self.config.normalization_method == "none":
            return features_df.values
            
        normalized_features = features_df.copy()
        
        for column in features_df.columns:
            if column in self.scalers:
                scaler = self.scalers[column]
                normalized_features[column] = scaler.transform(
                    features_df[column].values.reshape(-1, 1)
                ).flatten()
                
        return normalized_features.values