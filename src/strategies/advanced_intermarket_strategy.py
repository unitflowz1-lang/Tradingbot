"""
Advanced intermarket and correlation strategy for FX.

This strategy blends:
  - Intermarket reference relationships (DXY, commodities, peer FX crosses)
  - Cross-asset / relative-value residual analysis
  - Pairs-style mean reversion with regression residual z-scores
  - Cointegration-style stability filters via spread stationarity proxies
  - Carry-bias overlays via configurable currency-rate differentials

The strategy uses a pluggable related-market loader because the current live
strategy contract only passes one symbol's bars into `analyze(...)`.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd

from src.models import Direction, ExitPolicy, MarketData, TradingSignal


logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ReferenceSpec:
    symbol: str
    expected_sign: int = 1
    role: str = "peer"
    weight: float = 1.0


@dataclass(frozen=True)
class AdvancedIntermarketConfig:
    lookback: int = 60
    min_reference_bars: int = 50
    min_abs_correlation: float = 0.45
    residual_zscore_entry: float = 1.60
    residual_zscore_exit: float = 0.40
    max_residual_half_life: float = 30.0
    spread_vol_max: float = 0.020
    stop_atr_mult: float = 1.25
    take_profit_atr_mult: float = 1.80
    min_confidence: float = 0.57
    confidence_ceiling: float = 0.89
    risk_per_trade: float = 0.01
    reference_map: dict[str, list[ReferenceSpec]] = field(default_factory=dict)
    currency_rate_map: dict[str, float] = field(default_factory=dict)


class AdvancedIntermarketStrategy:
    """Intermarket / correlation strategy with pluggable reference data."""

    RELATED_SYMBOL_DEFAULTS: dict[str, list[ReferenceSpec]] = {
        "EUR/USD": [
            ReferenceSpec(symbol="DXY", expected_sign=-1, role="dxy", weight=1.0),
            ReferenceSpec(symbol="USD/JPY", expected_sign=1, role="yield_proxy", weight=0.5),
        ],
        "GBP/USD": [
            ReferenceSpec(symbol="DXY", expected_sign=-1, role="dxy", weight=1.0),
            ReferenceSpec(symbol="EUR/USD", expected_sign=1, role="peer", weight=0.7),
        ],
        "AUD/USD": [
            ReferenceSpec(symbol="DXY", expected_sign=-1, role="dxy", weight=0.8),
            ReferenceSpec(symbol="XAU/USD", expected_sign=1, role="commodity", weight=1.0),
            ReferenceSpec(symbol="NZD/USD", expected_sign=1, role="peer", weight=0.9),
        ],
        "NZD/USD": [
            ReferenceSpec(symbol="DXY", expected_sign=-1, role="dxy", weight=0.8),
            ReferenceSpec(symbol="AUD/USD", expected_sign=1, role="peer", weight=1.0),
        ],
        "USD/CAD": [
            ReferenceSpec(symbol="DXY", expected_sign=1, role="dxy", weight=0.7),
            ReferenceSpec(symbol="XTI/USD", expected_sign=-1, role="commodity", weight=1.0),
            ReferenceSpec(symbol="AUD/USD", expected_sign=-1, role="risk", weight=0.4),
        ],
        "USD/JPY": [
            ReferenceSpec(symbol="DXY", expected_sign=1, role="dxy", weight=0.8),
            ReferenceSpec(symbol="XAU/USD", expected_sign=-1, role="safe_haven", weight=0.5),
        ],
    }

    DEFAULT_RATE_MAP = {
        "USD": 5.25,
        "EUR": 4.00,
        "GBP": 5.00,
        "JPY": 0.10,
        "CHF": 1.50,
        "AUD": 4.35,
        "NZD": 5.50,
        "CAD": 4.50,
        "NOK": 4.50,
    }

    REQUIRED_BARS = 80

    def __init__(
        self,
        symbol: Optional[str] = None,
        verbose: bool = True,
        entry_filters: Optional[dict[str, Any]] = None,
        config: Optional[Any] = None,
        admission_controller: Optional[Any] = None,
        related_data_loader: Optional[Callable[[str, list[str], int], Any]] = None,
    ):
        self.symbol = symbol or "UNKNOWN"
        self.verbose = verbose
        self.entry_filters = entry_filters or {}
        self.config = self._coerce_config(config)
        self.admission_controller = admission_controller
        self.related_data_loader = related_data_loader
        self.logger = logging.getLogger(__name__)

    def _coerce_config(self, config: Optional[Any]) -> AdvancedIntermarketConfig:
        if config is None:
            return AdvancedIntermarketConfig()
        if isinstance(config, AdvancedIntermarketConfig):
            return config
        if isinstance(config, dict):
            valid_keys = set(AdvancedIntermarketConfig.__dataclass_fields__.keys())
            filtered = {k: v for k, v in config.items() if k in valid_keys}

            if "reference_map" in filtered:
                ref_map = {}
                for key, specs in (filtered.get("reference_map") or {}).items():
                    parsed_specs = []
                    for spec in specs or []:
                        if isinstance(spec, ReferenceSpec):
                            parsed_specs.append(spec)
                        elif isinstance(spec, dict):
                            parsed_specs.append(ReferenceSpec(**spec))
                    ref_map[key] = parsed_specs
                filtered["reference_map"] = ref_map
            return AdvancedIntermarketConfig(**filtered)
        return AdvancedIntermarketConfig()

    @staticmethod
    def _build_frame(historical_data: list[MarketData]) -> pd.DataFrame:
        frame = pd.DataFrame(
            {
                "time": [bar.timestamp for bar in historical_data],
                "open": [bar.open for bar in historical_data],
                "high": [bar.high for bar in historical_data],
                "low": [bar.low for bar in historical_data],
                "close": [bar.close for bar in historical_data],
                "spread": [bar.spread for bar in historical_data],
                "volume": [bar.volume for bar in historical_data],
            }
        )
        frame["time"] = pd.to_datetime(frame["time"], utc=True, errors="coerce")
        return frame.dropna(subset=["time"]).set_index("time")

    @staticmethod
    def _true_range(frame: pd.DataFrame) -> pd.Series:
        prev_close = frame["close"].shift(1)
        return pd.concat(
            [
                (frame["high"] - frame["low"]).abs(),
                (frame["high"] - prev_close).abs(),
                (frame["low"] - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)

    @staticmethod
    def _estimate_half_life(series: pd.Series) -> float:
        clean = series.dropna().to_numpy(dtype=float)
        if len(clean) < 12:
            return float("inf")
        x_prev = clean[:-1]
        x_next = clean[1:]
        design = np.vstack([np.ones_like(x_prev), x_prev]).T
        intercept, beta = np.linalg.lstsq(design, x_next, rcond=None)[0]
        if not np.isfinite(beta):
            return float("inf")
        beta = float(np.clip(beta, 1e-6, 0.9999))
        theta = float(max(-np.log(beta), 0.0))
        if theta <= 0:
            return float("inf")
        return float(np.log(2.0) / theta)

    def _currency_carry_bias(self) -> float:
        rate_map = dict(self.DEFAULT_RATE_MAP)
        rate_map.update(self.config.currency_rate_map or {})
        base, quote = str(self.symbol).replace("_", "/").split("/")
        return float(rate_map.get(base, 0.0) - rate_map.get(quote, 0.0))

    def _reference_specs(self) -> list[ReferenceSpec]:
        custom = self.config.reference_map.get(self.symbol) if self.config.reference_map else None
        specs = list(custom) if custom else list(self.RELATED_SYMBOL_DEFAULTS.get(self.symbol, []))
        normalized: list[ReferenceSpec] = []
        use_dxy_filter = _env_bool("USE_DXY_FILTER", not _env_bool("REQUIRE_USDX", False))
        for spec in specs:
            if isinstance(spec, ReferenceSpec):
                candidate = spec
            elif isinstance(spec, dict):
                candidate = ReferenceSpec(**spec)
            else:
                continue
            if candidate.role == "dxy" and not use_dxy_filter:
                continue
            normalized.append(candidate)
        return normalized

    async def _load_related_histories(self, count: int) -> dict[str, list[MarketData]]:
        specs = self._reference_specs()
        if not specs or self.related_data_loader is None:
            return {}

        symbols = [spec.symbol for spec in specs]
        result = self.related_data_loader(self.symbol, symbols, count)
        if hasattr(result, "__await__"):
            result = await result
        if not isinstance(result, dict):
            return {}
        return {str(k): v for k, v in result.items() if isinstance(v, list) and v}

    def _align_reference(self, main_frame: pd.DataFrame, ref_bars: list[MarketData]) -> Optional[pd.DataFrame]:
        ref_frame = self._build_frame(ref_bars)[["close"]].rename(columns={"close": "ref_close"})
        joined = main_frame[["close"]].join(ref_frame, how="inner").dropna()
        if len(joined) < self.config.min_reference_bars:
            return None
        return joined.tail(self.config.lookback)

    def _score_reference(
        self,
        aligned: pd.DataFrame,
        spec: ReferenceSpec,
    ) -> Optional[dict[str, float]]:
        main_returns = np.log(aligned["close"] / aligned["close"].shift(1)).dropna()
        ref_returns = np.log(aligned["ref_close"] / aligned["ref_close"].shift(1)).dropna()
        if len(main_returns) < self.config.min_reference_bars - 1 or len(ref_returns) != len(main_returns):
            return None

        corr = float(np.corrcoef(main_returns, ref_returns)[0, 1])
        if not np.isfinite(corr):
            return None
        signed_corr_alignment = corr * float(spec.expected_sign)
        if signed_corr_alignment < self.config.min_abs_correlation:
            return None

        x = aligned["ref_close"].to_numpy(dtype=float)
        y = aligned["close"].to_numpy(dtype=float)
        design = np.vstack([np.ones_like(x), x]).T
        intercept, beta = np.linalg.lstsq(design, y, rcond=None)[0]
        fitted = intercept + beta * x
        residual = y - fitted
        residual_std = float(np.std(residual))
        if residual_std <= 0 or not np.isfinite(residual_std):
            return None
        residual_z = float((residual[-1] - np.mean(residual)) / residual_std)
        half_life = self._estimate_half_life(pd.Series(residual))
        spread_vol = float(np.std(np.diff(residual))) if len(residual) > 5 else float("inf")

        return {
            "corr": corr,
            "aligned_corr": signed_corr_alignment,
            "beta": float(beta),
            "residual_z": residual_z,
            "half_life": float(half_life),
            "spread_vol": spread_vol,
            "weight": float(spec.weight),
        }

    def _build_reasoning(
        self,
        direction: Direction,
        driver_symbol: str,
        driver_role: str,
        residual_z: float,
        corr: float,
        carry_bias: float,
        dxy_bias: float,
    ) -> str:
        return (
            f"Intermarket relative-value signal | driver={driver_symbol} ({driver_role}) | "
            f"direction={direction.value} | residual_z={residual_z:.2f} | corr={corr:.2f} | "
            f"carry_bias={carry_bias:.2f} | dxy_bias={dxy_bias:.2f}"
        )

    async def analyze(
        self,
        historical_data: list[MarketData],
        current_positions: Optional[list[Any]] = None,
    ) -> Optional[TradingSignal]:
        if not historical_data or len(historical_data) < self.REQUIRED_BARS:
            return None
        if current_positions:
            for position in current_positions:
                if getattr(position, "symbol", None) == self.symbol:
                    return None

        main_frame = self._build_frame(historical_data).tail(max(self.config.lookback, self.REQUIRED_BARS))
        main_frame["atr"] = self._true_range(main_frame).rolling(14).mean()
        latest_atr = float(main_frame["atr"].iloc[-1] or 0.0)
        if latest_atr <= 0.0:
            return None

        related_histories = await self._load_related_histories(max(self.config.lookback, self.REQUIRED_BARS))
        if not related_histories:
            return None

        best_symbol = None
        best_role = "peer"
        best_metrics = None
        specs = {spec.symbol: spec for spec in self._reference_specs()}

        dxy_bias = 0.0
        for ref_symbol, ref_bars in related_histories.items():
            spec = specs.get(ref_symbol)
            if spec is None:
                continue
            aligned = self._align_reference(main_frame, ref_bars)
            if aligned is None:
                continue
            metrics = self._score_reference(aligned, spec)
            if metrics is None:
                continue
            if spec.role == "dxy":
                dxy_bias = float(np.sign(metrics["corr"]) * metrics["weight"])

            score = abs(metrics["residual_z"]) * metrics["weight"] * max(metrics["aligned_corr"], 0.0)
            if best_metrics is None or score > (
                abs(best_metrics["residual_z"]) * best_metrics["weight"] * max(best_metrics["aligned_corr"], 0.0)
            ):
                best_symbol = ref_symbol
                best_role = spec.role
                best_metrics = metrics

        if best_metrics is None or best_symbol is None:
            return None
        if abs(best_metrics["residual_z"]) < self.config.residual_zscore_entry:
            return None
        if not np.isfinite(best_metrics["half_life"]) or best_metrics["half_life"] > self.config.max_residual_half_life:
            return None
        if best_metrics["spread_vol"] > self.config.spread_vol_max:
            return None

        residual_z = float(best_metrics["residual_z"])
        direction = Direction.SHORT if residual_z > 0 else Direction.LONG

        carry_bias = self._currency_carry_bias()
        if direction == Direction.LONG and carry_bias < -2.0:
            return None
        if direction == Direction.SHORT and carry_bias > 2.0:
            return None

        current_price = float(main_frame["close"].iloc[-1])
        spread = float(main_frame["spread"].iloc[-1] or 0.0)
        mean_target = float(main_frame["close"].rolling(self.config.lookback).mean().iloc[-1])

        if direction == Direction.LONG:
            stop_loss = current_price - (self.config.stop_atr_mult * latest_atr) - spread
            take_profit = max(mean_target, current_price + (self.config.take_profit_atr_mult * latest_atr))
        else:
            stop_loss = current_price + (self.config.stop_atr_mult * latest_atr) + spread
            take_profit = min(mean_target, current_price - (self.config.take_profit_atr_mult * latest_atr))

        if stop_loss <= 0 or take_profit <= 0:
            return None

        risk = abs(current_price - stop_loss)
        reward = abs(take_profit - current_price)
        if risk <= 0.0 or reward <= spread * 2.0:
            return None
        rr_ratio = reward / risk
        if rr_ratio < 0.9:
            return None

        confidence = self.config.min_confidence
        confidence += min(abs(residual_z), 3.0) * 0.06
        confidence += min(max(best_metrics["aligned_corr"] - self.config.min_abs_correlation, 0.0), 0.4) * 0.20
        confidence += min(max(carry_bias / 5.0, -0.05), 0.05) if direction == Direction.LONG else min(max(-carry_bias / 5.0, -0.05), 0.05)
        confidence = float(np.clip(confidence, self.config.min_confidence, self.config.confidence_ceiling))

        signal = TradingSignal(
            symbol=self.symbol,
            direction=direction,
            entry_price=current_price,
            stop_loss=float(stop_loss),
            take_profit=float(take_profit),
            position_size=float(self.config.risk_per_trade),
            confidence=confidence,
            reasoning=self._build_reasoning(
                direction=direction,
                driver_symbol=best_symbol,
                driver_role=best_role,
                residual_z=residual_z,
                corr=float(best_metrics["corr"]),
                carry_bias=carry_bias,
                dxy_bias=dxy_bias,
            ),
            timestamp=historical_data[-1].timestamp,
            rr_ratio=float(rr_ratio),
            trade_tier="TIER_A" if confidence >= 0.70 else "TIER_B",
            quality_score=round(confidence * 100.0, 2),
            exit_policy=ExitPolicy.MEAN_REVERT,
            source="advanced_intermarket",
            regime_label="INTERMARKET_RELATIVE_VALUE",
        )
        setattr(
            signal,
            "strategy_meta",
            {
                "strategy": "advanced_intermarket",
                "driver_symbol": best_symbol,
                "driver_role": best_role,
                "residual_zscore": residual_z,
                "correlation": float(best_metrics["corr"]),
                "aligned_correlation": float(best_metrics["aligned_corr"]),
                "half_life": float(best_metrics["half_life"]),
                "carry_bias": carry_bias,
                "dxy_bias": dxy_bias,
            },
        )
        return signal

    def mark_market_closed(self) -> None:
        return None

    def mark_market_reopened(self) -> None:
        return None

    def is_open_session_spread_allowed(self, _spread_pips: float) -> bool:
        return True

    def is_time_exit_disabled(self) -> bool:
        return False
