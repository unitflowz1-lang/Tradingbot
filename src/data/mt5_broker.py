"""
MetaTrader 5 Broker Interface
"""

import asyncio
import logging
import json
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple
import MetaTrader5 as mt5
import os

from src.interfaces import BrokerInterface
from src.models import MarketData, Portfolio, Position, Direction, OrderStatus, Order
from src.exceptions import BrokerAPIError
from src.trading.modification_gate import ModificationGate, ModificationProposal, ModificationType
from src.data.mt5_manager import MT5Manager
from src.utils.pip_standardizer import PipStandardizer
from utils.safe_format import format_float, safe_float


def normalize_mt5_timestamp_to_utc(timestamp_value: Any, broker_offset_hours: int = 0) -> datetime:
    """
    Normalize MT5 timestamp values to UTC-aware datetime objects.
    
    IMPORTANT: MT5 pos.time is ALWAYS a Unix timestamp (UTC-based).
    The broker_offset_hours parameter is DEPRECATED and ignored.
    Do not use it to modify timestamps. This function treats all inputs
    as UTC without any offset adjustments.
    
    MT5 can return timestamps in different formats:
    - UNIX timestamp (seconds since epoch) - interpreted as UTC, used directly
    - datetime object (treated as naive UTC, no offset applied)
    
    Args:
        timestamp_value: The timestamp from MT5 (int/float for UNIX, or datetime object)
        broker_offset_hours: DEPRECATED. Ignored for backwards compatibility only.
    
    Returns:
        A UTC-aware datetime object (always UTC, no offsets applied)
    """
    if timestamp_value is None:
        return datetime.now(timezone.utc)
    
    # If it's a datetime object
    if isinstance(timestamp_value, datetime):
        # If already timezone-aware, convert to UTC if needed
        if timestamp_value.tzinfo is not None:
            if timestamp_value.tzinfo != timezone.utc:
                # Convert to UTC if it's in a different timezone
                return timestamp_value.astimezone(timezone.utc)
            return timestamp_value
        # If naive: treat as UTC datetime (NOT as broker time)
        # Rule: MT5 timestamps should never be in broker time
        # pos.time from mt5.positions_get() is always UTC-based Unix timestamp
        return timestamp_value.replace(tzinfo=timezone.utc)
    
    # If it's a numeric value (UNIX timestamp)
    try:
        timestamp_float = float(timestamp_value)
        # Convert UNIX timestamp to UTC datetime
        # UNIX timestamps are ALWAYS UTC-based by definition
        # No offset adjustment should ever be applied
        return datetime.fromtimestamp(timestamp_float, tz=timezone.utc)
    except (ValueError, TypeError, OSError):
        # If conversion fails, return current UTC time
        return datetime.now(timezone.utc)


def clamp_future_position_time(opened_at: datetime, *, max_future_seconds: int = 3600) -> datetime:
    """
    Guard against future-dated position timestamps entering runtime state.

    MT5 timestamps should already be epoch-based. If a normalized timestamp still
    lands materially in the future relative to the local UTC clock, clamp it to
    the local clock so age-based logic never sees a negative hold time.
    
    ISSUE #1 FIX: Increased max_future_seconds from 300 (5 min) to 3600 (1 hour)
    to tolerate broker timezone offsets and server clock skew during position sync.
    This prevents aggressive log spam when broker is UTC+2/+3 and local is UTC+0.
    """
    now_utc = datetime.now(timezone.utc)
    if opened_at.tzinfo is None:
        opened_at = opened_at.replace(tzinfo=timezone.utc)
    elif opened_at.tzinfo != timezone.utc:
        opened_at = opened_at.astimezone(timezone.utc)

    if opened_at > (now_utc + timedelta(seconds=max_future_seconds)):
        return now_utc
    return opened_at


def fetch_mt5_rates_with_retry(
    mt5_symbol: str,
    timeframe: int,
    requested_count: int,
    max_retries: int = 3,
    logger: Optional[Any] = None
) -> Optional[Any]:
    """
    Robust MT5 data fetching with retry logic and sleep delays.
    
    ===== ISSUE #2 FIX: Retry mechanism for insufficient historical data =====
    
    MT5 may return fewer bars than requested if the history hasn't been loaded into memory.
    This function:
    1. Requests the initially specified number of bars
    2. If insufficient bars are returned, requests a larger chunk (5x multiplier)
    3. Sleeps briefly between retries to allow MT5 to load history
    4. Retries up to max_retries times before giving up
    
    Args:
        mt5_symbol: MT5 symbol name (e.g., "EURUSD")
        timeframe: MT5 timeframe constant (e.g., mt5.TIMEFRAME_H1)
        requested_count: Desired number of bars
        max_retries: Maximum retry attempts (default 3)
        logger: Optional logger for debug output
        
    Returns:
        Tuple of bar data or None if all retries fail
    """
    if logger is None:
        logger = logging.getLogger(__name__)
    
    last_result = None
    best_count = 0
    
    for attempt in range(max_retries):
        try:
            # On first attempt, request the requested amount
            # On subsequent attempts, request 5x the original to force MT5 to load more history
            if attempt == 0:
                fetch_count = requested_count
            else:
                fetch_count = requested_count * 5
            
            logger.debug(
                f"[MT5_DATA_FETCH] Attempt {attempt + 1}/{max_retries} - "
                f"Requesting {fetch_count} bars (symbol={mt5_symbol}, timeframe={timeframe})"
            )
            
            # Attempt to fetch the bars
            rates = mt5.copy_rates_from_pos(mt5_symbol, timeframe, 0, fetch_count)
            
            if rates is not None:
                actual_count = len(rates)
                logger.info(
                    f"[MT5_DATA_FETCH] Attempt {attempt + 1} returned {actual_count} bars "
                    f"(requested {requested_count})"
                )
                
                # Track the best result so far
                if actual_count > best_count:
                    best_count = actual_count
                    last_result = rates
                
                # If we got enough bars, return immediately
                if actual_count >= requested_count:
                    logger.info(
                        f"[MT5_DATA_FETCH_SUCCESS] Got sufficient bars ({actual_count}/{requested_count})"
                    )
                    return rates
            else:
                error_code = mt5.last_error()
                logger.warning(
                    f"[MT5_DATA_FETCH_ERROR] Attempt {attempt + 1}: MT5 returned None. "
                    f"Error code: {error_code}"
                )
            
            # If not the last attempt, sleep before retry
            if attempt < max_retries - 1:
                sleep_time = 0.5 + (attempt * 0.5)  # Progressive backoff: 0.5s, 1.0s, 1.5s
                logger.debug(
                    f"[MT5_DATA_FETCH_SLEEP] Sleeping {sleep_time:.1f}s before retry {attempt + 2}/{max_retries}"
                )
                time.sleep(sleep_time)
        
        except Exception as e:
            logger.warning(
                f"[MT5_DATA_FETCH_EXCEPTION] Attempt {attempt + 1} raised exception: {e}"
            )
            if attempt < max_retries - 1:
                time.sleep(0.5 + (attempt * 0.5))
    
    # Return the best result we got, even if it's not enough
    if last_result is not None and best_count > 0:
        logger.warning(
            f"[MT5_DATA_FETCH_PARTIAL] Returning {best_count} bars after {max_retries} retries "
            f"(requested {requested_count}). Data may be incomplete for analysis."
        )
        return last_result
    
    logger.error(
        f"[MT5_DATA_FETCH_FAILED] Failed to fetch any bars after {max_retries} retries"
    )
    return None


class MT5BrokerInterface(BrokerInterface):
    """MetaTrader 5 broker interface"""
    
    # ===== TRANSACTIONAL TICKET PERSISTENCE =====
    # Path to the transactional ticket registry (saved immediately upon TRADE_RETCODE_DONE)
    TRANSACTIONAL_TICKET_REGISTRY = os.path.join(os.getcwd(), "transactional_tickets.json")
    
    def __init__(
        self,
        login: int,
        password: str,
        server: str = "MetaQuotes-Demo",
        monitored_symbols: Optional[List[str]] = None,
        symbol_suffix: Optional[str] = None,
    ):
        self.login = login
        self.password = password
        self.server = server
        self.connected = False
        self.logger = logging.getLogger(__name__)
        self.monitored_symbols = monitored_symbols or []
        self.symbol_suffix = str(
            symbol_suffix if symbol_suffix is not None else os.environ.get("MT5_SYMBOL_SUFFIX", "")
        ).strip()
        self.manager = MT5Manager(suffix=self.symbol_suffix)
        # ===== MT5 AUTHORIZATION RETRY LIMIT =====
        # Track consecutive auth failures to prevent infinite retry loops
        # Hard limit: max 3 auth attempts per connect() call before giving up
        self._auth_retry_count: int = 0
        self._max_auth_retries: int = 3
        
        # MT5 symbol mapping
        self.symbol_mapping = {
            'EUR/USD': 'EURUSD',
            'GBP/USD': 'GBPUSD',
            'USD/JPY': 'USDJPY',
            'USD/CHF': 'USDCHF',
            'AUD/USD': 'AUDUSD',
            'USD/CAD': 'USDCAD',
            'NZD/USD': 'NZDUSD'
        }
        
        # Reverse mapping for converting MT5 symbols back to standard format
        self.reverse_symbol_mapping = {v: k for k, v in self.symbol_mapping.items()}
        
        # ===== IMPROVEMENT #2: FILL-MODE CACHING =====
        # Stores the last filling mode that resulted in a TRADE_RETCODE_DONE.
        # Default to ORDER_FILLING_RETURN (0) to avoid IOC/FOK trial lag.
        self._default_fill_mode: int = self._resolve_configured_fill_mode()
        self._confirmed_fill_mode: Optional[int] = self._default_fill_mode
        # Per-symbol fill mode cache (symbol_key -> mode)
        self._fill_mode_cache: Dict[str, int] = {}
        self._fill_mode_cache_path = os.environ.get(
            "FILL_MODE_CACHE_PATH",
            os.path.join(os.getcwd(), "data", "fill_mode_cache.json"),
        )
        self._load_fill_mode_cache()
        self.uncaged_mode: bool = False
        # Tickets that failed position deserialization and are confirmed absent in MT5.
        self._ghost_ticket_ids: set[str] = set()
        # Soft PnL validation tolerances (configurable via env).
        self.pnl_tolerance_abs: float = float(os.environ.get("PNL_TOLERANCE_ABS", "0.50"))
        self.pnl_tolerance_rel: float = float(os.environ.get("PNL_TOLERANCE_REL", "0.02"))
        # Only log drift warnings above this absolute dollar threshold to avoid noise.
        self.pnl_drift_log_abs: float = float(os.environ.get("PNL_DRIFT_LOG_ABS", "2.50"))
        # Market data glitch tracking / local sync halt
        self._market_data_glitch_counts: Dict[str, int] = {}
        self._local_sync_halt_until: Dict[str, datetime] = {}
        self._local_sync_halt_seconds: int = int(os.environ.get("LOCAL_SYNC_HALT_SECONDS", "60"))
        self._local_sync_reinit_lock = asyncio.Lock()
        self._is_admin: Optional[bool] = None
        self._stable_connection_cycles: int = 0
        self.last_modify_result: Dict[str, Any] = {}
        # Frozen-quote fallback: symbol -> (limit_price, expires_at)
        self._limit_price_hint: Dict[str, tuple[float, datetime]] = {}
        self.modification_gate = ModificationGate(
            min_sl_step_pips=float(os.environ.get("MIN_SL_MODIFICATION_PIPS", "2.0")),
            min_tp_step_pips=float(os.environ.get("MIN_TP_MODIFICATION_PIPS", "2.0")),
            modification_cooldown_seconds=0,
        )
        self._spread_tolerance_pips: float = float(os.environ.get("SPREAD_TOLERANCE_PIPS", "5.0"))
        self._defensive_spread_multiplier: float = float(os.environ.get("DEFENSIVE_SPREAD_TOLERANCE_MULTIPLIER", "1.5"))
        self._rollover_sleep_active: bool = False
        self._rollover_sleep_last_logged_at: Optional[str] = None
        self.governance_mode: Optional[str] = None
        # ===== DEPRECATED BROKER TIMEZONE CONFIGURATION =====
        # Kept only for backwards compatibility with existing environments/logging.
        # MT5 position timestamps are treated as UTC source-of-truth everywhere.
        self.broker_timezone_offset_hours: int = int(
            os.environ.get("BROKER_TIMEZONE_OFFSET_HOURS", "2")
        )
        # ===== ISSUE #1 FIX: Broker timezone offset detection =====
        # Detect the broker's timezone offset dynamically by sampling recent position timestamps
        # This prevents timezone clamp spam when broker and local machine have different TZ offsets
        self._detected_broker_offset_hours: Optional[float] = None
        self._broker_offset_sample_count: int = 0
        self._broker_offset_samples: List[float] = []  # Stores offsets from recent positions
        # ===== ISSUE #1 FIX: Suppress repeated time-clamp warnings per sync cycle =====
        # Track which tickets we've warned about in THIS sync cycle to avoid log spam
        self._warned_time_clamp_tickets_this_sync: set[str] = set()

    def _record_modify_result(
        self,
        *,
        order_id: str,
        symbol: str,
        success: bool,
        retcode: Optional[int] = None,
        comment: str = "",
        reason: str = "",
        requested_sl: Optional[float] = None,
        requested_tp: Optional[float] = None,
    ) -> None:
        self.last_modify_result = {
            "order_id": str(order_id),
            "symbol": str(symbol),
            "success": bool(success),
            "retcode": retcode,
            "comment": str(comment or ""),
            "reason": str(reason or ""),
            "requested_sl": requested_sl,
            "requested_tp": requested_tp,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _normalize_mt5_symbol_name(self, symbol: str) -> str:
        mapped_symbol = self.symbol_mapping.get(symbol, symbol)
        return self.manager.format_symbol(mapped_symbol)

    def _map_symbol(self, symbol: str) -> str:
        """Compatibility alias used by the execution engine."""
        return self._normalize_mt5_symbol_name(symbol)

    def _is_probably_fx_market_open(self, now_utc: Optional[datetime] = None) -> bool:
        check_time = now_utc or datetime.now(timezone.utc)
        weekday = check_time.weekday()
        hour = check_time.hour
        if weekday == 5:
            return False
        if weekday == 6 and hour < 22:
            return False
        if weekday == 4 and hour >= 22:
            return False
        return True

    def _check_symbol_session(self, symbol: str, symbol_info: Any = None, tick: Any = None) -> tuple[bool, str]:
        mt5_symbol = self._normalize_mt5_symbol_name(symbol)
        if symbol_info is None:
            symbol_info = mt5.symbol_info(mt5_symbol)
        if symbol_info is None:
            return False, "SYMBOL_INFO_UNAVAILABLE"

        if not self._is_probably_fx_market_open():
            return False, "FOREX_MARKET_CLOSED_WINDOW"

        trade_mode = int(getattr(symbol_info, "trade_mode", 0) or 0)
        trade_mode_disabled = int(getattr(mt5, "SYMBOL_TRADE_MODE_DISABLED", 0))
        if trade_mode == trade_mode_disabled:
            return False, "SYMBOL_TRADE_DISABLED"

        visible = bool(getattr(symbol_info, "visible", True))
        if not visible:
            return False, "SYMBOL_NOT_VISIBLE"

        session_deals = getattr(symbol_info, "session_deals", None)
        if session_deals is not None:
            try:
                if int(session_deals) > 0:
                    return True, "SESSION_DEALS_ACTIVE"
            except Exception:
                pass

        if tick is None:
            try:
                tick = mt5.symbol_info_tick(mt5_symbol)
            except Exception:
                tick = None
        if tick is not None and self._is_tick_fresh(tick, max_age_seconds=180):
            bid = float(getattr(tick, "bid", 0.0) or 0.0)
            ask = float(getattr(tick, "ask", 0.0) or 0.0)
            if bid > 0.0 and ask > 0.0:
                return True, "FRESH_TICK_AVAILABLE"

        return False, "NO_FRESH_TICK_OR_SESSION_ACTIVITY"

    def _prepare_symbol_for_trading(self, symbol: str) -> tuple[str, Any]:
        """
        Normalize symbol, enforce Market Watch visibility, and validate session readiness.
        """
        mt5_symbol = self._normalize_mt5_symbol_name(symbol)
        if not mt5.symbol_select(mt5_symbol, True):
            last_error = mt5.last_error()
            raise BrokerAPIError(
                f"SYMBOL_SELECT_FAILED: {symbol} -> {mt5_symbol} | last_error={last_error}"
            )

        symbol_info = mt5.symbol_info(mt5_symbol)
        if symbol_info is None:
            raise BrokerAPIError(f"SYMBOL_INFO_UNAVAILABLE: {symbol} -> {mt5_symbol}")

        is_open, reason = self._check_symbol_session(symbol, symbol_info=symbol_info)
        if not is_open:
            raise BrokerAPIError(f"MARKET_SESSION_CLOSED: {symbol} -> {mt5_symbol} | {reason}")

        return mt5_symbol, symbol_info

    def set_governance_mode(self, governance_mode: Optional[str]) -> None:
        """Allow runtime orchestration to expose the latest governance mode to the broker."""
        self.governance_mode = str(governance_mode).upper() if governance_mode else None

    def _resolve_governance_mode(self) -> str:
        runtime_value = str(getattr(self, "governance_mode", "") or "").strip()
        if runtime_value:
            return runtime_value.upper()
        env_value = str(os.environ.get("GOVERNANCE_MODE", "") or "").strip()
        if env_value:
            return env_value.upper()
        return ""

    def _get_symbol_pip_size(self, symbol: str, symbol_info: Any = None) -> float:
        if symbol_info is None:
            mt5_symbol = self._normalize_mt5_symbol_name(symbol)
            symbol_info = mt5.symbol_info(mt5_symbol)
        if symbol_info is not None:
            return PipStandardizer.get_pip_value_from_digits(
                digits=getattr(symbol_info, "digits", None),
                point=getattr(symbol_info, "point", None),
                symbol=symbol,
            )
        return PipStandardizer.get_pip_value_for_pair(symbol)

    def _price_delta_to_pips(self, symbol: str, value: float, symbol_info: Any = None) -> float:
        if symbol_info is None:
            mt5_symbol = self._normalize_mt5_symbol_name(symbol)
            symbol_info = mt5.symbol_info(mt5_symbol)
        if symbol_info is not None:
            return PipStandardizer.broker_value_to_pips_by_digits(
                value=float(value or 0.0),
                digits=getattr(symbol_info, "digits", None),
                point=getattr(symbol_info, "point", None),
                symbol=symbol,
            )
        return PipStandardizer.broker_value_to_pips(float(value or 0.0), symbol)

    def _detect_broker_timezone_offset(self, raw_timestamp: datetime) -> None:
        """
        Detect broker timezone offset by sampling recent position timestamps.
        
        If a position timestamp appears to be in the future, calculate how many hours
        ahead it is and store this as potential broker offset. After collecting multiple
        samples, use the median offset to apply corrections to future timestamps.
        """
        try:
            now_utc = datetime.now(timezone.utc)
            if raw_timestamp.tzinfo is None:
                raw_timestamp = raw_timestamp.replace(tzinfo=timezone.utc)
            elif raw_timestamp.tzinfo != timezone.utc:
                raw_timestamp = raw_timestamp.astimezone(timezone.utc)
            
            # Calculate how far in the future this timestamp appears to be
            time_diff_seconds = (raw_timestamp - now_utc).total_seconds()
            
            # If timestamp is in future, calculate the offset in hours
            if time_diff_seconds > 60:  # More than 1 minute in the future
                offset_hours = time_diff_seconds / 3600.0
                
                # Store this sample (keep last 10 samples)
                self._broker_offset_samples.append(offset_hours)
                if len(self._broker_offset_samples) > 10:
                    self._broker_offset_samples.pop(0)
                
                # Update detected offset (use median to avoid outliers)
                if len(self._broker_offset_samples) >= 3:
                    sorted_offsets = sorted(self._broker_offset_samples)
                    self._detected_broker_offset_hours = sorted_offsets[len(sorted_offsets) // 2]
                    
                    # Log when offset is first detected and stable
                    if self._broker_offset_sample_count == 0:
                        self.logger.info(
                            f"[BROKER_TZ_DETECTED] Detected broker timezone offset: +{self._detected_broker_offset_hours:.1f} hours | "
                            f"Samples: {len(self._broker_offset_samples)} | Offset range: "
                            f"{min(self._broker_offset_samples):.1f}h to {max(self._broker_offset_samples):.1f}h"
                        )
                    self._broker_offset_sample_count += 1
        except Exception as e:
            self.logger.debug(f"Error detecting broker timezone offset: {e}")

    def _has_open_position(self, mt5_symbol: str) -> bool:
        try:
            positions = mt5.positions_get(symbol=mt5_symbol)
            return bool(positions)
        except Exception:
            return False

    def _resolve_spread_tolerance_pips(self, *, mt5_symbol: str, governance_mode: Optional[str] = None) -> float:
        tolerance = float(self._spread_tolerance_pips)
        mode = str(governance_mode or self._resolve_governance_mode() or "").upper()
        if mode == "DEFENSIVE_PRESERVATION" and self._has_open_position(mt5_symbol):
            return tolerance * float(self._defensive_spread_multiplier)
        return tolerance

    def _get_server_time_from_tick(self, tick: Any) -> datetime:
        raw_time = None
        if isinstance(tick, dict):
            raw_time = tick.get("time_msc") or tick.get("time")
        else:
            raw_time = getattr(tick, "time_msc", None) or getattr(tick, "time", None)
        if raw_time is None:
            return datetime.now()
        raw_time = float(raw_time)
        if raw_time > 10_000_000_000:
            raw_time /= 1000.0
        return datetime.fromtimestamp(raw_time)

    def _is_rollover_sleep_window(self, server_time: datetime) -> bool:
        minute_of_day = (server_time.hour * 60) + server_time.minute
        return minute_of_day >= ((23 * 60) + 55) or minute_of_day <= 5

    def _handle_rollover_sleep_state(self, symbol: str, server_time: datetime) -> bool:
        in_rollover = self._is_rollover_sleep_window(server_time)
        stamp = server_time.strftime("%Y-%m-%d %H:%M")
        if in_rollover:
            if (not self._rollover_sleep_active) or self._rollover_sleep_last_logged_at != stamp:
                self.logger.info(
                    "[ROLLOVER_SLEEP] %s | MT5 server time %s inside 23:55-00:05 rollover window. "
                    "Suppressing spread mismatch checks until liquidity normalizes.",
                    symbol,
                    server_time.strftime("%Y-%m-%d %H:%M:%S"),
                )
                self._rollover_sleep_last_logged_at = stamp
            self._rollover_sleep_active = True
            return True

        if self._rollover_sleep_active:
            self.logger.info(
                "[ROLLOVER_WAKE] %s | MT5 server time %s. Resuming normal spread validation.",
                symbol,
                server_time.strftime("%Y-%m-%d %H:%M:%S"),
            )
        self._rollover_sleep_active = False
        self._rollover_sleep_last_logged_at = None
        return False

    def _load_fill_mode_cache(self) -> None:
        try:
            if not os.path.exists(self._fill_mode_cache_path):
                return
            with open(self._fill_mode_cache_path, "r", encoding="utf-8") as f:
                payload = json.load(f) or {}
            symbol_map = payload.get("symbols", {}) or {}
            self._fill_mode_cache = {
                str(sym).replace("/", "").upper(): int(mode)
                for sym, mode in symbol_map.items()
            }
            confirmed = payload.get("confirmed_fill_mode")
            if confirmed is not None:
                self._confirmed_fill_mode = int(confirmed)
            self.logger.info(
                "[FILL_CACHE] Loaded %d persisted fill-mode entries from %s",
                len(self._fill_mode_cache),
                self._fill_mode_cache_path,
            )
        except Exception as exc:
            self.logger.warning("[FILL_CACHE] Failed to load fill-mode cache: %s", exc)

    def _resolve_configured_fill_mode(self) -> int:
        configured = os.environ.get("MT5_ORDER_FILLING_MODE")
        if configured is None:
            configured = os.environ.get("MT5_DEFAULT_FILL_MODE")
        if configured is None:
            return int(getattr(mt5, "ORDER_FILLING_RETURN", 0))
        try:
            mode = int(str(configured).strip())
        except Exception:
            self.logger.warning(
                "[FILL_MODE_CONFIG] Invalid MT5_ORDER_FILLING_MODE=%r. Falling back to RETURN (0).",
                configured,
            )
            return int(getattr(mt5, "ORDER_FILLING_RETURN", 0))
        if mode not in {0, 1, 2}:
            self.logger.warning(
                "[FILL_MODE_CONFIG] Unsupported configured fill mode %s. Expected 0, 1, or 2. Falling back to RETURN (0).",
                mode,
            )
            return int(getattr(mt5, "ORDER_FILLING_RETURN", 0))
        self.logger.info("[FILL_MODE_CONFIG] Preferred MT5 fill mode set to %s.", mode)
        return mode

    def _build_fill_mode_candidates(
        self,
        symbol: str,
        symbol_info: Any,
        *,
        include_fallbacks: bool = True,
    ) -> List[int]:
        symbol_cache_key = str(symbol).replace("/", "").upper()
        preferred_mode = self._fill_mode_cache.get(symbol_cache_key, self._confirmed_fill_mode)
        if preferred_mode is None:
            preferred_mode = self._default_fill_mode

        uncaged_active = (
            str(os.environ.get("SYSTEM_UNCAGED", "0")).lower() in {"1", "true", "yes", "on"}
            or str(os.environ.get("SYSTEM_UNCAGED_V6", "0")).lower() in {"1", "true", "yes", "on"}
            or str(os.environ.get("STRIKING_MODE", "0")).lower() in {"1", "true", "yes", "on"}
        )
        self.uncaged_mode = bool(uncaged_active)

        candidates: List[int] = [int(preferred_mode)]
        if not include_fallbacks or uncaged_active:
            return list(dict.fromkeys(candidates))

        filling_flags = int(getattr(symbol_info, "filling_mode", 0) or 0)
        ordered_modes = [
            int(getattr(mt5, "ORDER_FILLING_RETURN", 0)),
            int(getattr(mt5, "ORDER_FILLING_IOC", 1)),
            int(getattr(mt5, "ORDER_FILLING_FOK", 2)),
        ]
        for mode in ordered_modes:
            if mode == int(getattr(mt5, "ORDER_FILLING_RETURN", 0)):
                candidates.append(mode)
            elif mode == int(getattr(mt5, "ORDER_FILLING_IOC", 1)) and (filling_flags & 1):
                candidates.append(mode)
            elif mode == int(getattr(mt5, "ORDER_FILLING_FOK", 2)) and (filling_flags & 2):
                candidates.append(mode)
        candidates.extend(ordered_modes)
        return list(dict.fromkeys(int(mode) for mode in candidates if int(mode) in {0, 1, 2}))

    async def _send_order_with_fill_mode_fallback(
        self,
        *,
        symbol: str,
        mt5_symbol: str,
        symbol_info: Any,
        request: Dict[str, Any],
        order_type: int,
        target_price: float,
        validated_sl: Optional[float],
        validated_tp: Optional[float],
        market_closed_retcode: int,
        allow_fallbacks: bool = True,
        persist_ticket: bool = True,
    ) -> Tuple[Any, str]:
        fill_modes = self._build_fill_mode_candidates(
            mt5_symbol,
            symbol_info,
            include_fallbacks=allow_fallbacks,
        )
        symbol_cache_key = str(mt5_symbol).replace("/", "").upper()
        last_result = None

        if self.uncaged_mode:
            self.logger.critical(
                "[PRE_FLIGHT_LOCKED] %s | Filling mode %s forced. Fast-route active.",
                symbol,
                fill_modes[0] if fill_modes else self._default_fill_mode,
            )

        for idx, mode in enumerate(fill_modes, start=1):
            trial_request = dict(request)
            trial_request["type_filling"] = int(mode)
            if self.uncaged_mode:
                trial_request["volume"] = max(float(trial_request.get("volume", 0.0)), 0.05)
            self.logger.info(
                "[ORDER_EXECUTION] %s | SEND | fill_mode=%s | attempt=%s/%s | SL=%s TP=%s",
                symbol,
                mode,
                idx,
                len(fill_modes),
                trial_request.get("sl", "NONE"),
                trial_request.get("tp", "NONE"),
            )

            result = mt5.order_send(trial_request)
            last_result = result
            if result is None:
                self.logger.warning(
                    "[BROKER_TIMEOUT] %s | order_send returned None for fill mode %s. Trying next mode.",
                    symbol,
                    mode,
                )
                await asyncio.sleep(0.5)
                continue

            retcode = int(getattr(result, "retcode", -1))
            if retcode == market_closed_retcode:
                raise BrokerAPIError(f"MARKET_CLOSED: {result.retcode} - {result.comment}")
            if retcode == 10027:
                self.logger.error("CRITICAL: 'Algorithmic Trading' is disabled in MT5 Terminal.")
                raise BrokerAPIError(f"AutoTrading disabled: {result.retcode}")
            if retcode == 10016:
                raise BrokerAPIError(
                    f"SLTP_PREFLIGHT_REJECTED: {symbol} | retcode 10016 invalid stops on protected order"
                )
            if retcode == 10030:
                self.logger.warning(
                    "[ORDER_EXECUTION] %s | fill_mode=%s unsupported (10030). Trying fallback.",
                    symbol,
                    mode,
                )
                continue
            if retcode != mt5.TRADE_RETCODE_DONE:
                self.logger.warning(
                    "[ORDER_EXECUTION] %s | fill_mode=%s failed | retcode=%s comment=%s",
                    symbol,
                    mode,
                    retcode,
                    getattr(result, "comment", ""),
                )
                continue

            placed_ticket = str(result.order)
            if persist_ticket:
                direction_label = "BUY" if order_type == mt5.ORDER_TYPE_BUY else "SELL"
                persist_ok = self._sync_ticket_to_disk(
                    ticket_id=placed_ticket,
                    symbol=mt5_symbol,
                    direction=direction_label,
                    entry_price=target_price,
                    stop_loss=validated_sl if validated_sl else 0.0,
                    take_profit=validated_tp if validated_tp else 0.0,
                )
                if not persist_ok:
                    self.logger.critical(
                        "[ORDER_EXECUTION_WARNING] Ticket %s obtained but persistence to disk failed. Position may become orphaned.",
                        placed_ticket,
                    )

            if self._confirmed_fill_mode != mode or self._fill_mode_cache.get(symbol_cache_key) != mode:
                self.logger.info(
                    "[FILL_CACHE] %s | Caching successful fill mode %s (previous: %s).",
                    symbol,
                    mode,
                    self._confirmed_fill_mode,
                )
                self._confirmed_fill_mode = int(mode)
                self._fill_mode_cache[symbol_cache_key] = int(mode)
                self._persist_fill_mode_cache()

            self.logger.info(
                "[ORDER_EXECUTION] %s | FILLED | ticket=%s | mode=%s",
                symbol,
                placed_ticket,
                mode,
            )
            return result, placed_ticket

        err_desc = (
            f"{last_result.retcode} - {last_result.comment}"
            if last_result is not None
            else "all attempts returned None"
        )
        raise BrokerAPIError(f"Order failed after all fill modes: {err_desc}")

    def _persist_fill_mode_cache(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._fill_mode_cache_path), exist_ok=True)
            payload = {
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "default_fill_mode": int(self._default_fill_mode),
                "confirmed_fill_mode": (
                    int(self._confirmed_fill_mode)
                    if self._confirmed_fill_mode is not None
                    else None
                ),
                "symbols": {sym: int(mode) for sym, mode in self._fill_mode_cache.items()},
            }
            with open(self._fill_mode_cache_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        except Exception as exc:
            self.logger.warning("[FILL_CACHE] Failed to persist fill-mode cache: %s", exc)

    def _subscribe_monitored_symbols(self) -> None:
        if not self.monitored_symbols:
            self.logger.warning("[SYMBOL_SUBSCRIBE] No monitored symbols provided. Skipping symbol subscription.")
            return
        for symbol in self.monitored_symbols:
            mt5_symbol = self._normalize_mt5_symbol_name(symbol)
            try:
                if not mt5.symbol_select(mt5_symbol, True):
                    self.logger.critical(
                        "[SYMBOL_UNSUPPORTED] Broker does not support symbol %s (MT5: %s).",
                        symbol,
                        mt5_symbol,
                    )
                    continue
                # Force initial history download to seed tick stream.
                _rates = mt5.copy_rates_from_pos(mt5_symbol, mt5.TIMEFRAME_M1, 0, 10)
                if _rates is None or len(_rates) == 0:
                    self.logger.warning(
                        "[SYMBOL_HISTORY_WARMUP] No rates returned for %s (MT5: %s) during warm-up.",
                        symbol,
                        mt5_symbol,
                    )
                # Force a tick refresh by requesting a tiny slice of recent ticks.
                _ticks = mt5.copy_ticks_from(mt5_symbol, datetime.now(), 1, mt5.COPY_TICKS_ALL)
                if _ticks is None or len(_ticks) == 0:
                    self.logger.warning(
                        "[SYMBOL_TICK_WARMUP] No ticks returned for %s (MT5: %s) during warm-up.",
                        symbol,
                        mt5_symbol,
                    )
            except Exception as exc:
                self.logger.critical(
                    "[SYMBOL_SUBSCRIBE_FAILED] Broker does not support symbol %s (MT5: %s). Error: %s",
                    symbol,
                    mt5_symbol,
                    exc,
                )

    def _get_tick_age_seconds(self, tick) -> Optional[float]:
        if tick is None:
            return None
        try:
            tick_time = getattr(tick, "time", None)
            if tick_time is None:
                return None
            tick_dt = datetime.fromtimestamp(float(tick_time), tz=timezone.utc)
            return (datetime.now(timezone.utc) - tick_dt).total_seconds()
        except Exception:
            return None

    def ensure_symbol_active(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Ensure symbol is active in Market Watch and force-refresh ticks.
        Returns a tick dict or None if data is stale or invalid.
        """
        try:
            tick, _info, mt5_symbol = self.manager.get_tick(symbol)
            bid = float(getattr(tick, "bid", 0.0) or 0.0)
            ask = float(getattr(tick, "ask", 0.0) or 0.0)
            tick_time = int(getattr(tick, "time", 0) or 0)
            last_price = float(getattr(tick, "last", 0.0) or 0.0)
            volume = int(getattr(tick, "volume", 0) or 0)
        except Exception as exc:
            self.logger.warning(
                "[SYMBOL_SELECT_FAILED] Unable to activate %s (MT5: %s). Reason: %s",
                symbol,
                self._normalize_mt5_symbol_name(symbol),
                exc,
            )
            return None

        if bid <= 0 or ask <= 0:
            return None

        tick_dt = datetime.fromtimestamp(float(tick_time), tz=timezone.utc)
        max_tick_age = int(os.environ.get("MAX_SIGNAL_AGE_SECONDS", "60"))  # Sync with signal_combiner
        if (datetime.now(timezone.utc) - tick_dt).total_seconds() > max_tick_age:
            return None

        return {
            "bid": bid,
            "ask": ask,
            "last": last_price,
            "time": tick_time,
            "volume": volume,
            "frozen": bid == ask,
        }

    def _is_tick_fresh(self, tick, max_age_seconds: int = 60) -> bool:
        age = self._get_tick_age_seconds(tick)
        return age is not None and age <= max_age_seconds

    def _set_limit_price_hint(self, symbol: str, price: float, ttl_seconds: int = 60) -> None:
        key = symbol.replace("/", "").upper()
        expires = datetime.now(timezone.utc) + timedelta(seconds=max(1, int(ttl_seconds)))
        self._limit_price_hint[key] = (float(price), expires)

    def _consume_limit_price_hint(self, symbol: str) -> Optional[float]:
        key = symbol.replace("/", "").upper()
        hint = self._limit_price_hint.get(key)
        if not hint:
            return None
        price, expires = hint
        if datetime.now(timezone.utc) > expires:
            del self._limit_price_hint[key]
            return None
        del self._limit_price_hint[key]
        return float(price)

    def clear_frozen_quote_state(self, symbol: str) -> None:
        key = symbol.replace("/", "").upper()
        self._limit_price_hint.pop(key, None)
        self._market_data_glitch_counts.pop(key, None)
        self._local_sync_halt_until.pop(key, None)
        self.logger.warning(
            "[FROZEN_QUOTE_CLEAR] %s | Cleared frozen-quote limit hints and symbol glitch state.",
            symbol,
        )

    def _get_recent_m1_close(self, mt5_symbol: str) -> tuple[Optional[float], bool]:
        """
        Returns (close_price, is_moving) for the last M1 candle.
        is_moving indicates last close differs from previous close or open.
        """
        try:
            rates = mt5.copy_rates_from_pos(mt5_symbol, mt5.TIMEFRAME_M1, 0, 2)
            if rates is None or len(rates) == 0:
                return None, False
            last = rates[-1]
            close_price = float(last["close"])
            prev_close = float(rates[-2]["close"]) if len(rates) > 1 else close_price
            last_open = float(last["open"])
            is_moving = (close_price != prev_close) or (close_price != last_open)
            if close_price <= 0:
                return None, False
            return close_price, bool(is_moving)
        except Exception:
            return None, False

    def get_stable_connection_cycles(self) -> int:
        return int(self._stable_connection_cycles)

    def _detect_is_admin(self) -> bool:
        if self._is_admin is not None:
            return self._is_admin
        try:
            import ctypes
            self._is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            self._is_admin = False
        return self._is_admin

    def _log_ipc_admin_warning(self, context: str, error_text: Optional[str] = None) -> None:
        if self._detect_is_admin():
            return
        details = f" | Error: {error_text}" if error_text else ""
        self.logger.warning(
            "[MT5_IPC_ADMIN_WARNING] IPC error while not running as Administrator (%s)%s",
            context,
            details,
        )

    async def _attempt_initialize(
        self,
        *,
        timeout_ms: int,
        wait_timeout: int,
        **kwargs: Any,
    ) -> bool:
        """Run mt5.initialize with a hard timeout guard to avoid hangs."""
        return await asyncio.wait_for(
            asyncio.to_thread(mt5.initialize, timeout=timeout_ms, **kwargs),
            timeout=wait_timeout,
        )

    async def _authorization_backoff_login(self, context: str) -> bool:
        """Backoff retry for MT5 auth failures (-6) before any restart/kill."""
        # ===== FIX #2: HARD AUTH LIMIT =====
        # Increment auth failure counter and check against max retries
        self._auth_retry_count += 1
        if self._auth_retry_count > self._max_auth_retries:
            self.logger.error(
                "[FATAL_AUTH_FAILURE] Max auth retries (%d) exceeded. Terminating connect attempt. context=%s",
                self._max_auth_retries,
                context,
            )
            return False
        
        for delay in (5, 10, 30):
            self.logger.warning(
                "[MT5_AUTH_BACKOFF] Authorization failed (-6) during %s [Attempt %d/%d]. "
                "Retrying login in %ss...",
                context,
                self._auth_retry_count,
                self._max_auth_retries,
                delay,
            )
            await asyncio.sleep(delay)
            try:
                if await self._attempt_initialize(
                    login=self.login,
                    password=self.password,
                    server=self.server,
                    timeout_ms=5000,
                    wait_timeout=15,
                ):
                    self.logger.info("[OK] MT5 authorized after backoff during %s", context)
                    return await self._login()
            except Exception as exc:
                self.logger.warning(
                    "[MT5_AUTH_BACKOFF] Login retry failed during %s: %s",
                    context,
                    exc,
                )
        return False

    def pop_ghost_ticket_ids(self) -> set[str]:
        """Return and clear ghost tickets flagged during account/position processing."""
        ghost_ids = set(self._ghost_ticket_ids)
        self._ghost_ticket_ids.clear()
        return ghost_ids

    def _estimate_unrealized_pnl(
        self,
        symbol: str,
        mt5_symbol: str,
        direction: Direction,
        entry_price: float,
        current_price_fallback: float,
        quantity: float,
        swap_value: float = 0.0,
        commission_value: float = 0.0,
        contract_size: float = 100000.0,
    ) -> float:
        """Estimate unrealized PnL using MT5 tick-value math and fee-adjusted net."""
        current_price = current_price_fallback
        try:
            tick = mt5.symbol_info_tick(mt5_symbol)
            if tick is not None:
                side_px = tick.bid if direction == Direction.LONG else tick.ask
                if side_px and side_px > 0:
                    current_price = float(side_px)
        except Exception:
            pass

        raw = 0.0
        try:
            symbol_info = mt5.symbol_info(mt5_symbol)
            tick_size = float(getattr(symbol_info, "trade_tick_size", 0.0) or 0.0)
            tick_value = float(getattr(symbol_info, "trade_tick_value", 0.0) or 0.0)
            if tick_size > 0.0 and tick_value > 0.0:
                price_diff = (current_price - entry_price) if direction == Direction.LONG else (entry_price - current_price)
                raw = (price_diff / tick_size) * tick_value * quantity
            else:
                raise ValueError("Missing trade_tick_size/trade_tick_value")
        except Exception:
            if direction == Direction.LONG:
                raw = (current_price - entry_price) * quantity * contract_size
            else:
                raw = (entry_price - current_price) * quantity * contract_size
            if "JPY" in str(symbol).upper() and current_price:
                raw = raw / current_price

        # MT5 reconciliation includes swap + commission.
        return raw + float(swap_value or 0.0) + float(commission_value or 0.0)

    def _validate_unrealized_pnl_soft(
        self,
        symbol: str,
        mt5_symbol: str,
        ticket: str,
        direction: Direction,
        entry_price: float,
        current_price_fallback: float,
        quantity: float,
        swap_value: float,
        commission_value: float,
        broker_unrealized_pnl: float,
    ) -> tuple[bool, Dict[str, Any]]:
        """
        Soft-fail PnL validation:
        - returns valid=True when within tolerance
        - logs warning on manageable drift
        - caller decides whether to hard-fail on extreme drift
        """
        calc_pnl = self._estimate_unrealized_pnl(
            symbol=symbol,
            mt5_symbol=mt5_symbol,
            direction=direction,
            entry_price=entry_price,
            current_price_fallback=current_price_fallback,
            quantity=quantity,
            swap_value=swap_value,
            commission_value=commission_value,
        )
        diff = abs(float(broker_unrealized_pnl) - float(calc_pnl))
        base = max(abs(float(broker_unrealized_pnl)), abs(float(calc_pnl)), 1e-9)
        rel_diff = diff / base
        valid = (diff <= self.pnl_tolerance_abs) or (rel_diff <= self.pnl_tolerance_rel)
        return valid, {
            "broker_pnl": float(broker_unrealized_pnl),
            "calc_pnl": float(calc_pnl),
            "synced_pnl": float(broker_unrealized_pnl),
            "abs_diff": float(diff),
            "rel_diff": float(rel_diff),
            "ticket": str(ticket),
        }

    def _mt5_deal_reason_name(self, reason_code: int) -> str:
        """Map MT5 deal reason code to canonical bot exit reason."""
        try:
            reason_code = int(reason_code)
        except Exception:
            reason_code = -1
        sl_code = int(getattr(mt5, "DEAL_REASON_SL", 3))
        tp_code = int(getattr(mt5, "DEAL_REASON_TP", 4))
        so_code = int(getattr(mt5, "DEAL_REASON_SO", 5))
        client_code = int(getattr(mt5, "DEAL_REASON_CLIENT", 3))
        if reason_code == sl_code:
            return "SL_HIT"
        if reason_code == tp_code:
            return "TP_HIT"
        if reason_code == so_code:
            return "STOP_OUT"
        if reason_code == client_code or reason_code == 3:
            return "MANUAL_CLOSE"
        return "UNKNOWN"
    
    async def connect(self) -> bool:
        """Connect to MetaTrader 5 with extreme robustness"""
        try:
            # Reset stability counter and auth retry counter on fresh connect attempts.
            self._stable_connection_cycles = 0
            self._auth_retry_count = 0  # <--- FIX #2: Reset auth counter at start of each connect()
            import psutil
            import subprocess
            
            # Check for Administrator privileges (common cause of IPC timeouts)
            is_admin = self._detect_is_admin()
            
            self.logger.info(f"Connection attempt (Process Elevation: {'Admin' if is_admin else 'Standard User'})")
            if not is_admin:
                self.logger.warning("Bot is NOT running as Administrator. If MT5 is elevated, IPC connection WILL fail with timeout.")

            mt5_path = r"C:\Program Files\MetaTrader 5\terminal64.exe"
            
            # --- STAGE 1: CONNECT TO EXISTING ---
            is_running = any(proc.info['name'] == 'terminal64.exe' 
                           for proc in psutil.process_iter(['name']))
            
            if is_running:
                self.logger.info("Connecting to existing terminal...")
                try:
                    # Use to_thread + wait_for because mt5.initialize sometimes hangs despite timeout param
                    # Pass credentials directly to initialize to avoid Stage 1 authorization errors
                    if await self._attempt_initialize(
                        login=self.login,
                        password=self.password,
                        server=self.server,
                        timeout_ms=5000,
                        wait_timeout=15,
                    ):
                        self.logger.info("[OK] Connected and authorized with MT5 terminal")
                        return await self._login()
                    else:
                        err = mt5.last_error()
                        self.logger.warning("Failed to link to running terminal: %s. Re-initializing...", err)
                        if err[0] == -6:
                            self.logger.error(
                                "CRITICAL: MT5 Authorization failed (-6). Check your login, password, and server in config."
                            )
                            if await self._authorization_backoff_login("existing_terminal"):
                                return True
                except asyncio.TimeoutError:
                    self.logger.warning("Existing terminal connection HUNG. Proceeding to Stage 2...")

            # --- STAGE 2: START WITH PATH ---
            self.logger.info("Starting MT5 from path: %s", mt5_path)
            try:
                # Use to_thread + wait_for to ensure we don't hang forever
                # Increased timeout to 90 seconds for slower systems
                if await self._attempt_initialize(
                    path=mt5_path,
                    login=self.login,
                    password=self.password,
                    server=self.server,
                    timeout_ms=45000,
                    wait_timeout=90,
                ):
                    self.logger.info("[OK] MT5 initialized and authorized from path")
                    return await self._login()
            except asyncio.TimeoutError:
                self.logger.warning("Standard initialization HUNG (Timed out at 50s).")
            except Exception as e:
                self.logger.warning(f"Standard initialization error: {e}")
            
            err = mt5.last_error()
            self.logger.warning(f"Last MT5 Error: {err}")
            if isinstance(err, (list, tuple)) and len(err) > 0 and err[0] == -6:
                if await self._authorization_backoff_login("path_initialize"):
                    return True

            # --- STAGE 3: COLD START FALLBACK ---
            # Trigger if we reached here (either failed or hung in Stage 2)
            self.logger.info("Executing cold-start fallback (Manual Launch)...")
            await self._cleanup_terminal_processes()
            await asyncio.sleep(8)
            
            self.logger.info("Launching MT5 process manually: %s", mt5_path)
            try:
                subprocess.Popen([mt5_path])
            except Exception as launch_err:
                self.logger.error(f"Failed to launch MT5 process: {launch_err}")
                return False
            
            self.logger.info("Waiting 20s for MT5 GUI to fully load before initialize...")
            await asyncio.sleep(20)

            for attempt in range(12):
                self.logger.info(f"Connection attempt {attempt+1}/12...")
                await asyncio.sleep(7)
                
                try:
                    # Try to attach to the manually launched terminal
                    if await self._attempt_initialize(
                        login=self.login,
                        password=self.password,
                        server=self.server,
                        timeout_ms=10000,
                        wait_timeout=20,
                    ):
                        self.logger.info("[OK] MT5 connected and authorized after manual launch")
                        return await self._login()
                    else:
                        # Check for auth failure in STAGE 3
                        err = mt5.last_error()
                        if isinstance(err, (list, tuple)) and len(err) > 0 and err[0] == -6:
                            self.logger.warning("[STAGE3_AUTH_ERROR] Auth failed during cold-start attempt %d", attempt+1)
                            if await self._authorization_backoff_login("stage3_coldstart"):
                                return True
                            # If backoff failed and we've exceeded max retries, fail immediately
                            if self._auth_retry_count > self._max_auth_retries:
                                self.logger.error("[STAGE3_MAX_AUTH_RETRIES] Max auth retries exceeded in STAGE 3")
                                return False
                except (asyncio.TimeoutError, Exception) as e:
                    self.logger.debug(f"Attempt {attempt+1} connection failed/hung: {e}")
                    # Check if it's an auth error
                    err = mt5.last_error()
                    if isinstance(err, (list, tuple)) and len(err) > 0 and err[0] == -6:
                        if self._auth_retry_count > self._max_auth_retries:
                            self.logger.error("[STAGE3_MAX_AUTH_RETRIES_EXCEPTION] Max auth retries exceeded in STAGE 3")
                            return False
                
            self.logger.error("All cold-start connection attempts failed")
            return False
            
        except Exception as e:
            self.logger.error(f"Error during MT5 connect: {e}")
            return False

    async def _login(self) -> bool:
        """Internal login logic with existing session check and hang protection"""
        try:
            # 1. Check if already logged in (with timeout)
            try:
                account_info = await asyncio.wait_for(asyncio.to_thread(mt5.account_info), timeout=15)
                if account_info is not None:
                    if account_info.login == self.login:
                        self.logger.info("[OK] Already logged in to account %s", self.login)
                        self.connected = True
                        return True
                    else:
                        self.logger.info("Currently on account %s, switching to %s...", account_info.login, self.login)
            except asyncio.TimeoutError:
                self.logger.warning("Check for existing login HUNG. Forcing login...")

            # 2. Perform Login (with timeout)
            self.logger.info("Logging in to account %s on %s...", self.login, self.server)
            try:
                login_success = await asyncio.wait_for(
                    asyncio.to_thread(mt5.login, login=self.login, password=self.password, server=self.server),
                    timeout=30
                )
                if not login_success:
                    self.logger.error(f"MT5 login failed: {mt5.last_error()}")
                    return False
            except asyncio.TimeoutError:
                self.logger.error("MT5 login call HUNG (Timed out at 30s)")
                return False
            
            # 3. Verify Account Info (with timeout)
            try:
                account_info = await asyncio.wait_for(asyncio.to_thread(mt5.account_info), timeout=15)
                if account_info is None:
                    self.logger.error("Failed to get account info after login")
                    return False
                
                self.logger.info("[OK] Connected to MT5 account: %s", account_info.login)
                self.logger.info("Balance: %s, Equity: %s", format_float(account_info.balance, '.2f'), format_float(account_info.equity, '.2f'))

                # Subscribe monitored symbols after successful login.
                self._subscribe_monitored_symbols()

                self.connected = True
                return True
            except asyncio.TimeoutError:
                self.logger.error("Verification of account info HUNG after successful login")
                return False
                
        except Exception as e:
            self.logger.error(f"Login exception: {e}")
            return False

    async def _cleanup_terminal_processes(self):
        """Kill all terminal64.exe processes using psutil for better reliability"""
        import psutil
        try:
            self.logger.info("Killing any existing terminal64.exe processes...")
            for proc in psutil.process_iter(['pid', 'name']):
                if proc.info['name'] == 'terminal64.exe':
                    try:
                        self.logger.info(f"Terminating MT5 process (PID: {proc.info['pid']})")
                        proc.kill()
                    except Exception as e:
                        self.logger.error(f"Failed to kill process {proc.info['pid']}: {e}")
            await asyncio.sleep(3) # Give it a moment to release resources
        except Exception as e:
            self.logger.error(f"Error during terminal process cleanup: {e}")
    
    async def disconnect(self) -> bool:
        """Disconnect from MetaTrader 5"""
        try:
            if self.connected:
                mt5.shutdown()
                self.connected = False
                self._stable_connection_cycles = 0
                self.logger.info("Disconnected from MT5")
            return True
        except Exception as e:
            self.logger.error(f"Error disconnecting from MT5: {e}")
            return False
    
    def _sync_ticket_to_disk(self, ticket_id: str, symbol: str, direction: str, 
                            entry_price: float, stop_loss: float, take_profit: float) -> bool:
        """
        ===== TRANSACTIONAL TICKET PERSISTENCE =====
        Synchronously save ticket and position data to disk immediately upon TRADE_RETCODE_DONE.
        
        This is called IN THE SAME THREAD as the order confirmation, preventing any 
        memory-to-disk desynchronization that could lead to orphaned positions.
        
        The ticket is written to a transactional registry file with atomic operations
        BEFORE any subsequent processing occurs.
        
        Args:
            ticket_id: MT5 ticket number as string
            symbol: Symbol (e.g., 'EURUSD')
            direction: 'BUY' or 'SELL'
            entry_price: Position entry price
            stop_loss: Stop loss price
            take_profit: Take profit price
            
        Returns:
            bool: True if successfully persisted, False if write failed
        """
        temp_path = self.TRANSACTIONAL_TICKET_REGISTRY + ".tmp"
        try:
            # Read existing registry or start fresh
            registry = {}
            if os.path.exists(self.TRANSACTIONAL_TICKET_REGISTRY):
                try:
                    with open(self.TRANSACTIONAL_TICKET_REGISTRY, 'r') as f:
                        registry = json.load(f)
                except Exception as read_err:
                    self.logger.warning(
                        f"[TRANSACTIONAL] Could not read existing registry ({read_err}). Starting fresh."
                    )
                    registry = {}
            
            # Add new ticket data
            registry[ticket_id] = {
                'ticket_id': ticket_id,
                'symbol': symbol,
                'direction': direction,
                'entry_price': entry_price,
                'stop_loss': stop_loss,
                'take_profit': take_profit,
                'persisted_at': datetime.now(timezone.utc).isoformat(),
                'status': 'CONFIRMED'
            }
            
            # Atomic write: write to temp file first, then rename
            with open(temp_path, 'w') as f:
                json.dump(registry, f, indent=2)
            
            # Atomic replacement
            if os.path.exists(self.TRANSACTIONAL_TICKET_REGISTRY):
                os.remove(self.TRANSACTIONAL_TICKET_REGISTRY)
            os.rename(temp_path, self.TRANSACTIONAL_TICKET_REGISTRY)
            
            self.logger.critical(
                f"[TRANSACTIONAL_PERSISTENCE] âœ… Ticket {ticket_id} ({symbol} {direction}) "
                f"IMMEDIATELY PERSISTED TO DISK | "
                f"Entry: {format_float(entry_price, '.5f')} | "
                f"SL: {format_float(stop_loss, '.5f')} | "
                f"TP: {format_float(take_profit, '.5f')}"
            )
            return True
            
        except Exception as e:
            self.logger.critical(
                f"[TRANSACTIONAL_PERSISTENCE_FAILED] âŒ CRITICAL: Could not persist ticket {ticket_id} to disk! {e} | "
                f"This ticket MAY BECOME ORPHANED. Manual recovery may be required."
            )
            # Clean up temp file if it exists
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except:
                    pass
            return False
    
    async def disconnect(self) -> bool:
        """Disconnect from MetaTrader 5"""
        try:
            if self.connected:
                mt5.shutdown()
                self.connected = False
                self.logger.info("Disconnected from MT5")
            return True
        except Exception as e:
            self.logger.error(f"Error disconnecting from MT5: {e}")
            return False
    
    async def get_account_info(self) -> Portfolio:
        """Get account information with retry logic"""
        if not self.connected:
            # Try to reconnect
            await self.connect()
            if not self.connected:
                raise BrokerAPIError("Not connected to MT5")
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                account_info = mt5.account_info()
                if account_info is None:
                    if attempt < max_retries - 1:
                        self.logger.warning(f"account_info() returned None, attempt {attempt + 1}/{max_retries}, retrying...")
                        await asyncio.sleep(0.5)  # Brief delay before retry
                        continue
                    else:
                        raise BrokerAPIError("Failed to get account info after retries")
                
                # Get open positions with retry
                positions = None
                for pos_attempt in range(2):
                    positions = mt5.positions_get()
                    if positions is not None:
                        break
                    if pos_attempt == 0:
                        await asyncio.sleep(0.2)
                
                if positions is None:
                    self.logger.warning("positions_get() returned None, continuing with empty positions")
                    positions = ()
                    
                position_list = []
                for pos in positions:
                    try:
                        # Map MT5 symbol format (USDJPY) back to standard format (USD/JPY)
                        standard_symbol = self.reverse_symbol_mapping.get(pos.symbol, pos.symbol)
                        direction = Direction.LONG if pos.type == 0 else Direction.SHORT
                        symbol_info = mt5.symbol_info(pos.symbol)
                        tick_size = float(getattr(symbol_info, "trade_tick_size", 0.0) or 0.0) if symbol_info else 0.0
                        tick_value = float(getattr(symbol_info, "trade_tick_value", 0.0) or 0.0) if symbol_info else 0.0
                        pnl_for_model = float(float(getattr(pos, "profit", 0.0) or 0.0) + float(getattr(pos, "swap", 0.0) or 0.0))
                        # ===== ISSUE #1 FIX: Clear warned tickets at sync start (first position) =====
                        # Reset tracking on first position to start fresh per sync cycle
                        if not self._warned_time_clamp_tickets_this_sync:
                            self._warned_time_clamp_tickets_this_sync.clear()
                        
                        ticket_str = str(getattr(pos, "ticket", ""))
                        normalized_opened_at = clamp_future_position_time(
                            normalize_mt5_timestamp_to_utc(pos.time)
                        )
                        if normalized_opened_at != normalize_mt5_timestamp_to_utc(pos.time):
                            # ===== ISSUE #1 FIX: Only warn once per ticket per sync cycle =====
                            if ticket_str not in self._warned_time_clamp_tickets_this_sync:
                                self.logger.warning(
                                    "[MT5_POSITION_TIME_CLAMP] Ticket=%s | raw_pos_time=%s | normalized_opened_at=%s | clamped_to=%s",
                                    ticket_str,
                                    str(getattr(pos, "time", "")),
                                    normalize_mt5_timestamp_to_utc(pos.time).isoformat(),
                                    normalized_opened_at.isoformat(),
                                )
                                self._warned_time_clamp_tickets_this_sync.add(ticket_str)

                        position_list.append(Position(
                            position_id=str(pos.ticket),
                            symbol=standard_symbol,
                            direction=direction,
                            quantity=pos.volume,
                            entry_price=pos.price_open,
                            current_price=pos.price_current,
                            unrealized_pnl=pnl_for_model,
                            stop_loss=pos.sl if pos.sl != 0.0 else None,
                            take_profit=pos.tp if pos.tp != 0.0 else None,
                            opened_at=normalized_opened_at,
                            magic=pos.magic,
                            swap=float(getattr(pos, "swap", 0.0) or 0.0),
                            commission=float(getattr(pos, "commission", 0.0) or 0.0),
                            tick_value=tick_value if tick_value > 0.0 else None,
                            tick_size=tick_size if tick_size > 0.0 else None,
                            # ===== FIX #1: SET FLAG TO PREVENT RECALCULATION =====
                            time_normalized=True
                        ))
                    except Exception as pos_err:
                        self.logger.error(f"Error processing position {pos.ticket}: {pos_err}")
                        try:
                            ticket_id = str(getattr(pos, "ticket", ""))
                            live_pos = mt5.positions_get(ticket=int(ticket_id)) if ticket_id else None
                            if not live_pos:
                                self._ghost_ticket_ids.add(ticket_id)
                                self.logger.warning(
                                    f"[GHOST_PURGE_FLAG] Ticket {ticket_id} failed processing and is absent in MT5. "
                                    f"Flagged for forced registry purge."
                                )
                        except Exception:
                            # Keep original error path non-fatal.
                            pass
                        continue
                
                return Portfolio(
                    account_id=str(account_info.login),
                    balance=account_info.balance,
                    equity=account_info.equity,
                    margin_used=account_info.margin,
                    margin_available=account_info.margin_free,
                    positions=position_list,
                    updated_at=datetime.now(timezone.utc)
                )
                
            except Exception as e:
                if attempt < max_retries - 1:
                    self.logger.warning(f"Error getting account info (attempt {attempt + 1}/{max_retries}): {e}")
                    await asyncio.sleep(0.5)
                    continue
                else:
                    self.logger.error(f"Error getting account info after {max_retries} attempts: {e}")
                    raise BrokerAPIError(f"Failed to get account info: {e}")
    
    async def check_connection_health(self) -> bool:
        """Check if MT5 connection is healthy"""
        try:
            account_info = await asyncio.wait_for(
                asyncio.to_thread(mt5.account_info), 
                timeout=5
            )
            if account_info is not None:
                self.connected = True
                self._stable_connection_cycles += 1
                return True
            else:
                self.logger.warning("Connection health check: account_info returned None")
                self.connected = False
                self._stable_connection_cycles = 0
                return False
        except asyncio.TimeoutError:
            self.logger.warning("Connection health check: Timeout")
            self.connected = False
            self._stable_connection_cycles = 0
            return False
        except Exception as e:
            self.logger.warning(f"Connection health check failed: {e}")
            self.connected = False
            self._stable_connection_cycles = 0
            return False
    
    def _is_price_valid(self, tick) -> bool:
        """Validation Function: Returns True only if tick.bid < tick.ask and both values are greater than zero."""
        if tick is None:
            return False
        if not self._is_tick_fresh(tick, max_age_seconds=60):
            return False
        return tick.bid > 0 and tick.ask > 0 and tick.bid < tick.ask

    def _mark_market_data_glitch(self, symbol: str) -> int:
        key = symbol.replace("/", "").upper()
        current = self._market_data_glitch_counts.get(key, 0) + 1
        self._market_data_glitch_counts[key] = current
        return current

    def _reset_market_data_glitch(self, symbol: str) -> None:
        key = symbol.replace("/", "").upper()
        if key in self._market_data_glitch_counts:
            del self._market_data_glitch_counts[key]

    async def _trigger_local_sync_halt(self, symbol: str, reason: str) -> None:
        key = symbol.replace("/", "").upper()
        # FIX: Check if already halted to prevent redundant logging
        if key in self._local_sync_halt_until:
            halt_until = self._local_sync_halt_until[key]
            if datetime.now(timezone.utc) < halt_until:
                return  # Already halted, skip redundant trigger
        until = datetime.now(timezone.utc) + timedelta(seconds=self._local_sync_halt_seconds)
        self._local_sync_halt_until[key] = until
        self.logger.critical(
            "[LOCAL_SYNC_HALT] %s | Halted until %s | Reason: %s",
            key,
            until.strftime("%Y-%m-%d %H:%M:%S UTC"),
            reason,
        )
        async with self._local_sync_reinit_lock:
            try:
                await self.disconnect()
                await asyncio.sleep(1)
                await self.connect()
            except Exception as exc:
                self.logger.error("[LOCAL_SYNC_HALT] Re-init failed for %s: %s", key, exc)

    async def _attempt_frozen_quote_feed_reconnect(self, symbol: str, glitch_count: int) -> None:
        if glitch_count < 3:
            return
        self.logger.critical(
            "[FROZEN_FEED_RECONNECT] %s | Frozen quote persisted %d cycles. Forcing MT5 feed reconnect.",
            symbol,
            glitch_count,
        )
        await self._trigger_local_sync_halt(symbol, f"Frozen quote persisted {glitch_count} cycles")

    async def get_market_data(self, symbol: str) -> MarketData:
        """Get real-time market data"""
        if not self.connected:
            raise BrokerAPIError("Not connected to MT5")
        
        try:
            # Map/select symbol through the MT5 manager
            symbol_info, mt5_symbol = self.manager.get_symbol_info(symbol)
            symbol_key = symbol.replace("/", "").upper()
            halt_until = self._local_sync_halt_until.get(symbol_key)
            if halt_until and datetime.now(timezone.utc) < halt_until:
                self.logger.warning(
                    "[LOCAL_SYNC_HALT] %s | Market data requests paused until %s",
                    symbol_key,
                    halt_until.strftime("%Y-%m-%d %H:%M:%S UTC"),
                )
                return None
            
            # Strict live quote handling: force wakeup via copy_ticks_from.
            tick = self.ensure_symbol_active(symbol)
            if tick is None:
                bid = "N/A"
                ask = "N/A"
                last_err = None
                try:
                    last_err = mt5.last_error()
                except Exception:
                    last_err = None
                if last_err and "IPC" in str(last_err):
                    self._log_ipc_admin_warning("market_data_invalid_tick", str(last_err))
                
                if not self._is_probably_fx_market_open():
                    # Market is closed (weekend), gracefully pause instead of halting
                    self.logger.debug(
                        f"[MARKET_CLOSED_GRACEFUL] {symbol} | Bid/Ask unavailable during market closure. "
                        f"Gracefully pausing data collection until market reopens."
                    )
                    return None
                
                glitch_count = self._mark_market_data_glitch(symbol)
                self.logger.warning(
                    f"[MARKET_DATA_GLITCH] Invalid quote for {symbol} (Bid: {bid}, Ask: {ask}). "
                    "Strict mode: no OHLC estimates. Skipping cycle."
                )
                if glitch_count > 3:
                    await self._trigger_local_sync_halt(
                        symbol, f"Invalid quote persisted {glitch_count} cycles"
                    )
                return None

            self._reset_market_data_glitch(symbol)
            if symbol_key in self._local_sync_halt_until:
                if datetime.now(timezone.utc) >= self._local_sync_halt_until[symbol_key]:
                    del self._local_sync_halt_until[symbol_key]

            synthetic_quote = False
            if tick.get("frozen"):
                close_price, is_moving = self._get_recent_m1_close(mt5_symbol)
                if close_price is None:
                    glitch_count = self._mark_market_data_glitch(symbol)
                    self.logger.warning(
                        f"[MARKET_DATA_GLITCH] Frozen quote with no M1 close for {symbol}. "
                        "Strict mode: no OHLC estimates. Skipping cycle."
                    )
                    if glitch_count >= 3:
                        await self._attempt_frozen_quote_feed_reconnect(symbol, glitch_count)
                    return None

                pip_size = self._get_symbol_pip_size(symbol)
                min_spread = 1.0 * pip_size
                tick["bid"] = close_price - (min_spread / 2)
                tick["ask"] = close_price + (min_spread / 2)
                tick["last"] = close_price
                synthetic_quote = True

                if is_moving:
                    self._set_limit_price_hint(symbol, close_price, ttl_seconds=60)
                    self.logger.warning(
                        "[FROZEN_QUOTE_FALLBACK] %s | Bid/Ask frozen. M1 close=%.5f moving. "
                        "Limit-order hint armed.",
                        symbol,
                        close_price,
                    )
                else:
                    glitch_count = self._mark_market_data_glitch(symbol)
                    self.logger.warning(
                        "[FROZEN_QUOTE_FALLBACK] %s | Bid/Ask frozen. M1 close=%.5f static. "
                        "Using synthetic quote without limit hint.",
                        symbol,
                        close_price,
                    )
                    if glitch_count >= 3:
                        await self._attempt_frozen_quote_feed_reconnect(symbol, glitch_count)
            
            market_open, market_reason = self._check_symbol_session(symbol, symbol_info=symbol_info)
            if not market_open:
                self.logger.debug(
                    "[MARKET_CLOSED_GRACEFUL] %s | %s",
                    symbol,
                    market_reason,
                )
                return None
            
            # Point and Pip Calculation for Tolerance
            point = symbol_info.point
            pip_size = self._get_symbol_pip_size(symbol, symbol_info)
            tolerance_pips = self._resolve_spread_tolerance_pips(mt5_symbol=mt5_symbol)
            tolerance = tolerance_pips * pip_size
            
            # ===== SPREAD VALIDATION & SOURCE OF TRUTH =====
            # 1. Calculate spread from Bid/Ask
            calculated_spread = tick["ask"] - tick["bid"]
            # 2. Compare against MT5 reported spread (provided in points)
            reported_spread = symbol_info.spread * point
            calculated_spread_pips = PipStandardizer.spread_to_pips(
                ask=float(tick["ask"]),
                bid=float(tick["bid"]),
                symbol=symbol,
                symbol_info=symbol_info,
            )
            reported_spread_pips = self._price_delta_to_pips(symbol, reported_spread, symbol_info)
            diff_pips = self._price_delta_to_pips(symbol, abs(calculated_spread - reported_spread), symbol_info)
            server_time = self._get_server_time_from_tick(tick)
            in_rollover_sleep = self._handle_rollover_sleep_state(symbol, server_time)

            if not synthetic_quote and not in_rollover_sleep:
                diff = abs(calculated_spread - reported_spread)
                if diff > tolerance + 1e-7:
                    self.logger.warning(
                        f"[SPREAD_MISMATCH] {symbol} exceeds {tolerance_pips:.1f} pip tolerance. "
                        f"Calculated: {calculated_spread:.5f} ({calculated_spread_pips:.1f} pips), "
                        f"Reported: {reported_spread:.5f} ({reported_spread_pips:.1f} pips), "
                        f"Delta: {diff_pips:.1f} pips. Skipping cycle."
                    )
                    return None

                if diff > 0:
                    self.logger.debug(
                        f"[SPREAD_DRIFT] {symbol} Minor drift detected ({diff:.6f} / {diff_pips:.2f} pips). "
                        f"Using calculated spread as source of truth."
                    )
            # ===============================================

            # Use last price if available, otherwise mid price
            price_to_use = tick["last"] if tick["last"] > 0 else (tick["bid"] + tick["ask"]) / 2
            
            # ===== SPREAD SAFETY FLOOR (1.0 Pip) =====
            # Ensure we have a minimum spread floor for risk calculations
            min_spread = 1.0 * pip_size
            safe_spread = max(calculated_spread, min_spread)
            
            market_snapshot = MarketData(
                symbol=symbol,
                timestamp=datetime.fromtimestamp(tick["time"], tz=timezone.utc),
                open=price_to_use,
                high=price_to_use,
                low=price_to_use,
                close=price_to_use,
                volume=int(tick["volume"]),
                bid=tick["bid"],
                ask=tick["ask"],
                spread=safe_spread
            )
            try:
                setattr(market_snapshot, "quote_is_frozen", bool(synthetic_quote))
                setattr(market_snapshot, "tick_age_seconds", float(self._get_tick_age_seconds(tick) or 0.0))
            except Exception:
                pass
            return market_snapshot
            
        except Exception as e:
            self.logger.error(f"Error getting market data for {symbol}: {e}")
            raise BrokerAPIError(f"Failed to get market data: {e}")
    
    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # SL/TP Pre-flight Validation Helper
    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _validate_sltp_preflight(
        self,
        mt5_symbol: str,
        direction: Direction,
        entry_price: float,
        stop_loss: Optional[float],
        take_profit: Optional[float],
    ) -> tuple:
        """
        Validate SL and TP against broker's minimum stop distance.

        Reads symbol_info.trade_stops_level (in points) to determine the
        minimum distance from current price that stops must be placed.
        Adjusts stops outward if they violate the constraint.

        Returns:
            (validated_sl: float, validated_tp: float, validation_ok: bool, report: str)
        """
        try:
            symbol_info = mt5.symbol_info(mt5_symbol)
            if symbol_info is None:
                return stop_loss, take_profit, False, f"symbol_info returned None for {mt5_symbol}"

            point          = symbol_info.point          # e.g. 0.00001 for EURUSD
            digits         = symbol_info.digits         # e.g. 5
            stops_level    = symbol_info.trade_stops_level  # minimum distance in points
            min_stop_dist  = stops_level * point        # minimum distance in price units

            # Use a sensible floor: at least 1 pip even if broker says 0
            pip_size = (0.01 if 'JPY' in mt5_symbol else 0.0001)
            min_stop_dist = max(min_stop_dist, pip_size * 2)

            tick = mt5.symbol_info_tick(mt5_symbol)
            current_ask = tick.ask if tick else entry_price
            current_bid = tick.bid if tick else entry_price

            validated_sl = stop_loss
            validated_tp = take_profit
            adjustments  = []
            if stop_loss in (None, 0.0) or take_profit in (None, 0.0):
                return stop_loss, take_profit, False, "stop_loss/take_profit missing"

            if direction == Direction.LONG:
                ref_price = current_ask
                # SL must be below (ref_price - min_stop_dist)
                sl_limit = round(ref_price - min_stop_dist, digits)
                # TP must be above (ref_price + min_stop_dist)
                tp_limit = round(ref_price + min_stop_dist, digits)

                if validated_sl is not None and validated_sl >= sl_limit:
                    old_sl = validated_sl
                    validated_sl = round(sl_limit - pip_size, digits)
                    adjustments.append(f"SL adjusted from {old_sl:.{digits}f} â†’ {validated_sl:.{digits}f} (min dist: {min_stop_dist:.{digits}f})")

                if validated_tp is not None and validated_tp <= tp_limit:
                    old_tp = validated_tp
                    validated_tp = round(tp_limit + pip_size, digits)
                    adjustments.append(f"TP adjusted from {old_tp:.{digits}f} â†’ {validated_tp:.{digits}f} (min dist: {min_stop_dist:.{digits}f})")
            else:
                ref_price = current_bid
                # SL must be above (ref_price + min_stop_dist)
                sl_limit = round(ref_price + min_stop_dist, digits)
                # TP must be below (ref_price - min_stop_dist)
                tp_limit = round(ref_price - min_stop_dist, digits)

                if validated_sl is not None and validated_sl <= sl_limit:
                    old_sl = validated_sl
                    validated_sl = round(sl_limit + pip_size, digits)
                    adjustments.append(f"SL adjusted from {old_sl:.{digits}f} â†’ {validated_sl:.{digits}f} (min dist: {min_stop_dist:.{digits}f})")

                if validated_tp is not None and validated_tp >= tp_limit:
                    old_tp = validated_tp
                    validated_tp = round(tp_limit - pip_size, digits)
                    adjustments.append(f"TP adjusted from {old_tp:.{digits}f} â†’ {validated_tp:.{digits}f} (min dist: {min_stop_dist:.{digits}f})")

            report = (
                f"symbol={mt5_symbol} point={point} digits={digits} "
                f"trade_stops_level={stops_level} min_dist={min_stop_dist:.{digits}f} "
                f"entryâ‰ˆ{entry_price:.{digits}f} | "
                + ('; '.join(adjustments) if adjustments else "SL/TP within broker constraints")
            )
            return validated_sl, validated_tp, len(adjustments) == 0, report

        except Exception as e:
            return stop_loss, take_profit, False, f"pre-flight validation exception: {e}"

    def _normalize_price(self, mt5_symbol: str, price: Optional[float]) -> Optional[float]:
        """Normalize any order/SL/TP price to the broker symbol digits."""
        if price is None:
            return None
        try:
            symbol_info = mt5.symbol_info(mt5_symbol)
            digits = symbol_info.digits if symbol_info is not None else 5
            return round(float(price), int(digits))
        except Exception:
            return float(price)

    def _calc_deviation_points(self, mt5_symbol: str, pips: float = 1.5) -> int:
        try:
            symbol_info = mt5.symbol_info(mt5_symbol)
            point = float(getattr(symbol_info, "point", 0.0) or 0.0)
            pip_size = 0.01 if "JPY" in mt5_symbol else 0.0001
            if point <= 0:
                return 1
            points = int(round((pip_size * float(pips)) / point))
            return max(1, points)
        except Exception:
            return 1

    async def place_order(self, symbol: str, direction: Direction, size: float,
                         price: Optional[float] = None, stop_loss: Optional[float] = None,
                         take_profit: Optional[float] = None) -> str:
        """Place a market order with mandatory SL/TP attachment and broker pre-flight validation."""
        
        # ===== IMPROVEMENT #1: CRITICAL STABILITY â€“ ORDER_TYPE SCOPED FIRST =====
        # Define order_type at the ABSOLUTE FIRST LINE of the function body so it is
        # always available in error-handling branches and retry loops, preventing
        # NameError: name 'order_type' is not defined.
        order_type = mt5.ORDER_TYPE_BUY if direction == Direction.LONG else mt5.ORDER_TYPE_SELL
        
        if not self.connected:
            raise BrokerAPIError("Not connected to MT5")

        try:
            market_closed_retcode = int(getattr(mt5, "TRADE_RETCODE_MARKET_CLOSED", 10018))
            symbol_info, mt5_symbol = self.manager.get_symbol_info(symbol)
            _prepared_symbol, _prepared_info = self._prepare_symbol_for_trading(symbol)
            mt5_symbol = _prepared_symbol
            symbol_info = _prepared_info

            # â”€â”€ Volume normalisation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            step   = symbol_info.volume_step
            volume = round(size / step) * step
            if volume is None or volume <= 0:
                raise BrokerAPIError(f"Invalid volume: {volume}")

            limit_hint_price = self._consume_limit_price_hint(symbol)
            use_limit_order = limit_hint_price is not None
            if use_limit_order:
                pip_size = self._get_symbol_pip_size(symbol, symbol_info)
                synthetic_offset = max(float(pip_size or 0.0) * 0.2, float(getattr(symbol_info, "point", 0.0) or 0.0))
                target_price = float(limit_hint_price) - synthetic_offset if direction == Direction.LONG else float(limit_hint_price) + synthetic_offset
                self.logger.info(
                    "[FROZEN_LIMIT_HINT] %s | hint=%.5f | offset=%.5f | target=%.5f",
                    symbol,
                    float(limit_hint_price),
                    synthetic_offset,
                    float(target_price),
                )
            else:
                target_price = price or (symbol_info.ask if direction == Direction.LONG else symbol_info.bid)
            if target_price is None or target_price <= 0:
                raise BrokerAPIError(f"Invalid price: {target_price}")

            digits = symbol_info.digits
            target_price = self._normalize_price(mt5_symbol, target_price)
            deviation_points = self._calc_deviation_points(mt5_symbol, pips=1.5)

            # â”€â”€ Pre-flight SL/TP validation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            validated_sl, validated_tp, pf_ok, pf_report = self._validate_sltp_preflight(
                mt5_symbol, direction, target_price, stop_loss, take_profit
            )
            self.logger.info(
                f"[ORDER_EXECUTION] {symbol} | PREFLIGHT | {pf_report} | "
                f"SL={format_float(validated_sl, f'.{digits}f')} "
                f"TP={format_float(validated_tp, f'.{digits}f')} | "
                f"BrokerValidation={'OK' if pf_ok else 'WARN'}"
            )
            if not pf_ok:
                raise BrokerAPIError(
                    f"SLTP_PREFLIGHT_REJECTED: {symbol} | {pf_report} | "
                    f"SL={format_float(validated_sl, f'.{digits}f')} TP={format_float(validated_tp, f'.{digits}f')}"
                )

            # â”€â”€ R:R ratio audit â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            if validated_sl and validated_tp and target_price:
                raw_risk   = abs(target_price - validated_sl)
                raw_reward = abs(validated_tp - target_price)
                rr_ratio   = (raw_reward / raw_risk) if raw_risk > 0 else 0.0
            else:
                rr_ratio = 0.0

            self.logger.info(
                f"[ORDER_EXECUTION] {symbol} | {direction.value} | "
                f"Entry={format_float(target_price, f'.{digits}f')} | "
                f"SL={format_float(validated_sl, f'.{digits}f')} | "
                f"TP={format_float(validated_tp, f'.{digits}f')} | "
                f"R:R={format_float(rr_ratio, '.2f')}R | "
                f"Volume={format_float(volume, '.2f')} lots"
            )

            # â”€â”€ Build base request WITH sl/tp â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            # NOTE: order_type is already defined above (Improvement #1), reused here.
            request = {
                "action":    mt5.TRADE_ACTION_DEAL,
                "symbol":    mt5_symbol,
                "volume":    float(volume),
                "type":      order_type,
                "price":     float(target_price),
                "deviation": deviation_points,
                "magic":     234000,
                "comment":   "AIBot",
                "type_time": mt5.ORDER_TIME_GTC,
            }

            # Always attach validated SL/TP; fall back to 0.0 only if None
            # (MT5 treats 0.0 as "no stop", but we guard against that below)
            if validated_sl is not None:
                request["sl"] = self._normalize_price(mt5_symbol, validated_sl)
            if validated_tp is not None:
                request["tp"] = self._normalize_price(mt5_symbol, validated_tp)

            if use_limit_order:
                pending_type = mt5.ORDER_TYPE_BUY_LIMIT if direction == Direction.LONG else mt5.ORDER_TYPE_SELL_LIMIT
                pending_request = {
                    "action": mt5.TRADE_ACTION_PENDING,
                    "symbol": mt5_symbol,
                    "volume": float(volume),
                    "type": pending_type,
                    "price": float(target_price),
                    "deviation": deviation_points,
                    "magic": 234000,
                    "comment": "AIBot-LIMIT-FROZEN",
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": mt5.ORDER_FILLING_RETURN,
                }
                if validated_sl is not None:
                    pending_request["sl"] = self._normalize_price(mt5_symbol, validated_sl)
                if validated_tp is not None:
                    pending_request["tp"] = self._normalize_price(mt5_symbol, validated_tp)

                self.logger.warning(
                    f"[ORDER_EXECUTION] {symbol} | FROZEN_QUOTE_LIMIT | "
                    f"Price={format_float(target_price, f'.{digits}f')} | "
                    f"SL={pending_request.get('sl', 'NONE')} TP={pending_request.get('tp', 'NONE')} | "
                    f"Deviation={deviation_points}pts"
                )
                result = mt5.order_send(pending_request)
                if result is None:
                    raise BrokerAPIError("Limit order failed: Broker returned None (timeout)")
                if int(getattr(result, "retcode", -1)) == market_closed_retcode:
                    msg = f"MARKET_CLOSED: {result.retcode} - {result.comment}"
                    self.logger.warning(
                        f"[ORDER_DEFERRED_MARKET_CLOSED] {symbol} | {msg} | "
                        "Limit order placement deferred until market reopens."
                    )
                    raise BrokerAPIError(msg)
                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    placed_ticket = str(result.order)
                    direction_label = "BUY" if direction == Direction.LONG else "SELL"
                    persist_ok = self._sync_ticket_to_disk(
                        ticket_id=placed_ticket,
                        symbol=mt5_symbol,
                        direction=direction_label,
                        entry_price=target_price,
                        stop_loss=validated_sl if validated_sl else 0.0,
                        take_profit=validated_tp if validated_tp else 0.0
                    )
                    if not persist_ok:
                        self.logger.critical(
                            f"[ORDER_EXECUTION_WARNING] Ticket {placed_ticket} obtained but "
                            f"persistence to disk FAILED. Position may become orphaned."
                        )
                    self.logger.info(
                        f"[ORDER_EXECUTION] {symbol} | LIMIT PLACED | ticket={placed_ticket}"
                    )
                    return placed_ticket

                raise BrokerAPIError(f"Limit order failed: {result.retcode} - {result.comment}")

            _, placed_ticket = await self._send_order_with_fill_mode_fallback(
                symbol=symbol,
                mt5_symbol=mt5_symbol,
                symbol_info=symbol_info,
                request=request,
                order_type=order_type,
                target_price=target_price,
                validated_sl=validated_sl,
                validated_tp=validated_tp,
                market_closed_retcode=market_closed_retcode,
                allow_fallbacks=True,
            )

            await asyncio.sleep(0.3)
            try:
                filled_positions = mt5.positions_get(ticket=int(placed_ticket))
                pos_to_check = filled_positions[0] if filled_positions and len(filled_positions) > 0 else None
                if pos_to_check is None:
                    all_pos = mt5.positions_get(symbol=mt5_symbol)
                    if all_pos:
                        pos_to_check = max(all_pos, key=lambda p: p.time)
                if pos_to_check is None:
                    raise BrokerAPIError(f"Confirmation failed: position {placed_ticket} not found in MT5")
                sl_live = pos_to_check.sl
                tp_live = pos_to_check.tp
                if sl_live in (None, 0.0) or tp_live in (None, 0.0):
                    self.logger.error(
                        "[ORDER_EXECUTION] %s | ticket=%s | confirmation failed | SL=%s TP=%s",
                        symbol,
                        placed_ticket,
                        sl_live,
                        tp_live,
                    )
                    close_ok = await self.close_position(str(pos_to_check.ticket))
                    status = "closed" if close_ok else "close_failed"
                    raise BrokerAPIError(f"SLTP_CONFIRMATION_FAILED: ticket={placed_ticket} | {status}")
            except Exception as verify_err:
                raise BrokerAPIError(
                    f"SLTP_VERIFICATION_FAILED: {symbol} | ticket={placed_ticket} | {verify_err}"
                )

            self.logger.info(
                f"[ORDER_EXECUTION] {symbol} | CONFIRMED | ticket={placed_ticket} | "
                f"SL={format_float(sl_live, f'.{digits}f')} TP={format_float(tp_live, f'.{digits}f')}"
            )
            return placed_ticket

            # â”€â”€ Filling-mode priority list â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            # ===== IMPROVEMENT #2: FILL-MODE CACHING =====
            # If a fill mode succeeded on a previous order, try it FIRST before
            # building and iterating the full fallback list.  This eliminates
            # latency from testing modes 0, 1, 2 on every single order.
            uncaged_active = (
                str(os.environ.get("SYSTEM_UNCAGED", "0")).lower() in {"1", "true", "yes", "on"}
                or str(os.environ.get("SYSTEM_UNCAGED_V6", "0")).lower() in {"1", "true", "yes", "on"}
                or str(os.environ.get("STRIKING_MODE", "0")).lower() in {"1", "true", "yes", "on"}
            )
            self.uncaged_mode = bool(uncaged_active)
            symbol_cache_key = str(mt5_symbol).replace("/", "").upper()
            fill_modes = []
            if uncaged_active:
                # Sunday pre-flight hard-lock requested by operator.
                fill_modes = [self._default_fill_mode]
                self.logger.critical(
                    f"[PRE_FLIGHT_LOCKED] {symbol} | Filling mode {self._default_fill_mode} forced. Fast-route active."
                )
            else:
                cached_mode = self._fill_mode_cache.get(symbol_cache_key, self._confirmed_fill_mode)
                if cached_mode is None:
                    cached_mode = self._default_fill_mode
                if cached_mode is not None:
                    # Prioritise the cached winner to the front
                    fill_modes.append(cached_mode)
                    self.logger.debug(
                        f"[FILL_CACHE] {symbol} | Using cached fill mode {cached_mode} first."
                    )

                filling_flags = getattr(symbol_info, 'filling_mode', 0)
                if mt5.ORDER_FILLING_RETURN not in fill_modes:
                    fill_modes.append(mt5.ORDER_FILLING_RETURN)
                if filling_flags & 1 and mt5.ORDER_FILLING_IOC not in fill_modes:
                    fill_modes.append(mt5.ORDER_FILLING_IOC)
                if filling_flags & 2 and mt5.ORDER_FILLING_FOK not in fill_modes:
                    fill_modes.append(mt5.ORDER_FILLING_FOK)
                if mt5.ORDER_FILLING_IOC not in fill_modes:
                    fill_modes.append(mt5.ORDER_FILLING_IOC)
                if mt5.ORDER_FILLING_FOK not in fill_modes:
                    fill_modes.append(mt5.ORDER_FILLING_FOK)

            last_result   = None
            placed_ticket = None

            for idx, mode in enumerate(fill_modes):
                try:
                    request["type_filling"] = mode
                    if self.uncaged_mode:
                        request["volume"] = max(float(request.get("volume", 0.0)), 0.05)
                    self.logger.info(
                        f"[ORDER_EXECUTION] {symbol} | fill_mode {idx+1}/{len(fill_modes)}: {mode} | "
                        f"SL={request.get('sl', 'NONE')} TP={request.get('tp', 'NONE')}"
                    )

                    result      = mt5.order_send(request)
                    last_result = result

                    if result is None:
                        self.logger.warning(
                            f"[BROKER_TIMEOUT] order_send returned None for {symbol} mode {mode}. Retrying..."
                        )
                        await asyncio.sleep(0.5)
                        continue

                    if int(getattr(result, "retcode", -1)) == market_closed_retcode:
                        msg = f"MARKET_CLOSED: {result.retcode} - {result.comment}"
                        self.logger.warning(
                            f"[ORDER_DEFERRED_MARKET_CLOSED] {symbol} | {msg} | "
                            "Order placement deferred until market reopens."
                        )
                        raise BrokerAPIError(msg)

                    if result.retcode == mt5.TRADE_RETCODE_DONE:
                        placed_ticket = str(result.order)
                        
                        # ===== TRANSACTIONAL EXECUTION WRAPPER =====
                        # [CRITICAL] Synchronously persist ticket to disk IN THIS THREAD
                        # before any other processing. This prevents orphaned positions.
                        direction_label = "BUY" if order_type == mt5.ORDER_TYPE_BUY else "SELL"
                        persist_ok = self._sync_ticket_to_disk(
                            ticket_id=placed_ticket,
                            symbol=mt5_symbol,
                            direction=direction_label,
                            entry_price=target_price,
                            stop_loss=validated_sl if validated_sl else 0.0,
                            take_profit=validated_tp if validated_tp else 0.0
                        )
                        if not persist_ok:
                            self.logger.critical(
                                f"[ORDER_EXECUTION_WARNING] Ticket {placed_ticket} obtained but "
                                f"persistence to disk FAILED. Position may become orphaned."
                            )
                        # ============================================
                        
                        # ===== IMPROVEMENT #2: CACHE THE WINNING FILL MODE =====
                        if self._confirmed_fill_mode != mode or self._fill_mode_cache.get(symbol_cache_key) != mode:
                            self.logger.info(
                                f"[FILL_CACHE] {symbol} | Caching successful fill mode {mode} "
                                f"(previous: {self._confirmed_fill_mode}). Future orders will use this first."
                            )
                            self._confirmed_fill_mode = mode
                            self._fill_mode_cache[symbol_cache_key] = mode
                            self._persist_fill_mode_cache()
                        
                        self.logger.info(
                            f"[ORDER_EXECUTION] {symbol} | FILLED | ticket={placed_ticket} | mode={mode}"
                        )
                        break

                    # AutoTrading disabled â€” fatal
                    if result.retcode == 10027:
                        self.logger.error(
                            "CRITICAL: 'Algorithmic Trading' is disabled in MT5 Terminal."
                        )
                        raise BrokerAPIError(f"AutoTrading disabled: {result.retcode}")

                    # Invalid stops (10016) â€” strip SL/TP, retry, then reattach via modify
                    if result.retcode == 10016:
                        raise BrokerAPIError(
                            f"SLTP_PREFLIGHT_REJECTED: {symbol} | retcode 10016 invalid stops on protected order"
                        )

                    # Unsupported filling â€” try next
                    if result.retcode == 10030:
                        self.logger.warning(f"Filling mode {mode} unsupported (10030), trying next...")
                        continue

                    self.logger.warning(
                        f"Order failed mode {mode} (retcode {result.retcode}: {result.comment}), trying next..."
                    )
                    continue

                except BrokerAPIError:
                    raise
                except Exception as e:
                    self.logger.warning(f"Error with filling mode {mode}: {type(e).__name__}: {e}, trying next...")
                    continue

            # â”€â”€ Check we actually got a ticket â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            if placed_ticket is None:
                err_desc = (
                    f"{last_result.retcode} - {last_result.comment}"
                    if last_result else "all attempts returned None"
                )
                if "10018" in err_desc or "market closed" in str(err_desc).lower():
                    raise BrokerAPIError(f"MARKET_CLOSED: {err_desc}")
                raise BrokerAPIError(f"Order failed after all fill modes: {err_desc}")

            # â”€â”€ Post-fill: verify SL/TP are live on the server â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            # Give MT5 a brief moment to register the position
            await asyncio.sleep(0.3)
            try:
                filled_positions = mt5.positions_get(ticket=int(placed_ticket))
                pos_to_check = filled_positions[0] if filled_positions and len(filled_positions) > 0 else None

                # NOTE: after a DEAL, the position ticket often matches the order ticket
                # but sometimes differs.  If not found by ticket, try the most recent.
                if pos_to_check is None:
                    all_pos = mt5.positions_get(symbol=mt5_symbol)
                    if all_pos:
                        pos_to_check = max(all_pos, key=lambda p: p.time)

                sl_live = pos_to_check.sl if pos_to_check else None
                tp_live = pos_to_check.tp if pos_to_check else None
                pos_ticket = str(pos_to_check.ticket) if pos_to_check else placed_ticket

                stops_ok = (
                    sl_live is not None and sl_live != 0.0 and
                    tp_live is not None and tp_live != 0.0
                )

                if not stops_ok:
                    # Stops missing â€” issue immediate follow-up modify
                    self.logger.error(
                        f"[ORDER_EXECUTION] {symbol} | ticket={pos_ticket} | "
                        f"Stops NOT live after fill (SL={sl_live}, TP={tp_live}). "
                        f"Issuing TRADE_ACTION_SLTP follow-up..."
                    )
                    if validated_sl and validated_tp:
                        normalized_sl = self._normalize_price(mt5_symbol, validated_sl)
                        normalized_tp = self._normalize_price(mt5_symbol, validated_tp)
                        attach_ok = False
                        for attach_attempt in range(1, 4):
                            modify_request = {
                                "action": mt5.TRADE_ACTION_SLTP,
                                "position": int(pos_ticket),
                                "symbol": mt5_symbol,
                                "sl": normalized_sl,
                                "tp": normalized_tp,
                            }
                            mod_result = mt5.order_send(modify_request)
                            if mod_result and mod_result.retcode == mt5.TRADE_RETCODE_DONE:
                                attach_ok = True
                                self.logger.info(
                                    f"[ORDER_EXECUTION] {symbol} | ticket={pos_ticket} | "
                                    f"Follow-up SLTP ATTACHED ✅ | attempt={attach_attempt}/3 | "
                                    f"SL={format_float(normalized_sl, f'.{digits}f')} "
                                    f"TP={format_float(normalized_tp, f'.{digits}f')} | "
                                    f"BrokerValidation=OK"
                                )
                                break
                            retcode = mod_result.retcode if mod_result else 'None'
                            comment = mod_result.comment if mod_result else 'timeout'
                            self.logger.warning(
                                f"[ORDER_EXECUTION] {symbol} | ticket={pos_ticket} | "
                                f"SLTP attach failed attempt {attach_attempt}/3: retcode={retcode} comment={comment}. Retrying in 1s..."
                            )
                            await asyncio.sleep(1.0)

                        if not attach_ok:
                            self.logger.error(
                                f"[ORDER_EXECUTION] SLTP_NOT_ATTACHED_ABORTED_TRADE | "
                                f"{symbol} | ticket={pos_ticket} | "
                                f"Follow-up SLTP modify FAILED after 3 attempts | "
                                f"SL={format_float(normalized_sl, f'.{digits}f')} "
                                f"TP={format_float(normalized_tp, f'.{digits}f')} | "
                                f"Initiating emergency close to prevent naked risk."
                            )
                            close_ok = await self.close_position(str(pos_ticket))
                            if close_ok:
                                raise BrokerAPIError(
                                    f"SLTP_ATTACH_FAILED_CLOSED: ticket={pos_ticket} closed after 3 failed attach attempts"
                                )
                            raise BrokerAPIError(
                                f"SLTP_ATTACH_FAILED_UNCLOSED: ticket={pos_ticket} close failed after 3 failed attach attempts"
                            )
                    else:
                        self.logger.error(
                            f"[ORDER_EXECUTION] SLTP_NOT_ATTACHED_ABORTED_TRADE | "
                            f"{symbol} | ticket={pos_ticket} | "
                            f"No valid SL/TP values available for follow-up attach. "
                            f"UNPROTECTED POSITION â€” manual intervention required."
                        )
                else:
                    self.logger.info(
                        f"[ORDER_EXECUTION] {symbol} | ticket={pos_ticket} | "
                        f"Stops CONFIRMED live âœ… | "
                        f"SL={format_float(sl_live, f'.{digits}f')} "
                        f"TP={format_float(tp_live, f'.{digits}f')} | "
                        f"BrokerValidation=OK"
                    )

            except Exception as verify_err:
                self.logger.error(
                    f"[ORDER_EXECUTION] {symbol} | ticket={placed_ticket} | "
                    f"Post-fill stop verification failed: {verify_err}. "
                    f"Trade protection could not be verified."
                )
                raise BrokerAPIError(
                    f"SLTP_VERIFICATION_FAILED: {symbol} | ticket={placed_ticket} | {verify_err}"
                )

            return placed_ticket

        except Exception as e:
            self.logger.error(f"Error placing order: {e}")
            if "MARKET_CLOSED" in str(e) or "10018" in str(e) or "market closed" in str(e).lower():
                raise BrokerAPIError(f"MARKET_CLOSED: {e}")
            raise BrokerAPIError(f"Failed to place order: {e}")
    
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an order"""
        if not self.connected:
            raise BrokerAPIError("Not connected to MT5")
        
        try:
            # Get order info
            order = mt5.order_get(ticket=int(order_id))
            if order is None:
                raise BrokerAPIError(f"Order {order_id} not found")
            
            # Prepare cancel request
            request = {
                "action": mt5.TRADE_ACTION_REMOVE,
                "order": int(order_id),
            }
            
            # Send cancel request
            result = mt5.order_send(request)
            
            # PATCH: Guard against NoneType from broker timeout
            if result is None:
                self.logger.warning(f"[BROKER_TIMEOUT] order_send returned None during cancel for {order_id}")
                raise BrokerAPIError(f"Cancel failed: Broker returned None (timeout)")
            
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                raise BrokerAPIError(f"Cancel failed: {result.retcode} - {result.comment}")
            
            self.logger.info(f"Order {order_id} cancelled successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Error cancelling order {order_id}: {e}")
            raise BrokerAPIError(f"Failed to cancel order: {e}")
    
    async def get_orders(self) -> List[Order]:
        """Get all pending orders"""
        if not self.connected:
            raise BrokerAPIError("Not connected to MT5")
        
        try:
            orders = mt5.orders_get()
            order_list = []
            
            if orders:
                for order in orders:
                    order_list.append(Order(
                        order_id=str(order.ticket),
                        symbol=order.symbol,
                        direction=Direction.LONG if order.type == mt5.ORDER_TYPE_BUY else Direction.SHORT,
                        size=order.volume_initial,
                        price=order.price_open,
                        status=OrderStatus.PENDING,
                        timestamp=datetime.fromtimestamp(order.time_setup, tz=timezone.utc)
                    ))
            
            return order_list
            
        except Exception as e:
            self.logger.error(f"Error getting orders: {e}")
            raise BrokerAPIError(f"Failed to get orders: {e}")
    
    async def get_positions(self) -> List[Position]:
        """Get all open positions"""
        if not self.connected:
            raise BrokerAPIError("Not connected to MT5")
        
        try:
            positions = mt5.positions_get()
            position_list = []
            
            if positions:
                for pos in positions:
                    try:
                        # Map MT5 symbol format back to standard format
                        standard_symbol = getattr(self, 'reverse_symbol_mapping', {}).get(pos.symbol, pos.symbol)
                        direction = Direction.LONG if pos.type == mt5.POSITION_TYPE_BUY else Direction.SHORT
                        symbol_info = mt5.symbol_info(pos.symbol)
                        tick_size = float(getattr(symbol_info, "trade_tick_size", 0.0) or 0.0) if symbol_info else 0.0
                        tick_value = float(getattr(symbol_info, "trade_tick_value", 0.0) or 0.0) if symbol_info else 0.0
                        pnl_for_model = float(getattr(pos, "profit", 0.0) or 0.0) + float(getattr(pos, "swap", 0.0) or 0.0)
                        
                        # Convert opened_at directly using MT5's native Unix timestamp (already UTC)
                        # Note: pos.time from mt5.positions_get() is a UTC-based Unix timestamp
                        # Do NOT apply broker timezone offset - it is the source of truth
                        raw_normalized_opened_at = normalize_mt5_timestamp_to_utc(pos.time)
                        
                        # ===== ISSUE #1 FIX: Apply hard -3 hour timezone offset for broker UTC+3 =====
                        # Broker is UTC+3 (19:00), local is UTC+0. Apply -3 hour correction.
                        # First detect the offset dynamically, then use hard fallback if not detected.
                        self._detect_broker_timezone_offset(raw_normalized_opened_at)
                        
                        # Apply timezone offset correction
                        corrected_opened_at = raw_normalized_opened_at
                        # Use detected offset, or fallback to hard-coded -3 hours
                        offset_to_apply = self._detected_broker_offset_hours if self._detected_broker_offset_hours is not None else 3.0
                        if offset_to_apply > 0:
                            # Subtract the offset to shift timestamp back to correct UTC
                            corrected_opened_at = raw_normalized_opened_at - timedelta(hours=offset_to_apply)
                            if corrected_opened_at != raw_normalized_opened_at:
                                self.logger.debug(
                                    f"[BROKER_TZ_APPLIED] Ticket={str(getattr(pos, 'ticket', ''))} | "
                                    f"raw={raw_normalized_opened_at.isoformat()} | "
                                    f"corrected={corrected_opened_at.isoformat()} | "
                                    f"offset={offset_to_apply:.1f}h (detected={self._detected_broker_offset_hours})"
                                )
                        
                        # ===== ISSUE #1 FIX: Clear warned tickets at sync start (first position in this method too) =====
                        if not self._warned_time_clamp_tickets_this_sync:
                            self._warned_time_clamp_tickets_this_sync.clear()
                        
                        ticket_str = str(getattr(pos, "ticket", ""))
                        normalized_opened_at = clamp_future_position_time(corrected_opened_at)
                        if normalized_opened_at != corrected_opened_at:
                            # ===== ISSUE #1 FIX: Only warn once per ticket per sync cycle =====
                            if ticket_str not in self._warned_time_clamp_tickets_this_sync:
                                self.logger.warning(
                                    "[MT5_POSITION_TIME_CLAMP] Ticket=%s | raw_pos_time=%s | normalized_opened_at=%s | clamped_to=%s",
                                    ticket_str,
                                    str(getattr(pos, "time", "")),
                                    corrected_opened_at.isoformat(),
                                    normalized_opened_at.isoformat(),
                                )
                                self._warned_time_clamp_tickets_this_sync.add(ticket_str)

                        position_list.append(Position(
                            position_id=str(pos.ticket),
                            symbol=standard_symbol,
                            direction=direction,
                            quantity=pos.volume,
                            entry_price=pos.price_open,
                            current_price=pos.price_current,
                            unrealized_pnl=pnl_for_model,
                            stop_loss=pos.sl if pos.sl != 0.0 else None,
                            take_profit=pos.tp if pos.tp != 0.0 else None,
                            opened_at=normalized_opened_at,
                            magic=pos.magic,
                            swap=float(getattr(pos, "swap", 0.0) or 0.0),
                            commission=float(getattr(pos, "commission", 0.0) or 0.0),
                            tick_value=tick_value if tick_value > 0.0 else None,
                            tick_size=tick_size if tick_size > 0.0 else None,
                            # ===== FIX #1: SET FLAG TO PREVENT RECALCULATION =====
                            time_normalized=True
                        ))
                    except Exception as pos_err:
                        self.logger.error(f"Error processing position {pos.ticket}: {pos_err}")
                        try:
                            ticket_id = str(getattr(pos, "ticket", ""))
                            live_pos = mt5.positions_get(ticket=int(ticket_id)) if ticket_id else None
                            if not live_pos:
                                self._ghost_ticket_ids.add(ticket_id)
                                self.logger.warning(
                                    f"[GHOST_PURGE_FLAG] Ticket {ticket_id} failed processing and is absent in MT5. "
                                    f"Flagged for forced registry purge."
                                )
                        except Exception:
                            pass
                        continue
            
            return position_list
            
        except Exception as e:
            self.logger.error(f"Error getting positions: {e}")
            raise BrokerAPIError(f"Failed to get positions: {e}")
    
    async def modify_order(self, order_id: str, sl: float = None, tp: float = None) -> bool:
        """Modify position SL/TP with validation"""
        global mt5  # ===== FIX: SAFETY PASS - Ensure global mt5 is used =====
        self.last_modify_result = {}
        
        if not self.connected:
            raise BrokerAPIError("Not connected to MT5")
        
        try:
            position = mt5.positions_get(ticket=int(order_id))
            if not position:
                raise BrokerAPIError(f"Position {order_id} not found for modification")
            
            pos = position[0]
            entry_price = pos.price_open
            position_type = pos.type  # 0=BUY, 1=SELL
            pip_value = PipStandardizer.get_pip_value_for_pair(pos.symbol)
            
            # === FIX #2: Pre-check to prevent MT5 Error 10025 (no changes) ===
            # Get symbol info for broker minimum points (using global mt5)
            symbol_info = mt5.symbol_info(pos.symbol)
            if symbol_info:
                tick_size = max(
                    float(getattr(symbol_info, "trade_tick_size", 0.0) or 0.0),
                    float(getattr(symbol_info, "point", 0.0) or 0.0),
                )
                stops_step = float(getattr(symbol_info, "trade_stops_level", 0.0) or 0.0) * float(
                    getattr(symbol_info, "point", 0.0) or 0.0
                )
                min_points = max(tick_size, stops_step)
                
                # Check if proposed SL change meets minimum threshold
                if sl is not None and pos.sl and pos.sl != 0:
                    sl_change = abs(sl - pos.sl)
                    if sl_change < min_points:
                        self._record_modify_result(
                            order_id=order_id,
                            symbol=pos.symbol,
                            success=False,
                            reason="MIN_SL_CHANGE",
                            comment="SL change below broker minimum step",
                            requested_sl=sl,
                            requested_tp=tp,
                        )
                        self.logger.debug(
                            f"[FIX_10025_SKIP] {pos.symbol} ticket {order_id} | "
                            f"SL change {sl_change:.6f} < minimum {min_points:.6f}. Skipping modification."
                        )
                        return False
                
                # Check if proposed TP change meets minimum threshold
                if tp is not None and pos.tp and pos.tp != 0:
                    tp_change = abs(tp - pos.tp)
                    if tp_change < min_points:
                        self._record_modify_result(
                            order_id=order_id,
                            symbol=pos.symbol,
                            success=False,
                            reason="MIN_TP_CHANGE",
                            comment="TP change below broker minimum step",
                            requested_sl=sl,
                            requested_tp=tp,
                        )
                        self.logger.debug(
                            f"[FIX_10025_SKIP] {pos.symbol} ticket {order_id} | "
                            f"TP change {tp_change:.6f} < minimum {min_points:.6f}. Skipping modification."
                        )
                        return False
            
            # Determine final SL and TP values
            final_sl = sl if sl is not None else pos.sl
            final_tp = tp if tp is not None else pos.tp
            final_sl = self._normalize_price(pos.symbol, final_sl) if final_sl is not None else None
            final_tp = self._normalize_price(pos.symbol, final_tp) if final_tp is not None else None

            if sl is not None or tp is not None:
                proposal = ModificationProposal(
                    ticket=int(order_id),
                    symbol=pos.symbol,
                    current_sl=float(pos.sl or 0.0),
                    proposed_sl=float(final_sl or 0.0),
                    current_tp=float(pos.tp or 0.0),
                    proposed_tp=float(final_tp or 0.0),
                    modification_type=(
                        ModificationType.BOTH if sl is not None and tp is not None
                        else ModificationType.STOP_LOSS if sl is not None
                        else ModificationType.TAKE_PROFIT
                    ),
                    reason="BROKER_MODIFY",
                )
                should_send, block_reason, block_details = self.modification_gate.evaluate_modification(
                    proposal,
                    pip_value=pip_value,
                )
                if not should_send:
                    self._record_modify_result(
                        order_id=order_id,
                        symbol=pos.symbol,
                        success=False,
                        reason=block_reason or "MODIFICATION_GUARD",
                        comment=str(block_details or ""),
                        requested_sl=final_sl,
                        requested_tp=final_tp,
                    )
                    self.logger.debug(
                        "[MODIFICATION_GUARD] %s ticket %s blocked: %s | %s",
                        pos.symbol,
                        order_id,
                        block_reason,
                        block_details,
                    )
                    return False
            
            # Validate stops
            errors = []
            
            # Check for NaN or 0 values
            if final_sl is not None and (final_sl == 0 or final_sl != final_sl):  # NaN check
                final_sl = 0
            if final_tp is not None and (final_tp == 0 or final_tp != final_tp):  # NaN check
                final_tp = 0
            
            # Determine current price for validation
            tick = mt5.symbol_info_tick(pos.symbol)
            current_bid = tick.bid if tick else pos.price_current
            current_ask = tick.ask if tick else pos.price_current
            current_bid = float(current_bid or 0.0)
            current_ask = float(current_ask or 0.0)
            point = float(getattr(symbol_info, "point", 0.0) or 0.0) if symbol_info else 0.0
            min_distance_points = 0.0
            if symbol_info:
                min_distance_points = max(
                    float(getattr(symbol_info, "trade_stops_level", 0) or 0),
                    float(getattr(symbol_info, "trade_freeze_level", 0) or 0),
                )
            min_distance_price = (
                min_distance_points * point
            ) + (0.2 * pip_value)
            freeze_buffer_price = 2.0 * point
            abort_distance_price = min_distance_price + freeze_buffer_price

            if final_sl not in (None, 0):
                if position_type == 0:
                    if float(final_sl) >= (current_bid - abort_distance_price):
                        self._record_modify_result(
                            order_id=order_id,
                            symbol=pos.symbol,
                            success=False,
                            reason="MOD_STALE",
                            comment="Aborting modification: Price too close to Freeze Zone.",
                            requested_sl=final_sl,
                            requested_tp=final_tp,
                        )
                        self.logger.warning(
                            "[MOD_STALE] Aborting modification: Price too close to Freeze Zone. %s ticket %s | LONG SL %.5f | boundary %.5f",
                            pos.symbol,
                            order_id,
                            float(final_sl),
                            float(current_bid - abort_distance_price),
                        )
                        return False
                else:
                    if float(final_sl) <= (current_ask + abort_distance_price):
                        self._record_modify_result(
                            order_id=order_id,
                            symbol=pos.symbol,
                            success=False,
                            reason="MOD_STALE",
                            comment="Aborting modification: Price too close to Freeze Zone.",
                            requested_sl=final_sl,
                            requested_tp=final_tp,
                        )
                        self.logger.warning(
                            "[MOD_STALE] Aborting modification: Price too close to Freeze Zone. %s ticket %s | SHORT SL %.5f | boundary %.5f",
                            pos.symbol,
                            order_id,
                            float(final_sl),
                            float(current_ask + abort_distance_price),
                        )
                        return False

            if final_tp not in (None, 0):
                if position_type == 0:
                    if float(final_tp) <= (current_bid + abort_distance_price):
                        self._record_modify_result(
                            order_id=order_id,
                            symbol=pos.symbol,
                            success=False,
                            reason="MOD_STALE",
                            comment="Aborting modification: Price too close to Freeze Zone.",
                            requested_sl=final_sl,
                            requested_tp=final_tp,
                        )
                        self.logger.warning(
                            "[MOD_STALE] Aborting modification: Price too close to Freeze Zone. %s ticket %s | LONG TP %.5f | boundary %.5f",
                            pos.symbol,
                            order_id,
                            float(final_tp),
                            float(current_bid + abort_distance_price),
                        )
                        return False
                else:
                    if float(final_tp) >= (current_ask - abort_distance_price):
                        self._record_modify_result(
                            order_id=order_id,
                            symbol=pos.symbol,
                            success=False,
                            reason="MOD_STALE",
                            comment="Aborting modification: Price too close to Freeze Zone.",
                            requested_sl=final_sl,
                            requested_tp=final_tp,
                        )
                        self.logger.warning(
                            "[MOD_STALE] Aborting modification: Price too close to Freeze Zone. %s ticket %s | SHORT TP %.5f | boundary %.5f",
                            pos.symbol,
                            order_id,
                            float(final_tp),
                            float(current_ask - abort_distance_price),
                        )
                        return False

            if final_sl not in (None, 0):
                if position_type == 0:
                    legal_sl = self._normalize_price(pos.symbol, current_bid - min_distance_price)
                    if final_sl >= legal_sl:
                        self.logger.warning(
                            "[MODIFY_STOPS_CLAMP] %s ticket %s | Proposed LONG SL %.5f inside broker stops/freeze zone. Clamping to %.5f.",
                            pos.symbol,
                            order_id,
                            float(final_sl),
                            float(legal_sl),
                        )
                        final_sl = legal_sl
                else:
                    legal_sl = self._normalize_price(pos.symbol, current_ask + min_distance_price)
                    if final_sl <= legal_sl:
                        self.logger.warning(
                            "[MODIFY_STOPS_CLAMP] %s ticket %s | Proposed SHORT SL %.5f inside broker stops/freeze zone. Clamping to %.5f.",
                            pos.symbol,
                            order_id,
                            float(final_sl),
                            float(legal_sl),
                        )
                        final_sl = legal_sl

            # For LONG positions (BUY)
            if position_type == 0:
                if final_sl != 0:
                    if final_sl >= current_bid:
                        errors.append(f"Long: SL {format_float(final_sl, '.5f')} must be < current bid {format_float(current_bid, '.5f')}")
                if final_tp != 0:
                    if final_tp <= current_bid:
                        errors.append(f"Long: TP {format_float(final_tp, '.5f')} must be > current bid {format_float(current_bid, '.5f')}")
            
            # For SHORT positions (SELL)
            else:
                if final_sl != 0:
                    if final_sl <= current_ask:
                        errors.append(f"Short: SL {format_float(final_sl, '.5f')} must be > current ask {format_float(current_ask, '.5f')}")
                if final_tp != 0:
                    if final_tp >= current_ask:
                        errors.append(f"Short: TP {format_float(final_tp, '.5f')} must be < current ask {format_float(current_ask, '.5f')}")
            
            # Check if SL == TP (invalid)
            if final_sl != 0 and final_tp != 0 and abs(final_sl - final_tp) < 0.00001:
                errors.append(f"SL {format_float(final_sl, '.5f')} and TP {format_float(final_tp, '.5f')} are too close or equal")
            
            if errors:
                error_msg = "; ".join(errors)
                self._record_modify_result(
                    order_id=order_id,
                    symbol=pos.symbol,
                    success=False,
                    reason="VALIDATION_ERROR",
                    comment=error_msg,
                    requested_sl=final_sl,
                    requested_tp=final_tp,
                )
                self.logger.warning(
                    f"Skipping modify order {order_id}: {error_msg} "
                    f"(Bid: {format_float(current_bid, '.5f')}, Ask: {format_float(current_ask, '.5f')}, Type: {'LONG' if position_type == 0 else 'SHORT'})"
                )
                return False
            
            request = {
                "action": mt5.TRADE_ACTION_SLTP,
                "position": int(order_id),
                "symbol": pos.symbol,
                "sl": final_sl,
                "tp": final_tp,
            }
            
            # PATCH: Retry loop with NoneType guard for broker timeout during SL/TP modification
            max_modify_attempts = 2
            for modify_attempt in range(max_modify_attempts):
                result = mt5.order_send(request)
                
                # Guard against NoneType from broker timeout
                if result is None:
                    self._record_modify_result(
                        order_id=order_id,
                        symbol=pos.symbol,
                        success=False,
                        reason="BROKER_TIMEOUT",
                        comment="order_send returned None during modify",
                        requested_sl=final_sl,
                        requested_tp=final_tp,
                    )
                    self.logger.warning(
                        f"[BROKER_TIMEOUT] order_send returned None during modify for {order_id} "
                        f"(attempt {modify_attempt+1}/{max_modify_attempts}). Retrying..."
                    )
                    await asyncio.sleep(0.5)
                    continue
                
                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    self._record_modify_result(
                        order_id=order_id,
                        symbol=pos.symbol,
                        success=True,
                        retcode=int(getattr(result, "retcode", 0)),
                        comment=str(getattr(result, "comment", "") or ""),
                        reason="TRADE_RETCODE_DONE",
                        requested_sl=final_sl,
                        requested_tp=final_tp,
                    )
                    return True
                else:
                    self._record_modify_result(
                        order_id=order_id,
                        symbol=pos.symbol,
                        success=False,
                        retcode=int(getattr(result, "retcode", -1)),
                        comment=str(getattr(result, "comment", "") or ""),
                        reason="ORDER_SEND_REJECTED",
                        requested_sl=final_sl,
                        requested_tp=final_tp,
                    )
                    self.logger.warning(
                        f"[MODIFY_RETRY] Modification attempt {modify_attempt+1} failed: "
                        f"{result.retcode} - {result.comment}"
                    )
                    if int(getattr(result, "retcode", -1)) in {10016, 10029}:
                        self.logger.warning(
                            "[MODIFY_DEFERRED] %s ticket %s | Broker stops/freeze zone still blocking SL/TP update. Will retry later.",
                            pos.symbol,
                            order_id,
                        )
                        return False
                    if modify_attempt < max_modify_attempts - 1:
                        await asyncio.sleep(0.3)
                        continue
                    raise BrokerAPIError(f"Modification failed: {result.retcode} - {result.comment}")
            
            # All attempts returned None
            self._record_modify_result(
                order_id=order_id,
                symbol=pos.symbol,
                success=False,
                reason="BROKER_TIMEOUT",
                comment=f"All {max_modify_attempts} modify attempts returned None",
                requested_sl=final_sl,
                requested_tp=final_tp,
            )
            self.logger.error(f"[BROKER_TIMEOUT] All {max_modify_attempts} modify attempts returned None for {order_id}")
            return False
            
        except Exception as e:
            self._record_modify_result(
                order_id=order_id,
                symbol=locals().get("pos", None).symbol if locals().get("pos", None) else str(order_id),
                success=False,
                reason="EXCEPTION",
                comment=str(e),
                requested_sl=sl,
                requested_tp=tp,
            )
            self.logger.error(f"Error modifying order {order_id}: {e}")
            raise BrokerAPIError(f"Failed to modify order: {e}")

    def is_modification_within_freeze_zone(self, order_id: str, sl: float = None, tp: float = None) -> tuple[bool, str]:
        try:
            position = mt5.positions_get(ticket=int(order_id))
            if not position:
                return False, "position_not_found"

            pos = position[0]
            symbol = str(getattr(pos, "symbol", "") or "")
            symbol_info = mt5.symbol_info(symbol)
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                return False, "tick_unavailable"

            point = float(getattr(symbol_info, "point", 0.0) or 0.0) if symbol_info else 0.0
            if point <= 0.0:
                return False, "point_unavailable"

            current_bid = float(getattr(tick, "bid", getattr(pos, "price_current", 0.0)) or 0.0)
            current_ask = float(getattr(tick, "ask", getattr(pos, "price_current", 0.0)) or 0.0)
            forbidden_points = max(
                float(getattr(symbol_info, "trade_stops_level", 0.0) or 0.0) if symbol_info else 0.0,
                float(getattr(symbol_info, "trade_freeze_level", 0.0) or 0.0) if symbol_info else 0.0,
            )
            abort_distance_price = (forbidden_points * point) + (2.0 * point)
            position_type = int(getattr(pos, "type", 0) or 0)

            if sl not in (None, 0):
                sl_value = float(sl or 0.0)
                if position_type == mt5.POSITION_TYPE_BUY and sl_value >= (current_bid - abort_distance_price):
                    return True, f"{symbol} ticket {order_id} long_sl {sl_value:.5f} near freeze boundary"
                if position_type != mt5.POSITION_TYPE_BUY and sl_value <= (current_ask + abort_distance_price):
                    return True, f"{symbol} ticket {order_id} short_sl {sl_value:.5f} near freeze boundary"

            if tp not in (None, 0):
                tp_value = float(tp or 0.0)
                if position_type == mt5.POSITION_TYPE_BUY and tp_value <= (current_bid + abort_distance_price):
                    return True, f"{symbol} ticket {order_id} long_tp {tp_value:.5f} near freeze boundary"
                if position_type != mt5.POSITION_TYPE_BUY and tp_value >= (current_ask - abort_distance_price):
                    return True, f"{symbol} ticket {order_id} short_tp {tp_value:.5f} near freeze boundary"

            return False, ""
        except Exception as exc:
            return False, f"freeze_zone_check_failed:{exc}"

    async def get_historical_data(self, symbol: str, timeframe: int, count: int) -> List[MarketData]:
        """Fetch historical data from MT5"""
        if not self.connected:
            raise BrokerAPIError("Not connected to MT5")
            
        try:
            mt5_symbol = self._normalize_mt5_symbol_name(symbol)
            
            # Map string timeframe to MT5 constant if necessary
            if isinstance(timeframe, str):
                tf_map = {
                    '1m': mt5.TIMEFRAME_M1, '5m': mt5.TIMEFRAME_M5, '15m': mt5.TIMEFRAME_M15,
                    '30m': mt5.TIMEFRAME_M30, '1h': mt5.TIMEFRAME_H1, '4h': mt5.TIMEFRAME_H4,
                    '1d': mt5.TIMEFRAME_D1, '1w': mt5.TIMEFRAME_W1, '1mn': mt5.TIMEFRAME_MN1
                }
                mapped_tf = tf_map.get(timeframe.lower())
                if mapped_tf is None:
                    self.logger.warning(f"Unknown timeframe string '{timeframe}', defaulting to H1")
                    mapped_tf = mt5.TIMEFRAME_H1
                timeframe = mapped_tf

            # Ensure symbol is selected and available in Market Watch
            if not mt5.symbol_select(mt5_symbol, True):
                error_code = mt5.last_error()
                self.logger.warning(f"Symbol {mt5_symbol} not in Market Watch, attempting to force select: {error_code}")
            
            requested_count = max(int(count or 0), 600)

            # ===== ISSUE #2 FIX: Use robust data-fetching wrapper with retry logic =====
            # This wrapper forces MT5 to load history by requesting larger chunks
            # and retrying with sleep delays if insufficient bars are returned
            rates = await asyncio.to_thread(
                fetch_mt5_rates_with_retry,
                mt5_symbol,
                timeframe,
                requested_count,
                max_retries=3,
                logger=self.logger
            )

            if len(rates) < requested_count:
                fallback_count = max(requested_count * 5, 5000)
                self.logger.warning(
                    "[MT5_HISTORY_SHORTFALL] %s | Requested %d bars on timeframe %s but received %d. "
                    "Retrying with max-history fallback (%d bars).",
                    symbol,
                    requested_count,
                    timeframe,
                    len(rates),
                    fallback_count,
                )
                try:
                    fallback_rates = await asyncio.to_thread(
                        mt5.copy_rates_from_pos,
                        mt5_symbol,
                        timeframe,
                        0,
                        fallback_count,
                    )
                    if fallback_rates is not None and len(fallback_rates) > len(rates):
                        rates = fallback_rates
                        self.logger.info(
                            "[MT5_HISTORY_FALLBACK] %s | Max-history fetch expanded dataset to %d bars on timeframe %s.",
                            symbol,
                            len(rates),
                            timeframe,
                        )
                except Exception as fallback_err:
                    self.logger.warning(
                        "[MT5_HISTORY_FALLBACK_WARN] %s | Max-history fetch failed on timeframe %s: %s",
                        symbol,
                        timeframe,
                        fallback_err,
                    )
                
            market_data_list = []
            symbol_info = mt5.symbol_info(mt5_symbol)
            
            # Validate bid/ask from symbol info (strict mode: no OHLC estimate)
            bid = symbol_info.bid if symbol_info else None
            ask = symbol_info.ask if symbol_info else None
            if not symbol_info or bid is None or ask is None or bid >= ask:
                # Fallback to live tick if symbol_info is stale or zero-spread.
                tick = mt5.symbol_info_tick(mt5_symbol)
                if tick is not None and self._is_tick_fresh(tick, max_age_seconds=60):
                    bid = tick.bid
                    ask = tick.ask
                # If still equal, apply a minimal spread floor from broker settings.
                if symbol_info and bid is not None and ask is not None and bid >= ask and bid > 0:
                    point = float(getattr(symbol_info, "point", 0.0) or 0.0)
                    spread_points = float(getattr(symbol_info, "spread", 0.0) or 0.0)
                    min_spread = max(point, spread_points * point)
                    if min_spread > 0:
                        ask = bid + min_spread
                if not symbol_info or bid is None or ask is None or bid >= ask:
                    raise BrokerAPIError(
                        f"Invalid symbol info for {symbol}: bid={bid}, ask={ask}. "
                        "OHLC estimates are disabled."
                    )
            
            for rate in rates:
                # Use symbol_info bid/ask (required)
                market_bid = bid
                market_ask = ask
                market_spread = ask - bid
                
                market_data_list.append(MarketData(
                    symbol=symbol,
                    timestamp=datetime.fromtimestamp(rate['time'], tz=timezone.utc),
                    open=rate['open'],
                    high=rate['high'],
                    low=rate['low'],
                    close=rate['close'],
                    volume=int(rate['tick_volume']),
                    bid=market_bid,
                    ask=market_ask,
                    spread=market_spread
                ))
            return market_data_list
        except Exception as e:
            self.logger.error(f"Error getting historical data for {symbol}: {e}")
            raise BrokerAPIError(f"Failed to get historical data: {e}")

    async def close_position(self, position_id: str, volume: Optional[float] = None) -> bool:
        """Close a specific position (full or partial)"""
        if not self.connected:
            raise BrokerAPIError("Not connected to MT5")
        
        try:
            market_closed_retcode = int(getattr(mt5, "TRADE_RETCODE_MARKET_CLOSED", 10018))
            position = mt5.positions_get(ticket=int(position_id))
            if not position:
                raise BrokerAPIError(f"Position {position_id} not found")
            
            pos = position[0]

            # Use provided volume or full position volume
            close_volume = float(volume) if volume is not None else float(pos.volume)
            # Ensure volume is within valid bounds (not exceeding position size)
            close_volume = min(close_volume, float(pos.volume))

            close_price = mt5.symbol_info_tick(pos.symbol).bid if pos.type == mt5.POSITION_TYPE_BUY else mt5.symbol_info_tick(pos.symbol).ask
            close_price = self._normalize_price(pos.symbol, close_price)
            close_symbol_info = mt5.symbol_info(pos.symbol)
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": pos.symbol,
                "volume": close_volume,
                "type": mt5.ORDER_TYPE_SELL if pos.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY,
                "position": int(position_id),
                "price": close_price,
                "deviation": 20,
                "magic": 234000,
                "comment": "Close AI",
                "type_time": mt5.ORDER_TIME_GTC,
            }

            self.logger.info(
                "[ORDER_CLOSE] %s | Attempting close with preferred fill mode %s and fallback enabled.",
                position_id,
                self._default_fill_mode,
            )
            result, _ = await self._send_order_with_fill_mode_fallback(
                symbol=pos.symbol,
                mt5_symbol=pos.symbol,
                symbol_info=close_symbol_info,
                request=request,
                order_type=request["type"],
                target_price=float(close_price),
                validated_sl=None,
                validated_tp=None,
                market_closed_retcode=market_closed_retcode,
                allow_fallbacks=True,
                persist_ticket=False,
            )

            if result is None:
                self.logger.warning(f"[BROKER_TIMEOUT] order_send returned None during close for {position_id}")
                raise BrokerAPIError("Close failed: Broker returned None (timeout)")

            if int(getattr(result, "retcode", -1)) == market_closed_retcode:
                self.logger.warning(
                    f"[CLOSE_DEFERRED_MARKET_CLOSED] Position {position_id} | "
                    f"Retcode={result.retcode} | Comment={result.comment} | "
                    "Market session closed. Close request deferred until market reopens."
                )
                return False

            if result.retcode == mt5.TRADE_RETCODE_DONE:
                self.logger.info(f"Successfully closed position {position_id}")
                return True

            raise BrokerAPIError(f"Close failed: Retcode: {result.retcode} - {result.comment}")
            
        except Exception as e:
            err_text = str(e)
            if "10018" in err_text or "market closed" in err_text.lower():
                self.logger.warning(
                    f"[CLOSE_DEFERRED_MARKET_CLOSED] Position {position_id} | {err_text} | "
                    "Close request deferred until market reopens."
                )
                return False
            self.logger.error(f"Error closing position {position_id}: {e}")
            raise BrokerAPIError(f"Failed to close position: {e}")

    async def get_order_status(self, order_id: str) -> Optional[OrderStatus]:
        """Get current status of an order (Pending, Filled, Cancelled)"""
        if not self.connected:
            return None
        
        try:
            # Extract numeric ticket from various order ID formats:
            # - 'order_1768188609' -> 1768188609
            # - 'close_54629372524_1768198168' -> 1768198168 (use last number)
            # - '1768188609' -> 1768188609 (already numeric)
            
            if isinstance(order_id, str):
                # Handle 'close_<position>_<order_id>' format
                if order_id.startswith('close_'):
                    # Extract the order_id part (last number after final underscore)
                    parts = order_id.split('_')
                    if len(parts) >= 3:
                        ticket = int(parts[-1])  # Get last part
                    else:
                        # Fallback: try to extract any number
                        import re
                        numbers = re.findall(r'\d+', order_id)
                        ticket = int(numbers[-1]) if numbers else None
                        if ticket is None:
                            self.logger.warning(f"Could not extract order ID from format: {order_id}")
                            return None
                # Handle 'order_<order_id>' format
                elif order_id.startswith('order_'):
                    order_str = order_id.replace('order_', '').split('_')[0]
                    ticket = int(order_str)
                # Handle plain numeric format
                else:
                    ticket = int(order_id)
            else:
                ticket = int(order_id)
            
            # 1. Check Pending Orders
            orders = mt5.orders_get(ticket=ticket)
            if orders:
                return OrderStatus.PENDING
                
            # 2. Check Positions (Active/Filled)
            positions = mt5.positions_get(ticket=ticket)
            if positions:
                return OrderStatus.FILLED
                
            # 3. Check History (Closed/Cancelled/Rejected)
            # Fetch history from 1970 to now
            history = mt5.history_orders_get(ticket=ticket)
            if history:
                state = history[0].state
                if state == mt5.ORDER_STATE_CANCELED:
                    return OrderStatus.CANCELLED
                elif state == mt5.ORDER_STATE_FILLED:
                    return OrderStatus.FILLED
                elif state == mt5.ORDER_STATE_REJECTED:
                    return OrderStatus.REJECTED
                elif state == mt5.ORDER_STATE_EXPIRED:
                    return OrderStatus.CANCELLED
                else:
                    return OrderStatus.PENDING
            
            # Not found
            return None
            
        except Exception as e:
            self.logger.error(f"Error getting order status for {order_id}: {e}")
            return None
            


    async def get_position_exit_reason(self, position_id: str) -> Optional[Dict[str, Any]]:
        """
        Check history deals for a specific position to determine if it was hit by SL or TP.
        Returns structured exit metadata with realized PnL, or None.
        """
        if not self.connected:
            return None
            
        try:
            # MT5 may delay writing deals to history. Try up to 3 times with small backoff.
            for attempt in range(3):
                # Fetch history deals for this position
                deals = mt5.history_deals_get(position=int(position_id))
                if deals:
                    deal_entry_out = int(getattr(mt5, "DEAL_ENTRY_OUT", 1))
                    # Look for the deal that closed the position (DEAL_ENTRY_OUT)
                    # and check its reason or comment
                    for deal in deals:
                        if int(getattr(deal, "entry", -1)) == deal_entry_out:
                            reason = self._mt5_deal_reason_name(getattr(deal, "reason", -1))
                            profit = float(getattr(deal, "profit", 0.0) or 0.0)
                            swap = float(getattr(deal, "swap", 0.0) or 0.0)
                            commission = float(getattr(deal, "commission", 0.0) or 0.0)
                            fee = float(getattr(deal, "fee", 0.0) or 0.0)
                            realized_pnl = profit + swap + commission + fee

                            def _exit_payload(resolved_reason: str) -> Dict[str, Any]:
                                return {
                                    "reason": resolved_reason,
                                    "deal_reason_code": int(getattr(deal, "reason", -1)),
                                    "realized_pnl": realized_pnl,
                                    "exit_price": float(getattr(deal, "price", 0.0) or 0.0),
                                    "closed_at": datetime.fromtimestamp(
                                        getattr(deal, "time", 0),
                                        tz=timezone.utc,
                                    ),
                                    "comment": str(getattr(deal, "comment", "") or ""),
                                    "ticket": str(getattr(deal, "ticket", "")),
                                }

                            if reason in {"SL_HIT", "TP_HIT", "STOP_OUT", "MANUAL_CLOSE"}:
                                return _exit_payload(reason)

                            # Fallback to comment checking when broker leaves reason as 0/unknown.
                            comment = str(getattr(deal, "comment", "") or "").lower()
                            if "close ai" in comment:
                                return _exit_payload("MANUAL_CLOSE")
                            if " sl" in f" {comment}" or "[sl]" in comment or "stop loss" in comment:
                                return _exit_payload("SL_HIT")
                            if " tp" in f" {comment}" or "[tp]" in comment or "take profit" in comment:
                                return _exit_payload("TP_HIT")
                            if "stopout" in comment or "stop out" in comment or "[so]" in comment:
                                return _exit_payload("STOP_OUT")
                                
                            self.logger.info(
                                "Closed deal for %s found but unknown reason/comment. Reason: %s, Comment: %s",
                                position_id,
                                getattr(deal, "reason", None),
                                getattr(deal, "comment", ""),
                            )
                            return _exit_payload("MANUAL_CLOSE")
                
                if attempt < 2:
                    await asyncio.sleep(1.0) # Wait for MT5 to sync history
                    
            return None
        except Exception as e:
            self.logger.error(f"Error getting exit reason for position {position_id}: {e}")
            return None


    async def get_deal_history(self, from_date: datetime, to_date: datetime = None) -> List[Dict]:
        """Fetch closed deal history"""
        if not self.connected:
            raise BrokerAPIError("Not connected to MT5")
        
        try:
            if to_date is None:
                to_date = datetime.now(timezone.utc)
            
            deals = mt5.history_deals_get(from_date, to_date)
            if deals is None:
                return []
            
            # Convert to list of dicts for easier processing
            history = []
            deal_entry_out = int(getattr(mt5, "DEAL_ENTRY_OUT", 1))
            for deal in deals:
                if int(getattr(deal, "entry", -1)) == deal_entry_out:
                    # Determine reason
                    reason = self._mt5_deal_reason_name(getattr(deal, "reason", -1))
                    comment = str(getattr(deal, "comment", "") or "").lower()
                    if reason == "UNKNOWN":
                        if " sl" in f" {comment}" or "[sl]" in comment or "stop loss" in comment:
                            reason = "SL_HIT"
                        elif " tp" in f" {comment}" or "[tp]" in comment or "take profit" in comment:
                            reason = "TP_HIT"
                        elif "stopout" in comment or "stop out" in comment or "[so]" in comment:
                            reason = "STOP_OUT"
                        elif "close ai" in comment:
                            reason = "MANUAL_CLOSE"
                        else:
                            reason = "MANUAL_CLOSE"

                    history.append({
                        "ticket": deal.ticket,
                        "position_id": deal.position_id,
                        "symbol": deal.symbol,
                        "profit": deal.profit,
                        "time": datetime.fromtimestamp(deal.time, tz=timezone.utc),
                        "time_msc": getattr(deal, "time_msc", None),
                        "price": getattr(deal, "price", None),
                        "comment": deal.comment,
                        "reason": reason
                    })
            return history
        except Exception as e:
            self.logger.error(f"Error getting deal history: {e}")
            return []

    async def has_recent_symbol_activity(self, symbol: str, lookback_seconds: int = 60) -> bool:
        """
        Check whether MT5 has any recent deal activity (entry or exit) for a symbol.
        This is used by queue flush guards to prevent duplicate re-sends after a fill.
        """
        if not self.connected:
            raise BrokerAPIError("Not connected to MT5")

        try:
            mt5_symbol = self.symbol_mapping.get(symbol, symbol.replace("/", ""))
            to_date = datetime.now(timezone.utc)
            from_date = to_date - timedelta(seconds=lookback_seconds)
            deals = mt5.history_deals_get(from_date, to_date)
            if deals is None:
                return False

            for deal in deals:
                if str(getattr(deal, "symbol", "")).upper() == str(mt5_symbol).upper():
                    return True
            return False
        except Exception as e:
            self.logger.error(f"Error checking recent symbol activity for {symbol}: {e}")
            return False


def create_mt5_broker(
    login: int = None,
    password: str = None,
    server: str = None,
    monitored_symbols: Optional[List[str]] = None,
    symbol_suffix: Optional[str] = None,
) -> MT5BrokerInterface:
    """Factory function to create MT5 broker interface
    
    Uses environment variables if credentials not provided:
    - MT5_LOGIN
    - MT5_PASSWORD  
    - MT5_SERVER
    """
    # Get from environment if not provided
    login = login or int(os.environ.get('MT5_LOGIN', '0'))
    password = password or os.environ.get('MT5_PASSWORD', '')
    server = server or os.environ.get('MT5_SERVER', 'MetaQuotes-Demo')
    
    if login == 0 or not password:
        raise ValueError("MT5 credentials not provided. Set MT5_LOGIN and MT5_PASSWORD environment variables or pass as arguments.")
    
    return MT5BrokerInterface(
        login=login,
        password=password,
        server=server,
        monitored_symbols=monitored_symbols,
        symbol_suffix=symbol_suffix or os.environ.get("MT5_SYMBOL_SUFFIX", ""),
    )
