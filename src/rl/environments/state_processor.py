"""
State Processor for RL Trading Environment

This module contains the StateProcessor class for converting
market data into normalized state vectors for RL agents.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List
import numpy as np
from datetime import datetime

from ...models import MarketData
from .base import PortfolioState, EnvironmentConfig


class StateProcessor(ABC):
    """Abstract base class for state processing."""
    
    @abstractmethod
    def process_market_data(self, market_data: List[MarketData], 
                          portfolio_state: PortfolioState) -> np.ndarray:
        """Convert raw market data into normalized state vector."""
        pass
        
    @abstractmethod
    def get_state_dimension(self) -> int:
        """Return the dimension of the state space."""
        pass


class DefaultStateProcessor(StateProcessor):
    """
    Default state processor implementation.
    
    Creates normalized state vectors from market data and portfolio information.
    """
    
    def __init__(self, config: EnvironmentConfig):
        self.config = config
        self.lookback_window = config.lookback_window
        
        # Define feature dimensions
        self.price_features_dim = 4  # OHLC normalized
        self.technical_features_dim = 8  # Technical indicators
        self.portfolio_features_dim = 6  # Portfolio state
        self.temporal_features_dim = 4  # Time-based features
        
        self.total_dim = (
            self.price_features_dim * self.lookback_window +
            self.technical_features_dim +
            self.portfolio_features_dim +
            self.temporal_features_dim
        )
        
    def process_market_data(self, market_data: List[MarketData], 
                          portfolio_state: PortfolioState) -> np.ndarray:
        """
        Convert market data and portfolio state into normalized state vector.
        
        Args:
            market_data: List of market data (lookback window)
            portfolio_state: Current portfolio state
            
        Returns:
            Normalized state vector
        """
        if not market_data:
            return np.zeros(self.total_dim)
            
        # Ensure we have enough data
        if len(market_data) < self.lookback_window:
            # Pad with first available data point
            padded_data = [market_data[0]] * (self.lookback_window - len(market_data)) + market_data
            market_data = padded_data
        elif len(market_data) > self.lookback_window:
            # Take the most recent data
            market_data = market_data[-self.lookback_window:]
            
        features = []
        
        # 1. Price features (normalized OHLC for each timestep)
        price_features = self._extract_price_features(market_data)
        features.extend(price_features)
        
        # 2. Technical indicators (based on current data)
        technical_features = self._extract_technical_features(market_data)
        features.extend(technical_features)
        
        # 3. Portfolio features
        portfolio_features = self._extract_portfolio_features(portfolio_state)
        features.extend(portfolio_features)
        
        # 4. Temporal features
        temporal_features = self._extract_temporal_features(market_data[-1])
        features.extend(temporal_features)
        
        return np.array(features, dtype=np.float32)
        
    def get_state_dimension(self) -> int:
        """Return the dimension of the state space."""
        return self.total_dim
        
    def _extract_price_features(self, market_data: List[MarketData]) -> List[float]:
        """Extract and normalize price features."""
        features = []
        
        # Get price series
        opens = [d.open for d in market_data]
        highs = [d.high for d in market_data]
        lows = [d.low for d in market_data]
        closes = [d.close for d in market_data]
        
        # Normalize prices relative to the first close price
        base_price = closes[0] if closes else 1.0
        
        for i in range(len(market_data)):
            # Normalize OHLC relative to base price
            norm_open = (opens[i] - base_price) / base_price
            norm_high = (highs[i] - base_price) / base_price
            norm_low = (lows[i] - base_price) / base_price
            norm_close = (closes[i] - base_price) / base_price
            
            features.extend([norm_open, norm_high, norm_low, norm_close])
            
        return features
        
    def _extract_technical_features(self, market_data: List[MarketData]) -> List[float]:
        """Extract technical indicator features."""
        if len(market_data) < 2:
            return [0.0] * self.technical_features_dim
            
        closes = [d.close for d in market_data]
        highs = [d.high for d in market_data]
        lows = [d.low for d in market_data]
        volumes = [d.volume for d in market_data]
        
        features = []
        
        # 1. Simple Moving Average ratio (SMA5/SMA10)
        sma_ratio = self._calculate_sma_ratio(closes)
        features.append(sma_ratio)
        
        # 2. RSI (normalized to [-1, 1])
        rsi = self._calculate_rsi(closes)
        features.append((rsi - 50) / 50)  # Normalize RSI to [-1, 1]
        
        # 3. Price momentum (rate of change)
        momentum = self._calculate_momentum(closes, periods=5)
        features.append(momentum)
        
        # 4. Volatility (normalized standard deviation)
        volatility = self._calculate_volatility(closes)
        features.append(volatility)
        
        # 5. Volume ratio (current vs average)
        volume_ratio = self._calculate_volume_ratio(volumes)
        features.append(volume_ratio)
        
        # 6. High-Low spread
        hl_spread = self._calculate_hl_spread(highs, lows, closes)
        features.append(hl_spread)
        
        # 7. Price position within recent range
        price_position = self._calculate_price_position(closes, highs, lows)
        features.append(price_position)
        
        # 8. Trend strength
        trend_strength = self._calculate_trend_strength(closes)
        features.append(trend_strength)
        
        return features
        
    def _extract_portfolio_features(self, portfolio_state: PortfolioState) -> List[float]:
        """Extract portfolio state features."""
        features = []
        
        # 1. Current position (already normalized to [-1, 1])
        features.append(portfolio_state.current_position)
        
        # 2. Unrealized P&L ratio
        pnl_ratio = portfolio_state.unrealized_pnl / max(portfolio_state.balance, 1.0)
        features.append(np.clip(pnl_ratio, -1.0, 1.0))
        
        # 3. Current drawdown
        features.append(-portfolio_state.current_drawdown)  # Negative because drawdown is bad
        
        # 4. Win rate (if any trades)
        win_rate = portfolio_state.winning_trades / max(portfolio_state.total_trades, 1)
        features.append(win_rate * 2 - 1)  # Normalize to [-1, 1]
        
        # 5. Trade frequency (normalized)
        trade_frequency = min(portfolio_state.total_trades / 100.0, 1.0)  # Cap at 100 trades
        features.append(trade_frequency)
        
        # 6. Equity ratio (current equity vs initial balance)
        equity_ratio = (portfolio_state.equity / self.config.initial_balance) - 1.0
        features.append(np.clip(equity_ratio, -1.0, 2.0))  # Allow up to 200% gain
        
        return features
        
    def _extract_temporal_features(self, market_data: MarketData) -> List[float]:
        """Extract time-based features."""
        timestamp = market_data.timestamp
        
        # Hour of day (normalized to [-1, 1])
        hour_norm = (timestamp.hour - 12) / 12.0
        
        # Day of week (normalized to [-1, 1])
        day_norm = (timestamp.weekday() - 2.5) / 2.5
        
        # Day of month (normalized to [-1, 1])
        day_month_norm = (timestamp.day - 15.5) / 15.5
        
        # Month of year (normalized to [-1, 1])
        month_norm = (timestamp.month - 6.5) / 6.5
        
        return [hour_norm, day_norm, day_month_norm, month_norm]
        
    # Technical indicator calculation methods
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
            return 50.0  # Neutral RSI
            
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
        
        # Normalize volatility (typical forex volatility is 0.01-0.02)
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
        return min(ratio, 3.0) - 1.0  # Normalize to [-1, 2]
        
    def _calculate_hl_spread(self, highs: List[float], lows: List[float], closes: List[float]) -> float:
        """Calculate high-low spread."""
        if not highs or not lows or not closes:
            return 0.0
            
        current_high = highs[-1]
        current_low = lows[-1]
        current_close = closes[-1]
        
        if current_close == 0:
            return 0.0
            
        spread = (current_high - current_low) / current_close
        return min(spread, 0.1)  # Cap at 10%
        
    def _calculate_price_position(self, closes: List[float], highs: List[float], lows: List[float]) -> float:
        """Calculate price position within recent range."""
        if len(closes) < 2:
            return 0.0
            
        recent_high = max(highs[-min(10, len(highs)):])
        recent_low = min(lows[-min(10, len(lows)):])
        current_price = closes[-1]
        
        if recent_high == recent_low:
            return 0.0
            
        position = (current_price - recent_low) / (recent_high - recent_low)
        return position * 2 - 1  # Normalize to [-1, 1]
        
    def _calculate_trend_strength(self, prices: List[float]) -> float:
        """Calculate trend strength."""
        if len(prices) < 3:
            return 0.0
            
        # Simple linear regression slope
        x = np.arange(len(prices))
        y = np.array(prices)
        
        if len(x) < 2:
            return 0.0
            
        slope = np.polyfit(x, y, 1)[0]
        
        # Normalize slope relative to price level
        avg_price = np.mean(prices)
        if avg_price == 0:
            return 0.0
            
        normalized_slope = slope / avg_price
        return np.clip(normalized_slope * 100, -1.0, 1.0)  # Scale and clip