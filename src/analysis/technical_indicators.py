"""Technical indicators calculator for forex trading analysis"""

import numpy as np
import pandas as pd
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
from src.models import MarketData
from src.exceptions import DataValidationError


@dataclass
class TechnicalIndicators:
    """Container for technical indicator values"""
    symbol: str
    timestamp: datetime
    sma_20: Optional[float] = None
    sma_50: Optional[float] = None
    ema_12: Optional[float] = None
    ema_26: Optional[float] = None
    rsi: Optional[float] = None
    macd: Optional[float] = None
    macd_signal: Optional[float] = None
    macd_histogram: Optional[float] = None
    bollinger_upper: Optional[float] = None
    bollinger_middle: Optional[float] = None
    bollinger_lower: Optional[float] = None
    stochastic_k: Optional[float] = None
    stochastic_d: Optional[float] = None
    atr: Optional[float] = None
    adx: Optional[float] = None
    williams_r: Optional[float] = None
    
    def to_dict(self) -> Dict[str, float]:
        """Convert indicators to dictionary, excluding None values"""
        return {k: v for k, v in self.__dict__.items() 
                if v is not None and k not in ['symbol', 'timestamp']}
    
    def get(self, key: str, default=None):
        """Get indicator value by name (dict-like interface)"""
        return getattr(self, key, default)
    
    def __getitem__(self, key: str):
        """Allow bracket notation access to indicators"""
        value = getattr(self, key, None)
        if value is None:
            raise KeyError(f"Indicator '{key}' not available")
        return value
    
    def __contains__(self, key: str) -> bool:
        """Allow 'in' operator"""
        return hasattr(self, key) and getattr(self, key) is not None


class IndicatorCalculator:
    """Calculate technical indicators from market data"""
    
    def __init__(self, timeframes: List[str] = None):
        """Initialize calculator with supported timeframes"""
        self.timeframes = timeframes or ['1m', '5m', '15m', '1h', '4h', '1d']
        self.data_cache: Dict[str, List[MarketData]] = {}
    
    def add_market_data(self, data: MarketData) -> None:
        """Add market data to the cache for calculations"""
        key = f"{data.symbol}_{self._get_timeframe_key(data.timestamp)}"
        if key not in self.data_cache:
            self.data_cache[key] = []
        
        # Insert data in chronological order
        self.data_cache[key].append(data)
        self.data_cache[key].sort(key=lambda x: x.timestamp)
        
        # Keep only last 200 periods for efficiency
        if len(self.data_cache[key]) > 200:
            self.data_cache[key] = self.data_cache[key][-200:]
    
    def calculate_indicators(self, symbol: str, timeframe: str = '1h', 
                           periods: int = 50) -> TechnicalIndicators:
        """Calculate all technical indicators for a symbol"""
        data_key = f"{symbol}_{timeframe}"
        
        if data_key not in self.data_cache or len(self.data_cache[data_key]) < 2:
            raise DataValidationError(
                f"Insufficient data for {symbol} on {timeframe}",
                error_code="INSUFFICIENT_DATA",
                context={"symbol": symbol, "timeframe": timeframe}
            )
        
        data_list = self.data_cache[data_key][-periods:]
        
        # ===== BUG #3 FIX: More lenient minimum bars requirement =====
        # Allow calculation with as few as 5 bars (for fast-moving situations)
        # but still warn if we're below 20 bars
        if len(data_list) < 5:
            raise DataValidationError(
                f"Need at least 5 periods for indicators, got {len(data_list)}",
                error_code="INSUFFICIENT_PERIODS",
                context={"symbol": symbol, "periods": len(data_list)}
            )
        
        if len(data_list) < 20:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(
                f"[INDICATORS_LOW_DATA] {symbol} on {timeframe}: Only {len(data_list)} bars available "
                f"(minimum for all indicators: 20). Some indicators may be missing or calculated with reduced precision."
            )
        
        # Convert to arrays for calculations
        closes = np.array([d.close for d in data_list])
        highs = np.array([d.high for d in data_list])
        lows = np.array([d.low for d in data_list])
        volumes = np.array([d.volume for d in data_list])
        
        indicators = TechnicalIndicators(
            symbol=symbol,
            timestamp=data_list[-1].timestamp
        )
        
        # Calculate moving averages with adaptive periods based on available data
        min_bars = len(closes)
        if min_bars >= 20:
            indicators.sma_20 = self._calculate_sma(closes, 20)
        if min_bars >= 50:
            indicators.sma_50 = self._calculate_sma(closes, 50)
        
        # Calculate exponential moving averages
        if min_bars >= 12:
            indicators.ema_12 = self._calculate_ema(closes, 12)
        if min_bars >= 26:
            indicators.ema_26 = self._calculate_ema(closes, 26)
        
        # Calculate RSI
        if len(closes) >= 14:
            indicators.rsi = self._calculate_rsi(closes, 14)
        
        # Calculate MACD
        if len(closes) >= 26:
            macd_data = self._calculate_macd(closes)
            indicators.macd = macd_data['macd']
            indicators.macd_signal = macd_data['signal']
            indicators.macd_histogram = macd_data['histogram']
        
        # Calculate Bollinger Bands
        if len(closes) >= 20:
            bb_data = self._calculate_bollinger_bands(closes, 20, 2.0)
            indicators.bollinger_upper = bb_data['upper']
            indicators.bollinger_middle = bb_data['middle']
            indicators.bollinger_lower = bb_data['lower']
        
        # Calculate Stochastic
        if len(closes) >= 14:
            stoch_data = self._calculate_stochastic(highs, lows, closes, 14, 3)
            indicators.stochastic_k = stoch_data['k']
            indicators.stochastic_d = stoch_data['d']
        
        # Calculate ATR
        if len(closes) >= 14:
            indicators.atr = self._calculate_atr(highs, lows, closes, 14)

        # Calculate ADX
        if len(closes) >= 20: # Needs more for smoothing
            indicators.adx = self._calculate_adx(highs, lows, closes, 14)

        # Calculate Williams %R
        if len(closes) >= 14:
            indicators.williams_r = self._calculate_williams_r(highs, lows, closes, 14)
        
        return indicators
    
    def _calculate_sma(self, prices: np.ndarray, period: int) -> float:
        """Calculate Simple Moving Average"""
        if len(prices) < period:
            return None
        return float(np.mean(prices[-period:]))
    
    def _calculate_ema(self, prices: np.ndarray, period: int) -> float:
        """Calculate Exponential Moving Average"""
        if len(prices) < period:
            return None
        
        # Calculate initial SMA for the first EMA point
        initial_sma = np.mean(prices[:period])
        multiplier = 2.0 / (period + 1)
        ema = initial_sma
        
        # Calculate EMA for the rest of the array
        for price in prices[period:]:
            ema = (price * multiplier) + (ema * (1 - multiplier))
        
        return float(ema)

    def _calculate_ema_series(self, prices: np.ndarray, period: int) -> np.ndarray:
        """Calculate a series of Exponential Moving Averages"""
        if len(prices) < period:
            return np.array([])
            
        multiplier = 2.0 / (period + 1)
        ema_values = np.zeros_like(prices)
        ema_values[period-1] = np.mean(prices[:period])
        
        for i in range(period, len(prices)):
            ema_values[i] = (prices[i] * multiplier) + (ema_values[i-1] * (1 - multiplier))
            
        return ema_values

    def _calculate_rsi(self, prices: np.ndarray, period: int = 14) -> float:
        """Calculate Relative Strength Index"""
        if len(prices) < period + 1:
            return None
        
        diff = np.diff(prices)
        up = diff.copy()
        down = diff.copy()
        up[up < 0] = 0
        down[down > 0] = 0
        
        # Use Wilders smoothing
        avg_gain = np.mean(up[:period])
        avg_loss = np.mean(np.abs(down[:period]))
        
        alpha = 1.0 / period
        
        for i in range(period, len(diff)):
            avg_gain = alpha * up[i] + (1 - alpha) * avg_gain
            avg_loss = alpha * np.abs(down[i]) + (1 - alpha) * avg_loss
            
        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0
            
        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))
        
        return float(rsi)
    
    def _calculate_macd(self, prices: np.ndarray, fast: int = 12, 
                       slow: int = 26, signal: int = 9) -> Dict[str, float]:
        """Calculate MACD (Moving Average Convergence Divergence)"""
        if len(prices) < slow + signal:
            return {'macd': None, 'signal': None, 'histogram': None}
        
        ema_fast_series = self._calculate_ema_series(prices, fast)
        ema_slow_series = self._calculate_ema_series(prices, slow)
        
        # Align series (pad with 0s at the start where EMA is not yet calculated)
        valid_start = slow - 1
        macosx = ema_fast_series[valid_start:] - ema_slow_series[valid_start:]
        
        # Calculate signal line (EMA of MACD line)
        signal_line_series = self._calculate_ema_series(macosx, signal)
        
        if len(signal_line_series) < signal:
             return {'macd': None, 'signal': None, 'histogram': None}

        current_macd = macosx[-1]
        current_signal = signal_line_series[-1]
        histogram = current_macd - current_signal
        
        return {
            'macd': float(current_macd),
            'signal': float(current_signal),
            'histogram': float(histogram)
        }
    
    def _calculate_bollinger_bands(self, prices: np.ndarray, period: int = 20, 
                                  std_dev: float = 2.0) -> Dict[str, float]:
        """Calculate Bollinger Bands"""
        if len(prices) < period:
            return {'upper': None, 'middle': None, 'lower': None}
        
        sma = self._calculate_sma(prices, period)
        std = float(np.std(prices[-period:]))
        
        upper = sma + (std_dev * std)
        lower = sma - (std_dev * std)
        
        return {
            'upper': float(upper),
            'middle': float(sma),
            'lower': float(lower)
        }
    
    def _calculate_stochastic(self, highs: np.ndarray, lows: np.ndarray, 
                             closes: np.ndarray, k_period: int = 14, 
                             d_period: int = 3) -> Dict[str, float]:
        """Calculate Stochastic Oscillator"""
        if len(closes) < k_period:
            return {'k': None, 'd': None}
        
        # Calculate %K
        lowest_low = np.min(lows[-k_period:])
        highest_high = np.max(highs[-k_period:])
        current_close = closes[-1]
        
        if highest_high == lowest_low:
            k_percent = 50.0  # Avoid division by zero
        else:
            k_percent = ((current_close - lowest_low) / 
                        (highest_high - lowest_low)) * 100.0
        
        # %D is typically a moving average of %K
        # For simplicity, we'll return %K as both values
        # In production, you'd maintain %K history for proper %D calculation
        d_percent = k_percent
        
        return {
            'k': float(k_percent),
            'd': float(d_percent)
        }
    
    def _calculate_atr(self, highs: np.ndarray, lows: np.ndarray, 
                      closes: np.ndarray, period: int = 14) -> float:
        """Calculate Average True Range"""
        if len(closes) < period + 1:
            return None
        
        # Calculate True Range for each period
        true_ranges = []
        
        for i in range(1, len(closes)):
            high_low = highs[i] - lows[i]
            high_close_prev = abs(highs[i] - closes[i-1])
            low_close_prev = abs(lows[i] - closes[i-1])
            
            true_range = max(high_low, high_close_prev, low_close_prev)
            true_ranges.append(true_range)
        
        # Calculate ATR as average of last 'period' true ranges
        if len(true_ranges) >= period:
            atr = np.mean(true_ranges[-period:])
            return float(atr)
        
        return None

    def _calculate_adx(self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> float:
        """Calculate Average Directional Index (ADX)"""
        if len(closes) < period * 2:
            return None
            
        up_move = np.diff(highs)
        down_move = -np.diff(lows)
        
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)
        
        # True Range
        tr = np.zeros_like(up_move)
        for i in range(len(tr)):
            tr[i] = max(highs[i+1] - lows[i+1], abs(highs[i+1] - closes[i]), abs(lows[i+1] - closes[i]))
            
        # Smoothing
        alpha = 1.0 / period
        atr = np.mean(tr[:period])
        ps_dm = np.mean(plus_dm[:period])
        ms_dm = np.mean(minus_dm[:period])
        
        dx_list = []
        for i in range(period, len(tr)):
            atr = alpha * tr[i] + (1 - alpha) * atr
            ps_dm = alpha * plus_dm[i] + (1 - alpha) * ps_dm
            ms_dm = alpha * minus_dm[i] + (1 - alpha) * ms_dm
            
            plus_di = 100.0 * ps_dm / atr if atr > 0 else 0
            minus_di = 100.0 * ms_dm / atr if atr > 0 else 0
            
            dx = 100.0 * abs(plus_di - minus_di) / (plus_di + minus_di) if (plus_di + minus_di) > 0 else 0
            dx_list.append(dx)
            
        if len(dx_list) < period:
            return None
            
        # ADX is the average of DX
        adx = np.mean(dx_list[-period:])
        return float(adx)

    def _calculate_williams_r(self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> float:
        """Calculate Williams %R"""
        if len(closes) < period:
            return None
            
        highest_high = np.max(highs[-period:])
        lowest_low = np.min(lows[-period:])
        current_close = closes[-1]
        
        if highest_high == lowest_low:
            return -50.0
            
        w_r = ((highest_high - current_close) / (highest_high - lowest_low)) * -100.0
        return float(w_r)
    
    def _get_timeframe_key(self, timestamp: datetime) -> str:
        """Generate timeframe key from timestamp"""
        # Simplified timeframe detection - in production you'd want more sophisticated logic
        return "1h"  # Default to 1 hour timeframe
    
    def get_trend_direction(self, indicators: TechnicalIndicators) -> str:
        """Determine trend direction from indicators"""
        if not indicators.sma_20 or not indicators.sma_50:
            return "UNKNOWN"
        
        if indicators.sma_20 > indicators.sma_50:
            return "UPTREND"
        elif indicators.sma_20 < indicators.sma_50:
            return "DOWNTREND"
        else:
            return "SIDEWAYS"
    
    def get_momentum_strength(self, indicators: TechnicalIndicators) -> float:
        """Calculate momentum strength from 0.0 to 1.0"""
        strength_factors = []
        
        # RSI momentum
        if indicators.rsi is not None:
            if indicators.rsi > 70:
                strength_factors.append(0.8)  # Overbought - strong momentum
            elif indicators.rsi < 25:
                strength_factors.append(0.8)  # Oversold - strong momentum
            else:
                # Normalize RSI to strength (50 = neutral = 0.5)
                strength_factors.append(abs(indicators.rsi - 50) / 50)
        
        # MACD momentum
        if indicators.macd is not None and indicators.macd_signal is not None:
            macd_diff = abs(indicators.macd - indicators.macd_signal)
            # Normalize MACD difference (arbitrary scaling)
            strength_factors.append(min(macd_diff * 1000, 1.0))
        
        # Stochastic momentum
        if indicators.stochastic_k is not None:
            if indicators.stochastic_k > 80 or indicators.stochastic_k < 20:
                strength_factors.append(0.8)
            else:
                strength_factors.append(abs(indicators.stochastic_k - 50) / 50)
        
        if not strength_factors:
            return 0.5  # Neutral if no indicators available
        
        return float(np.mean(strength_factors))
    
    def clear_cache(self, symbol: str = None) -> None:
        """Clear data cache for symbol or all symbols"""
        if symbol:
            keys_to_remove = [k for k in self.data_cache.keys() if k.startswith(symbol)]
            for key in keys_to_remove:
                del self.data_cache[key]
        else:
            self.data_cache.clear()