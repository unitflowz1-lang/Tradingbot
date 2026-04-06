"""
High Reward Reversal Peaks strategy.

Standalone, vectorized signal engine + trade simulator for reversal peaks using:
  - Bollinger Bands
  - RSI divergence on confirmed pivots
  - ATR-based stop placement
  - 1.5R trailing-stop activation

This module is intentionally standalone so it can be used for:
  1. Research / backtests
  2. Signal generation
  3. Future integration into the live strategy router
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import numpy as np
import pandas as pd

from src.analysis.llm_macro_monitor import macro_risk_cache
from src.models import Direction, ExitPolicy, MarketData, TradingSignal


class _NullMLPredictor:
    """Compatibility shim for live router ML hooks."""

    def predict_with_details(self, *_args, **_kwargs):
        return "NEUTRAL", 0.0, {"meta_win_prob": 1.0}


class _NullStrictnessController:
    """Compatibility shim for strategy result callbacks."""

    def update_performance(self, *_args, **_kwargs) -> None:
        return None


@dataclass(frozen=True)
class ReversalPeaksConfig:
    bb_length: int = 20
    bb_std: float = 2.0
    rsi_length: int = 14
    atr_length: int = 14
    volume_sma_length: int = 10
    pivot_left: int = 5
    pivot_right: int = 5
    divergence_min_bars: int = 5
    divergence_max_bars: int = 60
    volume_spike_mult: float = 1.5
    stop_atr_buffer: float = 0.5
    activation_r_multiple: float = 1.5
    trailing_atr_mult: float = 3.0
    equity: float = 100_000.0
    risk_per_trade: float = 0.01


class HighRewardReversalPeaksStrategy:
    """
    Vectorized reversal-peak detector with path-dependent trade simulation.

    Feature generation is fully vectorized.
    Trade simulation iterates over entry events only, not over every row.
    """

    REQUIRED_COLUMNS = {"open", "high", "low", "close", "volume"}

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
        self.logger = logging.getLogger(__name__)
        self.config = self._coerce_config(config)
        self.admission_controller = admission_controller
        self.combiner = None
        self.ml_predictor = _NullMLPredictor()
        self.strictness_controller = _NullStrictnessController()
        self._trail_state: dict[str, Any] = {}
        self.news_collector = None

        from src.analysis.market_regime_detector import MarketRegimeDetector

        self.regime_detector = MarketRegimeDetector()
        if config is not None:
            try:
                from src.data.news_data_collector import NewsDataCollector

                self.news_collector = NewsDataCollector(config)
            except Exception as exc:
                self.logger.debug("[REVERSAL_PEAKS] %s | News collector unavailable: %s", self.symbol, exc)

    def _coerce_config(self, config: Optional[Any]) -> ReversalPeaksConfig:
        if config is None:
            return ReversalPeaksConfig()
        if isinstance(config, ReversalPeaksConfig):
            return config
        if isinstance(config, dict):
            valid_keys = set(ReversalPeaksConfig.__dataclass_fields__.keys())
            filtered = {k: v for k, v in config.items() if k in valid_keys}
            return ReversalPeaksConfig(**filtered)
        return ReversalPeaksConfig()

    def _validate_input(self, df: pd.DataFrame) -> None:
        missing = sorted(self.REQUIRED_COLUMNS.difference(df.columns))
        if missing:
            raise ValueError(
                f"HighRewardReversalPeaksStrategy requires columns: {', '.join(sorted(self.REQUIRED_COLUMNS))}. "
                f"Missing: {', '.join(missing)}"
            )

    def _session_volume_multiplier(self, index: pd.DatetimeIndex) -> pd.Series:
        utc_index = index.tz_convert("UTC") if getattr(index, "tz", None) is not None else index.tz_localize("UTC")
        hours = utc_index.hour
        multipliers = pd.Series(float(self.config.volume_spike_mult), index=index, dtype="float64")
        multipliers.loc[(hours >= 0) & (hours < 9)] = 1.2
        multipliers.loc[(hours >= 13) & (hours < 17)] = 1.7
        return multipliers

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Build all strategy features using vectorized pandas / pandas_ta operations.
        """
        self._validate_input(df)
        out = df.copy()

        try:
            import pandas_ta as ta
        except ImportError as exc:
            raise ImportError(
                "pandas_ta is required for HighRewardReversalPeaksStrategy. Install with `pip install pandas_ta`."
            ) from exc

        cfg = self.config

        bb = ta.bbands(out["close"], length=cfg.bb_length, std=cfg.bb_std)
        if bb is None or bb.empty:
            raise ValueError("pandas_ta.bbands returned no Bollinger Band data")

        bb_std_candidates = [str(cfg.bb_std), f"{float(cfg.bb_std):.1f}", f"{float(cfg.bb_std):g}"]

        def _resolve_bb_column(prefix: str) -> str:
            for std_value in bb_std_candidates:
                candidate = f"{prefix}_{cfg.bb_length}_{std_value}"
                if candidate in bb.columns:
                    return candidate
                prefixed_matches = [
                    str(col)
                    for col in bb.columns
                    if str(col).startswith(f"{candidate}_")
                ]
                if prefixed_matches:
                    return prefixed_matches[0]
            generic_matches = [
                str(col)
                for col in bb.columns
                if str(col).startswith(f"{prefix}_{cfg.bb_length}_")
            ]
            if generic_matches:
                return generic_matches[0]
            available = ", ".join(str(col) for col in bb.columns)
            raise KeyError(
                f"Missing Bollinger column for prefix={prefix}, length={cfg.bb_length}, std={cfg.bb_std}. "
                f"Available columns: {available}"
            )

        lower_col = _resolve_bb_column("BBL")
        mid_col = _resolve_bb_column("BBM")
        upper_col = _resolve_bb_column("BBU")

        out["bb_lower"] = bb[lower_col]
        out["bb_mid"] = bb[mid_col]
        out["bb_upper"] = bb[upper_col]

        canonical_std = f"{float(cfg.bb_std):.1f}"
        out[f"BBL_{cfg.bb_length}_{canonical_std}"] = bb[lower_col]
        out[f"BBM_{cfg.bb_length}_{canonical_std}"] = bb[mid_col]
        out[f"BBU_{cfg.bb_length}_{canonical_std}"] = bb[upper_col]
        out["rsi"] = ta.rsi(out["close"], length=cfg.rsi_length)
        out["atr"] = ta.atr(out["high"], out["low"], out["close"], length=cfg.atr_length)
        out["vol_sma"] = ta.sma(out["volume"], length=cfg.volume_sma_length)
        out["volume_ratio"] = np.where(out["vol_sma"] > 0, out["volume"] / out["vol_sma"], np.nan)
        out["session_volume_spike_mult"] = self._session_volume_multiplier(out.index)

        pivot_window = cfg.pivot_left + cfg.pivot_right + 1
        out["pivot_high"] = (
            out["high"].eq(out["high"].rolling(pivot_window, center=True).max())
            & out["high"].rolling(pivot_window, center=True).count().eq(pivot_window)
        )
        out["pivot_low"] = (
            out["low"].eq(out["low"].rolling(pivot_window, center=True).min())
            & out["low"].rolling(pivot_window, center=True).count().eq(pivot_window)
        )

        idx = pd.Series(np.arange(len(out)), index=out.index, dtype="float64")

        pivot_high_price = out["high"].where(out["pivot_high"])
        pivot_high_rsi = out["rsi"].where(out["pivot_high"])
        pivot_high_idx = idx.where(out["pivot_high"])
        prev_high_price = pivot_high_price.ffill().shift(1)
        prev_high_rsi = pivot_high_rsi.ffill().shift(1)
        prev_high_idx = pivot_high_idx.ffill().shift(1)
        high_gap = idx - prev_high_idx

        pivot_low_price = out["low"].where(out["pivot_low"])
        pivot_low_rsi = out["rsi"].where(out["pivot_low"])
        pivot_low_idx = idx.where(out["pivot_low"])
        prev_low_price = pivot_low_price.ffill().shift(1)
        prev_low_rsi = pivot_low_rsi.ffill().shift(1)
        prev_low_idx = pivot_low_idx.ffill().shift(1)
        low_gap = idx - prev_low_idx

        out["bearish_divergence_pivot"] = (
            out["pivot_high"]
            & high_gap.between(cfg.divergence_min_bars, cfg.divergence_max_bars)
            & (out["high"] > prev_high_price)
            & (out["rsi"] < prev_high_rsi)
        )
        out["bearish_divergence_strength"] = np.where(
            out["bearish_divergence_pivot"],
            (prev_high_rsi - out["rsi"]).clip(lower=0.0),
            np.nan,
        )
        out["bullish_divergence_pivot"] = (
            out["pivot_low"]
            & low_gap.between(cfg.divergence_min_bars, cfg.divergence_max_bars)
            & (out["low"] < prev_low_price)
            & (out["rsi"] > prev_low_rsi)
        )
        out["bullish_divergence_strength"] = np.where(
            out["bullish_divergence_pivot"],
            (out["rsi"] - prev_low_rsi).clip(lower=0.0),
            np.nan,
        )

        # Confirmation occurs after `pivot_right` bars. We shift pivot-candle conditions
        # to the actual trade-trigger bar to keep the logic zero-lookahead in backtests.
        r = cfg.pivot_right
        out["signal_volume_ratio"] = out["volume_ratio"].shift(r)
        out["short_band_excess"] = ((out["close"] - out["bb_upper"]).clip(lower=0.0) / out["atr"].replace(0, np.nan)).shift(r)
        out["long_band_excess"] = ((out["bb_lower"] - out["close"]).clip(lower=0.0) / out["atr"].replace(0, np.nan)).shift(r)
        out["signal_bearish_divergence_strength"] = out["bearish_divergence_strength"].shift(r)
        out["signal_bullish_divergence_strength"] = out["bullish_divergence_strength"].shift(r)
        out["short_entry_signal"] = (
            out["bearish_divergence_pivot"].shift(r, fill_value=False)
            & (out["close"].shift(r) > out["bb_upper"].shift(r))
            & (out["volume"].shift(r) >= out["session_volume_spike_mult"].shift(r) * out["vol_sma"].shift(r))
        )
        out["long_entry_signal"] = (
            out["bullish_divergence_pivot"].shift(r, fill_value=False)
            & (out["close"].shift(r) < out["bb_lower"].shift(r))
            & (out["volume"].shift(r) >= out["session_volume_spike_mult"].shift(r) * out["vol_sma"].shift(r))
        )

        out["short_stop"] = pivot_high_price.shift(r) + (cfg.stop_atr_buffer * out["atr"].shift(r))
        out["long_stop"] = pivot_low_price.shift(r) - (cfg.stop_atr_buffer * out["atr"].shift(r))

        risk_cash = cfg.equity * cfg.risk_per_trade
        long_risk = (out["close"] - out["long_stop"]).abs()
        short_risk = (out["short_stop"] - out["close"]).abs()
        out["long_position_size"] = np.where(long_risk > 0, risk_cash / long_risk, np.nan)
        out["short_position_size"] = np.where(short_risk > 0, risk_cash / short_risk, np.nan)

        return out

    @staticmethod
    def _build_dataframe(historical_data: list[MarketData]) -> pd.DataFrame:
        frame = pd.DataFrame(
            {
                "time": [bar.timestamp for bar in historical_data],
                "open": [bar.open for bar in historical_data],
                "high": [bar.high for bar in historical_data],
                "low": [bar.low for bar in historical_data],
                "close": [bar.close for bar in historical_data],
                "volume": [bar.volume for bar in historical_data],
            }
        )
        frame["time"] = pd.to_datetime(frame["time"], utc=True, errors="coerce")
        return frame.set_index("time")

    @staticmethod
    def _clamp(value: float, floor: float, ceiling: float) -> float:
        return max(floor, min(ceiling, value))

    def _current_volatility_ratio(self, historical_data: list[MarketData]) -> float:
        try:
            frame = self._build_dataframe(historical_data)
            if len(frame) < 48:
                return 1.0
            prev_close = frame["close"].shift(1)
            true_range = pd.concat(
                [
                    (frame["high"] - frame["low"]).abs(),
                    (frame["high"] - prev_close).abs(),
                    (frame["low"] - prev_close).abs(),
                ],
                axis=1,
            ).max(axis=1)
            atr_now = float(true_range.tail(14).mean() or 0.0)
            daily_avg = float(true_range.tail(24).mean() or 0.0)
            if atr_now <= 0.0 or daily_avg <= 0.0:
                return 1.0
            return atr_now / daily_avg
        except Exception:
            return 1.0

    async def _check_news_buffer(self) -> tuple[bool, str]:
        if self.news_collector is None:
            return False, ""
        try:
            news = await self.news_collector.collect_data([self.symbol], timeframe="1h")
            articles = news.get(self.symbol, [])
            now = datetime.now(timezone.utc)
            high_impact_keywords = ["FED", "CPI", "INTEREST RATE", "GDP", "ECB", "NON-FARM"]
            for article in articles:
                content = f"{article.title} {article.content}".upper()
                if not any(keyword in content for keyword in high_impact_keywords):
                    continue
                pub_time = article.published_at
                if pub_time.tzinfo is None:
                    pub_time = pub_time.replace(tzinfo=timezone.utc)
                if abs((now - pub_time).total_seconds()) <= 1800:
                    return True, f"High-impact news nearby: {article.title}"
            return False, ""
        except Exception as exc:
            self.logger.debug("[REVERSAL_PEAKS] %s | News buffer check failed: %s", self.symbol, exc)
            return False, ""

    def _check_entry_filters(self, *_args, **_kwargs) -> bool:
        return True

    def mark_market_closed(self) -> None:
        return None

    def mark_market_reopened(self) -> None:
        return None

    def is_open_session_spread_allowed(self, _spread_pips: float) -> bool:
        return True

    def is_time_exit_disabled(self) -> bool:
        return False

    def load_position_state(self, position: Any) -> None:
        """Hydrate trailing state from a persisted position payload."""
        if getattr(position, "symbol", None) != self.symbol:
            return
        strategy_meta = dict(getattr(position, "strategy_meta", {}) or {})
        if not strategy_meta:
            return
        if strategy_meta.get("strategy") not in {None, "reversal_peaks"}:
            return
        self._trail_state = strategy_meta
        self.logger.info("[REVERSAL_PEAKS] Restored trailing state for %s: %s", self.symbol, self._trail_state)

    def update_trailing_stop(
        self,
        current_price: float,
        position: Any,
        current_atr: float,
    ) -> Optional[float]:
        """
        Update live trailing stop from persisted strategy state.

        Returns a tighter stop if one should be pushed to broker, otherwise None.
        """
        state = dict(getattr(position, "strategy_meta", {}) or self._trail_state or {})
        if not state:
            return None
        if state.get("strategy") not in {None, "reversal_peaks"}:
            return None
        if not np.isfinite(current_atr) or current_atr <= 0:
            return None

        current_sl = float(getattr(position, "stop_loss", 0.0) or 0.0)
        direction = getattr(position, "direction", None)
        is_long = direction == Direction.LONG

        activation_price = float(state.get("activation_price", 0.0) or 0.0)
        extreme_price = float(state.get("extreme_price", current_price) or current_price)
        trail_active = bool(state.get("trail_active", False))

        if not trail_active:
            if (is_long and current_price >= activation_price) or ((not is_long) and current_price <= activation_price):
                trail_active = True
                extreme_price = current_price
                self.logger.info("[REVERSAL_PEAKS] 1.5R trailing stop activated for %s", self.symbol)

        if not trail_active:
            return None

        if is_long:
            extreme_price = max(extreme_price, current_price)
            candidate_sl = extreme_price - (self.config.trailing_atr_mult * current_atr)
            if current_sl > 0:
                candidate_sl = max(candidate_sl, current_sl)
            if current_sl > 0 and candidate_sl <= current_sl:
                state["trail_active"] = trail_active
                state["extreme_price"] = extreme_price
                position.strategy_meta = state
                self._trail_state = state
                return None
        else:
            extreme_price = min(extreme_price, current_price)
            candidate_sl = extreme_price + (self.config.trailing_atr_mult * current_atr)
            if current_sl > 0:
                candidate_sl = min(candidate_sl, current_sl)
            if current_sl > 0 and candidate_sl >= current_sl:
                state["trail_active"] = trail_active
                state["extreme_price"] = extreme_price
                position.strategy_meta = state
                self._trail_state = state
                return None

        state["trail_active"] = trail_active
        state["extreme_price"] = extreme_price
        state["last_stop_loss"] = float(candidate_sl)
        state["updated_at"] = datetime.now(timezone.utc)
        position.strategy_meta = state
        self._trail_state = state
        return float(candidate_sl)

    async def analyze(
        self,
        historical_data: list[MarketData],
        current_positions: Optional[list[Any]] = None,
    ) -> Optional[TradingSignal]:
        """
        Live-compatible signal adapter for the reversal-peaks engine.

        The strategy triggers only on the latest confirmed bar after the pivot-right
        confirmation delay, keeping the live decision path zero-lookahead.
        """
        if not historical_data or len(historical_data) < 80:
            return None
        if current_positions:
            for position in current_positions:
                if getattr(position, "symbol", None) == self.symbol:
                    return None

        macro_reason = str(macro_risk_cache.get_macro_risk_reason(self.symbol) or "")
        macro_penalty = float(macro_risk_cache.get_macro_risk_penalty(self.symbol) or 0.0)
        macro_reason_upper = macro_reason.upper()
        volatility_ratio = self._current_volatility_ratio(historical_data)
        macro_high = (
            macro_penalty >= 0.25
            and any(token in macro_reason_upper for token in ("VOLATILITY", "EXTREME", "SPIKE", "SHOCK"))
            and volatility_ratio > 3.0
        )
        news_buffer_result = await self._check_news_buffer()
        if isinstance(news_buffer_result, tuple):
            news_buffer_active = bool(news_buffer_result[0]) if len(news_buffer_result) >= 1 else False
            news_reason = str(news_buffer_result[1]) if len(news_buffer_result) >= 2 else ""
        else:
            news_buffer_active = bool(news_buffer_result)
            news_reason = ""
        if macro_high or news_buffer_active:
            block_reason = news_reason if news_buffer_active else (
                f"{macro_reason or 'MacroRisk=HIGH'} | VolatilityRatio={volatility_ratio:.2f}x"
            )
            self.logger.warning(
                "[REVERSAL_PEAKS_BLOCKED] %s | Entry blocked due to high macro risk/news event: %s. "
                "Avoiding reversal entry to prevent catching a falling knife during volatility spikes.",
                self.symbol,
                block_reason,
            )
            return None

        try:
            features = self.prepare_features(self._build_dataframe(historical_data))
        except ImportError as exc:
            self.logger.error("[REVERSAL_PEAKS] %s | pandas_ta unavailable: %s", self.symbol, exc)
            return None
        except Exception as exc:
            self.logger.error("[REVERSAL_PEAKS] %s | Feature build failed: %s", self.symbol, exc)
            return None

        latest = features.iloc[-1]
        long_signal = bool(latest.get("long_entry_signal", False))
        short_signal = bool(latest.get("short_entry_signal", False))
        if long_signal == short_signal:
            return None

        entry_price = float(latest["close"])
        risk_fraction = float(self.config.risk_per_trade)

        if long_signal:
            direction = Direction.LONG
            stop_loss = float(latest.get("long_stop", np.nan))
            initial_risk = entry_price - stop_loss
            activation_price = entry_price + (self.config.activation_r_multiple * initial_risk)
            div_strength = float(latest.get("signal_bullish_divergence_strength", 0.0) or 0.0)
            band_excess = float(latest.get("long_band_excess", 0.0) or 0.0)
            volume_ratio = float(latest.get("signal_volume_ratio", 0.0) or 0.0)
            reason = "Bullish divergence + lower-band exhaustion + volume spike"
        else:
            direction = Direction.SHORT
            stop_loss = float(latest.get("short_stop", np.nan))
            initial_risk = stop_loss - entry_price
            activation_price = entry_price - (self.config.activation_r_multiple * initial_risk)
            div_strength = float(latest.get("signal_bearish_divergence_strength", 0.0) or 0.0)
            band_excess = float(latest.get("short_band_excess", 0.0) or 0.0)
            volume_ratio = float(latest.get("signal_volume_ratio", 0.0) or 0.0)
            reason = "Bearish divergence + upper-band exhaustion + volume spike"

        if not np.isfinite(stop_loss) or not np.isfinite(initial_risk) or initial_risk <= 0:
            return None

        confidence = 0.55
        confidence += 0.08 * min(max(volume_ratio - self.config.volume_spike_mult, 0.0), 1.5)
        confidence += 0.06 * min(max(band_excess, 0.0), 2.0)
        confidence += 0.01 * min(max(div_strength, 0.0), 8.0)
        confidence = self._clamp(confidence, 0.55, 0.88)

        self._trail_state = {
            "strategy": "reversal_peaks",
            "symbol": self.symbol,
            "entry_price": entry_price,
            "initial_stop": stop_loss,
            "trail_active": False,
            "extreme_price": entry_price,
            "activation_price": activation_price,
            "updated_at": datetime.now(timezone.utc),
        }

        signal = TradingSignal(
            symbol=self.symbol,
            direction=direction,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=activation_price,
            position_size=self._clamp(risk_fraction, 0.001, 1.0),
            confidence=confidence,
            reasoning=reason,
            timestamp=historical_data[-1].timestamp,
            rr_ratio=float(self.config.activation_r_multiple),
            trade_tier="TIER_A" if confidence >= 0.70 else "TIER_B",
            quality_score=round(confidence * 100.0, 2),
            exit_policy=ExitPolicy.TREND_FOLLOW,
            source="reversal_peaks",
        )
        setattr(signal, "strategy_meta", dict(self._trail_state))
        return signal

    def backtest(self, df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
        """
        Simulate trades using the vectorized entry arrays and a trade-by-trade exit engine.
        """
        features = self.prepare_features(df)
        cfg = self.config
        trades = []
        active_until = -1

        highs = features["high"].to_numpy(dtype=float)
        lows = features["low"].to_numpy(dtype=float)
        closes = features["close"].to_numpy(dtype=float)
        atr = features["atr"].to_numpy(dtype=float)
        entries_long = features.index[features["long_entry_signal"]].tolist()
        entries_short = features.index[features["short_entry_signal"]].tolist()

        entry_events = sorted(
            [(features.index.get_loc(idx), "LONG", idx) for idx in entries_long]
            + [(features.index.get_loc(idx), "SHORT", idx) for idx in entries_short],
            key=lambda x: x[0],
        )

        for entry_pos, side, entry_idx in entry_events:
            if entry_pos <= active_until:
                continue

            entry_price = closes[entry_pos]
            if side == "LONG":
                stop_price = float(features.iloc[entry_pos]["long_stop"])
                size = float(features.iloc[entry_pos]["long_position_size"])
            else:
                stop_price = float(features.iloc[entry_pos]["short_stop"])
                size = float(features.iloc[entry_pos]["short_position_size"])

            if not np.isfinite(stop_price) or not np.isfinite(size) or size <= 0:
                continue

            initial_risk = abs(entry_price - stop_price)
            if initial_risk <= 0:
                continue

            activation_price = (
                entry_price + cfg.activation_r_multiple * initial_risk
                if side == "LONG"
                else entry_price - cfg.activation_r_multiple * initial_risk
            )

            trail_active = False
            trail_stop = np.nan
            extreme_price = entry_price
            exit_price = closes[-1]
            exit_reason = "end_of_data"
            exit_pos = len(features) - 1

            for i in range(entry_pos + 1, len(features)):
                if side == "LONG":
                    if lows[i] <= stop_price:
                        exit_price = stop_price
                        exit_reason = "initial_stop"
                        exit_pos = i
                        break
                    if not trail_active and highs[i] >= activation_price:
                        trail_active = True
                        extreme_price = highs[i]
                    if trail_active:
                        extreme_price = max(extreme_price, highs[i])
                        trail_stop = extreme_price - (cfg.trailing_atr_mult * atr[i])
                        stop_price = max(stop_price, trail_stop)
                        if lows[i] <= stop_price:
                            exit_price = stop_price
                            exit_reason = "atr_trail"
                            exit_pos = i
                            break
                else:
                    if highs[i] >= stop_price:
                        exit_price = stop_price
                        exit_reason = "initial_stop"
                        exit_pos = i
                        break
                    if not trail_active and lows[i] <= activation_price:
                        trail_active = True
                        extreme_price = lows[i]
                    if trail_active:
                        extreme_price = min(extreme_price, lows[i])
                        trail_stop = extreme_price + (cfg.trailing_atr_mult * atr[i])
                        stop_price = min(stop_price, trail_stop)
                        if highs[i] >= stop_price:
                            exit_price = stop_price
                            exit_reason = "atr_trail"
                            exit_pos = i
                            break

            pnl_per_unit = (exit_price - entry_price) if side == "LONG" else (entry_price - exit_price)
            pnl_cash = pnl_per_unit * size
            r_multiple = pnl_per_unit / initial_risk if initial_risk > 0 else np.nan
            active_until = exit_pos

            trades.append(
                {
                    "entry_time": entry_idx,
                    "exit_time": features.index[exit_pos],
                    "side": side,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "initial_stop": float(
                        features.iloc[entry_pos]["long_stop"] if side == "LONG" else features.iloc[entry_pos]["short_stop"]
                    ),
                    "activation_price": activation_price,
                    "size": size,
                    "pnl_cash": pnl_cash,
                    "r_multiple": r_multiple,
                    "exit_reason": exit_reason,
                }
            )

        trades_df = pd.DataFrame(trades)
        return features, trades_df


if __name__ == "__main__":
    # Example usage:
    # df = pd.read_csv("your_ohlcv.csv", parse_dates=["time"]).set_index("time")
    # strategy = HighRewardReversalPeaksStrategy()
    # features, trades = strategy.backtest(df)
    # print(trades.tail())
    pass
