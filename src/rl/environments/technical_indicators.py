"""
Technical Indicators for RL Trading Environment

This module provides comprehensive technical indicator calculations
for feature engineering in the state processor.
"""

import numpy as np
from typing import List, Tuple, Optional
from dataclasses import dataclass


@dataclass
class IndicatorConfig:
    """Configuration for technical indicators."""
    rsi_period: int = 14
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    bb_period: int = 20
    bb_std: float = 2.0
    stoch_k_period: int = 14
    stoch_d_period: int = 3
    atr_period: int = 14
    adx_period: int = 14
    cci_period: int = 20
    williams_r_period: int = 14
    momentum_period: int = 10
    roc_period: int = 12


class TechnicalIndicators:
    """
    Comprehensive technical indicator calculations.
    
    Provides a wide range of technical indicators commonly used
    in forex trading for feature engineering.
    """
    
    def __init__(self, config: IndicatorConfig = None):
        self.config = config or IndicatorConfig()
        
    def calculate_all_indicators(self, 
                               opens: List[float],
                               highs: List[float], 
                               lows: List[float],
                               closes: List[float],
                               volumes: List[int]) -> dict:
        """
        Calculate all technical indicators.
        
        Args:
            opens: Open prices
            highs: High prices
            lows: Low prices
            closes: Close prices
            volumes: Volume data
            
        Returns:
            Dictionary of indicator values
        """
        if not closes or len(closes) < 2:
            return self._get_default_indicators()
            
        indicators = {}
        
        # Convert to numpy arrays for efficiency
        o = np.array(opens, dtype=np.float64)
        h = np.array(highs, dtype=np.float64)
        l = np.array(lows, dtype=np.float64)
        c = np.array(closes, dtype=np.float64)
        v = np.array(volumes, dtype=np.float64)
        
        # Trend Indicators
        indicators.update(self._calculate_trend_indicators(o, h, l, c))
        
        # Momentum Indicators
        indicators.update(self._calculate_momentum_indicators(o, h, l, c))
        
        # Volatility Indicators
        indicators.update(self._calculate_volatility_indicators(h, l, c))
        
        # Volume Indicators
        indicators.update(self._calculate_volume_indicators(c, v))
        
        # Support/Resistance Indicators
        indicators.update(self._calculate_support_resistance_indicators(h, l, c))
        
        return indicators
        
    def _calculate_trend_indicators(self, opens: np.ndarray, highs: np.ndarray, 
                                  lows: np.ndarray, closes: np.ndarray) -> dict:
        """Calculate trend-following indicators."""
        indicators = {}
        
        # Simple Moving Averages
        indicators['sma_5'] = self._sma(closes, 5)
        indicators['sma_10'] = self._sma(closes, 10)
        indicators['sma_20'] = self._sma(closes, 20)
        indicators['sma_50'] = self._sma(closes, 50)
        
        # Exponential Moving Averages
        indicators['ema_5'] = self._ema(closes, 5)
        indicators['ema_10'] = self._ema(closes, 10)
        indicators['ema_20'] = self._ema(closes, 20)
        
        # MACD
        macd_line, macd_signal, macd_histogram = self._macd(closes)
        indicators['macd_line'] = macd_line
        indicators['macd_signal'] = macd_signal
        indicators['macd_histogram'] = macd_histogram
        
        # Average Directional Index (ADX)
        indicators['adx'] = self._adx(highs, lows, closes)
        
        # Parabolic SAR
        indicators['sar'] = self._parabolic_sar(highs, lows, closes)
        
        return indicators
        
    def _calculate_momentum_indicators(self, opens: np.ndarray, highs: np.ndarray,
                                     lows: np.ndarray, closes: np.ndarray) -> dict:
        """Calculate momentum oscillators."""
        indicators = {}
        
        # RSI
        indicators['rsi'] = self._rsi(closes, self.config.rsi_period)
        
        # Stochastic Oscillator
        stoch_k, stoch_d = self._stochastic(highs, lows, closes)
        indicators['stoch_k'] = stoch_k
        indicators['stoch_d'] = stoch_d
        
        # Williams %R
        indicators['williams_r'] = self._williams_r(highs, lows, closes)
        
        # Commodity Channel Index (CCI)
        indicators['cci'] = self._cci(highs, lows, closes)
        
        # Rate of Change (ROC)
        indicators['roc'] = self._roc(closes, self.config.roc_period)
        
        # Momentum
        indicators['momentum'] = self._momentum(closes, self.config.momentum_period)
        
        return indicators
        
    def _calculate_volatility_indicators(self, highs: np.ndarray, 
                                       lows: np.ndarray, closes: np.ndarray) -> dict:
        """Calculate volatility indicators."""
        indicators = {}
        
        # Bollinger Bands
        bb_upper, bb_middle, bb_lower = self._bollinger_bands(closes)
        indicators['bb_upper'] = bb_upper
        indicators['bb_middle'] = bb_middle
        indicators['bb_lower'] = bb_lower
        indicators['bb_width'] = (bb_upper - bb_lower) / bb_middle if bb_middle != 0 else 0
        indicators['bb_position'] = ((closes[-1] - bb_lower) / (bb_upper - bb_lower) 
                                   if bb_upper != bb_lower else 0.5)
        
        # Average True Range (ATR)
        indicators['atr'] = self._atr(highs, lows, closes)
        
        # Historical Volatility
        indicators['volatility'] = self._historical_volatility(closes)
        
        return indicators
        
    def _calculate_volume_indicators(self, closes: np.ndarray, volumes: np.ndarray) -> dict:
        """Calculate volume-based indicators."""
        indicators = {}
        
        if len(volumes) < 2:
            indicators['volume_sma'] = 0.0
            indicators['volume_ratio'] = 1.0
            indicators['obv'] = 0.0
            return indicators
            
        # Volume SMA
        indicators['volume_sma'] = self._sma(volumes, 10)
        
        # Volume Ratio
        current_volume = volumes[-1]
        avg_volume = np.mean(volumes[-10:]) if len(volumes) >= 10 else np.mean(volumes)
        indicators['volume_ratio'] = current_volume / avg_volume if avg_volume > 0 else 1.0
        
        # On-Balance Volume (OBV)
        indicators['obv'] = self._obv(closes, volumes)
        
        return indicators
        
    def _calculate_support_resistance_indicators(self, highs: np.ndarray,
                                               lows: np.ndarray, closes: np.ndarray) -> dict:
        """Calculate support and resistance indicators."""
        indicators = {}
        
        # Pivot Points
        pivot_points = self._pivot_points(highs, lows, closes)
        indicators.update(pivot_points)
        
        # Price position in recent range
        lookback = min(20, len(closes))
        if lookback > 1:
            recent_high = np.max(highs[-lookback:])
            recent_low = np.min(lows[-lookback:])
            current_price = closes[-1]
            
            if recent_high != recent_low:
                indicators['price_position'] = ((current_price - recent_low) / 
                                              (recent_high - recent_low))
            else:
                indicators['price_position'] = 0.5
        else:
            indicators['price_position'] = 0.5
            
        return indicators
        
    # Technical Indicator Calculation Methods
    
    def _sma(self, data: np.ndarray, period: int) -> float:
        """Simple Moving Average."""
        if len(data) < period:
            return np.mean(data) if len(data) > 0 else 0.0
        return np.mean(data[-period:])
        
    def _ema(self, data: np.ndarray, period: int) -> float:
        """Exponential Moving Average."""
        if len(data) == 0:
            return 0.0
        if len(data) == 1:
            return data[0]
            
        alpha = 2.0 / (period + 1)
        ema = data[0]
        
        for price in data[1:]:
            ema = alpha * price + (1 - alpha) * ema
            
        return ema
        
    def _rsi(self, data: np.ndarray, period: int) -> float:
        """Relative Strength Index."""
        if len(data) < period + 1:
            return 50.0  # Neutral RSI
            
        deltas = np.diff(data[-period-1:])
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        
        avg_gain = np.mean(gains)
        avg_loss = np.mean(losses)
        
        if avg_loss == 0:
            return 100.0
            
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
        
    def _macd(self, data: np.ndarray) -> Tuple[float, float, float]:
        """MACD (Moving Average Convergence Divergence)."""
        if len(data) < max(self.config.macd_fast, self.config.macd_slow):
            return 0.0, 0.0, 0.0
            
        ema_fast = self._ema(data, self.config.macd_fast)
        ema_slow = self._ema(data, self.config.macd_slow)
        
        macd_line = ema_fast - ema_slow
        
        # For signal line, we'd need historical MACD values
        # Simplified: use a fraction of MACD line
        macd_signal = macd_line * 0.8  # Approximation
        macd_histogram = macd_line - macd_signal
        
        return macd_line, macd_signal, macd_histogram
        
    def _stochastic(self, highs: np.ndarray, lows: np.ndarray, 
                   closes: np.ndarray) -> Tuple[float, float]:
        """Stochastic Oscillator."""
        period = self.config.stoch_k_period
        
        if len(closes) < period:
            return 50.0, 50.0
            
        recent_highs = highs[-period:]
        recent_lows = lows[-period:]
        current_close = closes[-1]
        
        highest_high = np.max(recent_highs)
        lowest_low = np.min(recent_lows)
        
        if highest_high == lowest_low:
            stoch_k = 50.0
        else:
            stoch_k = ((current_close - lowest_low) / (highest_high - lowest_low)) * 100
            
        # %D is SMA of %K (simplified)
        stoch_d = stoch_k * 0.9  # Approximation
        
        return stoch_k, stoch_d
        
    def _williams_r(self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray) -> float:
        """Williams %R."""
        period = self.config.williams_r_period
        
        if len(closes) < period:
            return -50.0
            
        recent_highs = highs[-period:]
        recent_lows = lows[-period:]
        current_close = closes[-1]
        
        highest_high = np.max(recent_highs)
        lowest_low = np.min(recent_lows)
        
        if highest_high == lowest_low:
            return -50.0
            
        williams_r = ((highest_high - current_close) / (highest_high - lowest_low)) * -100
        
        return williams_r
        
    def _cci(self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray) -> float:
        """Commodity Channel Index."""
        period = self.config.cci_period
        
        if len(closes) < period:
            return 0.0
            
        # Typical Price
        typical_prices = (highs[-period:] + lows[-period:] + closes[-period:]) / 3
        
        sma_tp = np.mean(typical_prices)
        current_tp = typical_prices[-1]
        
        # Mean Deviation
        mean_deviation = np.mean(np.abs(typical_prices - sma_tp))
        
        if mean_deviation == 0:
            return 0.0
            
        cci = (current_tp - sma_tp) / (0.015 * mean_deviation)
        
        return cci
        
    def _bollinger_bands(self, data: np.ndarray) -> Tuple[float, float, float]:
        """Bollinger Bands."""
        period = self.config.bb_period
        std_dev = self.config.bb_std
        
        if len(data) < period:
            current_price = data[-1] if len(data) > 0 else 0.0
            return current_price, current_price, current_price
            
        sma = np.mean(data[-period:])
        std = np.std(data[-period:])
        
        upper_band = sma + (std * std_dev)
        lower_band = sma - (std * std_dev)
        
        return upper_band, sma, lower_band
        
    def _atr(self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray) -> float:
        """Average True Range."""
        period = self.config.atr_period
        
        if len(closes) < 2:
            return 0.0
            
        # True Range calculation
        tr_values = []
        for i in range(1, len(closes)):
            high_low = highs[i] - lows[i]
            high_close_prev = abs(highs[i] - closes[i-1])
            low_close_prev = abs(lows[i] - closes[i-1])
            
            tr = max(high_low, high_close_prev, low_close_prev)
            tr_values.append(tr)
            
        if len(tr_values) < period:
            return np.mean(tr_values) if tr_values else 0.0
            
        return np.mean(tr_values[-period:])
        
    def _adx(self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray) -> float:
        """Average Directional Index (simplified)."""
        if len(closes) < self.config.adx_period + 1:
            return 25.0  # Neutral ADX
            
        # Simplified ADX calculation
        # In practice, this would require more complex DI+ and DI- calculations
        price_changes = np.abs(np.diff(closes[-self.config.adx_period:]))
        avg_change = np.mean(price_changes)
        
        # Normalize to 0-100 scale
        adx = min(avg_change * 10000, 100)  # Scale for forex prices
        
        return adx
        
    def _parabolic_sar(self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray) -> float:
        """Parabolic SAR (simplified)."""
        if len(closes) < 2:
            return closes[-1] if len(closes) > 0 else 0.0
            
        # Simplified SAR calculation
        current_price = closes[-1]
        prev_price = closes[-2]
        
        if current_price > prev_price:
            # Uptrend - SAR below price
            sar = min(lows[-min(5, len(lows)):])
        else:
            # Downtrend - SAR above price
            sar = max(highs[-min(5, len(highs)):])
            
        return sar
        
    def _roc(self, data: np.ndarray, period: int) -> float:
        """Rate of Change."""
        if len(data) < period + 1:
            return 0.0
            
        current_price = data[-1]
        past_price = data[-period-1]
        
        if past_price == 0:
            return 0.0
            
        roc = ((current_price - past_price) / past_price) * 100
        
        return roc
        
    def _momentum(self, data: np.ndarray, period: int) -> float:
        """Price Momentum."""
        if len(data) < period + 1:
            return 0.0
            
        current_price = data[-1]
        past_price = data[-period-1]
        
        momentum = current_price - past_price
        
        return momentum
        
    def _historical_volatility(self, data: np.ndarray, period: int = 20) -> float:
        """Historical Volatility."""
        if len(data) < 2:
            return 0.0
            
        returns = np.diff(np.log(data[-period:]))
        volatility = np.std(returns) * np.sqrt(252)  # Annualized
        
        return volatility
        
    def _obv(self, closes: np.ndarray, volumes: np.ndarray) -> float:
        """On-Balance Volume."""
        if len(closes) < 2 or len(volumes) < 2:
            return 0.0
            
        obv = 0
        for i in range(1, len(closes)):
            if closes[i] > closes[i-1]:
                obv += volumes[i]
            elif closes[i] < closes[i-1]:
                obv -= volumes[i]
                
        return obv
        
    def _pivot_points(self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray) -> dict:
        """Pivot Points."""
        if len(closes) < 1:
            return {'pivot': 0.0, 'r1': 0.0, 'r2': 0.0, 's1': 0.0, 's2': 0.0}
            
        # Use recent high, low, close for pivot calculation
        recent_high = np.max(highs[-min(5, len(highs)):])
        recent_low = np.min(lows[-min(5, len(lows)):])
        recent_close = closes[-1]
        
        pivot = (recent_high + recent_low + recent_close) / 3
        
        r1 = 2 * pivot - recent_low
        r2 = pivot + (recent_high - recent_low)
        s1 = 2 * pivot - recent_high
        s2 = pivot - (recent_high - recent_low)
        
        return {
            'pivot': pivot,
            'r1': r1,
            'r2': r2,
            's1': s1,
            's2': s2
        }
        
    def _get_default_indicators(self) -> dict:
        """Return default indicator values when insufficient data."""
        return {
            # Trend indicators
            'sma_5': 0.0, 'sma_10': 0.0, 'sma_20': 0.0, 'sma_50': 0.0,
            'ema_5': 0.0, 'ema_10': 0.0, 'ema_20': 0.0,
            'macd_line': 0.0, 'macd_signal': 0.0, 'macd_histogram': 0.0,
            'adx': 25.0, 'sar': 0.0,
            
            # Momentum indicators
            'rsi': 50.0, 'stoch_k': 50.0, 'stoch_d': 50.0,
            'williams_r': -50.0, 'cci': 0.0, 'roc': 0.0, 'momentum': 0.0,
            
            # Volatility indicators
            'bb_upper': 0.0, 'bb_middle': 0.0, 'bb_lower': 0.0,
            'bb_width': 0.0, 'bb_position': 0.5, 'atr': 0.0, 'volatility': 0.0,
            
            # Volume indicators
            'volume_sma': 0.0, 'volume_ratio': 1.0, 'obv': 0.0,
            
            # Support/Resistance indicators
            'pivot': 0.0, 'r1': 0.0, 'r2': 0.0, 's1': 0.0, 's2': 0.0,
            'price_position': 0.5
        }