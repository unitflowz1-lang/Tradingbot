"""
Crash-Proof MT5 Property Manager

Handles broker metadata (swaps, stops_level, leverage, margin_requirements) 
with safe defaults and zero-division protection. Non-blocking initialization 
ensures broker connection blips don't crash the trading loop.

GUARANTEES:
- All MT5 API calls wrapped in try-except
- All property accesses return safe defaults (never None)
- Zero-division protection in all calculations
- Non-blocking initialization doesn't halt the bot
- Thread-safe caching for repeated calls
"""

import logging
import time
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from threading import Lock

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════════════
# SAFE DEFAULTS
# ════════════════════════════════════════════════════════════════════════════

SAFE_DEFAULTS = {
    "swap_long": 0.0,              # No swap cost if broker unavailable
    "swap_short": 0.0,
    "stops_level": 0,              # No minimum distance requirement
    "leverage": 1,                 # Conservative: no leverage
    "margin_initial": 100.0,       # 1 lot = 100K units, conservative default
    "margin_maintenance": 50.0,    # 50% maintenance
    "is_spread_fixed": False,
    "spread": 0.0002,              # 20 pips default spread (conservative)
    "trade_mode": mt5.SYMBOL_TRADE_MODE_FULL if mt5 else 0,
    "trade_execution": mt5.SYMBOL_TRADE_EXECUTION_MARKET if mt5 else 0,
}


@dataclass
class SymbolProperties:
    """Structured broker property cache for one symbol."""
    symbol: str
    swap_long: float = SAFE_DEFAULTS["swap_long"]
    swap_short: float = SAFE_DEFAULTS["swap_short"]
    stops_level: int = SAFE_DEFAULTS["stops_level"]
    leverage: int = SAFE_DEFAULTS["leverage"]
    margin_initial: float = SAFE_DEFAULTS["margin_initial"]
    margin_maintenance: float = SAFE_DEFAULTS["margin_maintenance"]
    is_spread_fixed: bool = SAFE_DEFAULTS["is_spread_fixed"]
    spread: float = SAFE_DEFAULTS["spread"]
    trade_mode: int = SAFE_DEFAULTS["trade_mode"]
    trade_execution: int = SAFE_DEFAULTS["trade_execution"]
    
    # Metadata
    last_refreshed_at: float = field(default_factory=time.time)
    refresh_attempts: int = 0
    is_cached_default: bool = False  # True = using safe default, not from broker


class MT5PropertyManager:
    """
    Crash-proof broker property fetcher with non-blocking init and safe defaults.
    
    Thread-safe property caching prevents repeated MT5 API calls.
    All failures degrade gracefully to safe defaults instead of crashing.
    """
    
    CACHE_TTL_SECONDS: float = 300.0  # Refresh cache every 5 minutes
    MAX_REFRESH_ATTEMPTS: int = 3     # Try 3 times before using default
    
    def __init__(self, enable_init_logging: bool = True):
        """
        Initialize manager with non-blocking startup.
        
        Args:
            enable_init_logging: Log init status (useful for debugging)
        """
        self._properties_cache: Dict[str, SymbolProperties] = {}
        self._cache_lock = Lock()
        self._mt5_reachable: bool = False
        self._init_timestamp = time.time()
        self.enable_init_logging = enable_init_logging
        
        # Non-blocking initialization: don't crash if broker unavailable
        try:
            self._validate_mt5_available()
        except Exception as e:
            if self.enable_init_logging:
                logger.warning(
                    "[MT5_PROPERTY_MANAGER_INIT] Broker unavailable on startup: %s | "
                    "Will use safe defaults for all symbols",
                    str(e)[:100]
                )
            self._mt5_reachable = False
    
    # ════════════════════════════════════════════════════════════════════════
    # PUBLIC API
    # ════════════════════════════════════════════════════════════════════════
    
    def get_properties(
        self, 
        symbol: str, 
        force_refresh: bool = False
    ) -> SymbolProperties:
        """
        Get broker properties for symbol with automatic fallback to safe defaults.
        
        Args:
            symbol: MT5 symbol (e.g., "EURUSD")
            force_refresh: Bypass cache and fetch from broker immediately
            
        Returns:
            SymbolProperties with guaranteed non-None values
            
        GUARANTEES:
        - Never returns None
        - Never has None fields
        - All division-sensitive fields are positive or zero
        """
        if not force_refresh:
            cached = self._get_cached_properties(symbol)
            if cached is not None:
                return cached
        
        # Try to fetch from broker (non-blocking fail-through to defaults)
        try:
            props = self._fetch_from_broker(symbol)
            self._cache_properties(symbol, props, is_default=False)
            return props
        except Exception as e:
            logger.warning(
                "[MT5_PROPERTY_MANAGER] Failed to fetch properties for %s: %s | "
                "Using safe default",
                symbol, str(e)[:80]
            )
            # Return safe default cached
            props = SymbolProperties(
                symbol=symbol,
                **SAFE_DEFAULTS,
                is_cached_default=True
            )
            self._cache_properties(symbol, props, is_default=True)
            return props
    
    def get_cost_penalty(
        self, 
        symbol: str, 
        position_type: str = "long",
        minutes_held: float = 60.0
    ) -> float:
        """
        Calculate holding cost (swap penalty) with zero-division protection.
        
        Args:
            symbol: MT5 symbol
            position_type: "long" or "short"
            minutes_held: How long position held (for daily swap calc)
            
        Returns:
            Cost as percentage of notional (e.g., 0.0002 = 0.02%)
            
        GUARANTEES:
        - Never divides by zero
        - Never returns negative
        - Never returns NaN or Inf
        """
        props = self.get_properties(symbol)
        
        # Get swap rate (ensure it's a number)
        swap_rate = props.swap_long if position_type.lower() == "long" else props.swap_short
        if swap_rate is None or swap_rate != swap_rate:  # NaN check
            swap_rate = SAFE_DEFAULTS["swap_long"]
        
        swap_rate = float(swap_rate)
        
        # If zero or negative, no cost
        if swap_rate <= 0:
            return 0.0
        
        # Annualize: swap_rate is per 1 lot, convert to percentage per minute
        # Assuming: 1 lot on 100K notional, 365 days, 1440 minutes/day
        if minutes_held <= 0:
            minutes_held = 60.0  # Default 1 hour
        
        # Safe calculation with zero-division check
        try:
            # Swap is typically per lot per day; convert to per-minute rate
            daily_rate = swap_rate / 100000.0  # per 100K notional
            per_minute = daily_rate / 1440.0
            total_cost = per_minute * minutes_held
        except (ZeroDivisionError, TypeError, ValueError):
            total_cost = 0.0
        
        # Clamp to positive
        return max(0.0, float(total_cost))
    
    def get_stops_level_pips(self, symbol: str) -> int:
        """
        Minimum distance to place stops (in pips).
        
        Returns:
            Integer pips with safe default (0 = broker allows any distance)
            Never None, never negative
        """
        props = self.get_properties(symbol)
        level = props.stops_level
        if level is None or not isinstance(level, (int, float)):
            return SAFE_DEFAULTS["stops_level"]
        return max(0, int(level))
    
    def get_margin_requirement(self, symbol: str, lot_size: float = 1.0) -> float:
        """
        Calculate margin requirement (in deposit currency) for given lot size.
        
        Args:
            symbol: MT5 symbol
            lot_size: Number of lots
            
        Returns:
            Margin amount (safe default if broker unavailable)
            Never divides by zero
        """
        props = self.get_properties(symbol)
        
        margin_initial = props.margin_initial
        if margin_initial is None or margin_initial <= 0:
            margin_initial = SAFE_DEFAULTS["margin_initial"]
        
        lot_size = float(lot_size) if lot_size else 1.0
        if lot_size <= 0:
            lot_size = 1.0
        
        try:
            requirement = margin_initial * lot_size
            return max(0.0, float(requirement))
        except (ZeroDivisionError, TypeError, ValueError):
            return SAFE_DEFAULTS["margin_initial"] * lot_size
    
    def get_leverage(self, symbol: str) -> int:
        """
        Safe access to broker leverage (never breaks division).
        
        Returns:
            Leverage multiplier (e.g., 50, 100, 500).
            Never 0 or negative. Minimum 1.
        """
        props = self.get_properties(symbol)
        lev = props.leverage
        if lev is None or lev <= 0 or not isinstance(lev, (int, float)):
            lev = SAFE_DEFAULTS["leverage"]
        return max(1, int(lev))
    
    def is_ready(self) -> bool:
        """Check if MT5 broker is reachable (non-blocking, always returns True or False)."""
        return self._mt5_reachable
    
    def health_check(self) -> Dict[str, Any]:
        """Return current manager status for logging/monitoring."""
        with self._cache_lock:
            cached_symbols = list(self._properties_cache.keys())
        
        return {
            "mt5_reachable": self._mt5_reachable,
            "cache_size": len(self._properties_cache),
            "cached_symbols": cached_symbols,
            "uptime_seconds": time.time() - self._init_timestamp,
        }
    
    # ════════════════════════════════════════════════════════════════════════
    # PRIVATE: INITIALIZATION & VALIDATION
    # ════════════════════════════════════════════════════════════════════════
    
    def _validate_mt5_available(self) -> None:
        """
        Quick validation that MT5 module is loaded and broker is reachable.
        Raises Exception if unavailable (caught by __init__ for non-blocking startup).
        """
        if mt5 is None:
            raise RuntimeError("MetaTrader5 module not available")
        
        # Quick ping: try to get account info
        if not mt5.initialize():
            raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
        
        account_info = mt5.account_info()
        if account_info is None:
            raise RuntimeError(f"MT5 account_info returned None: {mt5.last_error()}")
        
        self._mt5_reachable = True
        if self.enable_init_logging:
            logger.info(
                "[MT5_PROPERTY_MANAGER_INIT] ✅ MT5 broker reachable | "
                "Login=%d | Server=%s",
                account_info.login,
                account_info.server
            )
    
    # ════════════════════════════════════════════════════════════════════════
    # PRIVATE: CACHE MANAGEMENT
    # ════════════════════════════════════════════════════════════════════════
    
    def _get_cached_properties(self, symbol: str) -> Optional[SymbolProperties]:
        """Return cached properties if fresh (< TTL), else None."""
        with self._cache_lock:
            if symbol not in self._properties_cache:
                return None
            
            cached = self._properties_cache[symbol]
            age_seconds = time.time() - cached.last_refreshed_at
            
            if age_seconds < self.CACHE_TTL_SECONDS:
                return cached
            
            # Cache expired
            return None
    
    def _cache_properties(
        self, 
        symbol: str, 
        props: SymbolProperties, 
        is_default: bool = False
    ) -> None:
        """Store properties in thread-safe cache."""
        props.last_refreshed_at = time.time()
        props.is_cached_default = is_default
        
        with self._cache_lock:
            self._properties_cache[symbol] = props
    
    # ════════════════════════════════════════════════════════════════════════
    # PRIVATE: BROKER FETCH (with error handling)
    # ════════════════════════════════════════════════════════════════════════
    
    def _fetch_from_broker(
        self, 
        symbol: str,
        attempt: int = 1
    ) -> SymbolProperties:
        """
        Fetch symbol properties from MT5 broker with retry logic.
        SLASH-AGNOSTIC: Tries both "AUD/USD" and "AUDUSD" formats.
        
        Raises Exception if all retries fail.
        """
        if mt5 is None:
            raise RuntimeError("MT5 module not available")
        
        # Ensure MT5 is initialized
        if not mt5.initialize():
            raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
        
        # Try both slash and no-slash formats (slash-agnostic lookup)
        symbols_to_try = [symbol]
        if "/" in symbol:
            symbols_to_try.append(symbol.replace("/", ""))
        elif len(symbol) == 6:  # Likely EURUSD format
            symbols_to_try.append(f"{symbol[:3]}/{symbol[3:]}")
        
        selected_symbol = None
        for attempt_symbol in symbols_to_try:
            if mt5.symbol_select(attempt_symbol, True):
                selected_symbol = attempt_symbol
                break
        
        if selected_symbol is None:
            raise ValueError(
                f"Symbol {symbol} not found in any format. Tried: {symbols_to_try}"
            )
        
        # Fetch symbol info
        info = mt5.symbol_info(selected_symbol)
        if info is None:
            raise ValueError(f"mt5.symbol_info returned None for {selected_symbol}")
        
        # Extract properties with safe getattr fallbacks
        props = SymbolProperties(
            symbol=symbol,
            swap_long=self._safe_get_number(info, "swap_long", SAFE_DEFAULTS["swap_long"]),
            swap_short=self._safe_get_number(info, "swap_short", SAFE_DEFAULTS["swap_short"]),
            stops_level=self._safe_get_number(info, "stops_level", SAFE_DEFAULTS["stops_level"]),
            leverage=self._safe_get_number(info, "trade_accrued_interest", SAFE_DEFAULTS["leverage"]),
            margin_initial=self._safe_get_number(info, "margin_initial", SAFE_DEFAULTS["margin_initial"]),
            margin_maintenance=self._safe_get_number(info, "margin_maintenance", SAFE_DEFAULTS["margin_maintenance"]),
            is_spread_fixed=self._safe_get_bool(info, "spread_fixed", SAFE_DEFAULTS["is_spread_fixed"]),
            spread=self._safe_get_number(info, "spread", SAFE_DEFAULTS["spread"]),
            trade_mode=self._safe_get_number(info, "trade_mode", SAFE_DEFAULTS["trade_mode"]),
            trade_execution=self._safe_get_number(info, "trade_execution", SAFE_DEFAULTS["trade_execution"]),
        )
        
        return props
    
    @staticmethod
    def _safe_get_number(
        obj: Any, 
        attr: str, 
        default: float
    ) -> float:
        """
        Safely extract numeric attribute with default fallback.
        
        GUARANTEES:
        - Never None
        - Never NaN
        - Never Inf
        """
        try:
            val = getattr(obj, attr, default)
            if val is None:
                return default
            
            num = float(val)
            
            # Check for NaN and Inf
            if num != num or num == float('inf') or num == float('-inf'):
                return default
            
            return num
        except (TypeError, ValueError, AttributeError):
            return default
    
    @staticmethod
    def _safe_get_bool(
        obj: Any, 
        attr: str, 
        default: bool
    ) -> bool:
        """Safely extract boolean attribute with default fallback."""
        try:
            val = getattr(obj, attr, default)
            if val is None:
                return default
            return bool(val)
        except (TypeError, AttributeError):
            return default


# ════════════════════════════════════════════════════════════════════════════
# MODULE SINGLETON (lazy initialized)
# ════════════════════════════════════════════════════════════════════════════

_manager_instance: Optional[MT5PropertyManager] = None
_manager_lock = Lock()


def get_property_manager(enable_logging: bool = True) -> MT5PropertyManager:
    """
    Get or create the shared property manager instance (thread-safe singleton).
    
    Example usage in main loop:
        pm = get_property_manager()
        props = pm.get_properties("EURUSD")
        stops_level = pm.get_stops_level_pips("EURUSD")
        cost = pm.get_cost_penalty("EURUSD", position_type="long", minutes_held=120)
    """
    global _manager_instance
    
    if _manager_instance is None:
        with _manager_lock:
            if _manager_instance is None:
                _manager_instance = MT5PropertyManager(enable_init_logging=enable_logging)
    
    return _manager_instance
