"""
Real-Time Trading Environment for RL System

This module provides a real-time trading environment that connects RL agents
with live market data and order execution through MT5.
"""

import asyncio
import logging
import numpy as np
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple, Union
from enum import Enum
import threading
import time

from src.models import MarketData, Portfolio, Direction
from src.exceptions import BrokerAPIError, TradeExecutionError
from src.rl.environments.base import TradingEnvironment, EnvironmentConfig, PortfolioState, ActionType
from src.rl.integration.mt5_connector import EnhancedMT5Connector
from src.rl.monitoring.metrics import MetricsTracker
from src.interfaces import RiskManager


class TradingMode(Enum):
    """Trading execution modes"""
    PAPER = "paper"
    LIVE = "live"
    SIMULATION = "simulation"


class RealTimeEnvironment(TradingEnvironment):
    """
    Real-time trading environment for live market interaction.
    
    Provides seamless switching between paper trading and live execution
    while maintaining consistent RL agent interface.
    """
    
    def __init__(self, 
                 config: EnvironmentConfig,
                 mt5_connector: EnhancedMT5Connector,
                 risk_manager: Optional[RiskManager] = None,
                 trading_mode: TradingMode = TradingMode.PAPER,
                 symbols: List[str] = None):
        """
        Initialize real-time trading environment.
        
        Args:
            config: Environment configuration
            mt5_connector: Enhanced MT5 connector
            risk_manager: Risk management system
            trading_mode: Trading execution mode
            symbols: List of symbols to trade
        """
        super().__init__(config)
        
        self.mt5_connector = mt5_connector
        self.risk_manager = risk_manager
        self.trading_mode = trading_mode
        self.symbols = symbols or ['EUR/USD', 'GBP/USD', 'USD/JPY']
        
        # Real-time state
        self.current_symbol = self.symbols[0]  # Primary symbol
        self.market_data_cache: Dict[str, MarketData] = {}
        self.last_update_time: Dict[str, datetime] = {}
        
        # Performance tracking
        self.performance_metrics = MetricsTracker()
        self.trade_history: List[Dict[str, Any]] = []
        
        # Real-time monitoring
        self.is_running = False
        self.data_thread: Optional[threading.Thread] = None
        self.update_interval = 1.0  # seconds
        
        # Paper trading simulation
        self.paper_portfolio = PortfolioState(
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
        
        self.logger = logging.getLogger(__name__)
        
    async def initialize(self) -> bool:
        """Initialize real-time environment and connections."""
        try:
            # Initialize MT5 connection
            if not self.mt5_connector.connected:
                success = await self.mt5_connector.connect()
                if not success:
                    raise BrokerAPIError("Failed to connect to MT5")
            
            # Initialize data feeds
            success = await self.mt5_connector.initialize_rl_data_feeds(self.symbols)
            if not success:
                raise BrokerAPIError("Failed to initialize RL data feeds")
            
            # Start real-time data monitoring
            await self._start_real_time_monitoring()
            
            self.logger.info(f"Real-time environment initialized in {self.trading_mode.value} mode")
            return True
            
        except Exception as e:
            self.logger.error(f"Error initializing real-time environment: {e}")
            return False
    
    async def reset(self) -> np.ndarray:
        """Reset environment to initial state."""
        try:
            # Reset portfolio state
            if self.trading_mode == TradingMode.PAPER:
                self.paper_portfolio = PortfolioState(
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
                self.portfolio = self.paper_portfolio
            else:
                # Get current live portfolio state
                live_portfolio = await self.mt5_connector.get_account_info()
                self.portfolio = self._convert_to_portfolio_state(live_portfolio)
            
            # Reset environment state
            self.current_step = 0
            self.done = False
            self.info = {}
            self.trade_history = []
            
            # Get initial state
            state = await self._get_current_state_async()
            
            self.logger.info("Real-time environment reset completed")
            return state
            
        except Exception as e:
            self.logger.error(f"Error resetting real-time environment: {e}")
            raise TradeExecutionError(f"Failed to reset environment: {e}")
    
    async def step(self, action: int) -> Tuple[np.ndarray, float, bool, Dict[str, Any]]:
        """
        Execute action in real-time environment.
        
        Args:
            action: RL agent action
            
        Returns:
            Tuple of (next_state, reward, done, info)
        """
        try:
            # Store previous state for reward calculation
            prev_portfolio = self._copy_portfolio_state(self.portfolio)
            
            # Execute action
            execution_result = await self._execute_action(action)
            
            # Update portfolio state
            await self._update_portfolio_state()
            
            # Calculate reward
            reward = self._calculate_reward(prev_portfolio, self.portfolio, action)
            
            # Get next state
            next_state = await self._get_current_state_async()
            
            # Update step counter
            self.current_step += 1
            
            # Check if episode is done
            done = self._check_episode_done()
            
            # Prepare info
            info = {
                'action_executed': execution_result,
                'portfolio_value': self.portfolio.equity,
                'current_position': self.portfolio.current_position,
                'realized_pnl': self.portfolio.realized_pnl,
                'unrealized_pnl': self.portfolio.unrealized_pnl,
                'total_trades': self.portfolio.total_trades,
                'trading_mode': self.trading_mode.value,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
            
            # Update performance metrics
            returns = (self.portfolio.equity - self.config.initial_balance) / self.config.initial_balance
            self.performance_metrics.record_performance_metrics(
                returns=returns,
                sharpe_ratio=0.0,  # Would need historical data to calculate
                max_drawdown=self.portfolio.max_drawdown,
                win_rate=self.portfolio.winning_trades / max(self.portfolio.total_trades, 1),
                profit_factor=1.0  # Simplified
            )
            
            self.info = info
            return next_state, reward, done, info
            
        except Exception as e:
            self.logger.error(f"Error in environment step: {e}")
            # Return safe state on error
            state = await self._get_current_state_async()
            return state, -1.0, True, {'error': str(e)}
    
    async def _execute_action(self, action: int) -> Dict[str, Any]:
        """Execute trading action based on mode."""
        try:
            action_config = {
                'action_space': 'discrete',
                'max_position_size': self.config.max_position_size,
                'risk_per_trade': 0.02,
                'account_balance': self.portfolio.balance
            }
            
            if self.trading_mode == TradingMode.PAPER:
                return await self._execute_paper_action(action, action_config)
            else:
                return await self._execute_live_action(action, action_config)
                
        except Exception as e:
            self.logger.error(f"Error executing action {action}: {e}")
            return {'success': False, 'error': str(e)}
    
    async def _execute_paper_action(self, action: int, config: Dict[str, Any]) -> Dict[str, Any]:
        """Execute action in paper trading mode."""
        try:
            # Decode action
            action_info = self._decode_action(action)
            
            if action_info['type'] == 'HOLD':
                return {'success': True, 'action': 'HOLD', 'order_id': None}
            
            # Get current market data for non-HOLD actions
            current_data = self.market_data_cache.get(self.current_symbol)
            if not current_data:
                return {'success': False, 'error': 'No market data available'}
            
            elif action_info['type'] == 'CLOSE_POSITION':
                if abs(self.paper_portfolio.current_position) > 0.001:
                    # Close position
                    close_price = current_data.bid if self.paper_portfolio.current_position > 0 else current_data.ask
                    pnl = self._calculate_position_pnl(close_price)
                    
                    self.paper_portfolio.realized_pnl += pnl
                    self.paper_portfolio.current_position = 0.0
                    self.paper_portfolio.total_trades += 1
                    
                    if pnl > 0:
                        self.paper_portfolio.winning_trades += 1
                    
                    # Record trade
                    trade_record = {
                        'timestamp': datetime.now(timezone.utc),
                        'action': 'CLOSE',
                        'symbol': self.current_symbol,
                        'price': close_price,
                        'pnl': pnl,
                        'position_size': 0.0
                    }
                    self.trade_history.append(trade_record)
                    
                    return {'success': True, 'action': 'CLOSE_POSITION', 'pnl': pnl}
                
                return {'success': True, 'action': 'HOLD', 'message': 'No position to close'}
            
            else:
                # Open new position
                direction = action_info['direction']
                size = action_info['size']
                
                # Apply risk management
                size = self._apply_paper_risk_management(size, config)
                
                if size > 0:
                    # Close existing position if opposite direction
                    if ((direction == 'BUY' and self.paper_portfolio.current_position < 0) or
                        (direction == 'SELL' and self.paper_portfolio.current_position > 0)):
                        
                        close_price = current_data.bid if self.paper_portfolio.current_position > 0 else current_data.ask
                        pnl = self._calculate_position_pnl(close_price)
                        self.paper_portfolio.realized_pnl += pnl
                        self.paper_portfolio.current_position = 0.0
                    
                    # Open new position
                    entry_price = current_data.ask if direction == 'BUY' else current_data.bid
                    position_size = size if direction == 'BUY' else -size
                    
                    self.paper_portfolio.current_position = position_size
                    self.paper_portfolio.total_trades += 1
                    
                    # Record trade
                    trade_record = {
                        'timestamp': datetime.now(timezone.utc),
                        'action': direction,
                        'symbol': self.current_symbol,
                        'price': entry_price,
                        'position_size': position_size,
                        'pnl': 0.0
                    }
                    self.trade_history.append(trade_record)
                    
                    return {
                        'success': True, 
                        'action': direction, 
                        'size': size,
                        'price': entry_price
                    }
                
                return {'success': True, 'action': 'HOLD', 'message': 'Position size too small'}
                
        except Exception as e:
            self.logger.error(f"Error in paper trading execution: {e}")
            return {'success': False, 'error': str(e)}
    
    async def _execute_live_action(self, action: int, config: Dict[str, Any]) -> Dict[str, Any]:
        """Execute action in live trading mode."""
        try:
            # Apply additional risk checks for live trading
            if self.risk_manager:
                risk_check = await self.risk_manager.check_trade_risk(
                    symbol=self.current_symbol,
                    action=action,
                    portfolio=self.portfolio
                )
                
                if not risk_check['approved']:
                    return {
                        'success': False, 
                        'error': f"Risk check failed: {risk_check['reason']}"
                    }
            
            # Execute through MT5 connector
            order_id = await self.mt5_connector.execute_rl_action(
                self.current_symbol, 
                action, 
                config
            )
            
            if order_id:
                return {'success': True, 'action': 'ORDER_PLACED', 'order_id': order_id}
            else:
                return {'success': True, 'action': 'HOLD', 'order_id': None}
                
        except Exception as e:
            self.logger.error(f"Error in live trading execution: {e}")
            return {'success': False, 'error': str(e)}
    

    
    async def _update_portfolio_state(self) -> None:
        """Update portfolio state based on trading mode."""
        try:
            if self.trading_mode == TradingMode.PAPER:
                # Update paper portfolio with current market prices
                if abs(self.paper_portfolio.current_position) > 0.001:
                    current_data = self.market_data_cache.get(self.current_symbol)
                    if current_data:
                        current_price = current_data.bid if self.paper_portfolio.current_position > 0 else current_data.ask
                        self.paper_portfolio.unrealized_pnl = self._calculate_position_pnl(current_price)
                
                self.paper_portfolio.equity = (self.paper_portfolio.balance + 
                                             self.paper_portfolio.realized_pnl + 
                                             self.paper_portfolio.unrealized_pnl)
                
                # Update drawdown
                peak_equity = max(self.paper_portfolio.equity, self.config.initial_balance)
                current_drawdown = (peak_equity - self.paper_portfolio.equity) / peak_equity
                self.paper_portfolio.current_drawdown = current_drawdown
                self.paper_portfolio.max_drawdown = max(self.paper_portfolio.max_drawdown, current_drawdown)
                
                self.portfolio = self.paper_portfolio
                
            else:
                # Get live portfolio state
                live_portfolio = await self.mt5_connector.get_account_info()
                self.portfolio = self._convert_to_portfolio_state(live_portfolio)
                
        except Exception as e:
            self.logger.error(f"Error updating portfolio state: {e}")
    
    async def _start_real_time_monitoring(self) -> None:
        """Start real-time market data monitoring."""
        try:
            self.is_running = True
            
            # Start data update thread
            self.data_thread = threading.Thread(
                target=self._data_update_loop,
                daemon=True
            )
            self.data_thread.start()
            
            self.logger.info("Real-time monitoring started")
            
        except Exception as e:
            self.logger.error(f"Error starting real-time monitoring: {e}")
    
    def _data_update_loop(self) -> None:
        """Background thread for updating market data."""
        while self.is_running:
            try:
                # Update market data for all symbols
                asyncio.run(self._update_market_data())
                time.sleep(self.update_interval)
                
            except Exception as e:
                self.logger.error(f"Error in data update loop: {e}")
                time.sleep(self.update_interval)
    
    async def _update_market_data(self) -> None:
        """Update cached market data."""
        try:
            for symbol in self.symbols:
                try:
                    market_data = await self.mt5_connector.get_market_data(symbol)
                    self.market_data_cache[symbol] = market_data
                    self.last_update_time[symbol] = datetime.now(timezone.utc)
                    
                except Exception as e:
                    self.logger.warning(f"Failed to update data for {symbol}: {e}")
                    
        except Exception as e:
            self.logger.error(f"Error updating market data: {e}")
    
    def _decode_action(self, action: int) -> Dict[str, Any]:
        """Decode RL action into trading instruction."""
        action_map = {
            0: {'type': 'HOLD'},
            1: {'type': 'BUY', 'direction': 'BUY', 'size': 0.01},
            2: {'type': 'BUY', 'direction': 'BUY', 'size': 0.02},
            3: {'type': 'BUY', 'direction': 'BUY', 'size': 0.05},
            4: {'type': 'SELL', 'direction': 'SELL', 'size': 0.01},
            5: {'type': 'SELL', 'direction': 'SELL', 'size': 0.02},
            6: {'type': 'SELL', 'direction': 'SELL', 'size': 0.05},
            7: {'type': 'CLOSE_POSITION'}
        }
        return action_map.get(action, {'type': 'HOLD'})
    
    def _apply_paper_risk_management(self, size: float, config: Dict[str, Any]) -> float:
        """Apply risk management for paper trading."""
        max_position = config.get('max_position_size', 0.1)
        risk_per_trade = config.get('risk_per_trade', 0.02)
        
        # Limit position size
        size = min(size, max_position)
        
        # Apply risk-based sizing
        account_balance = self.paper_portfolio.balance
        risk_amount = account_balance * risk_per_trade
        
        # Simplified risk calculation
        if size * 100000 * 0.0001 > risk_amount:
            size = risk_amount / (100000 * 0.0001)
        
        return max(0.01, size)
    
    def _calculate_position_pnl(self, current_price: float) -> float:
        """Calculate P&L for current position."""
        if abs(self.paper_portfolio.current_position) < 0.001:
            return 0.0
        
        # Get entry price from last trade
        if self.trade_history:
            last_trade = self.trade_history[-1]
            entry_price = last_trade['price']
            
            if self.paper_portfolio.current_position > 0:
                # Long position
                pnl = (current_price - entry_price) * abs(self.paper_portfolio.current_position) * 100000
            else:
                # Short position
                pnl = (entry_price - current_price) * abs(self.paper_portfolio.current_position) * 100000
            
            return pnl
        
        return 0.0
    
    def _calculate_reward(self, prev_portfolio: PortfolioState, 
                         current_portfolio: PortfolioState, action: int) -> float:
        """Calculate reward for the action taken."""
        # Base reward: change in equity
        equity_change = current_portfolio.equity - prev_portfolio.equity
        base_reward = equity_change / self.config.initial_balance
        
        # Risk-adjusted reward
        if current_portfolio.current_drawdown > 0.1:  # 10% drawdown penalty
            drawdown_penalty = -current_portfolio.current_drawdown * 2
        else:
            drawdown_penalty = 0
        
        # Transaction cost penalty
        if action != 0:  # Not HOLD
            transaction_penalty = -self.config.transaction_cost
        else:
            transaction_penalty = 0
        
        # Combine rewards
        total_reward = base_reward + drawdown_penalty + transaction_penalty
        
        return np.clip(total_reward, -1.0, 1.0)
    
    def _check_episode_done(self) -> bool:
        """Check if episode should end."""
        # End if maximum drawdown exceeded
        if self.portfolio.current_drawdown > 0.2:  # 20% max drawdown
            return True
        
        # End if maximum steps reached
        if self.current_step >= self.config.max_episode_steps:
            return True
        
        # End if equity falls below minimum threshold
        if self.portfolio.equity < self.config.initial_balance * 0.5:
            return True
        
        return False
    
    def _convert_to_portfolio_state(self, portfolio: Portfolio) -> PortfolioState:
        """Convert Portfolio to PortfolioState."""
        # Calculate current position for primary symbol
        current_position = 0.0
        for pos in portfolio.positions:
            if pos.symbol == self.current_symbol:
                current_position = pos.quantity if pos.direction == Direction.LONG else -pos.quantity
                break
        
        return PortfolioState(
            balance=portfolio.balance,
            equity=portfolio.equity,
            current_position=current_position,
            unrealized_pnl=sum(pos.unrealized_pnl for pos in portfolio.positions),
            realized_pnl=0.0,  # Not tracked in Portfolio model
            total_trades=len(portfolio.positions),
            winning_trades=len([p for p in portfolio.positions if p.unrealized_pnl > 0]),
            max_drawdown=0.0,  # Would need historical tracking
            current_drawdown=0.0  # Would need historical tracking
        )
    
    def _copy_portfolio_state(self, portfolio: PortfolioState) -> PortfolioState:
        """Create a copy of portfolio state."""
        return PortfolioState(
            balance=portfolio.balance,
            equity=portfolio.equity,
            current_position=portfolio.current_position,
            unrealized_pnl=portfolio.unrealized_pnl,
            realized_pnl=portfolio.realized_pnl,
            total_trades=portfolio.total_trades,
            winning_trades=portfolio.winning_trades,
            max_drawdown=portfolio.max_drawdown,
            current_drawdown=portfolio.current_drawdown
        )
    
    async def switch_trading_mode(self, new_mode: TradingMode) -> bool:
        """Switch between trading modes."""
        try:
            old_mode = self.trading_mode
            self.trading_mode = new_mode
            
            self.logger.info(f"Switched trading mode from {old_mode.value} to {new_mode.value}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error switching trading mode: {e}")
            return False
    
    async def get_performance_summary(self) -> Dict[str, Any]:
        """Get performance summary."""
        return {
            'total_equity': self.portfolio.equity,
            'total_return': (self.portfolio.equity - self.config.initial_balance) / self.config.initial_balance,
            'realized_pnl': self.portfolio.realized_pnl,
            'unrealized_pnl': self.portfolio.unrealized_pnl,
            'total_trades': self.portfolio.total_trades,
            'winning_trades': self.portfolio.winning_trades,
            'win_rate': self.portfolio.winning_trades / max(self.portfolio.total_trades, 1),
            'max_drawdown': self.portfolio.max_drawdown,
            'current_drawdown': self.portfolio.current_drawdown,
            'current_position': self.portfolio.current_position,
            'trading_mode': self.trading_mode.value,
            'symbols': self.symbols
        }
    
    def render(self, mode: str = 'human') -> Optional[Any]:
        """Render environment state."""
        if mode == 'human':
            print(f"Portfolio Equity: ${self.portfolio.equity:.2f}")
            print(f"Current Position: {self.portfolio.current_position:.4f}")
            print(f"Realized P&L: ${self.portfolio.realized_pnl:.2f}")
            print(f"Unrealized P&L: ${self.portfolio.unrealized_pnl:.2f}")
            print(f"Total Trades: {self.portfolio.total_trades}")
            print(f"Win Rate: {self.portfolio.winning_trades / max(self.portfolio.total_trades, 1):.2%}")
            print(f"Max Drawdown: {self.portfolio.max_drawdown:.2%}")
            print(f"Trading Mode: {self.trading_mode.value}")
            return None
        elif mode == 'rgb_array':
            # Could return a visualization array
            return None
        else:
            return None
    
    def get_observation_space_shape(self) -> Tuple[int, ...]:
        """Get observation space shape."""
        state_dim = self.mt5_connector.state_processor.get_state_dimension()
        return (state_dim,)
    
    def get_action_space_size(self) -> int:
        """Get action space size."""
        return 8  # HOLD, BUY_SMALL, BUY_MEDIUM, BUY_LARGE, SELL_SMALL, SELL_MEDIUM, SELL_LARGE, CLOSE_POSITION
    
    def seed(self, seed: Optional[int] = None) -> List[int]:
        """Set random seed."""
        if seed is not None:
            np.random.seed(seed)
            return [seed]
        return []
    
    def _get_current_state(self) -> np.ndarray:
        """Internal method to get current state (synchronous version)."""
        # This is a synchronous version for the base class compatibility
        # The async version is used in the actual implementation
        try:
            # Run the async version in a new event loop if needed
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # If we're already in an event loop, we can't use asyncio.run
                    # Return a zero state as fallback
                    return np.zeros(self.mt5_connector.state_processor.get_state_dimension())
                else:
                    return loop.run_until_complete(self._get_current_state_async())
            except RuntimeError:
                return asyncio.run(self._get_current_state_async())
        except Exception as e:
            self.logger.error(f"Error getting current state: {e}")
            return np.zeros(self.mt5_connector.state_processor.get_state_dimension())
    
    async def _get_current_state_async(self) -> np.ndarray:
        """Async version of get current state."""
        try:
            # Get state vector from MT5 connector
            portfolio_state = {
                'balance': self.portfolio.balance,
                'equity': self.portfolio.equity,
                'current_position': self.portfolio.current_position,
                'unrealized_pnl': self.portfolio.unrealized_pnl,
                'realized_pnl': self.portfolio.realized_pnl
            }
            
            state_vector = await self.mt5_connector.get_rl_state_vector(
                self.current_symbol, 
                portfolio_state
            )
            
            return state_vector
            
        except Exception as e:
            self.logger.error(f"Error getting current state: {e}")
            # Return zero state as fallback
            return np.zeros(self.mt5_connector.state_processor.get_state_dimension())

    async def cleanup(self) -> None:
        """Cleanup resources."""
        try:
            self.is_running = False
            
            if self.data_thread and self.data_thread.is_alive():
                self.data_thread.join(timeout=5.0)
            
            if self.mt5_connector.connected:
                await self.mt5_connector.disconnect()
            
            self.logger.info("Real-time environment cleanup completed")
            
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")


def create_real_time_environment(config: EnvironmentConfig,
                                mt5_connector: EnhancedMT5Connector,
                                trading_mode: TradingMode = TradingMode.PAPER,
                                symbols: List[str] = None) -> RealTimeEnvironment:
    """Factory function to create real-time trading environment."""
    return RealTimeEnvironment(
        config=config,
        mt5_connector=mt5_connector,
        trading_mode=trading_mode,
        symbols=symbols
    )