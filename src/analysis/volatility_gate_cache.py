"""
Lightweight volatility cooldown cache for fail-fast symbol skips.
"""

import logging
import time
from typing import Dict

logger = logging.getLogger(__name__)


class VolatilityGateCache:
    """Soft-lock symbols that recently failed spread or volatility gates."""

    def __init__(self, soft_cooldown_seconds: int = 60):
        # FIX #4: Reduced from 180s to 60s for faster recovery
        self.cooldown_sec = max(1, int(soft_cooldown_seconds))
        self.cooldowns: Dict[str, float] = {}

    def is_pair_tradeable(self, symbol: str) -> bool:
        key = str(symbol or "").replace("/", "").upper()
        unblock_at = self.cooldowns.get(key)
        if unblock_at is None:
            return True
        now = time.time()
        if now < unblock_at:
            return False
        self.cooldowns.pop(key, None)
        logger.info("[VOLATILITY_GATE] %s cooldown expired. Resuming analysis.", symbol)
        return True

    def trigger_cooldown(self, symbol: str, current_spread: float, max_allowed: float):
        key = str(symbol or "").replace("/", "").upper()
        self.cooldowns[key] = time.time() + self.cooldown_sec
        logger.warning(
            "[VOLATILITY_CACHE] %s spread %.5f >= %.5f. Soft-locking for %ss to save CPU.",
            symbol,
            current_spread,
            max_allowed,
            self.cooldown_sec,
        )
