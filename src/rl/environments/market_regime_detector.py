"""
Market Session and Regime Awareness for RL Trading Environment

This module implements market session detection, volatility regime classification,
and adaptive strategies based on market conditions.
"""

import numpy as np
from typing import Dict, Any, List, Optional, Tuple, Union
from datetime import datetime, timezone, timedelta
from enum import Enum
import logging
from dataclasses import dataclass
from collections import deque, defaultdict
import pytz

from ...models import MarketData


logger = logging.getLogger(__name__)


class TradingSession(Enum):
    """Trading session types."""
    SYDNEY = "sydney"
    TOKYO = "tokyo"
    LONDON = "london"
    NEW_YORK = "new_york"
    OVERLAP_LONDON_NY = "london_ny_overlap"
    OVERLAP_TOKYO_LONDON = "tokyo_london_overlap"
    QUIET = "quiet"


class VolatilityRegime(Enum):
    """Volatility regime types."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    EXTREME = "extreme"


class TrendRegime(Enum):
    """Trend regime types."""
    STRONG_UPTREND = "strong_uptrend"
    WEAK_UPTREND = "weak_uptrend"
    SIDEWAYS = "sideways"
    WEAK_DOWNTREND = "weak_downtrend"
    STRONG_DOWNTREND = "strong_downtrend"


@dataclass
class SessionInfo:
    """Information about a trading session."""
    session: TradingSession
    start_hour_utc: int
    end_hour_utc: int
    timezone_name: str
    typical_volume_multiplier: float
    typical_volatility_multiplier: float
    major_pairs: List[str]  # Pairs most active during this session


@dataclass
class MarketRegime:
    """Current market regime information."""
    volatility_regime: VolatilityRegime
    trend_regime: TrendRegime
    current_session: TradingSession
    volatility_percentile: float  # 0-100
    trend_strength: float  # -1 to 1
    regime_confidence: float  # 0-1
    regime_duration: int  # Number of periods in current regime
    last_regime_change: datetime


class SessionDetector:
    """Detects current trading session based on time and market activity."""
    
    def __init__(self):
        # Define trading sessions (UTC hours)
        self.sessions = {
            TradingSession.SYDNEY: SessionInfo(
                session=TradingSession.SYDNEY,
                start_hour_utc=22,  # 22:00 UTC (Sydney 8:00 AM)
                end_hour_utc=7,     # 07:00 UTC (Sydney 5:00 PM)
                timezone_name='Australia/Sydney',
                typical_volume_multiplier=0.6,
                typical_volatility_multiplier=0.7,
                major_pairs=['AUD/USD', 'NZD/USD', 'AUD/JPY']
            ),
            TradingSession.TOKYO: SessionInfo(
                session=TradingSession.TOKYO,
                start_hour_utc=0,   # 00:00 UTC (Tokyo 9:00 AM)
                end_hour_utc=9,     # 09:00 UTC (Tokyo 6:00 PM)
                timezone_name='Asia/Tokyo',
                typical_volume_multiplier=0.8,
                typical_volatility_multiplier=0.8,
                major_pairs=['USD/JPY', 'EUR/JPY', 'GBP/JPY', 'AUD/JPY']
            ),
            TradingSession.LONDON: SessionInfo(
                session=TradingSession.LONDON,
                start_hour_utc=8,   # 08:00 UTC (London 8:00 AM)
                end_hour_utc=17,    # 17:00 UTC (London 5:00 PM)
                timezone_name='Europe/London',
                typical_volume_multiplier=1.2,
                typical_volatility_multiplier=1.1,
                major_pairs=['EUR/USD', 'GBP/USD', 'EUR/GBP', 'USD/CHF']
            ),
            TradingSession.NEW_YORK: SessionInfo(
                session=TradingSession.NEW_YORK,
                start_hour_utc=13,  # 13:00 UTC (New York 8:00 AM)
                end_hour_utc=22,    # 22:00 UTC (New York 5:00 PM)
                timezone_name='America/New_York',
                typical_volume_multiplier=1.0,
                typical_volatility_multiplier=1.0,
                major_pairs=['EUR/USD', 'GBP/USD', 'USD/JPY', 'USD/CAD']
            )
        }
        
        # Define overlap sessions
        self.overlap_sessions = {
            TradingSession.OVERLAP_TOKYO_LONDON: (2, 9),    # 02:00-09:00 UTC
            TradingSession.OVERLAP_LONDON_NY: (13, 17)  # 13:00-17:00 UTC
        }
        
        logger.info("Initialized session detector with 4 major sessions and 2 overlap periods")
        
    def detect_session(self, timestamp: datetime, pair: str = None) -> TradingSession:
        """
        Detect current trading session based on timestamp.
        
        Args:
            timestamp: Current timestamp (should be timezone-aware)
            pair: Optional currency pair for session-specific detection
            
        Returns:
            Current trading session
        """
        # Convert to UTC if not already
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        elif timestamp.tzinfo != timezone.utc:
            timestamp = timestamp.astimezone(timezone.utc)
            
        hour_utc = timestamp.hour
        
        # Check for overlap sessions first (higher priority)
        if 13 <= hour_utc <= 17:  # London-NY overlap
            return TradingSession.OVERLAP_LONDON_NY
        elif 2 <= hour_utc <= 9:  # Tokyo-London overlap
            return TradingSession.OVERLAP_TOKYO_LONDON
            
        # Check individual sessions
        for session_info in self.sessions.values():
            if self._is_in_session(hour_utc, session_info):
                # If pair is specified, check if it's major for this session
                if pair and pair in session_info.major_pairs:
                    return session_info.session
                elif pair is None:
                    return session_info.session
                    
        # Default to quiet session if no major session is active
        return TradingSession.QUIET
        
    def _is_in_session(self, hour_utc: int, session_info: SessionInfo) -> bool:
        """Check if hour is within session time."""
        start = session_info.start_hour_utc
        end = session_info.end_hour_utc
        
        if start <= end:
            return start <= hour_utc <= end
        else:  # Session crosses midnight
            return hour_utc >= start or hour_utc <= end
            
    def get_session_info(self, session: TradingSession) -> Optional[SessionInfo]:
        """Get information about a specific session."""
        return self.sessions.get(session)
        
    def get_active_sessions(self, timestamp: datetime) -> List[TradingSession]:
        """Get all currently active sessions."""
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        elif timestamp.tzinfo != timezone.utc:
            timestamp = timestamp.astimezone(timezone.utc)
            
        hour_utc = timestamp.hour
        active_sessions = []
        
        for session_info in self.sessions.values():
            if self._is_in_session(hour_utc, session_info):
                active_sessions.append(session_info.session)
                
        return active_sessions
        
    def get_session_multipliers(self, session: TradingSession) -> Tuple[float, float]:
        """Get volume and volatility multipliers for session."""
        session_info = self.sessions.get(session)
        if session_info:
            return session_info.typical_volume_multiplier, session_info.typical_volatility_multiplier
        return 1.0, 1.0


class VolatilityRegimeDetector:
    """Detects volatility regimes using statistical methods."""
    
    def __init__(self, lookback_periods: int = 100, regime_threshold: float = 0.2):
        self.lookback_periods = lookback_periods
        self.regime_threshold = regime_threshold
        self.price_history = deque(maxlen=lookback_periods)
        self.volatility_history = deque(maxlen=lookback_periods)
        self.current_regime = VolatilityRegime.NORMAL
        self.regime_start_time = None
        
        # Volatility percentile thresholds
        self.volatility_thresholds = {
            VolatilityRegime.LOW: (0, 25),      # 0-25th percentile
            VolatilityRegime.NORMAL: (25, 75),  # 25-75th percentile
            VolatilityRegime.HIGH: (75, 95),    # 75-95th percentile
            VolatilityRegime.EXTREME: (95, 100) # 95-100th percentile
        }
        
        logger.info(f"Initialized volatility regime detector with {lookback_periods} period lookback")
        
    def update(self, market_data: MarketData) -> VolatilityRegime:
        """
        Update volatility regime based on new market data.
        
        Args:
            market_data: Latest market data point
            
        Returns:
            Current volatility regime
        """
        # Calculate current volatility (using high-low range)
        if market_data.close > 0:
            current_volatility = (market_data.high - market_data.low) / market_data.close
        else:
            current_volatility = 0.0
            
        self.price_history.append(market_data.close)
        self.volatility_history.append(current_volatility)
        
        # Need sufficient history to detect regimes
        if len(self.volatility_history) < 20:
            return self.current_regime
            
        # Calculate volatility percentile
        volatility_array = np.array(self.volatility_history)
        current_percentile = self._calculate_percentile(current_volatility, volatility_array)
        
        # Determine regime based on percentile
        new_regime = self._classify_volatility_regime(current_percentile)
        
        # Check for regime change
        if new_regime != self.current_regime:
            logger.info(f"Volatility regime changed from {self.current_regime.value} to {new_regime.value}")
            self.current_regime = new_regime
            self.regime_start_time = market_data.timestamp
            
        return self.current_regime
        
    def _calculate_percentile(self, value: float, array: np.ndarray) -> float:
        """Calculate percentile of value within array."""
        if len(array) == 0:
            return 50.0
            
        return (np.sum(array <= value) / len(array)) * 100
        
    def _classify_volatility_regime(self, percentile: float) -> VolatilityRegime:
        """Classify volatility regime based on percentile."""
        for regime, (low, high) in self.volatility_thresholds.items():
            if low <= percentile < high:
                return regime
                
        return VolatilityRegime.EXTREME  # Default for 100th percentile
        
    def get_volatility_stats(self) -> Dict[str, float]:
        """Get current volatility statistics."""
        if len(self.volatility_history) == 0:
            return {'current': 0.0, 'mean': 0.0, 'std': 0.0, 'percentile': 50.0}
            
        volatility_array = np.array(self.volatility_history)
        current_vol = volatility_array[-1] if len(volatility_array) > 0 else 0.0
        
        return {
            'current': current_vol,
            'mean': np.mean(volatility_array),
            'std': np.std(volatility_array),
            'percentile': self._calculate_percentile(current_vol, volatility_array)
        }


class TrendRegimeDetector:
    """Detects trend regimes using multiple indicators."""
    
    def __init__(self, short_period: int = 20, long_period: int = 50, trend_threshold: float = 0.1):
        self.short_period = short_period
        self.long_period = long_period
        self.trend_threshold = trend_threshold
        self.price_history = deque(maxlen=long_period)
        self.current_regime = TrendRegime.SIDEWAYS
        self.regime_start_time = None
        
        logger.info(f"Initialized trend regime detector with {short_period}/{long_period} period MAs")
        
    def update(self, market_data: MarketData) -> TrendRegime:
        """
        Update trend regime based on new market data.
        
        Args:
            market_data: Latest market data point
            
        Returns:
            Current trend regime
        """
        self.price_history.append(market_data.close)
        
        # Need sufficient history
        if len(self.price_history) < self.long_period:
            return self.current_regime
            
        # Calculate trend indicators
        trend_strength = self._calculate_trend_strength()
        trend_direction = self._calculate_trend_direction()
        
        # Classify trend regime
        new_regime = self._classify_trend_regime(trend_strength, trend_direction)
        
        # Check for regime change
        if new_regime != self.current_regime:
            logger.info(f"Trend regime changed from {self.current_regime.value} to {new_regime.value}")
            self.current_regime = new_regime
            self.regime_start_time = market_data.timestamp
            
        return self.current_regime
        
    def _calculate_trend_strength(self) -> float:
        """Calculate trend strength using multiple methods."""
        prices = np.array(self.price_history)
        
        # Method 1: Linear regression slope
        x = np.arange(len(prices))
        slope = np.polyfit(x, prices, 1)[0]
        normalized_slope = slope / np.mean(prices) if np.mean(prices) > 0 else 0.0
        
        # Method 2: Moving average separation
        if len(prices) >= self.long_period:
            short_ma = np.mean(prices[-self.short_period:])
            long_ma = np.mean(prices[-self.long_period:])
            ma_separation = abs(short_ma - long_ma) / long_ma if long_ma > 0 else 0.0
        else:
            ma_separation = 0.0
            
        # Method 3: Price momentum
        if len(prices) >= 10:
            momentum = (prices[-1] - prices[-10]) / prices[-10] if prices[-10] > 0 else 0.0
        else:
            momentum = 0.0
            
        # Combine methods
        trend_strength = (abs(normalized_slope) * 100 + ma_separation + abs(momentum)) / 3
        return min(trend_strength, 1.0)  # Cap at 1.0
        
    def _calculate_trend_direction(self) -> float:
        """Calculate trend direction (-1 to 1)."""
        prices = np.array(self.price_history)
        
        if len(prices) < self.short_period:
            return 0.0
            
        # Use moving average crossover
        short_ma = np.mean(prices[-self.short_period:])
        long_ma = np.mean(prices[-self.long_period:]) if len(prices) >= self.long_period else short_ma
        
        if long_ma == 0:
            return 0.0
            
        direction = (short_ma - long_ma) / long_ma
        return np.clip(direction, -1.0, 1.0)
        
    def _classify_trend_regime(self, strength: float, direction: float) -> TrendRegime:
        """Classify trend regime based on strength and direction."""
        if strength < self.trend_threshold:
            return TrendRegime.SIDEWAYS
        elif direction > 0.5:
            return TrendRegime.STRONG_UPTREND
        elif direction > 0.1:
            return TrendRegime.WEAK_UPTREND
        elif direction < -0.5:
            return TrendRegime.STRONG_DOWNTREND
        elif direction < -0.1:
            return TrendRegime.WEAK_DOWNTREND
        else:
            return TrendRegime.SIDEWAYS
            
    def get_trend_stats(self) -> Dict[str, float]:
        """Get current trend statistics."""
        if len(self.price_history) < self.short_period:
            return {'strength': 0.0, 'direction': 0.0}
            
        strength = self._calculate_trend_strength()
        direction = self._calculate_trend_direction()
        
        return {
            'strength': strength,
            'direction': direction
        }


class MarketRegimeDetector:
    """Main class that combines session and regime detection."""
    
    def __init__(self, 
                 volatility_lookback: int = 100,
                 trend_short_period: int = 20,
                 trend_long_period: int = 50):
        self.session_detector = SessionDetector()
        self.volatility_detector = VolatilityRegimeDetector(volatility_lookback)
        self.trend_detector = TrendRegimeDetector(trend_short_period, trend_long_period)
        
        # Current regime state
        self.current_regime = MarketRegime(
            volatility_regime=VolatilityRegime.NORMAL,
            trend_regime=TrendRegime.SIDEWAYS,
            current_session=TradingSession.QUIET,
            volatility_percentile=50.0,
            trend_strength=0.0,
            regime_confidence=0.5,
            regime_duration=0,
            last_regime_change=datetime.now(timezone.utc)
        )
        
        self.regime_history = deque(maxlen=1000)
        
        logger.info("Initialized market regime detector")
        
    def update(self, market_data: MarketData, pair: str = None) -> MarketRegime:
        """
        Update market regime based on new market data.
        
        Args:
            market_data: Latest market data point
            pair: Currency pair (for session-specific detection)
            
        Returns:
            Updated market regime
        """
        # Detect current session
        current_session = self.session_detector.detect_session(market_data.timestamp, pair)
        
        # Update regime detectors
        volatility_regime = self.volatility_detector.update(market_data)
        trend_regime = self.trend_detector.update(market_data)
        
        # Get statistics
        vol_stats = self.volatility_detector.get_volatility_stats()
        trend_stats = self.trend_detector.get_trend_stats()
        
        # Calculate regime confidence
        confidence = self._calculate_regime_confidence(vol_stats, trend_stats)
        
        # Check for regime changes
        regime_changed = (
            volatility_regime != self.current_regime.volatility_regime or
            trend_regime != self.current_regime.trend_regime or
            current_session != self.current_regime.current_session
        )
        
        # Update regime duration
        if regime_changed:
            regime_duration = 0
            last_change = market_data.timestamp
        else:
            regime_duration = self.current_regime.regime_duration + 1
            last_change = self.current_regime.last_regime_change
            
        # Create new regime state
        self.current_regime = MarketRegime(
            volatility_regime=volatility_regime,
            trend_regime=trend_regime,
            current_session=current_session,
            volatility_percentile=vol_stats['percentile'],
            trend_strength=trend_stats['strength'],
            regime_confidence=confidence,
            regime_duration=regime_duration,
            last_regime_change=last_change
        )
        
        # Store in history
        self.regime_history.append(self.current_regime)
        
        return self.current_regime
        
    def _calculate_regime_confidence(self, vol_stats: Dict[str, float], trend_stats: Dict[str, float]) -> float:
        """Calculate confidence in current regime classification."""
        # Base confidence on how extreme the current values are
        vol_confidence = min(abs(vol_stats['percentile'] - 50) / 50, 1.0)
        trend_confidence = trend_stats['strength']
        
        # Combine confidences
        overall_confidence = (vol_confidence + trend_confidence) / 2
        return min(max(overall_confidence, 0.1), 0.9)  # Keep between 0.1 and 0.9
        
    def get_regime_features(self) -> Dict[str, float]:
        """Get regime features for RL state representation."""
        regime = self.current_regime
        
        # Session features (one-hot encoded)
        session_features = {
            'session_sydney': 1.0 if regime.current_session == TradingSession.SYDNEY else 0.0,
            'session_tokyo': 1.0 if regime.current_session == TradingSession.TOKYO else 0.0,
            'session_london': 1.0 if regime.current_session == TradingSession.LONDON else 0.0,
            'session_new_york': 1.0 if regime.current_session == TradingSession.NEW_YORK else 0.0,
            'session_london_ny': 1.0 if regime.current_session == TradingSession.OVERLAP_LONDON_NY else 0.0,
            'session_tokyo_london': 1.0 if regime.current_session == TradingSession.OVERLAP_TOKYO_LONDON else 0.0,
            'session_quiet': 1.0 if regime.current_session == TradingSession.QUIET else 0.0,
        }
        
        # Volatility regime features
        vol_features = {
            'vol_regime_low': 1.0 if regime.volatility_regime == VolatilityRegime.LOW else 0.0,
            'vol_regime_normal': 1.0 if regime.volatility_regime == VolatilityRegime.NORMAL else 0.0,
            'vol_regime_high': 1.0 if regime.volatility_regime == VolatilityRegime.HIGH else 0.0,
            'vol_regime_extreme': 1.0 if regime.volatility_regime == VolatilityRegime.EXTREME else 0.0,
            'vol_percentile': regime.volatility_percentile / 100.0,  # Normalize to [0, 1]
        }
        
        # Trend regime features
        trend_features = {
            'trend_strong_up': 1.0 if regime.trend_regime == TrendRegime.STRONG_UPTREND else 0.0,
            'trend_weak_up': 1.0 if regime.trend_regime == TrendRegime.WEAK_UPTREND else 0.0,
            'trend_sideways': 1.0 if regime.trend_regime == TrendRegime.SIDEWAYS else 0.0,
            'trend_weak_down': 1.0 if regime.trend_regime == TrendRegime.WEAK_DOWNTREND else 0.0,
            'trend_strong_down': 1.0 if regime.trend_regime == TrendRegime.STRONG_DOWNTREND else 0.0,
            'trend_strength': regime.trend_strength,
        }
        
        # Meta features
        meta_features = {
            'regime_confidence': regime.regime_confidence,
            'regime_duration': min(regime.regime_duration / 100.0, 1.0),  # Normalize
        }
        
        # Combine all features
        all_features = {}
        all_features.update(session_features)
        all_features.update(vol_features)
        all_features.update(trend_features)
        all_features.update(meta_features)
        
        return all_features
        
    def get_regime_summary(self) -> Dict[str, Any]:
        """Get comprehensive regime summary."""
        regime = self.current_regime
        
        return {
            'current_session': regime.current_session.value,
            'volatility_regime': regime.volatility_regime.value,
            'trend_regime': regime.trend_regime.value,
            'volatility_percentile': regime.volatility_percentile,
            'trend_strength': regime.trend_strength,
            'regime_confidence': regime.regime_confidence,
            'regime_duration': regime.regime_duration,
            'last_regime_change': regime.last_regime_change.isoformat(),
            'active_sessions': [s.value for s in self.session_detector.get_active_sessions(regime.last_regime_change)]
        }
        
    def get_session_adjusted_features(self, base_features: Dict[str, float]) -> Dict[str, float]:
        """Adjust features based on current trading session."""
        regime = self.current_regime
        session_info = self.session_detector.get_session_info(regime.current_session)
        
        if session_info is None:
            return base_features
            
        # Apply session multipliers
        adjusted_features = base_features.copy()
        
        # Adjust volatility-related features
        vol_multiplier = session_info.typical_volatility_multiplier
        for key in adjusted_features:
            if 'volatility' in key.lower() or 'vol' in key.lower():
                adjusted_features[key] *= vol_multiplier
                
        # Adjust volume-related features
        volume_multiplier = session_info.typical_volume_multiplier
        for key in adjusted_features:
            if 'volume' in key.lower():
                adjusted_features[key] *= volume_multiplier
                
        return adjusted_features
        
    def should_adjust_strategy(self) -> Tuple[bool, str]:
        """Determine if trading strategy should be adjusted based on regime."""
        regime = self.current_regime
        
        # High volatility regimes
        if regime.volatility_regime in [VolatilityRegime.HIGH, VolatilityRegime.EXTREME]:
            return True, "reduce_position_size_high_volatility"
            
        # Strong trend regimes
        if regime.trend_regime in [TrendRegime.STRONG_UPTREND, TrendRegime.STRONG_DOWNTREND]:
            return True, "increase_trend_following"
            
        # Quiet sessions
        if regime.current_session == TradingSession.QUIET:
            return True, "reduce_activity_quiet_session"
            
        # High activity overlap sessions
        if regime.current_session in [TradingSession.OVERLAP_LONDON_NY, TradingSession.OVERLAP_TOKYO_LONDON]:
            return True, "increase_activity_overlap_session"
            
        return False, "no_adjustment_needed"
        
    def get_regime_history(self, lookback_periods: int = 100) -> List[MarketRegime]:
        """Get recent regime history."""
        return list(self.regime_history)[-lookback_periods:]