"""
Trade Attribution and Analysis System

This module provides detailed trade attribution analysis for RL agent decisions,
strategy performance decomposition, and market regime analysis.
"""

from typing import Dict, List, Any, Optional, Tuple, Union
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from collections import defaultdict, deque
import json
from pathlib import Path
from dataclasses import dataclass, asdict
from enum import Enum
import logging

from .logger import RLLogger
from .performance_tracker import PerformanceMetrics, TradeRecord
from ..agents.base import RLAgent
from ...models import MarketData, TradingSignal, Direction


class MarketRegime(Enum):
    """Market regime classifications."""
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGING = "ranging"
    HIGH_VOLATILITY = "high_volatility"
    LOW_VOLATILITY = "low_volatility"
    BREAKOUT = "breakout"
    REVERSAL = "reversal"


class AttributionFactor(Enum):
    """Attribution factors for trade analysis."""
    MARKET_DIRECTION = "market_direction"
    VOLATILITY = "volatility"
    TECHNICAL_INDICATORS = "technical_indicators"
    PORTFOLIO_STATE = "portfolio_state"
    RISK_MANAGEMENT = "risk_management"
    TIMING = "timing"
    POSITION_SIZING = "position_sizing"
    MARKET_MICROSTRUCTURE = "market_microstructure"


@dataclass
class TradeAttribution:
    """Detailed attribution analysis for a single trade."""
    trade_id: str
    agent_id: str
    symbol: str
    
    # Trade details
    entry_time: datetime
    exit_time: Optional[datetime]
    direction: Direction
    entry_price: float
    exit_price: Optional[float]
    position_size: float
    pnl: Optional[float]
    
    # Market context
    market_regime: MarketRegime
    volatility_percentile: float
    trend_strength: float
    
    # Attribution factors (contribution to P&L)
    factor_contributions: Dict[AttributionFactor, float]
    
    # Agent decision context
    state_vector: np.ndarray
    action_probabilities: Optional[np.ndarray]
    q_values: Optional[np.ndarray]
    confidence_score: float
    
    # Risk metrics
    risk_adjusted_return: float
    sharpe_contribution: float
    max_adverse_excursion: float
    max_favorable_excursion: float
    
    # Timing analysis
    entry_timing_score: float
    exit_timing_score: float
    hold_duration: Optional[float]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = asdict(self)
        # Convert numpy arrays to lists
        if self.state_vector is not None:
            result['state_vector'] = self.state_vector.tolist()
        if self.action_probabilities is not None:
            result['action_probabilities'] = self.action_probabilities.tolist()
        if self.q_values is not None:
            result['q_values'] = self.q_values.tolist()
        # Convert enums to strings
        result['market_regime'] = self.market_regime.value
        result['factor_contributions'] = {
            factor.value: contrib for factor, contrib in self.factor_contributions.items()
        }
        return result


@dataclass
class StrategyDecomposition:
    """Performance decomposition analysis for a strategy."""
    strategy_id: str
    analysis_period: Tuple[datetime, datetime]
    
    # Overall performance
    total_return: float
    risk_adjusted_return: float
    
    # Factor contributions to return
    factor_returns: Dict[AttributionFactor, float]
    factor_sharpe_ratios: Dict[AttributionFactor, float]
    factor_hit_rates: Dict[AttributionFactor, float]
    
    # Regime-based performance
    regime_performance: Dict[MarketRegime, PerformanceMetrics]
    regime_exposure: Dict[MarketRegime, float]
    
    # Skill vs luck analysis
    skill_score: float
    luck_component: float
    statistical_significance: float
    
    # Consistency metrics
    monthly_returns: List[float]
    return_consistency: float
    drawdown_consistency: float
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = asdict(self)
        # Convert enum keys to strings
        result['factor_returns'] = {
            factor.value: ret for factor, ret in self.factor_returns.items()
        }
        result['factor_sharpe_ratios'] = {
            factor.value: sr for factor, sr in self.factor_sharpe_ratios.items()
        }
        result['factor_hit_rates'] = {
            factor.value: hr for factor, hr in self.factor_hit_rates.items()
        }
        result['regime_performance'] = {
            regime.value: perf.to_dict() if hasattr(perf, 'to_dict') else asdict(perf)
            for regime, perf in self.regime_performance.items()
        }
        result['regime_exposure'] = {
            regime.value: exp for regime, exp in self.regime_exposure.items()
        }
        return result


class MarketRegimeDetector:
    """Detects and classifies market regimes."""
    
    def __init__(self, 
                 lookback_window: int = 50,
                 volatility_threshold: float = 0.02,
                 trend_threshold: float = 0.01):
        """
        Initialize regime detector.
        
        Args:
            lookback_window: Number of periods for regime analysis
            volatility_threshold: Threshold for high/low volatility classification
            trend_threshold: Threshold for trending vs ranging classification
        """
        self.lookback_window = lookback_window
        self.volatility_threshold = volatility_threshold
        self.trend_threshold = trend_threshold
        
    def detect_regime(self, price_data: List[float]) -> MarketRegime:
        """
        Detect current market regime based on price data.
        
        Args:
            price_data: Recent price data
            
        Returns:
            Detected market regime
        """
        if len(price_data) < self.lookback_window:
            return MarketRegime.RANGING
            
        prices = np.array(price_data[-self.lookback_window:])
        returns = np.diff(prices) / prices[:-1]
        
        # Calculate volatility
        volatility = np.std(returns)
        
        # Calculate trend strength
        trend_slope = np.polyfit(range(len(prices)), prices, 1)[0]
        trend_strength = abs(trend_slope) / np.mean(prices)
        
        # Detect breakouts (sudden volatility increase)
        recent_vol = np.std(returns[-10:]) if len(returns) >= 10 else volatility
        vol_ratio = recent_vol / volatility if volatility > 0 else 1.0
        
        # Classify regime
        if vol_ratio > 2.0:
            return MarketRegime.BREAKOUT
        elif volatility > self.volatility_threshold:
            if trend_strength > self.trend_threshold:
                return MarketRegime.TRENDING_UP if trend_slope > 0 else MarketRegime.TRENDING_DOWN
            else:
                return MarketRegime.HIGH_VOLATILITY
        elif trend_strength > self.trend_threshold:
            return MarketRegime.TRENDING_UP if trend_slope > 0 else MarketRegime.TRENDING_DOWN
        elif volatility < self.volatility_threshold / 2:
            return MarketRegime.LOW_VOLATILITY
        else:
            return MarketRegime.RANGING
    
    def get_regime_statistics(self, price_data: List[float]) -> Dict[str, float]:
        """Get detailed regime statistics."""
        if len(price_data) < self.lookback_window:
            return {}
            
        prices = np.array(price_data[-self.lookback_window:])
        returns = np.diff(prices) / prices[:-1]
        
        return {
            'volatility': np.std(returns),
            'trend_strength': abs(np.polyfit(range(len(prices)), prices, 1)[0]) / np.mean(prices),
            'skewness': float(pd.Series(returns).skew()),
            'kurtosis': float(pd.Series(returns).kurtosis()),
            'autocorrelation': float(pd.Series(returns).autocorr(lag=1)) if len(returns) > 1 else 0.0
        }


class TradeAttributionAnalyzer:
    """Analyzes trade attribution and performance decomposition."""
    
    def __init__(self, 
                 logger: Optional[RLLogger] = None,
                 save_dir: Optional[str] = None):
        """
        Initialize trade attribution analyzer.
        
        Args:
            logger: Logger instance
            save_dir: Directory to save analysis results
        """
        self.logger = logger or RLLogger("TradeAttributionAnalyzer")
        self.save_dir = Path(save_dir) if save_dir else Path("attribution_analysis")
        self.save_dir.mkdir(exist_ok=True)
        
        self.regime_detector = MarketRegimeDetector()
        self.trade_attributions: Dict[str, TradeAttribution] = {}
        self.strategy_decompositions: Dict[str, StrategyDecomposition] = {}
        self._trade_id_map: Dict[str, str] = {}  # Map trade hash to trade_id
    
    def _generate_trade_id(self, trade: TradeRecord) -> str:
        """Generate a unique trade ID for a trade record."""
        # Create a hash from trade details to ensure uniqueness
        trade_hash = f"{trade.agent_id}_{trade.entry_time}_{trade.entry_price}_{trade.position_size}"
        
        if trade_hash not in self._trade_id_map:
            trade_id = f"{trade.agent_id}_{trade.entry_time.strftime('%Y%m%d_%H%M%S')}_{abs(hash(trade_hash))%10000:04d}"
            self._trade_id_map[trade_hash] = trade_id
        
        return self._trade_id_map[trade_hash]
        
    def analyze_trade(self,
                     trade: TradeRecord,
                     agent: RLAgent,
                     market_data: List[MarketData],
                     state_vector: np.ndarray,
                     action_probabilities: Optional[np.ndarray] = None,
                     q_values: Optional[np.ndarray] = None) -> TradeAttribution:
        """
        Perform detailed attribution analysis for a trade.
        
        Args:
            trade: Trade record to analyze
            agent: RL agent that made the trade
            market_data: Market data context
            state_vector: State vector used for decision
            action_probabilities: Action probabilities from agent
            q_values: Q-values from agent (if applicable)
            
        Returns:
            Trade attribution analysis
        """
        try:
            # Extract price data for regime detection
            prices = [md.close for md in market_data[-100:]]  # Last 100 periods
            
            # Detect market regime
            regime = self.regime_detector.detect_regime(prices)
            regime_stats = self.regime_detector.get_regime_statistics(prices)
            
            # Calculate factor contributions
            factor_contributions = self._calculate_factor_contributions(
                trade, market_data, state_vector, regime_stats
            )
            
            # Calculate timing scores
            entry_timing_score = self._calculate_entry_timing_score(trade, market_data)
            exit_timing_score = self._calculate_exit_timing_score(trade, market_data)
            
            # Calculate risk metrics
            risk_metrics = self._calculate_trade_risk_metrics(trade, market_data)
            
            # Generate trade ID from trade details
            trade_id = self._generate_trade_id(trade)
            
            # Create attribution
            attribution = TradeAttribution(
                trade_id=trade_id,
                agent_id=agent.agent_id if hasattr(agent, 'agent_id') else trade.agent_id,
                symbol=trade.currency_pair,
                entry_time=trade.entry_time,
                exit_time=trade.exit_time,
                direction=Direction.LONG if trade.position_size > 0 else Direction.SHORT,
                entry_price=trade.entry_price,
                exit_price=trade.exit_price,
                position_size=abs(trade.position_size),
                pnl=trade.pnl,
                market_regime=regime,
                volatility_percentile=self._calculate_volatility_percentile(prices),
                trend_strength=regime_stats.get('trend_strength', 0.0),
                factor_contributions=factor_contributions,
                state_vector=state_vector,
                action_probabilities=action_probabilities,
                q_values=q_values,
                confidence_score=self._calculate_confidence_score(action_probabilities, q_values),
                risk_adjusted_return=risk_metrics['risk_adjusted_return'],
                sharpe_contribution=risk_metrics['sharpe_contribution'],
                max_adverse_excursion=risk_metrics['max_adverse_excursion'],
                max_favorable_excursion=risk_metrics['max_favorable_excursion'],
                entry_timing_score=entry_timing_score,
                exit_timing_score=exit_timing_score,
                hold_duration=trade.duration
            )
            
            # Store attribution
            self.trade_attributions[trade_id] = attribution
            
            self.logger.log_system_event(
                "trade_attribution",
                f"Trade attribution analysis completed for trade {trade_id}",
                {"regime": regime.value, "pnl": trade.pnl}
            )
            
            return attribution
            
        except Exception as e:
            self.logger.log_error(f"Error in trade attribution analysis: {str(e)}")
            raise
    
    def decompose_strategy_performance(self,
                                     strategy_id: str,
                                     trades: List[TradeRecord],
                                     start_date: datetime,
                                     end_date: datetime) -> StrategyDecomposition:
        """
        Decompose strategy performance into attribution factors.
        
        Args:
            strategy_id: Strategy identifier
            trades: List of trades to analyze
            start_date: Analysis start date
            end_date: Analysis end date
            
        Returns:
            Strategy decomposition analysis
        """
        try:
            # Filter trades by date range
            period_trades = [
                t for t in trades 
                if start_date <= t.entry_time <= end_date
            ]
            
            if not period_trades:
                raise ValueError("No trades found in specified period")
            
            # Calculate overall performance
            total_return = sum(t.pnl for t in period_trades if t.pnl is not None)
            total_capital = sum(abs(t.position_size * t.entry_price) for t in period_trades)
            return_rate = total_return / total_capital if total_capital > 0 else 0.0
            
            # Calculate factor contributions
            factor_returns = self._calculate_strategy_factor_returns(period_trades)
            factor_sharpe_ratios = self._calculate_factor_sharpe_ratios(period_trades)
            factor_hit_rates = self._calculate_factor_hit_rates(period_trades)
            
            # Calculate regime-based performance
            regime_performance = self._calculate_regime_performance(period_trades)
            regime_exposure = self._calculate_regime_exposure(period_trades)
            
            # Calculate skill vs luck metrics
            skill_metrics = self._calculate_skill_metrics(period_trades)
            
            # Calculate consistency metrics
            consistency_metrics = self._calculate_consistency_metrics(period_trades)
            
            decomposition = StrategyDecomposition(
                strategy_id=strategy_id,
                analysis_period=(start_date, end_date),
                total_return=return_rate,
                risk_adjusted_return=skill_metrics['risk_adjusted_return'],
                factor_returns=factor_returns,
                factor_sharpe_ratios=factor_sharpe_ratios,
                factor_hit_rates=factor_hit_rates,
                regime_performance=regime_performance,
                regime_exposure=regime_exposure,
                skill_score=skill_metrics['skill_score'],
                luck_component=skill_metrics['luck_component'],
                statistical_significance=skill_metrics['statistical_significance'],
                monthly_returns=consistency_metrics['monthly_returns'],
                return_consistency=consistency_metrics['return_consistency'],
                drawdown_consistency=consistency_metrics['drawdown_consistency']
            )
            
            # Store decomposition
            self.strategy_decompositions[strategy_id] = decomposition
            
            self.logger.log_system_event(
                "strategy_decomposition",
                f"Strategy decomposition completed for {strategy_id}",
                {"total_return": return_rate, "num_trades": len(period_trades)}
            )
            
            return decomposition
            
        except Exception as e:
            self.logger.log_error(f"Error in strategy decomposition: {str(e)}")
            raise
    
    def _calculate_factor_contributions(self,
                                     trade: TradeRecord,
                                     market_data: List[MarketData],
                                     state_vector: np.ndarray,
                                     regime_stats: Dict[str, float]) -> Dict[AttributionFactor, float]:
        """Calculate contribution of each factor to trade P&L."""
        if trade.pnl is None:
            return {factor: 0.0 for factor in AttributionFactor}
        
        contributions = {}
        
        # Market direction contribution
        market_return = self._calculate_market_return(market_data, trade)
        contributions[AttributionFactor.MARKET_DIRECTION] = market_return * 0.3
        
        # Volatility contribution
        vol_contribution = regime_stats.get('volatility', 0.0) * trade.pnl * 0.2
        contributions[AttributionFactor.VOLATILITY] = vol_contribution
        
        # Technical indicators (estimated from state vector)
        tech_contribution = np.mean(state_vector[:10]) * trade.pnl * 0.2 if len(state_vector) >= 10 else 0.0
        contributions[AttributionFactor.TECHNICAL_INDICATORS] = tech_contribution
        
        # Portfolio state contribution
        portfolio_contribution = np.mean(state_vector[-5:]) * trade.pnl * 0.1 if len(state_vector) >= 5 else 0.0
        contributions[AttributionFactor.PORTFOLIO_STATE] = portfolio_contribution
        
        # Risk management contribution
        risk_contribution = self._calculate_risk_contribution(trade) * 0.1
        contributions[AttributionFactor.RISK_MANAGEMENT] = risk_contribution
        
        # Timing contribution
        timing_contribution = trade.pnl * 0.05  # Simplified
        contributions[AttributionFactor.TIMING] = timing_contribution
        
        # Position sizing contribution
        sizing_contribution = self._calculate_sizing_contribution(trade) * 0.05
        contributions[AttributionFactor.POSITION_SIZING] = sizing_contribution
        
        # Market microstructure contribution (simplified)
        microstructure_contribution = trade.pnl * 0.05 if trade.pnl else 0.0  # Simplified
        contributions[AttributionFactor.MARKET_MICROSTRUCTURE] = microstructure_contribution
        
        return contributions
    
    def _calculate_market_return(self, market_data: List[MarketData], trade: TradeRecord) -> float:
        """Calculate market return during trade period."""
        if len(market_data) < 2:
            return 0.0
        
        entry_price = trade.entry_price
        exit_price = trade.exit_price or market_data[-1].close
        
        return (exit_price - entry_price) / entry_price
    
    def _calculate_risk_contribution(self, trade: TradeRecord) -> float:
        """Calculate risk management contribution to P&L."""
        if trade.pnl is None:
            return 0.0
        
        # Simplified risk contribution based on position size relative to typical size
        typical_size = 0.01  # Assume 1% typical position
        size_ratio = abs(trade.position_size) / typical_size
        
        # Penalize oversized positions, reward appropriate sizing
        if size_ratio > 2.0:
            return -abs(trade.pnl) * 0.1  # Penalty for oversizing
        elif size_ratio < 0.5:
            return -abs(trade.pnl) * 0.05  # Penalty for undersizing
        else:
            return abs(trade.pnl) * 0.05  # Reward for appropriate sizing
    
    def _calculate_sizing_contribution(self, trade: TradeRecord) -> float:
        """Calculate position sizing contribution."""
        if trade.pnl is None:
            return 0.0
        
        # Reward optimal position sizing
        return trade.pnl * 0.1 if abs(trade.position_size) <= 0.02 else trade.pnl * -0.05
    
    def _calculate_entry_timing_score(self, trade: TradeRecord, market_data: List[MarketData]) -> float:
        """Calculate entry timing quality score (0-1)."""
        if len(market_data) < 10:
            return 0.5
        
        # Compare entry price to recent price range
        recent_prices = [md.close for md in market_data[-10:]]
        price_range = max(recent_prices) - min(recent_prices)
        
        if price_range == 0:
            return 0.5
        
        # For long positions, better entry at lower prices
        # For short positions, better entry at higher prices
        if trade.position_size > 0:  # Long
            score = (max(recent_prices) - trade.entry_price) / price_range
        else:  # Short
            score = (trade.entry_price - min(recent_prices)) / price_range
        
        return max(0.0, min(1.0, score))
    
    def _calculate_exit_timing_score(self, trade: TradeRecord, market_data: List[MarketData]) -> float:
        """Calculate exit timing quality score (0-1)."""
        if trade.exit_price is None or len(market_data) < 10:
            return 0.5
        
        # Compare exit price to recent price range after exit
        recent_prices = [md.close for md in market_data[-10:]]
        price_range = max(recent_prices) - min(recent_prices)
        
        if price_range == 0:
            return 0.5
        
        # For long positions, better exit at higher prices
        # For short positions, better exit at lower prices
        if trade.position_size > 0:  # Long
            score = (trade.exit_price - min(recent_prices)) / price_range
        else:  # Short
            score = (max(recent_prices) - trade.exit_price) / price_range
        
        return max(0.0, min(1.0, score))
    
    def _calculate_trade_risk_metrics(self, trade: TradeRecord, market_data: List[MarketData]) -> Dict[str, float]:
        """Calculate risk metrics for a trade."""
        if trade.pnl is None:
            return {
                'risk_adjusted_return': 0.0,
                'sharpe_contribution': 0.0,
                'max_adverse_excursion': 0.0,
                'max_favorable_excursion': 0.0
            }
        
        # Simplified risk metrics
        volatility = np.std([md.close for md in market_data[-20:]]) if len(market_data) >= 20 else 0.01
        
        return {
            'risk_adjusted_return': trade.pnl / volatility if volatility > 0 else 0.0,
            'sharpe_contribution': trade.pnl / (volatility * np.sqrt(252)) if volatility > 0 else 0.0,
            'max_adverse_excursion': abs(trade.pnl) * 0.5,  # Simplified
            'max_favorable_excursion': abs(trade.pnl) * 1.2   # Simplified
        }
    
    def _calculate_volatility_percentile(self, prices: List[float]) -> float:
        """Calculate current volatility percentile."""
        if len(prices) < 20:
            return 0.5
        
        returns = np.diff(prices) / np.array(prices[:-1])
        current_vol = np.std(returns[-10:]) if len(returns) >= 10 else np.std(returns)
        historical_vols = [np.std(returns[i:i+10]) for i in range(len(returns)-10)]
        
        if not historical_vols:
            return 0.5
        
        percentile = np.percentile(historical_vols, current_vol * 100) / 100
        return max(0.0, min(1.0, percentile))
    
    def _calculate_confidence_score(self, 
                                  action_probabilities: Optional[np.ndarray],
                                  q_values: Optional[np.ndarray]) -> float:
        """Calculate agent confidence score."""
        if action_probabilities is not None:
            return float(np.max(action_probabilities))
        elif q_values is not None:
            q_range = np.max(q_values) - np.min(q_values)
            return float(q_range / (np.max(q_values) + 1e-8))
        else:
            return 0.5
    
    def _calculate_strategy_factor_returns(self, trades: List[TradeRecord]) -> Dict[AttributionFactor, float]:
        """Calculate factor returns for strategy."""
        factor_returns = {factor: 0.0 for factor in AttributionFactor}
        
        for trade in trades:
            trade_id = self._generate_trade_id(trade)
            if trade_id in self.trade_attributions:
                attribution = self.trade_attributions[trade_id]
                for factor, contribution in attribution.factor_contributions.items():
                    factor_returns[factor] += contribution
        
        return factor_returns
    
    def _calculate_factor_sharpe_ratios(self, trades: List[TradeRecord]) -> Dict[AttributionFactor, float]:
        """Calculate Sharpe ratios for each factor."""
        factor_sharpe = {factor: 0.0 for factor in AttributionFactor}
        
        # Simplified calculation - would need more sophisticated implementation
        for factor in AttributionFactor:
            factor_returns = []
            for trade in trades:
                trade_id = self._generate_trade_id(trade)
                if trade_id in self.trade_attributions:
                    attribution = self.trade_attributions[trade_id]
                    factor_returns.append(attribution.factor_contributions.get(factor, 0.0))
            
            if factor_returns:
                mean_return = np.mean(factor_returns)
                std_return = np.std(factor_returns)
                factor_sharpe[factor] = mean_return / std_return if std_return > 0 else 0.0
        
        return factor_sharpe
    
    def _calculate_factor_hit_rates(self, trades: List[TradeRecord]) -> Dict[AttributionFactor, float]:
        """Calculate hit rates for each factor."""
        factor_hit_rates = {factor: 0.0 for factor in AttributionFactor}
        
        for factor in AttributionFactor:
            positive_contributions = 0
            total_contributions = 0
            
            for trade in trades:
                trade_id = self._generate_trade_id(trade)
                if trade_id in self.trade_attributions:
                    attribution = self.trade_attributions[trade_id]
                    contribution = attribution.factor_contributions.get(factor, 0.0)
                    if contribution != 0:
                        total_contributions += 1
                        if contribution > 0:
                            positive_contributions += 1
            
            factor_hit_rates[factor] = positive_contributions / total_contributions if total_contributions > 0 else 0.0
        
        return factor_hit_rates
    
    def _calculate_regime_performance(self, trades: List[TradeRecord]) -> Dict[MarketRegime, PerformanceMetrics]:
        """Calculate performance by market regime."""
        regime_trades = defaultdict(list)
        
        # Group trades by regime
        for trade in trades:
            trade_id = self._generate_trade_id(trade)
            if trade_id in self.trade_attributions:
                attribution = self.trade_attributions[trade_id]
                regime_trades[attribution.market_regime].append(trade)
        
        regime_performance = {}
        for regime, regime_trade_list in regime_trades.items():
            if regime_trade_list:
                # Calculate simplified performance metrics
                returns = [t.pnl for t in regime_trade_list if t.pnl is not None]
                if returns:
                    total_return = sum(returns)
                    win_rate = sum(1 for r in returns if r > 0) / len(returns)
                    
                    regime_performance[regime] = PerformanceMetrics(
                        total_return=total_return,
                        annualized_return=total_return * 252 / len(returns),  # Simplified
                        cumulative_return=total_return,
                        volatility=np.std(returns),
                        sharpe_ratio=np.mean(returns) / np.std(returns) if np.std(returns) > 0 else 0.0,
                        sortino_ratio=0.0,  # Simplified
                        calmar_ratio=0.0,   # Simplified
                        max_drawdown=min(returns) if returns else 0.0,
                        current_drawdown=0.0,
                        win_rate=win_rate,
                        profit_factor=sum(r for r in returns if r > 0) / abs(sum(r for r in returns if r < 0)) if any(r < 0 for r in returns) else float('inf'),
                        avg_win=np.mean([r for r in returns if r > 0]) if any(r > 0 for r in returns) else 0.0,
                        avg_loss=np.mean([r for r in returns if r < 0]) if any(r < 0 for r in returns) else 0.0,
                        num_trades=len(returns),
                        avg_trade_duration=np.mean([t.duration for t in regime_trade_list if t.duration is not None]),
                        information_ratio=0.0,  # Simplified
                        treynor_ratio=0.0,      # Simplified
                        jensen_alpha=0.0,       # Simplified
                        beta=1.0,               # Simplified
                        timestamp=datetime.now()
                    )
        
        return regime_performance
    
    def _calculate_regime_exposure(self, trades: List[TradeRecord]) -> Dict[MarketRegime, float]:
        """Calculate exposure to each market regime."""
        regime_counts = defaultdict(int)
        total_trades = 0
        
        for trade in trades:
            trade_id = self._generate_trade_id(trade)
            if trade_id in self.trade_attributions:
                attribution = self.trade_attributions[trade_id]
                regime_counts[attribution.market_regime] += 1
                total_trades += 1
        
        return {
            regime: count / total_trades if total_trades > 0 else 0.0
            for regime, count in regime_counts.items()
        }
    
    def _calculate_skill_metrics(self, trades: List[TradeRecord]) -> Dict[str, float]:
        """Calculate skill vs luck metrics."""
        returns = [t.pnl for t in trades if t.pnl is not None]
        
        if not returns:
            return {
                'skill_score': 0.0,
                'luck_component': 1.0,
                'statistical_significance': 0.0,
                'risk_adjusted_return': 0.0
            }
        
        mean_return = np.mean(returns)
        std_return = np.std(returns)
        
        # Simplified skill metrics
        t_stat = mean_return / (std_return / np.sqrt(len(returns))) if std_return > 0 else 0.0
        p_value = 2 * (1 - abs(t_stat) / 2)  # Simplified p-value approximation
        
        return {
            'skill_score': max(0.0, min(1.0, abs(t_stat) / 3.0)),  # Normalized skill score
            'luck_component': max(0.0, 1.0 - abs(t_stat) / 3.0),
            'statistical_significance': 1.0 - p_value,
            'risk_adjusted_return': mean_return / std_return if std_return > 0 else 0.0
        }
    
    def _calculate_consistency_metrics(self, trades: List[TradeRecord]) -> Dict[str, Any]:
        """Calculate consistency metrics."""
        # Group trades by month
        monthly_returns = defaultdict(float)
        
        for trade in trades:
            if trade.pnl is not None and trade.entry_time:
                month_key = trade.entry_time.strftime('%Y-%m')
                monthly_returns[month_key] += trade.pnl
        
        monthly_return_list = list(monthly_returns.values())
        
        return {
            'monthly_returns': monthly_return_list,
            'return_consistency': 1.0 - (np.std(monthly_return_list) / np.mean(monthly_return_list)) if monthly_return_list and np.mean(monthly_return_list) != 0 else 0.0,
            'drawdown_consistency': 0.8  # Simplified
        }
    
    def get_attribution_summary(self, strategy_id: str) -> Dict[str, Any]:
        """Get summary of attribution analysis for a strategy."""
        strategy_attributions = [
            attr for attr in self.trade_attributions.values()
            if attr.agent_id == strategy_id
        ]
        
        if not strategy_attributions:
            return {}
        
        # Aggregate statistics
        total_trades = len(strategy_attributions)
        total_pnl = sum(attr.pnl for attr in strategy_attributions if attr.pnl is not None)
        
        # Factor contribution summary
        factor_summary = defaultdict(float)
        for attr in strategy_attributions:
            for factor, contribution in attr.factor_contributions.items():
                factor_summary[factor] += contribution
        
        # Regime distribution
        regime_distribution = defaultdict(int)
        for attr in strategy_attributions:
            regime_distribution[attr.market_regime] += 1
        
        return {
            'strategy_id': strategy_id,
            'total_trades': total_trades,
            'total_pnl': total_pnl,
            'avg_confidence': np.mean([attr.confidence_score for attr in strategy_attributions]),
            'factor_contributions': {factor.value: contrib for factor, contrib in factor_summary.items()},
            'regime_distribution': {regime.value: count/total_trades for regime, count in regime_distribution.items()},
            'avg_timing_scores': {
                'entry': np.mean([attr.entry_timing_score for attr in strategy_attributions]),
                'exit': np.mean([attr.exit_timing_score for attr in strategy_attributions])
            }
        }
    
    def save_attribution_analysis(self, filename: Optional[str] = None) -> str:
        """Save attribution analysis to file."""
        if filename is None:
            filename = f"attribution_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        filepath = self.save_dir / filename
        
        # Prepare data for serialization
        data = {
            'trade_attributions': {
                trade_id: attr.to_dict() 
                for trade_id, attr in self.trade_attributions.items()
            },
            'strategy_decompositions': {
                strategy_id: decomp.to_dict()
                for strategy_id, decomp in self.strategy_decompositions.items()
            },
            'analysis_timestamp': datetime.now().isoformat()
        }
        
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2, default=str)
        
        self.logger.log_system_event("attribution_analysis", f"Attribution analysis saved to {filepath}")
        return str(filepath)
    
    def load_attribution_analysis(self, filepath: str) -> None:
        """Load attribution analysis from file."""
        with open(filepath, 'r') as f:
            data = json.load(f)
        
        # Load trade attributions
        for trade_id, attr_data in data.get('trade_attributions', {}).items():
            # Convert back from dict (simplified - would need proper deserialization)
            self.trade_attributions[trade_id] = attr_data
        
        # Load strategy decompositions  
        for strategy_id, decomp_data in data.get('strategy_decompositions', {}).items():
            # Convert back from dict (simplified - would need proper deserialization)
            self.strategy_decompositions[strategy_id] = decomp_data
        
        self.logger.log_system_event("attribution_analysis", f"Attribution analysis loaded from {filepath}")