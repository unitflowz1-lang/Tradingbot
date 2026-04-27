"""
Multi-Currency Pair Trading Environment

This module implements a trading environment that supports multiple currency pairs
simultaneously, with cross-pair correlation features and currency-specific
normalization and feature engineering.
"""

import numpy as np
from typing import Tuple, Dict, Any, Optional, List, Set
import pandas as pd
from datetime import datetime, timedelta
from collections import defaultdict
import logging
import random

from .base import TradingEnvironment, EnvironmentConfig, ActionType, PortfolioState
from .state_processor import StateProcessor
from .reward_calculator import RewardCalculator
from ...models import MarketData


logger = logging.getLogger(__name__)


class MultiPairEnvironmentConfig(EnvironmentConfig):
    """Extended configuration for multi-pair environment"""
    
    def __init__(self, 
                 currency_pairs: List[str],
                 correlation_lookback: int = 50,
                 pair_weights: Optional[Dict[str, float]] = None,
                 enable_cross_pair_features: bool = True,
                 **kwargs):
        super().__init__(**kwargs)
        self.currency_pairs = currency_pairs
        self.correlation_lookback = correlation_lookback
        self.pair_weights = pair_weights or {pair: 1.0 for pair in currency_pairs}
        self.enable_cross_pair_features = enable_cross_pair_features
        
        # Validate configuration
        self._validate_config()
        
    def _validate_config(self):
        """Validate multi-pair configuration"""
        if not self.currency_pairs:
            raise ValueError("Currency pairs list cannot be empty")
            
        if len(self.currency_pairs) < 2:
            raise ValueError("Multi-pair environment requires at least 2 currency pairs")
            
        # Validate pair weights
        for pair in self.currency_pairs:
            if pair not in self.pair_weights:
                raise ValueError(f"Missing weight for currency pair: {pair}")
                
        # Normalize weights
        total_weight = sum(self.pair_weights.values())
        if total_weight <= 0:
            raise ValueError("Total pair weights must be positive")
            
        self.pair_weights = {
            pair: weight / total_weight 
            for pair, weight in self.pair_weights.items()
        }


class MultiPairPortfolioState(PortfolioState):
    """Extended portfolio state for multi-pair trading"""
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Per-pair positions and metrics
        self.pair_positions: Dict[str, float] = {}
        self.pair_unrealized_pnl: Dict[str, float] = {}
        self.pair_realized_pnl: Dict[str, float] = {}
        self.pair_trades: Dict[str, int] = {}
        self.pair_winning_trades: Dict[str, int] = {}
        self.pair_entry_prices: Dict[str, float] = {}
        
    def get_total_position_exposure(self) -> float:
        """Calculate total position exposure across all pairs"""
        return sum(abs(pos) for pos in self.pair_positions.values())
        
    def get_pair_win_rate(self, pair: str) -> float:
        """Get win rate for specific currency pair"""
        total_trades = self.pair_trades.get(pair, 0)
        if total_trades == 0:
            return 0.0
        return self.pair_winning_trades.get(pair, 0) / total_trades
        
    def get_diversification_score(self) -> float:
        """Calculate portfolio diversification score (0-1)"""
        positions = list(self.pair_positions.values())
        if not positions:
            return 1.0
            
        # Calculate concentration using Herfindahl index
        total_exposure = sum(abs(pos) for pos in positions)
        if total_exposure == 0:
            return 1.0
            
        weights = [abs(pos) / total_exposure for pos in positions]
        herfindahl = sum(w**2 for w in weights)
        
        # Convert to diversification score (1 = perfectly diversified)
        max_herfindahl = 1.0  # All in one pair
        min_herfindahl = 1.0 / len(positions)  # Equally distributed
        
        if max_herfindahl == min_herfindahl:
            return 1.0
            
        return 1.0 - (herfindahl - min_herfindahl) / (max_herfindahl - min_herfindahl)


class MultiPairTradingEnvironment(TradingEnvironment):
    """
    Multi-currency pair trading environment.
    
    Supports simultaneous trading across multiple currency pairs with
    cross-pair correlation features and currency-specific processing.
    """
    
    def __init__(self,
                 market_data: Dict[str, List[MarketData]],
                 config: MultiPairEnvironmentConfig,
                 state_processor: Optional[StateProcessor] = None,
                 reward_calculator: Optional[RewardCalculator] = None):
        """
        Initialize multi-pair trading environment.
        
        Args:
            market_data: Dictionary mapping currency pairs to market data lists
            config: Multi-pair environment configuration
            state_processor: Optional custom state processor
            reward_calculator: Optional custom reward calculator
        """
        # Initialize base class with dummy config for compatibility
        base_config = EnvironmentConfig(
            state_features=config.state_features,
            action_space_type=config.action_space_type,
            reward_function=config.reward_function,
            lookback_window=config.lookback_window,
            normalization_method=config.normalization_method,
            transaction_cost=config.transaction_cost,
            max_position_size=config.max_position_size,
            initial_balance=config.initial_balance,
            max_episode_steps=config.max_episode_steps,
            min_episode_steps=config.min_episode_steps
        )
        
        super().__init__(base_config)
        
        self.multi_config = config
        self.market_data = market_data
        self.currency_pairs = config.currency_pairs
        
        # Validate market data
        self._validate_market_data()
        
        # Initialize processors
        self.state_processor = state_processor or self._create_default_state_processor()
        self.reward_calculator = reward_calculator or self._create_default_reward_calculator()
        
        # Multi-pair specific attributes
        self.current_data_indices = {pair: 0 for pair in self.currency_pairs}
        self.episode_start_indices = {pair: 0 for pair in self.currency_pairs}
        self.correlation_matrix = np.eye(len(self.currency_pairs))
        self.pair_volatilities = {pair: 0.0 for pair in self.currency_pairs}
        
        # Action space: each pair can have independent actions
        self.pair_action_space_size = len(ActionType)
        self.total_action_space_size = self.pair_action_space_size ** len(self.currency_pairs)
        
        # Initialize random number generator
        self.np_random = np.random.RandomState()
        
        # Initialize multi-pair portfolio
        self.portfolio = MultiPairPortfolioState(
            balance=config.initial_balance,
            equity=config.initial_balance,
            current_position=0.0,
            unrealized_pnl=0.0,
            realized_pnl=0.0,
            total_trades=0,
            winning_trades=0,
            max_drawdown=0.0,
            current_drawdown=0.0
        )
        
        # Initialize pair-specific portfolio data
        for pair in self.currency_pairs:
            self.portfolio.pair_positions[pair] = 0.0
            self.portfolio.pair_unrealized_pnl[pair] = 0.0
            self.portfolio.pair_realized_pnl[pair] = 0.0
            self.portfolio.pair_trades[pair] = 0
            self.portfolio.pair_winning_trades[pair] = 0
            self.portfolio.pair_entry_prices[pair] = 0.0
            
        logger.info(f"Initialized multi-pair environment with {len(self.currency_pairs)} pairs: {self.currency_pairs}")
        
    def reset(self) -> np.ndarray:
        """Reset environment for new episode."""
        # Reset base environment state
        self.current_step = 0
        self.done = False
        self.info = {}
        
        # Reset multi-pair portfolio
        self.portfolio = MultiPairPortfolioState(
            balance=self.config.initial_balance,
            equity=self.config.initial_balance,
            current_position=0.0,
            unrealized_pnl=0.0,
            realized_pnl=0.0,
            total_trades=0,
            winning_trades=0,
            max_drawdown=0.0,
            current_drawdown=0.0
        )
        
        # Initialize pair-specific data
        for pair in self.currency_pairs:
            self.portfolio.pair_positions[pair] = 0.0
            self.portfolio.pair_unrealized_pnl[pair] = 0.0
            self.portfolio.pair_realized_pnl[pair] = 0.0
            self.portfolio.pair_trades[pair] = 0
            self.portfolio.pair_winning_trades[pair] = 0
            self.portfolio.pair_entry_prices[pair] = 0.0
            
        # Reset tracking variables
        self.episode_start_balance = self.config.initial_balance
        self.peak_equity = self.config.initial_balance
        
        # Select random episode start points for each pair
        for pair in self.currency_pairs:
            data_length = len(self.market_data[pair])
            max_start_idx = data_length - self.config.max_episode_steps - self.config.lookback_window
            
            if max_start_idx <= 0:
                raise ValueError(f"Not enough market data for pair {pair}")
                
            start_idx = self.np_random.randint(0, max_start_idx)
            self.episode_start_indices[pair] = start_idx
            self.current_data_indices[pair] = start_idx + self.config.lookback_window
            
        # Update correlation matrix and volatilities
        self._update_correlation_matrix()
        self._update_pair_volatilities()
        
        # Get initial state
        initial_state = self._get_current_state()
        
        return initial_state
        
    def step(self, action: int) -> Tuple[np.ndarray, float, bool, Dict[str, Any]]:
        """
        Execute multi-pair action and advance environment.
        
        Args:
            action: Encoded action for all currency pairs
            
        Returns:
            Tuple of (next_state, reward, done, info)
        """
        if self.done:
            raise RuntimeError("Episode is done. Call reset() to start new episode.")
            
        # Decode action into per-pair actions
        pair_actions = self._decode_multi_pair_action(action)
        
        # Store previous portfolio state
        prev_portfolio = self._copy_portfolio_state()
        
        # Get current market data for all pairs
        current_market_data = {}
        for pair in self.currency_pairs:
            if self.current_data_indices[pair] < len(self.market_data[pair]):
                current_market_data[pair] = self.market_data[pair][self.current_data_indices[pair]]
            else:
                # Use last available data if we've run out
                current_market_data[pair] = self.market_data[pair][-1]
                
        # Execute actions for each pair
        execution_info = {}
        for pair, pair_action in pair_actions.items():
            if pair in current_market_data:
                execution_info[pair] = self._execute_pair_action(
                    pair, pair_action, current_market_data[pair].close
                )
                
        # Update unrealized P&L for all pairs
        for pair in self.currency_pairs:
            if pair in current_market_data:
                self._update_pair_unrealized_pnl(pair, current_market_data[pair].close)
                
        # Update overall portfolio metrics
        self._update_portfolio_totals()
        self._update_equity_and_drawdown()
        
        # Calculate reward
        reward = self.reward_calculator.calculate_reward(
            prev_portfolio, self.portfolio, action, current_market_data
        )
        
        # Advance to next step
        self.current_step += 1
        for pair in self.currency_pairs:
            self.current_data_indices[pair] += 1
            
        # Check termination conditions
        done, termination_reason = self._check_episode_termination()
        
        # Check if any pair has run out of data
        for pair in self.currency_pairs:
            if self.current_data_indices[pair] >= len(self.market_data[pair]):
                done = True
                termination_reason = f"end_of_data_{pair}"
                break
                
        self.done = done
        
        # Get next state
        if not done:
            next_state = self._get_current_state()
            # Update correlation matrix periodically
            if self.current_step % 10 == 0:
                self._update_correlation_matrix()
                self._update_pair_volatilities()
        else:
            next_state = np.zeros(self.get_observation_space_shape()[0])
            
        # Create comprehensive info dictionary
        info = self.get_info_dict()
        info.update({
            'pair_actions': pair_actions,
            'execution_info': execution_info,
            'termination_reason': termination_reason,
            'current_prices': {pair: data.close for pair, data in current_market_data.items()},
            'correlation_matrix': self.correlation_matrix.tolist(),
            'pair_volatilities': self.pair_volatilities,
            'diversification_score': self.portfolio.get_diversification_score(),
            'total_exposure': self.portfolio.get_total_position_exposure()
        })
        
        return next_state, reward, done, info
        
    def get_observation_space_shape(self) -> Tuple[int, ...]:
        """Get shape of multi-pair observation space."""
        return (self.state_processor.get_state_dimension(),)
        
    def get_action_space_size(self) -> int:
        """Get size of multi-pair action space."""
        return self.total_action_space_size
        
    def _decode_multi_pair_action(self, action: int) -> Dict[str, int]:
        """
        Decode single action integer into per-pair actions.
        
        Args:
            action: Encoded action for all pairs
            
        Returns:
            Dictionary mapping pair names to action indices
        """
        if action >= self.total_action_space_size:
            raise ValueError(f"Invalid action: {action}")
            
        pair_actions = {}
        remaining_action = action
        
        for i, pair in enumerate(self.currency_pairs):
            pair_action = remaining_action % self.pair_action_space_size
            pair_actions[pair] = pair_action
            remaining_action //= self.pair_action_space_size
            
        return pair_actions
        
    def _execute_pair_action(self, pair: str, action: int, current_price: float) -> Dict[str, Any]:
        """Execute action for specific currency pair."""
        action_type = ActionType(action)
        execution_info = {
            'pair': pair,
            'action_type': action_type.name,
            'executed': False,
            'position_change': 0.0,
            'transaction_cost': 0.0,
            'error': None
        }
        
        try:
            if action_type == ActionType.HOLD:
                execution_info['executed'] = True
                
            elif action_type == ActionType.CLOSE_POSITION:
                if abs(self.portfolio.pair_positions[pair]) > 1e-6:
                    self._close_pair_position(pair, current_price)
                    execution_info['executed'] = True
                    execution_info['position_change'] = -self.portfolio.pair_positions[pair]
                    
            else:
                # Execute buy/sell action for this pair
                position_change = self.action_sizes[action_type]
                new_position = self.portfolio.pair_positions[pair] + position_change
                
                # Check position limits (per pair and total)
                if (abs(new_position) <= self.config.max_position_size and
                    self.portfolio.get_total_position_exposure() + abs(position_change) <= 
                    self.config.max_position_size * len(self.currency_pairs)):
                    
                    self._update_pair_position(pair, position_change, current_price)
                    execution_info['executed'] = True
                    execution_info['position_change'] = position_change
                    execution_info['transaction_cost'] = (
                        abs(position_change) * self.config.transaction_cost
                    )
                else:
                    execution_info['error'] = 'Position limit exceeded'
                    
        except Exception as e:
            execution_info['error'] = str(e)
            logger.error(f"Error executing action for {pair}: {e}")
            
        return execution_info
        
    def _update_pair_position(self, pair: str, position_change: float, current_price: float) -> None:
        """Update position for specific currency pair."""
        # Calculate transaction cost
        transaction_cost = (
            abs(position_change) * self.config.transaction_cost * 
            self.portfolio.balance * self.multi_config.pair_weights[pair]
        )
        
        # Update position
        old_position = self.portfolio.pair_positions[pair]
        self.portfolio.pair_positions[pair] += position_change
        
        # Track entry price for new positions
        if abs(old_position) < 1e-6 and abs(self.portfolio.pair_positions[pair]) > 1e-6:
            self.portfolio.pair_entry_prices[pair] = current_price
            
        # Update balance (subtract transaction costs)
        self.portfolio.balance -= transaction_cost
        
        # Update trade count
        if abs(position_change) > 1e-6:
            self.portfolio.pair_trades[pair] += 1
            
    def _close_pair_position(self, pair: str, current_price: float) -> None:
        """Close position for specific currency pair."""
        if abs(self.portfolio.pair_positions[pair]) < 1e-6:
            return
            
        # Calculate realized P&L
        entry_price = self.portfolio.pair_entry_prices[pair]
        if entry_price > 0:
            price_change = current_price - entry_price
            pnl = (
                self.portfolio.pair_positions[pair] * price_change * 
                self.portfolio.balance * self.multi_config.pair_weights[pair]
            )
            
            # Update realized P&L
            self.portfolio.pair_realized_pnl[pair] += pnl
            self.portfolio.balance += pnl
            
            # Track winning trades
            if pnl > 0:
                self.portfolio.pair_winning_trades[pair] += 1
                
        # Reset position
        self.portfolio.pair_positions[pair] = 0.0
        self.portfolio.pair_entry_prices[pair] = 0.0
        
    def _update_pair_unrealized_pnl(self, pair: str, current_price: float) -> None:
        """Update unrealized P&L for specific pair."""
        position = self.portfolio.pair_positions[pair]
        entry_price = self.portfolio.pair_entry_prices[pair]
        
        if abs(position) < 1e-6 or entry_price <= 0:
            self.portfolio.pair_unrealized_pnl[pair] = 0.0
            return
            
        price_change = current_price - entry_price
        self.portfolio.pair_unrealized_pnl[pair] = (
            position * price_change * self.portfolio.balance * 
            self.multi_config.pair_weights[pair]
        )
        
    def _update_portfolio_totals(self) -> None:
        """Update total portfolio metrics from pair-specific data."""
        # Update total position (weighted average)
        total_weighted_position = sum(
            self.portfolio.pair_positions[pair] * self.multi_config.pair_weights[pair]
            for pair in self.currency_pairs
        )
        self.portfolio.current_position = total_weighted_position
        
        # Update total unrealized P&L
        self.portfolio.unrealized_pnl = sum(self.portfolio.pair_unrealized_pnl.values())
        
        # Update total realized P&L
        self.portfolio.realized_pnl = sum(self.portfolio.pair_realized_pnl.values())
        
        # Update total trades
        self.portfolio.total_trades = sum(self.portfolio.pair_trades.values())
        
        # Update total winning trades
        self.portfolio.winning_trades = sum(self.portfolio.pair_winning_trades.values())
        
    def _update_correlation_matrix(self) -> None:
        """Update correlation matrix between currency pairs."""
        if self.current_step < self.multi_config.correlation_lookback:
            return
            
        try:
            # Collect price data for correlation calculation
            price_data = {}
            
            for pair in self.currency_pairs:
                start_idx = max(0, self.current_data_indices[pair] - self.multi_config.correlation_lookback)
                end_idx = self.current_data_indices[pair]
                
                if end_idx <= start_idx:
                    continue
                    
                pair_data = self.market_data[pair][start_idx:end_idx]
                prices = [data.close for data in pair_data]
                
                if len(prices) > 1:
                    # Calculate returns
                    returns = np.diff(prices) / prices[:-1]
                    price_data[pair] = returns
                    
            # Calculate correlation matrix
            if len(price_data) >= 2:
                pairs_list = list(price_data.keys())
                n_pairs = len(pairs_list)
                correlation_matrix = np.eye(n_pairs)
                
                for i in range(n_pairs):
                    for j in range(i + 1, n_pairs):
                        pair1, pair2 = pairs_list[i], pairs_list[j]
                        returns1, returns2 = price_data[pair1], price_data[pair2]
                        
                        # Ensure same length
                        min_len = min(len(returns1), len(returns2))
                        if min_len > 1:
                            corr = np.corrcoef(returns1[:min_len], returns2[:min_len])[0, 1]
                            if not np.isnan(corr):
                                correlation_matrix[i, j] = corr
                                correlation_matrix[j, i] = corr
                                
                self.correlation_matrix = correlation_matrix
                
        except Exception as e:
            logger.warning(f"Error updating correlation matrix: {e}")
            
    def _update_pair_volatilities(self) -> None:
        """Update volatility estimates for each currency pair."""
        lookback = min(self.multi_config.correlation_lookback, self.current_step)
        
        for pair in self.currency_pairs:
            try:
                start_idx = max(0, self.current_data_indices[pair] - lookback)
                end_idx = self.current_data_indices[pair]
                
                if end_idx <= start_idx:
                    continue
                    
                pair_data = self.market_data[pair][start_idx:end_idx]
                prices = [data.close for data in pair_data]
                
                if len(prices) > 1:
                    returns = np.diff(prices) / prices[:-1]
                    volatility = np.std(returns) * np.sqrt(252)  # Annualized
                    self.pair_volatilities[pair] = volatility
                    
            except Exception as e:
                logger.warning(f"Error updating volatility for {pair}: {e}")
                
    def _validate_market_data(self) -> None:
        """Validate multi-pair market data."""
        if not self.market_data:
            raise ValueError("Market data dictionary cannot be empty")
            
        # Check all required pairs are present
        for pair in self.currency_pairs:
            if pair not in self.market_data:
                raise ValueError(f"Missing market data for currency pair: {pair}")
                
            pair_data = self.market_data[pair]
            if not pair_data:
                raise ValueError(f"Empty market data for currency pair: {pair}")
                
            min_required = self.config.lookback_window + self.config.min_episode_steps
            if len(pair_data) < min_required:
                raise ValueError(
                    f"Insufficient data for {pair}. Need {min_required}, got {len(pair_data)}"
                )
                
            # Validate data is sorted by timestamp
            for i in range(1, len(pair_data)):
                if pair_data[i].timestamp <= pair_data[i-1].timestamp:
                    raise ValueError(f"Market data for {pair} not sorted by timestamp at index {i}")
                    
            # Validate each data point
            for i, data in enumerate(pair_data):
                try:
                    data.validate()
                except Exception as e:
                    raise ValueError(f"Invalid market data for {pair} at index {i}: {e}")
                    
    def _copy_portfolio_state(self) -> MultiPairPortfolioState:
        """Create a copy of current portfolio state."""
        portfolio_copy = MultiPairPortfolioState(
            balance=self.portfolio.balance,
            equity=self.portfolio.equity,
            current_position=self.portfolio.current_position,
            unrealized_pnl=self.portfolio.unrealized_pnl,
            realized_pnl=self.portfolio.realized_pnl,
            total_trades=self.portfolio.total_trades,
            winning_trades=self.portfolio.winning_trades,
            max_drawdown=self.portfolio.max_drawdown,
            current_drawdown=self.portfolio.current_drawdown
        )
        
        # Copy pair-specific data
        portfolio_copy.pair_positions = self.portfolio.pair_positions.copy()
        portfolio_copy.pair_unrealized_pnl = self.portfolio.pair_unrealized_pnl.copy()
        portfolio_copy.pair_realized_pnl = self.portfolio.pair_realized_pnl.copy()
        portfolio_copy.pair_trades = self.portfolio.pair_trades.copy()
        portfolio_copy.pair_winning_trades = self.portfolio.pair_winning_trades.copy()
        portfolio_copy.pair_entry_prices = self.portfolio.pair_entry_prices.copy()
        
        return portfolio_copy
        
    def _get_current_state(self) -> np.ndarray:
        """Get current multi-pair state vector."""
        # Collect current market data for all pairs
        current_market_data = {}
        
        for pair in self.currency_pairs:
            if self.current_data_indices[pair] < len(self.market_data[pair]):
                # Get lookback window for this pair
                start_idx = max(0, self.current_data_indices[pair] - self.config.lookback_window + 1)
                end_idx = self.current_data_indices[pair] + 1
                
                lookback_data = self.market_data[pair][start_idx:end_idx]
                current_market_data[pair] = lookback_data
            else:
                # Return zero state if past end of data
                return np.zeros(self.state_processor.get_state_dimension())
                
        # Process multi-pair state
        return self.state_processor.process_market_data(
            current_market_data, self.portfolio, self.correlation_matrix, self.pair_volatilities
        )
        
    def _create_default_state_processor(self) -> StateProcessor:
        """Create default multi-pair state processor."""
        from .multi_pair_state_processor import MultiPairStateProcessor
        return MultiPairStateProcessor(self.multi_config)
        
    def _create_default_reward_calculator(self) -> RewardCalculator:
        """Create default multi-pair reward calculator."""
        from .multi_pair_reward_calculator import MultiPairRewardCalculator
        return MultiPairRewardCalculator(self.multi_config)
        
    def get_pair_info(self, pair: str) -> Dict[str, Any]:
        """Get detailed information for specific currency pair."""
        if pair not in self.currency_pairs:
            raise ValueError(f"Unknown currency pair: {pair}")
            
        return {
            'position': self.portfolio.pair_positions[pair],
            'unrealized_pnl': self.portfolio.pair_unrealized_pnl[pair],
            'realized_pnl': self.portfolio.pair_realized_pnl[pair],
            'total_trades': self.portfolio.pair_trades[pair],
            'winning_trades': self.portfolio.pair_winning_trades[pair],
            'win_rate': self.portfolio.get_pair_win_rate(pair),
            'entry_price': self.portfolio.pair_entry_prices[pair],
            'volatility': self.pair_volatilities.get(pair, 0.0),
            'weight': self.multi_config.pair_weights[pair]
        }
        
    def get_correlation_info(self) -> Dict[str, Any]:
        """Get correlation matrix and related information."""
        return {
            'correlation_matrix': self.correlation_matrix.tolist(),
            'currency_pairs': self.currency_pairs,
            'diversification_score': self.portfolio.get_diversification_score(),
            'total_exposure': self.portfolio.get_total_position_exposure(),
            'pair_volatilities': self.pair_volatilities
        }
        
    def render(self, mode: str = 'human') -> Optional[Any]:
        """
        Render current multi-pair environment state.
        
        Args:
            mode: Rendering mode ('human', 'rgb_array', etc.)
            
        Returns:
            Rendered output or None
        """
        if mode == 'human':
            print(f"\n=== Multi-Pair Trading Environment State (Step {self.current_step}) ===")
            print(f"Total Balance: ${self.portfolio.balance:.2f}")
            print(f"Total Equity: ${self.portfolio.equity:.2f}")
            print(f"Total Unrealized P&L: ${self.portfolio.unrealized_pnl:.2f}")
            print(f"Total Realized P&L: ${self.portfolio.realized_pnl:.2f}")
            print(f"Total Trades: {self.portfolio.total_trades}")
            print(f"Win Rate: {self.portfolio.winning_trades / max(1, self.portfolio.total_trades):.2%}")
            print(f"Max Drawdown: {self.portfolio.max_drawdown:.2%}")
            print(f"Current Drawdown: {self.portfolio.current_drawdown:.2%}")
            print(f"Diversification Score: {self.portfolio.get_diversification_score():.3f}")
            print(f"Total Exposure: {self.portfolio.get_total_position_exposure():.3f}")
            
            print(f"\n--- Per-Pair Positions ---")
            for pair in self.currency_pairs:
                position = self.portfolio.pair_positions.get(pair, 0.0)
                unrealized_pnl = self.portfolio.pair_unrealized_pnl.get(pair, 0.0)
                trades = self.portfolio.pair_trades.get(pair, 0)
                win_rate = self.portfolio.get_pair_win_rate(pair)
                
                print(f"{pair}: Position={position:.4f}, P&L=${unrealized_pnl:.2f}, "
                      f"Trades={trades}, Win Rate={win_rate:.2%}")
                      
            print(f"\n--- Current Prices ---")
            for pair in self.currency_pairs:
                if self.current_data_indices[pair] < len(self.market_data[pair]):
                    current_data = self.market_data[pair][self.current_data_indices[pair]]
                    print(f"{pair}: ${current_data.close:.5f} (Spread: {current_data.spread:.5f})")
                    
        elif mode == 'rgb_array':
            # Could implement matplotlib visualization here
            return None
            
        return None
        
    def seed(self, seed: Optional[int] = None) -> List[int]:
        """Set random seed for reproducibility."""
        if seed is None:
            seed = random.randint(0, 2**32 - 1)
            
        self.np_random = np.random.RandomState(seed)
        random.seed(seed)
        np.random.seed(seed)
        
        return [seed]