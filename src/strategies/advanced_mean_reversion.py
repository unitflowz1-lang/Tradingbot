"""
Advanced mean-reversion strategy for FX symbols.

This module focuses on single-symbol mean reversion using:
  - Ornstein-Uhlenbeck style residual modeling
  - Bollinger-band stretch / squeeze context
  - Hurst exponent and fractal-dimension filters
  - ADX-based regime gating
  - Cost-aware no-trade zones and ATR-based invalidation
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import numpy as np
import pandas as pd

from src.analysis.market_regime_detector import MarketRegimeDetector
from src.models import Direction, ExitPolicy, MarketData, TradingSignal


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AdvancedMeanReversionConfig:
    lookback: int = 48
    bollinger_length: int = 20
    bollinger_std: float = 2.0
    atr_length: int = 14
    adx_length: int = 14
    hurst_max: float = 0.48
    adx_max: float = 23.0
    entry_zscore: float = 1.75
    exit_zscore: float = 0.35
    min_theta: float = 0.02
    squeeze_quantile: float = 0.35
    min_bandwidth_ratio: float = 0.0015
    spread_cost_multiplier: float = 3.0
    stop_atr_mult: float = 1.3
    max_holding_bars: float = 18.0
    min_confidence: float = 0.56
    confidence_ceiling: float = 0.88
    risk_per_trade: float = 0.01


class AdvancedMeanReversionStrategy:
    """Regime-aware OU/Bollinger/Hurst mean-reversion strategy."""

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

    def _coerce_config(self, config: Optional[Any]) -> AdvancedMeanReversionConfig:
        if config is None:
            return AdvancedMeanReversionConfig()
        if isinstance(config, AdvancedMeanReversionConfig):
            return config
        if isinstance(config, dict):
            valid_keys = set(AdvancedMeanReversionConfig.__dataclass_fields__.keys())
            filtered = {k: v for k, v in config.items() if k in valid_keys}
            return AdvancedMeanReversionConfig(**filtered)
        return AdvancedMeanReversionConfig()

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
        frame = frame.dropna(subset=["time"]).set_index("time")
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
    def _adx(frame: pd.DataFrame, period: int) -> pd.Series:
        high = frame["high"]
        low = frame["low"]
        close = frame["close"]

        plus_dm = high.diff()
        minus_dm = -low.diff()
        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

        tr = AdvancedMeanReversionStrategy._true_range(frame)
        atr = tr.ewm(alpha=1 / max(period, 1), adjust=False).mean()
        plus_di = 100.0 * plus_dm.ewm(alpha=1 / max(period, 1), adjust=False).mean() / atr.replace(0, np.nan)
        minus_di = 100.0 * minus_dm.ewm(alpha=1 / max(period, 1), adjust=False).mean() / atr.replace(0, np.nan)
        dx = (100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)).fillna(0.0)
        return dx.ewm(alpha=1 / max(period, 1), adjust=False).mean()

    @staticmethod
    def _hurst_exponent(prices: pd.Series, max_lag: int = 20) -> float:
        clean = prices.dropna().astype(float)
        if len(clean) < max_lag + 5:
            return 0.5

        lags = range(2, min(max_lag, max(3, len(clean) // 3)))
        tau = []
        valid_lags = []
        values = clean.to_numpy(dtype=float)
        for lag in lags:
            diff = values[lag:] - values[:-lag]
            std = float(np.std(diff))
            if np.isfinite(std) and std > 0:
                valid_lags.append(lag)
                tau.append(std)

        if len(valid_lags) < 3:
            return 0.5

        slope, _ = np.polyfit(np.log(valid_lags), np.log(tau), 1)
        return float(np.clip(slope, 0.0, 1.0))

    @staticmethod
    def _estimate_ou_params(series: pd.Series) -> tuple[float, float, float, float]:
        values = series.dropna().to_numpy(dtype=float)
        if len(values) < 12:
            return 0.0, float(values[-1]) if len(values) else 0.0, 0.0, float("inf")

        x_prev = values[:-1]
        x_next = values[1:]
        design = np.vstack([np.ones_like(x_prev), x_prev]).T
        intercept, beta = np.linalg.lstsq(design, x_next, rcond=None)[0]

        if not np.isfinite(beta):
            return 0.0, float(np.mean(values)), 0.0, float("inf")

        beta = float(np.clip(beta, 1e-6, 0.9999))
        theta = float(max(-np.log(beta), 0.0))
        mu = float(intercept / (1.0 - beta)) if abs(1.0 - beta) > 1e-6 else float(np.mean(values))
        residuals = x_next - (intercept + beta * x_prev)
        sigma = float(np.std(residuals)) if len(residuals) else 0.0
        half_life = float(np.log(2.0) / theta) if theta > 0 else float("inf")
        return theta, mu, sigma, half_life

    def _prepare_features(self, historical_data: list[MarketData]) -> pd.DataFrame:
        frame = self._build_dataframe(historical_data)
        cfg = self.config

        frame["rolling_mean"] = frame["close"].rolling(cfg.lookback).mean()
        frame["rolling_std"] = frame["close"].rolling(cfg.lookback).std(ddof=0)
        frame["zscore"] = (
            (frame["close"] - frame["rolling_mean"]) / frame["rolling_std"].replace(0, np.nan)
        )

        frame["bb_mid"] = frame["close"].rolling(cfg.bollinger_length).mean()
        frame["bb_std"] = frame["close"].rolling(cfg.bollinger_length).std(ddof=0)
        frame["bb_upper"] = frame["bb_mid"] + cfg.bollinger_std * frame["bb_std"]
        frame["bb_lower"] = frame["bb_mid"] - cfg.bollinger_std * frame["bb_std"]
        frame["bb_width"] = (frame["bb_upper"] - frame["bb_lower"]) / frame["bb_mid"].replace(0, np.nan)

        tr = self._true_range(frame)
        frame["atr"] = tr.rolling(cfg.atr_length).mean()
        frame["adx"] = self._adx(frame, cfg.adx_length)

        frame["squeeze_threshold"] = frame["bb_width"].rolling(cfg.lookback).quantile(cfg.squeeze_quantile)
        frame["in_squeeze"] = (
            frame["bb_width"]
            <= np.maximum(frame["squeeze_threshold"].fillna(np.inf), cfg.min_bandwidth_ratio)
        )
        frame["recent_squeeze"] = (
            frame["in_squeeze"].rolling(5, min_periods=1).max().fillna(0).astype(bool)
        )
        return frame

    def _build_reasoning(
        self,
        direction: Direction,
        zscore: float,
        theta: float,
        half_life: float,
        hurst: float,
        adx: float,
        squeeze_ready: bool,
        expected_edge: float,
        spread_cost: float,
    ) -> str:
        side = "Oversold" if direction == Direction.LONG else "Overbought"
        squeeze_text = "recent squeeze unwind" if squeeze_ready else "no squeeze dependency"
        return (
            f"{side} OU/Bollinger dislocation | z={zscore:.2f} | theta={theta:.3f} | "
            f"half_life={half_life:.1f} bars | hurst={hurst:.3f} | adx={adx:.1f} | "
            f"{squeeze_text} | expected_edge={expected_edge:.5f} vs spread_cost={spread_cost:.5f}"
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

        if latest[["rolling_mean", "rolling_std", "bb_upper", "bb_lower", "atr", "adx"]].isna().any():
            return None

        lookback_slice = features["close"].tail(cfg.lookback)
        hurst = self._hurst_exponent(lookback_slice)
        fractal_dimension = float(2.0 - hurst)

        residual_series = (features["close"] - features["rolling_mean"]).tail(cfg.lookback)
        theta, ou_mean, _sigma, half_life = self._estimate_ou_params(residual_series)
        current_residual = float(residual_series.iloc[-1])
        residual_std = float(residual_series.std(ddof=0) or 0.0)
        if residual_std <= 0:
            return None
        ou_zscore = (current_residual - ou_mean) / residual_std

        adx = float(latest["adx"] or 0.0)
        rolling_mean = float(latest["rolling_mean"])
        current_price = float(latest["close"])
        atr = float(latest["atr"])
        spread_cost = float(latest.get("spread", 0.0) or 0.0) * cfg.spread_cost_multiplier
        recent_squeeze = bool(latest.get("recent_squeeze", False))

        session = self.regime_detector.detect_session(historical_data[-1].timestamp)
        thresholds = self.regime_detector.get_dynamic_thresholds(session)
        session_adx_cap = min(cfg.adx_max, float(thresholds.get("adx_strong", cfg.adx_max)))

        if hurst > cfg.hurst_max:
            return None
        if adx > session_adx_cap:
            return None
        if theta < cfg.min_theta:
            return None
        if not np.isfinite(half_life) or half_life <= 0 or half_life > cfg.max_holding_bars:
            return None

        upper_band = float(latest["bb_upper"])
        lower_band = float(latest["bb_lower"])
        signal_direction: Optional[Direction] = None

        if ou_zscore <= -cfg.entry_zscore and current_price <= lower_band:
            signal_direction = Direction.LONG
        elif ou_zscore >= cfg.entry_zscore and current_price >= upper_band:
            signal_direction = Direction.SHORT

        if signal_direction is None:
            return None

        expected_edge = abs(current_price - rolling_mean)
        if expected_edge <= spread_cost:
            return None

        confidence = cfg.min_confidence
        confidence += min(abs(ou_zscore) - cfg.entry_zscore, 1.5) * 0.08
        confidence += max(0.0, (cfg.hurst_max - hurst)) * 0.25
        confidence += max(0.0, (session_adx_cap - adx) / max(session_adx_cap, 1.0)) * 0.07
        if recent_squeeze:
            confidence += 0.03
        confidence = float(np.clip(confidence, cfg.min_confidence, cfg.confidence_ceiling))

        if confidence < cfg.min_confidence:
            return None

        if signal_direction == Direction.LONG:
            stop_loss = current_price - (cfg.stop_atr_mult * atr)
            take_profit = max(rolling_mean, current_price + max(expected_edge * 0.9, atr))
        else:
            stop_loss = current_price + (cfg.stop_atr_mult * atr)
            take_profit = min(rolling_mean, current_price - max(expected_edge * 0.9, atr))

        if stop_loss <= 0 or take_profit <= 0:
            return None

        risk = abs(current_price - stop_loss)
        reward = abs(take_profit - current_price)
        if risk <= 0 or reward <= spread_cost:
            return None

        rr_ratio = reward / risk
        if rr_ratio <= 0.8:
            return None

        reasoning = self._build_reasoning(
            direction=signal_direction,
            zscore=float(ou_zscore),
            theta=theta,
            half_life=half_life,
            hurst=hurst,
            adx=adx,
            squeeze_ready=recent_squeeze,
            expected_edge=expected_edge,
            spread_cost=spread_cost,
        )

        signal = TradingSignal(
            symbol=self.symbol,
            direction=signal_direction,
            entry_price=current_price,
            stop_loss=float(stop_loss),
            take_profit=float(take_profit),
            position_size=float(cfg.risk_per_trade),
            confidence=confidence,
            reasoning=reasoning,
            timestamp=historical_data[-1].timestamp,
            rr_ratio=float(rr_ratio),
            trade_tier="TIER_A" if confidence >= 0.70 else "TIER_B",
            quality_score=round(confidence * 100.0, 2),
            exit_policy=ExitPolicy.MEAN_REVERT,
            source="advanced_mean_reversion",
            regime_label="RANGING",
        )
        setattr(
            signal,
            "strategy_meta",
            {
                "strategy": "advanced_mean_reversion",
                "ou_theta": theta,
                "ou_half_life": half_life,
                "hurst": hurst,
                "fractal_dimension": fractal_dimension,
                "ou_zscore": float(ou_zscore),
                "bollinger_width": float(latest["bb_width"]),
                "recent_squeeze": recent_squeeze,
                "mean_target": rolling_mean,
                "expected_edge": expected_edge,
                "spread_cost": spread_cost,
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
