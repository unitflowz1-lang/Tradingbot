import logging
from typing import Dict

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class PriceActionMath:
    """
    Convert OHLCV data into normalized mathematical price-action features.

    Expected columns:
    - open, high, low, close
    - tick_volume or volume
    """

    REQUIRED_COLUMNS = {"open", "high", "low", "close"}

    @staticmethod
    def _resolve_volume_column(df: pd.DataFrame) -> str:
        if "tick_volume" in df.columns:
            return "tick_volume"
        if "volume" in df.columns:
            return "volume"
        return "tick_volume"

    @staticmethod
    def _rolling_linear_regression_slope(values: pd.Series, window: int) -> np.ndarray:
        arr = values.to_numpy(dtype=float, copy=False)
        n = len(arr)
        if n == 0:
            return np.array([], dtype=float)
        if n < window:
            return np.zeros(n, dtype=float)

        x = np.arange(window, dtype=float)
        sum_x = float(x.sum())
        sum_x2 = float((x * x).sum())
        denom = (window * sum_x2) - (sum_x * sum_x)
        if abs(denom) < 1e-12:
            return np.zeros(n, dtype=float)

        sum_y = np.convolve(arr, np.ones(window, dtype=float), mode="valid")
        sum_xy = np.convolve(arr, x[::-1], mode="valid")
        slope_valid = ((window * sum_xy) - (sum_x * sum_y)) / denom

        out = np.zeros(n, dtype=float)
        out[window - 1 :] = slope_valid
        return out

    @staticmethod
    def _hurst_exponent(window_values: np.ndarray) -> float:
        arr = np.asarray(window_values, dtype=float)
        if arr.size < 10:
            return 0.5
        if np.allclose(arr, arr[0], atol=1e-12):
            return 0.5

        candidate_lags = np.array([2, 4, 8], dtype=int)
        lags = candidate_lags[candidate_lags < arr.size]
        if lags.size < 2:
            return 0.5

        tau = []
        valid_lags = []
        for lag in lags:
            diff = arr[lag:] - arr[:-lag]
            std = float(np.std(diff))
            if std > 1e-12:
                tau.append(np.sqrt(std))
                valid_lags.append(lag)

        if len(valid_lags) < 2:
            return 0.5

        slope, _ = np.polyfit(np.log(valid_lags), np.log(tau), 1)
        return float(np.clip(slope * 2.0, 0.0, 1.0))

    @staticmethod
    def _forecast_breakout_probabilities(df: pd.DataFrame) -> pd.DataFrame:
        bullish_pattern = df["bullish_pin_bar"].astype(int)
        bearish_pattern = df["bearish_pin_bar"].astype(int)

        bullish_success = (
            (bullish_pattern.shift(1).fillna(0).astype(int) == 1)
            & (df["close"] > df["high"].shift(1).fillna(df["close"]))
        ).astype(int)
        bearish_success = (
            (bearish_pattern.shift(1).fillna(0).astype(int) == 1)
            & (df["close"] < df["low"].shift(1).fillna(df["close"]))
        ).astype(int)

        bullish_occ = bullish_pattern.shift(1).fillna(0).astype(int).cumsum()
        bearish_occ = bearish_pattern.shift(1).fillna(0).astype(int).cumsum()
        bullish_succ = bullish_success.cumsum()
        bearish_succ = bearish_success.cumsum()

        # Beta(1,1) prior to avoid unstable 0/1 outputs.
        df["bullish_breakout_prob"] = np.where(
            bullish_pattern == 1,
            (bullish_succ + 1.0) / (bullish_occ + 2.0),
            0.5,
        )
        df["bearish_breakout_prob"] = np.where(
            bearish_pattern == 1,
            (bearish_succ + 1.0) / (bearish_occ + 2.0),
            0.5,
        )
        return df

    @staticmethod
    def extract_features(df: pd.DataFrame) -> pd.DataFrame:
        """
        Append mathematical price-action features to an OHLCV dataframe.
        Returns a dataframe with no NaN values.
        """
        if df is None or df.empty:
            return df

        missing = PriceActionMath.REQUIRED_COLUMNS.difference(df.columns)
        if missing:
            logger.warning("[PRICE_ACTION_MATH] Missing required columns: %s", sorted(missing))
            return df.copy()

        out = df.copy()
        volume_col = PriceActionMath._resolve_volume_column(out)
        if volume_col not in out.columns:
            out[volume_col] = 0.0

        numeric_cols = ["open", "high", "low", "close", volume_col]
        for col in numeric_cols:
            out[col] = pd.to_numeric(out[col], errors="coerce").astype(float)

        body_signed = out["close"] - out["open"]
        body = body_signed.abs()
        candle_range = (out["high"] - out["low"]).abs()
        safe_range = np.where(candle_range <= 1e-12, 1e-6, candle_range)
        upper_wick = (out["high"] - out[["open", "close"]].max(axis=1)).clip(lower=0.0)
        lower_wick = (out[["open", "close"]].min(axis=1) - out["low"]).clip(lower=0.0)
        safe_body = np.where(body <= 1e-12, 1e-6, body)

        out["range"] = safe_range
        out["body"] = body
        out["upper_wick"] = upper_wick
        out["lower_wick"] = lower_wick
        out["body_ratio"] = np.clip(body / safe_range, 0.0, 1.0)
        out["upper_wick_ratio"] = np.clip(upper_wick / safe_range, 0.0, 1.0)
        out["lower_wick_ratio"] = np.clip(lower_wick / safe_range, 0.0, 1.0)
        out["upper_wick_to_body"] = upper_wick / safe_body
        out["lower_wick_to_body"] = lower_wick / safe_body

        vol_avg_20 = out[volume_col].rolling(window=20, min_periods=1).mean()
        rel_volume = out[volume_col] / np.where(vol_avg_20 <= 1e-12, 1.0, vol_avg_20)
        volume_multiplier = np.clip(rel_volume, 0.25, 3.0)

        out["vol_avg_20"] = vol_avg_20
        out["rel_volume"] = rel_volume
        out["bullish_rejection_score"] = out["lower_wick_ratio"] * (1.0 - out["body_ratio"]) * volume_multiplier
        out["bearish_rejection_score"] = out["upper_wick_ratio"] * (1.0 - out["body_ratio"]) * volume_multiplier

        rolling_body_avg = body.rolling(window=3, min_periods=1).mean().shift(1)
        rolling_body_avg = rolling_body_avg.fillna(body.rolling(window=3, min_periods=1).mean())
        out["rolling_body_avg"] = rolling_body_avg
        out["body_expansion_ratio"] = body / np.where(rolling_body_avg <= 1e-12, 1e-6, rolling_body_avg)
        out["direction"] = np.sign(body_signed)
        out["momentum_strike"] = out["body_expansion_ratio"] * out["direction"]

        out["bullish_pin_bar"] = (
            (out["body_ratio"] < 0.20)
            & (out["lower_wick_to_body"] >= 3.0)
            & (out["lower_wick_ratio"] > out["upper_wick_ratio"])
        ).astype(int)
        out["bearish_pin_bar"] = (
            (out["body_ratio"] < 0.20)
            & (out["upper_wick_to_body"] >= 3.0)
            & (out["upper_wick_ratio"] > out["lower_wick_ratio"])
        ).astype(int)

        close_series = out["close"].astype(float)
        slope_5 = PriceActionMath._rolling_linear_regression_slope(close_series, 5)
        slope_10 = PriceActionMath._rolling_linear_regression_slope(close_series, 10)
        close_scale_5 = close_series.rolling(window=5, min_periods=1).mean().abs().to_numpy()
        close_scale_10 = close_series.rolling(window=10, min_periods=1).mean().abs().to_numpy()
        out["micro_trend_slope_5"] = slope_5 / np.where(close_scale_5 <= 1e-12, 1.0, close_scale_5)
        out["micro_trend_slope_10"] = slope_10 / np.where(close_scale_10 <= 1e-12, 1.0, close_scale_10)
        out["micro_trend_vector"] = (0.6 * out["micro_trend_slope_5"]) + (0.4 * out["micro_trend_slope_10"])

        prev_close = out["close"].shift(1)
        out["log_return_1"] = np.log(
            np.where((out["close"] > 0) & (prev_close > 0), out["close"] / prev_close, 1.0)
        )
        out["log_return_3"] = out["log_return_1"].rolling(window=3, min_periods=1).sum()
        realized_vol_10 = out["log_return_1"].rolling(window=10, min_periods=1).std(ddof=0)
        realized_vol_20 = out["log_return_1"].rolling(window=20, min_periods=1).std(ddof=0)
        out["realized_vol_10"] = realized_vol_10
        out["realized_vol_20"] = realized_vol_20
        out["volatility_norm_10"] = realized_vol_10 / np.where(realized_vol_20 <= 1e-12, 1.0, realized_vol_20)
        out["kurtosis_14"] = out["log_return_1"].rolling(window=14, min_periods=5).kurt()
        signed_volume = np.sign(out["log_return_1"]).replace(0.0, np.nan).ffill().fillna(0.0) * out[volume_col]
        total_volume_14 = out[volume_col].rolling(window=14, min_periods=1).sum()
        out["vpin_toxicity"] = signed_volume.abs().rolling(window=14, min_periods=1).sum() / np.where(total_volume_14 <= 1e-12, 1.0, total_volume_14)

        pos_vol = out["log_return_1"].clip(lower=0.0).rolling(window=14, min_periods=1).std(ddof=0)
        neg_vol = out["log_return_1"].clip(upper=0.0).abs().rolling(window=14, min_periods=1).std(ddof=0)
        out["rvi_14"] = 100.0 * pos_vol / np.where((pos_vol + neg_vol) <= 1e-12, 1.0, (pos_vol + neg_vol))
        out["rvi_bias"] = (out["rvi_14"] - 50.0) / 50.0

        out["hurst_exponent_20"] = (
            out["close"].rolling(window=20, min_periods=10).apply(PriceActionMath._hurst_exponent, raw=True)
        )

        out = PriceActionMath._forecast_breakout_probabilities(out)

        bullish_attack = (
            0.40 * np.clip(out["bullish_rejection_score"] / 2.0, 0.0, 1.0)
            + 0.20 * np.clip(out["body_expansion_ratio"] / 3.0, 0.0, 1.0)
            + 0.20 * np.clip((out["micro_trend_vector"] * 100.0 + 1.0) / 2.0, 0.0, 1.0)
            + 0.20 * np.clip(out["bullish_breakout_prob"], 0.0, 1.0)
        )
        bearish_attack = (
            0.40 * np.clip(out["bearish_rejection_score"] / 2.0, 0.0, 1.0)
            + 0.20 * np.clip((-out["momentum_strike"] + 1.0) / 3.0, 0.0, 1.0)
            + 0.20 * np.clip(((-out["micro_trend_vector"]) * 100.0 + 1.0) / 2.0, 0.0, 1.0)
            + 0.20 * np.clip(out["bearish_breakout_prob"], 0.0, 1.0)
        )
        out["bullish_attack_score"] = np.clip(bullish_attack, 0.0, 1.0)
        out["bearish_attack_score"] = np.clip(bearish_attack, 0.0, 1.0)
        out["price_action_score"] = out["bullish_attack_score"] - out["bearish_attack_score"]

        out.replace([np.inf, -np.inf], 0.0, inplace=True)
        out.fillna(0.0, inplace=True)
        return out

    @staticmethod
    def extract_price_action_features(df: pd.DataFrame) -> pd.DataFrame:
        return PriceActionMath.extract_features(df)

    @staticmethod
    def get_attack_signal(df: pd.DataFrame) -> Dict[str, float]:
        """
        Return an immediate attack/hold decision from the latest completed candle.
        Confidence is returned in percentage terms for easier logging.
        """
        if df is None or df.empty:
            return {"action": "HOLD", "confidence": 0.0, "type": "NONE", "probability": 0.5, "score": 0.0}

        enriched = PriceActionMath.extract_features(df)
        latest = enriched.iloc[-1]

        bullish_prob = float(latest.get("bullish_breakout_prob", 0.5) or 0.5)
        bearish_prob = float(latest.get("bearish_breakout_prob", 0.5) or 0.5)
        bullish_score = float(latest.get("bullish_attack_score", 0.0) or 0.0)
        bearish_score = float(latest.get("bearish_attack_score", 0.0) or 0.0)

        if bullish_prob >= 0.65 and bullish_score >= bearish_score:
            confidence = max(bullish_prob, bullish_score) * 100.0
            return {
                "action": "LONG",
                "confidence": confidence,
                "type": "MATH_REJECTION",
                "probability": bullish_prob,
                "score": bullish_score,
            }

        if bearish_prob >= 0.65 and bearish_score > bullish_score:
            confidence = max(bearish_prob, bearish_score) * 100.0
            return {
                "action": "SHORT",
                "confidence": confidence,
                "type": "MATH_REJECTION",
                "probability": bearish_prob,
                "score": bearish_score,
            }

        return {
            "action": "HOLD",
            "confidence": 0.0,
            "type": "NONE",
            "probability": max(bullish_prob, bearish_prob),
            "score": float(latest.get("price_action_score", 0.0) or 0.0),
        }


extract_price_action_features = PriceActionMath.extract_price_action_features
