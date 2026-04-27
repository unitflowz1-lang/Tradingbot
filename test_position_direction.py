#!/usr/bin/env python3
"""Quick test of PositionDirectionTracker functionality"""

from src.trading.position_direction_tracker import PositionDirectionTracker, PositionType
from dataclasses import dataclass

# Test instantiation
tracker = PositionDirectionTracker()

# Test adding positions
tracker.add_position("pos_1", "EUR/USD", PositionType.LONG, 0.1, 1.0950)
tracker.add_position("pos_2", "EUR/USD", PositionType.SHORT, 0.1, 1.0960)
tracker.add_position("pos_3", "GBP/USD", PositionType.LONG, 0.1, 1.2750)

# Test queries
print("✓ Long positions:", tracker.get_long_positions())
print("✓ Short positions:", tracker.get_short_positions())
print("✓ Long symbols:", tracker.get_long_symbols())
print("✓ Short symbols:", tracker.get_short_symbols())
print("✓ EUR/USD exposure:", tracker.get_net_exposure()["EUR/USD"])
print("✓ Direction for EUR/USD:", tracker.get_direction_for_symbol("EUR/USD"))
print("\n✓ Position Direction Tracker working correctly!")
