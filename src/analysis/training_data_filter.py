"""
Training Data Filtering
Ensures ML model learns only from market-driven exits, not administrative decisions.

The ML model should learn from:
- How prices move after entry
- What volatility patterns precede reversals
- How trends evolve

The ML model should NOT learn from:
- Manual closes made by users
- Equity lock decisions (when we take profits)
- Time-based exits (when we get tired of holding)
- Risk governor force-closes (when systems override)

This module filters the training dataset to keep it CLEAN.
"""

import logging
from typing import List, Optional, Dict, Tuple
from datetime import datetime, timezone

from src.trading.exit_reason import ExitRecord, ExitReason
from src.models import MarketData


class TrainingDataFilter:
    """
    Ensures training data only includes market-driven exits.
    """
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger(__name__)
    
    def filter_for_training(self, 
                           exit_records: List[ExitRecord]
                           ) -> Tuple[List[ExitRecord], List[ExitRecord]]:
        """
        Separate exits into training-eligible and excluded.
        
        Args:
            exit_records: All trade exits
        
        Returns:
            (training_eligible, excluded_from_training)
        """
        training_eligible = []
        excluded = []
        
        for record in exit_records:
            if record.reason.is_market_driven:
                training_eligible.append(record)
            else:
                excluded.append(record)
                self.logger.debug(
                    f"[TRAINING FILTER] Excluding {record.symbol} | "
                    f"Reason: {record.reason.value} | "
                    f"P&L: ${record.profit_loss:.2f}"
                )
        
        return training_eligible, excluded
    
    def get_training_dataset_stats(self, 
                                  exit_records: List[ExitRecord]) -> Dict:
        """
        Analyze the training dataset composition.
        
        Returns metrics about what's included vs excluded.
        """
        training, excluded = self.filter_for_training(exit_records)
        
        # Group by reason
        reason_breakdown = {}
        for record in exit_records:
            reason_key = record.reason.value
            if reason_key not in reason_breakdown:
                reason_breakdown[reason_key] = {
                    'count': 0,
                    'total_pnl': 0.0,
                    'win_rate': 0.0,
                    'included_in_training': record.reason.is_market_driven
                }
            reason_breakdown[reason_key]['count'] += 1
            reason_breakdown[reason_key]['total_pnl'] += record.profit_loss
        
        # Calculate win rates
        for reason_key, data in reason_breakdown.items():
            wins = sum(1 for r in exit_records 
                      if r.reason.value == reason_key and r.profit_loss > 0)
            data['win_rate'] = (wins / data['count'] * 100) if data['count'] > 0 else 0.0
        
        return {
            'total_records': len(exit_records),
            'training_eligible': len(training),
            'excluded_from_training': len(excluded),
            'pct_training': (len(training) / len(exit_records) * 100) if exit_records else 0,
            'training_total_pnl': sum(r.profit_loss for r in training),
            'excluded_total_pnl': sum(r.profit_loss for r in excluded),
            'training_win_rate': (sum(1 for r in training if r.profit_loss > 0) / len(training) * 100) if training else 0,
            'excluded_win_rate': (sum(1 for r in excluded if r.profit_loss > 0) / len(excluded) * 100) if excluded else 0,
            'reason_breakdown': reason_breakdown,
        }
    
    def prepare_training_records(self, 
                                exit_records: List[ExitRecord],
                                historical_data: Dict[str, List[MarketData]]
                                ) -> List[Dict]:
        """
        Convert filtered exit records into training samples.
        
        Each training sample should contain:
        - Entry features (price, volatility, trend at entry)
        - Holding period (how long until market exit)
        - Exit type (TP, SL, or trailing stop)
        - Market outcome (pips gained/lost)
        
        Args:
            exit_records: All trade exits
            historical_data: Historical market data by symbol
        
        Returns:
            List of training samples (dicts)
        """
        training, _ = self.filter_for_training(exit_records)
        samples = []
        
        for record in training:
            # Only process if we have historical data for this symbol
            if record.symbol not in historical_data:
                self.logger.debug(
                    f"[TRAINING PREP] Skipping {record.symbol} - no historical data"
                )
                continue
            
            sample = {
                'symbol': record.symbol,
                'direction': record.direction,
                'entry_price': record.entry_price,
                'entry_time': record.entry_time,
                'exit_price': record.exit_price,
                'exit_time': record.exit_time,
                'exit_reason': record.reason.value,
                
                # Outcome metrics
                'profit_loss': record.profit_loss,
                'profit_loss_pips': record.profit_loss_pips,
                'hold_time_seconds': record.hold_time_seconds,
                'is_win': record.profit_loss > 0,
                
                # Risk metrics
                'max_profit_during_hold': record.max_profit_during_hold,
                'max_loss_during_hold': record.max_loss_during_hold,
                
                # For analysis
                'position_id': record.position_id,
            }
            samples.append(sample)
        
        self.logger.info(
            "[TRAINING PREP] Prepared %d market-driven samples for training "
            "(%d records excluded as administrative)",
            len(samples), len(exit_records) - len(samples)
        )
        
        return samples


class TrainingDataValidator:
    """
    Validates that training data is clean and suitable for model training.
    """
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger(__name__)
    
    def validate_dataset(self, training_records: List[Dict]) -> Dict[str, bool]:
        """
        Check that the training dataset meets quality standards.
        
        Returns dict of validation results.
        """
        results = {
            'has_minimum_samples': len(training_records) >= 50,  # Need at least 50 trades
            'has_mixed_outcomes': False,  # Should have both wins and losses
            'has_reasonable_distribution': False,  # Should not be all one direction
            'win_rate_realistic': False,  # Should be 30-70% range
        }
        
        if not training_records:
            return results
        
        # Check for mixed outcomes
        wins = sum(1 for r in training_records if r['is_win'])
        losses = len(training_records) - wins
        results['has_mixed_outcomes'] = wins > 0 and losses > 0
        
        # Check direction distribution
        longs = sum(1 for r in training_records if r['direction'] == 'LONG')
        shorts = len(training_records) - longs
        pct_long = (longs / len(training_records) * 100) if training_records else 0
        results['has_reasonable_distribution'] = 20 < pct_long < 80  # 20-80 split
        
        # Check win rate
        win_rate = wins / len(training_records) if training_records else 0
        results['win_rate_realistic'] = 0.3 <= win_rate <= 0.7
        
        # Log results
        all_pass = all(results.values())
        status = "✅ PASS" if all_pass else "⚠️ WARNING"
        
        self.logger.info(
            f"{status} Training Data Validation | "
            f"Samples: {len(training_records)} | "
            f"Win Rate: {win_rate:.1%} | "
            f"Long: {pct_long:.1f}% | "
            f"Mixed Outcomes: {results['has_mixed_outcomes']}"
        )
        
        return results
