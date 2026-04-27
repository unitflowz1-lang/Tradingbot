"""
Multi-Pair State Processor for RL Trading Environment

This module contains the state processor for multi-currency pair environments,
including cross-pair correlation features and currency-specific normalization.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
import numpy as np
from datetime import datetime
import logging

from ...models import MarketData
from .base import PortfolioState
from .state_processor import StateProcessor
from .multi_pair_environment import MultiPairEnvironmentConfig, MultiPairPortfolioState


logger = logging.getLogger(__name__)


class MultiPairStateProcessor(StateProcessor):
    """
    State processor for multi-currency pair environments.
    
    Handles cross-pair correlations, currency-specific normalization,
    and feature engineering for multiple currency pairs simultaneously.
    """
    
    def __init__(self, config: MultiPairEnvironmentConfig):
        self.config = config
        self.currency_pairs = config.currency_pairs
        self.lookback_window = config.lookback_window
        self.enable_cross_pair_features = config.enable_cross_pair_features
        
        # Define feature dimensions per pair
        self.price_features_per_pair = 4  # OHLC normalized
        self.technical_features_per_pair = 8  # Technical indicators
        self.pair_specific_features = 3  # Pair weight, volatility, position
        
        # Cross-pair features
        self.correlation_features = len(self.currency_pairs) * (len(self.currency_pairs) - 1) // 2
        self.portfolio_features = 8  # Multi-pair portfolio metrics
        self.temporal_features = 4  # Time-based features
        
        # Calculate total dimensions
        self.per_pair_dim = (
            self.price_features_per_pair * self.lookback_window +
            self.technical_features_per_pair +
            self.pair_specific_features
        )
        
        self.cross_pair_dim = (
            self.correlation_features +
            self.portfolio_features +
            self.temporal_features
        ) if self.enable_cross_pair_features else 0
        
        self.total_dim = (
            self.per_pair_dim * len(self.currency_pairs) +
            self.cross_pair_dim
        )
        
        # Currency-specific normalization parameters
        self.pair_normalizers = self._initialize_pair_normalizers()
        
        logger.info(f"Initialized multi-pair state processor for {len(self.currency_pairs)} pairs")
        logger.info(f"Total state dimension: {self.total_dim}")
        
    def process_market_data(self, 
                          market_data: Dict[str, List[MarketData]], 
                          portfolio_state: MultiPairPortfolioState,
                          correlation_matrix: Optional[np.ndarray] = None,
                          pair_volatilities: Optional[Dict[str, float]] = None) -> np.ndarray:
        """
        Convert multi-pair market data into normalized state vector.
        
        Args:
            market_data: Dictionary mapping pairs to market data lists
            portfolio_state: Current multi-pair portfolio state
            correlation_matrix: Cross-pair correlation matrix
            pair_volatilities: Volatility estimates for each pair
            
        Returns:
            Normalized state vector
        """
        if not market_data:
            return np.zeros(self.total_dim)
            
        features = []
        
        # Process each currency pair
        for pair in self.currency_pairs:
            if pair in market_data and market_data[pair]:
                pair_features = self._process_pair_data(
                    pair, market_data[pair], portfolio_state, pair_volatilities
                )
            else:
                # Use zero features if pair data is missing
                pair_features = np.zeros(self.per_pair_dim)
                
            features.extend(pair_features)
            
        # Add cross-pair features if enabled
        if self.enable_cross_pair_features:
            cross_pair_features = self._extract_cross_pair_features(
                market_data, portfolio_state, correlation_matrix, pair_volatilities
            )
            features.extend(cross_pair_features)
            
        return np.array(features, dtype=np.float32)
        
    def get_state_dimension(self) -> int:
        """Return the dimension of the multi-pair state space."""
        return self.total_dim
        
    def _process_pair_data(self, 
                          pair: str,
                          pair_market_data: List[MarketData],
                          portfolio_state: MultiPairPortfolioState,
                          pair_volatilities: Optional[Dict[str, float]] = None) -> List[float]:
        """Process data for a single currency pair."""
        # Ensure we have enough data
        if len(pair_market_data) < self.lookback_window:
            # Pad with first available data point
            padded_data = ([pair_market_data[0]] * (self.lookback_window - len(pair_market_data)) + 
                          pair_market_data)
            pair_market_data = padded_data
        elif len(pair_market_data) > self.lookback_window:
            # Take the most recent data
            pair_market_data = pair_market_data[-self.lookback_window:]
            
        features = []
        
        # 1. Currency-specific price features
        price_features = self._extract_currency_specific_price_features(pair, pair_market_data)
        features.extend(price_features)
        
        # 2. Currency-specific technical indicators
        technical_features = self._extract_currency_specific_technical_features(pair, pair_market_data)
        features.extend(technical_features)
        
        # 3. Pair-specific features
        pair_specific_features = self._extract_pair_specific_features(
            pair, portfolio_state, pair_volatilities
        )
        features.extend(pair_specific_features)
        
        return features
        
    def _extract_currency_specific_price_features(self, 
                                                pair: str, 
                                                market_data: List[MarketData]) -> List[float]:
        """Extract currency-specific normalized price features."""
        features = []
        
        # Get price series
        opens = [d.open for d in market_data]
        highs = [d.high for d in market_data]
        lows = [d.low for d in market_data]
        closes = [d.close for d in market_data]
        
        # Get currency-specific normalizer
        normalizer = self.pair_normalizers[pair]
        
        # Use adaptive normalization based on recent price range
        recent_prices = closes[-min(20, len(closes)):]  # Last 20 periods or available
        price_range = max(recent_prices) - min(recent_prices)
        base_price = np.mean(recent_prices)
        
        if price_range == 0 or base_price == 0:
            # Fallback to simple normalization
            base_price = closes[0] if closes else 1.0
            price_range = base_price * 0.01  # 1% range
            
        for i in range(len(market_data)):
            # Normalize OHLC relative to adaptive base and range
            norm_open = (opens[i] - base_price) / price_range
            norm_high = (highs[i] - base_price) / price_range
            norm_low = (lows[i] - base_price) / price_range
            norm_close = (closes[i] - base_price) / price_range
            
            # Apply currency-specific scaling
            norm_open *= normalizer['price_scale']
            norm_high *= normalizer['price_scale']
            norm_low *= normalizer['price_scale']
            norm_close *= normalizer['price_scale']
            
            # Clip to reasonable range
            features.extend([
                np.clip(norm_open, -5.0, 5.0),
                np.clip(norm_high, -5.0, 5.0),
                np.clip(norm_low, -5.0, 5.0),
                np.clip(norm_close, -5.0, 5.0)
            ])
            
        return features
        
    def _extract_currency_specific_technical_features(self, 
                                                    pair: str, 
                                                    market_data: List[MarketData]) -> List[float]:
        """Extract currency-specific technical indicator features."""
        if len(market_data) < 2:
            return [0.0] * self.technical_features_per_pair
            
        closes = [d.close for d in market_data]
        highs = [d.high for d in market_data]
        lows = [d.low for d in market_data]
        volumes = [d.volume for d in market_data]
        
        normalizer = self.pair_normalizers[pair]
        features = []
        
        # 1. Currency-specific SMA ratio
        sma_ratio = self._calculate_sma_ratio(closes)
        features.append(sma_ratio * normalizer['momentum_scale'])
        
        # 2. Currency-specific RSI
        rsi = self._calculate_rsi(closes)
        features.append((rsi - 50) / 50)  # Normalize to [-1, 1]
        
        # 3. Currency-specific momentum
        momentum = self._calculate_momentum(closes, periods=5)
        features.append(momentum * normalizer['momentum_scale'])
        
        # 4. Currency-specific volatility
        volatility = self._calculate_volatility(closes)
        features.append(volatility * normalizer['volatility_scale'])
        
        # 5. Currency-specific volume ratio
        volume_ratio = self._calculate_volume_ratio(volumes)
        features.append(volume_ratio * normalizer['volume_scale'])
        
        # 6. Currency-specific spread analysis
        spread_features = self._calculate_currency_spread_features(pair, market_data)
        features.extend(spread_features)
        
        # 7. Currency-specific trend strength
        trend_strength = self._calculate_trend_strength(closes)
        features.append(trend_strength * normalizer['trend_scale'])
        
        # Pad to required dimension if needed
        while len(features) < self.technical_features_per_pair:
            features.append(0.0)
            
        return features[:self.technical_features_per_pair]
        
    def _extract_pair_specific_features(self, 
                                      pair: str,
                                      portfolio_state: MultiPairPortfolioState,
                                      pair_volatilities: Optional[Dict[str, float]] = None) -> List[float]:
        """Extract pair-specific portfolio and market features."""
        features = []
        
        # 1. Pair weight in portfolio
        pair_weight = self.config.pair_weights.get(pair, 0.0)
        features.append(pair_weight)
        
        # 2. Pair volatility (normalized)
        if pair_volatilities and pair in pair_volatilities:
            volatility = pair_volatilities[pair]
            # Normalize volatility (typical forex volatility 0.05-0.25)
            norm_volatility = min(volatility / 0.25, 2.0)
        else:
            norm_volatility = 0.0
        features.append(norm_volatility)
        
        # 3. Pair position
        pair_position = portfolio_state.pair_positions.get(pair, 0.0)
        features.append(pair_position)  # Already normalized to [-1, 1]
        
        return features
        
    def _extract_cross_pair_features(self, 
                                   market_data: Dict[str, List[MarketData]],
                                   portfolio_state: MultiPairPortfolioState,
                                   correlation_matrix: Optional[np.ndarray] = None,
                                   pair_volatilities: Optional[Dict[str, float]] = None) -> List[float]:
        """Extract cross-pair correlation and portfolio features."""
        features = []
        
        # 1. Correlation features
        if correlation_matrix is not None and correlation_matrix.shape[0] == len(self.currency_pairs):
            # Extract upper triangular correlation values
            for i in range(len(self.currency_pairs)):
                for j in range(i + 1, len(self.currency_pairs)):
                    corr_value = correlation_matrix[i, j]
                    if np.isnan(corr_value):
                        corr_value = 0.0
                    features.append(np.clip(corr_value, -1.0, 1.0))
        else:
            # Use zero correlations if matrix not available
            features.extend([0.0] * self.correlation_features)
            
        # 2. Portfolio diversification features
        diversification_score = portfolio_state.get_diversification_score()
        total_exposure = portfolio_state.get_total_position_exposure()
        
        # Normalize total exposure
        max_exposure = self.config.max_position_size * len(self.currency_pairs)
        norm_exposure = total_exposure / max_exposure if max_exposure > 0 else 0.0
        
        features.extend([
            diversification_score,
            norm_exposure,
            portfolio_state.current_position,  # Overall weighted position
            portfolio_state.current_drawdown,
            portfolio_state.winning_trades / max(1, portfolio_state.total_trades),  # Win rate
            min(portfolio_state.total_trades / 100.0, 1.0),  # Trade frequency
        ])
        
        # 3. Cross-pair momentum and volatility features
        if len(market_data) >= 2:
            cross_momentum = self._calculate_cross_pair_momentum(market_data)
            volatility_dispersion = self._calculate_volatility_dispersion(pair_volatilities)
        else:
            cross_momentum = 0.0
            volatility_dispersion = 0.0
            
        features.extend([cross_momentum, volatility_dispersion])
        
        # 4. Temporal features (based on first available market data)
        temporal_features = self._extract_temporal_features(market_data)
        features.extend(temporal_features)
        
        return features
        
    def _calculate_currency_spread_features(self, pair: str, market_data: List[MarketData]) -> List[float]:
        """Calculate currency-specific spread features."""
        if not market_data:
            return [0.0, 0.0]
            
        # Current spread
        current_data = market_data[-1]
        current_spread = current_data.spread
        
        # Average spread over lookback
        spreads = [d.spread for d in market_data]
        avg_spread = np.mean(spreads)
        
        # Normalize spreads (typical forex spreads: 0.5-5 pips)
        normalizer = self.pair_normalizers[pair]
        norm_current_spread = current_spread * normalizer['spread_scale']
        norm_avg_spread = avg_spread * normalizer['spread_scale']
        
        return [
            min(norm_current_spread, 2.0),  # Cap at 2.0
            min(norm_avg_spread, 2.0)
        ]
        
    def _calculate_cross_pair_momentum(self, market_data: Dict[str, List[MarketData]]) -> float:
        """Calculate cross-pair momentum correlation."""
        try:
            pair_momentums = {}
            
            for pair, data in market_data.items():
                if len(data) >= 6:  # Need at least 6 points for 5-period momentum
                    closes = [d.close for d in data]
                    momentum = self._calculate_momentum(closes, periods=5)
                    pair_momentums[pair] = momentum
                    
            if len(pair_momentums) < 2:
                return 0.0
                
            # Calculate average momentum
            momentums = list(pair_momentums.values())
            avg_momentum = np.mean(momentums)
            
            # Calculate momentum dispersion
            momentum_std = np.std(momentums)
            
            # Return normalized momentum signal
            return np.clip(avg_momentum, -1.0, 1.0)
            
        except Exception as e:
            logger.warning(f"Error calculating cross-pair momentum: {e}")
            return 0.0
            
    def _calculate_volatility_dispersion(self, pair_volatilities: Optional[Dict[str, float]]) -> float:
        """Calculate volatility dispersion across pairs."""
        if not pair_volatilities or len(pair_volatilities) < 2:
            return 0.0
            
        try:
            volatilities = list(pair_volatilities.values())
            if not volatilities:
                return 0.0
                
            # Calculate coefficient of variation
            mean_vol = np.mean(volatilities)
            std_vol = np.std(volatilities)
            
            if mean_vol == 0:
                return 0.0
                
            cv = std_vol / mean_vol
            return min(cv, 2.0)  # Cap at 2.0
            
        except Exception as e:
            logger.warning(f"Error calculating volatility dispersion: {e}")
            return 0.0
            
    def _extract_temporal_features(self, market_data: Dict[str, List[MarketData]]) -> List[float]:
        """Extract temporal features from market data."""
        # Use first available market data for timestamp
        timestamp = None
        for pair_data in market_data.values():
            if pair_data:
                timestamp = pair_data[-1].timestamp
                break
                
        if timestamp is None:
            return [0.0] * self.temporal_features
            
        # Hour of day (normalized to [-1, 1])
        hour_norm = (timestamp.hour - 12) / 12.0
        
        # Day of week (normalized to [-1, 1])
        day_norm = (timestamp.weekday() - 2.5) / 2.5
        
        # Day of month (normalized to [-1, 1])
        day_month_norm = (timestamp.day - 15.5) / 15.5
        
        # Month of year (normalized to [-1, 1])
        month_norm = (timestamp.month - 6.5) / 6.5
        
        return [hour_norm, day_norm, day_month_norm, month_norm]
        
    def _initialize_pair_normalizers(self) -> Dict[str, Dict[str, float]]:
        """Initialize currency-specific normalization parameters."""
        normalizers = {}
        
        for pair in self.currency_pairs:
            # Get base and quote currencies
            base_currency, quote_currency = pair.split('/')
            
            # Currency-specific scaling factors
            normalizers[pair] = {
                'price_scale': self._get_currency_price_scale(base_currency, quote_currency),
                'momentum_scale': self._get_currency_momentum_scale(base_currency, quote_currency),
                'volatility_scale': self._get_currency_volatility_scale(base_currency, quote_currency),
                'volume_scale': self._get_currency_volume_scale(base_currency, quote_currency),
                'spread_scale': self._get_currency_spread_scale(base_currency, quote_currency),
                'trend_scale': self._get_currency_trend_scale(base_currency, quote_currency)
            }
            
        return normalizers
        
    def _get_currency_price_scale(self, base_currency: str, quote_currency: str) -> float:
        """Get price scaling factor for currency pair."""
        # Different currency pairs have different typical price ranges
        if quote_currency == 'JPY':
            return 0.01  # JPY pairs typically 100-150 range
        elif base_currency in ['GBP', 'EUR', 'AUD', 'NZD']:
            return 1.0   # Major pairs typically 1.0-2.0 range
        else:
            return 1.0   # Default scaling
            
    def _get_currency_momentum_scale(self, base_currency: str, quote_currency: str) -> float:
        """Get momentum scaling factor for currency pair."""
        # Some currencies are more volatile than others
        volatile_currencies = ['GBP', 'AUD', 'NZD', 'CAD']
        
        if base_currency in volatile_currencies or quote_currency in volatile_currencies:
            return 0.8  # Scale down for more volatile pairs
        else:
            return 1.0  # Standard scaling
            
    def _get_currency_volatility_scale(self, base_currency: str, quote_currency: str) -> float:
        """Get volatility scaling factor for currency pair."""
        # Emerging market currencies tend to be more volatile
        stable_currencies = ['USD', 'EUR', 'CHF']
        
        if base_currency in stable_currencies and quote_currency in stable_currencies:
            return 1.5  # Scale up for stable pairs
        else:
            return 1.0  # Standard scaling
            
    def _get_currency_volume_scale(self, base_currency: str, quote_currency: str) -> float:
        """Get volume scaling factor for currency pair."""
        # Major pairs have higher volume
        major_currencies = ['USD', 'EUR', 'GBP', 'JPY']
        
        if base_currency in major_currencies and quote_currency in major_currencies:
            return 0.5  # Scale down for high volume pairs
        else:
            return 1.0  # Standard scaling
            
    def _get_currency_spread_scale(self, base_currency: str, quote_currency: str) -> float:
        """Get spread scaling factor for currency pair."""
        # Major pairs typically have tighter spreads
        major_pairs = ['EUR/USD', 'GBP/USD', 'USD/JPY', 'USD/CHF']
        pair = f"{base_currency}/{quote_currency}"
        
        if pair in major_pairs:
            return 2.0  # Scale up for tight spreads
        else:
            return 1.0  # Standard scaling
            
    def _get_currency_trend_scale(self, base_currency: str, quote_currency: str) -> float:
        """Get trend scaling factor for currency pair."""
        # All pairs use standard trend scaling
        return 1.0
        
    # Technical indicator calculation methods (reused from base state processor)
    def _calculate_sma_ratio(self, prices: List[float]) -> float:
        """Calculate SMA ratio."""
        if len(prices) < 10:
            return 0.0
            
        sma5 = np.mean(prices[-5:])
        sma10 = np.mean(prices[-10:])
        
        if sma10 == 0:
            return 0.0
            
        return (sma5 - sma10) / sma10
        
    def _calculate_rsi(self, prices: List[float], periods: int = 14) -> float:
        """Calculate RSI."""
        if len(prices) < periods + 1:
            return 50.0
            
        deltas = np.diff(prices[-periods-1:])
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        
        avg_gain = np.mean(gains)
        avg_loss = np.mean(losses)
        
        if avg_loss == 0:
            return 100.0
            
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
        
    def _calculate_momentum(self, prices: List[float], periods: int = 5) -> float:
        """Calculate price momentum."""
        if len(prices) < periods + 1:
            return 0.0
            
        current_price = prices[-1]
        past_price = prices[-periods-1]
        
        if past_price == 0:
            return 0.0
            
        return (current_price - past_price) / past_price
        
    def _calculate_volatility(self, prices: List[float]) -> float:
        """Calculate normalized volatility."""
        if len(prices) < 2:
            return 0.0
            
        returns = np.diff(prices) / prices[:-1]
        volatility = np.std(returns)
        
        return min(volatility / 0.02, 1.0)
        
    def _calculate_volume_ratio(self, volumes: List[int]) -> float:
        """Calculate volume ratio."""
        if len(volumes) < 2:
            return 0.0
            
        current_volume = volumes[-1]
        avg_volume = np.mean(volumes[:-1])
        
        if avg_volume == 0:
            return 0.0
            
        ratio = current_volume / avg_volume
        return min(ratio, 3.0) - 1.0
        
    def _calculate_trend_strength(self, prices: List[float]) -> float:
        """Calculate trend strength."""
        if len(prices) < 3:
            return 0.0
            
        x = np.arange(len(prices))
        y = np.array(prices)
        
        if len(x) < 2:
            return 0.0
            
        slope = np.polyfit(x, y, 1)[0]
        
        avg_price = np.mean(prices)
        if avg_price == 0:
            return 0.0
            
        normalized_slope = slope / avg_price
        return np.clip(normalized_slope * 100, -1.0, 1.0)