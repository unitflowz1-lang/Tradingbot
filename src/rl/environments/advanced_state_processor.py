"""
Advanced State Processor for RL Trading Environment

This module provides enhanced state processing with sophisticated
feature engineering, normalization, and feature selection capabilities.
"""

import numpy as np
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import warnings

from ...models import MarketData
from .base import PortfolioState, EnvironmentConfig
from .state_processor import StateProcessor
from .technical_indicators import TechnicalIndicators, IndicatorConfig


class NormalizationMethod(Enum):
    """Normalization methods for features."""
    MINMAX = "minmax"
    ZSCORE = "zscore"
    ROBUST = "robust"
    QUANTILE = "quantile"
    NONE = "none"


@dataclass
class FeatureConfig:
    """Configuration for feature engineering."""
    # Price features
    include_ohlc: bool = True
    include_returns: bool = True
    include_log_returns: bool = True
    include_price_ratios: bool = True
    
    # Technical indicators
    include_trend_indicators: bool = True
    include_momentum_indicators: bool = True
    include_volatility_indicators: bool = True
    include_volume_indicators: bool = True
    include_support_resistance: bool = True
    
    # Advanced features
    include_market_microstructure: bool = True
    include_regime_features: bool = True
    include_cross_asset_features: bool = False
    include_sentiment_features: bool = False
    
    # Feature selection
    max_features: Optional[int] = None
    feature_selection_method: str = "variance"  # "variance", "correlation", "mutual_info"
    
    # Normalization
    normalization_method: NormalizationMethod = NormalizationMethod.ROBUST
    normalization_window: int = 100
    
    # Lookback windows for different feature types
    price_lookback: int = 20
    technical_lookback: int = 50
    volatility_lookback: int = 30


class AdvancedStateProcessor(StateProcessor):
    """
    Advanced state processor with comprehensive feature engineering.
    
    Provides sophisticated feature extraction, normalization, and selection
    capabilities for optimal RL agent training.
    """
    
    def __init__(self, 
                 env_config: EnvironmentConfig,
                 feature_config: FeatureConfig = None,
                 indicator_config: IndicatorConfig = None):
        """
        Initialize advanced state processor.
        
        Args:
            env_config: Environment configuration
            feature_config: Feature engineering configuration
            indicator_config: Technical indicator configuration
        """
        self.env_config = env_config
        self.feature_config = feature_config or FeatureConfig()
        self.indicator_config = indicator_config or IndicatorConfig()
        
        # Initialize technical indicators calculator
        self.tech_indicators = TechnicalIndicators(self.indicator_config)
        
        # Feature normalization state
        self.feature_stats = {}
        self.normalization_history = {}
        
        # Calculate total feature dimension
        self.total_dim = self._calculate_feature_dimension()
        
        # Feature names for debugging and analysis
        self.feature_names = self._generate_feature_names()
        
    def process_market_data(self, 
                          market_data: List[MarketData], 
                          portfolio_state: PortfolioState) -> np.ndarray:
        """
        Process market data into advanced feature vector.
        
        Args:
            market_data: List of market data (lookback window)
            portfolio_state: Current portfolio state
            
        Returns:
            Advanced normalized feature vector
        """
        if not market_data:
            return np.zeros(self.total_dim)
            
        # Ensure sufficient data
        market_data = self._ensure_sufficient_data(market_data)
        
        features = []
        
        # 1. Price-based features
        if self.feature_config.include_ohlc or self.feature_config.include_returns:
            price_features = self._extract_price_features(market_data)
            features.extend(price_features)
            
        # 2. Technical indicator features
        technical_features = self._extract_technical_features(market_data)
        features.extend(technical_features)
        
        # 3. Market microstructure features
        if self.feature_config.include_market_microstructure:
            microstructure_features = self._extract_microstructure_features(market_data)
            features.extend(microstructure_features)
            
        # 4. Market regime features
        if self.feature_config.include_regime_features:
            regime_features = self._extract_regime_features(market_data)
            features.extend(regime_features)
            
        # 5. Portfolio features
        portfolio_features = self._extract_portfolio_features(portfolio_state)
        features.extend(portfolio_features)
        
        # 6. Temporal features
        temporal_features = self._extract_temporal_features(market_data[-1])
        features.extend(temporal_features)
        
        # Convert to numpy array
        feature_vector = np.array(features, dtype=np.float32)
        
        # Handle NaN and infinite values
        feature_vector = self._handle_invalid_values(feature_vector)
        
        # Apply normalization
        feature_vector = self._normalize_features(feature_vector)
        
        # Apply feature selection if configured
        if self.feature_config.max_features:
            feature_vector = self._select_features(feature_vector)
            
        return feature_vector
        
    def get_state_dimension(self) -> int:
        """Return the dimension of the state space."""
        if self.feature_config.max_features:
            return min(self.feature_config.max_features, self.total_dim)
        return self.total_dim
        
    def get_feature_names(self) -> List[str]:
        """Get names of all features for analysis."""
        return self.feature_names.copy()
        
    def _extract_price_features(self, market_data: List[MarketData]) -> List[float]:
        """Extract comprehensive price-based features."""
        features = []
        
        # Extract price arrays
        opens = [d.open for d in market_data]
        highs = [d.high for d in market_data]
        lows = [d.low for d in market_data]
        closes = [d.close for d in market_data]
        
        lookback = min(self.feature_config.price_lookback, len(market_data))
        
        if self.feature_config.include_ohlc:
            # Normalized OHLC features
            base_price = closes[0] if closes else 1.0
            
            for i in range(-lookback, 0):
                if abs(i) <= len(closes):
                    idx = i if i < 0 else len(closes) - 1
                    features.extend([
                        (opens[idx] - base_price) / base_price,
                        (highs[idx] - base_price) / base_price,
                        (lows[idx] - base_price) / base_price,
                        (closes[idx] - base_price) / base_price
                    ])
                else:
                    features.extend([0.0, 0.0, 0.0, 0.0])
                    
        if self.feature_config.include_returns:
            # Simple returns
            returns = self._calculate_returns(closes, lookback)
            features.extend(returns)
            
        if self.feature_config.include_log_returns:
            # Log returns
            log_returns = self._calculate_log_returns(closes, lookback)
            features.extend(log_returns)
            
        if self.feature_config.include_price_ratios:
            # Price ratios and spreads
            price_ratios = self._calculate_price_ratios(opens, highs, lows, closes)
            features.extend(price_ratios)
            
        return features
        
    def _extract_technical_features(self, market_data: List[MarketData]) -> List[float]:
        """Extract technical indicator features."""
        features = []
        
        # Extract price and volume arrays
        opens = [d.open for d in market_data]
        highs = [d.high for d in market_data]
        lows = [d.low for d in market_data]
        closes = [d.close for d in market_data]
        volumes = [d.volume for d in market_data]
        
        # Calculate all technical indicators
        indicators = self.tech_indicators.calculate_all_indicators(
            opens, highs, lows, closes, volumes
        )
        
        # Normalize and select indicators based on configuration
        if self.feature_config.include_trend_indicators:
            trend_features = self._extract_trend_features(indicators, closes[-1] if closes else 1.0)
            features.extend(trend_features)
            
        if self.feature_config.include_momentum_indicators:
            momentum_features = self._extract_momentum_features(indicators)
            features.extend(momentum_features)
            
        if self.feature_config.include_volatility_indicators:
            volatility_features = self._extract_volatility_features(indicators)
            features.extend(volatility_features)
            
        if self.feature_config.include_volume_indicators:
            volume_features = self._extract_volume_features(indicators)
            features.extend(volume_features)
            
        if self.feature_config.include_support_resistance:
            sr_features = self._extract_support_resistance_features(indicators, closes[-1] if closes else 1.0)
            features.extend(sr_features)
            
        return features
        
    def _extract_microstructure_features(self, market_data: List[MarketData]) -> List[float]:
        """Extract market microstructure features."""
        features = []
        
        if not market_data:
            return [0.0] * 8  # Default microstructure features
            
        current_data = market_data[-1]
        
        # Bid-ask spread features
        spread_abs = current_data.spread
        spread_rel = spread_abs / current_data.close if current_data.close > 0 else 0.0
        features.extend([spread_abs * 10000, spread_rel * 10000])  # In pips
        
        # Mid-price vs close price
        mid_price = (current_data.bid + current_data.ask) / 2
        mid_close_diff = (mid_price - current_data.close) / current_data.close if current_data.close > 0 else 0.0
        features.append(mid_close_diff * 10000)
        
        # Intrabar price dynamics
        if len(market_data) >= 2:
            prev_data = market_data[-2]
            
            # Price gap
            gap = (current_data.open - prev_data.close) / prev_data.close if prev_data.close > 0 else 0.0
            features.append(gap * 10000)
            
            # Intrabar range
            intrabar_range = (current_data.high - current_data.low) / current_data.close if current_data.close > 0 else 0.0
            features.append(intrabar_range * 10000)
            
            # Volume-weighted features
            volume_change = (current_data.volume - prev_data.volume) / prev_data.volume if prev_data.volume > 0 else 0.0
            features.append(np.clip(volume_change, -2.0, 2.0))
            
        else:
            features.extend([0.0, 0.0, 0.0])
            
        # Order flow approximation (simplified)
        body_size = abs(current_data.close - current_data.open) / current_data.close if current_data.close > 0 else 0.0
        upper_shadow = (current_data.high - max(current_data.open, current_data.close)) / current_data.close if current_data.close > 0 else 0.0
        lower_shadow = (min(current_data.open, current_data.close) - current_data.low) / current_data.close if current_data.close > 0 else 0.0
        
        features.extend([body_size * 10000, upper_shadow * 10000, lower_shadow * 10000])
        
        return features
        
    def _extract_regime_features(self, market_data: List[MarketData]) -> List[float]:
        """Extract market regime features."""
        features = []
        
        if len(market_data) < 10:
            return [0.0] * 6  # Default regime features
            
        closes = [d.close for d in market_data]
        
        # Volatility regime
        returns = np.diff(closes) / closes[:-1]
        current_vol = np.std(returns[-10:]) if len(returns) >= 10 else 0.0
        long_term_vol = np.std(returns[-30:]) if len(returns) >= 30 else current_vol
        vol_regime = (current_vol - long_term_vol) / long_term_vol if long_term_vol > 0 else 0.0
        features.append(np.clip(vol_regime, -2.0, 2.0))
        
        # Trend regime
        short_ma = np.mean(closes[-5:])
        long_ma = np.mean(closes[-20:]) if len(closes) >= 20 else short_ma
        trend_strength = (short_ma - long_ma) / long_ma if long_ma > 0 else 0.0
        features.append(np.clip(trend_strength * 100, -2.0, 2.0))
        
        # Mean reversion tendency
        current_price = closes[-1]
        mean_price = np.mean(closes[-20:]) if len(closes) >= 20 else current_price
        mean_reversion = (current_price - mean_price) / mean_price if mean_price > 0 else 0.0
        features.append(np.clip(mean_reversion * 100, -2.0, 2.0))
        
        # Momentum regime
        momentum_5 = (closes[-1] - closes[-6]) / closes[-6] if len(closes) >= 6 and closes[-6] > 0 else 0.0
        momentum_10 = (closes[-1] - closes[-11]) / closes[-11] if len(closes) >= 11 and closes[-11] > 0 else 0.0
        momentum_ratio = momentum_5 / momentum_10 if abs(momentum_10) > 1e-8 else 1.0
        features.append(np.clip(momentum_ratio, -2.0, 2.0))
        
        # Autocorrelation (simplified)
        if len(returns) >= 10:
            autocorr = np.corrcoef(returns[-10:-1], returns[-9:])[0, 1]
            autocorr = autocorr if not np.isnan(autocorr) else 0.0
        else:
            autocorr = 0.0
        features.append(autocorr)
        
        # Market session indicator (simplified)
        current_hour = market_data[-1].timestamp.hour
        session_indicator = self._get_session_indicator(current_hour)
        features.append(session_indicator)
        
        return features
        
    def _extract_portfolio_features(self, portfolio_state: PortfolioState) -> List[float]:
        """Extract enhanced portfolio features."""
        features = []
        
        # Basic portfolio features
        features.append(portfolio_state.current_position)  # Already normalized [-1, 1]
        
        # P&L features
        pnl_ratio = portfolio_state.unrealized_pnl / max(portfolio_state.balance, 1.0)
        features.append(np.clip(pnl_ratio, -1.0, 1.0))
        
        realized_pnl_ratio = portfolio_state.realized_pnl / self.env_config.initial_balance
        features.append(np.clip(realized_pnl_ratio, -1.0, 2.0))
        
        # Risk features
        features.append(-portfolio_state.current_drawdown)  # Negative because drawdown is bad
        features.append(-portfolio_state.max_drawdown)
        
        # Trading activity features
        win_rate = portfolio_state.winning_trades / max(portfolio_state.total_trades, 1)
        features.append(win_rate * 2 - 1)  # Normalize to [-1, 1]
        
        trade_frequency = min(portfolio_state.total_trades / 100.0, 1.0)
        features.append(trade_frequency)
        
        # Equity curve features
        equity_ratio = (portfolio_state.equity / self.env_config.initial_balance) - 1.0
        features.append(np.clip(equity_ratio, -1.0, 2.0))
        
        # Risk-adjusted performance (simplified Sharpe approximation)
        if portfolio_state.total_trades > 5:
            avg_return = realized_pnl_ratio / max(portfolio_state.total_trades, 1)
            risk_adjusted_perf = avg_return / max(portfolio_state.max_drawdown, 0.01)
            features.append(np.clip(risk_adjusted_perf, -2.0, 2.0))
        else:
            features.append(0.0)
            
        return features
        
    def _extract_temporal_features(self, market_data: MarketData) -> List[float]:
        """Extract enhanced temporal features."""
        timestamp = market_data.timestamp
        
        # Basic time features
        hour_norm = (timestamp.hour - 12) / 12.0
        day_norm = (timestamp.weekday() - 2.5) / 2.5
        day_month_norm = (timestamp.day - 15.5) / 15.5
        month_norm = (timestamp.month - 6.5) / 6.5
        
        # Market session features
        session_features = self._get_detailed_session_features(timestamp.hour)
        
        # Weekend/holiday proximity
        weekend_proximity = self._get_weekend_proximity(timestamp.weekday())
        
        return [hour_norm, day_norm, day_month_norm, month_norm] + session_features + [weekend_proximity]
        
    # Helper methods for feature extraction
    
    def _calculate_returns(self, prices: List[float], lookback: int) -> List[float]:
        """Calculate simple returns."""
        if len(prices) < 2:
            return [0.0] * lookback
            
        returns = []
        for i in range(1, min(lookback + 1, len(prices))):
            if prices[-i-1] > 0:
                ret = (prices[-i] - prices[-i-1]) / prices[-i-1]
                returns.append(ret * 100)  # Scale for better numerical properties
            else:
                returns.append(0.0)
                
        # Pad if necessary
        while len(returns) < lookback:
            returns.append(0.0)
            
        return returns
        
    def _calculate_log_returns(self, prices: List[float], lookback: int) -> List[float]:
        """Calculate log returns."""
        if len(prices) < 2:
            return [0.0] * lookback
            
        log_returns = []
        for i in range(1, min(lookback + 1, len(prices))):
            if prices[-i-1] > 0 and prices[-i] > 0:
                log_ret = np.log(prices[-i] / prices[-i-1])
                log_returns.append(log_ret * 100)  # Scale for better numerical properties
            else:
                log_returns.append(0.0)
                
        # Pad if necessary
        while len(log_returns) < lookback:
            log_returns.append(0.0)
            
        return log_returns
        
    def _calculate_price_ratios(self, opens: List[float], highs: List[float], 
                              lows: List[float], closes: List[float]) -> List[float]:
        """Calculate price ratios and spreads."""
        if not closes:
            return [0.0] * 6
            
        current_close = closes[-1]
        current_open = opens[-1] if opens else current_close
        current_high = highs[-1] if highs else current_close
        current_low = lows[-1] if lows else current_close
        
        features = []
        
        # OHLC ratios
        if current_close > 0:
            features.append((current_open - current_close) / current_close * 100)
            features.append((current_high - current_close) / current_close * 100)
            features.append((current_low - current_close) / current_close * 100)
            features.append((current_high - current_low) / current_close * 100)
        else:
            features.extend([0.0, 0.0, 0.0, 0.0])
            
        # Body and shadow ratios
        body_size = abs(current_close - current_open)
        total_range = current_high - current_low
        
        if total_range > 0:
            body_ratio = body_size / total_range
            upper_shadow_ratio = (current_high - max(current_open, current_close)) / total_range
            lower_shadow_ratio = (min(current_open, current_close) - current_low) / total_range
        else:
            body_ratio = upper_shadow_ratio = lower_shadow_ratio = 0.0
            
        features.extend([body_ratio, upper_shadow_ratio])
        
        return features
        
    def _extract_trend_features(self, indicators: Dict[str, float], current_price: float) -> List[float]:
        """Extract normalized trend indicator features."""
        features = []
        
        # Moving average ratios
        if current_price > 0:
            sma_ratios = [
                (indicators['sma_5'] - current_price) / current_price * 100 if indicators['sma_5'] > 0 else 0.0,
                (indicators['sma_10'] - current_price) / current_price * 100 if indicators['sma_10'] > 0 else 0.0,
                (indicators['sma_20'] - current_price) / current_price * 100 if indicators['sma_20'] > 0 else 0.0,
                (indicators['ema_10'] - current_price) / current_price * 100 if indicators['ema_10'] > 0 else 0.0
            ]
            features.extend([np.clip(ratio, -5.0, 5.0) for ratio in sma_ratios])
        else:
            features.extend([0.0, 0.0, 0.0, 0.0])
            
        # MACD features (already in good scale)
        features.extend([
            np.clip(indicators['macd_line'] * 10000, -2.0, 2.0),
            np.clip(indicators['macd_signal'] * 10000, -2.0, 2.0),
            np.clip(indicators['macd_histogram'] * 10000, -2.0, 2.0)
        ])
        
        # ADX (already 0-100)
        features.append(indicators['adx'] / 50.0 - 1.0)  # Normalize to [-1, 1]
        
        return features
        
    def _extract_momentum_features(self, indicators: Dict[str, float]) -> List[float]:
        """Extract normalized momentum indicator features."""
        features = []
        
        # RSI (normalize from 0-100 to -1,1)
        features.append((indicators['rsi'] - 50) / 50.0)
        
        # Stochastic (normalize from 0-100 to -1,1)
        features.extend([
            (indicators['stoch_k'] - 50) / 50.0,
            (indicators['stoch_d'] - 50) / 50.0
        ])
        
        # Williams %R (already -100 to 0, normalize to -1,1)
        features.append(indicators['williams_r'] / 50.0)
        
        # CCI (clip to reasonable range)
        features.append(np.clip(indicators['cci'] / 100.0, -2.0, 2.0))
        
        # ROC and Momentum (clip to reasonable range)
        features.extend([
            np.clip(indicators['roc'] / 5.0, -2.0, 2.0),
            np.clip(indicators['momentum'] * 10000, -2.0, 2.0)
        ])
        
        return features
        
    def _extract_volatility_features(self, indicators: Dict[str, float]) -> List[float]:
        """Extract normalized volatility indicator features."""
        features = []
        
        # Bollinger Band position (already 0-1)
        features.append(indicators['bb_position'] * 2 - 1)  # Convert to [-1, 1]
        
        # Bollinger Band width (normalize)
        features.append(np.clip(indicators['bb_width'] * 100, 0.0, 2.0) - 1.0)
        
        # ATR (normalize by current price approximation)
        features.append(np.clip(indicators['atr'] * 10000, 0.0, 2.0) - 1.0)
        
        # Historical volatility (already annualized)
        features.append(np.clip(indicators['volatility'], 0.0, 2.0) - 1.0)
        
        return features
        
    def _extract_volume_features(self, indicators: Dict[str, float]) -> List[float]:
        """Extract normalized volume indicator features."""
        features = []
        
        # Volume ratio (clip to reasonable range)
        features.append(np.clip(indicators['volume_ratio'] - 1.0, -2.0, 2.0))
        
        # OBV (normalize by scaling)
        features.append(np.clip(indicators['obv'] / 1000000, -2.0, 2.0))
        
        return features
        
    def _extract_support_resistance_features(self, indicators: Dict[str, float], current_price: float) -> List[float]:
        """Extract normalized support/resistance features."""
        features = []
        
        if current_price > 0:
            # Pivot point distances (normalize by current price)
            pivot_distances = [
                (indicators['pivot'] - current_price) / current_price * 100 if indicators['pivot'] > 0 else 0.0,
                (indicators['r1'] - current_price) / current_price * 100 if indicators['r1'] > 0 else 0.0,
                (indicators['s1'] - current_price) / current_price * 100 if indicators['s1'] > 0 else 0.0
            ]
            features.extend([np.clip(dist, -5.0, 5.0) for dist in pivot_distances])
        else:
            features.extend([0.0, 0.0, 0.0])
            
        # Price position in range (already 0-1)
        features.append(indicators['price_position'] * 2 - 1)  # Convert to [-1, 1]
        
        return features
        
    def _get_session_indicator(self, hour: int) -> float:
        """Get market session indicator."""
        # Simplified session mapping (UTC hours)
        if 0 <= hour < 6:  # Asian session
            return -1.0
        elif 6 <= hour < 14:  # European session
            return 0.0
        else:  # American session
            return 1.0
            
    def _get_detailed_session_features(self, hour: int) -> List[float]:
        """Get detailed market session features."""
        # One-hot encoding for sessions
        asian = 1.0 if 0 <= hour < 6 else 0.0
        european = 1.0 if 6 <= hour < 14 else 0.0
        american = 1.0 if 14 <= hour < 22 else 0.0
        overlap = 1.0 if hour in [6, 7, 13, 14] else 0.0  # Session overlaps
        
        return [asian, european, american, overlap]
        
    def _get_weekend_proximity(self, weekday: int) -> float:
        """Get weekend proximity feature."""
        # 0 = Monday, 6 = Sunday
        if weekday == 4:  # Friday
            return 1.0
        elif weekday == 0:  # Monday
            return -1.0
        else:
            return 0.0
            
    def _ensure_sufficient_data(self, market_data: List[MarketData]) -> List[MarketData]:
        """Ensure sufficient data for feature extraction."""
        required_length = max(
            self.env_config.lookback_window,
            self.feature_config.price_lookback,
            self.feature_config.technical_lookback
        )
        
        if len(market_data) < required_length:
            # Pad with first available data point
            if market_data:
                padding = [market_data[0]] * (required_length - len(market_data))
                return padding + market_data
            else:
                return market_data
        elif len(market_data) > required_length:
            # Take the most recent data
            return market_data[-required_length:]
        else:
            return market_data
            
    def _handle_invalid_values(self, feature_vector: np.ndarray) -> np.ndarray:
        """Handle NaN and infinite values in feature vector."""
        # Replace NaN with 0
        feature_vector = np.nan_to_num(feature_vector, nan=0.0, posinf=2.0, neginf=-2.0)
        
        # Clip extreme values
        feature_vector = np.clip(feature_vector, -10.0, 10.0)
        
        return feature_vector
        
    def _normalize_features(self, feature_vector: np.ndarray) -> np.ndarray:
        """Apply normalization to feature vector."""
        if self.feature_config.normalization_method == NormalizationMethod.NONE:
            return feature_vector
            
        # Update normalization statistics
        self._update_normalization_stats(feature_vector)
        
        # Apply normalization
        if self.feature_config.normalization_method == NormalizationMethod.MINMAX:
            return self._minmax_normalize(feature_vector)
        elif self.feature_config.normalization_method == NormalizationMethod.ZSCORE:
            return self._zscore_normalize(feature_vector)
        elif self.feature_config.normalization_method == NormalizationMethod.ROBUST:
            return self._robust_normalize(feature_vector)
        elif self.feature_config.normalization_method == NormalizationMethod.QUANTILE:
            return self._quantile_normalize(feature_vector)
        else:
            return feature_vector
            
    def _update_normalization_stats(self, feature_vector: np.ndarray) -> None:
        """Update running statistics for normalization."""
        if 'history' not in self.normalization_history:
            self.normalization_history['history'] = []
            
        self.normalization_history['history'].append(feature_vector.copy())
        
        # Keep only recent history
        max_history = self.feature_config.normalization_window
        if len(self.normalization_history['history']) > max_history:
            self.normalization_history['history'] = self.normalization_history['history'][-max_history:]
            
    def _minmax_normalize(self, feature_vector: np.ndarray) -> np.ndarray:
        """Min-max normalization."""
        if 'history' not in self.normalization_history or len(self.normalization_history['history']) < 2:
            return feature_vector
            
        history = np.array(self.normalization_history['history'])
        min_vals = np.min(history, axis=0)
        max_vals = np.max(history, axis=0)
        
        # Avoid division by zero
        ranges = max_vals - min_vals
        ranges = np.where(ranges == 0, 1.0, ranges)
        
        normalized = (feature_vector - min_vals) / ranges
        return np.clip(normalized, -2.0, 2.0)
        
    def _zscore_normalize(self, feature_vector: np.ndarray) -> np.ndarray:
        """Z-score normalization."""
        if 'history' not in self.normalization_history or len(self.normalization_history['history']) < 2:
            return feature_vector
            
        history = np.array(self.normalization_history['history'])
        means = np.mean(history, axis=0)
        stds = np.std(history, axis=0)
        
        # Avoid division by zero
        stds = np.where(stds == 0, 1.0, stds)
        
        normalized = (feature_vector - means) / stds
        return np.clip(normalized, -3.0, 3.0)
        
    def _robust_normalize(self, feature_vector: np.ndarray) -> np.ndarray:
        """Robust normalization using median and IQR."""
        if 'history' not in self.normalization_history or len(self.normalization_history['history']) < 2:
            return feature_vector
            
        history = np.array(self.normalization_history['history'])
        medians = np.median(history, axis=0)
        q75 = np.percentile(history, 75, axis=0)
        q25 = np.percentile(history, 25, axis=0)
        
        iqr = q75 - q25
        iqr = np.where(iqr == 0, 1.0, iqr)
        
        normalized = (feature_vector - medians) / iqr
        return np.clip(normalized, -3.0, 3.0)
        
    def _quantile_normalize(self, feature_vector: np.ndarray) -> np.ndarray:
        """Quantile normalization."""
        if 'history' not in self.normalization_history or len(self.normalization_history['history']) < 10:
            return feature_vector
            
        history = np.array(self.normalization_history['history'])
        
        # Calculate quantiles for each feature
        normalized = np.zeros_like(feature_vector)
        for i in range(len(feature_vector)):
            if i < history.shape[1]:
                # Calculate percentile rank
                percentile = (np.sum(history[:, i] <= feature_vector[i]) / len(history)) * 100
                # Convert to [-1, 1] range
                normalized[i] = (percentile - 50) / 50
            else:
                normalized[i] = 0.0
                
        return np.clip(normalized, -1.0, 1.0)
        
    def _select_features(self, feature_vector: np.ndarray) -> np.ndarray:
        """Apply feature selection if configured."""
        # For now, just return the first max_features
        # In practice, you'd implement proper feature selection algorithms
        max_features = self.feature_config.max_features
        if max_features and len(feature_vector) > max_features:
            return feature_vector[:max_features]
        return feature_vector
        
    def _calculate_feature_dimension(self) -> int:
        """Calculate total feature dimension based on configuration."""
        dim = 0
        
        # Price features
        if self.feature_config.include_ohlc:
            dim += 4 * self.feature_config.price_lookback
        if self.feature_config.include_returns:
            dim += self.feature_config.price_lookback
        if self.feature_config.include_log_returns:
            dim += self.feature_config.price_lookback
        if self.feature_config.include_price_ratios:
            dim += 6
            
        # Technical indicator features
        if self.feature_config.include_trend_indicators:
            dim += 8  # MA ratios + MACD + ADX
        if self.feature_config.include_momentum_indicators:
            dim += 7  # RSI + Stoch + Williams + CCI + ROC + Momentum
        if self.feature_config.include_volatility_indicators:
            dim += 4  # BB features + ATR + Volatility
        if self.feature_config.include_volume_indicators:
            dim += 2  # Volume ratio + OBV
        if self.feature_config.include_support_resistance:
            dim += 4  # Pivot distances + price position
            
        # Other features
        if self.feature_config.include_market_microstructure:
            dim += 8
        if self.feature_config.include_regime_features:
            dim += 6
            
        # Portfolio features (always included)
        dim += 8
        
        # Temporal features (always included)
        dim += 9  # Basic time + session features + weekend proximity
        
        return dim
        
    def _generate_feature_names(self) -> List[str]:
        """Generate feature names for debugging and analysis."""
        names = []
        
        # Price features
        if self.feature_config.include_ohlc:
            for i in range(self.feature_config.price_lookback):
                names.extend([f'open_{i}', f'high_{i}', f'low_{i}', f'close_{i}'])
        if self.feature_config.include_returns:
            for i in range(self.feature_config.price_lookback):
                names.append(f'return_{i}')
        if self.feature_config.include_log_returns:
            for i in range(self.feature_config.price_lookback):
                names.append(f'log_return_{i}')
        if self.feature_config.include_price_ratios:
            names.extend(['open_close_ratio', 'high_close_ratio', 'low_close_ratio', 
                         'hl_range_ratio', 'body_ratio', 'upper_shadow_ratio'])
            
        # Technical indicators
        if self.feature_config.include_trend_indicators:
            names.extend(['sma5_ratio', 'sma10_ratio', 'sma20_ratio', 'ema10_ratio',
                         'macd_line', 'macd_signal', 'macd_histogram', 'adx'])
        if self.feature_config.include_momentum_indicators:
            names.extend(['rsi', 'stoch_k', 'stoch_d', 'williams_r', 'cci', 'roc', 'momentum'])
        if self.feature_config.include_volatility_indicators:
            names.extend(['bb_position', 'bb_width', 'atr', 'volatility'])
        if self.feature_config.include_volume_indicators:
            names.extend(['volume_ratio', 'obv'])
        if self.feature_config.include_support_resistance:
            names.extend(['pivot_distance', 'r1_distance', 's1_distance', 'price_position'])
            
        # Other features
        if self.feature_config.include_market_microstructure:
            names.extend(['spread_abs', 'spread_rel', 'mid_close_diff', 'price_gap',
                         'intrabar_range', 'volume_change', 'body_size', 'upper_shadow', 'lower_shadow'])
        if self.feature_config.include_regime_features:
            names.extend(['vol_regime', 'trend_regime', 'mean_reversion', 'momentum_regime',
                         'autocorr', 'session_indicator'])
            
        # Portfolio features
        names.extend(['position', 'unrealized_pnl_ratio', 'realized_pnl_ratio', 'current_drawdown',
                     'max_drawdown', 'win_rate', 'trade_frequency', 'equity_ratio'])
        
        # Temporal features
        names.extend(['hour', 'day', 'day_month', 'month', 'asian_session', 'european_session',
                     'american_session', 'session_overlap', 'weekend_proximity'])
        
        return names
        
    def reset_normalization_stats(self) -> None:
        """Reset normalization statistics for new training."""
        self.normalization_history = {}
        self.feature_stats = {}