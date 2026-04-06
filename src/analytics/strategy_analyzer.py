"""Strategy analysis tools for identifying improvement opportunities"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Any, Tuple


class InsightType(Enum):
    """Types of strategy insights"""
    PERFORMANCE = "performance"
    RISK = "risk"
    TIMING = "timing"
    MARKET_CONDITIONS = "market_conditions"
    SIGNAL_QUALITY = "signal_quality"
    OPTIMIZATION = "optimization"


@dataclass
class StrategyInsight:
    """Individual strategy insight with recommendations"""
    insight_type: InsightType
    title: str
    description: str
    impact_score: float  # 0.0 to 1.0 (severity/importance)
    confidence: float    # 0.0 to 1.0 (confidence in insight)
    recommendation: str
    supporting_data: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert insight to dictionary"""
        return {
            'insight_type': self.insight_type.value,
            'title': self.title,
            'description': self.description,
            'impact_score': self.impact_score,
            'confidence': self.confidence,
            'recommendation': self.recommendation,
            'supporting_data': self.supporting_data,
            'timestamp': self.timestamp.isoformat()
        }


@dataclass
class StrategyRecommendation:
    """Actionable strategy recommendation"""
    category: str
    priority: str  # HIGH, MEDIUM, LOW
    title: str
    description: str
    expected_impact: str
    implementation_effort: str  # LOW, MEDIUM, HIGH
    supporting_insights: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert recommendation to dictionary"""
        return {
            'category': self.category,
            'priority': self.priority,
            'title': self.title,
            'description': self.description,
            'expected_impact': self.expected_impact,
            'implementation_effort': self.implementation_effort,
            'supporting_insights': self.supporting_insights
        }


class StrategyAnalyzer:
    """Advanced strategy analysis for identifying improvement opportunities"""
    
    def __init__(self, min_trades_for_analysis: int = 10):
        self.min_trades_for_analysis = min_trades_for_analysis
        self.logger = logging.getLogger(__name__)
        
        # Analysis thresholds
        self.thresholds = {
            'low_win_rate': 0.4,
            'high_drawdown': 0.15,
            'low_profit_factor': 1.2,
            'signal_accuracy': 0.6,
            'execution_rate': 0.8
        }
    
    def analyze_strategy_performance(
        self,
        trades_data: List[Dict[str, Any]],
        signals_data: Optional[List[Dict[str, Any]]] = None,
        market_data: Optional[List] = None,
        analysis_period: Optional[Tuple[datetime, datetime]] = None
    ) -> List[StrategyInsight]:
        """Comprehensive strategy performance analysis"""
        insights = []
        
        if len(trades_data) < self.min_trades_for_analysis:
            insights.append(StrategyInsight(
                insight_type=InsightType.PERFORMANCE,
                title="Insufficient Trade Data",
                description=f"Only {len(trades_data)} trades available. Need at least {self.min_trades_for_analysis} for meaningful analysis.",
                impact_score=0.3,
                confidence=1.0,
                recommendation="Continue trading to gather more data for analysis."
            ))
            return insights
        
        # Basic win rate analysis
        winning_trades = sum(1 for trade in trades_data if trade.get('pnl', 0) > 0)
        total_trades = len(trades_data)
        win_rate = winning_trades / total_trades if total_trades > 0 else 0
        
        if win_rate < self.thresholds['low_win_rate']:
            insights.append(StrategyInsight(
                insight_type=InsightType.PERFORMANCE,
                title="Low Win Rate",
                description=f"Win rate of {win_rate:.1%} is below optimal threshold",
                impact_score=0.8,
                confidence=0.9,
                recommendation="Review signal generation criteria and consider tightening entry conditions",
                supporting_data={'win_rate': win_rate, 'winning_trades': winning_trades, 'total_trades': total_trades}
            ))
        elif win_rate >= 0.6:  # Good win rate
            insights.append(StrategyInsight(
                insight_type=InsightType.PERFORMANCE,
                title="Strong Win Rate Performance",
                description=f"Win rate of {win_rate:.1%} indicates good strategy performance",
                impact_score=0.6,
                confidence=0.8,
                recommendation="Continue current approach while monitoring for consistency",
                supporting_data={'win_rate': win_rate, 'winning_trades': winning_trades, 'total_trades': total_trades}
            ))
        else:  # Moderate win rate (between low threshold and 60%)
            insights.append(StrategyInsight(
                insight_type=InsightType.PERFORMANCE,
                title="Moderate Win Rate Performance",
                description=f"Win rate of {win_rate:.1%} is acceptable but has room for improvement",
                impact_score=0.4,
                confidence=0.7,
                recommendation="Consider optimizing entry criteria to improve win rate",
                supporting_data={'win_rate': win_rate, 'winning_trades': winning_trades, 'total_trades': total_trades}
            ))
        
        # Analyze profit factor
        total_profits = sum(trade.get('pnl', 0) for trade in trades_data if trade.get('pnl', 0) > 0)
        total_losses = abs(sum(trade.get('pnl', 0) for trade in trades_data if trade.get('pnl', 0) < 0))
        profit_factor = total_profits / total_losses if total_losses > 0 else float('inf')
        
        if profit_factor < self.thresholds['low_profit_factor']:
            insights.append(StrategyInsight(
                insight_type=InsightType.RISK,
                title="Low Profit Factor",
                description=f"Profit factor of {profit_factor:.2f} suggests losses are too large relative to wins",
                impact_score=0.7,
                confidence=0.8,
                recommendation="Consider tighter stop losses or better exit strategies",
                supporting_data={'profit_factor': profit_factor, 'total_profits': total_profits, 'total_losses': total_losses}
            ))
        
        return insights
    
    def generate_recommendations(self, insights: List[StrategyInsight]) -> List[StrategyRecommendation]:
        """Generate actionable recommendations based on insights"""
        recommendations = []
        
        for insight in insights:
            if "Low Win Rate" in insight.title:
                recommendations.append(StrategyRecommendation(
                    category="Signal Quality",
                    priority="HIGH",
                    title="Improve Signal Filtering",
                    description="Implement additional filters to improve signal quality and win rate",
                    expected_impact="Increase win rate by 10-15%",
                    implementation_effort="MEDIUM",
                    supporting_insights=[insight.title]
                ))
        
        return recommendations
    
    def identify_optimization_opportunities(
        self,
        trades_data: List[Dict[str, Any]],
        signals_data: Optional[List[Dict[str, Any]]] = None
    ) -> List[StrategyInsight]:
        """Identify specific optimization opportunities"""
        return []  # Simplified implementation