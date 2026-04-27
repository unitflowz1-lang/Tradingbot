"""
Regime-Aware Exit Policy Ensemble & Capital Allocation Optimizer
Produces expectancy-based recommendations rather than single predictions.
"""

import json
import os
import logging
import numpy as np
from typing import Dict, Any, Tuple, Optional, List
from dataclasses import dataclass
from collections import defaultdict

from src.models import ExitPolicy

logger = logging.getLogger(__name__)


@dataclass
class PolicyExpectancy:
    """Expectancy surface for a single policy in a given regime"""
    policy: ExitPolicy
    regime: str
    expected_r_multiple: float
    expected_quality: float
    win_rate: float
    sample_count: int
    confidence: float  # Statistical confidence based on sample size
    avg_capital_efficiency: float  # PnL / time-in-trade / drawdown exposure


@dataclass
class AllocationRecommendation:
    """Optimal exit policy and capital allocation"""
    exit_policy: ExitPolicy
    position_size_multiplier: float  # Multiply base position size by this
    expectancy: float
    confidence: float
    regime: str
    reasoning: str
    # Regret Components
    policy_regret_risk: float = 0.0  # Risk of choosing wrong policy
    allocation_regret_risk: float = 0.0  # Risk of wrong sizing


class ExitPolicyEnsemble:
    """
    Ensemble model that produces regime-conditioned expectancy for each ExitPolicy.
    Uses historical performance data stratified by market regime.
    
    FIX #4: Singleton pattern to prevent duplicate initialization hooks
    """
    
    PERFORMANCE_FILE = "regime_policy_performance.json"
    _instance = None  # Singleton instance
    _initialized = False  # Track if already loaded
    
    def __new__(cls, data_dir: str = "."):
        # FIX #4: Implement singleton pattern to prevent duplicate 'Loaded performance matrix' logs
        if cls._instance is None:
            cls._instance = super(ExitPolicyEnsemble, cls).__new__(cls)
        return cls._instance
    
    def __init__(self, data_dir: str = "."):
        # FIX #4: Only initialize once to prevent duplicate initialization hooks
        if ExitPolicyEnsemble._initialized:
            return
        
        self.data_dir = data_dir
        self.performance_path = os.path.join(data_dir, self.PERFORMANCE_FILE)
        
        # Regime x Policy Performance Matrix
        self.performance_matrix: Dict[str, Dict[str, PolicyExpectancy]] = {}
        
        # Minimum samples required for trustworthy expectancy
        self.min_samples_for_confidence = 10
        
        # Load existing performance data (only once)
        self.load_performance()
        
        ExitPolicyEnsemble._initialized = True
        
    def get_policy_expectancies(self, regime: str, features: np.ndarray, 
                               current_volatility: float, current_spread: float) -> List[PolicyExpectancy]:
        """
        Get expectancy for all policies conditioned on regime and current market conditions.
        
        Args:
            regime: Market regime label (TRENDING, RANGING, etc.)
            features: Market features [ATR, ADX, RSI, Spread, Confidence]
            current_volatility: Current ATR value
            current_spread: Current bid-ask spread
            
        Returns:
            List of PolicyExpectancy for each policy
        """
        expectancies = []
        
        # Get historical performance for this regime
        regime_performance = self.performance_matrix.get(regime, {})
        
        for policy in [ExitPolicy.STANDARD, ExitPolicy.SCALP, ExitPolicy.TREND_FOLLOW, ExitPolicy.MEAN_REVERT]:
            policy_key = policy.value
            
            if policy_key in regime_performance:
                # Use historical data
                perf = regime_performance[policy_key]
                
                # Adjust for current conditions (volatility, spread costs)
                adjusted_expectancy = self._adjust_expectancy_for_conditions(
                    perf.expected_r_multiple, 
                    current_volatility, 
                    current_spread, 
                    policy
                )
                
                expectancies.append(PolicyExpectancy(
                    policy=policy,
                    regime=regime,
                    expected_r_multiple=adjusted_expectancy,
                    expected_quality=perf.expected_quality,
                    win_rate=perf.win_rate,
                    sample_count=perf.sample_count,
                    confidence=self._calculate_confidence(perf.sample_count),
                    avg_capital_efficiency=perf.avg_capital_efficiency
                ))
            else:
                # No historical data - use conservative defaults
                expectancies.append(self._get_default_expectancy(policy, regime))
                
        return expectancies
    
    def get_optimal_allocation(self, regime: str, features: np.ndarray,
                              current_volatility: float, current_spread: float,
                              base_confidence: float, enforce_invariants: bool = True) -> AllocationRecommendation:
        """
        Select optimal policy and capital allocation based on expectancy surface.
        
        Args:
            regime: Market regime
            features: Market features
            current_volatility: ATR
            current_spread: Bid-ask spread
            base_confidence: Signal confidence (raw ML confidence)
            enforce_invariants: Apply hard risk constraints
            
        Returns:
            AllocationRecommendation with policy and sizing
        """
        # Get all policy expectancies
        expectancies = self.get_policy_expectancies(regime, features, current_volatility, current_spread)
        
        # Calculate confidence-weighted edge for each policy
        policy_scores = []
        for exp in expectancies:
            # Edge = Expectancy * Confidence * Capital Efficiency
            # Ensure avg_capital_efficiency is non-negative before square root to avoid complex numbers
            safe_efficiency = max(0.01, exp.avg_capital_efficiency) # Minimum boost factor
            edge = float(exp.expected_r_multiple * exp.confidence * (safe_efficiency ** 0.5))
            policy_scores.append((exp.policy, edge, exp))
        
        # Sort by edge (descending)
        policy_scores.sort(key=lambda x: x[1], reverse=True)
        
        if not policy_scores:
            # Fallback to STANDARD with minimal allocation
            return AllocationRecommendation(
                exit_policy=ExitPolicy.STANDARD,
                position_size_multiplier=0.5,
                expectancy=0.0,
                confidence=0.0,
                regime=regime,
                reasoning="No performance data available - conservative default"
            )
        
        best_policy, best_edge, best_exp = policy_scores[0]
        
        # ===== FIX #1: ENSEMBLE CONFIDENCE PASS-THROUGH =====
        # Use max(0.10, raw_ml_confidence) to prevent downgrading high-confidence signals
        # If the raw ML confidence is higher than the ensemble's estimated confidence,
        # use the raw ML confidence instead of the lower ensemble default
        final_ensemble_confidence = max(float(best_exp.confidence), float(base_confidence or 0.0))
        
        # Calculate position size multiplier based on Kelly-inspired criterion
        # Kelly Fraction = (Win% * AvgWin - Loss% * AvgLoss) / AvgWin
        # Simplified: Use expectancy and confidence
        
        # Base multiplier from expectancy
        if best_exp.expected_r_multiple > 0:
            # Positive expectancy - scale up
            kelly_fraction = min(best_exp.expected_r_multiple * best_exp.win_rate, 2.0)
        else:
            # Negative expectancy - don't trade
            kelly_fraction = 0.0
        
        # Adjust by confidence (using the pass-through confidence, not the ensemble default)
        size_multiplier = kelly_fraction * final_ensemble_confidence * base_confidence
        
        # Cap at reasonable bounds
        size_multiplier = np.clip(size_multiplier, 0.25, 2.0)
        
        # Apply Hard Risk Invariants
        if enforce_invariants:
            size_multiplier = self._apply_risk_invariants(
                size_multiplier, regime, current_spread, current_volatility
            )
        
        # Calculate regret risks
        policy_regret = self._calculate_policy_regret_risk(policy_scores)
        allocation_regret = self._calculate_allocation_regret_risk(best_exp, size_multiplier)
        
        reasoning = (f"{best_policy.value} selected in {regime} regime | "
                    f"Expectancy: {best_exp.expected_r_multiple:.2f}R | "
                    f"Win Rate: {best_exp.win_rate*100:.1f}% | "
                    f"Samples: {best_exp.sample_count} | "
                    f"Size Multiplier: {size_multiplier:.2f}x")
        
        return AllocationRecommendation(
            exit_policy=best_policy,
            position_size_multiplier=size_multiplier,
            expectancy=best_exp.expected_r_multiple,
            confidence=final_ensemble_confidence,
            regime=regime,
            reasoning=reasoning,
            policy_regret_risk=policy_regret,
            allocation_regret_risk=allocation_regret
        )
    
    def _adjust_expectancy_for_conditions(self, base_expectancy: float, 
                                         volatility: float, spread: float,
                                         policy: ExitPolicy) -> float:
        """Adjust historical expectancy for current market conditions"""
        adjusted = base_expectancy
        
        # Spread cost adjustment (higher spread = lower expectancy)
        # Assume 2 pips spread is baseline, penalty increases linearly
        spread_penalty = (spread - 0.0002) * 1000  # Convert to R-multiple impact
        adjusted -= spread_penalty
        
        # Volatility adjustment (policy-dependent)
        if policy == ExitPolicy.SCALP:
            # Scalping suffers in high volatility (more whipsaws)
            if volatility > 0.0005:  # High volatility threshold
                adjusted *= 0.8
        elif policy == ExitPolicy.TREND_FOLLOW:
            # Trend following benefits from volatility
            if volatility > 0.0005:
                adjusted *= 1.2
        
        return adjusted
    
    def _calculate_confidence(self, sample_count: int) -> float:
        """Calculate statistical confidence based on sample size"""
        if sample_count < self.min_samples_for_confidence:
            return sample_count / self.min_samples_for_confidence
        else:
            # Logarithmic confidence growth after min threshold
            return min(1.0, 0.5 + 0.5 * np.log10(sample_count / self.min_samples_for_confidence + 1))
    
    def _get_default_expectancy(self, policy: ExitPolicy, regime: str) -> PolicyExpectancy:
        """Conservative default expectancy when no data available"""
        # Regime-policy heuristics
        defaults = {
            ('TRENDING', ExitPolicy.TREND_FOLLOW): (1.5, 0.45),
            ('TRENDING', ExitPolicy.STANDARD): (1.0, 0.50),
            ('TRENDING', ExitPolicy.SCALP): (0.5, 0.55),
            ('TRENDING', ExitPolicy.MEAN_REVERT): (-0.2, 0.40),
            
            ('RANGING', ExitPolicy.MEAN_REVERT): (1.0, 0.50),
            ('RANGING', ExitPolicy.SCALP): (0.8, 0.52),
            ('RANGING', ExitPolicy.STANDARD): (0.5, 0.48),
            ('RANGING', ExitPolicy.TREND_FOLLOW): (-0.3, 0.35),
            
            ('HIGH_VOLATILITY', ExitPolicy.STANDARD): (0.3, 0.45),
            ('HIGH_VOLATILITY', ExitPolicy.TREND_FOLLOW): (0.5, 0.40),
            ('HIGH_VOLATILITY', ExitPolicy.SCALP): (-0.2, 0.42),
            ('HIGH_VOLATILITY', ExitPolicy.MEAN_REVERT): (-0.1, 0.43),
            
            ('LOW_LIQUIDITY', ExitPolicy.STANDARD): (-0.5, 0.35),
            ('LOW_LIQUIDITY', ExitPolicy.TREND_FOLLOW): (-0.3, 0.35),
            ('LOW_LIQUIDITY', ExitPolicy.SCALP): (-0.8, 0.30),
            ('LOW_LIQUIDITY', ExitPolicy.MEAN_REVERT): (-0.4, 0.33),
        }
        
        key = (regime, policy)
        r_multiple, win_rate = defaults.get(key, (0.0, 0.40))
        
        return PolicyExpectancy(
            policy=policy,
            regime=regime,
            expected_r_multiple=r_multiple,
            expected_quality=0.5,
            win_rate=win_rate,
            sample_count=0,
            confidence=0.1,  # Low confidence for defaults
            avg_capital_efficiency=1.0
        )
    
    def _apply_risk_invariants(self, size_multiplier: float, regime: str,
                               spread: float, volatility: float) -> float:
        """Apply hard risk constraints"""
        adjusted = size_multiplier
        
        # No increase in exposure during high-risk regimes
        if regime in ['HIGH_VOLATILITY', 'LOW_LIQUIDITY']:
            adjusted = min(adjusted, 0.75)
        
        # No leverage amplification in high spread
        if spread > 0.0003:  # 3 pips
            adjusted = min(adjusted, 0.5)
        
        # No amplification in extreme volatility
        if volatility > 0.001:  # Very high ATR
            adjusted = min(adjusted, 0.5)
        
        return max(adjusted, 0.1)  # Never go below 0.1x
    
    def _calculate_policy_regret_risk(self, policy_scores: List[Tuple]) -> float:
        """Calculate risk of having chosen wrong policy"""
        if len(policy_scores) < 2:
            return 0.0
        
        # Regret = difference between best and second-best edge
        best_edge = policy_scores[0][1]
        second_edge = policy_scores[1][1]
        
        regret_risk = max(0.0, best_edge - second_edge)
        return regret_risk
    
    def _calculate_allocation_regret_risk(self, expectancy: PolicyExpectancy, 
                                         size_multiplier: float) -> float:
        """Calculate risk of wrong position sizing"""
        # If we have high expectancy but low allocation, regret is high
        optimal_size = expectancy.expected_r_multiple * expectancy.confidence * 0.5
        optimal_size = np.clip(optimal_size, 0.5, 2.0)
        
        # Regret is difference from optimal
        allocation_regret = abs(optimal_size - size_multiplier)
        return allocation_regret
    
    def update_performance(self, exit_record: Dict[str, Any]) -> None:
        """Update performance matrix with new trade result"""
        regime = exit_record.get('regime_label', 'NEUTRAL')
        policy = exit_record.get('exit_policy', 'STANDARD')
        
        # Calculate capital efficiency
        pnl = exit_record.get('profit_loss', 0.0)
        hold_time = max(exit_record.get('hold_time_seconds', 1), 1)
        mae = abs(exit_record.get('mae', 0.0))
        capital_efficiency = pnl / (hold_time / 3600) / max(mae, 0.01)  # PnL per hour per drawdown
        
        # Initialize regime if needed
        if regime not in self.performance_matrix:
            self.performance_matrix[regime] = {}
        
        # Get or create policy entry
        if policy in self.performance_matrix[regime]:
            existing = self.performance_matrix[regime][policy]
            
            # Running averages
            n = existing.sample_count
            new_n = n + 1
            
            r_multiple = exit_record.get('r_multiple', 0.0)
            quality = exit_record.get('exit_quality', 0.5)
            won = 1 if pnl > 0 else 0
            
            updated = PolicyExpectancy(
                policy=ExitPolicy(policy),
                regime=regime,
                expected_r_multiple=(existing.expected_r_multiple * n + r_multiple) / new_n,
                expected_quality=(existing.expected_quality * n + quality) / new_n,
                win_rate=(existing.win_rate * n + won) / new_n,
                sample_count=new_n,
                confidence=self._calculate_confidence(new_n),
                avg_capital_efficiency=(existing.avg_capital_efficiency * n + capital_efficiency) / new_n
            )
            
            self.performance_matrix[regime][policy] = updated
        else:
            # First sample for this regime-policy combination
            r_multiple = exit_record.get('r_multiple', 0.0)
            quality = exit_record.get('exit_quality', 0.5)
            won = 1 if pnl > 0 else 0
            
            self.performance_matrix[regime][policy] = PolicyExpectancy(
                policy=ExitPolicy(policy),
                regime=regime,
                expected_r_multiple=r_multiple,
                expected_quality=quality,
                win_rate=float(won),
                sample_count=1,
                confidence=self._calculate_confidence(1),
                avg_capital_efficiency=capital_efficiency
            )
        
        # Save updated matrix
        self.save_performance()
    
    def get_diagnostics(self) -> Dict[str, Any]:
        """Get comprehensive diagnostics"""
        diagnostics = {
            'regime_policy_matrix': {},
            'best_policy_per_regime': {},
            'staleness_alerts': []
        }
        
        for regime, policies in self.performance_matrix.items():
            diagnostics['regime_policy_matrix'][regime] = {}
            
            best_policy = None
            best_expectancy = -999
            
            for policy_name, perf in policies.items():
                diagnostics['regime_policy_matrix'][regime][policy_name] = {
                    'expectancy': perf.expected_r_multiple,
                    'win_rate': perf.win_rate,
                    'quality': perf.expected_quality,
                    'samples': perf.sample_count,
                    'confidence': perf.confidence,
                    'capital_efficiency': perf.avg_capital_efficiency
                }
                
                if perf.expected_r_multiple > best_expectancy:
                    best_expectancy = perf.expected_r_multiple
                    best_policy = policy_name
            
            diagnostics['best_policy_per_regime'][regime] = {
                'policy': best_policy,
                'expectancy': best_expectancy
            }
        
        # Check for staleness (regimes with low sample counts)
        for regime, policies in self.performance_matrix.items():
            for policy_name, perf in policies.items():
                if perf.sample_count < self.min_samples_for_confidence:
                    diagnostics['staleness_alerts'].append({
                        'regime': regime,
                        'policy': policy_name,
                        'samples': perf.sample_count,
                        'needed': self.min_samples_for_confidence
                    })
        
        return diagnostics
    
    def save_performance(self) -> None:
        """Persist performance matrix"""
        try:
            # Convert to serializable format
            data = {}
            for regime, policies in self.performance_matrix.items():
                data[regime] = {}
                for policy_name, perf in policies.items():
                    data[regime][policy_name] = {
                        'policy': perf.policy.value,
                        'regime': perf.regime,
                        'expected_r_multiple': perf.expected_r_multiple,
                        'expected_quality': perf.expected_quality,
                        'win_rate': perf.win_rate,
                        'sample_count': perf.sample_count,
                        'confidence': perf.confidence,
                        'avg_capital_efficiency': perf.avg_capital_efficiency
                    }
            
            with open(self.performance_path, 'w') as f:
                json.dump(data, f, indent=2)
                
        except Exception as e:
            logger.error(f"Failed to save performance matrix: {e}")
    
    def load_performance(self) -> None:
        """Load performance matrix from disk"""
        if not os.path.exists(self.performance_path):
            return
        
        try:
            with open(self.performance_path, 'r') as f:
                data = json.load(f)
            
            for regime, policies in data.items():
                self.performance_matrix[regime] = {}
                for policy_name, perf_data in policies.items():
                    self.performance_matrix[regime][policy_name] = PolicyExpectancy(
                        policy=ExitPolicy(perf_data['policy']),
                        regime=perf_data['regime'],
                        expected_r_multiple=perf_data['expected_r_multiple'],
                        expected_quality=perf_data['expected_quality'],
                        win_rate=perf_data['win_rate'],
                        sample_count=perf_data['sample_count'],
                        confidence=perf_data['confidence'],
                        avg_capital_efficiency=perf_data.get('avg_capital_efficiency', 1.0)
                    )
            
            logger.info(f"Loaded performance matrix with {len(self.performance_matrix)} regimes")
            
        except Exception as e:
            logger.error(f"Failed to load performance matrix: {e}")
