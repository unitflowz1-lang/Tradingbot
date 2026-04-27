"""
Advanced volatility strategy for spot FX.

This is a spot-market adaptation of volatility trading concepts:
  - Realized volatility vs forecast volatility (IV proxy)
  - GARCH/EWMA-style volatility forecasting
  - Volatility clustering and vol-of-vol expansion
  - Breakout trading during volatility expansion
  - Volatility-crush mean reversion after exhaustion spikes

Because the current bot primarily ingests spot/bar data, this implementation
uses a forecast-volatility proxy rather than true OTC FX implied volatility.
The strategy is designed to be extendable if options-chain or dealer-gamma data
becomes available later.
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
class AdvancedVolatilityConfig:
    lookback: int = 48
    short_window: int = 12
    long_window: int = 48
    atr_length: int = 14
    ewma_lambda: float = 0.94
    forecast_premium_threshold: float = 1.10
    vol_zscore_threshold: float = 1.10
    vol_of_vol_threshold: float = 0.10
    breakout_buffer_atr: float = 0.20
    compression_threshold: float = 0.85
    exhaustion_zscore_threshold: float = 1.80
    spread_zscore_max: float = 1.75
    spread_to_range_max: float = 0.30
    stop_atr_mult: float = 1.30
    take_profit_atr_mult: float = 2.00
    mean_reversion_tp_mult: float = 1.30
    min_confidence: float = 0.58
    confidence_ceiling: float = 0.90
    risk_per_trade: float = 0.01


class AdvancedVolatilityStrategy:
    """Spot-FX volatility regime strategy using forecast vs realized vol."""

    REQUIRED_BARS = 80

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

    def _coerce_config(self, config: Optional[Any]) -> AdvancedVolatilityConfig:
        if config is None:
            return AdvancedVolatilityConfig()
        if isinstance(config, AdvancedVolatilityConfig):
            return config
        if isinstance(config, dict):
            valid_keys = set(AdvancedVolatilityConfig.__dataclass_fields__.keys())
            filtered = {k: v for k, v in config.items() if k in valid_keys}
            return AdvancedVolatilityConfig(**filtered)
        return AdvancedVolatilityConfig()

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
    def _ewma_volatility(returns: pd.Series, lam: float) -> pd.Series:
        clean = returns.fillna(0.0)
        variance = np.zeros(len(clean), dtype=float)
        if len(clean) == 0:
            return pd.Series(dtype=float, index=returns.index)
        variance[0] = float(clean.iloc[: min(10, len(clean))].var() or 0.0)
        for i in range(1, len(clean)):
            variance[i] = lam * variance[i - 1] + (1.0 - lam) * float(clean.iloc[i - 1] ** 2)
        return pd.Series(np.sqrt(np.maximum(variance, 0.0)), index=returns.index, dtype=float)

    def _prepare_features(self, historical_data: list[MarketData]) -> pd.DataFrame:
        frame = self._build_dataframe(historical_data)
        cfg = self.config

        frame["return"] = np.log(frame["close"] / frame["close"].shift(1)).replace([np.inf, -np.inf], np.nan)
        frame["atr"] = self._true_range(frame).rolling(cfg.atr_length).mean()
        frame["range"] = (frame["high"] - frame["low"]).replace(0.0, np.nan)
        frame["spread_mean"] = frame["spread"].rolling(cfg.short_window).mean()
        frame["spread_std"] = frame["spread"].rolling(cfg.short_window).std(ddof=0)
        frame["spread_zscore"] = (
            (frame["spread"] - frame["spread_mean"]) / frame["spread_std"].replace(0.0, np.nan)
        ).fillna(0.0)
        frame["spread_to_range"] = (frame["spread"] / frame["range"]).replace([np.inf, -np.inf], np.nan)

        frame["realized_vol_short"] = frame["return"].rolling(cfg.short_window).std(ddof=0)
        frame["realized_vol_long"] = frame["return"].rolling(cfg.long_window).std(ddof=0)
        frame["forecast_vol"] = self._ewma_volatility(frame["return"], cfg.ewma_lambda)
        frame["vol_premium_proxy"] = frame["forecast_vol"] / frame["realized_vol_short"].replace(0.0, np.nan)
        frame["vol_ratio"] = frame["realized_vol_short"] / frame["realized_vol_long"].replace(0.0, np.nan)
        frame["vol_diff"] = frame["realized_vol_short"] - frame["realized_vol_long"]
        frame["vol_zscore"] = (
            (frame["vol_diff"] - frame["vol_diff"].rolling(cfg.long_window).mean())
            / frame["vol_diff"].rolling(cfg.long_window).std(ddof=0).replace(0.0, np.nan)
        )
        frame["vol_of_vol"] = frame["realized_vol_short"].rolling(cfg.short_window).std(ddof=0)
        frame["cluster_score"] = (
            frame["return"].abs().rolling(3).mean() / frame["return"].abs().rolling(cfg.short_window).mean().replace(0.0, np.nan)
        )
        frame["momentum"] = frame["close"].pct_change(cfg.short_window)
        frame["upper_breakout"] = frame["high"].rolling(cfg.short_window).max().shift(1)
        frame["lower_breakout"] = frame["low"].rolling(cfg.short_window).min().shift(1)
        frame["rolling_mean"] = frame["close"].rolling(cfg.long_window).mean()
        frame["price_zscore"] = (
            (frame["close"] - frame["rolling_mean"])
            / frame["close"].rolling(cfg.long_window).std(ddof=0).replace(0.0, np.nan)
        )
        return frame

    def _build_reasoning(
        self,
        mode: str,
        direction: Direction,
        realized_vol: float,
        forecast_vol: float,
        premium_proxy: float,
        vol_zscore: float,
        cluster_score: float,
    ) -> str:
        side = "LONG" if direction == Direction.LONG else "SHORT"
        return (
            f"{mode} volatility setup | side={side} | rv={realized_vol:.5f} | "
            f"forecast_vol={forecast_vol:.5f} | premium_proxy={premium_proxy:.2f} | "
            f"vol_z={vol_zscore:.2f} | cluster={cluster_score:.2f}"
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
            "spread",
            "spread_zscore",
            "spread_to_range",
            "realized_vol_short",
            "realized_vol_long",
            "forecast_vol",
            "vol_premium_proxy",
            "vol_zscore",
            "vol_of_vol",
            "cluster_score",
            "upper_breakout",
            "lower_breakout",
            "rolling_mean",
            "price_zscore",
            "momentum",
        ]
        if latest[required].isna().any():
            return None

        current_price = float(latest["close"])
        atr = float(latest["atr"])
        spread = float(latest["spread"])
        spread_zscore = float(latest["spread_zscore"])
        spread_to_range = float(latest["spread_to_range"])
        realized_vol = float(latest["realized_vol_short"])
        realized_vol_long = float(latest["realized_vol_long"])
        forecast_vol = float(latest["forecast_vol"])
        premium_proxy = float(latest["vol_premium_proxy"])
        vol_zscore = float(latest["vol_zscore"])
        vol_of_vol = float(latest["vol_of_vol"])
        cluster_score = float(latest["cluster_score"])
        momentum = float(latest["momentum"])
        upper_breakout = float(latest["upper_breakout"])
        lower_breakout = float(latest["lower_breakout"])
        rolling_mean = float(latest["rolling_mean"])
        price_zscore = float(latest["price_zscore"])

        if atr <= 0.0 or spread_zscore > cfg.spread_zscore_max or spread_to_range > cfg.spread_to_range_max:
            return None

        session = self.regime_detector.detect_session(historical_data[-1].timestamp)
        session_thresholds = self.regime_detector.get_dynamic_thresholds(session)
        active_session_bonus = 0.03 if session_thresholds.get("vol_mult", 1.0) >= 1.0 else 0.0

        breakout_long = (
            premium_proxy >= cfg.forecast_premium_threshold
            and vol_zscore >= cfg.vol_zscore_threshold
            and vol_of_vol >= cfg.vol_of_vol_threshold
            and cluster_score >= 1.0
            and current_price >= upper_breakout + (cfg.breakout_buffer_atr * atr)
            and momentum > 0.0
        )
        breakout_short = (
            premium_proxy >= cfg.forecast_premium_threshold
            and vol_zscore >= cfg.vol_zscore_threshold
            and vol_of_vol >= cfg.vol_of_vol_threshold
            and cluster_score >= 1.0
            and current_price <= lower_breakout - (cfg.breakout_buffer_atr * atr)
            and momentum < 0.0
        )

        crush_long = (
            realized_vol > forecast_vol * cfg.compression_threshold
            and vol_zscore >= cfg.exhaustion_zscore_threshold
            and price_zscore <= -1.0
            and current_price > historical_data[-1].open
        )
        crush_short = (
            realized_vol > forecast_vol * cfg.compression_threshold
            and vol_zscore >= cfg.exhaustion_zscore_threshold
            and price_zscore >= 1.0
            and current_price < historical_data[-1].open
        )

        mode: Optional[str] = None
        direction: Optional[Direction] = None
        exit_policy = ExitPolicy.TREND_FOLLOW

        if breakout_long:
            mode = "VOL_EXPANSION_BREAKOUT"
            direction = Direction.LONG
        elif breakout_short:
            mode = "VOL_EXPANSION_BREAKOUT"
            direction = Direction.SHORT
        elif crush_long:
            mode = "VOL_CRUSH_MEAN_REVERSION"
            direction = Direction.LONG
            exit_policy = ExitPolicy.MEAN_REVERT
        elif crush_short:
            mode = "VOL_CRUSH_MEAN_REVERSION"
            direction = Direction.SHORT
            exit_policy = ExitPolicy.MEAN_REVERT

        if direction is None or mode is None:
            return None

        if mode == "VOL_EXPANSION_BREAKOUT":
            if direction == Direction.LONG:
                stop_loss = current_price - (cfg.stop_atr_mult * atr) - spread
                take_profit = current_price + (cfg.take_profit_atr_mult * atr)
            else:
                stop_loss = current_price + (cfg.stop_atr_mult * atr) + spread
                take_profit = current_price - (cfg.take_profit_atr_mult * atr)
        else:
            if direction == Direction.LONG:
                stop_loss = current_price - (cfg.stop_atr_mult * atr)
                take_profit = min(current_price + (cfg.mean_reversion_tp_mult * atr), rolling_mean)
            else:
                stop_loss = current_price + (cfg.stop_atr_mult * atr)
                take_profit = max(current_price - (cfg.mean_reversion_tp_mult * atr), rolling_mean)

        if stop_loss <= 0 or take_profit <= 0:
            return None

        risk = abs(current_price - stop_loss)
        reward = abs(take_profit - current_price)
        if risk <= 0.0 or reward <= spread * 2.0:
            return None

        rr_ratio = reward / risk
        if rr_ratio < 0.9:
            return None

        confidence = cfg.min_confidence
        confidence += min(max(premium_proxy - 1.0, 0.0), 0.6) * 0.18
        confidence += min(max(vol_zscore, 0.0), 2.5) * 0.05
        confidence += min(max(cluster_score - 1.0, 0.0), 1.5) * 0.06
        confidence += active_session_bonus
        if mode == "VOL_CRUSH_MEAN_REVERSION":
            confidence += 0.02
        confidence = float(np.clip(confidence, cfg.min_confidence, cfg.confidence_ceiling))

        signal = TradingSignal(
            symbol=self.symbol,
            direction=direction,
            entry_price=current_price,
            stop_loss=float(stop_loss),
            take_profit=float(take_profit),
            position_size=float(cfg.risk_per_trade),
            confidence=confidence,
            reasoning=self._build_reasoning(
                mode=mode,
                direction=direction,
                realized_vol=realized_vol,
                forecast_vol=forecast_vol,
                premium_proxy=premium_proxy,
                vol_zscore=vol_zscore,
                cluster_score=cluster_score,
            ),
            timestamp=historical_data[-1].timestamp,
            rr_ratio=float(rr_ratio),
            trade_tier="TIER_A" if confidence >= 0.70 else "TIER_B",
            quality_score=round(confidence * 100.0, 2),
            exit_policy=exit_policy,
            source="advanced_volatility",
            regime_label=mode,
        )
        setattr(
            signal,
            "strategy_meta",
            {
                "strategy": "advanced_volatility",
                "mode": mode,
                "realized_vol_short": realized_vol,
                "realized_vol_long": realized_vol_long,
                "forecast_vol": forecast_vol,
                "vol_premium_proxy": premium_proxy,
                "vol_zscore": vol_zscore,
                "vol_of_vol": vol_of_vol,
                "cluster_score": cluster_score,
                "price_zscore": price_zscore,
                "rolling_mean": rolling_mean,
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
