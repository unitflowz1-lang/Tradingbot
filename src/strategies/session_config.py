"""
Session-Based Market Regime & Filter Manager
Adjusts entry thresholds based on trading session characteristics
"""

from datetime import datetime, time
from typing import Dict, Tuple, Optional

class SessionConfig:
    """Configuration for different trading sessions"""
    
    # Session time windows (UTC)
    ASIA_OPEN = time(0, 0)      # 00:00 UTC = Tokyo 09:00
    LONDON_OPEN = time(8, 0)    # 08:00 UTC = London 08:00
    LONDON_CLOSE = time(17, 0)  # 17:00 UTC = London 17:00
    NY_OPEN = time(13, 0)       # 13:00 UTC = NY 08:00
    NY_CLOSE = time(22, 0)      # 22:00 UTC = NY 17:00
    
    # Session quality tiers (relative to standard 0.75)
    TIER_ELITE = 0.78      # London/NY overlap (tightest, best signals)
    TIER_HIGH = 0.76       # London or NY main hours
    TIER_BALANCED = 0.75   # Standard (baseline)
    TIER_RELAXED = 0.73    # Asia session (more volatile)

class SessionBasedFilters:
    """Applies session-aware filtering to trading signals"""
    
    def __init__(self):
        self.session_config = SessionConfig()
        
    def get_session_name(self, utc_hour: int) -> str:
        """Identify current trading session"""
        if 0 <= utc_hour < 8:
            return "ASIA"
        elif 8 <= utc_hour < 13:
            return "LONDON"
        elif 13 <= utc_hour < 17:
            return "LONDON_NY_OVERLAP"
        elif 17 <= utc_hour < 22:
            return "NY"
        else:  # 22-24
            return "ASIA"
    
    def get_quality_threshold_adjustment(self, utc_hour: int) -> float:
        """Get quality threshold adjustment for session
        
        Returns multiplier to apply to base quality threshold
        Example: base 0.75 * 1.02 = 0.765 (slight increase in elite session)
        """
        session = self.get_session_name(utc_hour)
        
        adjustments = {
            "LONDON_NY_OVERLAP": 1.02,      # +2% stricter (elite signals only)
            "LONDON": 1.005,                # +0.5% slightly stricter
            "NY": 1.005,                    # +0.5% slightly stricter
            "ASIA": 0.985,                  # -1.5% slightly relaxed
        }
        
        return adjustments.get(session, 1.0)
    
    def get_adx_threshold_adjustment(self, utc_hour: int) -> float:
        """Get ADX threshold adjustment for session
        
        Returns multiplier to apply to base ADX threshold
        London/NY Overlap needs stronger trends (higher ADX)
        Asia can work with weaker trends (lower ADX)
        """
        session = self.get_session_name(utc_hour)
        
        adjustments = {
            "LONDON_NY_OVERLAP": 1.03,      # +3% stricter trend requirement
            "LONDON": 1.01,                 # +1% slightly stricter
            "NY": 1.01,                     # +1% slightly stricter
            "ASIA": 0.98,                   # -2% slightly relaxed
        }
        
        return adjustments.get(session, 1.0)
    
    def get_ml_confidence_threshold(self, utc_hour: int) -> float:
        """Get ML confidence threshold adjustment for session"""
        session = self.get_session_name(utc_hour)
        
        thresholds = {
            "LONDON_NY_OVERLAP": 0.67,     # Highest: most correlated hours
            "LONDON": 0.65,                 # High: established trend hours
            "NY": 0.65,                     # High: established trend hours
            "ASIA": 0.61,                   # Standard: higher volatility
        }
        
        return thresholds.get(session, 0.63)
    
    def apply_session_filters(self, 
                            symbol: str, 
                            direction: str,
                            base_quality_threshold: float,
                            base_adx_threshold: float,
                            base_ml_threshold: float,
                            utc_hour: int) -> Dict[str, float]:
        """Apply session-specific filter adjustments
        
        Args:
            symbol: Currency pair (EUR/USD, GBP/USD, etc.)
            direction: LONG or SHORT
            base_quality_threshold: Base signal quality threshold
            base_adx_threshold: Base ADX threshold
            base_ml_threshold: Base ML confidence threshold
            utc_hour: Current hour in UTC (0-23)
            
        Returns:
            Dictionary with adjusted thresholds
        """
        session = self.get_session_name(utc_hour)
        
        # Get adjustments
        quality_adj = self.get_quality_threshold_adjustment(utc_hour)
        adx_adj = self.get_adx_threshold_adjustment(utc_hour)
        ml_threshold = self.get_ml_confidence_threshold(utc_hour)
        
        # Apply adjustments
        adjusted_quality = base_quality_threshold * quality_adj
        adjusted_adx = base_adx_threshold * adx_adj
        
        return {
            'session': session,
            'quality_threshold': min(adjusted_quality, 0.82),  # Cap at elite
            'adx_threshold': min(adjusted_adx, 32),             # Cap at max ADX
            'ml_confidence': ml_threshold,
            'quality_adj': quality_adj,
            'adx_adj': adx_adj,
        }
    
    def get_session_summary(self, utc_hour: int) -> str:
        """Get human-readable session summary"""
        session = self.get_session_name(utc_hour)
        quality_adj = self.get_quality_threshold_adjustment(utc_hour)
        
        tier = "ELITE" if quality_adj > 1.03 else \
               "HIGH" if quality_adj > 1.0 else \
               "BALANCED" if quality_adj >= 0.99 else "RELAXED"
        
        return f"{session:20} | Quality Tier: {tier:8} | Adj: {quality_adj:.2f}x"

# Singleton instance
session_manager = SessionBasedFilters()

def apply_session_filtering(symbol: str, 
                           direction: str,
                           quality_threshold: float,
                           adx_threshold: float,
                           ml_confidence: float,
                           utc_hour: int) -> Dict[str, float]:
    """Apply session-based filtering to thresholds"""
    return session_manager.apply_session_filters(
        symbol, direction, quality_threshold, adx_threshold, ml_confidence, utc_hour
    )

def get_session_info(utc_hour: int) -> str:
    """Get session information for logging"""
    return session_manager.get_session_summary(utc_hour)
