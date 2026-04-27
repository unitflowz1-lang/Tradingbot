"""
Frozen Quote Handler
Detects and manages pairs with frozen/stale price data.
Prevents repeated modification attempts on frozen quotes which could cause "Requote" errors.

ANOMALY FIX: [FROZEN_QUOTE_FALLBACK] - Prevents bot from thrashing on stale prices
"""

import logging
from typing import Dict, Optional, Set
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
import asyncio

logger = logging.getLogger(__name__)


@dataclass
class FrozenQuoteState:
    """Tracks frozen quote state for a symbol"""
    symbol: str
    first_detection: datetime
    last_detection: datetime
    detection_count: int = 1
    is_moving: bool = False  # Is M1 close changing?
    
    def get_duration_seconds(self) -> float:
        """Get how long quote has been frozen"""
        elapsed = datetime.now(timezone.utc) - self.first_detection
        return elapsed.total_seconds()
    
    def is_stale(self, max_age_seconds: int = 300) -> bool:
        """Check if frozen quote detection is too old"""
        return self.get_duration_seconds() > max_age_seconds


class FrozenQuoteHandler:
    """
    Manages frozen/stale quote detection and cooldown.
    
    Strategy:
    1. Track symbols where [FROZEN_QUOTE_FALLBACK] is logged
    2. Implement cooldown period for affected symbols
    3. Skip modification attempts during cooldown
    4. Auto-clear cooldown when quote resumes (M1 moving)
    
    Benefits:
    - Prevents "Requote" errors from repeated mod attempts on stale prices
    - Reduces API spam on frozen quotes
    - Auto-recovers when quotes resume moving
    """
    
    def __init__(
        self,
        frozen_quote_cooldown_seconds: int = 60,
        recovery_detection_period: int = 5  # Check if moving after 5 detections
    ):
        """
        Args:
            frozen_quote_cooldown_seconds: How long to skip mods on frozen quote
            recovery_detection_period: Cycles before checking if quote resumed
        """
        self.frozen_quote_cooldown_seconds = frozen_quote_cooldown_seconds
        self.recovery_detection_period = recovery_detection_period
        
        # Frozen quote tracking
        self.frozen_quotes: Dict[str, FrozenQuoteState] = {}
        self.frozen_symbols: Set[str] = set()
        
        # Statistics
        self.total_detections = 0
        self.total_recoveries = 0
        self.modifications_skipped = 0
    
    def register_frozen_quote(
        self,
        symbol: str,
        is_moving: bool = False,
        detail_message: str = ""
    ):
        """
        Register a frozen quote detection.
        
        Args:
            symbol: Symbol with frozen quote
            is_moving: Is M1 close changing (quote recovering)?
            detail_message: Log message detail for context
        """
        self.total_detections += 1
        current_time = datetime.now(timezone.utc)
        
        if symbol in self.frozen_quotes:
            state = self.frozen_quotes[symbol]
            state.last_detection = current_time
            state.detection_count += 1
            state.is_moving = is_moving
        else:
            state = FrozenQuoteState(
                symbol=symbol,
                first_detection=current_time,
                last_detection=current_time,
                is_moving=is_moving
            )
            self.frozen_quotes[symbol] = state
        
        # Add to frozen set if not moving
        if not is_moving:
            self.frozen_symbols.add(symbol)
            logger.warning(
                f"[FROZEN_QUOTE] {symbol} registered | "
                f"Duration: {state.get_duration_seconds():.1f}s | "
                f"Detections: {state.detection_count}"
            )
        else:
            # Quote is moving - likely recovering
            if symbol in self.frozen_symbols:
                self.frozen_symbols.discard(symbol)
                self.total_recoveries += 1
                logger.info(
                    f"[FROZEN_QUOTE_RECOVERY] {symbol} resuming | "
                    f"Duration was: {state.get_duration_seconds():.1f}s"
                )
    
    def is_symbol_frozen(self, symbol: str) -> bool:
        """
        Check if symbol is currently in frozen quote cooldown.
        
        Args:
            symbol: Symbol to check
            
        Returns:
            True if symbol should skip modifications
        """
        if symbol not in self.frozen_quotes:
            return False
        
        state = self.frozen_quotes[symbol]
        
        # Check if cooldown has expired
        time_since_detection = (
            datetime.now(timezone.utc) - state.last_detection
        ).total_seconds()
        
        if time_since_detection > self.frozen_quote_cooldown_seconds:
            # Cooldown expired - remove from frozen set
            self.frozen_symbols.discard(symbol)
            logger.info(
                f"[FROZEN_QUOTE_COOLDOWN_EXPIRED] {symbol} | "
                f"Cooldown duration: {time_since_detection:.1f}s"
            )
            return False
        
        # Still in cooldown
        return True
    
    def should_skip_modification(self, symbol: str) -> tuple:
        """
        Check if modification should be skipped due to frozen quote.
        
        Args:
            symbol: Symbol for proposed modification
            
        Returns:
            (should_skip: bool, reason: str, remaining_cooldown_seconds: float)
        """
        if not self.is_symbol_frozen(symbol):
            return False, "", 0.0
        
        self.modifications_skipped += 1
        state = self.frozen_quotes[symbol]
        
        time_since_detection = (
            datetime.now(timezone.utc) - state.last_detection
        ).total_seconds()
        remaining_cooldown = self.frozen_quote_cooldown_seconds - time_since_detection
        
        return True, (
            f"Frozen quote cooldown active | "
            f"Remaining: {remaining_cooldown:.1f}s"
        ), remaining_cooldown
    
    async def sleep_for_frozen_quote(
        self,
        symbol: str,
        max_sleep_seconds: float = 2.0
    ) -> bool:
        """
        Optionally sleep when frozen quote is detected.
        Non-blocking async sleep to avoid repeated attempts.
        
        Args:
            symbol: Symbol with frozen quote
            max_sleep_seconds: Maximum sleep duration
            
        Returns:
            True if sleep was performed
        """
        if not self.is_symbol_frozen(symbol):
            return False
        
        state = self.frozen_quotes[symbol]
        sleep_duration = min(
            max_sleep_seconds,
            self.frozen_quote_cooldown_seconds / state.detection_count
        )
        
        logger.debug(
            f"[FROZEN_QUOTE_SLEEP] {symbol} | "
            f"Sleeping {sleep_duration:.2f}s to avoid API spam"
        )
        
        await asyncio.sleep(sleep_duration)
        return True
    
    def get_frozen_quote_stats(self) -> Dict:
        """Get frozen quote handler statistics"""
        active_frozen = len(self.frozen_symbols)
        
        return {
            'total_detections': self.total_detections,
            'total_recoveries': self.total_recoveries,
            'modifications_skipped': self.modifications_skipped,
            'currently_frozen_symbols': list(self.frozen_symbols),
            'currently_frozen_count': active_frozen,
        }
    
    def clear_symbol(self, symbol: str):
        """Manually clear frozen state for a symbol"""
        if symbol in self.frozen_quotes:
            del self.frozen_quotes[symbol]
        self.frozen_symbols.discard(symbol)
        logger.info(f"[FROZEN_QUOTE_CLEARED] {symbol}")
    
    def clear_all(self):
        """Clear all frozen quote states"""
        count = len(self.frozen_quotes)
        self.frozen_quotes.clear()
        self.frozen_symbols.clear()
        logger.info(f"[FROZEN_QUOTE_CLEARED_ALL] Cleared {count} entries")


# ============================================================================
# Integration Pattern for main.py
# ============================================================================

if __name__ == "__main__":
    print("""
    INTEGRATION PATTERN for main.py:
    
    === 1. Initialize Handler ===
    from src.trading.frozen_quote_handler import FrozenQuoteHandler
    
    frozen_quote_handler = FrozenQuoteHandler(
        frozen_quote_cooldown_seconds=60,  # 1 minute cooldown on frozen quotes
        recovery_detection_period=5
    )
    
    === 2. Register Frozen Quotes ===
    # When you detect [FROZEN_QUOTE_FALLBACK] in logs, call:
    frozen_quote_handler.register_frozen_quote(
        symbol='GBPUSD',
        is_moving=False,  # Not recovering yet
        detail_message='Bid/Ask frozen. M1 close static.'
    )
    
    === 3. Check Before Modification (Add to MACRO_SHIELD) ===
    # Before sending TradeModify:
    should_skip, reason, remaining_cooldown = frozen_quote_handler.should_skip_modification(
        symbol=position.symbol
    )
    
    if should_skip:
        logger.warning(
            f"[MODIFICATION_SKIPPED] {position.symbol}: {reason} "
            f"({remaining_cooldown:.1f}s remaining)"
        )
        
        # Optional: Sleep to avoid thrashing
        # await frozen_quote_handler.sleep_for_frozen_quote(position.symbol, max_sleep_seconds=2.0)
        
        continue  # Skip this modification cycle
    
    # Otherwise proceed with modification
    should_send, gate_reason, _ = modification_gate.evaluate_modification(proposal, pip_value)
    
    === 4. Auto-Register on Quote Recovery ===
    # In your price quote detection logic:
    if quote_is_moving(symbol):
        frozen_quote_handler.register_frozen_quote(
            symbol=symbol,
            is_moving=True  # Quote recovering!
        )
    
    === 5. Monitor Statistics ===
    # Periodically log stats:
    stats = frozen_quote_handler.get_frozen_quote_stats()
    logger.info(
        f"[FROZEN_QUOTE_STATS] "
        f"Detections={stats['total_detections']}, "
        f"Recoveries={stats['total_recoveries']}, "
        f"Mods skipped={stats['modifications_skipped']}, "
        f"Currently frozen={stats['currently_frozen_count']}"
    )
    """)
