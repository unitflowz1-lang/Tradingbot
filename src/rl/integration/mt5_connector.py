"""
Enhanced MT5 Connector for RL System

This module extends the existing MT5BrokerInterface with RL-specific functionality
including real-time state vector construction and RL agent action execution.
"""

import asyncio
import logging
import numpy as np
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple
import MetaTrader5 as mt5

from src.data.mt5_broker import MT5BrokerInterface
from src.models import MarketData, Direction
from src.exceptions import BrokerAPIError
from src.rl.environments.state_processor import StateProcessor
from src.rl.environments.technical_indicators import TechnicalIndicators


class EnhancedMT5Connector(MT5BrokerInterface):
    """
    Enhanced MT5 connector with RL-specific capabilities for real-time
    state vector construction and agent action execution.
    """
    
    def __init__(self, login: int, password: str, server: str = "MetaQuotes-Demo",
                 state_processor: Optional[StateProcessor] = None,
                 lookback_window: int = 100):
        """
        Initialize enhanced MT5 connector.
        
        Args:
            login: MT5 account login
            password: MT5 account password  
            server: MT5 server name
            state_processor: State processor for RL state construction
            lookback_window: Number of historical bars for state construction
        """
        super().__init__(login, password, server)
        if state_processor is None:
            # Import here to avoid circular imports
            from src.rl.environments.advanced_state_processor import AdvancedStateProcessor
            from src.rl.environments.base import EnvironmentConfig
            env_config = EnvironmentConfig(
                state_features=['price', 'technical', 'portfolio'],
                action_space_type='discrete',
                reward_function='profit_based',
                lookback_window=100,
                normalization_method='robust',
                transaction_cost=0.0001,
                max_position_size=0.1,
                initial_balance=10000.0
            )
            self.state_processor = AdvancedStateProcessor(env_config)
        else:
            self.state_processor = state_processor
        self.lookback_window = lookback_window
        self.technical_indicators = TechnicalIndicators()
        
        # Cache for historical data
        self._price_history: Dict[str, List[MarketData]] = {}
        self._last_update: Dict[str, datetime] = {}
        
        # RL-specific configuration
        self.rl_symbols = ['EURUSD', 'GBPUSD', 'USDJPY', 'USDCHF']
        self.timeframe = mt5.TIMEFRAME_M1  # 1-minute bars for RL
        
        self.logger = logging.getLogger(__name__)
    
    async def initialize_rl_data_feeds(self, symbols: List[str]) -> bool:
        """
        Initialize real-time data feeds for RL system.
        
        Args:
            symbols: List of symbols to monitor
            
        Returns:
            bool: True if initialization successful
        """
        try:
            if not self.connected:
                await self.connect()
            
            # Initialize price history for each symbol
            for symbol in symbols:
                mt5_symbol = self.symbol_mapping.get(symbol, symbol)
                
                # Get initial historical data
                rates = mt5.copy_rates_from_pos(
                    mt5_symbol, 
                    self.timeframe, 
                    0, 
                    self.lookback_window
                )
                
                if rates is None:
                    self.logger.error(f"Failed to get historical data for {symbol}")
                    continue
                
                # Convert to MarketData objects
                history = []
                for rate in rates:
                    # Calculate realistic bid/ask from close price
                    spread = 0.0001  # Default spread for major pairs
                    bid_price = rate['close'] - spread / 2
                    ask_price = rate['close'] + spread / 2
                    
                    market_data = MarketData(
                        symbol=symbol,
                        timestamp=datetime.fromtimestamp(rate['time'], tz=timezone.utc),
                        open=rate['open'],
                        high=rate['high'],
                        low=rate['low'],
                        close=rate['close'],
                        volume=int(rate['tick_volume']),
                        bid=bid_price,
                        ask=ask_price,
                        spread=spread
                    )
                    history.append(market_data)
                
                self._price_history[symbol] = history
                self._last_update[symbol] = datetime.now(timezone.utc)
                
                self.logger.info(f"Initialized RL data feed for {symbol} with {len(history)} bars")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error initializing RL data feeds: {e}")
            return False
    
    async def get_rl_state_vector(self, symbol: str, 
                                 portfolio_state: Optional[Dict[str, Any]] = None) -> np.ndarray:
        """
        Construct real-time state vector for RL agent.
        
        Args:
            symbol: Trading symbol
            portfolio_state: Current portfolio state information
            
        Returns:
            np.ndarray: Normalized state vector for RL agent
        """
        try:
            # Update price history with latest data
            await self._update_price_history(symbol)
            
            # Get current market data
            current_data = await self.get_market_data(symbol)
            
            # Get historical data for technical indicators
            history = self._price_history.get(symbol, [])
            if len(history) < 20:  # Minimum for technical indicators
                raise BrokerAPIError(f"Insufficient historical data for {symbol}")
            
            # Calculate technical indicators
            opens = [data.open for data in history]
            highs = [data.high for data in history]
            lows = [data.low for data in history]
            closes = [data.close for data in history]
            volumes = [data.volume for data in history]
            
            # Get all indicators at once
            technical_data = self.technical_indicators.calculate_all_indicators(
                opens, highs, lows, closes, volumes
            )
            
            # Get portfolio information
            if portfolio_state is None:
                portfolio = await self.get_account_info()
                portfolio_state = {
                    'balance': portfolio.balance,
                    'equity': portfolio.equity,
                    'margin_used': portfolio.margin_used,
                    'positions': len(portfolio.positions),
                    'current_position': self._get_current_position_size(symbol, portfolio.positions)
                }
            
            # Construct state vector using state processor
            state_vector = self.state_processor.process_market_data(
                market_data=current_data,
                technical_indicators=technical_data,
                portfolio_state=portfolio_state,
                price_history=history[-50:]  # Last 50 bars for context
            )
            
            return state_vector
            
        except Exception as e:
            self.logger.error(f"Error constructing RL state vector for {symbol}: {e}")
            raise BrokerAPIError(f"Failed to construct state vector: {e}")
    
    async def execute_rl_action(self, symbol: str, action: int, 
                               action_config: Dict[str, Any]) -> Optional[str]:
        """
        Execute RL agent action through MT5 order management.
        
        Args:
            symbol: Trading symbol
            action: RL agent action (integer)
            action_config: Configuration for action execution
            
        Returns:
            Optional[str]: Order ID if order placed, None if no action taken
        """
        try:
            # Decode action based on action space configuration
            action_type = self._decode_rl_action(action, action_config)
            
            if action_type['type'] == 'HOLD':
                self.logger.debug(f"RL agent chose to HOLD for {symbol}")
                return None
            
            elif action_type['type'] == 'CLOSE_POSITION':
                # Close existing position
                positions = await self.get_positions()
                symbol_positions = [p for p in positions if p.symbol == symbol]
                
                if symbol_positions:
                    position_id = symbol_positions[0].order_id
                    success = await self.close_position(position_id)
                    if success:
                        self.logger.info(f"RL agent closed position for {symbol}")
                        return position_id
                return None
            
            else:
                # Place new order
                direction = Direction.LONG if action_type['direction'] == 'BUY' else Direction.SHORT
                size = action_type['size']
                
                # Apply risk management
                size = self._apply_risk_management(size, symbol, action_config)
                
                if size > 0:
                    order_id = await self.place_order(
                        symbol=symbol,
                        direction=direction,
                        size=size,
                        stop_loss=action_type.get('stop_loss'),
                        take_profit=action_type.get('take_profit')
                    )
                    
                    self.logger.info(f"RL agent placed {direction.value} order for {symbol}: {size} lots")
                    return order_id
                
                return None
                
        except Exception as e:
            self.logger.error(f"Error executing RL action for {symbol}: {e}")
            raise BrokerAPIError(f"Failed to execute RL action: {e}")
    
    async def get_real_time_features(self, symbol: str) -> Dict[str, float]:
        """
        Get real-time market features for RL state construction.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Dict[str, float]: Real-time market features
        """
        try:
            # Get current tick data
            mt5_symbol = self.symbol_mapping.get(symbol, symbol)
            tick = mt5.symbol_info_tick(mt5_symbol)
            
            if tick is None:
                raise BrokerAPIError(f"Failed to get tick data for {symbol}")
            
            # Calculate real-time features
            features = {
                'bid_ask_spread': tick.ask - tick.bid,
                'mid_price': (tick.bid + tick.ask) / 2,
                'tick_volume': float(tick.volume),
                'price_change': tick.last - tick.bid if tick.last > 0 else 0,
                'volatility_proxy': abs(tick.ask - tick.bid) / ((tick.ask + tick.bid) / 2),
                'timestamp': float(tick.time)
            }
            
            # Add order book features if available
            depth = mt5.market_book_get(mt5_symbol)
            if depth:
                features.update({
                    'order_book_imbalance': self._calculate_order_book_imbalance(depth),
                    'bid_depth': sum(item.volume for item in depth if item.type == 1),
                    'ask_depth': sum(item.volume for item in depth if item.type == 2)
                })
            
            return features
            
        except Exception as e:
            self.logger.error(f"Error getting real-time features for {symbol}: {e}")
            return {}
    
    async def _update_price_history(self, symbol: str) -> None:
        """Update price history with latest data."""
        try:
            mt5_symbol = self.symbol_mapping.get(symbol, symbol)
            
            # Get latest bar
            rates = mt5.copy_rates_from_pos(mt5_symbol, self.timeframe, 0, 1)
            if rates is None or len(rates) == 0:
                return
            
            rate = rates[0]
            latest_time = datetime.fromtimestamp(rate['time'], tz=timezone.utc)
            
            # Check if we need to update
            if symbol in self._last_update:
                if latest_time <= self._last_update[symbol]:
                    return  # No new data
            
            # Calculate realistic bid/ask from close price
            spread = 0.0001  # Default spread for major pairs
            bid_price = rate['close'] - spread / 2
            ask_price = rate['close'] + spread / 2
            
            # Add new data point
            new_data = MarketData(
                symbol=symbol,
                timestamp=latest_time,
                open=rate['open'],
                high=rate['high'],
                low=rate['low'],
                close=rate['close'],
                volume=int(rate['tick_volume']),
                bid=bid_price,
                ask=ask_price,
                spread=spread
            )
            
            if symbol not in self._price_history:
                self._price_history[symbol] = []
            
            self._price_history[symbol].append(new_data)
            
            # Keep only lookback_window data points
            if len(self._price_history[symbol]) > self.lookback_window:
                self._price_history[symbol] = self._price_history[symbol][-self.lookback_window:]
            
            self._last_update[symbol] = latest_time
            
        except Exception as e:
            self.logger.error(f"Error updating price history for {symbol}: {e}")
    
    def _decode_rl_action(self, action: int, config: Dict[str, Any]) -> Dict[str, Any]:
        """Decode RL agent action into trading instruction."""
        action_space = config.get('action_space', 'discrete')
        
        if action_space == 'discrete':
            # Discrete action space mapping
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
        
        else:
            # Continuous action space (future implementation)
            return {'type': 'HOLD'}
    
    def _apply_risk_management(self, size: float, symbol: str, config: Dict[str, Any]) -> float:
        """Apply risk management rules to position size."""
        max_position_size = config.get('max_position_size', 0.1)
        risk_per_trade = config.get('risk_per_trade', 0.02)
        
        # Limit position size
        size = min(size, max_position_size)
        
        # Apply risk-based sizing (simplified)
        account_balance = config.get('account_balance', 10000)
        risk_amount = account_balance * risk_per_trade
        
        # Adjust size based on risk (this is a simplified calculation)
        if size * 100000 * 0.0001 > risk_amount:  # Assuming 1 pip = $1 for standard lot
            size = risk_amount / (100000 * 0.0001)
        
        return max(0.01, size)  # Minimum position size
    
    def _get_current_position_size(self, symbol: str, positions: List) -> float:
        """Get current position size for symbol."""
        for position in positions:
            if position.symbol == symbol:
                return position.quantity if position.direction == Direction.LONG else -position.quantity
        return 0.0
    
    def _calculate_order_book_imbalance(self, depth) -> float:
        """Calculate order book imbalance from market depth."""
        if not depth:
            return 0.0
        
        bid_volume = sum(item.volume for item in depth if item.type == 1)
        ask_volume = sum(item.volume for item in depth if item.type == 2)
        
        total_volume = bid_volume + ask_volume
        if total_volume == 0:
            return 0.0
        
        return (bid_volume - ask_volume) / total_volume
    
    async def get_multiple_symbols_state(self, symbols: List[str]) -> Dict[str, np.ndarray]:
        """
        Get state vectors for multiple symbols simultaneously.
        
        Args:
            symbols: List of trading symbols
            
        Returns:
            Dict[str, np.ndarray]: State vectors for each symbol
        """
        try:
            states = {}
            portfolio = await self.get_account_info()
            
            portfolio_state = {
                'balance': portfolio.balance,
                'equity': portfolio.equity,
                'margin_used': portfolio.margin_used,
                'positions': len(portfolio.positions)
            }
            
            # Get states for all symbols
            for symbol in symbols:
                try:
                    portfolio_state['current_position'] = self._get_current_position_size(
                        symbol, portfolio.positions
                    )
                    state_vector = await self.get_rl_state_vector(symbol, portfolio_state)
                    states[symbol] = state_vector
                except Exception as e:
                    self.logger.error(f"Error getting state for {symbol}: {e}")
                    # Use zero state as fallback
                    states[symbol] = np.zeros(self.state_processor.get_state_dimension())
            
            return states
            
        except Exception as e:
            self.logger.error(f"Error getting multiple symbol states: {e}")
            return {}


def create_enhanced_mt5_connector(login: int = None, 
                                password: str = None, 
                                server: str = None,
                                state_processor: Optional[StateProcessor] = None) -> EnhancedMT5Connector:
    """Factory function to create enhanced MT5 connector for RL system.
    
    Uses environment variables if credentials not provided:
    - MT5_LOGIN
    - MT5_PASSWORD
    - MT5_SERVER
    """
    import os
    
    # Get from environment if not provided
    login = login or int(os.environ.get('MT5_LOGIN', '95185205'))
    password = password or os.environ.get('MT5_PASSWORD', 'QxE@7tYo')
    server = server or os.environ.get('MT5_SERVER', 'MetaQuotes-Demo')
    
    # Import here to avoid circular imports
    from src.rl.environments.advanced_state_processor import AdvancedStateProcessor
    from src.rl.environments.base import EnvironmentConfig
    
    if state_processor is None:
        # Create default environment config
        env_config = EnvironmentConfig(
            state_features=['price', 'technical', 'portfolio'],
            action_space_type='discrete',
            reward_function='profit_based',
            lookback_window=100,
            normalization_method='robust',
            transaction_cost=0.0001,
            max_position_size=0.1,
            initial_balance=10000.0
        )
        state_processor = AdvancedStateProcessor(env_config)
    
    return EnhancedMT5Connector(
        login=login, 
        password=password, 
        server=server,
        state_processor=state_processor
    )
