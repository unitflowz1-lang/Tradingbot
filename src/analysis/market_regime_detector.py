"""
Market Regime Detector Module - Session-Aware & Dynamic
File: src/analysis/market_regime_detector.py
"""

import logging
from typing import Dict, Any, Tuple, List, Optional
from datetime import datetime, timezone
from enum import Enum

logger = logging.getLogger(__name__)

class TradingSession(Enum):
    SYDNEY = "SYDNEY"
    TOKYO = "TOKYO"
    LONDON = "LONDON"
    NEW_YORK = "NEW_YORK"
    OVERLAP_LONDON_NY = "LONDON_NY_OVERLAP"
    OVERLAP_TOKYO_LONDON = "TOKYO_LONDON_OVERLAP"
    LONDON_OPEN = "LONDON_OPEN"
    QUIET = "QUIET"

class MarketRegimeDetector:
    """
    Detects current market regime based on session-aware ADX and volatility.
    
    Now adapts thresholds to Asia, London, and New York sessions instead of hard cutoffs.
    """
    
    def __init__(self, atr_window: int = 14, adx_window: int = 14):
        self.atr_window = atr_window
        self.adx_window = adx_window
        
        # Session definitions (UTC hours)
        self.session_hours = {
            TradingSession.SYDNEY: (22, 7),
            TradingSession.TOKYO: (0, 9),
            TradingSession.LONDON: (8, 17),
            TradingSession.NEW_YORK: (13, 22)
        }

    def detect_session(self, timestamp: Optional[datetime] = None) -> TradingSession:
        """Detect current trading session based on UTC hour."""
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)
        elif timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        
        hour = timestamp.hour
        
        # Check overlaps first
        if 13 <= hour <= 16:
            return TradingSession.OVERLAP_LONDON_NY
        if 8 <= hour < 9: # 8:00 to 8:59 UTC
            return TradingSession.LONDON_OPEN
        if 8 <= hour <= 9:
            return TradingSession.OVERLAP_TOKYO_LONDON
        
        # Check major sessions
        if 8 <= hour <= 17:
            return TradingSession.LONDON
        if 13 <= hour <= 22:
            return TradingSession.NEW_YORK
        if 0 <= hour <= 9:
            return TradingSession.TOKYO
        if hour >= 22 or hour <= 7:
            return TradingSession.SYDNEY
            
        return TradingSession.QUIET

    def get_dynamic_thresholds(self, session: TradingSession) -> Dict[str, float]:
        """Get session-specific thresholds for signal quality."""
        # Thresholds adapt to session characteristics
        # Asia is lower intensity, London/NY are higher intensity
        thresholds = {
            TradingSession.TOKYO: {
                'adx_strong': 18,    # Lower ADX required for "strong" in Asia
                'adx_weak': 10.0,
                'rsi_ob': 75,       # Wider RSI bands for ranging Asia
                'rsi_os': 25,
                'vol_mult': 0.8     # Expect lower volatility
            },
            TradingSession.SYDNEY: {
                'adx_strong': 15,
                'adx_weak': 9.0,
                'rsi_ob': 80,
                'rsi_os': 20,
                'vol_mult': 0.7
            },
            TradingSession.LONDON: {
                'adx_strong': 25,
                'adx_weak': 12.0,
                'rsi_ob': 75,
                'rsi_os': 25,
                'vol_mult': 1.2
            },
            TradingSession.NEW_YORK: {
                'adx_strong': 24,
                'adx_weak': 12.0,
                'rsi_ob': 75,
                'rsi_os': 25,
                'vol_mult': 1.1
            },
            TradingSession.OVERLAP_LONDON_NY: {
                'adx_strong': 28,    # Higher standard during most active period
                'adx_weak': 15.0,
                'rsi_ob': 65,       # Tighter RSI bands for momentum plays
                'rsi_os': 35,
                'vol_mult': 1.5
            },
            TradingSession.OVERLAP_TOKYO_LONDON: {
                'adx_strong': 22,
                'adx_weak': 11.0,
                'rsi_ob': 72,
                'rsi_os': 25,
                'vol_mult': 1.0
            },
            TradingSession.LONDON_OPEN: {
                'adx_strong': 20,    # Lower ADX for breakout detection
                'adx_weak': 10.0,
                'rsi_ob': 75,       # Wider RSI for initial volatility
                'rsi_os': 25,
                'vol_mult': 1.4      # High volatility expectation
            },
            TradingSession.QUIET: {
                'adx_strong': 30,
                'adx_weak': 14.0,
                'rsi_ob': 85,
                'rsi_os': 15,
                'vol_mult': 0.5
            }
        }
        return thresholds.get(session, thresholds[TradingSession.LONDON])

    def get_regime(self, data: Dict[str, Any], session: Optional[TradingSession] = None) -> str:
        """Determine market trend regime with session awareness."""
        if session is None:
            session = self.detect_session()
            
        thresholds = self.get_dynamic_thresholds(session)
        adx = data.get('adx', 15)
        atr = data.get('atr', 0)
        atr_mean = data.get('atr_mean', atr)
        
        if adx >= thresholds['adx_strong']:
            return 'TRENDING'
        elif atr < (atr_mean * 0.75):
            return 'LOW_VOLATILITY'
        else:
            return 'RANGING'

    def get_detailed_regime_label(self, data: Dict[str, Any], session: Optional[TradingSession] = None) -> str:
        """
        Classifies current environment into distinct functional labels:
        TRENDING, RANGING, HIGH_VOLATILITY, LOW_LIQUIDITY, NEUTRAL
        """
        if session is None:
            session = self.detect_session()
            
        thresholds = self.get_dynamic_thresholds(session)
        
        # 1. Check Distress/Liquidity First
        spread = data.get('spread', 0)
        volume = data.get('volume', 999999)
        vol_20 = data.get('vol_20_percentile', 0)
        
        if spread > 0.0003 or (volume < vol_20 and volume > 0): 
             return 'LOW_LIQUIDITY'
             
        # 2. Check Volatility
        atr = data.get('atr', 0)
        atr_80 = data.get('atr_80_percentile', 9999)
        if atr > atr_80:
             return 'HIGH_VOLATILITY'
             
        # 3. Check Trend
        adx = data.get('adx', 15)
        if adx >= thresholds['adx_strong']:
             return 'TRENDING'
             
        # 4. Check Range
        if adx <= thresholds['adx_weak']:
             return 'RANGING'
             
        return 'NEUTRAL'

    def get_volatility_regime(self, data: Dict[str, Any], session: Optional[TradingSession] = None) -> str:
        """Determine volatility regime with session awareness."""
        atr = data.get('atr', 0)
        atr_20_percentile = data.get('atr_20_percentile', 0)
        atr_80_percentile = data.get('atr_80_percentile', 0)
        
        # Optional: Adjust percentiles based on session volume multiplier
        # but usually percentile rank is already self-normalizing
        
        if atr < atr_20_percentile:
            return 'LOW_VOL'
        elif atr > atr_80_percentile:
            return 'HIGH_VOL'
        else:
            return 'NORMAL_VOL'

    def get_action(self, regime: str, vol_regime: str, signal_quality: float = 0.0) -> Dict[str, Any]:
        """
        Determine action with a more permissive approach for high-quality signals.
        
        Args:
            regime: Trend regime
            vol_regime: Volatility regime
            signal_quality: 0.0 to 1.0 (or 0-100) signal score
        """
        # Convert signal_quality to 0-1 range if it's 0-100
        quality = signal_quality / 100.0 if signal_quality > 1.0 else signal_quality
        
        # High quality override: If signal is >= 70%, we are more permissive
        is_high_quality = quality >= 0.70
        
        actions = {
            ('TRENDING', 'NORMAL_VOL'): {'trade': True, 'size_multiplier': 1.5, 'reason': 'Optimal Trending'},
            ('TRENDING', 'LOW_VOL'): {'trade': True, 'size_multiplier': 2.0, 'reason': 'Ideal Trending R/R'},
            ('TRENDING', 'HIGH_VOL'): {'trade': True, 'size_multiplier': 0.75, 'reason': 'Trending but volatile'},
            
            ('RANGING', 'NORMAL_VOL'): {'trade': True, 'size_multiplier': 0.75, 'reason': 'Standard Ranging'},
            ('RANGING', 'LOW_VOL'): {
                'trade': True if is_high_quality else False,
                'size_multiplier': 0.8 if is_high_quality else 0,
                'reason': 'Ranging + Low vol (High quality only)'
            },
            ('RANGING', 'HIGH_VOL'): {
                'trade': True if is_high_quality else False,
                'size_multiplier': 0.6 if is_high_quality else 0,
                'reason': 'Ranging + High vol (High quality only)'
            },
            
            ('LOW_VOLATILITY', 'NORMAL_VOL'): {
                'trade': True if is_high_quality and quality >= 0.85 else False,
                'size_multiplier': 0.5 if is_high_quality else 0,
                'reason': 'Quiet but exceptional signal'
            },
            ('LOW_VOLATILITY', 'LOW_VOL'): {'trade': False, 'size_multiplier': 0, 'reason': 'Consolidating'},
            ('LOW_VOLATILITY', 'HIGH_VOL'): {'trade': False, 'size_multiplier': 0, 'reason': 'Whipsaw risk'}
        }
        
        result = actions.get((regime, vol_regime), {'trade': False, 'size_multiplier': 0, 'reason': 'Unknown'})
        
        # Final override for very high quality continuation signals
        if is_high_quality and not result['trade'] and regime != 'LOW_VOLATILITY':
             result = {'trade': True, 'size_multiplier': 0.7, 'reason': 'High quality continuation override'}
             
        return result

    def get_regime_statistics(self, data: Dict[str, Any], timestamp: Optional[datetime] = None) -> Dict[str, Any]:
        """Detailed regime stats with session info."""
        session = self.detect_session(timestamp)
        regime = self.get_regime(data, session)
        vol_regime = self.get_volatility_regime(data, session)
        
        # Use a dummy high quality for basic stats if not provided
        action = self.get_action(regime, vol_regime, signal_quality=data.get('signal_quality', 0.5))
        
        return {
            'session': session.value,
            'trend_regime': regime,
            'volatility_regime': vol_regime,
            'detailed_label': self.get_detailed_regime_label(data, session),
            'adx': data.get('adx', 0),
            'atr': data.get('atr', 0),
            'should_trade': action['trade'],
            'size_multiplier': action['size_multiplier'],
            'reason': action['reason']
        }


# Example usage (for testing):
if __name__ == "__main__":
    # Create sample market data
    sample_data = {
        'adx': 32,                  # Strong trend
        'atr': 50,
        'atr_mean': 45,
        'atr_20_percentile': 35,
        'atr_80_percentile': 60,
    }
    
    # Create detector
    detector = MarketRegimeDetector()
    
    # Get regime
    regime = detector.get_regime(sample_data)
    vol_regime = detector.get_volatility_regime(sample_data)
    action = detector.get_action(regime, vol_regime)
    
    print(f"Regime: {regime}")
    print(f"Volatility: {vol_regime}")
    print(f"Action: {action}")
    print(f"\nDetailed Stats:")
    stats = detector.get_regime_statistics(sample_data)
    for key, value in stats.items():
        print(f"  {key}: {value}")
    
    # Show stops adjustment
    stops = detector.get_volatility_adjusted_stops(50, vol_regime)
    print(f"\nAdjusted Stops for {vol_regime}:")
    for key, value in stops.items():
        print(f"  {key}: {value:.2f}×ATR")
