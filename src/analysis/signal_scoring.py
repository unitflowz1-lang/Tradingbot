"""
Signal Scoring Module - READY TO USE
File: src/analysis/signal_scoring.py

Copy this entire file into your project.
No modifications needed - just copy-paste.
"""

import logging
from typing import Tuple, Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


from src.analysis.market_regime_detector import MarketRegimeDetector, TradingSession

class SignalScorer:
    """
    Calculates signal quality score based on multiple factors with session awareness.
    
    Scoring breakdown (adaptive):
    - 30%: Trend Score (Session-aware ADX)
    - 25%: Confluence Score (Indicator agreement)
    - 20%: Volatility Score (Session-aware ATR)
    - 15%: RSI Extremity Score (Session-aware thresholds)
    - 10%: Volume Confirmation
    """
    
    def __init__(self):
        self.regime_detector = MarketRegimeDetector()

    def calculate_score(self, analysis_data: Dict[str, Any], timestamp: Optional[datetime] = None) -> float:
        """
        Calculate composite signal quality score with session awareness.
        """
        session = self.regime_detector.detect_session(timestamp)
        thresholds = self.regime_detector.get_dynamic_thresholds(session)
        
        trend_score = self._calculate_trend_score(analysis_data, thresholds)
        confluence_score = self._calculate_confluence_score(analysis_data)
        volatility_score = self._calculate_volatility_score(analysis_data, thresholds)
        rsi_score = self._calculate_rsi_score(analysis_data, thresholds)
        volume_score = self._calculate_volume_score(analysis_data)
        
        total_score = (
            trend_score * 0.30 +
            confluence_score * 0.25 +
            volatility_score * 0.20 +
            rsi_score * 0.15 +
            volume_score * 0.10
        )
        
        return min(100, max(0, total_score))
    
    def _calculate_trend_score(self, data: Dict[str, Any], thresholds: Dict[str, float]) -> float:
        """Calculate trend strength score based on session-aware ADX."""
        adx = data.get('adx', 0)
        strong = thresholds['adx_strong']
        weak = thresholds['adx_weak']
        
        if adx >= strong:
            return 100
        elif adx >= (strong + weak) / 2:
            return 85
        elif adx >= weak:
            return 60
        elif adx >= weak * 0.7:
            return 40
        else:
            return 20
    
    def _calculate_confluence_score(self, data: Dict[str, Any]) -> float:
        """Calculate how many indicators support the signal."""
        support_count = 0
        factors = ['trend_aligned', 'rsi_extreme', 'volume_confirmed', 'ma_bullish', 'pattern_bullish']
        
        for factor in factors:
            if data.get(factor, False):
                support_count += 1
        
        return (support_count / len(factors)) * 100
    
    def _calculate_volatility_score(self, data: Dict[str, Any], thresholds: Dict[str, float]) -> float:
        """Check if volatility is appropriate, adjusting for session baseline."""
        atr = data.get('atr', 0)
        atr_mean = data.get('atr_mean', 1)
        vol_mult = thresholds['vol_mult']
        
        if atr_mean == 0:
            return 50
        
        # Adjust expected ratio based on session multiplier
        ratio = atr / (atr_mean * vol_mult)
        
        if 0.8 <= ratio <= 1.2:
            return 100
        elif 0.6 <= ratio <= 1.5:
            return 85
        elif 0.4 <= ratio <= 2.2:
            return 60
        else:
            return 30
    
    def _calculate_rsi_score(self, data: Dict[str, Any], thresholds: Dict[str, float]) -> float:
        """Score RSI extremity using session-aware boundaries (Symmetric logic - FIX #7)."""
        rsi = data.get('rsi', 50)
        ob = thresholds.get('rsi_ob', 70)
        
        # ===== FIX #7: RSI STANDARDIZATION - SYMMETRIC ABSOLUTE LOGIC =====
        # Handle long/short asymmetry using distance from the 50 indicator midpoint
        dist_from_mid = abs(rsi - 50)
        threshold_dist = ob - 50
        
        if dist_from_mid >= threshold_dist:
            return 100
        elif dist_from_mid >= threshold_dist - 10:
            return 75
        elif dist_from_mid >= threshold_dist - 20:
            return 50
        else:
            return 25
    
    def _calculate_volume_score(self, data: Dict[str, Any]) -> float:
        """Score volume confirmation."""
        volume = data.get('volume', 0)
        volume_mean = data.get('volume_mean', 1)
        
        if volume_mean == 0:
            return 50
        
        ratio = volume / volume_mean
        
        if ratio > 1.5:
            return 100
        elif ratio > 1.0:
            return 85
        elif ratio > 0.7:
            return 60
        else:
            return 30


class SignalFilterer:
    """
    Filters signals based on quality score threshold.
    Also adjusts position size based on signal quality.
    """
    
    def __init__(self, min_score: float = 65, max_score: float = 100):
        """
        Initialize signal filterer.
        
        Args:
            min_score: Minimum quality score to trade (0-100, default 65)
            max_score: Maximum quality score (default 100)
        """
        self.min_score = min_score
        self.max_score = max_score
        self.scorer = SignalScorer()
        self.trades_accepted = 0
        self.trades_rejected = 0
    
    def should_trade_signal(self, signal: Dict[str, Any], 
                           analysis_data: Dict[str, Any],
                           timestamp: Optional[datetime] = None) -> Tuple[bool, float, str]:
        """
        Determine if signal should be traded based on quality.
        """
        score = self.scorer.calculate_score(analysis_data, timestamp)
        
        if score >= self.min_score:
            self.trades_accepted += 1
            return True, score, f"Score: {score:.1f}/100 (EXCELLENT - Accepted)"
        elif score >= self.min_score - 15:
            self.trades_accepted += 1
            return True, score, f"Score: {score:.1f}/100 (GOOD - Accepted)"
        else:
            self.trades_rejected += 1
            return False, score, f"Score: {score:.1f}/100 (REJECTED - Too low quality)"
    
    def adjust_position_size(self, score: float, base_size: float) -> float:
        """
        Adjust position size based on signal quality.
        
        High quality (80-100): 1.5× base size
        Good quality (65-79): 1.0× base size
        Acceptable quality (50-64): 0.75× base size
        Low quality (0-49): 0.5× base size
        
        Args:
            score: Signal quality score (0-100)
            base_size: Base position size (lot size)
        
        Returns:
            Adjusted position size
        """
        if score >= 80:
            multiplier = 1.5  # Excellent - increase size
        elif score >= 65:
            multiplier = 1.0  # Good - keep normal
        elif score >= 50:
            multiplier = 0.75  # Acceptable - reduce slightly
        else:
            multiplier = 0.5  # Low quality - reduce significantly
        
        return base_size * multiplier
    
    def get_score_breakdown(self, analysis_data: Dict[str, Any]) -> Dict[str, float]:
        """
        Get detailed breakdown of score components.
        Useful for debugging and optimization.
        
        Returns:
            Dict with individual component scores
        """
        return {
            'trend_score': self.scorer._calculate_trend_score(analysis_data),
            'confluence_score': self.scorer._calculate_confluence_score(analysis_data),
            'volatility_score': self.scorer._calculate_volatility_score(analysis_data),
            'rsi_score': self.scorer._calculate_rsi_score(analysis_data),
            'volume_score': self.scorer._calculate_volume_score(analysis_data),
            'total_score': self.scorer.calculate_score(analysis_data),
        }
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get statistics on signal filtering.
        
        Returns:
            Dict with acceptance rate, rejection rate, etc.
        """
        total = self.trades_accepted + self.trades_rejected
        acceptance_rate = (self.trades_accepted / total * 100) if total > 0 else 0
        
        return {
            'total_signals': total,
            'accepted': self.trades_accepted,
            'rejected': self.trades_rejected,
            'acceptance_rate': f"{acceptance_rate:.1f}%",
        }


# Example usage (for testing):
if __name__ == "__main__":
    # Create sample analysis data
    sample_data = {
        'adx': 28,  # Good trend
        'trend_aligned': True,
        'rsi_extreme': True,
        'volume_confirmed': True,
        'ma_bullish': True,
        'pattern_bullish': False,
        'atr': 45,
        'atr_mean': 40,  # Normal volatility
        'rsi': 25,  # Oversold (extreme)
        'volume': 150000,
        'volume_mean': 120000,  # Above average
    }
    
    # Test scoring
    filterer = SignalFilterer(min_score=65)
    should_trade, score, reason = filterer.should_trade_signal({}, sample_data)
    
    print(f"Should trade: {should_trade}")
    print(f"Score: {score:.1f}")
    print(f"Reason: {reason}")
    print(f"\nScore breakdown: {filterer.get_score_breakdown(sample_data)}")
    
    # Test position sizing
    adjusted_size = filterer.adjust_position_size(score, base_size=1.0)
    print(f"Adjusted position size: {adjusted_size:.2f} lots")
