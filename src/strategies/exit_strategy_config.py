# Exit Strategy Parameter Optimization Module
# Provides different configurations for advanced exit strategies

class ExitStrategyConfig:
    """Exit strategy parameter sets for testing and optimization"""
    
    # BALANCED (Current configuration used in 54.6% result)
    BALANCED = {
        'trailing_stop': {
            'enabled': True,
            'atr_multiplier': 0.5,
            'min_profit_pips': 10,
        },
        'breakeven_stop': {
            'enabled': True,
            'activation_ratio': 0.7,  # Activate at 70% of TP
            'buffer_pips': 2,
        },
        'time_based_exit': {
            'enabled': True,
            'max_hold_bars': 72,  # 3 days on 1H
            'exit_reason': 'TIME_LIMIT',
        },
        'partial_profits': {
            'enabled': True,
            'levels': [
                {'profit_ratio': 0.5, 'close_percent': 0.3},  # Close 30% at 50% profit
                {'profit_ratio': 0.75, 'close_percent': 0.3},  # Close 30% at 75% profit
            ],
        },
        'reversal_exit': {
            'enabled': False,
            'reversal_threshold': 0.55,
        }
    }
    
    # AGGRESSIVE (Faster exits, more partial profits)
    AGGRESSIVE = {
        'trailing_stop': {
            'enabled': True,
            'atr_multiplier': 0.4,  # Tighter trailing (was 0.5)
            'min_profit_pips': 8,   # Lower threshold
        },
        'breakeven_stop': {
            'enabled': True,
            'activation_ratio': 0.6,  # Activate earlier at 60%
            'buffer_pips': 1,         # Tighter buffer
        },
        'time_based_exit': {
            'enabled': True,
            'max_hold_bars': 48,  # 2 days instead of 3
            'exit_reason': 'TIME_LIMIT',
        },
        'partial_profits': {
            'enabled': True,
            'levels': [
                {'profit_ratio': 0.33, 'close_percent': 0.25},  # Close 25% early
                {'profit_ratio': 0.5, 'close_percent': 0.25},   # Close 25% at 50%
                {'profit_ratio': 0.75, 'close_percent': 0.25},  # Close 25% at 75%
                {'profit_ratio': 1.0, 'close_percent': 0.25},   # Close 25% at target
            ],
        },
        'reversal_exit': {
            'enabled': True,
            'reversal_threshold': 0.60,  # Exit if 60% reversal signal
        }
    }
    
    # CONSERVATIVE (Fewer exits, let winners run)
    CONSERVATIVE = {
        'trailing_stop': {
            'enabled': True,
            'atr_multiplier': 0.6,  # Looser trailing (was 0.5)
            'min_profit_pips': 15,  # Higher threshold
        },
        'breakeven_stop': {
            'enabled': True,
            'activation_ratio': 0.8,  # Activate late at 80%
            'buffer_pips': 3,         # Wider buffer
        },
        'time_based_exit': {
            'enabled': True,
            'max_hold_bars': 96,  # 4 days instead of 3
            'exit_reason': 'TIME_LIMIT',
        },
        'partial_profits': {
            'enabled': True,
            'levels': [
                {'profit_ratio': 0.75, 'close_percent': 0.4},  # Close 40% at 75%
                {'profit_ratio': 1.0, 'close_percent': 0.3},   # Close 30% at target
            ],
        },
        'reversal_exit': {
            'enabled': False,
            'reversal_threshold': 0.50,
        }
    }
    
    # ULTRA_AGGRESSIVE (Maximum profit capture, frequent exits)
    ULTRA_AGGRESSIVE = {
        'trailing_stop': {
            'enabled': True,
            'atr_multiplier': 0.3,  # Very tight trailing
            'min_profit_pips': 5,   # Very low threshold
        },
        'breakeven_stop': {
            'enabled': True,
            'activation_ratio': 0.5,  # Activate at 50%
            'buffer_pips': 0,         # No buffer
        },
        'time_based_exit': {
            'enabled': True,
            'max_hold_bars': 36,  # 1.5 days
            'exit_reason': 'TIME_LIMIT',
        },
        'partial_profits': {
            'enabled': True,
            'levels': [
                {'profit_ratio': 0.25, 'close_percent': 0.2},
                {'profit_ratio': 0.5, 'close_percent': 0.2},
                {'profit_ratio': 0.75, 'close_percent': 0.2},
                {'profit_ratio': 1.0, 'close_percent': 0.2},
                {'profit_ratio': 1.25, 'close_percent': 0.2},
            ],
        },
        'reversal_exit': {
            'enabled': True,
            'reversal_threshold': 0.65,  # Aggressive reversal exit
        }
    }

def get_config(strategy_name: str) -> dict:
    """Get exit strategy configuration by name"""
    configs = {
        'balanced': ExitStrategyConfig.BALANCED,
        'aggressive': ExitStrategyConfig.AGGRESSIVE,
        'conservative': ExitStrategyConfig.CONSERVATIVE,
        'ultra_aggressive': ExitStrategyConfig.ULTRA_AGGRESSIVE,
    }
    return configs.get(strategy_name.lower(), ExitStrategyConfig.BALANCED)

def log_config(config_name: str) -> None:
    """Log configuration for debugging"""
    config = get_config(config_name)
    print(f"\n=== EXIT STRATEGY CONFIG: {config_name.upper()} ===")
    print(f"Trailing Stop: {config['trailing_stop']['enabled']} (ATR x{config['trailing_stop']['atr_multiplier']})")
    print(f"Breakeven Stop: {config['breakeven_stop']['enabled']} (activation {config['breakeven_stop']['activation_ratio']})")
    print(f"Time-Based Exit: {config['time_based_exit']['enabled']} ({config['time_based_exit']['max_hold_bars']}h)")
    print(f"Partial Profits: {config['partial_profits']['enabled']} ({len(config['partial_profits']['levels'])} levels)")
    print(f"Reversal Exit: {config['reversal_exit']['enabled']} (threshold {config['reversal_exit']['reversal_threshold']})")
    print("=" * 50)
