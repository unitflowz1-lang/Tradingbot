"""
Advanced market microstructure strategy for FX symbols.

This strategy uses Level-1/bar-proxy microstructure features that are available
in the current codebase:
  - Order-flow imbalance proxy from signed volume
  - Tick imbalance proxy from close-to-close direction
  - Session VWAP deviation
  - Volume-profile point of control approximation
  - Bid/ask spread regime analysis
  - Institutional footprint proxy via volume and range expansion

It deliberately avoids pretending we have full order-book depth. The resulting
signals are still execution-aware and fit the existing live `analyze(...)`
strategy contract.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np
import pandas as pd

from src.analysis.market_regime_detector import MarketRegimeDetector
from src.models import Direction, ExitPolicy, MarketData, TradingSignal


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AdvancedMicrostructureConfig:
    lookback: int = 48
    atr_length: int = 14
    volume_window: int = 20
    imbalance_threshold: float = 0.18
    tick_threshold: float = 0.10
    vwap_extension_threshold: float = 0.00015
    poc_distance_threshold: float = 0.0012
    spread_zscore_max: float = 1.5
    spread_to_range_max: float = 0.35
    institutional_zscore_threshold: float = 1.2
    stop_atr_mult: float = 1.15
    take_profit_atr_mult: float = 1.8
    min_confidence: float = 0.57
    confidence_ceiling: float = 0.90
    risk_per_trade: float = 0.01


class AdvancedMicrostructureStrategy:
    """Execution-aware FX strategy built from market microstructure proxies."""

    REQUIRED_BARS = 70

    def __init__(
        self,
        symbol: Optional[str] = None,
        verbose: bool = True,
        entry_filters: Optional[dict[str, Any]] = None,
        config: Optional[Any] = None,
        admission_controller: Optional[Any] = None,
    ):
        self.symbol = symbol or "UNKNOWN"
        self.verbose = verbose
        self.entry_filters = entry_filters or {}
        self.config = self._coerce_config(config)
        self.admission_controller = admission_controller
        self.logger = logging.getLogger(__name__)
        self.regime_detector = MarketRegimeDetector()

    def _coerce_config(self, config: Optional[Any]) -> AdvancedMicrostructureConfig:
        if config is None:
            return AdvancedMicrostructureConfig()
        if isinstance(config, AdvancedMicrostructureConfig):
            return config
        if isinstance(config, dict):
            valid_keys = set(AdvancedMicrostructureConfig.__dataclass_fields__.keys())
            filtered = {k: v for k, v in config.items() if k in valid_keys}
            return AdvancedMicrostructureConfig(**filtered)
        return AdvancedMicrostructureConfig()

    @staticmethod
    def _build_dataframe(historical_data: list[MarketData]) -> pd.DataFrame:
        frame = pd.DataFrame(
            {
                "time": [bar.timestamp for bar in historical_data],
                "open": [bar.open for bar in historical_data],
                "high": [bar.high for bar in historical_data],
                "low": [bar.low for bar in historical_data],
                "close": [bar.close for bar in historical_data],
                "spread": [bar.spread for bar in historical_data],
                "volume": [bar.volume for bar in historical_data],
                "bid": [bar.bid for bar in historical_data],
                "ask": [bar.ask for bar in historical_data],
            }
        )
        frame["time"] = pd.to_datetime(frame["time"], utc=True, errors="coerce")
        # Keep a simple RangeIndex to avoid pandas DatetimeIndex slicing/view edge-cases
        # during repeated iloc window extraction in live loops.
        frame = frame.dropna(subset=["time"]).sort_values("time").reset_index(drop=True)
        return frame

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
    def _point_of_control(close: pd.Series, volume: pd.Series, bins: int = 12) -> float:
        close_values = close.dropna().to_numpy(dtype=float)
        volume_values = volume.loc[close.dropna().index].to_numpy(dtype=float)
        if len(close_values) < 5:
            return float(close.iloc[-1])

        low = float(np.min(close_values))
        high = float(np.max(close_values))
        if not np.isfinite(low) or not np.isfinite(high) or high <= low:
            return float(close_values[-1])

        edges = np.linspace(low, high, bins + 1)
        bucket_idx = np.clip(np.digitize(close_values, edges) - 1, 0, bins - 1)
        bucket_volume = np.zeros(bins, dtype=float)
        for idx, vol in zip(bucket_idx, volume_values):
            bucket_volume[idx] += float(vol)

        best_bucket = int(np.argmax(bucket_volume))
        return float((edges[best_bucket] + edges[best_bucket + 1]) / 2.0)

    def _prepare_features(self, historical_data: list[MarketData]) -> pd.DataFrame:
        frame = self._build_dataframe(historical_data)
        cfg = self.config
        lookback = max(2, int(getattr(cfg, "lookback", 48) or 48))

        delta = frame["close"].diff().fillna(0.0)
        tick_sign = np.sign(delta)
        fallback_tick_sign = np.sign(frame["close"] - frame["open"]).replace(0.0, 1.0)
        tick_sign = tick_sign.mask(tick_sign == 0.0, fallback_tick_sign)
        range_ = (frame["high"] - frame["low"]).replace(0.0, np.nan)

        frame["atr"] = self._true_range(frame).rolling(cfg.atr_length).mean()
        frame["signed_volume"] = tick_sign * frame["volume"]
        frame["order_flow_imbalance"] = (
            frame["signed_volume"].rolling(cfg.lookback).sum()
            / frame["volume"].rolling(cfg.lookback).sum().replace(0.0, np.nan)
        )
        frame["tick_imbalance"] = tick_sign.rolling(cfg.lookback).mean()
        frame["cum_pv"] = (frame["close"] * frame["volume"]).cumsum()
        frame["cum_volume"] = frame["volume"].cumsum().replace(0.0, np.nan)
        frame["vwap"] = frame["cum_pv"] / frame["cum_volume"]
        frame["vwap_deviation"] = (frame["close"] - frame["vwap"]) / frame["vwap"].replace(0.0, np.nan)
        frame["spread_mean"] = frame["spread"].rolling(cfg.volume_window).mean()
        frame["spread_std"] = frame["spread"].rolling(cfg.volume_window).std(ddof=0)
        frame["spread_zscore"] = (
            (frame["spread"] - frame["spread_mean"]) / frame["spread_std"].replace(0.0, np.nan)
        ).fillna(0.0)
        frame["spread_to_range"] = (frame["spread"] / range_.replace(0.0, np.nan)).replace([np.inf, -np.inf], np.nan)

        frame["range"] = range_
        frame["volume_mean"] = frame["volume"].rolling(cfg.volume_window).mean()
        frame["volume_std"] = frame["volume"].rolling(cfg.volume_window).std(ddof=0)
        frame["volume_zscore"] = (
            (frame["volume"] - frame["volume_mean"]) / frame["volume_std"].replace(0.0, np.nan)
        ).fillna(0.0)
        frame["body"] = frame["close"] - frame["open"]
        frame["body_fraction"] = (frame["body"].abs() / range_.replace(0.0, np.nan)).fillna(0.0)
        frame["institutional_footprint"] = (
            np.sign(frame["body"]).replace(0.0, 0.0)
            * frame["volume_zscore"].clip(lower=0.0)
            * frame["body_fraction"]
        )
        frame["midpoint_skew"] = (
            ((frame["close"] - frame["low"]) - (frame["high"] - frame["close"])) / range_.replace(0.0, np.nan)
        ).fillna(0.0)

        poc_values = []
        for idx in range(len(frame)):
            start = max(0, int(idx) - lookback + 1)
            end = int(idx) + 1
            window = frame.iloc[start:end]
            poc_values.append(self._point_of_control(window["close"], window["volume"]))
        frame["poc"] = pd.Series(poc_values, index=frame.index, dtype=float)
        frame["poc_distance"] = (frame["close"] - frame["poc"]) / frame["close"].replace(0.0, np.nan)
        return frame

    def _build_reasoning(
        self,
        direction: Direction,
        ofi: float,
        tick_imb: float,
        vwap_dev: float,
        spread_z: float,
        poc_distance: float,
        institutional: float,
    ) -> str:
        side = "Buy-side" if direction == Direction.LONG else "Sell-side"
        return (
            f"{side} microstructure dominance | ofi={ofi:.2f} | tick_imb={tick_imb:.2f} | "
            f"vwap_dev={vwap_dev:.4f} | spread_z={spread_z:.2f} | poc_dist={poc_distance:.4f} | "
            f"institutional={institutional:.2f}"
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

        cfg = self.config
        features = self._prepare_features(historical_data)
        latest = features.iloc[-1]
        required = [
            "atr",
            "order_flow_imbalance",
            "tick_imbalance",
            "vwap",
            "vwap_deviation",
            "spread_zscore",
            "spread_to_range",
            "institutional_footprint",
            "poc",
            "poc_distance",
        ]
        if latest[required].isna().any():
            return None

        session = self.regime_detector.detect_session(historical_data[-1].timestamp)
        thresholds = self.regime_detector.get_dynamic_thresholds(session)

        current_price = float(latest["close"])
        atr = float(latest["atr"])
        ofi = float(latest["order_flow_imbalance"])
        tick_imbalance = float(latest["tick_imbalance"])
        vwap = float(latest["vwap"])
        vwap_deviation = float(latest["vwap_deviation"])
        spread_zscore = float(latest["spread_zscore"])
        spread_to_range = float(latest["spread_to_range"])
        institutional = float(latest["institutional_footprint"])
        poc = float(latest["poc"])
        poc_distance = float(latest["poc_distance"])
        midpoint_skew = float(latest["midpoint_skew"])
        spread = float(latest["spread"])

        if not np.isfinite(atr) or atr <= 0.0:
            return None
        if spread_zscore > cfg.spread_zscore_max:
            return None
        if spread_to_range > cfg.spread_to_range_max:
            return None
        if spread > atr * 0.45:
            return None

        long_setup = (
            ofi >= cfg.imbalance_threshold
            and tick_imbalance >= cfg.tick_threshold
            and vwap_deviation >= cfg.vwap_extension_threshold
            and institutional >= cfg.institutional_zscore_threshold * 0.20
            and abs(poc_distance) <= cfg.poc_distance_threshold
            and midpoint_skew > -0.10
        )
        short_setup = (
            ofi <= -cfg.imbalance_threshold
            and tick_imbalance <= -cfg.tick_threshold
            and vwap_deviation <= -cfg.vwap_extension_threshold
            and institutional <= -cfg.institutional_zscore_threshold * 0.20
            and abs(poc_distance) <= cfg.poc_distance_threshold
            and midpoint_skew < 0.10
        )

        if long_setup == short_setup:
            return None

        direction = Direction.LONG if long_setup else Direction.SHORT

        confidence = cfg.min_confidence
        confidence += min(abs(ofi), 0.45) * 0.35
        confidence += min(abs(tick_imbalance), 0.35) * 0.20
        confidence += min(abs(institutional), 2.5) * 0.04
        confidence += max(0.0, 1.0 - max(spread_zscore, 0.0) / max(cfg.spread_zscore_max, 1e-6)) * 0.05
        if str(session.value).startswith("OVERLAP") or session.value in {"LONDON", "NEW_YORK"}:
            confidence += 0.03
        if thresholds.get("vol_mult", 1.0) >= 1.0:
            confidence += 0.02
        confidence = float(np.clip(confidence, cfg.min_confidence, cfg.confidence_ceiling))

        spread_buffer = spread * 2.0
        if direction == Direction.LONG:
            stop_loss = current_price - (cfg.stop_atr_mult * atr) - spread_buffer
            take_profit = max(current_price + (cfg.take_profit_atr_mult * atr), vwap + atr, poc + atr * 0.5)
        else:
            stop_loss = current_price + (cfg.stop_atr_mult * atr) + spread_buffer
            take_profit = min(current_price - (cfg.take_profit_atr_mult * atr), vwap - atr, poc - atr * 0.5)

        if stop_loss <= 0 or take_profit <= 0:
            return None

        risk = abs(current_price - stop_loss)
        reward = abs(take_profit - current_price)
        if risk <= 0 or reward <= spread * 2.5:
            return None

        rr_ratio = reward / risk
        if rr_ratio < 1.0:
            return None

        signal = TradingSignal(
            symbol=self.symbol,
            direction=direction,
            entry_price=current_price,
            stop_loss=float(stop_loss),
            take_profit=float(take_profit),
            position_size=float(cfg.risk_per_trade),
            confidence=confidence,
            reasoning=self._build_reasoning(
                direction=direction,
                ofi=ofi,
                tick_imb=tick_imbalance,
                vwap_dev=vwap_deviation,
                spread_z=spread_zscore,
                poc_distance=poc_distance,
                institutional=institutional,
            ),
            timestamp=historical_data[-1].timestamp,
            rr_ratio=float(rr_ratio),
            trade_tier="TIER_A" if confidence >= 0.70 else "TIER_B",
            quality_score=round(confidence * 100.0, 2),
            exit_policy=ExitPolicy.STANDARD,
            source="advanced_microstructure",
            regime_label="MICROSTRUCTURE_FLOW",
        )
        setattr(
            signal,
            "strategy_meta",
            {
                "strategy": "advanced_microstructure",
                "order_flow_imbalance": ofi,
                "tick_imbalance": tick_imbalance,
                "vwap": vwap,
                "vwap_deviation": vwap_deviation,
                "poc": poc,
                "poc_distance": poc_distance,
                "spread_zscore": spread_zscore,
                "spread_to_range": spread_to_range,
                "institutional_footprint": institutional,
                "midpoint_skew": midpoint_skew,
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
