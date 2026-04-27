"""
Feature Engineering Module for ML Pipeline.
Generates technical, volatility, and temporal features.
"""

import pandas as pd
import numpy as np
from typing import Optional, List
from utils.logger import get_logger


logger = get_logger(__name__)


class FeatureEngineer:
    """
    Feature engineering for machine learning models.
    Generates technical indicators, volatility measures, and time-based features.
    """
    
    def __init__(self, lookback_periods: int = 50):
        """
        Initialize FeatureEngineer.
        
        Args:
            lookback_periods: Number of periods to look back for features
        """
        self.lookback = lookback_periods
    
    def engineer_features(self, data: pd.DataFrame) -> Optional[pd.DataFrame]:
        """
        Generate all features from OHLCV data.
        
        Args:
            data: OHLCV DataFrame
        
        Returns:
            DataFrame with engineered features
        """
        if data is None or len(data) < 10:
            return None
        
        try:
            features = pd.DataFrame(index=data.index)
            
            # Technical indicators
            features = self._add_technical_features(features, data)
            
            # Volatility features
            features = self._add_volatility_features(features, data)
            
            # Trend features
            features = self._add_trend_features(features, data)
            
            # Time-of-day features
            if 'timestamp' in data.columns:
                features = self._add_time_features(features, data)
            
            # Momentum features
            features = self._add_momentum_features(features, data)
            
            # Remove rows with NaN
            features = features.dropna()
            
            return features
        
        except Exception as e:
            logger.error(f"Error engineering features: {e}")
            return None
    
    def _add_technical_features(self, features: pd.DataFrame, data: pd.DataFrame) -> pd.DataFrame:
        """Add technical indicator features."""
        # RSI
        features['rsi_14'] = self._calculate_rsi(data['close'], 14)
        features['rsi_7'] = self._calculate_rsi(data['close'], 7)
        
        # MACD
        macd = self._calculate_macd(data['close'])
        features['macd'] = macd['macd']
        features['macd_signal'] = macd['signal']
        features['macd_diff'] = macd['diff']
        
        # Moving Averages
        features['sma_20'] = data['close'].rolling(20).mean()
        features['sma_50'] = data['close'].rolling(50).mean()
        features['ema_12'] = data['close'].ewm(span=12).mean()
        features['ema_26'] = data['close'].ewm(span=26).mean()
        
        # Bollinger Bands
        sma20 = data['close'].rolling(20).mean()
        std20 = data['close'].rolling(20).std()
        features['bb_upper'] = sma20 + (std20 * 2)
        features['bb_lower'] = sma20 - (std20 * 2)
        features['bb_middle'] = sma20
        features['bb_width'] = (features['bb_upper'] - features['bb_lower']) / sma20
        
        # ATR
        features['atr_14'] = self._calculate_atr(data, 14)
        
        # Price position in band
        features['price_bb_position'] = (
            (data['close'] - features['bb_lower']) / 
            (features['bb_upper'] - features['bb_lower'])
        )
        
        return features
    
    def _add_volatility_features(self, features: pd.DataFrame, data: pd.DataFrame) -> pd.DataFrame:
        """Add volatility-based features."""
        # Historical volatility
        returns = data['close'].pct_change()
        features['volatility_20'] = returns.rolling(20).std()
        features['volatility_10'] = returns.rolling(10).std()
        
        # Range-based volatility
        hl_range = (data['high'] - data['low']) / data['close']
        features['hl_range_20'] = hl_range.rolling(20).mean()
        
        # Parkinson volatility (high-low range)
        features['parkinson_vol'] = np.sqrt(
            (1 / (4 * np.log(2))) * (np.log(data['high'] / data['low']) ** 2)
        ).rolling(20).mean()
        
        # Garman-Klass volatility
        features['gk_volatility'] = (
            0.5 * np.log(data['high'] / data['low']) ** 2 -
            (2 * np.log(2) - 1) * np.log(data['close'] / data['open']) ** 2
        ).rolling(20).mean()
        
        # FIX #3: Session High-Low Distance (intraday volatility proxy)
        # Distance from current price to recent session high/low
        rolling_high_20 = data['high'].rolling(20).max()
        rolling_low_20 = data['low'].rolling(20).min()
        
        features['distance_to_session_high'] = (rolling_high_20 - data['close']) / data['close']
        features['distance_to_session_low'] = (data['close'] - rolling_low_20) / data['close']
        features['session_range_position'] = (
            (data['close'] - rolling_low_20) / (rolling_high_20 - rolling_low_20)
        )
        
        # Volatility expansion/contraction ratio
        features['volatility_ratio'] = features['volatility_10'] / features['volatility_20']
        
        return features
    
    def _add_trend_features(self, features: pd.DataFrame, data: pd.DataFrame) -> pd.DataFrame:
        """Add trend-related features."""
        # Trend determination
        features['sma_slope_20'] = (
            data['close'].rolling(20).mean() - 
            data['close'].rolling(40).mean()
        )
        
        # Higher highs / Lower lows
        features['hh_ll_20'] = data['high'].rolling(20).max() > data['high'].rolling(41).max().shift(1)
        
        # Trend strength (ADX approximation)
        diff_high = data['high'].diff()
        diff_low = data['low'].diff()
        plus_dm = diff_high.where((diff_high > diff_low) & (diff_high > 0), 0)
        minus_dm = diff_low.where((diff_low > diff_high) & (diff_low > 0), 0)
        
        tr = self._calculate_tr(data)
        features['adx_approx'] = (
            (plus_dm.rolling(14).sum() - minus_dm.rolling(14).sum()) / 
            tr.rolling(14).sum()
        )
        
        # Price vs Moving Averages
        features['price_above_sma20'] = (data['close'] > features['sma_20']).astype(int)
        features['price_above_sma50'] = (data['close'] > features['sma_50']).astype(int)
        
        return features
    
    def _add_momentum_features(self, features: pd.DataFrame, data: pd.DataFrame) -> pd.DataFrame:
        """Add momentum-based features."""
        # Rate of change
        features['roc_10'] = data['close'].pct_change(10)
        features['roc_20'] = data['close'].pct_change(20)
        
        # Momentum
        features['momentum_10'] = data['close'] - data['close'].shift(10)
        features['momentum_20'] = data['close'] - data['close'].shift(20)
        
        # Returns
        features['returns_1'] = data['close'].pct_change(1)
        features['returns_5'] = data['close'].pct_change(5)
        features['returns_20'] = data['close'].pct_change(20)
        
        # FIX #3: RSI Lag Features (momentum persistence)
        # RSI at previous time steps to capture momentum trends
        if 'rsi_14' in features.columns:
            features['rsi_lag_1'] = features['rsi_14'].shift(1)
            features['rsi_lag_3'] = features['rsi_14'].shift(3)
            features['rsi_lag_5'] = features['rsi_14'].shift(5)
            features['rsi_change_1'] = features['rsi_14'] - features['rsi_lag_1']
            features['rsi_change_3'] = features['rsi_14'] - features['rsi_lag_3']
            features['rsi_change_5'] = features['rsi_14'] - features['rsi_lag_5']
            
            # RSI-price divergence (momentum vs price movement)
            price_change_5 = data['close'].pct_change(5)
            features['rsi_price_divergence'] = features['rsi_change_5'] - price_change_5
        
        # Volume weighted price
        if 'volume' in data.columns:
            features['vwap'] = (data['close'] * data['volume']).rolling(20).sum() / data['volume'].rolling(20).sum()
        
        return features
    
    def _add_time_features(self, features: pd.DataFrame, data: pd.DataFrame) -> pd.DataFrame:
        """Add time-based features."""
        if 'timestamp' not in data.columns:
            return features
        
        timestamps = pd.to_datetime(data['timestamp'])
        
        # Hour, day of week
        features['hour'] = timestamps.dt.hour
        features['day_of_week'] = timestamps.dt.dayofweek
        features['day_of_month'] = timestamps.dt.day
        features['month'] = timestamps.dt.month
        
        # Sydney, London, New York session indicators
        features['sydney_session'] = ((timestamps.dt.hour >= 21) | (timestamps.dt.hour < 7)).astype(int)
        features['london_session'] = ((timestamps.dt.hour >= 7) & (timestamps.dt.hour < 16)).astype(int)
        features['ny_session'] = ((timestamps.dt.hour >= 12) & (timestamps.dt.hour < 21)).astype(int)
        
        return features
    
    def _calculate_rsi(self, prices: pd.Series, period: int = 14) -> pd.Series:
        """Calculate RSI indicator."""
        delta = prices.diff()
        gains = delta.where(delta > 0, 0).rolling(window=period).mean()
        losses = -delta.where(delta < 0, 0).rolling(window=period).mean()
        
        rs = gains / losses
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    def _calculate_macd(self, prices: pd.Series) -> dict:
        """Calculate MACD indicator."""
        ema_12 = prices.ewm(span=12).mean()
        ema_26 = prices.ewm(span=26).mean()
        
        macd = ema_12 - ema_26
        signal = macd.ewm(span=9).mean()
        diff = macd - signal
        
        return {
            'macd': macd,
            'signal': signal,
            'diff': diff
        }
    
    def _calculate_atr(self, data: pd.DataFrame, period: int = 14) -> pd.Series:
        """Calculate ATR indicator."""
        tr = self._calculate_tr(data)
        atr = tr.rolling(window=period).mean()
        return atr
    
    def _calculate_tr(self, data: pd.DataFrame) -> pd.Series:
        """Calculate True Range."""
        tr1 = data['high'] - data['low']
        tr2 = abs(data['high'] - data['close'].shift(1))
        tr3 = abs(data['low'] - data['close'].shift(1))
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr


class FeatureSelector:
    """
    Feature selection and normalization.
    Identifies most important features and normalizes them.
    """
    
    def __init__(self, selected_features: Optional[List[str]] = None):
        """
        Initialize FeatureSelector.
        
        Args:
            selected_features: List of feature names to use
        """
        self.selected_features = selected_features or self._get_default_features()
        self.scaler = None
    
    def select_features(self, features: pd.DataFrame) -> pd.DataFrame:
        """Select relevant features from engineered features."""
        available_features = [f for f in self.selected_features if f in features.columns]
        
        if not available_features:
            logger.warning("No selected features found. Using all features.")
            return features.dropna()
        
        return features[available_features].dropna()
    
    def _get_default_features(self) -> List[str]:
        """Get default feature list."""
        return [
            # Technical
            'rsi_14', 'rsi_7',
            'macd', 'macd_signal', 'macd_diff',
            'sma_20', 'sma_50',
            'atr_14',
            'bb_width', 'price_bb_position',
            
            # Volatility (ENHANCED)
            'volatility_20', 'volatility_10',
            'hl_range_20', 'parkinson_vol',
            'distance_to_session_high', 'distance_to_session_low',
            'session_range_position', 'volatility_ratio',
            
            # Trend (ENHANCED)
            'sma_slope_20', 'adx_approx',
            'price_above_sma20', 'price_above_sma50',
            'adx_trend_strength', 'adx_rising', 'adx_falling',
            'strong_trend', 'weak_trend',
            
            # Momentum (ENHANCED)
            'roc_10', 'roc_20',
            'momentum_10', 'momentum_20',
            'returns_1', 'returns_5', 'returns_20',
            
            # NEW: RSI Lag Features (momentum persistence)
            'rsi_lag_1', 'rsi_lag_3', 'rsi_lag_5',
            'rsi_change_1', 'rsi_change_3', 'rsi_change_5',
            'rsi_price_divergence',
        ]
