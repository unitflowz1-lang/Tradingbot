"""
Graceful degradation strategies for RL system components.
"""
import os
import time
import logging
from typing import Dict, Any, List, Optional, Callable, Union
from dataclasses import dataclass
from enum import Enum
import threading
import queue
from abc import ABC, abstractmethod

import torch
import numpy as np

from .error_handler import ErrorHandler, ErrorCategory, ErrorSeverity

logger = logging.getLogger(__name__)

class DegradationLevel(Enum):
    """Levels of system degradation."""
    NORMAL = "normal"
    REDUCED = "reduced"
    MINIMAL = "minimal"
    EMERGENCY = "emergency"

@dataclass
class SystemState:
    """Current system state information."""
    degradation_level: DegradationLevel
    active_components: List[str]
    disabled_components: List[str]
    performance_metrics: Dict[str, float]
    timestamp: float

class DegradationStrategy(ABC):
    """Base class for degradation strategies."""
    
    def __init__(self, name: str, trigger_conditions: Dict[str, Any]):
        self.name = name
        self.trigger_conditions = trigger_conditions
        self.is_active = False
    
    @abstractmethod
    def should_activate(self, system_state: SystemState, error_rate: float) -> bool:
        """Check if this degradation strategy should be activated."""
        pass
    
    @abstractmethod
    def activate(self, context: Dict[str, Any]) -> bool:
        """Activate the degradation strategy."""
        pass
    
    @abstractmethod
    def deactivate(self, context: Dict[str, Any]) -> bool:
        """Deactivate the degradation strategy."""
        pass
    
    @abstractmethod
    def get_degraded_behavior(self) -> Dict[str, Any]:
        """Get the degraded behavior configuration."""
        pass

class ReducedComplexityStrategy(DegradationStrategy):
    """Reduce system complexity to maintain core functionality."""
    
    def __init__(self):
        super().__init__(
            name="reduced_complexity",
            trigger_conditions={
                'error_rate_threshold': 0.1,  # 10% error rate
                'resource_usage_threshold': 0.85  # 85% resource usage
            }
        )
    
    def should_activate(self, system_state: SystemState, error_rate: float) -> bool:
        """Check if complexity reduction is needed."""
        resource_usage = system_state.performance_metrics.get('resource_usage', 0)
        
        return (error_rate > self.trigger_conditions['error_rate_threshold'] or
                resource_usage > self.trigger_conditions['resource_usage_threshold'])
    
    def activate(self, context: Dict[str, Any]) -> bool:
        """Activate reduced complexity mode."""
        try:
            logger.info("Activating reduced complexity strategy")
            
            # Reduce batch sizes
            if 'training_config' in context:
                config = context['training_config']
                config.batch_size = max(1, config.batch_size // 2)
                logger.info(f"Reduced batch size to {config.batch_size}")
            
            # Disable non-essential features
            if 'feature_flags' in context:
                flags = context['feature_flags']
                flags['advanced_metrics'] = False
                flags['detailed_logging'] = False
                flags['visualization'] = False
                logger.info("Disabled non-essential features")
            
            # Reduce model complexity
            if 'agent' in context:
                agent = context['agent']
                if hasattr(agent, 'set_complexity_level'):
                    agent.set_complexity_level('reduced')
                    logger.info("Reduced agent complexity")
            
            self.is_active = True
            return True
            
        except Exception as e:
            logger.error(f"Failed to activate reduced complexity strategy: {e}")
            return False
    
    def deactivate(self, context: Dict[str, Any]) -> bool:
        """Deactivate reduced complexity mode."""
        try:
            logger.info("Deactivating reduced complexity strategy")
            
            # Restore original settings
            if 'original_config' in context:
                original_config = context['original_config']
                if 'training_config' in context:
                    context['training_config'].batch_size = original_config.get('batch_size', 32)
            
            # Re-enable features
            if 'feature_flags' in context:
                flags = context['feature_flags']
                flags['advanced_metrics'] = True
                flags['detailed_logging'] = True
                flags['visualization'] = True
            
            # Restore model complexity
            if 'agent' in context:
                agent = context['agent']
                if hasattr(agent, 'set_complexity_level'):
                    agent.set_complexity_level('normal')
            
            self.is_active = False
            return True
            
        except Exception as e:
            logger.error(f"Failed to deactivate reduced complexity strategy: {e}")
            return False
    
    def get_degraded_behavior(self) -> Dict[str, Any]:
        """Get reduced complexity behavior configuration."""
        return {
            'batch_size_multiplier': 0.5,
            'disabled_features': ['advanced_metrics', 'detailed_logging', 'visualization'],
            'model_complexity': 'reduced',
            'update_frequency_multiplier': 0.5
        }

class FallbackModelStrategy(DegradationStrategy):
    """Fall back to simpler, more reliable models."""
    
    def __init__(self):
        super().__init__(
            name="fallback_model",
            trigger_conditions={
                'model_error_rate': 0.2,  # 20% model error rate
                'inference_latency_threshold': 1.0  # 1 second
            }
        )
    
    def should_activate(self, system_state: SystemState, error_rate: float) -> bool:
        """Check if model fallback is needed."""
        model_errors = system_state.performance_metrics.get('model_error_rate', 0)
        inference_latency = system_state.performance_metrics.get('inference_latency', 0)
        
        return (model_errors > self.trigger_conditions['model_error_rate'] or
                inference_latency > self.trigger_conditions['inference_latency_threshold'])
    
    def activate(self, context: Dict[str, Any]) -> bool:
        """Activate fallback model."""
        try:
            logger.info("Activating fallback model strategy")
            
            # Switch to simpler model
            if 'agent' in context and 'fallback_agent' in context:
                context['primary_agent'] = context['agent']
                context['agent'] = context['fallback_agent']
                logger.info("Switched to fallback agent")
            
            # Use conservative trading strategy
            if 'trading_strategy' in context:
                context['original_strategy'] = context['trading_strategy']
                context['trading_strategy'] = 'conservative'
                logger.info("Switched to conservative trading strategy")
            
            # Reduce position sizes
            if 'position_sizer' in context:
                sizer = context['position_sizer']
                if hasattr(sizer, 'set_risk_multiplier'):
                    sizer.set_risk_multiplier(0.5)
                    logger.info("Reduced position sizes")
            
            self.is_active = True
            return True
            
        except Exception as e:
            logger.error(f"Failed to activate fallback model strategy: {e}")
            return False
    
    def deactivate(self, context: Dict[str, Any]) -> bool:
        """Deactivate fallback model."""
        try:
            logger.info("Deactivating fallback model strategy")
            
            # Restore primary model
            if 'primary_agent' in context:
                context['agent'] = context['primary_agent']
                del context['primary_agent']
                logger.info("Restored primary agent")
            
            # Restore original strategy
            if 'original_strategy' in context:
                context['trading_strategy'] = context['original_strategy']
                del context['original_strategy']
                logger.info("Restored original trading strategy")
            
            # Restore position sizes
            if 'position_sizer' in context:
                sizer = context['position_sizer']
                if hasattr(sizer, 'set_risk_multiplier'):
                    sizer.set_risk_multiplier(1.0)
            
            self.is_active = False
            return True
            
        except Exception as e:
            logger.error(f"Failed to deactivate fallback model strategy: {e}")
            return False
    
    def get_degraded_behavior(self) -> Dict[str, Any]:
        """Get fallback model behavior configuration."""
        return {
            'model_type': 'simple',
            'trading_strategy': 'conservative',
            'position_size_multiplier': 0.5,
            'risk_tolerance': 'low'
        }

class EmergencyModeStrategy(DegradationStrategy):
    """Emergency mode with minimal functionality."""
    
    def __init__(self):
        super().__init__(
            name="emergency_mode",
            trigger_conditions={
                'critical_error_rate': 0.5,  # 50% critical error rate
                'system_availability': 0.3   # Less than 30% availability
            }
        )
    
    def should_activate(self, system_state: SystemState, error_rate: float) -> bool:
        """Check if emergency mode is needed."""
        critical_errors = system_state.performance_metrics.get('critical_error_rate', 0)
        availability = system_state.performance_metrics.get('system_availability', 1.0)
        
        return (critical_errors > self.trigger_conditions['critical_error_rate'] or
                availability < self.trigger_conditions['system_availability'])
    
    def activate(self, context: Dict[str, Any]) -> bool:
        """Activate emergency mode."""
        try:
            logger.critical("Activating emergency mode strategy")
            
            # Stop all training
            if 'trainer' in context:
                trainer = context['trainer']
                if hasattr(trainer, 'stop_training'):
                    trainer.stop_training()
                    logger.info("Stopped all training")
            
            # Close all positions
            if 'position_manager' in context:
                position_manager = context['position_manager']
                if hasattr(position_manager, 'close_all_positions'):
                    position_manager.close_all_positions()
                    logger.info("Closed all positions")
            
            # Switch to hold-only mode
            if 'trading_mode' in context:
                context['original_trading_mode'] = context['trading_mode']
                context['trading_mode'] = 'hold_only'
                logger.info("Switched to hold-only mode")
            
            # Disable all non-essential services
            if 'services' in context:
                services = context['services']
                context['disabled_services'] = []
                for service_name, service in services.items():
                    if service_name not in ['health_check', 'monitoring']:
                        if hasattr(service, 'stop'):
                            service.stop()
                            context['disabled_services'].append(service_name)
                logger.info(f"Disabled services: {context['disabled_services']}")
            
            self.is_active = True
            return True
            
        except Exception as e:
            logger.error(f"Failed to activate emergency mode strategy: {e}")
            return False
    
    def deactivate(self, context: Dict[str, Any]) -> bool:
        """Deactivate emergency mode."""
        try:
            logger.info("Deactivating emergency mode strategy")
            
            # Restore trading mode
            if 'original_trading_mode' in context:
                context['trading_mode'] = context['original_trading_mode']
                del context['original_trading_mode']
            
            # Re-enable services
            if 'disabled_services' in context and 'services' in context:
                services = context['services']
                for service_name in context['disabled_services']:
                    if service_name in services:
                        service = services[service_name]
                        if hasattr(service, 'start'):
                            service.start()
                del context['disabled_services']
            
            self.is_active = False
            return True
            
        except Exception as e:
            logger.error(f"Failed to deactivate emergency mode strategy: {e}")
            return False
    
    def get_degraded_behavior(self) -> Dict[str, Any]:
        """Get emergency mode behavior configuration."""
        return {
            'trading_mode': 'hold_only',
            'training_enabled': False,
            'position_changes_allowed': False,
            'essential_services_only': True
        }

class GracefulDegradationManager:
    """Manager for graceful degradation strategies."""
    
    def __init__(self, error_handler: ErrorHandler):
        self.error_handler = error_handler
        self.strategies: List[DegradationStrategy] = []
        self.current_level = DegradationLevel.NORMAL
        self.system_state = SystemState(
            degradation_level=DegradationLevel.NORMAL,
            active_components=[],
            disabled_components=[],
            performance_metrics={},
            timestamp=time.time()
        )
        
        # Monitoring
        self.monitoring_active = False
        self.monitor_thread = None
        
        # Register default strategies
        self._register_default_strategies()
    
    def _register_default_strategies(self):
        """Register default degradation strategies."""
        self.strategies.extend([
            ReducedComplexityStrategy(),
            FallbackModelStrategy(),
            EmergencyModeStrategy()
        ])
    
    def register_strategy(self, strategy: DegradationStrategy):
        """Register a custom degradation strategy."""
        self.strategies.append(strategy)
        logger.info(f"Registered degradation strategy: {strategy.name}")
    
    def start_monitoring(self, context: Dict[str, Any]):
        """Start degradation monitoring."""
        if self.monitoring_active:
            return
        
        self.monitoring_active = True
        self.monitor_thread = threading.Thread(
            target=self._monitoring_loop,
            args=(context,)
        )
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
        
        logger.info("Started graceful degradation monitoring")
    
    def stop_monitoring(self):
        """Stop degradation monitoring."""
        self.monitoring_active = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
        
        logger.info("Stopped graceful degradation monitoring")
    
    def _monitoring_loop(self, context: Dict[str, Any]):
        """Main monitoring loop."""
        while self.monitoring_active:
            try:
                # Update system state
                self._update_system_state(context)
                
                # Calculate error rate
                error_rate = self._calculate_error_rate()
                
                # Check degradation strategies
                self._check_degradation_strategies(context, error_rate)
                
                # Sleep before next check
                time.sleep(30)  # Check every 30 seconds
                
            except Exception as e:
                logger.error(f"Error in degradation monitoring loop: {e}")
                time.sleep(30)
    
    def _update_system_state(self, context: Dict[str, Any]):
        """Update current system state."""
        try:
            # Get performance metrics
            metrics = {}
            
            # Resource usage
            import psutil
            metrics['cpu_usage'] = psutil.cpu_percent()
            metrics['memory_usage'] = psutil.virtual_memory().percent
            
            # GPU usage
            if torch.cuda.is_available():
                try:
                    metrics['gpu_usage'] = torch.cuda.utilization()
                except Exception:
                    metrics['gpu_usage'] = 0
            
            # Error rates from error handler
            error_stats = self.error_handler.get_error_statistics()
            metrics['error_rate'] = 1.0 - error_stats.get('recovery_rate', 0.0)
            metrics['critical_error_rate'] = self._calculate_critical_error_rate()
            
            # System availability
            active_components = self._get_active_components(context)
            total_components = self._get_total_components(context)
            metrics['system_availability'] = (
                len(active_components) / max(1, total_components)
            )
            
            # Update system state
            self.system_state = SystemState(
                degradation_level=self.current_level,
                active_components=active_components,
                disabled_components=self._get_disabled_components(context),
                performance_metrics=metrics,
                timestamp=time.time()
            )
            
        except Exception as e:
            logger.error(f"Error updating system state: {e}")
    
    def _calculate_error_rate(self) -> float:
        """Calculate current error rate."""
        error_stats = self.error_handler.get_error_statistics()
        recent_errors = error_stats.get('recent_errors', 0)
        
        # Simple error rate calculation (errors per minute)
        return min(1.0, recent_errors / 60.0)
    
    def _calculate_critical_error_rate(self) -> float:
        """Calculate critical error rate."""
        recent_errors = [
            e for e in self.error_handler.error_history
            if (time.time() - e.timestamp < 3600 and  # Last hour
                e.severity == ErrorSeverity.CRITICAL)
        ]
        
        return min(1.0, len(recent_errors) / 60.0)
    
    def _get_active_components(self, context: Dict[str, Any]) -> List[str]:
        """Get list of active components."""
        active = []
        
        # Check common components
        components = ['agent', 'environment', 'trainer', 'data_loader']
        for component in components:
            if component in context and context[component] is not None:
                active.append(component)
        
        return active
    
    def _get_total_components(self, context: Dict[str, Any]) -> int:
        """Get total number of expected components."""
        return 4  # agent, environment, trainer, data_loader
    
    def _get_disabled_components(self, context: Dict[str, Any]) -> List[str]:
        """Get list of disabled components."""
        return context.get('disabled_services', [])
    
    def _check_degradation_strategies(self, context: Dict[str, Any], error_rate: float):
        """Check and activate/deactivate degradation strategies."""
        try:
            # Sort strategies by severity (emergency mode last)
            sorted_strategies = sorted(
                self.strategies,
                key=lambda s: s.name == 'emergency_mode'
            )
            
            for strategy in sorted_strategies:
                should_activate = strategy.should_activate(self.system_state, error_rate)
                
                if should_activate and not strategy.is_active:
                    # Activate strategy
                    success = strategy.activate(context)
                    if success:
                        self._update_degradation_level(strategy)
                        logger.info(f"Activated degradation strategy: {strategy.name}")
                
                elif not should_activate and strategy.is_active:
                    # Deactivate strategy
                    success = strategy.deactivate(context)
                    if success:
                        logger.info(f"Deactivated degradation strategy: {strategy.name}")
            
            # Update overall degradation level
            self._update_overall_degradation_level()
            
        except Exception as e:
            logger.error(f"Error checking degradation strategies: {e}")
    
    def _update_degradation_level(self, strategy: DegradationStrategy):
        """Update degradation level based on active strategy."""
        if strategy.name == 'emergency_mode':
            self.current_level = DegradationLevel.EMERGENCY
        elif strategy.name == 'fallback_model':
            self.current_level = DegradationLevel.MINIMAL
        elif strategy.name == 'reduced_complexity':
            self.current_level = DegradationLevel.REDUCED
    
    def _update_overall_degradation_level(self):
        """Update overall degradation level."""
        active_strategies = [s for s in self.strategies if s.is_active]
        
        if not active_strategies:
            self.current_level = DegradationLevel.NORMAL
        elif any(s.name == 'emergency_mode' for s in active_strategies):
            self.current_level = DegradationLevel.EMERGENCY
        elif any(s.name == 'fallback_model' for s in active_strategies):
            self.current_level = DegradationLevel.MINIMAL
        elif any(s.name == 'reduced_complexity' for s in active_strategies):
            self.current_level = DegradationLevel.REDUCED
    
    def get_current_state(self) -> SystemState:
        """Get current system state."""
        return self.system_state
    
    def force_degradation_level(self, level: DegradationLevel, context: Dict[str, Any]) -> bool:
        """Force a specific degradation level."""
        try:
            logger.info(f"Forcing degradation level: {level.value}")
            
            # Deactivate all current strategies
            for strategy in self.strategies:
                if strategy.is_active:
                    strategy.deactivate(context)
            
            # Activate appropriate strategy for level
            if level == DegradationLevel.REDUCED:
                strategy = next((s for s in self.strategies if s.name == 'reduced_complexity'), None)
            elif level == DegradationLevel.MINIMAL:
                strategy = next((s for s in self.strategies if s.name == 'fallback_model'), None)
            elif level == DegradationLevel.EMERGENCY:
                strategy = next((s for s in self.strategies if s.name == 'emergency_mode'), None)
            else:
                strategy = None
            
            if strategy:
                success = strategy.activate(context)
                if success:
                    self.current_level = level
                    return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error forcing degradation level: {e}")
            return False