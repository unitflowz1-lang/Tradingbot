"""
Data Augmentation for RL Training

Provides various data augmentation techniques to improve
robustness and generalization of RL agents.
"""

import numpy as np
from typing import List, Dict, Optional, Tuple, Any, Callable
from dataclasses import dataclass, field
import random
from abc import ABC, abstractmethod
import logging

from ...models import MarketData


@dataclass
class AugmentationConfig:
    """Configuration for data augmentation."""
    
    # General settings
    augmentation_probability: float = 0.3
    max_augmentations_per_sample: int = 2
    
    # Noise augmentation
    enable_noise: bool = True
    noise_std: float = 0.01
    noise_probability: float = 0.5
    
    # Time warping
    enable_time_warping: bool = True
    warp_probability: float = 0.3
    max_warp_ratio: float = 0.1
    
    # Scaling augmentation
    enable_scaling: bool = True
    scaling_probability: float = 0.4
    scaling_range: Tuple[float, float] = (0.95, 1.05)
    
    # Jittering
    enable_jittering: bool = True
    jitter_probability: float = 0.3
    jitter_strength: float = 0.005
    
    # Permutation
    enable_permutation: bool = False
    permutation_probability: float = 0.2
    max_permutation_segments: int = 3
    
    # Magnitude warping
    enable_magnitude_warping: bool = True
    magnitude_warp_probability: float = 0.3
    magnitude_warp_sigma: float = 0.2
    
    # Window slicing
    enable_window_slicing: bool = True
    window_slice_probability: float = 0.2
    min_slice_ratio: float = 0.8
    
    # Trend injection
    enable_trend_injection: bool = False
    trend_probability: float = 0.1
    trend_strength: float = 0.001
    
    # Market regime simulation
    enable_regime_simulation: bool = True
    regime_probability: float = 0.2
    volatility_multipliers: List[float] = field(default_factory=lambda: [0.5, 1.5, 2.0])


class AugmentationTechnique(ABC):
    """Abstract base class for augmentation techniques."""
    
    @abstractmethod
    def apply(self, data: np.ndarray, **kwargs) -> np.ndarray:
        """Apply augmentation to data."""
        pass
        
    @abstractmethod
    def get_name(self) -> str:
        """Get technique name."""
        pass


class NoiseAugmentation(AugmentationTechnique):
    """Add Gaussian noise to data."""
    
    def __init__(self, std: float = 0.01):
        self.std = std
        
    def apply(self, data: np.ndarray, **kwargs) -> np.ndarray:
        """Add Gaussian noise to data."""
        noise = np.random.normal(0, self.std, data.shape)
        return data + noise
        
    def get_name(self) -> str:
        return "noise"


class TimeWarpingAugmentation(AugmentationTechnique):
    """Apply time warping to sequences."""
    
    def __init__(self, max_warp_ratio: float = 0.1):
        self.max_warp_ratio = max_warp_ratio
        
    def apply(self, data: np.ndarray, **kwargs) -> np.ndarray:
        """Apply time warping to sequence data."""
        if len(data.shape) < 2:
            return data
            
        seq_len = data.shape[0]
        
        # Generate random warping curve
        warp_steps = max(4, seq_len // 10)
        warp_curve = np.random.uniform(-self.max_warp_ratio, self.max_warp_ratio, warp_steps)
        
        # Interpolate to sequence length
        warp_indices = np.linspace(0, seq_len - 1, warp_steps)
        full_warp = np.interp(np.arange(seq_len), warp_indices, warp_curve)
        
        # Apply warping
        warped_indices = np.arange(seq_len) + full_warp * seq_len
        warped_indices = np.clip(warped_indices, 0, seq_len - 1)
        
        # Interpolate data at warped indices
        warped_data = np.zeros_like(data)
        for i in range(data.shape[1]):
            warped_data[:, i] = np.interp(np.arange(seq_len), warped_indices, data[:, i])
            
        return warped_data
        
    def get_name(self) -> str:
        return "time_warping"


class ScalingAugmentation(AugmentationTechnique):
    """Apply random scaling to data."""
    
    def __init__(self, scaling_range: Tuple[float, float] = (0.95, 1.05)):
        self.scaling_range = scaling_range
        
    def apply(self, data: np.ndarray, **kwargs) -> np.ndarray:
        """Apply random scaling to data."""
        scale_factor = np.random.uniform(self.scaling_range[0], self.scaling_range[1])
        return data * scale_factor
        
    def get_name(self) -> str:
        return "scaling"


class JitteringAugmentation(AugmentationTechnique):
    """Apply jittering (small random displacements) to data."""
    
    def __init__(self, strength: float = 0.005):
        self.strength = strength
        
    def apply(self, data: np.ndarray, **kwargs) -> np.ndarray:
        """Apply jittering to data."""
        jitter = np.random.uniform(-self.strength, self.strength, data.shape)
        return data + jitter
        
    def get_name(self) -> str:
        return "jittering"


class PermutationAugmentation(AugmentationTechnique):
    """Apply permutation to sequence segments."""
    
    def __init__(self, max_segments: int = 3):
        self.max_segments = max_segments
        
    def apply(self, data: np.ndarray, **kwargs) -> np.ndarray:
        """Apply permutation to sequence segments."""
        if len(data.shape) < 2:
            return data
            
        seq_len = data.shape[0]
        if seq_len < self.max_segments:
            return data
            
        # Create random segments
        n_segments = random.randint(2, min(self.max_segments, seq_len // 2))
        segment_boundaries = sorted(random.sample(range(1, seq_len), n_segments - 1))
        segment_boundaries = [0] + segment_boundaries + [seq_len]
        
        # Create segments
        segments = []
        for i in range(len(segment_boundaries) - 1):
            start, end = segment_boundaries[i], segment_boundaries[i + 1]
            segments.append(data[start:end])
            
        # Shuffle segments
        random.shuffle(segments)
        
        # Concatenate shuffled segments
        return np.concatenate(segments, axis=0)
        
    def get_name(self) -> str:
        return "permutation"


class MagnitudeWarpingAugmentation(AugmentationTechnique):
    """Apply magnitude warping using smooth random curves."""
    
    def __init__(self, sigma: float = 0.2):
        self.sigma = sigma
        
    def apply(self, data: np.ndarray, **kwargs) -> np.ndarray:
        """Apply magnitude warping to data."""
        if len(data.shape) < 2:
            return data
            
        seq_len = data.shape[0]
        
        # Generate smooth random curve
        knot_points = max(4, seq_len // 20)
        knots = np.random.normal(1.0, self.sigma, knot_points)
        knot_indices = np.linspace(0, seq_len - 1, knot_points)
        
        # Interpolate to full sequence
        warp_curve = np.interp(np.arange(seq_len), knot_indices, knots)
        
        # Apply warping
        return data * warp_curve.reshape(-1, 1)
        
    def get_name(self) -> str:
        return "magnitude_warping"


class WindowSlicingAugmentation(AugmentationTechnique):
    """Extract random windows from sequences."""
    
    def __init__(self, min_slice_ratio: float = 0.8):
        self.min_slice_ratio = min_slice_ratio
        
    def apply(self, data: np.ndarray, **kwargs) -> np.ndarray:
        """Apply window slicing to data."""
        if len(data.shape) < 2:
            return data
            
        seq_len = data.shape[0]
        min_len = int(seq_len * self.min_slice_ratio)
        
        if min_len >= seq_len:
            return data
            
        # Random slice length
        slice_len = random.randint(min_len, seq_len)
        
        # Random start position
        max_start = seq_len - slice_len
        start_idx = random.randint(0, max_start)
        
        # Extract slice
        sliced_data = data[start_idx:start_idx + slice_len]
        
        # Pad to original length if needed
        if slice_len < seq_len:
            padding = seq_len - slice_len
            pad_before = padding // 2
            pad_after = padding - pad_before
            
            sliced_data = np.pad(sliced_data, ((pad_before, pad_after), (0, 0)), mode='edge')
            
        return sliced_data
        
    def get_name(self) -> str:
        return "window_slicing"


class TrendInjectionAugmentation(AugmentationTechnique):
    """Inject artificial trends into data."""
    
    def __init__(self, strength: float = 0.001):
        self.strength = strength
        
    def apply(self, data: np.ndarray, **kwargs) -> np.ndarray:
        """Inject trend into data."""
        if len(data.shape) < 2:
            return data
            
        seq_len = data.shape[0]
        
        # Generate random trend
        trend_direction = random.choice([-1, 1])
        trend_curve = np.linspace(0, trend_direction * self.strength * seq_len, seq_len)
        
        # Apply to price-related features (assuming first few columns are prices)
        augmented_data = data.copy()
        n_price_features = min(4, data.shape[1])  # OHLC
        
        for i in range(n_price_features):
            augmented_data[:, i] += trend_curve
            
        return augmented_data
        
    def get_name(self) -> str:
        return "trend_injection"


class RegimeSimulationAugmentation(AugmentationTechnique):
    """Simulate different market regimes by adjusting volatility."""
    
    def __init__(self, volatility_multipliers: List[float] = [0.5, 1.5, 2.0]):
        self.volatility_multipliers = volatility_multipliers
        
    def apply(self, data: np.ndarray, **kwargs) -> np.ndarray:
        """Simulate market regime by adjusting volatility."""
        if len(data.shape) < 2:
            return data
            
        # Choose random volatility multiplier
        vol_multiplier = random.choice(self.volatility_multipliers)
        
        # Calculate returns
        if data.shape[0] < 2:
            return data
            
        augmented_data = data.copy()
        
        # Apply to price features (assuming close price is in the data)
        # This is a simplified approach - in practice, you'd identify price columns
        for i in range(min(4, data.shape[1])):  # OHLC features
            prices = augmented_data[:, i]
            
            # Calculate returns
            returns = np.diff(prices) / prices[:-1]
            
            # Scale returns by volatility multiplier
            scaled_returns = returns * vol_multiplier
            
            # Reconstruct prices
            new_prices = np.zeros_like(prices)
            new_prices[0] = prices[0]
            
            for j in range(1, len(prices)):
                new_prices[j] = new_prices[j-1] * (1 + scaled_returns[j-1])
                
            augmented_data[:, i] = new_prices
            
        return augmented_data
        
    def get_name(self) -> str:
        return "regime_simulation"


class DataAugmentation:
    """
    Main data augmentation class that orchestrates various techniques.
    """
    
    def __init__(self, config: AugmentationConfig):
        """
        Initialize data augmentation.
        
        Args:
            config: Augmentation configuration
        """
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # Initialize augmentation techniques
        self.techniques = self._initialize_techniques()
        
        # Statistics
        self.augmentation_stats = {
            "total_augmentations": 0,
            "technique_usage": {technique.get_name(): 0 for technique in self.techniques}
        }
        
    def augment_batch(self, 
                     states: np.ndarray, 
                     next_states: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        Augment a batch of sequences.
        
        Args:
            states: State sequences [batch_size, seq_len, features]
            next_states: Next state sequences [batch_size, seq_len, features]
            
        Returns:
            Augmented (states, next_states) tuple
        """
        if random.random() > self.config.augmentation_probability:
            return states, next_states
            
        augmented_states = []
        augmented_next_states = []
        
        for i in range(states.shape[0]):
            # Original sequences
            augmented_states.append(states[i])
            augmented_next_states.append(next_states[i])
            
            # Apply augmentations
            n_augmentations = random.randint(1, self.config.max_augmentations_per_sample)
            
            for _ in range(n_augmentations):
                # Select random technique
                technique = random.choice(self.techniques)
                
                try:
                    # Apply to both states and next_states consistently
                    aug_state = technique.apply(states[i])
                    aug_next_state = technique.apply(next_states[i])
                    
                    augmented_states.append(aug_state)
                    augmented_next_states.append(aug_next_state)
                    
                    # Update statistics
                    self.augmentation_stats["total_augmentations"] += 1
                    self.augmentation_stats["technique_usage"][technique.get_name()] += 1
                    
                except Exception as e:
                    self.logger.warning(f"Augmentation {technique.get_name()} failed: {e}")
                    
        return np.array(augmented_states), np.array(augmented_next_states)
        
    def augment_market_data(self, data: List[MarketData]) -> List[MarketData]:
        """
        Augment raw market data.
        
        Args:
            data: List of MarketData objects
            
        Returns:
            Augmented market data list
        """
        if random.random() > self.config.augmentation_probability:
            return data
            
        # Convert to array for processing
        features = self._market_data_to_array(data)
        
        # Apply augmentation
        technique = random.choice(self.techniques)
        
        try:
            augmented_features = technique.apply(features)
            
            # Convert back to MarketData
            augmented_data = self._array_to_market_data(augmented_features, data)
            
            self.augmentation_stats["total_augmentations"] += 1
            self.augmentation_stats["technique_usage"][technique.get_name()] += 1
            
            return augmented_data
            
        except Exception as e:
            self.logger.warning(f"Market data augmentation failed: {e}")
            return data
            
    def get_augmentation_stats(self) -> Dict[str, Any]:
        """Get augmentation statistics."""
        return self.augmentation_stats.copy()
        
    def reset_stats(self) -> None:
        """Reset augmentation statistics."""
        self.augmentation_stats = {
            "total_augmentations": 0,
            "technique_usage": {technique.get_name(): 0 for technique in self.techniques}
        }
        
    def _initialize_techniques(self) -> List[AugmentationTechnique]:
        """Initialize enabled augmentation techniques."""
        techniques = []
        
        if self.config.enable_noise:
            techniques.append(NoiseAugmentation(self.config.noise_std))
            
        if self.config.enable_time_warping:
            techniques.append(TimeWarpingAugmentation(self.config.max_warp_ratio))
            
        if self.config.enable_scaling:
            techniques.append(ScalingAugmentation(self.config.scaling_range))
            
        if self.config.enable_jittering:
            techniques.append(JitteringAugmentation(self.config.jitter_strength))
            
        if self.config.enable_permutation:
            techniques.append(PermutationAugmentation(self.config.max_permutation_segments))
            
        if self.config.enable_magnitude_warping:
            techniques.append(MagnitudeWarpingAugmentation(self.config.magnitude_warp_sigma))
            
        if self.config.enable_window_slicing:
            techniques.append(WindowSlicingAugmentation(self.config.min_slice_ratio))
            
        if self.config.enable_trend_injection:
            techniques.append(TrendInjectionAugmentation(self.config.trend_strength))
            
        if self.config.enable_regime_simulation:
            techniques.append(RegimeSimulationAugmentation(self.config.volatility_multipliers))
            
        return techniques
        
    def _market_data_to_array(self, data: List[MarketData]) -> np.ndarray:
        """Convert MarketData list to numpy array."""
        features = []
        
        for market_data in data:
            feature_vector = [
                market_data.open,
                market_data.high,
                market_data.low,
                market_data.close,
                market_data.volume,
                market_data.bid,
                market_data.ask,
                market_data.spread
            ]
            features.append(feature_vector)
            
        return np.array(features)
        
    def _array_to_market_data(self, 
                             features: np.ndarray, 
                             original_data: List[MarketData]) -> List[MarketData]:
        """Convert numpy array back to MarketData list."""
        augmented_data = []
        
        for i, feature_vector in enumerate(features):
            if i >= len(original_data):
                break
                
            original = original_data[i]
            
            # Create new MarketData with augmented values
            augmented = MarketData(
                symbol=original.symbol,
                timestamp=original.timestamp,
                open=max(0.0001, float(feature_vector[0])),  # Ensure positive prices
                high=max(0.0001, float(feature_vector[1])),
                low=max(0.0001, float(feature_vector[2])),
                close=max(0.0001, float(feature_vector[3])),
                volume=max(0, int(feature_vector[4])),  # Ensure non-negative volume
                bid=max(0.0001, float(feature_vector[5])),
                ask=max(0.0001, float(feature_vector[6])),
                spread=max(0.0, float(feature_vector[7]))  # Ensure non-negative spread
            )
            
            # Validate OHLC relationships
            augmented.high = max(augmented.high, augmented.open, augmented.close)
            augmented.low = min(augmented.low, augmented.open, augmented.close)
            
            # Ensure bid < ask
            if augmented.bid >= augmented.ask:
                mid_price = (augmented.bid + augmented.ask) / 2
                augmented.bid = mid_price - augmented.spread / 2
                augmented.ask = mid_price + augmented.spread / 2
                
            augmented_data.append(augmented)
            
        return augmented_data