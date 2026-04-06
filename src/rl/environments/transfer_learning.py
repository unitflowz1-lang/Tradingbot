"""
Transfer Learning Framework for Multi-Currency Pair RL Agents

This module implements transfer learning capabilities for adapting
pre-trained RL models to new currency pairs with different market characteristics.
"""

import numpy as np
from typing import Dict, Any, List, Optional, Tuple, Union
import torch
import torch.nn as nn
import torch.optim as optim
from datetime import datetime, timedelta
import logging
from pathlib import Path
import pickle
import json
from dataclasses import dataclass, asdict
from abc import ABC, abstractmethod

from ...models import MarketData
from .multi_pair_environment import MultiPairEnvironmentConfig, MultiPairPortfolioState


logger = logging.getLogger(__name__)


@dataclass
class TransferLearningConfig:
    """Configuration for transfer learning framework."""
    
    # Source model configuration
    source_pairs: List[str]
    target_pairs: List[str]
    
    # Transfer learning parameters
    freeze_layers: List[str]  # Layer names to freeze during transfer
    learning_rate_multiplier: float = 0.1  # Reduce LR for pre-trained layers
    fine_tune_epochs: int = 100
    adaptation_method: str = 'fine_tuning'  # 'fine_tuning', 'feature_extraction', 'progressive'
    
    # Currency similarity parameters
    currency_similarity_threshold: float = 0.7
    market_regime_adaptation: bool = True
    volatility_adaptation: bool = True
    
    # Progressive transfer parameters
    progressive_unfreezing: bool = False
    unfreeze_schedule: List[int] = None  # Epochs at which to unfreeze layers
    
    # Validation parameters
    validation_split: float = 0.2
    early_stopping_patience: int = 10
    min_improvement: float = 0.001


@dataclass
class CurrencyCharacteristics:
    """Characteristics of a currency pair for transfer learning."""
    
    pair: str
    base_currency: str
    quote_currency: str
    
    # Market characteristics
    average_volatility: float
    average_spread: float
    trading_volume: float
    correlation_with_majors: Dict[str, float]
    
    # Temporal characteristics
    active_sessions: List[str]  # ['london', 'new_york', 'tokyo', 'sydney']
    peak_volatility_hours: List[int]
    
    # Economic factors
    interest_rate_sensitivity: float
    commodity_correlation: float
    safe_haven_status: float  # 0-1 scale
    
    def similarity_score(self, other: 'CurrencyCharacteristics') -> float:
        """Calculate similarity score with another currency pair."""
        # Currency overlap bonus
        currency_overlap = 0.0
        if self.base_currency == other.base_currency or self.base_currency == other.quote_currency:
            currency_overlap += 0.3
        if self.quote_currency == other.base_currency or self.quote_currency == other.quote_currency:
            currency_overlap += 0.3
            
        # Volatility similarity
        vol_diff = abs(self.average_volatility - other.average_volatility)
        vol_similarity = max(0, 1.0 - vol_diff / max(self.average_volatility, other.average_volatility))
        
        # Spread similarity
        spread_diff = abs(self.average_spread - other.average_spread)
        spread_similarity = max(0, 1.0 - spread_diff / max(self.average_spread, other.average_spread))
        
        # Session overlap
        session_overlap = len(set(self.active_sessions) & set(other.active_sessions)) / len(set(self.active_sessions) | set(other.active_sessions))
        
        # Weighted combination
        similarity = (
            0.4 * currency_overlap +
            0.25 * vol_similarity +
            0.15 * spread_similarity +
            0.2 * session_overlap
        )
        
        return min(1.0, similarity)


class ModelAdapter(ABC):
    """Abstract base class for model adaptation strategies."""
    
    @abstractmethod
    def adapt_model(self, 
                   source_model: nn.Module,
                   target_characteristics: CurrencyCharacteristics,
                   config: TransferLearningConfig) -> nn.Module:
        """Adapt source model for target currency pair."""
        pass
        
    @abstractmethod
    def get_adaptation_parameters(self) -> Dict[str, Any]:
        """Get parameters specific to this adaptation method."""
        pass


class FineTuningAdapter(ModelAdapter):
    """Fine-tuning adaptation strategy."""
    
    def __init__(self):
        self.frozen_layers = []
        self.adapted_layers = []
        
    def adapt_model(self, 
                   source_model: nn.Module,
                   target_characteristics: CurrencyCharacteristics,
                   config: TransferLearningConfig) -> nn.Module:
        """Adapt model using fine-tuning approach."""
        # Clone the source model
        adapted_model = self._clone_model(source_model)
        
        # Freeze specified layers
        self._freeze_layers(adapted_model, config.freeze_layers)
        
        # Adapt input/output layers if needed
        self._adapt_io_layers(adapted_model, target_characteristics)
        
        logger.info(f"Adapted model for {target_characteristics.pair} using fine-tuning")
        return adapted_model
        
    def _clone_model(self, model: nn.Module) -> nn.Module:
        """Create a deep copy of the model."""
        # This is a simplified version - in practice, you'd need to handle
        # the specific model architecture
        import copy
        return copy.deepcopy(model)
        
    def _freeze_layers(self, model: nn.Module, layer_names: List[str]) -> None:
        """Freeze specified layers."""
        for name, param in model.named_parameters():
            if any(layer_name in name for layer_name in layer_names):
                param.requires_grad = False
                self.frozen_layers.append(name)
            else:
                self.adapted_layers.append(name)
                
        logger.info(f"Frozen {len(self.frozen_layers)} layers, adapting {len(self.adapted_layers)} layers")
        
    def _adapt_io_layers(self, model: nn.Module, characteristics: CurrencyCharacteristics) -> None:
        """Adapt input/output layers for currency-specific features."""
        # This would be implemented based on the specific model architecture
        # For now, we'll just log the adaptation
        logger.info(f"Adapted I/O layers for {characteristics.pair}")
        
    def get_adaptation_parameters(self) -> Dict[str, Any]:
        """Get fine-tuning specific parameters."""
        return {
            'method': 'fine_tuning',
            'frozen_layers': self.frozen_layers,
            'adapted_layers': self.adapted_layers
        }


class FeatureExtractionAdapter(ModelAdapter):
    """Feature extraction adaptation strategy."""
    
    def __init__(self):
        self.feature_layers = []
        self.new_classifier = None
        
    def adapt_model(self, 
                   source_model: nn.Module,
                   target_characteristics: CurrencyCharacteristics,
                   config: TransferLearningConfig) -> nn.Module:
        """Adapt model using feature extraction approach."""
        # Freeze all layers except the final classifier
        adapted_model = self._clone_model(source_model)
        
        # Freeze feature extraction layers
        self._freeze_feature_layers(adapted_model)
        
        # Replace classifier for new currency pair
        self._replace_classifier(adapted_model, target_characteristics)
        
        logger.info(f"Adapted model for {target_characteristics.pair} using feature extraction")
        return adapted_model
        
    def _clone_model(self, model: nn.Module) -> nn.Module:
        """Create a deep copy of the model."""
        import copy
        return copy.deepcopy(model)
        
    def _freeze_feature_layers(self, model: nn.Module) -> None:
        """Freeze all layers except classifier."""
        for name, param in model.named_parameters():
            if 'classifier' not in name and 'fc' not in name:  # Keep classifier layers trainable
                param.requires_grad = False
                self.feature_layers.append(name)
                
        logger.info(f"Frozen {len(self.feature_layers)} feature extraction layers")
        
    def _replace_classifier(self, model: nn.Module, characteristics: CurrencyCharacteristics) -> None:
        """Replace classifier layers for new currency pair."""
        # This would be implemented based on the specific model architecture
        logger.info(f"Replaced classifier for {characteristics.pair}")
        
    def get_adaptation_parameters(self) -> Dict[str, Any]:
        """Get feature extraction specific parameters."""
        return {
            'method': 'feature_extraction',
            'frozen_feature_layers': self.feature_layers,
            'new_classifier': str(self.new_classifier)
        }


class ProgressiveAdapter(ModelAdapter):
    """Progressive unfreezing adaptation strategy."""
    
    def __init__(self):
        self.unfreeze_schedule = []
        self.current_epoch = 0
        
    def adapt_model(self, 
                   source_model: nn.Module,
                   target_characteristics: CurrencyCharacteristics,
                   config: TransferLearningConfig) -> nn.Module:
        """Adapt model using progressive unfreezing."""
        adapted_model = self._clone_model(source_model)
        
        # Initially freeze all layers
        self._freeze_all_layers(adapted_model)
        
        # Set up unfreezing schedule
        self.unfreeze_schedule = config.unfreeze_schedule or self._create_default_schedule(adapted_model)
        
        logger.info(f"Adapted model for {target_characteristics.pair} using progressive unfreezing")
        return adapted_model
        
    def _clone_model(self, model: nn.Module) -> nn.Module:
        """Create a deep copy of the model."""
        import copy
        return copy.deepcopy(model)
        
    def _freeze_all_layers(self, model: nn.Module) -> None:
        """Freeze all layers initially."""
        for param in model.parameters():
            param.requires_grad = False
            
    def _create_default_schedule(self, model: nn.Module) -> List[int]:
        """Create default unfreezing schedule."""
        # Unfreeze layers progressively every 20 epochs
        num_layers = len(list(model.named_parameters()))
        return [20 * i for i in range(1, num_layers // 5 + 1)]
        
    def update_epoch(self, epoch: int, model: nn.Module) -> None:
        """Update model based on current epoch and unfreezing schedule."""
        if epoch in self.unfreeze_schedule:
            self._unfreeze_next_layer(model)
            
    def _unfreeze_next_layer(self, model: nn.Module) -> None:
        """Unfreeze the next layer in sequence."""
        # This would be implemented based on the specific model architecture
        logger.info(f"Unfroze next layer at epoch {self.current_epoch}")
        
    def get_adaptation_parameters(self) -> Dict[str, Any]:
        """Get progressive unfreezing specific parameters."""
        return {
            'method': 'progressive',
            'unfreeze_schedule': self.unfreeze_schedule,
            'current_epoch': self.current_epoch
        }


class CurrencyCharacteristicsAnalyzer:
    """Analyzes market data to extract currency pair characteristics."""
    
    def __init__(self):
        self.major_pairs = ['EUR/USD', 'GBP/USD', 'USD/JPY', 'USD/CHF']
        self.session_hours = {
            'sydney': (22, 7),    # UTC hours
            'tokyo': (0, 9),
            'london': (8, 17),
            'new_york': (13, 22)
        }
        
    def analyze_currency_pair(self, 
                            pair: str,
                            market_data: List[MarketData],
                            lookback_days: int = 30) -> CurrencyCharacteristics:
        """Analyze market data to extract currency characteristics."""
        if not market_data:
            raise ValueError(f"No market data provided for {pair}")
            
        base_currency, quote_currency = pair.split('/')
        
        # Calculate basic statistics
        closes = [data.close for data in market_data[-lookback_days * 24:]]  # Assuming hourly data
        spreads = [data.spread for data in market_data[-lookback_days * 24:]]
        volumes = [data.volume for data in market_data[-lookback_days * 24:]]
        
        # Calculate volatility
        returns = np.diff(closes) / closes[:-1]
        volatility = np.std(returns) * np.sqrt(252 * 24)  # Annualized hourly volatility
        
        # Calculate average spread and volume
        avg_spread = np.mean(spreads)
        avg_volume = np.mean(volumes)
        
        # Analyze trading sessions
        active_sessions = self._identify_active_sessions(market_data[-lookback_days * 24:])
        peak_hours = self._identify_peak_volatility_hours(market_data[-lookback_days * 24:])
        
        # Calculate correlations with major pairs (simplified)
        correlations = self._calculate_correlations_with_majors(pair, market_data)
        
        # Estimate other characteristics (simplified)
        characteristics = CurrencyCharacteristics(
            pair=pair,
            base_currency=base_currency,
            quote_currency=quote_currency,
            average_volatility=volatility,
            average_spread=avg_spread,
            trading_volume=avg_volume,
            correlation_with_majors=correlations,
            active_sessions=active_sessions,
            peak_volatility_hours=peak_hours,
            interest_rate_sensitivity=self._estimate_interest_rate_sensitivity(base_currency, quote_currency),
            commodity_correlation=self._estimate_commodity_correlation(base_currency, quote_currency),
            safe_haven_status=self._estimate_safe_haven_status(base_currency, quote_currency)
        )
        
        logger.info(f"Analyzed characteristics for {pair}: volatility={volatility:.4f}, spread={avg_spread:.6f}")
        return characteristics
        
    def _identify_active_sessions(self, market_data: List[MarketData]) -> List[str]:
        """Identify active trading sessions based on volume patterns."""
        # Simplified implementation - analyze volume by hour
        hourly_volumes = {}
        for data in market_data:
            hour = data.timestamp.hour
            if hour not in hourly_volumes:
                hourly_volumes[hour] = []
            hourly_volumes[hour].append(data.volume)
            
        # Calculate average volume by hour
        avg_hourly_volumes = {hour: np.mean(volumes) for hour, volumes in hourly_volumes.items()}
        overall_avg = np.mean(list(avg_hourly_volumes.values()))
        
        # Identify sessions with above-average volume
        active_sessions = []
        for session, (start_hour, end_hour) in self.session_hours.items():
            session_hours = list(range(start_hour, end_hour + 1)) if start_hour <= end_hour else list(range(start_hour, 24)) + list(range(0, end_hour + 1))
            session_volume = np.mean([avg_hourly_volumes.get(hour, 0) for hour in session_hours])
            
            if session_volume > overall_avg * 1.2:  # 20% above average
                active_sessions.append(session)
                
        return active_sessions
        
    def _identify_peak_volatility_hours(self, market_data: List[MarketData]) -> List[int]:
        """Identify hours with peak volatility."""
        hourly_volatilities = {}
        
        for data in market_data:
            hour = data.timestamp.hour
            if hour not in hourly_volatilities:
                hourly_volatilities[hour] = []
                
            # Calculate hourly volatility using high-low range
            volatility = (data.high - data.low) / data.close
            hourly_volatilities[hour].append(volatility)
            
        # Calculate average volatility by hour
        avg_hourly_vol = {hour: np.mean(vols) for hour, vols in hourly_volatilities.items()}
        overall_avg_vol = np.mean(list(avg_hourly_vol.values()))
        
        # Return hours with above-average volatility
        peak_hours = [hour for hour, vol in avg_hourly_vol.items() if vol > overall_avg_vol * 1.3]
        return sorted(peak_hours)
        
    def _calculate_correlations_with_majors(self, pair: str, market_data: List[MarketData]) -> Dict[str, float]:
        """Calculate correlations with major currency pairs."""
        # Simplified implementation - return estimated correlations
        base_currency, quote_currency = pair.split('/')
        correlations = {}
        
        for major_pair in self.major_pairs:
            if major_pair == pair:
                correlations[major_pair] = 1.0
            else:
                major_base, major_quote = major_pair.split('/')
                
                # Estimate correlation based on currency overlap
                if base_currency == major_base or quote_currency == major_quote:
                    correlations[major_pair] = 0.7
                elif base_currency == major_quote or quote_currency == major_base:
                    correlations[major_pair] = -0.7
                else:
                    correlations[major_pair] = 0.1  # Low correlation
                    
        return correlations
        
    def _estimate_interest_rate_sensitivity(self, base_currency: str, quote_currency: str) -> float:
        """Estimate interest rate sensitivity."""
        # Simplified implementation based on currency characteristics
        high_sensitivity_currencies = ['USD', 'EUR', 'GBP', 'AUD', 'NZD']
        
        base_sensitive = base_currency in high_sensitivity_currencies
        quote_sensitive = quote_currency in high_sensitivity_currencies
        
        if base_sensitive and quote_sensitive:
            return 0.8
        elif base_sensitive or quote_sensitive:
            return 0.6
        else:
            return 0.3
            
    def _estimate_commodity_correlation(self, base_currency: str, quote_currency: str) -> float:
        """Estimate commodity correlation."""
        commodity_currencies = {'AUD': 0.8, 'NZD': 0.7, 'CAD': 0.9, 'NOK': 0.6}
        
        base_corr = commodity_currencies.get(base_currency, 0.0)
        quote_corr = commodity_currencies.get(quote_currency, 0.0)
        
        return max(base_corr, quote_corr)
        
    def _estimate_safe_haven_status(self, base_currency: str, quote_currency: str) -> float:
        """Estimate safe haven status."""
        safe_haven_currencies = {'USD': 0.9, 'CHF': 0.8, 'JPY': 0.7, 'EUR': 0.4}
        
        base_status = safe_haven_currencies.get(base_currency, 0.0)
        quote_status = safe_haven_currencies.get(quote_currency, 0.0)
        
        return max(base_status, quote_status)


class TransferLearningFramework:
    """Main framework for transfer learning between currency pairs."""
    
    def __init__(self, config: TransferLearningConfig):
        self.config = config
        self.analyzer = CurrencyCharacteristicsAnalyzer()
        self.adapters = {
            'fine_tuning': FineTuningAdapter(),
            'feature_extraction': FeatureExtractionAdapter(),
            'progressive': ProgressiveAdapter()
        }
        
        # Storage for characteristics and models
        self.currency_characteristics: Dict[str, CurrencyCharacteristics] = {}
        self.adapted_models: Dict[str, nn.Module] = {}
        
        logger.info(f"Initialized transfer learning framework for {len(config.target_pairs)} target pairs")
        
    def analyze_currency_pairs(self, 
                             market_data: Dict[str, List[MarketData]],
                             lookback_days: int = 30) -> None:
        """Analyze characteristics of all currency pairs."""
        all_pairs = set(self.config.source_pairs + self.config.target_pairs)
        
        for pair in all_pairs:
            if pair in market_data:
                characteristics = self.analyzer.analyze_currency_pair(
                    pair, market_data[pair], lookback_days
                )
                self.currency_characteristics[pair] = characteristics
                logger.info(f"Analyzed characteristics for {pair}")
            else:
                logger.warning(f"No market data available for {pair}")
                
    def find_best_source_pair(self, target_pair: str) -> Tuple[str, float]:
        """Find the best source pair for transfer learning to target pair."""
        if target_pair not in self.currency_characteristics:
            raise ValueError(f"No characteristics available for target pair {target_pair}")
            
        target_characteristics = self.currency_characteristics[target_pair]
        best_source = None
        best_similarity = 0.0
        
        for source_pair in self.config.source_pairs:
            if source_pair in self.currency_characteristics:
                source_characteristics = self.currency_characteristics[source_pair]
                similarity = target_characteristics.similarity_score(source_characteristics)
                
                if similarity > best_similarity:
                    best_similarity = similarity
                    best_source = source_pair
                    
        logger.info(f"Best source pair for {target_pair}: {best_source} (similarity: {best_similarity:.3f})")
        return best_source, best_similarity
        
    def adapt_model_for_pair(self, 
                           source_model: nn.Module,
                           source_pair: str,
                           target_pair: str) -> nn.Module:
        """Adapt a source model for a target currency pair."""
        if target_pair not in self.currency_characteristics:
            raise ValueError(f"No characteristics available for target pair {target_pair}")
            
        target_characteristics = self.currency_characteristics[target_pair]
        adapter = self.adapters[self.config.adaptation_method]
        
        adapted_model = adapter.adapt_model(source_model, target_characteristics, self.config)
        self.adapted_models[target_pair] = adapted_model
        
        logger.info(f"Adapted model from {source_pair} to {target_pair} using {self.config.adaptation_method}")
        return adapted_model
        
    def fine_tune_model(self, 
                       model: nn.Module,
                       target_pair: str,
                       training_data: List[MarketData],
                       validation_data: Optional[List[MarketData]] = None) -> Dict[str, Any]:
        """Fine-tune adapted model on target pair data."""
        # This is a simplified implementation - in practice, you'd need to
        # implement the full training loop with the RL environment
        
        logger.info(f"Starting fine-tuning for {target_pair}")
        
        # Set up optimizer with reduced learning rate for pre-trained layers
        optimizer = self._create_optimizer(model)
        
        # Training metrics
        training_metrics = {
            'epochs': [],
            'losses': [],
            'validation_losses': [],
            'early_stopped': False,
            'best_epoch': 0
        }
        
        best_loss = float('inf')
        patience_counter = 0
        
        for epoch in range(self.config.fine_tune_epochs):
            # Update progressive unfreezing if applicable
            if self.config.adaptation_method == 'progressive':
                self.adapters['progressive'].update_epoch(epoch, model)
                
            # Simulate training step (in practice, this would be actual training)
            train_loss = self._simulate_training_step(model, training_data)
            
            # Validation step
            val_loss = train_loss * 1.1  # Simplified validation loss
            if validation_data:
                val_loss = self._simulate_validation_step(model, validation_data)
                
            training_metrics['epochs'].append(epoch)
            training_metrics['losses'].append(train_loss)
            training_metrics['validation_losses'].append(val_loss)
            
            # Early stopping check
            if val_loss < best_loss - self.config.min_improvement:
                best_loss = val_loss
                patience_counter = 0
                training_metrics['best_epoch'] = epoch
            else:
                patience_counter += 1
                
            if patience_counter >= self.config.early_stopping_patience:
                training_metrics['early_stopped'] = True
                logger.info(f"Early stopping at epoch {epoch}")
                break
                
            if epoch % 10 == 0:
                logger.info(f"Epoch {epoch}: train_loss={train_loss:.4f}, val_loss={val_loss:.4f}")
                
        logger.info(f"Fine-tuning completed for {target_pair}")
        return training_metrics
        
    def _create_optimizer(self, model: nn.Module) -> optim.Optimizer:
        """Create optimizer with different learning rates for different layers."""
        param_groups = []
        
        for name, param in model.named_parameters():
            if param.requires_grad:
                # Use reduced learning rate for pre-trained layers
                lr = 0.001 * self.config.learning_rate_multiplier
                param_groups.append({'params': param, 'lr': lr})
                
        return optim.Adam(param_groups)
        
    def _simulate_training_step(self, model: nn.Module, training_data: List[MarketData]) -> float:
        """Simulate a training step (placeholder implementation)."""
        # In practice, this would involve actual RL training
        return np.random.uniform(0.1, 1.0)
        
    def _simulate_validation_step(self, model: nn.Module, validation_data: List[MarketData]) -> float:
        """Simulate a validation step (placeholder implementation)."""
        # In practice, this would involve actual validation
        return np.random.uniform(0.1, 1.0)
        
    def save_adapted_model(self, target_pair: str, filepath: str) -> None:
        """Save adapted model and metadata."""
        if target_pair not in self.adapted_models:
            raise ValueError(f"No adapted model available for {target_pair}")
            
        model = self.adapted_models[target_pair]
        characteristics = self.currency_characteristics[target_pair]
        
        # Save model state dict
        torch.save(model.state_dict(), filepath)
        
        # Save metadata
        metadata = {
            'target_pair': target_pair,
            'characteristics': asdict(characteristics),
            'config': asdict(self.config),
            'adaptation_method': self.config.adaptation_method,
            'timestamp': datetime.now().isoformat()
        }
        
        metadata_path = filepath.replace('.pth', '_metadata.json')
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)
            
        logger.info(f"Saved adapted model for {target_pair} to {filepath}")
        
    def load_adapted_model(self, target_pair: str, filepath: str, model_class: type) -> nn.Module:
        """Load adapted model and metadata."""
        # Load metadata
        metadata_path = filepath.replace('.pth', '_metadata.json')
        with open(metadata_path, 'r') as f:
            metadata = json.load(f)
            
        # Create model instance
        model = model_class()  # This would need proper initialization
        
        # Load state dict
        model.load_state_dict(torch.load(filepath))
        
        # Store in framework
        self.adapted_models[target_pair] = model
        
        # Reconstruct characteristics
        char_dict = metadata['characteristics']
        characteristics = CurrencyCharacteristics(**char_dict)
        self.currency_characteristics[target_pair] = characteristics
        
        logger.info(f"Loaded adapted model for {target_pair} from {filepath}")
        return model
        
    def get_transfer_learning_report(self) -> Dict[str, Any]:
        """Generate comprehensive transfer learning report."""
        report = {
            'config': asdict(self.config),
            'currency_pairs': {
                'source': self.config.source_pairs,
                'target': self.config.target_pairs
            },
            'characteristics': {},
            'similarity_matrix': {},
            'adapted_models': list(self.adapted_models.keys()),
            'recommendations': []
        }
        
        # Add characteristics
        for pair, characteristics in self.currency_characteristics.items():
            report['characteristics'][pair] = asdict(characteristics)
            
        # Calculate similarity matrix
        for target_pair in self.config.target_pairs:
            if target_pair in self.currency_characteristics:
                similarities = {}
                target_char = self.currency_characteristics[target_pair]
                
                for source_pair in self.config.source_pairs:
                    if source_pair in self.currency_characteristics:
                        source_char = self.currency_characteristics[source_pair]
                        similarity = target_char.similarity_score(source_char)
                        similarities[source_pair] = similarity
                        
                report['similarity_matrix'][target_pair] = similarities
                
        # Generate recommendations
        for target_pair in self.config.target_pairs:
            if target_pair in report['similarity_matrix']:
                similarities = report['similarity_matrix'][target_pair]
                best_source = max(similarities.items(), key=lambda x: x[1])
                
                recommendation = {
                    'target_pair': target_pair,
                    'recommended_source': best_source[0],
                    'similarity_score': best_source[1],
                    'transfer_feasibility': 'high' if best_source[1] > 0.7 else 'medium' if best_source[1] > 0.5 else 'low'
                }
                report['recommendations'].append(recommendation)
                
        return report