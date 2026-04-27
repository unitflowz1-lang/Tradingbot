"""Walk-Forward Validation for parameter stability verification.

This module ensures that parameter changes are stable across different market regimes
to prevent overfitting in the Aggressive Sniper Model.
"""

import numpy as np
from typing import Dict, List, Tuple
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class WFOStabilityResult:
    """Result of walk-forward stability check"""
    stability_rank: float  # 0-100 score
    sharpe_ratio: float
    regimes_tested: List[str]
    is_stable: bool  # True if passes all thresholds


class WFOValidator:
    """Ensures parameter changes are stable across market regimes.
    
    Requirements:
    - Sharpe >= 1.8 in ALL regimes
    - Performance variance < 30% between regimes
    - Stability rank > 60/100
    """
    
    def __init__(self, min_sharpe_ratio: float = 1.8):
        self.min_sharpe_ratio = min_sharpe_ratio
        self.regime_history: Dict[str, List[float]] = {
            "TRENDING": [],
            "RANGING": [],
            "CHOPPY": []
        }
    
    def validate_stability(
        self, 
        sharpe_trending: float,
        sharpe_ranging: float,
        sharpe_choppy: float
    ) -> WFOStabilityResult:
        """
        Validate parameter stability across three market regimes.
        
        Args:
            sharpe_trending: Sharpe ratio in trending market
            sharpe_ranging: Sharpe ratio in ranging market
            sharpe_choppy: Sharpe ratio in choppy market
            
        Returns:
            WFOStabilityResult with stability assessment
        """
        sharpes = [sharpe_trending, sharpe_ranging, sharpe_choppy]
        regimes = ["TRENDING", "RANGING", "CHOPPY"]
        
        # Check minimum Sharpe
        min_sharpe = min(sharpes)
        if min_sharpe < self.min_sharpe_ratio:
            logger.warning(
                f"[WFO_VALIDATOR] Minimum Sharpe {min_sharpe:.2f} < {self.min_sharpe_ratio} threshold. "
                f"Regimes: TRENDING={sharpe_trending:.2f}, RANGING={sharpe_ranging:.2f}, CHOPPY={sharpe_choppy:.2f}"
            )
            return WFOStabilityResult(
                stability_rank=0.0,
                sharpe_ratio=min_sharpe,
                regimes_tested=regimes,
                is_stable=False
            )
        
        # Check variance (coefficient of variation)
        mean_sharpe = np.mean(sharpes)
        std_sharpe = np.std(sharpes)
        cv = std_sharpe / mean_sharpe if mean_sharpe > 0 else float('inf')
        
        # Stability rank: 100 = perfect, 0 = unstable
        # CV of 0.5 = rank 0, CV of 0.0 = rank 100
        stability_rank = max(0, 100 - (cv * 200))
        
        is_stable = (
            min_sharpe >= self.min_sharpe_ratio and
            cv < 0.3 and  # Less than 30% variance
            stability_rank > 60  # Reasonable stability
        )
        
        if is_stable:
            logger.info(
                f"[WFO_VALIDATOR] PASSED | Min Sharpe: {min_sharpe:.2f} | "
                f"CV: {cv:.2f} | Stability Rank: {stability_rank:.1f}/100"
            )
        else:
            logger.warning(
                f"[WFO_VALIDATOR] FAILED | Min Sharpe: {min_sharpe:.2f} | "
                f"CV: {cv:.2f} (max 0.3) | Stability Rank: {stability_rank:.1f}/100 (min 60)"
            )
        
        return WFOStabilityResult(
            stability_rank=stability_rank,
            sharpe_ratio=min_sharpe,
            regimes_tested=regimes,
            is_stable=is_stable
        )
    
    def update_regime_history(self, regime: str, sharpe: float):
        """
        Update historical Sharpe ratios for a regime.
        
        Args:
            regime: Market regime (TRENDING, RANGING, CHOPPY)
            sharpe: Sharpe ratio to record
        """
        if regime in self.regime_history:
            self.regime_history[regime].append(sharpe)
            # Keep only last 10 observations
            if len(self.regime_history[regime]) > 10:
                self.regime_history[regime] = self.regime_history[regime][-10:]
            
            logger.debug(f"[WFO_HISTORY] Updated {regime} Sharpe: {sharpe:.2f} | Total records: {len(self.regime_history[regime])}")
    
    def get_average_regime_sharpe(self, regime: str) -> float:
        """
        Get average Sharpe ratio for a regime.
        
        Args:
            regime: Market regime name
            
        Returns:
            Average Sharpe ratio (default 1.8 if no history)
        """
        if regime in self.regime_history and self.regime_history[regime]:
            return float(np.mean(self.regime_history[regime]))
        return 1.8  # Default minimum
