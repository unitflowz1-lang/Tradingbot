"""
Machine Learning Price Movement Predictor
Uses calibrated probabilities and meta-labeling to avoid fake confidence.
"""
import json
import numpy as np
import pandas as pd
from typing import List, Dict, Optional, Tuple
import logging
from datetime import datetime, timezone
import joblib
import os

from src.models import MarketData
from src.analysis.technical_indicators import TechnicalIndicators

try:
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score, brier_score_loss, log_loss
    from sklearn.preprocessing import StandardScaler
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

MIN_TRAIN_BARS = 500


class PriceMovementPredictor:
    """Predicts price movement using calibrated primary and meta models."""

    def __init__(self, symbol: str, horizon: int = 3, calibration_method: str = "sigmoid"):
        self.symbol = symbol
        self.horizon = horizon
        self.calibration_method = calibration_method if calibration_method in ("sigmoid", "isotonic") else "sigmoid"
        self.logger = logging.getLogger(__name__)
        self.model = None
        self.meta_model = None
        self.scaler = None
        self.is_trained = False
        self.metadata: Dict[str, object] = {}

        if SKLEARN_AVAILABLE:
            self.scaler = StandardScaler()
        else:
            self.logger.warning(
                "Scikit-learn not installed. ML Predictor will use simplified logic. "
                "Install with: pip install scikit-learn>=1.3.0"
            )

    @staticmethod
    def _detect_liquidity_sweep(
        historical_data: List[MarketData],
        index: int,
        lookback: int = 24,
    ) -> int:
        """
        Detect structural liquidity sweeps on bar `index`.
        Returns:
            +1: Bullish sweep (sweep below prior lows then close back above)
            -1: Bearish sweep (sweep above prior highs then close back below)
             0: No sweep
        """
        if index <= 0:
            return 0

        start = max(0, index - lookback)
        ref_window = historical_data[start:index]  # exclude current bar
        if len(ref_window) < 5:
            return 0

        current = historical_data[index]
        prev_lowest = min(bar.low for bar in ref_window)
        prev_highest = max(bar.high for bar in ref_window)

        # Rejection validation: wick piercing the level must be >= 1.5x candle body.
        body = abs(float(current.close) - float(current.open))
        body_ref = max(body, 1e-9)
        lower_wick = min(float(current.open), float(current.close)) - float(current.low)
        upper_wick = float(current.high) - max(float(current.open), float(current.close))

        bullish_sweep = (
            (current.low < prev_lowest)
            and (current.close > prev_lowest)
            and (lower_wick >= 1.5 * body_ref)
        )
        bearish_sweep = (
            (current.high > prev_highest)
            and (current.close < prev_highest)
            and (upper_wick >= 1.5 * body_ref)
        )

        if bullish_sweep and not bearish_sweep:
            return 1
        if bearish_sweep and not bullish_sweep:
            return -1
        return 0

    @staticmethod
    def _compute_absorption_ratio(candle: MarketData) -> float:
        """
        Volumetric absorption proxy:
        abs(Close - Open) / TickVolume
        Lower values during sweeps imply higher absorption.
        """
        tick_volume = float(max(1, int(getattr(candle, "volume", 0) or 0)))
        displacement = abs(float(candle.close) - float(candle.open))
        raw_ratio = displacement / tick_volume
        return float(np.log1p(raw_ratio))

    @staticmethod
    def _detect_displacement_mss(
        historical_data: List[MarketData],
        index: int,
        body_lookback: int = 20,
        engulf_bars: int = 3,
        body_multiplier: float = 2.0,
    ) -> int:
        """
        Displacement / MSS proxy:
        1 if current candle body exceeds `body_multiplier` x average body size
        of previous `body_lookback` and close is outside prior `engulf_bars` range.
        Otherwise 0.
        """
        if index < max(body_lookback, engulf_bars):
            return 0

        current = historical_data[index]
        prev_body_window = historical_data[index - body_lookback:index]
        avg_body = float(np.mean([abs(b.close - b.open) for b in prev_body_window])) if prev_body_window else 0.0
        current_body = abs(current.close - current.open)

        prev3 = historical_data[index - engulf_bars:index]
        prev3_high = max(b.high for b in prev3)
        prev3_low = min(b.low for b in prev3)
        close_outside_prev_range = (current.close > prev3_high) or (current.close < prev3_low)

        high_momentum = current_body > (body_multiplier * avg_body) if avg_body > 0 else False
        return 1 if (close_outside_prev_range and high_momentum) else 0

    def prepare_features(
        self,
        historical_data: List[MarketData],
        indicators_list: List[TechnicalIndicators],
        bars_since_last_loss: Optional[List[int]] = None,
    ) -> pd.DataFrame:
        """Convert market data and indicators into a feature matrix."""
        length = min(len(historical_data), len(indicators_list))
        if length == 0:
            return pd.DataFrame()

        atr_history: List[float] = []
        data = []
        for i in range(length):
            m = historical_data[i]
            ind = indicators_list[i]
            atr_val = float(ind.atr or 0.0)
            atr_history.append(atr_val)

            bb_denom = 0.0
            if ind.bollinger_upper and ind.bollinger_lower:
                bb_denom = ind.bollinger_upper - ind.bollinger_lower

            htf_window_start = max(0, i - 199)
            htf_closes = [bar.close for bar in historical_data[htf_window_start : i + 1]]
            htf_sma_200 = float(np.mean(htf_closes)) if htf_closes else m.close
            htf_trend = (m.close - htf_sma_200) / htf_sma_200 if htf_sma_200 else 0.0

            if i >= 3 and historical_data[i - 3].close != 0:
                ltf_momentum = (m.close - historical_data[i - 3].close) / historical_data[i - 3].close
            else:
                ltf_momentum = 0.0

            if abs(htf_trend) < 1e-8 or abs(ltf_momentum) < 1e-8:
                htf_alignment = 0
            else:
                htf_alignment = 1 if np.sign(htf_trend) == np.sign(ltf_momentum) else -1

            atr_ref = np.median(atr_history[max(0, i - 49) : i + 1]) if atr_history else 0.0
            vol_ratio = (atr_val / atr_ref) if atr_ref and atr_val else 1.0
            if vol_ratio >= 1.3:
                vol_state = 2  # high-vol regime
            elif vol_ratio <= 0.8:
                vol_state = 0  # low-vol regime
            else:
                vol_state = 1  # normal-vol regime

            if bars_since_last_loss and i < len(bars_since_last_loss):
                bsl = int(max(0, bars_since_last_loss[i]))
            else:
                bsl = 999

            features = {
                "rsi": ind.rsi or 50,
                "adx": ind.adx or 0,
                "w_r": ind.williams_r or -50,
                "macd_hist": ind.macd_histogram or 0,
                "bb_pos": ((m.close - ind.bollinger_lower) / bb_denom) if bb_denom else 0.5,
                "atr": atr_val,
                "htf_trend_alignment": htf_alignment,
                "bars_since_last_loss": bsl,
                "volatility_regime_state": vol_state,
                "is_liquidity_sweep": self._detect_liquidity_sweep(historical_data, i, lookback=24),
                "absorption_ratio": self._compute_absorption_ratio(m),
                "is_displacement_mss": self._detect_displacement_mss(
                    historical_data,
                    i,
                    body_lookback=20,
                    engulf_bars=3,
                    body_multiplier=2.0,
                ),
            }

            if i >= 5 and historical_data[i - 1].close and historical_data[i - 3].close and historical_data[i - 5].close:
                features["ret_1"] = (m.close - historical_data[i - 1].close) / historical_data[i - 1].close
                features["ret_3"] = (m.close - historical_data[i - 3].close) / historical_data[i - 3].close
                features["ret_5"] = (m.close - historical_data[i - 5].close) / historical_data[i - 5].close
            else:
                features["ret_1"] = 0.0
                features["ret_3"] = 0.0
                features["ret_5"] = 0.0

            data.append(features)

        return pd.DataFrame(data)

    def train(self, historical_data: List[MarketData], indicators_list: List[TechnicalIndicators]):
        """
        Train primary calibrated direction model and secondary calibrated meta-model.
        """
        if not SKLEARN_AVAILABLE:
            self.logger.warning("Skipping training: sklearn missing.")
            return
        if len(historical_data) < MIN_TRAIN_BARS:
            self.logger.warning(
                "Skipping training: insufficient data (%d/%d bars).",
                len(historical_data),
                MIN_TRAIN_BARS,
            )
            return

        try:
            df = self.prepare_features(historical_data, indicators_list)
            if df.empty:
                self.logger.warning("No features produced. Skipping training.")
                return

            closes = np.array([m.close for m in historical_data])
            targets = []
            for i in range(len(closes) - self.horizon):
                targets.append(1 if closes[i + self.horizon] > closes[i] else 0)

            X = df.iloc[: len(targets)].copy()
            y = np.array(targets, dtype=int)

            mask = np.isfinite(X.to_numpy()).all(axis=1)
            X = X.loc[mask].reset_index(drop=True)
            y = y[mask]
            if len(X) < MIN_TRAIN_BARS:
                self.logger.warning(
                    "Filtered dataset too small after cleanup (%d/%d).",
                    len(X),
                    MIN_TRAIN_BARS,
                )
                return

            n = len(X)
            base_end = int(n * 0.6)
            meta_end = int(n * 0.8)
            if base_end < 50 or (meta_end - base_end) < 15 or (n - meta_end) < 15:
                self.logger.warning("Insufficient split sizes for calibrated/meta training.")
                return

            X_base, y_base = X.iloc[:base_end], y[:base_end]
            X_meta, y_meta = X.iloc[base_end:meta_end], y[base_end:meta_end]
            X_test, y_test = X.iloc[meta_end:], y[meta_end:]

            X_base_scaled = self.scaler.fit_transform(X_base)
            X_meta_scaled = self.scaler.transform(X_meta)
            X_test_scaled = self.scaler.transform(X_test)

            base_clf = RandomForestClassifier(
                n_estimators=250,
                max_depth=10,
                min_samples_leaf=5,
                random_state=42,
                class_weight="balanced_subsample",
            )
            calib_cv = 3 if len(X_base) >= 120 else 2
            self.model = CalibratedClassifierCV(
                estimator=base_clf,
                method=self.calibration_method,
                cv=calib_cv,
            )
            self.model.fit(X_base_scaled, y_base)

            # Meta-labels: 1 if primary direction is correct, else 0.
            meta_primary_prob = self.model.predict_proba(X_meta_scaled)[:, 1]
            meta_primary_pred = (meta_primary_prob >= 0.5).astype(int)
            y_meta_label = (meta_primary_pred == y_meta).astype(int)

            self.meta_model = None
            if len(np.unique(y_meta_label)) > 1:
                meta_X = np.column_stack([
                    X_meta_scaled,
                    meta_primary_prob,
                    np.abs(meta_primary_prob - 0.5),
                ])
                meta_base = LogisticRegression(
                    max_iter=500,
                    class_weight="balanced",
                    random_state=42,
                )
                meta_cv = 3 if len(meta_X) >= 120 else 2
                self.meta_model = CalibratedClassifierCV(
                    estimator=meta_base,
                    method=self.calibration_method,
                    cv=meta_cv,
                )
                self.meta_model.fit(meta_X, y_meta_label)
            else:
                self.logger.warning("Meta labels are single-class. Meta model disabled for this training run.")

            primary_prob_test = self.model.predict_proba(X_test_scaled)[:, 1]
            primary_pred_test = (primary_prob_test >= 0.5).astype(int)
            primary_acc = accuracy_score(y_test, primary_pred_test)
            primary_brier = brier_score_loss(y_test, primary_prob_test)
            primary_log_loss = log_loss(y_test, np.column_stack([1.0 - primary_prob_test, primary_prob_test]))

            meta_acc = None
            if self.meta_model is not None:
                meta_X_test = np.column_stack([
                    X_test_scaled,
                    primary_prob_test,
                    np.abs(primary_prob_test - 0.5),
                ])
                y_meta_test = (primary_pred_test == y_test).astype(int)
                meta_prob_test = self.meta_model.predict_proba(meta_X_test)[:, 1]
                meta_pred_test = (meta_prob_test >= 0.5).astype(int)
                meta_acc = float(accuracy_score(y_meta_test, meta_pred_test))

            probe_model = RandomForestClassifier(
                n_estimators=200,
                max_depth=10,
                min_samples_leaf=5,
                random_state=42,
            )
            probe_model.fit(X_base_scaled, y_base)
            importances = probe_model.feature_importances_
            feature_names = X.columns.tolist()
            sorted_features = dict(
                sorted(
                    zip(feature_names, importances),
                    key=lambda item: item[1],
                    reverse=True,
                )
            )
            ranked_features = list(sorted_features.items())
            structural_feature_set = ("is_liquidity_sweep", "absorption_ratio", "is_displacement_mss")
            structural_feature_ranks = {}
            for feat in structural_feature_set:
                rank = next((idx + 1 for idx, (name, _) in enumerate(ranked_features) if name == feat), None)
                importance = float(sorted_features.get(feat, 0.0))
                structural_feature_ranks[feat] = {
                    "rank": rank,
                    "importance": importance,
                }

            self.is_trained = True
            self.metadata = {
                "trained_at": datetime.now(timezone.utc).isoformat(),
                "accuracy_score": float(primary_acc),
                "brier_score": float(primary_brier),
                "log_loss": float(primary_log_loss),
                "meta_accuracy_score": meta_acc,
                "meta_model_enabled": self.meta_model is not None,
                "training_samples": int(len(X_base)),
                "meta_samples": int(len(X_meta)),
                "test_samples": int(len(X_test)),
                "calibration_method": self.calibration_method,
                "top_features": dict(list(sorted_features.items())[:10]),
                "structural_feature_ranks": structural_feature_ranks,
                "feature_names": feature_names,
            }

            top_feat = next(iter(sorted_features.keys()), "n/a")
            self.logger.info(
                f"ML Model for {self.symbol} trained | Acc: {primary_acc:.2%} | "
                f"Brier: {primary_brier:.4f} | Calib: {self.calibration_method} | Top feature: {top_feat}"
            )

        except Exception as e:
            self.logger.error(f"Failed to train ML model for {self.symbol}: {e}")
            self.is_trained = False

    def save_model(self, filepath: str):
        """Save model, meta model, scaler, and metadata."""
        if not self.is_trained or self.model is None:
            self.logger.warning(f"Cannot save model for {self.symbol}: model not trained.")
            return

        try:
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            data_to_save = {
                "model": self.model,
                "meta_model": self.meta_model,
                "scaler": self.scaler,
                "metadata": self.metadata,
            }
            joblib.dump(data_to_save, filepath)

            json_path = filepath.replace(".pkl", "_meta.json")
            try:
                with open(json_path, "w") as f:
                    json.dump(self.metadata, f, indent=2)
            except Exception as json_err:
                self.logger.warning(f"Could not save metadata JSON: {json_err}")

            self.logger.info(f"ML model saved to {filepath}")
        except Exception as e:
            self.logger.error(f"Failed to save model to {filepath}: {e}")

    def reset(self, filepath: Optional[str] = None, remove_persisted: bool = False) -> None:
        """
        Clear the in-memory model state and optionally remove the persisted bundle.
        This is used when startup detects the model was trained on stale data.
        """
        self.model = None
        self.meta_model = None
        self.is_trained = False
        self.metadata = {}
        if SKLEARN_AVAILABLE:
            self.scaler = StandardScaler()
        else:
            self.scaler = None

        if remove_persisted and filepath:
            for path in (filepath, filepath.replace(".pkl", "_meta.json")):
                try:
                    if os.path.exists(path):
                        os.remove(path)
                except Exception as exc:
                    self.logger.warning("Failed to remove stale model artifact %s: %s", path, exc)

        self.logger.warning("ML model reset for %s", self.symbol)

    def load_model(self, filepath: str) -> bool:
        """Load model bundle. Supports legacy model files without meta model."""
        if not os.path.exists(filepath):
            return False

        try:
            data = joblib.load(filepath)
            self.model = data.get("model")
            self.meta_model = data.get("meta_model")
            self.scaler = data.get("scaler", self.scaler)
            self.metadata = data.get("metadata", {})
            self.calibration_method = self.metadata.get("calibration_method", self.calibration_method)
            self.is_trained = self.model is not None and self.scaler is not None

            acc = float(self.metadata.get("accuracy_score", 0.0))
            date = self.metadata.get("trained_at", "Unknown")
            self.logger.info(
                f"ML model loaded from {filepath} (Acc: {acc:.2%}, Date: {date}, Meta: {self.meta_model is not None})"
            )
            return self.is_trained
        except Exception as e:
            self.logger.error(f"Failed to load model from {filepath}: {e}")
            return False

    def _prepare_latest_feature_row(
        self,
        historical_data: List[MarketData],
        indicators: TechnicalIndicators,
        bars_since_last_loss: Optional[int] = None,
    ) -> pd.DataFrame:
        """Build a single-row feature frame for inference."""
        if not historical_data:
            return pd.DataFrame()

        m = historical_data[-1]
        prev1 = historical_data[-2].close if len(historical_data) >= 2 else m.close
        prev3 = historical_data[-4].close if len(historical_data) >= 4 else m.close
        prev5 = historical_data[-6].close if len(historical_data) >= 6 else m.close

        htf_closes = [bar.close for bar in historical_data[-200:]]
        htf_sma_200 = float(np.mean(htf_closes)) if htf_closes else m.close
        htf_trend = (m.close - htf_sma_200) / htf_sma_200 if htf_sma_200 else 0.0
        ltf_momentum = (m.close - prev3) / prev3 if prev3 else 0.0
        if abs(htf_trend) < 1e-8 or abs(ltf_momentum) < 1e-8:
            htf_alignment = 0
        else:
            htf_alignment = 1 if np.sign(htf_trend) == np.sign(ltf_momentum) else -1

        atr_val = float(indicators.atr or 0.0)
        if len(historical_data) >= 50:
            tr_values = []
            for i in range(1, len(historical_data[-60:])):
                c = historical_data[-60:][i]
                p = historical_data[-60:][i - 1]
                tr = max(c.high - c.low, abs(c.high - p.close), abs(c.low - p.close))
                tr_values.append(tr)
            atr_ref = float(np.median(tr_values[-50:])) if tr_values else 0.0
        else:
            atr_ref = atr_val
        vol_ratio = (atr_val / atr_ref) if atr_ref and atr_val else 1.0
        if vol_ratio >= 1.3:
            vol_state = 2
        elif vol_ratio <= 0.8:
            vol_state = 0
        else:
            vol_state = 1

        bb_denom = 0.0
        if indicators.bollinger_upper and indicators.bollinger_lower:
            bb_denom = indicators.bollinger_upper - indicators.bollinger_lower

        row = {
            "rsi": indicators.rsi or 50,
            "adx": indicators.adx or 0,
            "w_r": indicators.williams_r or -50,
            "macd_hist": indicators.macd_histogram or 0,
            "bb_pos": ((m.close - indicators.bollinger_lower) / bb_denom) if bb_denom else 0.5,
            "atr": atr_val,
            "ret_1": ((m.close - prev1) / prev1) if prev1 else 0.0,
            "ret_3": ((m.close - prev3) / prev3) if prev3 else 0.0,
            "ret_5": ((m.close - prev5) / prev5) if prev5 else 0.0,
            "htf_trend_alignment": htf_alignment,
            "bars_since_last_loss": int(max(0, bars_since_last_loss if bars_since_last_loss is not None else 999)),
            "volatility_regime_state": vol_state,
            "is_liquidity_sweep": self._detect_liquidity_sweep(historical_data, len(historical_data) - 1, lookback=24),
            "absorption_ratio": self._compute_absorption_ratio(m),
            "is_displacement_mss": self._detect_displacement_mss(
                historical_data,
                len(historical_data) - 1,
                body_lookback=20,
                engulf_bars=3,
                body_multiplier=2.0,
            ),
        }

        df = pd.DataFrame([row])
        expected = self.metadata.get("feature_names", [])
        if expected:
            for col in expected:
                if col not in df.columns:
                    df[col] = 0.0
            df = df[expected]
        return df.replace([np.inf, -np.inf], 0.0).fillna(0.0)

    def predict(
        self,
        historical_data: List[MarketData],
        indicators: TechnicalIndicators,
        bars_since_last_loss: Optional[int] = None,
    ) -> Tuple[int, float]:
        """
        Predict direction for next bars.
        Returns: (Direction [1 for Up, 0 for Down], Confidence [0.0 to 1.0])
        """
        direction, confidence, _ = self.predict_with_details(
            historical_data=historical_data,
            indicators=indicators,
            bars_since_last_loss=bars_since_last_loss,
        )
        return direction, confidence

    def predict_with_details(
        self,
        historical_data: List[MarketData],
        indicators: TechnicalIndicators,
        bars_since_last_loss: Optional[int] = None,
        short_horizon_bars: Optional[int] = None,
    ) -> Tuple[int, float, Dict[str, float]]:
        """
        Predict with diagnostic probabilities.
        Returns: (direction, final_confidence, details)
        """
        if not self.is_trained or not SKLEARN_AVAILABLE or self.model is None or self.scaler is None:
            score = 0
            if indicators.rsi and indicators.rsi < 40:
                score += 1
            if indicators.rsi and indicators.rsi > 60:
                score -= 1
            if indicators.macd_histogram and indicators.macd_histogram > 0:
                score += 1
            else:
                score -= 1

            direction = 1 if score >= 0 else 0
            confidence = min(0.5 + (abs(score) / 4.0), 1.0)
            details = {
                "primary_prob_up": float(confidence if direction == 1 else 1.0 - confidence),
                "directional_confidence": float(confidence),
                "meta_win_prob": 1.0,
                "calibrated_confidence": float(confidence),
            }
            return direction, confidence, details

        df = self._prepare_latest_feature_row(historical_data, indicators, bars_since_last_loss=bars_since_last_loss)
        if df.empty:
            return 1, 0.5, {
                "primary_prob_up": 0.5,
                "directional_confidence": 0.5,
                "meta_win_prob": 0.5,
                "calibrated_confidence": 0.5,
            }

        try:
            X_scaled = self.scaler.transform(df)
            primary_prob_up = float(self.model.predict_proba(X_scaled)[0, 1])
            direction = 1 if primary_prob_up >= 0.5 else 0
            directional_conf = primary_prob_up if direction == 1 else (1.0 - primary_prob_up)

            win_prob = 1.0
            if self.meta_model is not None:
                meta_X = np.column_stack([X_scaled, [primary_prob_up], [abs(primary_prob_up - 0.5)]])
                win_prob = float(self.meta_model.predict_proba(meta_X)[0, 1])
                confidence = max(0.0, min(1.0, (directional_conf * 0.65) + (win_prob * 0.35)))
            else:
                confidence = max(0.0, min(1.0, directional_conf))

            confidence = self._stabilize_confidence(
                confidence=confidence,
                directional_conf=directional_conf,
                win_prob=win_prob,
                direction=direction,
                historical_data=historical_data,
                indicators=indicators,
                bars_since_last_loss=bars_since_last_loss,
            )

            # Optional short-horizon recalibration to combat stale confidence regimes.
            if short_horizon_bars and short_horizon_bars >= 20 and len(historical_data) >= short_horizon_bars:
                recent = historical_data[-short_horizon_bars:]
                recent_closes = np.array([float(b.close) for b in recent], dtype=float)
                if len(recent_closes) >= 10 and recent_closes[0] != 0:
                    drift = float((recent_closes[-1] - recent_closes[0]) / abs(recent_closes[0]))
                    realized_vol = float(np.std(np.diff(recent_closes) / recent_closes[:-1])) if len(recent_closes) > 1 else 0.0
                    trend_strength = abs(drift) / max(realized_vol, 1e-6)
                    horizon_conf = max(0.5, min(0.85, 0.5 + min(0.35, trend_strength * 0.05)))
                    if (drift >= 0 and direction == 1) or (drift < 0 and direction == 0):
                        confidence = max(confidence, horizon_conf)
                    details_horizon = {
                        "short_horizon_bars": int(short_horizon_bars),
                        "short_horizon_confidence": float(horizon_conf),
                        "short_horizon_drift": float(drift),
                    }
                else:
                    details_horizon = {"short_horizon_bars": int(short_horizon_bars)}
            else:
                details_horizon = {}

            details = {
                "primary_prob_up": primary_prob_up,
                "directional_confidence": float(directional_conf),
                "meta_win_prob": float(win_prob),
                "calibrated_confidence": float(confidence),
            }
            details.update(details_horizon)
            return direction, confidence, details
        except Exception as e:
            self.logger.error(f"Prediction error for {self.symbol}: {e}")
            return 1, 0.5, {
                "primary_prob_up": 0.5,
                "directional_confidence": 0.5,
                "meta_win_prob": 0.5,
                "calibrated_confidence": 0.5,
            }

    def _stabilize_confidence(
        self,
        *,
        confidence: float,
        directional_conf: float,
        win_prob: float,
        direction: int,
        historical_data: List[MarketData],
        indicators: TechnicalIndicators,
        bars_since_last_loss: Optional[int],
    ) -> float:
        """
        Blend model output with live market context so confidence remains
        responsive instead of collapsing into a low, nearly static value.
        """
        closes = np.array([float(bar.close) for bar in historical_data[-20:]], dtype=float)
        returns = np.diff(closes) / closes[:-1] if len(closes) > 1 else np.array([], dtype=float)
        realized_vol = float(np.std(returns)) if len(returns) > 0 else 0.0
        drift = float((closes[-1] - closes[0]) / closes[0]) if len(closes) > 1 and closes[0] else 0.0
        drift_alignment = 1.0 if ((drift >= 0 and direction == 1) or (drift < 0 and direction == 0)) else 0.0

        adx = float(getattr(indicators, "adx", 0.0) or 0.0)
        rsi = float(getattr(indicators, "rsi", 50.0) or 50.0)
        atr = float(getattr(indicators, "atr", 0.0) or 0.0)
        price = float(closes[-1]) if len(closes) else 0.0

        trend_component = min(1.0, adx / 35.0)
        volatility_component = min(1.0, (atr / price) * 1200.0) if price > 0 and atr > 0 else min(1.0, realized_vol * 300.0)
        momentum_component = min(1.0, abs(rsi - 50.0) / 25.0)

        live_context = (
            (trend_component * 0.35)
            + (volatility_component * 0.20)
            + (momentum_component * 0.20)
            + (drift_alignment * 0.15)
        )
        if bars_since_last_loss is not None:
            live_context += min(0.10, max(0.0, float(bars_since_last_loss)) / 200.0)

        live_context = max(0.0, min(1.0, live_context))
        stabilized = (confidence * 0.60) + (directional_conf * 0.15) + (win_prob * 0.10) + (live_context * 0.15)
        return float(max(0.05, min(0.95, stabilized)))
