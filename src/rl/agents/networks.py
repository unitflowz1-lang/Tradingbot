"""
Neural Network Architectures for RL Agents

This module contains configurable neural network classes for Q-value approximation
and policy networks with support for various architectures and optimizations.
"""

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum


class ActivationFunction(Enum):
    """Available activation functions."""
    RELU = "relu"
    LEAKY_RELU = "leaky_relu"
    TANH = "tanh"
    SIGMOID = "sigmoid"
    ELU = "elu"
    SWISH = "swish"
    GELU = "gelu"


class OptimizerType(Enum):
    """Available optimizer types."""
    ADAM = "adam"
    ADAMW = "adamw"
    SGD = "sgd"
    RMSPROP = "rmsprop"


@dataclass
class NetworkConfig:
    """Configuration for neural networks."""
    hidden_layers: List[int]
    activation: ActivationFunction = ActivationFunction.RELU
    dropout_rate: float = 0.1
    batch_norm: bool = True
    layer_norm: bool = False
    weight_init: str = "xavier_uniform"
    bias_init: str = "zeros"
    
    # Optimizer configuration
    optimizer: OptimizerType = OptimizerType.ADAM
    learning_rate: float = 0.001
    weight_decay: float = 1e-4
    momentum: float = 0.9  # For SGD
    beta1: float = 0.9     # For Adam
    beta2: float = 0.999   # For Adam
    eps: float = 1e-8      # For Adam
    
    # Training configuration
    gradient_clip_norm: float = 1.0
    use_gradient_clipping: bool = True
    
    # Advanced features
    use_residual_connections: bool = False
    use_attention: bool = False
    attention_heads: int = 4


class NeuralNetwork(nn.Module):
    """
    Configurable neural network for RL agents.
    
    Supports various architectures including feedforward, residual connections,
    and attention mechanisms for Q-value approximation and policy networks.
    """
    
    def __init__(self, 
                 input_dim: int, 
                 output_dim: int, 
                 config: NetworkConfig):
        """
        Initialize neural network.
        
        Args:
            input_dim: Input dimension
            output_dim: Output dimension
            config: Network configuration
        """
        super(NeuralNetwork, self).__init__()
        
        self.input_dim = input_dim
        self.output_dim = output_dim
        self.config = config
        
        # Build network layers
        self.layers = self._build_layers()
        
        # Initialize weights
        self._initialize_weights()
        
        # Setup optimizer
        self.optimizer = self._create_optimizer()
        
        # Training state
        self.training_step = 0
        
    def _build_layers(self) -> nn.ModuleList:
        """Build network layers based on configuration."""
        layers = nn.ModuleList()
        
        # Input layer
        prev_dim = self.input_dim
        
        # Hidden layers
        for i, hidden_dim in enumerate(self.config.hidden_layers):
            # Linear layer
            linear = nn.Linear(prev_dim, hidden_dim)
            layers.append(linear)
            
            # Batch normalization
            if self.config.batch_norm:
                layers.append(nn.BatchNorm1d(hidden_dim))
            
            # Layer normalization (alternative to batch norm)
            if self.config.layer_norm and not self.config.batch_norm:
                layers.append(nn.LayerNorm(hidden_dim))
            
            # Activation function
            activation = self._get_activation_function()
            layers.append(activation)
            
            # Dropout
            if self.config.dropout_rate > 0:
                layers.append(nn.Dropout(self.config.dropout_rate))
            
            prev_dim = hidden_dim
        
        # Output layer
        output_layer = nn.Linear(prev_dim, self.output_dim)
        layers.append(output_layer)
        
        return layers
        
    def _get_activation_function(self) -> nn.Module:
        """Get activation function based on configuration."""
        if self.config.activation == ActivationFunction.RELU:
            return nn.ReLU()
        elif self.config.activation == ActivationFunction.LEAKY_RELU:
            return nn.LeakyReLU(0.01)
        elif self.config.activation == ActivationFunction.TANH:
            return nn.Tanh()
        elif self.config.activation == ActivationFunction.SIGMOID:
            return nn.Sigmoid()
        elif self.config.activation == ActivationFunction.ELU:
            return nn.ELU()
        elif self.config.activation == ActivationFunction.SWISH:
            return nn.SiLU()  # SiLU is Swish in PyTorch
        elif self.config.activation == ActivationFunction.GELU:
            return nn.GELU()
        else:
            return nn.ReLU()  # Default
            
    def _initialize_weights(self) -> None:
        """Initialize network weights."""
        for module in self.modules():
            if isinstance(module, nn.Linear):
                if self.config.weight_init == "xavier_uniform":
                    nn.init.xavier_uniform_(module.weight)
                elif self.config.weight_init == "xavier_normal":
                    nn.init.xavier_normal_(module.weight)
                elif self.config.weight_init == "kaiming_uniform":
                    nn.init.kaiming_uniform_(module.weight, nonlinearity='relu')
                elif self.config.weight_init == "kaiming_normal":
                    nn.init.kaiming_normal_(module.weight, nonlinearity='relu')
                else:
                    nn.init.xavier_uniform_(module.weight)
                
                # Initialize bias
                if module.bias is not None:
                    if self.config.bias_init == "zeros":
                        nn.init.zeros_(module.bias)
                    elif self.config.bias_init == "small_uniform":
                        nn.init.uniform_(module.bias, -0.1, 0.1)
                    else:
                        nn.init.zeros_(module.bias)
                        
    def _create_optimizer(self) -> optim.Optimizer:
        """Create optimizer based on configuration."""
        if self.config.optimizer == OptimizerType.ADAM:
            return optim.Adam(
                self.parameters(),
                lr=self.config.learning_rate,
                betas=(self.config.beta1, self.config.beta2),
                eps=self.config.eps,
                weight_decay=self.config.weight_decay
            )
        elif self.config.optimizer == OptimizerType.ADAMW:
            return optim.AdamW(
                self.parameters(),
                lr=self.config.learning_rate,
                betas=(self.config.beta1, self.config.beta2),
                eps=self.config.eps,
                weight_decay=self.config.weight_decay
            )
        elif self.config.optimizer == OptimizerType.SGD:
            return optim.SGD(
                self.parameters(),
                lr=self.config.learning_rate,
                momentum=self.config.momentum,
                weight_decay=self.config.weight_decay
            )
        elif self.config.optimizer == OptimizerType.RMSPROP:
            return optim.RMSprop(
                self.parameters(),
                lr=self.config.learning_rate,
                weight_decay=self.config.weight_decay
            )
        else:
            return optim.Adam(self.parameters(), lr=self.config.learning_rate)
            
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Forward pass through the network.
        
        Args:
            x: Input tensor
            
        Returns:
            Output tensor
        """
        # Ensure input is the right shape
        single_input = False
        if x.dim() == 1:
            x = x.unsqueeze(0)
            single_input = True
            
        # For single inputs with batch norm, temporarily set to eval mode
        original_training = self.training
        if single_input and self.config.batch_norm:
            self.eval()
            
        try:
            # Pass through layers
            for layer in self.layers:
                x = layer(x)
        finally:
            # Restore original training mode
            if single_input and self.config.batch_norm:
                self.train(original_training)
            
        return x
        
    def predict(self, x: np.ndarray) -> np.ndarray:
        """
        Make predictions on numpy arrays.
        
        Args:
            x: Input array
            
        Returns:
            Predictions as numpy array
        """
        self.eval()
        with torch.no_grad():
            if isinstance(x, np.ndarray):
                x = torch.FloatTensor(x)
            
            # Ensure batch dimension
            if x.dim() == 1:
                x = x.unsqueeze(0)
                
            output = self.forward(x)
            return output.cpu().numpy()
            
    def update(self, 
               inputs: torch.Tensor, 
               targets: torch.Tensor,
               loss_fn: Optional[nn.Module] = None) -> Dict[str, float]:
        """
        Update network parameters.
        
        Args:
            inputs: Input batch
            targets: Target batch
            loss_fn: Loss function (defaults to MSE)
            
        Returns:
            Dictionary with training metrics
        """
        self.train()
        
        if loss_fn is None:
            loss_fn = nn.MSELoss()
            
        # Forward pass
        predictions = self.forward(inputs)
        loss = loss_fn(predictions, targets)
        
        # Backward pass
        self.optimizer.zero_grad()
        loss.backward()
        
        # Gradient clipping
        if self.config.use_gradient_clipping:
            grad_norm = torch.nn.utils.clip_grad_norm_(
                self.parameters(), 
                self.config.gradient_clip_norm
            )
        else:
            grad_norm = 0.0
            
        # Optimizer step
        self.optimizer.step()
        
        # Update training step
        self.training_step += 1
        
        # Return metrics
        return {
            'loss': loss.item(),
            'grad_norm': float(grad_norm),
            'training_step': self.training_step
        }
        
    def save_checkpoint(self, filepath: str) -> None:
        """Save model checkpoint."""
        checkpoint = {
            'model_state_dict': self.state_dict(),
            'optimizer_state_dict': self.optimizer.state_dict(),
            'config': self.config,
            'training_step': self.training_step,
            'input_dim': self.input_dim,
            'output_dim': self.output_dim
        }
        torch.save(checkpoint, filepath)
        
    def load_checkpoint(self, filepath: str) -> None:
        """Load model checkpoint."""
        checkpoint = torch.load(filepath, map_location='cpu', weights_only=False)
        
        self.load_state_dict(checkpoint['model_state_dict'])
        self.optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
        self.training_step = checkpoint.get('training_step', 0)
        
    def get_model_info(self) -> Dict[str, Any]:
        """Get model information."""
        total_params = sum(p.numel() for p in self.parameters())
        trainable_params = sum(p.numel() for p in self.parameters() if p.requires_grad)
        
        return {
            'input_dim': self.input_dim,
            'output_dim': self.output_dim,
            'hidden_layers': self.config.hidden_layers,
            'total_parameters': total_params,
            'trainable_parameters': trainable_params,
            'training_step': self.training_step,
            'activation': self.config.activation.value,
            'optimizer': self.config.optimizer.value,
            'learning_rate': self.config.learning_rate
        }
        
    def freeze_layers(self, layer_indices: List[int]) -> None:
        """Freeze specific layers."""
        for i, layer in enumerate(self.layers):
            if i in layer_indices and hasattr(layer, 'weight'):
                layer.weight.requires_grad = False
                if layer.bias is not None:
                    layer.bias.requires_grad = False
                    
    def unfreeze_layers(self, layer_indices: List[int]) -> None:
        """Unfreeze specific layers."""
        for i, layer in enumerate(self.layers):
            if i in layer_indices and hasattr(layer, 'weight'):
                layer.weight.requires_grad = True
                if layer.bias is not None:
                    layer.bias.requires_grad = True


class DuelingNetwork(NeuralNetwork):
    """
    Dueling network architecture for DQN.
    
    Separates value and advantage streams for better learning stability.
    """
    
    def __init__(self, input_dim: int, output_dim: int, config: NetworkConfig):
        """Initialize dueling network."""
        # Don't call parent __init__ as we need custom architecture
        nn.Module.__init__(self)
        
        self.input_dim = input_dim
        self.output_dim = output_dim
        self.config = config
        
        # Build shared feature layers
        self.feature_layers = self._build_feature_layers()
        
        # Build value and advantage streams
        self.value_stream = self._build_value_stream()
        self.advantage_stream = self._build_advantage_stream()
        
        # Initialize weights
        self._initialize_weights()
        
        # Setup optimizer
        self.optimizer = self._create_optimizer()
        
        self.training_step = 0
        
    def _build_feature_layers(self) -> nn.ModuleList:
        """Build shared feature extraction layers."""
        layers = nn.ModuleList()
        prev_dim = self.input_dim
        
        # Use first few hidden layers as shared features
        shared_layers = self.config.hidden_layers[:-1] if len(self.config.hidden_layers) > 1 else []
        
        for hidden_dim in shared_layers:
            layers.append(nn.Linear(prev_dim, hidden_dim))
            
            if self.config.batch_norm:
                layers.append(nn.BatchNorm1d(hidden_dim))
                
            layers.append(self._get_activation_function())
            
            if self.config.dropout_rate > 0:
                layers.append(nn.Dropout(self.config.dropout_rate))
                
            prev_dim = hidden_dim
            
        return layers
        
    def _build_value_stream(self) -> nn.ModuleList:
        """Build value stream (outputs single value)."""
        layers = nn.ModuleList()
        
        # Input dimension for streams
        if self.config.hidden_layers:
            if len(self.config.hidden_layers) > 1:
                input_dim = self.config.hidden_layers[-2]
            else:
                input_dim = self.input_dim
            stream_dim = self.config.hidden_layers[-1] // 2
        else:
            input_dim = self.input_dim
            stream_dim = 64
            
        layers.append(nn.Linear(input_dim, stream_dim))
        layers.append(self._get_activation_function())
        layers.append(nn.Linear(stream_dim, 1))  # Single value output
        
        return layers
        
    def _build_advantage_stream(self) -> nn.ModuleList:
        """Build advantage stream (outputs advantage for each action)."""
        layers = nn.ModuleList()
        
        # Input dimension for streams
        if self.config.hidden_layers:
            if len(self.config.hidden_layers) > 1:
                input_dim = self.config.hidden_layers[-2]
            else:
                input_dim = self.input_dim
            stream_dim = self.config.hidden_layers[-1] // 2
        else:
            input_dim = self.input_dim
            stream_dim = 64
            
        layers.append(nn.Linear(input_dim, stream_dim))
        layers.append(self._get_activation_function())
        layers.append(nn.Linear(stream_dim, self.output_dim))  # Advantage for each action
        
        return layers
        
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Forward pass through dueling network."""
        single_input = False
        if x.dim() == 1:
            x = x.unsqueeze(0)
            single_input = True
            
        # For single inputs with batch norm, temporarily set to eval mode
        original_training = self.training
        if single_input and self.config.batch_norm:
            self.eval()
            
        try:
            # Shared feature extraction
            features = x
            for layer in self.feature_layers:
                features = layer(features)
                
            # Value stream
            value = features
            for layer in self.value_stream:
                value = layer(value)
                
            # Advantage stream
            advantage = features
            for layer in self.advantage_stream:
                advantage = layer(advantage)
                
            # Combine value and advantage
            # Q(s,a) = V(s) + A(s,a) - mean(A(s,a))
            q_values = value + advantage - advantage.mean(dim=1, keepdim=True)
        finally:
            # Restore original training mode
            if single_input and self.config.batch_norm:
                self.train(original_training)
        
        return q_values


class NoisyLinear(nn.Module):
    """
    Noisy linear layer for exploration in neural networks.
    
    Implements parameter space noise for exploration as described in
    "Noisy Networks for Exploration" (Fortunato et al., 2017).
    """
    
    def __init__(self, in_features: int, out_features: int, std_init: float = 0.5):
        """Initialize noisy linear layer."""
        super(NoisyLinear, self).__init__()
        
        self.in_features = in_features
        self.out_features = out_features
        self.std_init = std_init
        
        # Learnable parameters
        self.weight_mu = nn.Parameter(torch.empty(out_features, in_features))
        self.weight_sigma = nn.Parameter(torch.empty(out_features, in_features))
        self.bias_mu = nn.Parameter(torch.empty(out_features))
        self.bias_sigma = nn.Parameter(torch.empty(out_features))
        
        # Noise buffers
        self.register_buffer('weight_epsilon', torch.empty(out_features, in_features))
        self.register_buffer('bias_epsilon', torch.empty(out_features))
        
        self.reset_parameters()
        self.reset_noise()
        
    def reset_parameters(self):
        """Initialize parameters."""
        mu_range = 1 / np.sqrt(self.in_features)
        self.weight_mu.data.uniform_(-mu_range, mu_range)
        self.weight_sigma.data.fill_(self.std_init / np.sqrt(self.in_features))
        self.bias_mu.data.uniform_(-mu_range, mu_range)
        self.bias_sigma.data.fill_(self.std_init / np.sqrt(self.out_features))
        
    def reset_noise(self):
        """Reset noise buffers."""
        epsilon_in = self._scale_noise(self.in_features)
        epsilon_out = self._scale_noise(self.out_features)
        
        self.weight_epsilon.copy_(epsilon_out.ger(epsilon_in))
        self.bias_epsilon.copy_(epsilon_out)
        
    def _scale_noise(self, size: int) -> torch.Tensor:
        """Scale noise using factorized Gaussian noise."""
        x = torch.randn(size)
        return x.sign().mul_(x.abs().sqrt_())
        
    def forward(self, input: torch.Tensor) -> torch.Tensor:
        """Forward pass with noisy parameters."""
        if self.training:
            weight = self.weight_mu + self.weight_sigma * self.weight_epsilon
            bias = self.bias_mu + self.bias_sigma * self.bias_epsilon
        else:
            weight = self.weight_mu
            bias = self.bias_mu
            
        return F.linear(input, weight, bias)