"""
Base Trading Environment for Reinforcement Learning

This module defines the abstract base class for trading environments
that RL agents interact with to learn trading strategies.
"""

from abc import ABC, abstractmethod
from typing import Tuple, Dict, Any, Optional, List
import numpy as np
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import random

from ...models import MarketData, Portfolio


class ActionType(Enum):
    """Discrete trading actions"""
    HOLD = 0
    BUY_SMALL = 1    # 0.5% position
    BUY_MEDIUM = 2   # 1.0% position  
    BUY_LARGE = 3    # 2.0% position
    SELL_SMALL = 4   # -0.5% position
    SELL_MEDIUM = 5  # -1.0% position
    SELL_LARGE = 6   # -2.0% position
    CLOSE_POSITION = 7


@dataclass
class EnvironmentConfig:
    """Configuration for trading environment"""
    state_features: List[str]
    action_space_type: str  # 'discrete' or 'continuous'
    reward_function: str
    lookback_window: int
    normalization_method: str
    transaction_cost: float
    max_position_size: float
    initial_balance: float
    max_episode_steps: int = 1000
    min_episode_steps: int = 100


@dataclass
class PortfolioState:
    """Simplified portfolio state for RL environment"""
    balance: float
    equity: float
    current_position: float  # -1 to 1 (short to long)
    unrealized_pnl: float
    realized_pnl: float
    total_trades: int
    winning_trades: int
    max_drawdown: float
    current_drawdown: float
    mfe: float = 0.0          # Max Favorable Excursion (highest unrealized profit)
    mae: float = 0.0          # Max Adverse Excursion (highest unrealized loss)
    entry_price: float = 0.0  # Average entry price of current position
    active_exit_policy: str = "STANDARD" # Current active exit policy
    last_regret: float = 0.0  # Regret from last closed trade (R-multiples)
    opportunity_cost_regret: float = 0.0  # Opportunity cost from entering vs waiting


class TradingEnvironment(ABC):
    """
    Abstract base class for trading environments.
    
    Follows OpenAI Gym interface for compatibility with RL libraries.
    Provides market simulation capabilities for training RL agents.
    """
    
    def __init__(self, config: EnvironmentConfig):
        self.config = config
        self.current_step = 0
        self.done = False
        self.info = {}
        
        # Action space mapping
        self.action_sizes = {
            ActionType.HOLD: 0.0,
            ActionType.BUY_SMALL: 0.005,
            ActionType.BUY_MEDIUM: 0.01,
            ActionType.BUY_LARGE: 0.02,
            ActionType.SELL_SMALL: -0.005,
            ActionType.SELL_MEDIUM: -0.01,
            ActionType.SELL_LARGE: -0.02,
            ActionType.CLOSE_POSITION: 0.0  # Special case
        }
        
        # Initialize portfolio state
        self.portfolio = PortfolioState(
            balance=config.initial_balance,
            equity=config.initial_balance,
            current_position=0.0,
            unrealized_pnl=0.0,
            realized_pnl=0.0,
            total_trades=0,
            winning_trades=0,
            max_drawdown=0.0,
            current_drawdown=0.0,
            mfe=0.0,
            mae=0.0,
            entry_price=0.0,
            active_exit_policy="STANDARD",
            last_regret=0.0
        )
        
        # State tracking
        self.episode_start_balance = config.initial_balance
        self.peak_equity = config.initial_balance
        self.last_action = ActionType.HOLD
        self.position_entry_price = 0.0
        self.current_mfe = 0.0
        self.current_mae = 0.0
        
    @abstractmethod
    def reset(self) -> np.ndarray:
        """
        Reset environment to initial state.
        
        Returns:
            np.ndarray: Initial observation/state
        """
        pass
        
    @abstractmethod
    def step(self, action: int) -> Tuple[np.ndarray, float, bool, Dict[str, Any]]:
        """
        Execute action and return next state, reward, done flag, and info.
        
        Args:
            action: Action to execute
            
        Returns:
            Tuple containing:
                - next_state: Next observation/state
                - reward: Reward for the action
                - done: Whether episode is finished
                - info: Additional information
        """
        pass
        
    @abstractmethod
    def render(self, mode: str = 'human') -> Optional[Any]:
        """
        Visualize current environment state.
        
        Args:
            mode: Rendering mode ('human', 'rgb_array', etc.)
            
        Returns:
            Rendered output (depends on mode)
        """
        pass
        
    @abstractmethod
    def get_observation_space_shape(self) -> Tuple[int, ...]:
        """
        Get the shape of the observation space.
        
        Returns:
            Shape tuple for observation space
        """
        pass
        
    @abstractmethod
    def get_action_space_size(self) -> int:
        """
        Get the size of the action space.
        
        Returns:
            Number of possible actions
        """
        pass
        
    @abstractmethod
    def seed(self, seed: Optional[int] = None) -> List[int]:
        """
        Set random seed for reproducibility.
        
        Args:
            seed: Random seed value
            
        Returns:
            List of seeds used
        """
        pass
        
    def close(self) -> None:
        """Clean up environment resources."""
        pass
        
    @property
    def current_state(self) -> np.ndarray:
        """Get current environment state."""
        return self._get_current_state()
        
    @abstractmethod
    def _get_current_state(self) -> np.ndarray:
        """Internal method to get current state."""
        pass
        
    @property
    def portfolio_state(self) -> PortfolioState:
        """Get current portfolio state."""
        return self.portfolio
        
    def _execute_action(self, action: int, current_price: float) -> Dict[str, Any]:
        """
        Execute trading action and update portfolio state.
        
        Args:
            action: Action index to execute
            current_price: Current market price
            
        Returns:
            Dictionary with execution details
        """
        action_type = ActionType(action)
        execution_info = {
            'action_type': action_type.name,
            'executed': False,
            'position_change': 0.0,
            'transaction_cost': 0.0,
            'error': None
        }
        
        try:
            if action_type == ActionType.HOLD:
                # No action taken
                execution_info['executed'] = True
                
            elif action_type == ActionType.CLOSE_POSITION:
                if abs(self.portfolio.current_position) > 1e-6:
                    # Close current position
                    self._close_position(current_price)
                    execution_info['executed'] = True
                    execution_info['position_change'] = -self.portfolio.current_position
                    
            else:
                # Execute buy/sell action
                position_change = self.action_sizes[action_type]
                new_position = self.portfolio.current_position + position_change
                
                # Check position limits
                if abs(new_position) <= self.config.max_position_size:
                    self._update_position(position_change, current_price)
                    execution_info['executed'] = True
                    execution_info['position_change'] = position_change
                    execution_info['transaction_cost'] = abs(position_change) * self.config.transaction_cost
                else:
                    execution_info['error'] = 'Position limit exceeded'
                    
        except Exception as e:
            execution_info['error'] = str(e)
            
        return execution_info
        
    def _update_position(self, position_change: float, current_price: float) -> None:
        """Update portfolio position and related metrics."""
        # Calculate transaction cost
        transaction_cost = abs(position_change) * self.config.transaction_cost * self.portfolio.balance
        
        # Update position
        old_position = self.portfolio.current_position
        self.portfolio.current_position += position_change
        
        # Track entry price for new positions
        if abs(old_position) < 1e-6 and abs(self.portfolio.current_position) > 1e-6:
            self.position_entry_price = current_price
            self.current_mfe = 0.0
            self.current_mae = 0.0
            
        # Update balance (subtract transaction costs)
        self.portfolio.balance -= transaction_cost
        
        # Update trade count
        if abs(position_change) > 1e-6:
            self.portfolio.total_trades += 1
            
    def _close_position(self, current_price: float) -> None:
        """Close current position and realize P&L."""
        if abs(self.portfolio.current_position) < 1e-6:
            return
            
        # Calculate realized P&L
        if self.position_entry_price > 0:
            price_change = current_price - self.position_entry_price
            pnl = self.portfolio.current_position * price_change * self.portfolio.balance
            
            # Update realized P&L
            self.portfolio.realized_pnl += pnl
            self.portfolio.balance += pnl
            
            # Track winning trades
            if pnl > 0:
                self.portfolio.winning_trades += 1
                
        # Reset position
        self.portfolio.current_position = 0.0
        self.position_entry_price = 0.0
        # Don't reset MFE/MAE yet so reward calc can see it in prev_state? 
        # Actually reward calc uses prev_state which is a copy before this update.
        # So we can reset internal trackers here if next step is fresh.
        # But MFE/MAE in portfolio state will be 0 after this method since current_position is 0.
        
    def _update_unrealized_pnl(self, current_price: float) -> None:
        """Update unrealized P&L for current position."""
        if abs(self.portfolio.current_position) < 1e-6 or self.position_entry_price <= 0:
            self.portfolio.unrealized_pnl = 0.0
            self.portfolio.mfe = 0.0
            self.portfolio.mae = 0.0
            return
            
        price_change = current_price - self.position_entry_price
        self.portfolio.unrealized_pnl = (
            self.portfolio.current_position * price_change * self.portfolio.balance
        )
        
        # Update MFE/MAE
        if self.portfolio.unrealized_pnl > self.current_mfe:
            self.current_mfe = self.portfolio.unrealized_pnl
        if self.portfolio.unrealized_pnl < self.current_mae:
            self.current_mae = self.portfolio.unrealized_pnl
            
        self.portfolio.mfe = self.current_mfe
        self.portfolio.mae = self.current_mae
        self.portfolio.entry_price = self.position_entry_price
        
    def _update_equity_and_drawdown(self) -> None:
        """Update equity and drawdown metrics."""
        # Update equity
        self.portfolio.equity = self.portfolio.balance + self.portfolio.unrealized_pnl
        
        # Update peak equity
        if self.portfolio.equity > self.peak_equity:
            self.peak_equity = self.portfolio.equity
            
        # Update drawdown
        if self.peak_equity > 0:
            self.portfolio.current_drawdown = (self.peak_equity - self.portfolio.equity) / self.peak_equity
            self.portfolio.max_drawdown = max(self.portfolio.max_drawdown, self.portfolio.current_drawdown)
            
    def _check_episode_termination(self) -> Tuple[bool, str]:
        """
        Check if episode should terminate.
        
        Returns:
            Tuple of (should_terminate, reason)
        """
        # Check step limit
        if self.current_step >= self.config.max_episode_steps:
            return True, "max_steps_reached"
            
        # Check minimum steps
        if self.current_step < self.config.min_episode_steps:
            return False, ""
            
        # Check for excessive drawdown
        if self.portfolio.current_drawdown > 0.5:  # 50% drawdown
            return True, "excessive_drawdown"
            
        # Check for negative balance
        if self.portfolio.balance <= 0:
            return True, "negative_balance"
            
        return False, ""
        
    def get_info_dict(self) -> Dict[str, Any]:
        """Get comprehensive info dictionary for step return."""
        return {
            'step': self.current_step,
            'balance': self.portfolio.balance,
            'equity': self.portfolio.equity,
            'position': self.portfolio.current_position,
            'unrealized_pnl': self.portfolio.unrealized_pnl,
            'realized_pnl': self.portfolio.realized_pnl,
            'total_trades': self.portfolio.total_trades,
            'winning_trades': self.portfolio.winning_trades,
            'win_rate': self.portfolio.winning_trades / max(1, self.portfolio.total_trades),
            'max_drawdown': self.portfolio.max_drawdown,
            'current_drawdown': self.portfolio.current_drawdown,
            'total_return': (self.portfolio.equity - self.episode_start_balance) / self.episode_start_balance,
            'last_action': self.last_action.name if hasattr(self.last_action, 'name') else str(self.last_action)
        }