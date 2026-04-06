"""
Lightweight volatility cooldown cache for fail-fast symbol skips.
"""

import logging
import time
from statistics import median
from typing import Dict, List

logger = logging.getLogger(__name__)


class VolatilityGateCache:
    """Soft-lock symbols that recently failed spread or volatility gates."""

    def __init__(self, soft_cooldown_seconds: int = 180):
        self.cooldown_sec = max(1, int(soft_cooldown_seconds))
        self.cooldowns: Dict[str, float] = {}
        self.spread_history: Dict[str, List[float]] = {}
        self.consecutive_soft_locks: Dict[str, int] = {}
        self.relaxed_tolerance_until: Dict[str, float] = {}
        self.relaxed_tolerance_multiplier: Dict[str, float] = {}
        self.relaxed_duration_sec: int = 15 * 60
        self.dynamic_spread_multiplier: float = 2.0
        self.post_soft_lock_tolerance_boost: float = 1.10
        self.soft_lock_streak_threshold: int = 3

    def _normalize_key(self, symbol: str) -> str:
        return str(symbol or "").replace("/", "").upper()

    def record_spread(self, symbol: str, spread: float) -> float:
        key = self._normalize_key(symbol)
        try:
            spread_value = float(spread or 0.0)
        except (TypeError, ValueError):
            spread_value = 0.0
        if spread_value > 0.0:
            history = self.spread_history.setdefault(key, [])
            history.append(spread_value)
            if len(history) > 20:
                del history[:-20]
        return self.get_median_spread(symbol)

    def get_median_spread(self, symbol: str) -> float:
        key = self._normalize_key(symbol)
        history = self.spread_history.get(key, [])
        if not history:
            return 0.0
        return float(median(history))

    def get_current_tolerance_multiplier(self, symbol: str) -> float:
        key = self._normalize_key(symbol)
        now = time.time()
        relaxed_until = self.relaxed_tolerance_until.get(key)
        if relaxed_until is None or now >= relaxed_until:
            self.relaxed_tolerance_until.pop(key, None)
            self.relaxed_tolerance_multiplier.pop(key, None)
            return 1.0
        return float(self.relaxed_tolerance_multiplier.get(key, 1.0) or 1.0)

    def get_allowed_spread(self, symbol: str, fallback_allowed: float = 0.0) -> float:
        median_spread = self.get_median_spread(symbol)
        baseline_allowed = median_spread * float(self.dynamic_spread_multiplier) if median_spread > 0.0 else 0.0
        effective_allowed = max(float(fallback_allowed or 0.0), baseline_allowed)
        return effective_allowed * self.get_current_tolerance_multiplier(symbol)

    def is_pair_tradeable(self, symbol: str) -> bool:
        key = self._normalize_key(symbol)
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
        key = self._normalize_key(symbol)
        self.cooldowns[key] = time.time() + self.cooldown_sec
        streak = int(self.consecutive_soft_locks.get(key, 0) or 0) + 1
        self.consecutive_soft_locks[key] = streak
        if streak > self.soft_lock_streak_threshold:
            self.relaxed_tolerance_until[key] = time.time() + self.relaxed_duration_sec
            self.relaxed_tolerance_multiplier[key] = float(self.post_soft_lock_tolerance_boost)
            self.consecutive_soft_locks[key] = 0
            logger.warning(
                "[VOLATILITY_SOFT_LOCK_RELAXED] %s hit %d consecutive soft-locks. "
                "Widening spread tolerance by %.0f%% for the next %d minutes.",
                symbol,
                streak,
                (self.post_soft_lock_tolerance_boost - 1.0) * 100.0,
                int(self.relaxed_duration_sec / 60),
            )
        logger.warning(
            "[VOLATILITY_CACHE] %s spread %.5f >= %.5f. Soft-locking for %ss to save CPU.",
            symbol,
            current_spread,
            max_allowed,
            self.cooldown_sec,
        )

    def clear_soft_lock_streak(self, symbol: str) -> None:
        key = self._normalize_key(symbol)
        self.consecutive_soft_locks[key] = 0
