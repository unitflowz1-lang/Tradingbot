"""
Unit tests for Multi-Pair Trading Environment

Tests multi-currency pair support, cross-pair correlations,
and currency-specific normalization features.
"""

import pytest
import numpy as np
from datetime import datetime, timezone, timedelta
from typing import Dict, List
import logging

from src.rl.environments.multi_pair_environment import (
    MultiPairTradingEnvironment,
    MultiPairEnvironmentConfig,
    MultiPairPortfolioState
)
from src.rl.environments.multi_pair_state_processor import MultiPairStateProcessor
from src.rl.environments.multi_pair_reward_calculator import MultiPairRewardCalculator
from src.rl.environments.base import ActionType
from src.models import MarketData


# Configure logging for tests
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TestMultiPairEnvironmentConfig:
    """Test multi-pair environment configuration."""
    
    def test_valid_config_creation(self):
        """Test creating valid multi-pair configuration."""
        currency_pairs = ['EUR/USD', 'GBP/USD', 'USD/JPY']
        
        config = MultiPairEnvironmentConfig(
            currency_pairs=currency_pairs,
            state_features=['price', 'technical', 'portfolio'],
            action_space_type='discrete',
            reward_function='multi_objective',
            lookback_window=10,
            normalization_method='adaptive',
            transaction_cost=0.0001,
            max_position_size=1.0,
            initial_balance=10000.0,
            correlation_lookback=50,
            enable_cross_pair_features=True
        )
        
        assert config.currency_pairs == currency_pairs
        assert config.correlation_lookback == 50
        assert config.enable_cross_pair_features is True
        assert len(config.pair_weights) == len(currency_pairs)
        
        # Check weights are normalized
        total_weight = sum(config.pair_weights.values())
        assert abs(total_weight - 1.0) < 1e-6
        
    def test_invalid_config_empty_pairs(self):
        """Test configuration with empty currency pairs."""
        with pytest.raises(ValueError, match="Currency pairs list cannot be empty"):
            MultiPairEnvironmentConfig(
                currency_pairs=[],
                state_features=['price'],
                action_space_type='discrete',
                reward_function='pnl',
                lookback_window=10,
                normalization_method='standard',
                transaction_cost=0.0001,
                max_position_size=1.0,
                initial_balance=10000.0
            )
            
    def test_invalid_config_single_pair(self):
        """Test configuration with single currency pair."""
        with pytest.raises(ValueError, match="Multi-pair environment requires at least 2 currency pairs"):
            MultiPairEnvironmentConfig(
                currency_pairs=['EUR/USD'],
                state_features=['price'],
                action_space_type='discrete',
                reward_function='pnl',
                lookback_window=10,
                normalization_method='standard',
                transaction_cost=0.0001,
                max_position_size=1.0,
                initial_balance=10000.0
            )
            
    def test_custom_pair_weights(self):
        """Test configuration with custom pair weights."""
        currency_pairs = ['EUR/USD', 'GBP/USD', 'USD/JPY']
        custom_weights = {'EUR/USD': 0.5, 'GBP/USD': 0.3, 'USD/JPY': 0.2}
        
        config = MultiPairEnvironmentConfig(
            currency_pairs=currency_pairs,
            pair_weights=custom_weights,
            state_features=['price'],
            action_space_type='discrete',
            reward_function='pnl',
            lookback_window=10,
            normalization_method='standard',
            transaction_cost=0.0001,
            max_position_size=1.0,
            initial_balance=10000.0
        )
        
        # Weights should be normalized
        assert abs(config.pair_weights['EUR/USD'] - 0.5) < 1e-6
        assert abs(config.pair_weights['GBP/USD'] - 0.3) < 1e-6
        assert abs(config.pair_weights['USD/JPY'] - 0.2) < 1e-6


class TestMultiPairPortfolioState:
    """Test multi-pair portfolio state functionality."""
    
    def test_portfolio_state_creation(self):
        """Test creating multi-pair portfolio state."""
        portfolio = MultiPairPortfolioState(
            balance=10000.0,
            equity=10000.0,
            current_position=0.0,
            unrealized_pnl=0.0,
            realized_pnl=0.0,
            total_trades=0,
            winning_trades=0,
            max_drawdown=0.0,
            current_drawdown=0.0
        )
        
        assert portfolio.balance == 10000.0
        assert len(portfolio.pair_positions) == 0
        assert len(portfolio.pair_unrealized_pnl) == 0
        
    def test_total_position_exposure(self):
        """Test total position exposure calculation."""
        portfolio = MultiPairPortfolioState(
            balance=10000.0,
            equity=10000.0,
            current_position=0.0,
            unrealized_pnl=0.0,
            realized_pnl=0.0,
            total_trades=0,
            winning_trades=0,
            max_drawdown=0.0,
            current_drawdown=0.0
        )
        
        portfolio.pair_positions = {
            'EUR/USD': 0.5,
            'GBP/USD': -0.3,
            'USD/JPY': 0.2
        }
        
        total_exposure = portfolio.get_total_position_exposure()
        expected_exposure = 0.5 + 0.3 + 0.2  # Sum of absolute values
        assert abs(total_exposure - expected_exposure) < 1e-6
        
    def test_diversification_score(self):
        """Test diversification score calculation."""
        portfolio = MultiPairPortfolioState(
            balance=10000.0,
            equity=10000.0,
            current_position=0.0,
            unrealized_pnl=0.0,
            realized_pnl=0.0,
            total_trades=0,
            winning_trades=0,
            max_drawdown=0.0,
            current_drawdown=0.0
        )
        
        # Test perfectly diversified portfolio
        portfolio.pair_positions = {
            'EUR/USD': 0.33,
            'GBP/USD': 0.33,
            'USD/JPY': 0.34
        }
        
        diversification_score = portfolio.get_diversification_score()
        assert diversification_score > 0.9  # Should be close to 1.0
        
        # Test concentrated portfolio
        portfolio.pair_positions = {
            'EUR/USD': 1.0,
            'GBP/USD': 0.0,
            'USD/JPY': 0.0
        }
        
        diversification_score = portfolio.get_diversification_score()
        assert diversification_score < 0.1  # Should be close to 0.0
        
    def test_pair_win_rate(self):
        """Test pair-specific win rate calculation."""
        portfolio = MultiPairPortfolioState(
            balance=10000.0,
            equity=10000.0,
            current_position=0.0,
            unrealized_pnl=0.0,
            realized_pnl=0.0,
            total_trades=0,
            winning_trades=0,
            max_drawdown=0.0,
            current_drawdown=0.0
        )
        
        portfolio.pair_trades = {'EUR/USD': 10}
        portfolio.pair_winning_trades = {'EUR/USD': 7}
        
        win_rate = portfolio.get_pair_win_rate('EUR/USD')
        assert abs(win_rate - 0.7) < 1e-6
        
        # Test pair with no trades
        win_rate = portfolio.get_pair_win_rate('GBP/USD')
        assert win_rate == 0.0


def create_test_market_data(pairs: List[str], 
                          num_points: int = 100,
                          start_time: datetime = None) -> Dict[str, List[MarketData]]:
    """Create test market data for multiple currency pairs."""
    if start_time is None:
        start_time = datetime.now(timezone.utc) - timedelta(days=num_points)
        
    market_data = {}
    
    for pair in pairs:
        pair_data = []
        base_price = 1.2000 if 'EUR' in pair else 1.3000 if 'GBP' in pair else 110.0
        
        for i in range(num_points):
            timestamp = start_time + timedelta(hours=i)
            
            # Generate realistic price movement
            price_change = np.random.normal(0, 0.001) * base_price
            base_price += price_change
            base_price = max(base_price, 0.5000)  # Prevent negative prices
            
            # Generate OHLC
            high = base_price * (1 + abs(np.random.normal(0, 0.0005)))
            low = base_price * (1 - abs(np.random.normal(0, 0.0005)))
            open_price = low + (high - low) * np.random.random()
            close_price = base_price
            
            # Generate bid/ask
            spread = base_price * 0.0001  # 1 pip spread
            bid = close_price - spread / 2
            ask = close_price + spread / 2
            
            market_data_point = MarketData(
                symbol=pair,
                timestamp=timestamp,
                open=open_price,
                high=high,
                low=low,
                close=close_price,
                volume=np.random.randint(1000, 10000),
                bid=bid,
                ask=ask,
                spread=spread
            )
            
            pair_data.append(market_data_point)
            
        market_data[pair] = pair_data
        
    return market_data


class TestMultiPairTradingEnvironment:
    """Test multi-pair trading environment functionality."""
    
    def setup_method(self):
        """Set up test environment."""
        self.currency_pairs = ['EUR/USD', 'GBP/USD', 'USD/JPY']
        self.config = MultiPairEnvironmentConfig(
            currency_pairs=self.currency_pairs,
            state_features=['price', 'technical', 'portfolio'],
            action_space_type='discrete',
            reward_function='multi_objective',
            lookback_window=10,
            normalization_method='adaptive',
            transaction_cost=0.0001,
            max_position_size=1.0,
            initial_balance=10000.0,
            max_episode_steps=100,
            min_episode_steps=10,
            correlation_lookback=20
        )
        
        self.market_data = create_test_market_data(self.currency_pairs, 150)
        
    def test_environment_initialization(self):
        """Test multi-pair environment initialization."""
        env = MultiPairTradingEnvironment(
            market_data=self.market_data,
            config=self.config
        )
        
        assert env.currency_pairs == self.currency_pairs
        assert len(env.current_data_indices) == len(self.currency_pairs)
        assert env.total_action_space_size == len(ActionType) ** len(self.currency_pairs)
        assert isinstance(env.portfolio, MultiPairPortfolioState)
        
    def test_environment_reset(self):
        """Test environment reset functionality."""
        env = MultiPairTradingEnvironment(
            market_data=self.market_data,
            config=self.config
        )
        
        initial_state = env.reset()
        
        assert isinstance(initial_state, np.ndarray)
        assert len(initial_state) == env.get_observation_space_shape()[0]
        assert env.current_step == 0
        assert not env.done
        assert env.portfolio.balance == self.config.initial_balance
        
        # Check all pairs have valid starting indices
        for pair in self.currency_pairs:
            assert env.current_data_indices[pair] >= self.config.lookback_window
            
    def test_action_decoding(self):
        """Test multi-pair action decoding."""
        env = MultiPairTradingEnvironment(
            market_data=self.market_data,
            config=self.config
        )
        
        # Test action decoding
        action = 0  # All pairs HOLD
        pair_actions = env._decode_multi_pair_action(action)
        
        assert len(pair_actions) == len(self.currency_pairs)
        for pair in self.currency_pairs:
            assert pair_actions[pair] == 0  # HOLD
            
        # Test different action
        action = 1  # First pair BUY_SMALL, others HOLD
        pair_actions = env._decode_multi_pair_action(action)
        assert pair_actions[self.currency_pairs[0]] == 1  # BUY_SMALL
        
    def test_step_execution(self):
        """Test environment step execution."""
        env = MultiPairTradingEnvironment(
            market_data=self.market_data,
            config=self.config
        )
        
        initial_state = env.reset()
        
        # Execute a step
        action = 1  # First pair BUY_SMALL
        next_state, reward, done, info = env.step(action)
        
        assert isinstance(next_state, np.ndarray)
        assert isinstance(reward, float)
        assert isinstance(done, bool)
        assert isinstance(info, dict)
        
        # Check info contains multi-pair information
        assert 'pair_actions' in info
        assert 'execution_info' in info
        assert 'correlation_matrix' in info
        assert 'diversification_score' in info
        
        assert env.current_step == 1
        
    def test_position_management(self):
        """Test multi-pair position management."""
        env = MultiPairTradingEnvironment(
            market_data=self.market_data,
            config=self.config
        )
        
        env.reset()
        
        # Execute buy action for first pair
        action = 1  # First pair BUY_SMALL
        env.step(action)
        
        # Check position was created
        first_pair = self.currency_pairs[0]
        assert env.portfolio.pair_positions[first_pair] > 0
        assert env.portfolio.pair_trades[first_pair] == 1
        
    def test_correlation_matrix_update(self):
        """Test correlation matrix calculation."""
        env = MultiPairTradingEnvironment(
            market_data=self.market_data,
            config=self.config
        )
        
        env.reset()
        
        # Run several steps to build correlation data
        for _ in range(25):  # More than correlation_lookback
            action = 0  # HOLD
            _, _, done, _ = env.step(action)
            if done:
                break
                
        # Check correlation matrix is updated
        assert env.correlation_matrix.shape == (len(self.currency_pairs), len(self.currency_pairs))
        
        # Diagonal should be 1.0
        for i in range(len(self.currency_pairs)):
            assert abs(env.correlation_matrix[i, i] - 1.0) < 1e-6
            
    def test_pair_info_retrieval(self):
        """Test pair-specific information retrieval."""
        env = MultiPairTradingEnvironment(
            market_data=self.market_data,
            config=self.config
        )
        
        env.reset()
        
        # Get info for first pair
        first_pair = self.currency_pairs[0]
        pair_info = env.get_pair_info(first_pair)
        
        assert 'position' in pair_info
        assert 'unrealized_pnl' in pair_info
        assert 'win_rate' in pair_info
        assert 'volatility' in pair_info
        assert 'weight' in pair_info
        
    def test_invalid_market_data(self):
        """Test environment with invalid market data."""
        # Missing pair data
        incomplete_data = {pair: self.market_data[pair] for pair in self.currency_pairs[:-1]}
        
        with pytest.raises(ValueError, match="Missing market data for currency pair"):
            MultiPairTradingEnvironment(
                market_data=incomplete_data,
                config=self.config
            )
            
    def test_insufficient_market_data(self):
        """Test environment with insufficient market data."""
        # Create data with too few points
        insufficient_data = create_test_market_data(self.currency_pairs, 5)
        
        with pytest.raises(ValueError, match="Insufficient data"):
            MultiPairTradingEnvironment(
                market_data=insufficient_data,
                config=self.config
            )


class TestMultiPairStateProcessor:
    """Test multi-pair state processor functionality."""
    
    def setup_method(self):
        """Set up test state processor."""
        self.currency_pairs = ['EUR/USD', 'GBP/USD', 'USD/JPY']
        self.config = MultiPairEnvironmentConfig(
            currency_pairs=self.currency_pairs,
            state_features=['price', 'technical', 'portfolio'],
            action_space_type='discrete',
            reward_function='multi_objective',
            lookback_window=10,
            normalization_method='adaptive',
            transaction_cost=0.0001,
            max_position_size=1.0,
            initial_balance=10000.0
        )
        
        self.processor = MultiPairStateProcessor(self.config)
        self.market_data = create_test_market_data(self.currency_pairs, 50)
        
    def test_state_processor_initialization(self):
        """Test state processor initialization."""
        assert self.processor.currency_pairs == self.currency_pairs
        assert self.processor.total_dim > 0
        assert len(self.processor.pair_normalizers) == len(self.currency_pairs)
        
    def test_state_dimension_calculation(self):
        """Test state dimension calculation."""
        expected_per_pair = (
            self.processor.price_features_per_pair * self.config.lookback_window +
            self.processor.technical_features_per_pair +
            self.processor.pair_specific_features
        )
        
        expected_total = (
            expected_per_pair * len(self.currency_pairs) +
            self.processor.cross_pair_dim
        )
        
        assert self.processor.get_state_dimension() == expected_total
        
    def test_market_data_processing(self):
        """Test market data processing."""
        portfolio = MultiPairPortfolioState(
            balance=10000.0,
            equity=10000.0,
            current_position=0.0,
            unrealized_pnl=0.0,
            realized_pnl=0.0,
            total_trades=0,
            winning_trades=0,
            max_drawdown=0.0,
            current_drawdown=0.0
        )
        
        # Initialize pair data
        for pair in self.currency_pairs:
            portfolio.pair_positions[pair] = 0.0
            
        # Process market data
        lookback_data = {}
        for pair in self.currency_pairs:
            lookback_data[pair] = self.market_data[pair][-self.config.lookback_window:]
            
        correlation_matrix = np.eye(len(self.currency_pairs))
        pair_volatilities = {pair: 0.01 for pair in self.currency_pairs}
        
        state_vector = self.processor.process_market_data(
            lookback_data, portfolio, correlation_matrix, pair_volatilities
        )
        
        assert isinstance(state_vector, np.ndarray)
        assert len(state_vector) == self.processor.get_state_dimension()
        assert not np.any(np.isnan(state_vector))
        assert not np.any(np.isinf(state_vector))
        
    def test_currency_specific_normalization(self):
        """Test currency-specific normalization."""
        # Test different currency pairs have different normalizers
        eur_usd_normalizer = self.processor.pair_normalizers['EUR/USD']
        usd_jpy_normalizer = self.processor.pair_normalizers['USD/JPY']
        
        # JPY pairs should have different price scaling
        assert eur_usd_normalizer['price_scale'] != usd_jpy_normalizer['price_scale']
        
    def test_cross_pair_features(self):
        """Test cross-pair feature extraction."""
        portfolio = MultiPairPortfolioState(
            balance=10000.0,
            equity=10000.0,
            current_position=0.0,
            unrealized_pnl=0.0,
            realized_pnl=0.0,
            total_trades=0,
            winning_trades=0,
            max_drawdown=0.0,
            current_drawdown=0.0
        )
        
        # Set up portfolio with positions
        for pair in self.currency_pairs:
            portfolio.pair_positions[pair] = 0.1
            
        lookback_data = {}
        for pair in self.currency_pairs:
            lookback_data[pair] = self.market_data[pair][-self.config.lookback_window:]
            
        correlation_matrix = np.array([[1.0, 0.5, -0.3], [0.5, 1.0, 0.2], [-0.3, 0.2, 1.0]])
        pair_volatilities = {pair: 0.01 for pair in self.currency_pairs}
        
        cross_features = self.processor._extract_cross_pair_features(
            lookback_data, portfolio, correlation_matrix, pair_volatilities
        )
        
        assert len(cross_features) == self.processor.cross_pair_dim
        assert not any(np.isnan(f) for f in cross_features)


class TestMultiPairRewardCalculator:
    """Test multi-pair reward calculator functionality."""
    
    def setup_method(self):
        """Set up test reward calculator."""
        self.currency_pairs = ['EUR/USD', 'GBP/USD', 'USD/JPY']
        self.config = MultiPairEnvironmentConfig(
            currency_pairs=self.currency_pairs,
            state_features=['price', 'technical', 'portfolio'],
            action_space_type='discrete',
            reward_function='multi_objective',
            lookback_window=10,
            normalization_method='adaptive',
            transaction_cost=0.0001,
            max_position_size=1.0,
            initial_balance=10000.0
        )
        
        self.calculator = MultiPairRewardCalculator(self.config)
        
    def test_reward_calculator_initialization(self):
        """Test reward calculator initialization."""
        assert self.calculator.currency_pairs == self.currency_pairs
        assert hasattr(self.calculator, 'pnl_weight')
        assert hasattr(self.calculator, 'diversification_weight')
        
    def test_pnl_reward_calculation(self):
        """Test P&L reward calculation."""
        prev_portfolio = MultiPairPortfolioState(
            balance=10000.0,
            equity=10000.0,
            current_position=0.0,
            unrealized_pnl=0.0,
            realized_pnl=0.0,
            total_trades=0,
            winning_trades=0,
            max_drawdown=0.0,
            current_drawdown=0.0
        )
        
        current_portfolio = MultiPairPortfolioState(
            balance=10000.0,
            equity=10100.0,
            current_position=0.1,
            unrealized_pnl=100.0,
            realized_pnl=0.0,
            total_trades=1,
            winning_trades=0,
            max_drawdown=0.0,
            current_drawdown=0.0
        )
        
        pnl_reward = self.calculator._calculate_pnl_reward(prev_portfolio, current_portfolio)
        assert pnl_reward > 0  # Positive P&L should give positive reward
        
    def test_diversification_reward(self):
        """Test diversification reward calculation."""
        portfolio = MultiPairPortfolioState(
            balance=10000.0,
            equity=10000.0,
            current_position=0.0,
            unrealized_pnl=0.0,
            realized_pnl=0.0,
            total_trades=0,
            winning_trades=0,
            max_drawdown=0.0,
            current_drawdown=0.0
        )
        
        # Well-diversified portfolio
        portfolio.pair_positions = {
            'EUR/USD': 0.33,
            'GBP/USD': 0.33,
            'USD/JPY': 0.34
        }
        
        diversification_reward = self.calculator._calculate_diversification_reward(portfolio)
        assert diversification_reward >= 0  # Good diversification should be rewarded
        
        # Concentrated portfolio
        portfolio.pair_positions = {
            'EUR/USD': 1.0,
            'GBP/USD': 0.0,
            'USD/JPY': 0.0
        }
        
        diversification_reward = self.calculator._calculate_diversification_reward(portfolio)
        assert diversification_reward < 0  # Poor diversification should be penalized
        
    def test_full_reward_calculation(self):
        """Test full reward calculation."""
        prev_portfolio = MultiPairPortfolioState(
            balance=10000.0,
            equity=10000.0,
            current_position=0.0,
            unrealized_pnl=0.0,
            realized_pnl=0.0,
            total_trades=0,
            winning_trades=0,
            max_drawdown=0.0,
            current_drawdown=0.0
        )
        
        current_portfolio = MultiPairPortfolioState(
            balance=10000.0,
            equity=10050.0,
            current_position=0.1,
            unrealized_pnl=50.0,
            realized_pnl=0.0,
            total_trades=1,
            winning_trades=0,
            max_drawdown=0.0,
            current_drawdown=0.0
        )
        
        # Initialize pair data
        for pair in self.currency_pairs:
            prev_portfolio.pair_positions[pair] = 0.0
            current_portfolio.pair_positions[pair] = 0.0
            
        current_portfolio.pair_positions['EUR/USD'] = 0.1
        
        market_data = {}
        for pair in self.currency_pairs:
            market_data[pair] = MarketData(
                symbol=pair,
                timestamp=datetime.now(timezone.utc),
                open=1.2000,
                high=1.2010,
                low=1.1990,
                close=1.2005,
                volume=1000,
                bid=1.2003,
                ask=1.2007,
                spread=0.0004
            )
            
        reward = self.calculator.calculate_reward(
            prev_portfolio, current_portfolio, 1, market_data
        )
        
        assert isinstance(reward, float)
        assert not np.isnan(reward)
        assert not np.isinf(reward)
        
    def test_reward_breakdown(self):
        """Test detailed reward breakdown."""
        prev_portfolio = MultiPairPortfolioState(
            balance=10000.0,
            equity=10000.0,
            current_position=0.0,
            unrealized_pnl=0.0,
            realized_pnl=0.0,
            total_trades=0,
            winning_trades=0,
            max_drawdown=0.0,
            current_drawdown=0.0
        )
        
        current_portfolio = MultiPairPortfolioState(
            balance=10000.0,
            equity=10050.0,
            current_position=0.1,
            unrealized_pnl=50.0,
            realized_pnl=0.0,
            total_trades=1,
            winning_trades=0,
            max_drawdown=0.0,
            current_drawdown=0.0
        )
        
        # Initialize pair data
        for pair in self.currency_pairs:
            prev_portfolio.pair_positions[pair] = 0.0
            current_portfolio.pair_positions[pair] = 0.0
            
        market_data = {}
        for pair in self.currency_pairs:
            market_data[pair] = MarketData(
                symbol=pair,
                timestamp=datetime.now(timezone.utc),
                open=1.2000,
                high=1.2010,
                low=1.1990,
                close=1.2005,
                volume=1000,
                bid=1.2003,
                ask=1.2007,
                spread=0.0004
            )
            
        breakdown = self.calculator.get_reward_breakdown(
            prev_portfolio, current_portfolio, 1, market_data
        )
        
        assert isinstance(breakdown, dict)
        assert 'total_reward' in breakdown
        assert 'pnl_reward' in breakdown
        assert 'diversification_reward' in breakdown
        assert 'correlation_penalty' in breakdown


class TestMultiPairIntegration:
    """Integration tests for multi-pair environment components."""
    
    def setup_method(self):
        """Set up integration test environment."""
        self.currency_pairs = ['EUR/USD', 'GBP/USD', 'USD/JPY']
        self.config = MultiPairEnvironmentConfig(
            currency_pairs=self.currency_pairs,
            state_features=['price', 'technical', 'portfolio'],
            action_space_type='discrete',
            reward_function='multi_objective',
            lookback_window=10,
            normalization_method='adaptive',
            transaction_cost=0.0001,
            max_position_size=1.0,
            initial_balance=10000.0,
            max_episode_steps=50,
            min_episode_steps=10
        )
        
        self.market_data = create_test_market_data(self.currency_pairs, 100)
        
    def test_full_episode_execution(self):
        """Test complete episode execution."""
        env = MultiPairTradingEnvironment(
            market_data=self.market_data,
            config=self.config
        )
        
        state = env.reset()
        total_reward = 0.0
        steps = 0
        
        while not env.done and steps < self.config.max_episode_steps:
            # Random action
            action = np.random.randint(0, min(env.get_action_space_size(), 100))
            
            next_state, reward, done, info = env.step(action)
            
            assert isinstance(next_state, np.ndarray)
            assert isinstance(reward, float)
            assert isinstance(done, bool)
            assert isinstance(info, dict)
            
            total_reward += reward
            steps += 1
            state = next_state
            
        assert steps >= self.config.min_episode_steps
        logger.info(f"Episode completed in {steps} steps with total reward: {total_reward:.4f}")
        
    def test_multiple_episodes(self):
        """Test multiple episode execution."""
        env = MultiPairTradingEnvironment(
            market_data=self.market_data,
            config=self.config
        )
        
        episode_rewards = []
        
        for episode in range(3):
            state = env.reset()
            episode_reward = 0.0
            steps = 0
            
            while not env.done and steps < self.config.max_episode_steps:
                action = np.random.randint(0, min(env.get_action_space_size(), 100))
                next_state, reward, done, info = env.step(action)
                
                episode_reward += reward
                steps += 1
                state = next_state
                
            episode_rewards.append(episode_reward)
            logger.info(f"Episode {episode + 1} reward: {episode_reward:.4f}")
            
        assert len(episode_rewards) == 3
        assert all(isinstance(r, float) for r in episode_rewards)
        
    def test_various_currency_combinations(self):
        """Test environment with different currency pair combinations."""
        test_combinations = [
            ['EUR/USD', 'GBP/USD'],
            ['EUR/USD', 'USD/JPY', 'GBP/JPY'],
            ['EUR/USD', 'GBP/USD', 'USD/JPY', 'AUD/USD']
        ]
        
        for pairs in test_combinations:
            config = MultiPairEnvironmentConfig(
                currency_pairs=pairs,
                state_features=['price', 'technical'],
                action_space_type='discrete',
                reward_function='pnl',
                lookback_window=5,
                normalization_method='standard',
                transaction_cost=0.0001,
                max_position_size=1.0,
                initial_balance=10000.0,
                max_episode_steps=20
            )
            
            market_data = create_test_market_data(pairs, 50)
            
            env = MultiPairTradingEnvironment(
                market_data=market_data,
                config=config
            )
            
            # Test basic functionality
            state = env.reset()
            assert len(state) == env.get_observation_space_shape()[0]
            
            action = 0  # All HOLD
            next_state, reward, done, info = env.step(action)
            
            assert isinstance(reward, float)
            assert len(info['pair_actions']) == len(pairs)


if __name__ == '__main__':
    # Run tests
    pytest.main([__file__, '-v'])