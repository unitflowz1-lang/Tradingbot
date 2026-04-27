"""
Integration Fix: Load Quality Floor from Optimized Parameters
Patches TradeAdmissionController to read quality_floor from config/optimized_params.json
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def patch_quality_floor_from_optimized_params(admission_controller):
    """
    Patch the TradeAdmissionController to use quality_floor from optimized_params.json
    
    Args:
        admission_controller: TradeAdmissionController instance
    
    Returns:
        True if patched successfully, False otherwise
    """
    try:
        # Load optimized parameters
        optimized_params_path = Path("config/optimized_params.json")
        
        if not optimized_params_path.exists():
            logger.warning("[QUALITY_FLOOR_PATCH] optimized_params.json not found, using defaults")
            return False
        
        with open(optimized_params_path, 'r') as f:
            optimized_params = json.load(f)
        
        # Extract quality floor
        entry_filters = optimized_params.get('entry_filters', {})
        quality_floor = entry_filters.get('quality_floor', 0.65)  # Default 65%
        
        # Apply to admission controller
        admission_controller.QUALITY_FLOOR = quality_floor
        admission_controller.quality_threshold = quality_floor
        
        logger.critical(
            f"[QUALITY_FLOOR_PATCH] ✅ Applied optimized quality floor: {quality_floor:.0%} "
            f"(was 40% hardcoded)"
        )
        
        return True
        
    except Exception as e:
        logger.error(f"[QUALITY_FLOOR_PATCH] Failed to patch quality floor: {e}")
        return False


def patch_signal_weights_from_optimized_params(strategy):
    """
    Patch strategy to use signal weights from optimized_params.json
    
    Args:
        strategy: Strategy instance
    
    Returns:
        True if patched successfully, False otherwise
    """
    try:
        # Load optimized parameters
        optimized_params_path = Path("config/optimized_params.json")
        
        if not optimized_params_path.exists():
            logger.warning("[WEIGHTS_PATCH] optimized_params.json not found, using defaults")
            return False
        
        with open(optimized_params_path, 'r') as f:
            optimized_params = json.load(f)
        
        # Extract signal weights
        signal_weights = optimized_params.get('signal_weights', {})
        ml_weight = signal_weights.get('ml_weight', 0.50)
        technical_weight = signal_weights.get('technical_weight', 0.50)
        
        # Apply to strategy
        if hasattr(strategy, 'weight_ml'):
            strategy.weight_ml = ml_weight
        if hasattr(strategy, 'weight_technical'):
            strategy.weight_technical = technical_weight
        
        logger.critical(
            f"[WEIGHTS_PATCH] ✅ Applied optimized signal weights: "
            f"ML={ml_weight:.2f}, Technical={technical_weight:.2f}"
        )
        
        return True
        
    except Exception as e:
        logger.error(f"[WEIGHTS_PATCH] Failed to patch signal weights: {e}")
        return False


if __name__ == "__main__":
    # Test the patch
    print("Testing quality floor patch...")
    
    # Mock admission controller
    class MockAdmissionController:
        QUALITY_FLOOR = 0.40
        quality_threshold = 0.40
    
    controller = MockAdmissionController()
    print(f"Before: QUALITY_FLOOR = {controller.QUALITY_FLOOR:.0%}")
    
    success = patch_quality_floor_from_optimized_params(controller)
    print(f"After: QUALITY_FLOOR = {controller.QUALITY_FLOOR:.0%}")
    print(f"Patch successful: {success}")
