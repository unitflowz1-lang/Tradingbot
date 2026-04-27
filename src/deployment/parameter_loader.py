"""
Parameter Loader - Injects optimized parameters into strategies
Loads config_optimized_params.json and applies to all strategies
PHASE 3: Auto-reload optimized parameters from config/optimized_params.json
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


def load_optimized_parameters(config_file: str = "config_optimized_params.json") -> Optional[Dict[str, Any]]:
    """
    Load optimized parameters from JSON file
    First tries config/optimized_params.json (Phase 3 output)
    Then falls back to config_optimized_params.json (legacy)
    
    Returns:
        Dict with signal_weights and exit_config, or None if not found
    """
    # Phase 3 hot-reload: Check for auto-generated optimized_params.json first
    phase3_config = Path("config") / "optimized_params.json"
    if phase3_config.exists():
        try:
            with open(phase3_config) as f:
                params = json.load(f)
            logger.critical(f"[AUTO-RELOAD] ✅ Loaded optimized parameters from {phase3_config}")
            return params
        except Exception as e:
            logger.warning(f"[AUTO-RELOAD] Failed to load {phase3_config}: {e}")
    
    # Fall back to original config file
    config_path = Path(config_file)
    
    if not config_path.exists():
        logger.warning(f"⚠️  Optimized config not found: {config_file}")
        logger.info("   Using default strategy parameters")
        return None
    
    try:
        with open(config_path) as f:
            params = json.load(f)
        logger.info(f"✅ Loaded optimized parameters from {config_file}")
        return params
    except json.JSONDecodeError as e:
        logger.error(f"❌ Failed to parse {config_file}: {e}")
        return None
    except Exception as e:
        logger.error(f"❌ Failed to load {config_file}: {e}")
        return None


def apply_parameters_to_strategy(
    strategy: Any,
    params: Dict[str, Any],
    symbol: str = ""
) -> bool:
    """
    Apply optimized parameters to a strategy instance
    Handles both legacy config and Phase 3 optimized_params.json format
    
    Args:
        strategy: Strategy object to update
        params: Dict with signal_weights and exit_config (or Phase 3 format)
        symbol: Symbol name (for logging)
    
    Returns:
        True if applied successfully, False otherwise
    """
    if not params:
        return False
    
    try:
        # Phase 3 format: signal_weights with ml_weight and technical_weight
        signal_cfg = params.get('signal_weights', {})
        dynamic_params = params.get('dynamic_parameters', {})
        
        if signal_cfg:
            # New format from Phase 3
            if 'ml_weight' in signal_cfg:
                strategy.weight_ml = signal_cfg.get('ml_weight', 0.7)
                strategy.weight_technical = signal_cfg.get('technical_weight', 0.3)
                strategy.weight_mtf = signal_cfg.get('weight_mtf', 0.0)
                logger.debug(f"  [{symbol}] Applied optimized weights (Phase 3): "
                            f"ML={strategy.weight_ml:.2f}, "
                            f"Tech={strategy.weight_technical:.2f}, "
                            f"MTF={strategy.weight_mtf:.2f}")
            else:
                # Legacy format
                strategy.weight_technical = signal_cfg.get('weight_technical', 0.5)
                strategy.weight_ml = signal_cfg.get('weight_ml', 0.5)
                strategy.weight_mtf = signal_cfg.get('weight_mtf', 0.0)
                logger.debug(f"  [{symbol}] Applied signal weights (legacy): "
                            f"Tech={strategy.weight_technical:.2f}, "
                            f"ML={strategy.weight_ml:.2f}, "
                            f"MTF={strategy.weight_mtf:.2f}")
        
        # Apply dynamic parameters from Phase 3
        if dynamic_params:
            if hasattr(strategy, 'trailing_stop_activation_pips'):
                strategy.trailing_stop_activation_pips = dynamic_params.get('trailing_stop_activation_pips', 20.0)
            if hasattr(strategy, 'dynamic_lock_increment_usd'):
                strategy.dynamic_lock_increment_usd = dynamic_params.get('dynamic_lock_increment_usd', 2.0)
            logger.debug(f"  [{symbol}] Applied dynamic parameters: "
                        f"Trailing={dynamic_params.get('trailing_stop_activation_pips', 20.0):.0f}pips, "
                        f"LockInc=${dynamic_params.get('dynamic_lock_increment_usd', 2.0):.2f}")
        
        # Apply exit parameters (legacy format)
        exit_cfg = params.get('exit_config', {})
        if exit_cfg:
            strategy.tp_multiplier = exit_cfg.get('tp_multiplier', 2.0)
            strategy.trailing_activation_r = exit_cfg.get('trailing_activation_r', 1.0)
            strategy.time_exit_bars = exit_cfg.get('time_exit_bars', 20)
            
            partial_levels = exit_cfg.get('partial_profit_levels', [])
            if partial_levels:
                strategy.partial_profit_levels = partial_levels
            
            logger.debug(f"  [{symbol}] Applied exit config: "
                        f"TP={strategy.tp_multiplier}R, "
                        f"Trailing={strategy.trailing_activation_r}R, "
                        f"TimeExit={strategy.time_exit_bars}b")
        
        return True
    
    except AttributeError as e:
        logger.warning(f"  [{symbol}] Could not apply parameter: {e}")
        return False
    except Exception as e:
        logger.error(f"  [{symbol}] Error applying parameters: {e}")
        return False


def apply_parameters_to_strategies(
    strategies: Dict[str, Any],
    config_file: str = "config_optimized_params.json"
) -> int:
    """
    Load and apply optimized parameters to all strategies
    Phase 3 Enhancement: Auto-loads from config/optimized_params.json if available
    
    Args:
        strategies: Dict mapping symbol to strategy instance
        config_file: Path to config_optimized_params.json
    
    Returns:
        Number of strategies updated
    """
    params = load_optimized_parameters(config_file)
    if not params:
        return 0
    
    applied_count = 0
    logger.info("═" * 70)
    
    # Check if this is Phase 3 optimized params
    is_phase3_optimized = "optimization_method" in params
    if is_phase3_optimized:
        logger.info("[AUTO-RELOAD] PHASE 3: APPLYING WALK-FORWARD OPTIMIZED PARAMETERS".center(70))
        stability_rank = params.get('stability_rank', 0)
        logger.info(f"Stability Rank: {stability_rank} (Lower = More Stable)".center(70))
    else:
        logger.info("APPLYING OPTIMIZED PARAMETERS TO STRATEGIES".center(70))
        # Add warning if Phase 3 metadata is missing
        if not params.get('stability_metrics'):
            logger.warning("⚠️  Phase 3 optimization metadata missing. Using default config format.")
    
    logger.info("═" * 70)
    
    for symbol, strategy in strategies.items():
        if apply_parameters_to_strategy(strategy, params, symbol):
            applied_count += 1
            logger.info(f"✅ [{symbol}] Parameters applied")
        else:
            logger.warning(f"⚠️  [{symbol}] Parameters not applied")
    
    if applied_count > 0:
        logger.info("═" * 70)
        logger.info(f"✅ APPLIED OPTIMIZED PARAMETERS TO {applied_count}/{len(strategies)} STRATEGIES")
        logger.info("═" * 70 + "\n")
        
        # Show summary
        signal_cfg = params.get('signal_weights', {})
        exit_cfg = params.get('exit_config', {})
        dynamic_cfg = params.get('dynamic_parameters', {})
        
        logger.info("[PARAMETER SUMMARY]")
        if is_phase3_optimized:
            logger.info("  Phase 3 Optimized Configuration:")
            logger.info(f"    • ML Weight: {signal_cfg.get('ml_weight', 0.7):.2f}")
            logger.info(f"    • Technical Weight: {signal_cfg.get('technical_weight', 0.3):.2f}")
            logger.info(f"    • Trailing Stop Activation: {dynamic_cfg.get('trailing_stop_activation_pips', 20.0):.0f} pips")
            logger.info(f"    • Dynamic Lock Increment: ${dynamic_cfg.get('dynamic_lock_increment_usd', 2.0):.2f}")
            
            stability = params.get('stability_metrics', {})
            avg_win_rate = stability.get('avg_test_win_rate', 0.50) if isinstance(stability, dict) else 0.50
            if avg_win_rate == 0.50 and (not stability or stability.get('avg_test_win_rate') is None):
                logger.warning(
                    "⚠️  avg_test_win_rate missing in stability_metrics. Using default value (0.50). "
                    "To fix: Add 'avg_test_win_rate' to config/optimized_params.json under 'stability_metrics'."
                )
            logger.info(f"    • Avg Test Win Rate: {avg_win_rate:.1%}")
            logger.info(f"    • Win Rate Variance: {stability.get('win_rate_variance', 0.0):.6f}")
        else:
            logger.info("  Signal Weights:")
            logger.info(f"    • Technical: {signal_cfg.get('weight_technical', 0.5):.2f}")
            logger.info(f"    • ML: {signal_cfg.get('weight_ml', 0.5):.2f}")
            logger.info(f"    • Multi-Timeframe: {signal_cfg.get('weight_mtf', 0.0):.2f}")
            logger.info(f"  Exit Configuration:")
            logger.info(f"    • TP Multiplier: {exit_cfg.get('tp_multiplier', 2.0):.1f}R")
            logger.info(f"    • Trailing Activation: {exit_cfg.get('trailing_activation_r', 1.0):.1f}R")
            logger.info(f"    • Time Exit: {exit_cfg.get('time_exit_bars', 20)} bars")
            logger.info(f"    • Partial Profit Levels: {exit_cfg.get('partial_profit_levels', [])}")
        
        logger.info("")
    
    return applied_count
