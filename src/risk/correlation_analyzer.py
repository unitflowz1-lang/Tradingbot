"""
Correlation Analyzer - Phase 2 Implementation
Analyzes currency pair correlations for diversification
"""

import logging
from typing import Dict, List, Set, Tuple
from dataclasses import dataclass
import numpy as np


@dataclass
class CorrelationConfig:
    """Configuration for correlation analysis"""
    high_correlation_threshold: float = 0.80  # Max correlation for same group
    medium_correlation_threshold: float = 0.60  # Medium correlation
    lookback_periods: int = 100  # Number of bars for correlation
    min_positions_same_group_high: int = 1  # Max 1 position if corr > 0.80
    min_positions_same_group_medium: int = 2  # Max 2 positions if corr > 0.60


class CurrencyGroup:
    """Represents a group of correlated currency pairs"""
    
    def __init__(self, name: str, pairs: List[str]):
        self.name = name
        self.pairs = pairs
        self.correlations: Dict[Tuple[str, str], float] = {}
    
    def add_correlation(self, pair1: str, pair2: str, corr: float):
        """Add correlation between two pairs"""
        self.correlations[(pair1, pair2)] = corr
        self.correlations[(pair2, pair1)] = corr


class CorrelationAnalyzer:
    """
    Analyzes correlations between currency pairs and enforces position limits
    
    Strategy:
    - High correlation (>0.80): Max 1 pair from group
    - Medium correlation (>0.60): Max 2 pairs from group
    - Low correlation (<0.60): No limit
    """
    
    def __init__(self, config: CorrelationConfig = None):
        """Initialize correlation analyzer"""
        self.config = config or CorrelationConfig()
        self.logger = logging.getLogger(f"[CORRELATION_ANALYZER]")
        self.logger.info(f"Correlation Analyzer initialized")
        
        # Predefined correlation groups
        self.currency_groups = self._create_currency_groups()
        
        # Store recent price data for correlation calculation
        self.price_history: Dict[str, List[float]] = {}
    
    def _create_currency_groups(self) -> List[CurrencyGroup]:
        """Create predefined currency pair groups"""
        groups = [
            # Euro pairs (very correlated)
            CurrencyGroup("Euro_Pairs", ["EUR/USD", "EUR/GBP", "EUR/JPY", "EUR/CHF", "EUR/AUD"]),
            
            # USD pairs (correlated)
            CurrencyGroup("USD_Pairs", ["USD/JPY", "USD/CHF", "USD/CAD"]),
            
            # GBP pairs
            CurrencyGroup("GBP_Pairs", ["GBP/USD", "GBP/JPY", "GBP/CHF"]),
            
            # Commodity currencies (AUD, NZD, CAD)
            CurrencyGroup("Commodity_Pairs", ["AUD/USD", "NZD/USD", "USD/CAD"]),
            
            # Japanese Yen pairs
            CurrencyGroup("JPY_Pairs", ["USD/JPY", "EUR/JPY", "GBP/JPY"]),
        ]
        return groups
    
    def add_price_data(self, pair: str, price: float):
        """
        Add price data for correlation calculation
        
        Args:
            pair: Currency pair (e.g., 'EUR/USD')
            price: Price value
        """
        if pair not in self.price_history:
            self.price_history[pair] = []
        
        self.price_history[pair].append(price)
        
        # Keep only last N periods
        if len(self.price_history[pair]) > self.config.lookback_periods:
            self.price_history[pair].pop(0)
    
    def calculate_correlation(self, pair1: str, pair2: str) -> float:
        """
        Calculate correlation between two pairs
        
        Args:
            pair1: First currency pair
            pair2: Second currency pair
            
        Returns:
            Correlation coefficient (-1 to 1)
        """
        if pair1 not in self.price_history or pair2 not in self.price_history:
            return 0.0
        
        prices1 = np.array(self.price_history[pair1])
        prices2 = np.array(self.price_history[pair2])
        
        if len(prices1) < 2 or len(prices2) < 2:
            return 0.0
        
        try:
            correlation = np.corrcoef(prices1, prices2)[0, 1]
            return float(correlation) if not np.isnan(correlation) else 0.0
        except Exception as e:
            self.logger.warning(f"Error calculating correlation for {pair1}/{pair2}: {e}")
            return 0.0
    
    def get_correlation_matrix(self, pairs: List[str]) -> Dict[str, Dict[str, float]]:
        """
        Get correlation matrix for a list of pairs
        
        Args:
            pairs: List of currency pairs
            
        Returns:
            Dictionary of correlations
        """
        matrix = {}
        
        for pair1 in pairs:
            matrix[pair1] = {}
            for pair2 in pairs:
                if pair1 == pair2:
                    matrix[pair1][pair2] = 1.0
                else:
                    corr = self.calculate_correlation(pair1, pair2)
                    matrix[pair1][pair2] = corr
        
        return matrix
    
    def can_open_position(
        self,
        new_pair: str,
        open_positions: Dict[str, Dict],
    ) -> Tuple[bool, str]:
        """
        Check if new position can be opened based on correlation limits
        
        Args:
            new_pair: Currency pair to open
            open_positions: Dict of currently open positions
            
        Returns:
            Tuple of (can_open, reason)
        """
        # Find which group the new pair belongs to
        new_pair_groups = self._find_pair_groups(new_pair)
        
        if not new_pair_groups:
            # Not in predefined groups, allow
            return True, "Pair not in correlation groups"
        
        # Check correlation with each open position
        correlation_violations = []
        
        for open_pair in open_positions.keys():
            corr = self.calculate_correlation(new_pair, open_pair)
            
            # Check if pairs are in same group
            open_pair_groups = self._find_pair_groups(open_pair)
            same_group = any(g in new_pair_groups for g in open_pair_groups)
            
            if same_group:
                # Check correlation threshold
                if corr > self.config.high_correlation_threshold:
                    violation = {
                        'pair': open_pair,
                        'correlation': corr,
                        'threshold': self.config.high_correlation_threshold,
                        'max_positions': self.config.min_positions_same_group_high,
                    }
                    correlation_violations.append(violation)
                
                elif corr > self.config.medium_correlation_threshold:
                    violation = {
                        'pair': open_pair,
                        'correlation': corr,
                        'threshold': self.config.medium_correlation_threshold,
                        'max_positions': self.config.min_positions_same_group_medium,
                    }
                    correlation_violations.append(violation)
        
        if correlation_violations:
            reason = f"High correlation violations: {correlation_violations}"
            self.logger.warning(f"Cannot open {new_pair}: {reason}")
            return False, reason
        
        self.logger.info(f"✓ {new_pair} can be opened (no correlation violations)")
        return True, "Correlation check passed"
    
    def get_position_group_limits(self) -> Dict[str, int]:
        """
        Get position limits for each group
        
        Returns:
            Dict mapping group names to max positions
        """
        limits = {}
        
        for group in self.currency_groups:
            # Default: 2 positions per group
            limits[group.name] = 2
        
        return limits
    
    def _find_pair_groups(self, pair: str) -> List[str]:
        """
        Find which groups a pair belongs to
        
        Args:
            pair: Currency pair
            
        Returns:
            List of group names
        """
        groups = []
        
        for group in self.currency_groups:
            if pair in group.pairs:
                groups.append(group.name)
        
        return groups
    
    def log_correlation_analysis(self, pairs: List[str]):
        """
        Log correlation analysis for a list of pairs
        
        Args:
            pairs: List of currency pairs
        """
        if len(pairs) < 2:
            return
        
        self.logger.info("=== CORRELATION ANALYSIS ===")
        
        for i, pair1 in enumerate(pairs):
            for pair2 in pairs[i+1:]:
                corr = self.calculate_correlation(pair1, pair2)
                
                if corr > self.config.high_correlation_threshold:
                    level = "HIGH"
                    symbol = "⚠️"
                elif corr > self.config.medium_correlation_threshold:
                    level = "MEDIUM"
                    symbol = "⚡"
                else:
                    level = "LOW"
                    symbol = "✓"
                
                self.logger.info(
                    f"{symbol} {pair1} ↔ {pair2}: {corr:.3f} ({level})"
                )


# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    analyzer = CorrelationAnalyzer()
    
    # Simulate price data
    import random
    np.random.seed(42)
    
    pairs = ["EUR/USD", "EUR/GBP", "USD/JPY"]
    
    # Generate correlated price data
    base_price = 1.0950
    for _ in range(100):
        # EUR/USD movement
        eur_usd = base_price + np.random.randn() * 0.005
        analyzer.add_price_data("EUR/USD", eur_usd)
        
        # EUR/GBP (highly correlated with EUR/USD)
        eur_gbp = 0.85 + np.random.randn() * 0.003 + (eur_usd - base_price) * 0.5
        analyzer.add_price_data("EUR/GBP", eur_gbp)
        
        # USD/JPY (less correlated)
        usdjpy = 155 + np.random.randn() * 0.3 - (eur_usd - base_price) * 100
        analyzer.add_price_data("USD/JPY", usdjpy)
    
    # Show correlations
    analyzer.log_correlation_analysis(pairs)
    
    # Check if we can open position
    open_positions = {"EUR/GBP": {"size": 0.5}}
    can_open, reason = analyzer.can_open_position("EUR/USD", open_positions)
    print(f"\nCan open EUR/USD: {can_open} ({reason})")
