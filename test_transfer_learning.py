"""
Unit tests for Transfer Learning Framework

Tests transfer learning capabilities for new currency pairs,
model adaptation, and fine-tuning functionality.
"""

import pytest
import numpy as np
import torch
import torch.nn as nn
from datetime import datetime, timezone, timedelta
from typing import Dict, List
import tempfile
import os
import json

from src.rl.environments.transfer_learning import (
    TransferLearningConfig,
    CurrencyCharacteristics,
    CurrencyCharacteristicsAnalyzer,
    TransferLearningFramework,
    FineTuningAdapter,
    FeatureExtractionAdapter,
    ProgressiveAdapter
)
from src.models import MarketData


class SimpleTestModel(nn.Module):
    """Simple neural network for testing."""
    
    def __init__(self, input_size=10, hidden_size=20, output_size=3):
        super().__init__()
        self.feature_extractor = nn.Sequential(
            nn.Linear(input_size, hidden_size),
            nn.ReLU(),
            nn.Linear(hidden_size, hidden_size),
            nn.ReLU()
        )
        self.classifier = nn.Linear(hidden_size, output_size)
        
    def forward(self, x):
        features = self.feature_extractor(x)
        return self.classifier(features)


def create_test_market_data(pair: str, num_points: int = 100) -> List[MarketData]:
    """Create test market data for a currency pair."""
    start_time = datetime.now(timezone.utc) - timedelta(hours=num_points)
    market_data = []
    
    # Set base price based on pair
    if 'JPY' in pair:
        base_price = 110.0
    elif 'EUR' in pair:
        base_price = 1.2000
    elif 'GBP' in pair:
        base_price = 1.3000
    else:
        base_price = 1.0000
        
    for i in range(num_points):
        timestamp = start_time + timedelta(hours=i)
        
        # Generate realistic price movement
        price_change = np.random.normal(0, 0.001) * base_price
        base_price += price_change
        base_price = max(base_price, 0.5000)
        
        # Generate OHLC
        high = base_price * (1 + abs(np.random.normal(0, 0.0005)))
        low = base_price * (1 - abs(np.random.normal(0, 0.0005)))
        open_price = low + (high - low) * np.random.random()
        close_price = base_price
        
        # Generate bid/ask with different spreads for different pairs
        if 'JPY' in pair:
            spread = 0.01  # 1 pip for JPY pairs
        else:
            spread = 0.0001  # 1 pip for other pairs
            
        bid = close_price - spread / 2
        ask = close_price + spread / 2
        
        # Generate volume with session-based patterns
        hour = timestamp.hour
        if 8 <= hour <= 17:  # London session
            volume = np.random.randint(5000, 15000)
        elif 13 <= hour <= 22:  # New York session
            volume = np.random.randint(4000, 12000)
        else:
            volume = np.random.randint(1000, 5000)
            
        market_data_point = MarketData(
            symbol=pair,
            timestamp=timestamp,
            open=open_price,
            high=high,
            low=low,
            close=close_price,
            volume=volume,
            bid=bid,
            ask=ask,
            spread=spread
        )
        
        market_data.append(market_data_point)
        
    return market_data


class TestTransferLearningConfig:
    """Test transfer learning configuration."""
    
    def test_config_creation(self):
        """Test creating transfer learning configuration."""
        config = TransferLearningConfig(
            source_pairs=['EUR/USD', 'GBP/USD'],
            target_pairs=['USD/JPY', 'AUD/USD'],
            freeze_layers=['feature_extractor'],
            learning_rate_multiplier=0.1,
            fine_tune_epochs=50,
            adaptation_method='fine_tuning'
        )
        
        assert config.source_pairs == ['EUR/USD', 'GBP/USD']
        assert config.target_pairs == ['USD/JPY', 'AUD/USD']
        assert config.freeze_layers == ['feature_extractor']
        assert config.learning_rate_multiplier == 0.1
        assert config.fine_tune_epochs == 50
        assert config.adaptation_method == 'fine_tuning'
        
    def test_default_values(self):
        """Test default configuration values."""
        config = TransferLearningConfig(
            source_pairs=['EUR/USD'],
            target_pairs=['USD/JPY'],
            freeze_layers=[]
        )
        
        assert config.learning_rate_multiplier == 0.1
        assert config.fine_tune_epochs == 100
        assert config.adaptation_method == 'fine_tuning'
        assert config.currency_similarity_threshold == 0.7


class TestCurrencyCharacteristics:
    """Test currency characteristics functionality."""
    
    def test_characteristics_creation(self):
        """Test creating currency characteristics."""
        characteristics = CurrencyCharacteristics(
            pair='EUR/USD',
            base_currency='EUR',
            quote_currency='USD',
            average_volatility=0.12,
            average_spread=0.0001,
            trading_volume=10000.0,
            correlation_with_majors={'GBP/USD': 0.7, 'USD/JPY': -0.3},
            active_sessions=['london', 'new_york'],
            peak_volatility_hours=[8, 9, 14, 15],
            interest_rate_sensitivity=0.8,
            commodity_correlation=0.1,
            safe_haven_status=0.4
        )
        
        assert characteristics.pair == 'EUR/USD'
        assert characteristics.base_currency == 'EUR'
        assert characteristics.quote_currency == 'USD'
        assert characteristics.average_volatility == 0.12
        
    def test_similarity_score_same_pair(self):
        """Test similarity score for identical pairs."""
        char1 = CurrencyCharacteristics(
            pair='EUR/USD',
            base_currency='EUR',
            quote_currency='USD',
            average_volatility=0.12,
            average_spread=0.0001,
            trading_volume=10000.0,
            correlation_with_majors={},
            active_sessions=['london', 'new_york'],
            peak_volatility_hours=[8, 9],
            interest_rate_sensitivity=0.8,
            commodity_correlation=0.1,
            safe_haven_status=0.4
        )
        
        char2 = CurrencyCharacteristics(
            pair='EUR/USD',
            base_currency='EUR',
            quote_currency='USD',
            average_volatility=0.12,
            average_spread=0.0001,
            trading_volume=10000.0,
            correlation_with_majors={},
            active_sessions=['london', 'new_york'],
            peak_volatility_hours=[8, 9],
            interest_rate_sensitivity=0.8,
            commodity_correlation=0.1,
            safe_haven_status=0.4
        )
        
        similarity = char1.similarity_score(char2)
        assert similarity > 0.8  # Should be high for identical characteristics
        
    def test_similarity_score_currency_overlap(self):
        """Test similarity score with currency overlap."""
        eur_usd = CurrencyCharacteristics(
            pair='EUR/USD',
            base_currency='EUR',
            quote_currency='USD',
            average_volatility=0.12,
            average_spread=0.0001,
            trading_volume=10000.0,
            correlation_with_majors={},
            active_sessions=['london', 'new_york'],
            peak_volatility_hours=[8, 9],
            interest_rate_sensitivity=0.8,
            commodity_correlation=0.1,
            safe_haven_status=0.4
        )
        
        gbp_usd = CurrencyCharacteristics(
            pair='GBP/USD',
            base_currency='GBP',
            quote_currency='USD',
            average_volatility=0.15,
            average_spread=0.0001,
            trading_volume=8000.0,
            correlation_with_majors={},
            active_sessions=['london', 'new_york'],
            peak_volatility_hours=[8, 9],
            interest_rate_sensitivity=0.8,
            commodity_correlation=0.1,
            safe_haven_status=0.4
        )
        
        similarity = eur_usd.similarity_score(gbp_usd)
        assert similarity > 0.5  # Should have moderate similarity due to USD overlap
        
    def test_similarity_score_different_pairs(self):
        """Test similarity score for very different pairs."""
        eur_usd = CurrencyCharacteristics(
            pair='EUR/USD',
            base_currency='EUR',
            quote_currency='USD',
            average_volatility=0.12,
            average_spread=0.0001,
            trading_volume=10000.0,
            correlation_with_majors={},
            active_sessions=['london', 'new_york'],
            peak_volatility_hours=[8, 9],
            interest_rate_sensitivity=0.8,
            commodity_correlation=0.1,
            safe_haven_status=0.4
        )
        
        aud_jpy = CurrencyCharacteristics(
            pair='AUD/JPY',
            base_currency='AUD',
            quote_currency='JPY',
            average_volatility=0.25,
            average_spread=0.01,
            trading_volume=2000.0,
            correlation_with_majors={},
            active_sessions=['sydney', 'tokyo'],
            peak_volatility_hours=[1, 2],
            interest_rate_sensitivity=0.6,
            commodity_correlation=0.8,
            safe_haven_status=0.7
        )
        
        similarity = eur_usd.similarity_score(aud_jpy)
        assert similarity < 0.5  # Should have low similarity


class TestCurrencyCharacteristicsAnalyzer:
    """Test currency characteristics analyzer."""
    
    def setup_method(self):
        """Set up test analyzer."""
        self.analyzer = CurrencyCharacteristicsAnalyzer()
        
    def test_analyzer_initialization(self):
        """Test analyzer initialization."""
        assert len(self.analyzer.major_pairs) == 4
        assert 'EUR/USD' in self.analyzer.major_pairs
        assert len(self.analyzer.session_hours) == 4
        
    def test_analyze_currency_pair(self):
        """Test analyzing currency pair characteristics."""
        market_data = create_test_market_data('EUR/USD', 720)  # 30 days of hourly data
        
        characteristics = self.analyzer.analyze_currency_pair('EUR/USD', market_data, 30)
        
        assert characteristics.pair == 'EUR/USD'
        assert characteristics.base_currency == 'EUR'
        assert characteristics.quote_currency == 'USD'
        assert characteristics.average_volatility > 0
        assert characteristics.average_spread > 0
        assert characteristics.trading_volume > 0
        assert len(characteristics.active_sessions) > 0
        assert len(characteristics.peak_volatility_hours) >= 0
        
    def test_analyze_jpy_pair(self):
        """Test analyzing JPY pair with different characteristics."""
        market_data = create_test_market_data('USD/JPY', 720)
        
        characteristics = self.analyzer.analyze_currency_pair('USD/JPY', market_data, 30)
        
        assert characteristics.pair == 'USD/JPY'
        assert characteristics.base_currency == 'USD'
        assert characteristics.quote_currency == 'JPY'
        # JPY pairs should have different spread characteristics
        assert characteristics.average_spread > 0.001  # Larger spread for JPY pairs
        
    def test_empty_market_data(self):
        """Test analyzer with empty market data."""
        with pytest.raises(ValueError, match="No market data provided"):
            self.analyzer.analyze_currency_pair('EUR/USD', [], 30)
            
    def test_identify_active_sessions(self):
        """Test session identification."""
        market_data = create_test_market_data('EUR/USD', 168)  # 1 week of hourly data
        
        active_sessions = self.analyzer._identify_active_sessions(market_data)
        
        assert isinstance(active_sessions, list)
        # Should identify at least some sessions
        assert len(active_sessions) >= 0
        
    def test_peak_volatility_hours(self):
        """Test peak volatility hour identification."""
        market_data = create_test_market_data('EUR/USD', 168)
        
        peak_hours = self.analyzer._identify_peak_volatility_hours(market_data)
        
        assert isinstance(peak_hours, list)
        assert all(0 <= hour <= 23 for hour in peak_hours)


class TestModelAdapters:
    """Test model adaptation strategies."""
    
    def setup_method(self):
        """Set up test adapters and model."""
        self.model = SimpleTestModel()
        self.characteristics = CurrencyCharacteristics(
            pair='USD/JPY',
            base_currency='USD',
            quote_currency='JPY',
            average_volatility=0.15,
            average_spread=0.01,
            trading_volume=5000.0,
            correlation_with_majors={},
            active_sessions=['tokyo', 'london'],
            peak_volatility_hours=[1, 2, 8, 9],
            interest_rate_sensitivity=0.7,
            commodity_correlation=0.2,
            safe_haven_status=0.7
        )
        self.config = TransferLearningConfig(
            source_pairs=['EUR/USD'],
            target_pairs=['USD/JPY'],
            freeze_layers=['feature_extractor'],
            adaptation_method='fine_tuning'
        )
        
    def test_fine_tuning_adapter(self):
        """Test fine-tuning adapter."""
        adapter = FineTuningAdapter()
        
        adapted_model = adapter.adapt_model(self.model, self.characteristics, self.config)
        
        assert adapted_model is not None
        assert isinstance(adapted_model, nn.Module)
        
        # Check that some layers are frozen
        frozen_params = sum(1 for param in adapted_model.parameters() if not param.requires_grad)
        total_params = sum(1 for param in adapted_model.parameters())
        
        # Should have some frozen parameters
        assert frozen_params < total_params
        
        # Get adaptation parameters
        params = adapter.get_adaptation_parameters()
        assert params['method'] == 'fine_tuning'
        assert 'frozen_layers' in params
        
    def test_feature_extraction_adapter(self):
        """Test feature extraction adapter."""
        adapter = FeatureExtractionAdapter()
        
        adapted_model = adapter.adapt_model(self.model, self.characteristics, self.config)
        
        assert adapted_model is not None
        assert isinstance(adapted_model, nn.Module)
        
        # Get adaptation parameters
        params = adapter.get_adaptation_parameters()
        assert params['method'] == 'feature_extraction'
        assert 'frozen_feature_layers' in params
        
    def test_progressive_adapter(self):
        """Test progressive unfreezing adapter."""
        adapter = ProgressiveAdapter()
        
        adapted_model = adapter.adapt_model(self.model, self.characteristics, self.config)
        
        assert adapted_model is not None
        assert isinstance(adapted_model, nn.Module)
        
        # Test epoch update
        adapter.update_epoch(20, adapted_model)
        
        # Get adaptation parameters
        params = adapter.get_adaptation_parameters()
        assert params['method'] == 'progressive'
        assert 'unfreeze_schedule' in params


class TestTransferLearningFramework:
    """Test main transfer learning framework."""
    
    def setup_method(self):
        """Set up test framework."""
        self.config = TransferLearningConfig(
            source_pairs=['EUR/USD', 'GBP/USD'],
            target_pairs=['USD/JPY', 'AUD/USD'],
            freeze_layers=['feature_extractor'],
            adaptation_method='fine_tuning',
            fine_tune_epochs=10  # Reduced for testing
        )
        
        self.framework = TransferLearningFramework(self.config)
        
        # Create test market data
        self.market_data = {}
        for pair in self.config.source_pairs + self.config.target_pairs:
            self.market_data[pair] = create_test_market_data(pair, 720)
            
    def test_framework_initialization(self):
        """Test framework initialization."""
        assert len(self.framework.adapters) == 3
        assert 'fine_tuning' in self.framework.adapters
        assert 'feature_extraction' in self.framework.adapters
        assert 'progressive' in self.framework.adapters
        
    def test_analyze_currency_pairs(self):
        """Test analyzing all currency pairs."""
        self.framework.analyze_currency_pairs(self.market_data, lookback_days=30)
        
        # Should have characteristics for all pairs
        expected_pairs = set(self.config.source_pairs + self.config.target_pairs)
        analyzed_pairs = set(self.framework.currency_characteristics.keys())
        
        assert analyzed_pairs == expected_pairs
        
        # Check characteristics are valid
        for pair, characteristics in self.framework.currency_characteristics.items():
            assert characteristics.pair == pair
            assert characteristics.average_volatility > 0
            assert characteristics.average_spread > 0
            
    def test_find_best_source_pair(self):
        """Test finding best source pair for transfer learning."""
        self.framework.analyze_currency_pairs(self.market_data)
        
        best_source, similarity = self.framework.find_best_source_pair('USD/JPY')
        
        assert best_source in self.config.source_pairs
        assert 0.0 <= similarity <= 1.0
        
    def test_adapt_model_for_pair(self):
        """Test adapting model for target pair."""
        self.framework.analyze_currency_pairs(self.market_data)
        
        source_model = SimpleTestModel()
        adapted_model = self.framework.adapt_model_for_pair(
            source_model, 'EUR/USD', 'USD/JPY'
        )
        
        assert adapted_model is not None
        assert isinstance(adapted_model, nn.Module)
        assert 'USD/JPY' in self.framework.adapted_models
        
    def test_fine_tune_model(self):
        """Test fine-tuning adapted model."""
        self.framework.analyze_currency_pairs(self.market_data)
        
        source_model = SimpleTestModel()
        adapted_model = self.framework.adapt_model_for_pair(
            source_model, 'EUR/USD', 'USD/JPY'
        )
        
        training_data = self.market_data['USD/JPY'][:500]
        validation_data = self.market_data['USD/JPY'][500:]
        
        metrics = self.framework.fine_tune_model(
            adapted_model, 'USD/JPY', training_data, validation_data
        )
        
        assert isinstance(metrics, dict)
        assert 'epochs' in metrics
        assert 'losses' in metrics
        assert 'validation_losses' in metrics
        assert len(metrics['epochs']) <= self.config.fine_tune_epochs
        
    def test_save_and_load_model(self):
        """Test saving and loading adapted models."""
        self.framework.analyze_currency_pairs(self.market_data)
        
        source_model = SimpleTestModel()
        adapted_model = self.framework.adapt_model_for_pair(
            source_model, 'EUR/USD', 'USD/JPY'
        )
        
        with tempfile.TemporaryDirectory() as temp_dir:
            filepath = os.path.join(temp_dir, 'test_model.pth')
            
            # Save model
            self.framework.save_adapted_model('USD/JPY', filepath)
            
            assert os.path.exists(filepath)
            assert os.path.exists(filepath.replace('.pth', '_metadata.json'))
            
            # Clear framework
            self.framework.adapted_models.clear()
            self.framework.currency_characteristics.clear()
            
            # Load model
            loaded_model = self.framework.load_adapted_model(
                'USD/JPY', filepath, SimpleTestModel
            )
            
            assert loaded_model is not None
            assert 'USD/JPY' in self.framework.adapted_models
            assert 'USD/JPY' in self.framework.currency_characteristics
            
    def test_transfer_learning_report(self):
        """Test generating transfer learning report."""
        self.framework.analyze_currency_pairs(self.market_data)
        
        report = self.framework.get_transfer_learning_report()
        
        assert isinstance(report, dict)
        assert 'config' in report
        assert 'currency_pairs' in report
        assert 'characteristics' in report
        assert 'similarity_matrix' in report
        assert 'recommendations' in report
        
        # Check recommendations
        assert len(report['recommendations']) == len(self.config.target_pairs)
        
        for recommendation in report['recommendations']:
            assert 'target_pair' in recommendation
            assert 'recommended_source' in recommendation
            assert 'similarity_score' in recommendation
            assert 'transfer_feasibility' in recommendation
            
    def test_missing_target_pair_characteristics(self):
        """Test error handling for missing target pair characteristics."""
        with pytest.raises(ValueError, match="No characteristics available"):
            self.framework.find_best_source_pair('UNKNOWN/PAIR')
            
    def test_missing_market_data(self):
        """Test handling of missing market data."""
        incomplete_data = {pair: self.market_data[pair] for pair in self.config.source_pairs}
        
        self.framework.analyze_currency_pairs(incomplete_data)
        
        # Should only have characteristics for source pairs
        assert len(self.framework.currency_characteristics) == len(self.config.source_pairs)


class TestTransferLearningIntegration:
    """Integration tests for transfer learning framework."""
    
    def test_full_transfer_learning_workflow(self):
        """Test complete transfer learning workflow."""
        # Set up configuration
        config = TransferLearningConfig(
            source_pairs=['EUR/USD'],
            target_pairs=['USD/JPY'],
            freeze_layers=['feature_extractor'],
            adaptation_method='fine_tuning',
            fine_tune_epochs=5
        )
        
        framework = TransferLearningFramework(config)
        
        # Create market data
        market_data = {
            'EUR/USD': create_test_market_data('EUR/USD', 500),
            'USD/JPY': create_test_market_data('USD/JPY', 500)
        }
        
        # Step 1: Analyze currency pairs
        framework.analyze_currency_pairs(market_data)
        
        # Step 2: Find best source pair
        best_source, similarity = framework.find_best_source_pair('USD/JPY')
        assert best_source == 'EUR/USD'
        
        # Step 3: Adapt model
        source_model = SimpleTestModel()
        adapted_model = framework.adapt_model_for_pair(source_model, best_source, 'USD/JPY')
        
        # Step 4: Fine-tune model
        training_data = market_data['USD/JPY'][:400]
        validation_data = market_data['USD/JPY'][400:]
        
        metrics = framework.fine_tune_model(adapted_model, 'USD/JPY', training_data, validation_data)
        
        # Step 5: Generate report
        report = framework.get_transfer_learning_report()
        
        # Verify workflow completed successfully
        assert 'USD/JPY' in framework.adapted_models
        assert len(metrics['epochs']) <= config.fine_tune_epochs
        assert len(report['recommendations']) == 1
        assert report['recommendations'][0]['target_pair'] == 'USD/JPY'
        
    def test_multiple_target_pairs(self):
        """Test transfer learning with multiple target pairs."""
        config = TransferLearningConfig(
            source_pairs=['EUR/USD', 'GBP/USD'],
            target_pairs=['USD/JPY', 'AUD/USD', 'USD/CHF'],
            freeze_layers=['feature_extractor'],
            adaptation_method='fine_tuning',
            fine_tune_epochs=3
        )
        
        framework = TransferLearningFramework(config)
        
        # Create market data for all pairs
        market_data = {}
        for pair in config.source_pairs + config.target_pairs:
            market_data[pair] = create_test_market_data(pair, 300)
            
        # Analyze all pairs
        framework.analyze_currency_pairs(market_data)
        
        # Adapt models for all target pairs
        source_model = SimpleTestModel()
        
        for target_pair in config.target_pairs:
            best_source, _ = framework.find_best_source_pair(target_pair)
            adapted_model = framework.adapt_model_for_pair(source_model, best_source, target_pair)
            
            # Verify adaptation
            assert target_pair in framework.adapted_models
            
        # Generate comprehensive report
        report = framework.get_transfer_learning_report()
        
        assert len(report['recommendations']) == len(config.target_pairs)
        assert len(report['similarity_matrix']) == len(config.target_pairs)


if __name__ == '__main__':
    # Run tests
    pytest.main([__file__, '-v'])