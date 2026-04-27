"""
Per-Symbol Entry Filter Configuration
Optimizes entry thresholds based on symbol characteristics
"""

from typing import Dict, Any

class SymbolFilterConfig:
    """Holds configuration for a trading symbol"""
    
    def __init__(self, symbol: str, long_config: Dict[str, Any], short_config: Dict[str, Any]):
        self.symbol = symbol
        self.long_config = long_config
        self.short_config = short_config


# Define per-symbol configurations
SYMBOL_CONFIGS = {
    'GBP/USD': SymbolFilterConfig(
        symbol='GBP/USD',
        # Strong LONG performance, relax ADX requirement
        long_config={
            'adx_min': 24,           # RELAXED: 26→24 (more LONG signals)
            'rsi_min': 41,
            'rsi_max': 59,
            'signal_quality_min': 0.45,  # HARD-SET TO 45% (Logic-Chain Sync)
            'ml_confidence_min': 0.62,
            'meta_win_prob_min': 0.56
        },
        # Stricter for SHORT trades
        short_config={
            'adx_min': 27,           # STRICTER: for SHORT trades
            'rsi_min': 42,
            'rsi_max': 58,
            'signal_quality_min': 0.45,  # HARD-SET TO 45% (Logic-Chain Sync)
            'ml_confidence_min': 0.65,
            'meta_win_prob_min': 0.59
        }
    ),
    'AUD/USD': SymbolFilterConfig(
        symbol='AUD/USD',
        # Standard for LONG
        long_config={
            'adx_min': 25,
            'rsi_min': 41,
            'rsi_max': 59,
            'signal_quality_min': 0.45,  # HARD-SET TO 45% (Logic-Chain Sync)
            'ml_confidence_min': 0.63,
            'meta_win_prob_min': 0.56
        },
        # SHORT weakness detected, require premium quality
        short_config={
            'adx_min': 28,           # STRICTER: Many false shorts detected
            'rsi_min': 43,           # Higher threshold
            'rsi_max': 57,           # Tighter bands
            'signal_quality_min': 0.45,  # HARD-SET TO 45% (Logic-Chain Sync)
            'ml_confidence_min': 0.66,
            'meta_win_prob_min': 0.60
        }
    ),
    'EUR/USD': SymbolFilterConfig(
        symbol='EUR/USD',
        # Mixed performance, standard balanced config
        long_config={
            'adx_min': 26,
            'rsi_min': 41,
            'rsi_max': 59,
            'signal_quality_min': 0.45,  # HARD-SET TO 45% (Logic-Chain Sync)
            'ml_confidence_min': 0.63,
            'meta_win_prob_min': 0.57
        },
        short_config={
            'adx_min': 26,
            'rsi_min': 41,
            'rsi_max': 59,
            'signal_quality_min': 0.45,  # HARD-SET TO 45% (Logic-Chain Sync)
            'ml_confidence_min': 0.63,
            'meta_win_prob_min': 0.57
        }
    ),
    'USD/JPY': SymbolFilterConfig(
        symbol='USD/JPY',
        # High volatility, require strong confluence for LONG
        long_config={
            'adx_min': 26,
            'rsi_min': 40,           # Slightly more extreme
            'rsi_max': 60,
            'signal_quality_min': 0.45,  # HARD-SET TO 45% (Logic-Chain Sync)
            'ml_confidence_min': 0.64,
            'meta_win_prob_min': 0.58
        },
        # High volatility, require strong confluence for SHORT
        short_config={
            'adx_min': 26,
            'rsi_min': 40,
            'rsi_max': 60,
            'signal_quality_min': 0.45,  # HARD-SET TO 45% (Logic-Chain Sync)
            'ml_confidence_min': 0.64,
            'meta_win_prob_min': 0.58
        }
    )
}


class SymbolFilterManager:
    """Manages per-symbol entry filters"""
    
    def __init__(self):
        """Initialize with symbol configurations"""
        self.configs = SYMBOL_CONFIGS
        # Default config for unknown symbols
        self.default_config = {
            'adx_min': 26,
            'rsi_min': 41,
            'rsi_max': 59,
            'signal_quality_min': 0.45,  # HARD-SET TO 45% (Logic-Chain Sync)
            'ml_confidence_min': 0.63,
            'meta_win_prob_min': 0.57
        }

    def _resolve_symbol_key(self, symbol: str) -> str:
        """Resolve symbol key, accepting both EURUSD and EUR/USD forms."""
        if not symbol:
            return symbol
        if symbol in self.configs:
            return symbol

        compact = symbol.replace('/', '').upper()
        if len(compact) == 6:
            slash_form = f"{compact[:3]}/{compact[3:]}"
            if slash_form in self.configs:
                return slash_form
            if compact in self.configs:
                return compact
        return symbol
    
    def get_filters(self, symbol: str, direction: str) -> Dict[str, Any]:
        """
        Get entry filters for specific symbol and direction
        
        Args:
            symbol: Trading symbol (e.g., 'GBP/USD')
            direction: 'LONG' or 'SHORT'
        
        Returns:
            Filter dictionary with thresholds
        """
        symbol_key = self._resolve_symbol_key(symbol)
        if symbol_key not in self.configs:
            return self.default_config.copy()
        
        config = self.configs[symbol_key]
        direction_key = 'long_config' if direction.upper() == 'LONG' else 'short_config'
        
        return getattr(config, direction_key).copy()
    
    def log_config(self, symbol: str, direction: str) -> str:
        """Get human-readable config string for logging"""
        filters = self.get_filters(symbol, direction)
        return (
            f"ADX:{filters['adx_min']}, "
            f"RSI:{filters['rsi_min']}-{filters['rsi_max']}, "
            f"Quality:{filters['signal_quality_min']:.2f}, "
            f"ML:{filters['ml_confidence_min']:.2f}, "
            f"META:{filters['meta_win_prob_min']:.2f}"
        )


# Global instance for easy access
symbol_manager = SymbolFilterManager()
