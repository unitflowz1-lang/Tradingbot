"""Centralized MT5 helper for symbol normalization, spread math, and order dispatch."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

try:
    import MetaTrader5 as mt5
except Exception:  # pragma: no cover - runtime dependency may be unavailable in test envs
    mt5 = None

from src.utils.pip_standardizer import PipStandardizer


@dataclass(frozen=True)
class MT5SymbolContext:
    raw_symbol: str
    formatted_symbol: str
    symbol_info: Any


class MT5Manager:
    """
    Repo-style MT5 wrapper that centralizes:
    - symbol formatting
    - Market Watch activation
    - pip/spread normalization
    - market order request creation
    """

    def __init__(self, suffix: Optional[str] = None):
        self.suffix = str(
            suffix if suffix is not None else os.environ.get("MT5_SYMBOL_SUFFIX", "")
        ).strip()

    def format_symbol(self, symbol: str) -> str:
        return PipStandardizer.normalize_symbol(symbol, self.suffix)

    def get_symbol_info(self, symbol: str) -> Tuple[Any, str]:
        """Standardize and select the symbol before fetching MT5 symbol_info."""
        if mt5 is None:
            raise RuntimeError("MetaTrader5 module is not available in this environment")

        formatted = self.format_symbol(symbol)
        if not mt5.symbol_select(formatted, True):
            raise ValueError(
                f"Symbol {formatted} not found/loaded in Market Watch. last_error={mt5.last_error()}"
            )

        info = mt5.symbol_info(formatted)
        if info is None:
            raise ValueError(f"mt5.symbol_info returned None for {formatted}")
        return info, formatted

    def get_symbol_context(self, symbol: str) -> MT5SymbolContext:
        info, formatted = self.get_symbol_info(symbol)
        return MT5SymbolContext(
            raw_symbol=str(symbol),
            formatted_symbol=formatted,
            symbol_info=info,
        )

    def get_tick(self, symbol: str) -> Tuple[Any, Any, str]:
        """Return (tick, info, formatted_symbol) after enforcing Market Watch visibility."""
        if mt5 is None:
            raise RuntimeError("MetaTrader5 module is not available in this environment")

        info, formatted = self.get_symbol_info(symbol)
        tick = mt5.symbol_info_tick(formatted)
        if tick is None:
            raise ValueError(
                f"MARKET_DATA_UNAVAILABLE: no tick for {symbol} -> {formatted}. last_error={mt5.last_error()}"
            )
        bid = float(getattr(tick, "bid", 0.0) or 0.0)
        ask = float(getattr(tick, "ask", 0.0) or 0.0)
        if bid <= 0.0 or ask <= 0.0:
            raise ValueError(
                f"MARKET_DATA_UNAVAILABLE: invalid tick for {formatted}. bid={bid}, ask={ask}"
            )
        return tick, info, formatted

    def get_spread_pips(self, symbol: str) -> float:
        """Calculate live spread in standard pips using MT5 digits/point metadata."""
        tick, info, _ = self.get_tick(symbol)
        return round(
            PipStandardizer.spread_to_pips(
                ask=float(getattr(tick, "ask", 0.0) or 0.0),
                bid=float(getattr(tick, "bid", 0.0) or 0.0),
                symbol=symbol,
                symbol_info=info,
            ),
            2,
        )

    def validate_spread_match(self, symbol: str, tolerance_pips: float = 0.1) -> Dict[str, Any]:
        """
        Compare ask/bid-derived spread against broker-reported spread in points.
        Useful when auditing SPREAD_MISMATCH warnings.
        """
        tick, info, formatted = self.get_tick(symbol)
        point = float(getattr(info, "point", 0.0) or 0.0)
        broker_spread_raw = float(getattr(info, "spread", 0.0) or 0.0) * point
        calc_pips = PipStandardizer.spread_to_pips(
            ask=float(getattr(tick, "ask", 0.0) or 0.0),
            bid=float(getattr(tick, "bid", 0.0) or 0.0),
            symbol=symbol,
            symbol_info=info,
        )
        reported_pips = PipStandardizer.broker_value_to_pips_by_digits(
            value=broker_spread_raw,
            digits=getattr(info, "digits", None),
            point=getattr(info, "point", None),
            symbol=symbol,
        )
        delta_pips = round(abs(calc_pips - reported_pips), 2)
        return {
            "symbol": symbol,
            "formatted_symbol": formatted,
            "calculated_spread_pips": round(calc_pips, 2),
            "reported_spread_pips": round(reported_pips, 2),
            "delta_pips": delta_pips,
            "matches": delta_pips <= float(tolerance_pips),
        }

    def execute_order(
        self,
        symbol: str,
        volume: float,
        direction: str,
        sl: float,
        tp: float,
        *,
        deviation: int = 20,
        magic: int = 234000,
        comment: str = "AI_TRADE",
        filling_mode: Optional[int] = None,
    ):
        """
        Send a market order with normalized symbol and broker-rounded prices.
        """
        if mt5 is None:
            raise RuntimeError("MetaTrader5 module is not available in this environment")

        tick, info, formatted = self.get_tick(symbol)
        side = str(direction or "").upper()
        is_buy = side in {"BUY", "LONG"}
        order_type = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL
        price = float(getattr(tick, "ask", 0.0) if is_buy else getattr(tick, "bid", 0.0))
        digits = int(getattr(info, "digits", 5) or 5)

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": formatted,
            "volume": float(volume),
            "type": order_type,
            "price": round(price, digits),
            "sl": round(float(sl), digits),
            "tp": round(float(tp), digits),
            "magic": int(magic),
            "comment": str(comment),
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": int(
                filling_mode
                if filling_mode is not None
                else getattr(mt5, "ORDER_FILLING_RETURN", 0)
            ),
        }
        return mt5.order_send(request)

    def market_snapshot(self, symbol: str) -> Dict[str, Any]:
        """Convenience helper for logging/debugging live MT5 quote state."""
        tick, info, formatted = self.get_tick(symbol)
        tick_time = getattr(tick, "time", None)
        return {
            "symbol": symbol,
            "formatted_symbol": formatted,
            "bid": float(getattr(tick, "bid", 0.0) or 0.0),
            "ask": float(getattr(tick, "ask", 0.0) or 0.0),
            "spread_pips": self.get_spread_pips(symbol),
            "digits": int(getattr(info, "digits", 5) or 5),
            "point": float(getattr(info, "point", 0.0) or 0.0),
            "timestamp": (
                datetime.fromtimestamp(float(tick_time), tz=timezone.utc)
                if tick_time is not None
                else None
            ),
        }


def create_mt5_manager(suffix: Optional[str] = None) -> MT5Manager:
    """Factory helper that defaults to the MT5_SYMBOL_SUFFIX environment variable."""
    return MT5Manager(suffix=suffix)
