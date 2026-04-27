"""Data acquisition layer for the AI Forex Trading Bot"""

from .mt5_manager import MT5Manager, MT5SymbolContext, create_mt5_manager

__all__ = [
    "MT5Manager",
    "MT5SymbolContext",
    "create_mt5_manager",
]
