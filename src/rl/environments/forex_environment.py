"""
Forex Trading Environment Implementation

This module implements a concrete trading environment for forex markets
that RL agents can use to learn trading strategies.
"""

import numpy as np
from typing import Tuple, Dict, Any, Optional, List
import pandas as pd
from datetime import datetime, timedelta
import random

from .base import TradingEnvironment, EnvironmentConfig, ActionType, PortfolioState
from .state_processor import StateProcessor
from .reward_calculator import RewardCalculator
from ...models import MarketData


class ForexTradingEnvironment(TradingEnvironment):
    """
    Concrete implementation of trading environment for forex markets.
    
    This environment simulates forex trading with realistic market conditions,
    transaction costs, and portfolio management constraints.
    """
    
    def __init__(self, 
                 market_data: List[MarketData],
                 config: EnvironmentConfig,
                 state_processor: Optional[StateProcessor] = None,
                 reward_calculator: Optional[RewardCalculator] = None):
        """
        Initialize forex trading environment.
        
        Args:
            market_data: List of historical market data
            config: Environment configuration
            state_processor: Optional custom state processor
            reward_calculator: Optional custom reward calculator
        """
        super().__init__(config)
        
        self.market_data = market_data
        self.data_length = len(market_data)
        
        # Initialize processors
        self.state_processor = state_processor or self._create_default_state_processor()
        self.reward_calculator = reward_calculator or self._create_default_reward_calculator()
        
        # Episode management
        self.episode_start_idx = 0
        self.current_data_idx = 0
        self.episode_data = []
        
        # State management
        self.state_history = []
        self.action_history = []
        self.reward_history = []
        
        # Random seed
        self.np_random = np.random.RandomState()
        
        # Validate data
        self._validate_market_data()
        
    def reset(self) -> np.ndarray:
        """
        Reset environment to start of new episode.
        
        Returns:
            Initial state observation
        """
        # Reset step counter and flags
        self.current_step = 0
        self.done = False
        self.info = {}
        
        # Reset portfolio to initial state
        self.portfolio = PortfolioState(
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
        
        # Reset tracking variables
        self.episode_start_balance = self.config.initial_balance
        self.peak_equity = self.config.initial_balance
        self.last_action = ActionType.HOLD
        self.position_entry_price = 0.0
        
        # Select random episode start point
        max_start_idx = self.data_length - self.config.max_episode_steps - self.config.lookback_window
        if max_start_idx <= 0:
            raise ValueError("Not enough market data for episode length and lookback window")
            
        self.episode_start_idx = self.np_random.randint(0, max_start_idx)
        self.current_data_idx = self.episode_start_idx + self.config.lookback_window
        
        # Clear history
        self.state_history = []
        self.action_history = []
        self.reward_history = []
        
        # Get initial state
        initial_state = self._get_current_state()
        self.state_history.append(initial_state)
        
        return initial_state
        
    def step(self, action: int) -> Tuple[np.ndarray, float, bool, Dict[str, Any]]:
        """
        Execute action and advance environment by one step.
        
        Args:
            action: Action index to execute
            
        Returns:
            Tuple of (next_state, reward, done, info)
        """
        if self.done:
            raise RuntimeError("Episode is done. Call reset() to start new episode.")
            
        if action < 0 or action >= len(ActionType):
            raise ValueError(f"Invalid action: {action}. Must be in range [0, {len(ActionType)-1}]")
            
        # Get current market data
        current_market_data = self.market_data[self.current_data_idx]
        current_price = current_market_data.close
        
        # Store previous portfolio state for reward calculation
        prev_portfolio = PortfolioState(
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
        
        # Execute action
        execution_info = self._execute_action(action, current_price)
        self.last_action = ActionType(action)
        
        # Update unrealized P&L and equity
        self._update_unrealized_pnl(current_price)
        self._update_equity_and_drawdown()
        
        # Calculate reward
        reward = self.reward_calculator.calculate_reward(
            prev_portfolio, self.portfolio, action, current_market_data
        )
        
        # Advance to next step
        self.current_step += 1
        self.current_data_idx += 1
        
        # Check if episode should terminate
        done, termination_reason = self._check_episode_termination()
        
        # Check if we've run out of data
        if self.current_data_idx >= self.data_length:
            done = True
            termination_reason = "end_of_data"
            
        self.done = done
        
        # Get next state (if not done)
        if not done:
            next_state = self._get_current_state()
        else:
            # Return zeros for terminal state
            next_state = np.zeros(self.get_observation_space_shape()[0])
            
        # Store history
        self.action_history.append(action)
        self.reward_history.append(reward)
        self.state_history.append(next_state)
        
        # Create info dictionary
        info = self.get_info_dict()
        info.update({
            'execution_info': execution_info,
            'termination_reason': termination_reason,
            'current_price': current_price,
            'market_data': {
                'timestamp': current_market_data.timestamp,
                'open': current_market_data.open,
                'high': current_market_data.high,
                'low': current_market_data.low,
                'close': current_market_data.close,
                'volume': current_market_data.volume
            }
        })
        
        return next_state, reward, done, info
        
    def render(self, mode: str = 'human') -> Optional[Any]:
        """
        Render current environment state.
        
        Args:
            mode: Rendering mode ('human', 'rgb_array', etc.)
            
        Returns:
            Rendered output or None
        """
        if mode == 'human':
            print(f"\n=== Trading Environment State (Step {self.current_step}) ===")
            print(f"Balance: ${self.portfolio.balance:.2f}")
            print(f"Equity: ${self.portfolio.equity:.2f}")
            print(f"Position: {self.portfolio.current_position:.4f}")
            print(f"Unrealized P&L: ${self.portfolio.unrealized_pnl:.2f}")
            print(f"Realized P&L: ${self.portfolio.realized_pnl:.2f}")
            print(f"Total Trades: {self.portfolio.total_trades}")
            print(f"Win Rate: {self.portfolio.winning_trades / max(1, self.portfolio.total_trades):.2%}")
            print(f"Max Drawdown: {self.portfolio.max_drawdown:.2%}")
            print(f"Current Drawdown: {self.portfolio.current_drawdown:.2%}")
            print(f"Last Action: {self.last_action.name}")
            
            if self.current_data_idx < len(self.market_data):
                current_data = self.market_data[self.current_data_idx]
                print(f"Current Price: ${current_data.close:.5f}")
                print(f"Timestamp: {current_data.timestamp}")
                
        elif mode == 'rgb_array':
            # Could implement matplotlib visualization here
            return None
            
        return None
        
    def get_observation_space_shape(self) -> Tuple[int, ...]:
        """Get shape of observation space."""
        return (self.state_processor.get_state_dimension(),)
        
    def get_action_space_size(self) -> int:
        """Get size of action space."""
        return len(ActionType)
        
    def seed(self, seed: Optional[int] = None) -> List[int]:
        """Set random seed for reproducibility."""
        if seed is None:
            seed = random.randint(0, 2**32 - 1)
            
        self.np_random = np.random.RandomState(seed)
        random.seed(seed)
        np.random.seed(seed)
        
        return [seed]
        
    def _get_current_state(self) -> np.ndarray:
        """Get current state vector."""
        if self.current_data_idx >= len(self.market_data):
            # Return zero state if we're past the end of data
            return np.zeros(self.state_processor.get_state_dimension())
            
        # Get lookback window of market data
        start_idx = max(0, self.current_data_idx - self.config.lookback_window + 1)
        end_idx = self.current_data_idx + 1
        
        lookback_data = self.market_data[start_idx:end_idx]
        
        # Process state using state processor
        return self.state_processor.process_market_data(
            lookback_data, self.portfolio
        )
        
    def _validate_market_data(self) -> None:
        """Validate that market data is sufficient and properly formatted."""
        if not self.market_data:
            raise ValueError("Market data cannot be empty")
            
        if len(self.market_data) < self.config.lookback_window + self.config.min_episode_steps:
            raise ValueError(
                f"Insufficient market data. Need at least {self.config.lookback_window + self.config.min_episode_steps} "
                f"data points, got {len(self.market_data)}"
            )
            
        # Check data is sorted by timestamp
        for i in range(1, len(self.market_data)):
            if self.market_data[i].timestamp <= self.market_data[i-1].timestamp:
                raise ValueError(f"Market data must be sorted by timestamp. Issue at index {i}")
                
        # Validate each data point
        for i, data in enumerate(self.market_data):
            try:
                data.validate()
            except Exception as e:
                raise ValueError(f"Invalid market data at index {i}: {e}")
                
    def _create_default_state_processor(self) -> StateProcessor:
        """Create default state processor if none provided."""
        from .state_processor import DefaultStateProcessor
        return DefaultStateProcessor(self.config)
        
    def _create_default_reward_calculator(self) -> RewardCalculator:
        """Create default reward calculator if none provided."""
        from .reward_calculator import DefaultRewardCalculator
        return DefaultRewardCalculator(self.config)
        
    def get_episode_summary(self) -> Dict[str, Any]:
        """Get summary statistics for completed episode."""
        if not self.done:
            raise RuntimeError("Episode not completed yet")
            
        total_return = (self.portfolio.equity - self.episode_start_balance) / self.episode_start_balance
        
        return {
            'episode_length': self.current_step,
            'total_return': total_return,
            'final_balance': self.portfolio.balance,
            'final_equity': self.portfolio.equity,
            'realized_pnl': self.portfolio.realized_pnl,
            'unrealized_pnl': self.portfolio.unrealized_pnl,
            'total_trades': self.portfolio.total_trades,
            'winning_trades': self.portfolio.winning_trades,
            'win_rate': self.portfolio.winning_trades / max(1, self.portfolio.total_trades),
            'max_drawdown': self.portfolio.max_drawdown,
            'sharpe_ratio': self._calculate_sharpe_ratio(),
            'total_reward': sum(self.reward_history),
            'avg_reward': np.mean(self.reward_history) if self.reward_history else 0.0,
            'reward_std': np.std(self.reward_history) if self.reward_history else 0.0
        }
        
    def _calculate_sharpe_ratio(self) -> float:
        """Calculate Sharpe ratio for the episode."""
        if len(self.reward_history) < 2:
            return 0.0
            
        returns = np.array(self.reward_history)
        if np.std(returns) == 0:
            return 0.0
            
        return np.mean(returns) / np.std(returns) * np.sqrt(252)  # Annualized
        
    def get_state_history(self) -> List[np.ndarray]:
        """Get history of states for analysis."""
        return self.state_history.copy()
        
    def get_action_history(self) -> List[int]:
        """Get history of actions for analysis."""
        return self.action_history.copy()
        
    def get_reward_history(self) -> List[float]:
        """Get history of rewards for analysis."""
        return self.reward_history.copy()