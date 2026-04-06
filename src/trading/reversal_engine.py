"""
Reversal Detection and Execution Module
========================================

Highly optimized, vectorized, zero-lookahead Reversal Engine for institutional Forex bot.
Detects high-probability market exhaustion zones and executes strictly on confirmed momentum shifts.
Integrates with Selective Risk Handling (SRH) system for dynamic regime-based thresholds.

Core Features:
  - Vectorized Analysis: Strict zero-lookahead with pandas vectorization
  - Feature Extraction: Divergence, Trend Exhaustion, Market Structure BOS, Price Action, Climax
  - Dynamic Regime Thresholds: RANGING, HIGH_VOL, STRONG_TREND regimes
  - Multi-Timeframe Integration: HTF trend alignment checks
  - Priority-Based Exit Management: Offensive profit-taking + Defensive structural bailouts
  - Anti-Compression Logic: Penalty clamping prevents over-penalizing elite setups

Author: Reversal Engine Team
Version: 1.0.0
"""

import pandas as pd
from dataclasses import dataclass, asdict, field
import logging
from typing import Optional, Dict, Tuple, Any

# System Logging Setup
logger = logging.getLogger("ReversalEngine")
if not logger.handlers:
    logging.basicConfig(
        format='%(asctime)s | %(levelname)s | %(message)s',
        datefmt='%H:%M:%S',
        level=logging.INFO
    )


@dataclass
class ReversalDecision:
    """
    Reversal Engine decision output.
    JSON-serializable dataclass for clean API integration.
    """
    action: str  # "BUY", "SELL", "NO_TRADE"
    confidence: float  # [0.0, 1.0] - exponential confidence
    reversal_score: float  # [0.0, 1.0] - base composite score
    entry_type: str  # "aggressive" (>0.75), "conservative", "none"
    reason: str  # Signal composition or veto reason
    risk_adjustment: float  # Risk multiplier from SRH.get_waterfall_multiplier()

    def to_dict(self) -> Dict:
        """Convert to JSON-serializable dict."""
        return asdict(self)


@dataclass
class ExitDecision:
    """
    Priority-based exit decision from ReversalExitManager.
    """
    action: str  # "CLOSE_FULL", "CLOSE_PARTIAL_50", "MOVE_SL_BE", "HOLD"
    reason: str  # Reason for exit decision


@dataclass
class SignatureStats:
    wins: int = 0
    losses: int = 0

    @property
    def total(self) -> int:
        return self.wins + self.losses

    @property
    def win_rate(self) -> float:
        return self.wins / self.total if self.total else 0.0


@dataclass(frozen=True)
class ReversalConfig:
    # --- SCORING WEIGHTS ---
    W_DIV: float = 0.35
    W_EXH: float = 0.20
    W_STR: float = 0.15
    W_PA: float = 0.15
    W_CLX: float = 0.15

    # --- DIVERGENCE / MOMENTUM ---
    RSI_DELTA_MIN_BY_TF: Dict[str, float] = field(default_factory=lambda: {
        "M5": 6.5,
        "M15": 5.0,
    })
    MOMENTUM_SHIFT_DELTA_BY_TF: Dict[str, float] = field(default_factory=lambda: {
        "M5": 3.5,
        "M15": 3.0,
    })

    # --- EXHAUSTION ---
    RSI_OVERBOUGHT: float = 75.0
    RSI_OVERSOLD: float = 25.0
    EMA_ATR_MULT_BASE: float = 2.5
    EMA_ATR_MULT_BY_SYMBOL: Dict[str, float] = field(default_factory=lambda: {
        "EUR/USD": 2.35,
        "USD/CHF": 2.35,
        "AUD/USD": 2.45,
        "USD/CAD": 2.50,
        "USD/JPY": 2.60,
        "GBP/USD": 2.70,
        "EUR/JPY": 2.75,
        "GBP/JPY": 2.95,
        "XAU/USD": 3.10,
    })

    # --- REGIME THRESHOLDS ---
    THRESH_RANGING: float = 0.55
    THRESH_VOLATILE: float = 0.65

    # --- ADX GRADIENTS ---
    ADX_BANDS_BY_REGIME: Dict[str, Tuple[float, float, float]] = field(default_factory=lambda: {
        "RANGING": (18.0, 24.0, 32.0),
        "HIGH_VOL": (22.0, 28.0, 35.0),
        "VOLATILE": (22.0, 28.0, 35.0),
    })
    ADX_PENALTY_1: float = 0.90
    ADX_PENALTY_2: float = 0.80

    # --- BONUSES / PENALTIES ---
    LIQ_SWEEP_BONUS: float = 1.15
    MOMENTUM_PENALTY: float = 0.88
    WEAK_STRUCTURE_PENALTY: float = 0.74
    SPREAD_PENALTY: float = 0.88
    SESSION_ASIA_PENALTY: float = 0.92
    LOW_WIN_RATE_SIGNATURE_PENALTY: float = 0.90
    SIGNATURE_MIN_WIN_RATE: float = 0.40
    SIGNATURE_MIN_SAMPLES: int = 5

    # --- PENALTY CLAMPING ---
    MAX_TOTAL_PENALTY: float = 0.45
    CONFIDENCE_FLOOR: float = 0.55

    # --- EXIT LOGIC ---
    SCALE_OUT_R: float = 1.0
    FREE_RIDE_R: float = 1.5
    FORCE_EXIT_AFTER_BARS: int = 12
    STRUCTURAL_FAILURE_MULT: float = 1.5
    RSI_NEUTRAL_EXIT_LONG: float = 45.0
    RSI_NEUTRAL_EXIT_SHORT: float = 55.0
    MIN_EXPECTED_R_BY_BAR_6: float = 0.20
    MIN_EXPECTED_R_BY_BAR_9: float = 0.35
    MIN_EXPECTED_R_BY_BAR_12: float = 0.50

    # --- FREQUENCY / CONFIDENCE ---
    COOLDOWN_CANDLES: int = 8
    CONFIDENCE_EXPONENT: float = 1.4
    FEATURE_CACHE_SIZE: int = 128
    DECISION_CACHE_SIZE: int = 256

    def get_rsi_delta_min(self, timeframe: str) -> float:
        return self.RSI_DELTA_MIN_BY_TF.get(timeframe, 5.5)

    def get_momentum_shift_min(self, timeframe: str) -> float:
        return self.MOMENTUM_SHIFT_DELTA_BY_TF.get(timeframe, 3.25)

    def get_ema_atr_mult(self, symbol: str) -> float:
        return self.EMA_ATR_MULT_BY_SYMBOL.get(symbol, self.EMA_ATR_MULT_BASE)

    def get_adx_bands(self, regime: str) -> Tuple[float, float, float]:
        return self.ADX_BANDS_BY_REGIME.get(regime, self.ADX_BANDS_BY_REGIME["VOLATILE"])

    def decay_min_r(self, bars_in_trade: int) -> float:
        if bars_in_trade <= 5:
            return -999.0
        if bars_in_trade <= 6:
            return self.MIN_EXPECTED_R_BY_BAR_6
        if bars_in_trade <= 9:
            slope = (self.MIN_EXPECTED_R_BY_BAR_9 - self.MIN_EXPECTED_R_BY_BAR_6) / 3.0
            return self.MIN_EXPECTED_R_BY_BAR_6 + slope * (bars_in_trade - 6)
        if bars_in_trade <= 12:
            slope = (self.MIN_EXPECTED_R_BY_BAR_12 - self.MIN_EXPECTED_R_BY_BAR_9) / 3.0
            return self.MIN_EXPECTED_R_BY_BAR_9 + slope * (bars_in_trade - 9)
        return self.MIN_EXPECTED_R_BY_BAR_12


class CooldownManager:
    """
    Prevents over-triggering in choppy environments.
    Block trades if a trade was taken on the same symbol within the last N candles.
    """

    def __init__(self, cooldown_candles: int = 8):
        self.cooldown_candles = cooldown_candles
        self.last_trade_index: Dict[str, int] = {}

    def is_cooling_down(self, symbol: str, current_index: int) -> bool:
        """Check if symbol is in cooldown period."""
        last_idx = self.last_trade_index.get(symbol, -9999)
        return (current_index - last_idx) < self.cooldown_candles

    def record_trade(self, symbol: str, current_index: int):
        """Record trade execution for cooldown tracking."""
        self.last_trade_index[symbol] = current_index


class MockSRH:
    """
    Interface connecting the Reversal Engine to external Risk, MTF, and Session systems.
    In production, this would query the actual SRH system for regime, trend, and session data.
    """

    def get_regime(self, symbol: str) -> str:
        """
        Get market regime for symbol.
        Returns: "RANGING", "HIGH_VOL", "VOLATILE", "STRONG_TREND"
        """
        return "VOLATILE"

    def get_htf_trend(self, symbol: str) -> str:
        """
        Get higher timeframe trend.
        Returns: "NEUTRAL", "STRONG_BULL", "STRONG_BEAR"
        """
        return "NEUTRAL"

    def get_session(self, symbol: str) -> str:
        """
        Get current trading session.
        Returns: "ASIA", "LONDON_NY_OVERLAP", "NEW_YORK", etc.
        """
        return "LONDON_NY_OVERLAP"

    def news_active(self, symbol: str = None) -> bool:
        """Check if major news event is active."""
        return False

    def get_spread_metrics(self, symbol: str) -> Tuple[float, float]:
        """
        Get spread metrics.
        Returns: (current_spread, average_spread)
        """
        return 0.2, 0.18

    def get_waterfall_multiplier(self, symbol: str, confidence: float) -> float:
        """
        Get risk adjustment multiplier from waterfall system.
        Applied post-decision to scale position size/risk.
        """
        return min(1.0, confidence * 1.2)


class MarketAnalyzer:
    """
    Highly optimized, vectorized feature extraction engine.
    Calculates heavy rolling windows once to save CPU cycles.
    STRICT zero-lookahead logic: All rolling windows use .shift(1).
    """

    REQUIRED_COLUMNS = {"open", "high", "low", "close", "tick_volume", "atr", "rsi", "adx"}
    _feature_cache: Dict[Tuple[Any, ...], pd.DataFrame] = {}

    @classmethod
    def _validate_columns(cls, df: pd.DataFrame) -> None:
        missing = sorted(cls.REQUIRED_COLUMNS.difference(df.columns))
        if missing:
            raise ValueError(
                f"MarketAnalyzer.calculate_features missing required columns: {', '.join(missing)}"
            )

    @staticmethod
    def _build_cache_key(
        df: pd.DataFrame,
        symbol: str,
        timeframe: str,
        cfg: ReversalConfig,
    ) -> Tuple[Any, ...]:
        latest = df.iloc[-1]
        return (
            symbol,
            timeframe,
            len(df),
            df.index[-1],
            round(float(latest["open"]), 8),
            round(float(latest["high"]), 8),
            round(float(latest["low"]), 8),
            round(float(latest["close"]), 8),
            round(float(latest["tick_volume"]), 4),
            round(float(latest["atr"]), 8),
            round(float(latest["rsi"]), 6),
            round(float(latest["adx"]), 6),
            cfg.get_rsi_delta_min(timeframe),
            cfg.get_ema_atr_mult(symbol),
        )

    @staticmethod
    def calculate_features(
        df: pd.DataFrame,
        symbol: str = "",
        timeframe: str = "M5",
        config: Optional[ReversalConfig] = None,
    ) -> pd.DataFrame:
        """
        Extract all technical features from OHLCV + RSI data.

        Expected DataFrame columns:
          - open, high, low, close, tick_volume, atr, rsi, adx

        Returns:
          DataFrame with added feature columns (bool/float)
        """
        cfg = config or ReversalConfig()
        MarketAnalyzer._validate_columns(df)
        cache_key = MarketAnalyzer._build_cache_key(df, symbol, timeframe, cfg)
        cached = MarketAnalyzer._feature_cache.get(cache_key)
        if cached is not None:
            return cached.copy()

        df = df.copy()
        ema_atr_mult = cfg.get_ema_atr_mult(symbol)
        rsi_delta_min = cfg.get_rsi_delta_min(timeframe)

        # Pre-calculate common shifts (critical for zero-lookahead)
        close_shift_1 = df["close"].shift(1)
        open_shift_1 = df["open"].shift(1)
        rsi_shift_1 = df["rsi"].shift(1)

        # ==================== 1. PRICE ACTION ====================
        body = abs(df["close"] - df["open"])
        wick_top = df["high"] - df[["open", "close"]].max(axis=1)
        wick_bot = df[["open", "close"]].min(axis=1) - df["low"]

        # Pin Bars: long wick on one side, compact real body
        min_body = body.where(body > 0, 1e-10)
        df["bull_pin"] = (wick_bot > 2.5 * min_body) & (wick_top <= min_body)
        df["bear_pin"] = (wick_top > 2.5 * min_body) & (wick_bot <= min_body)

        # Engulfing: current candle completely engulfs previous
        df["bull_engulfing"] = (
            (df["close"] > open_shift_1)
            & (df["open"] < close_shift_1)
            & (close_shift_1 < open_shift_1)
        )
        df["bear_engulfing"] = (
            (df["close"] < open_shift_1)
            & (df["open"] > close_shift_1)
            & (close_shift_1 > open_shift_1)
        )

        # ==================== 2. MOMENTUM & EMA ====================
        # Use a lagged EMA so the reference level itself never includes the active bar.
        df["ema_50"] = df["close"].ewm(span=50, adjust=False).mean().shift(1)
        df["rsi_delta"] = df["rsi"] - rsi_shift_1

        # ==================== 3. CLIMAX DETECTION ====================
        # Volatility expansion or volume spike
        rolling_20 = df[["tick_volume", "atr"]].rolling(20).mean().shift(1)
        df["climax"] = (df["tick_volume"] > rolling_20["tick_volume"] * 2.0) | (
            df["atr"] > rolling_20["atr"] * 1.5
        )

        # ==================== 4. LIQUIDITY SWEEPS (Stop Hunts) ====================
        rolling_10_high = df["high"].rolling(10).max().shift(1)
        rolling_10_low = df["low"].rolling(10).min().shift(1)

        df["liq_sweep_high"] = (df["high"] > rolling_10_high) & (
            df["close"] < rolling_10_high
        )
        df["liq_sweep_low"] = (df["low"] < rolling_10_low) & (
            df["close"] > rolling_10_low
        )

        # ==================== 5. MARKET STRUCTURE (BOS - 8 Bar True Fractal) ====================
        swing_low = df["low"].rolling(8).min().shift(1)
        swing_high = df["high"].rolling(8).max().shift(1)

        df["bull_bos"] = (df["close"] > swing_high) & (
            close_shift_1 <= swing_high.shift(1)
        )
        df["bear_bos"] = (df["close"] < swing_low) & (
            close_shift_1 >= swing_low.shift(1)
        )

        # ==================== 6. STRICT DIVERGENCE (Magnitude Gated) ====================
        # Price must extend beyond the prior 14-bar extreme while RSI fails to confirm.
        prior_14_low = df["low"].rolling(14).min().shift(1)
        prior_14_high = df["high"].rolling(14).max().shift(1)
        prior_14_rsi_low = df["rsi"].rolling(14).min().shift(1)
        prior_14_rsi_high = df["rsi"].rolling(14).max().shift(1)

        bull_rsi_delta_mag = (df["rsi"] - prior_14_rsi_low).abs()
        bear_rsi_delta_mag = (df["rsi"] - prior_14_rsi_high).abs()

        df["bull_div"] = (
            (df["low"] < prior_14_low)
            & (df["rsi"] > prior_14_rsi_low)
            & (bull_rsi_delta_mag > rsi_delta_min)
        )
        df["bear_div"] = (
            (df["high"] > prior_14_high)
            & (df["rsi"] < prior_14_rsi_high)
            & (bear_rsi_delta_mag > rsi_delta_min)
        )

        # Convenience flags for exhaustion scoring.
        df["bear_exhaustion"] = (df["rsi"] > cfg.RSI_OVERBOUGHT) | (
            (df["high"] - df["ema_50"]) > (df["atr"] * ema_atr_mult)
        )
        df["bull_exhaustion"] = (df["rsi"] < cfg.RSI_OVERSOLD) | (
            (df["ema_50"] - df["low"]) > (df["atr"] * ema_atr_mult)
        )

        bool_cols = [
            "bull_pin",
            "bear_pin",
            "bull_engulfing",
            "bear_engulfing",
            "climax",
            "liq_sweep_high",
            "liq_sweep_low",
            "bull_bos",
            "bear_bos",
            "bull_div",
            "bear_div",
            "bull_exhaustion",
            "bear_exhaustion",
        ]
        df[bool_cols] = df[bool_cols].fillna(False).astype(bool)

        if len(MarketAnalyzer._feature_cache) >= cfg.FEATURE_CACHE_SIZE:
            oldest_key = next(iter(MarketAnalyzer._feature_cache))
            del MarketAnalyzer._feature_cache[oldest_key]
        MarketAnalyzer._feature_cache[cache_key] = df.copy()

        return df


class ReversalEngine:
    """
    Core Reversal Detection Engine.

    Workflow:
      1. Check frequency controls (cooldown)
      2. Hard macro guards (ADX, HTF trend, news)
      3. Evaluate Bearish and Bullish logic separately
      4. Resolve direction (must not conflict)
      5. Apply multipliers & penalties
      6. Clamp penalties and calculate final score
      7. Exponential confidence filtering
      8. Return decision

    All logs follow institutional format:
      HH:MM:SS | LEVEL | [TAG] Pair: XXX | Score: Y.YY | Sigs: SIG+SIG | Action: Z | Conf: W.WW
    """

    def __init__(
        self,
        srh: Optional[MockSRH] = None,
        cooldown_mgr: Optional[CooldownManager] = None,
        config: ReversalConfig = ReversalConfig(),
    ):
        self.srh = srh or MockSRH()
        self.cfg = config
        self.cooldown_mgr = cooldown_mgr or CooldownManager(cooldown_candles=self.cfg.COOLDOWN_CANDLES)
        self.signature_stats: Dict[str, SignatureStats] = {}
        self._decision_cache: Dict[Tuple[Any, ...], ReversalDecision] = {}

    @staticmethod
    def _ensure_feature_columns(
        df: pd.DataFrame,
        symbol: str,
        timeframe: str,
        config: ReversalConfig,
    ) -> pd.DataFrame:
        required = {
            "bull_pin",
            "bear_pin",
            "bull_engulfing",
            "bear_engulfing",
            "ema_50",
            "rsi_delta",
            "climax",
            "liq_sweep_high",
            "liq_sweep_low",
            "bull_bos",
            "bear_bos",
            "bull_div",
            "bear_div",
            "bull_exhaustion",
            "bear_exhaustion",
        }
        if required.issubset(df.columns):
            return df
        return MarketAnalyzer.calculate_features(df, symbol=symbol, timeframe=timeframe, config=config)

    @staticmethod
    def _unique_join(signals) -> str:
        return "+".join(dict.fromkeys(signals))

    def _build_decision_cache_key(
        self,
        symbol: str,
        timeframe: str,
        latest: Dict[str, Any],
        regime: str,
        htf_trend: str,
        session: str,
        spreads: Tuple[float, float],
        news_active: bool,
    ) -> Tuple[Any, ...]:
        return (
            symbol,
            timeframe,
            regime,
            htf_trend,
            session,
            round(float(spreads[0]), 6),
            round(float(spreads[1]), 6),
            bool(news_active),
            round(float(latest.get("open", 0.0)), 8),
            round(float(latest.get("high", 0.0)), 8),
            round(float(latest.get("low", 0.0)), 8),
            round(float(latest.get("close", 0.0)), 8),
            round(float(latest.get("rsi", 0.0)), 6),
            round(float(latest.get("adx", 0.0)), 6),
            round(float(latest.get("atr", 0.0)), 8),
            round(float(latest.get("rsi_delta", 0.0)), 6),
            bool(latest.get("bear_div", False)),
            bool(latest.get("bull_div", False)),
            bool(latest.get("climax", False)),
            bool(latest.get("liq_sweep_high", False)),
            bool(latest.get("liq_sweep_low", False)),
        )

    def get_signature_penalty(self, setup_sig: str) -> float:
        stats = self.signature_stats.get(setup_sig)
        if not stats or stats.total < self.cfg.SIGNATURE_MIN_SAMPLES:
            return 1.0
        if stats.win_rate < self.cfg.SIGNATURE_MIN_WIN_RATE:
            return self.cfg.LOW_WIN_RATE_SIGNATURE_PENALTY
        return 1.0

    def record_setup_outcome(self, setup_sig: str, won: bool) -> None:
        if not setup_sig:
            return
        stats = self.signature_stats.setdefault(setup_sig, SignatureStats())
        if won:
            stats.wins += 1
        else:
            stats.losses += 1

    def evaluate_symbol(self, symbol: str, df: pd.DataFrame, timeframe: str = "M5") -> ReversalDecision:
        """
        Evaluate symbol for reversal trade opportunity.

        Args:
            symbol: Trading symbol (e.g., "EUR/USD")
            df: DataFrame with OHLCV + indicators. Must have columns:
                open, high, low, close, tick_volume, atr, rsi, adx

        Returns:
            ReversalDecision (action, confidence, reversal_score, entry_type, reason, risk_adjustment)
        """
        df = self._ensure_feature_columns(df, symbol=symbol, timeframe=timeframe, config=self.cfg)
        current_idx = len(df) - 1

        # ============ STEP 1: Frequency Control ============
        if self.cooldown_mgr.is_cooling_down(symbol, current_idx):
            return ReversalDecision(
                "NO_TRADE",
                0.0,
                0.0,
                "none",
                "Cooldown active",
                0.0,
            )

        latest = df.iloc[-1].to_dict()

        # ============ STEP 2: Hard Macro & Trend Guards ============
        adx = latest.get("adx", 0)
        htf_trend = self.srh.get_htf_trend(symbol)
        regime = self.srh.get_regime(symbol)
        session = self.srh.get_session(symbol)
        spreads = self.srh.get_spread_metrics(symbol)
        news_active = self.srh.news_active(symbol)

        cache_key = self._build_decision_cache_key(
            symbol=symbol,
            timeframe=timeframe,
            latest=latest,
            regime=regime,
            htf_trend=htf_trend,
            session=session,
            spreads=spreads,
            news_active=news_active,
        )
        cached_decision = self._decision_cache.get(cache_key)
        if cached_decision is not None:
            return cached_decision

        adx_penalty_1, adx_penalty_2, adx_hard_veto = self.cfg.get_adx_bands(regime)

        if (
            adx > adx_hard_veto
            or regime == "STRONG_TREND"
            or news_active
        ):
            decision = ReversalDecision(
                "NO_TRADE",
                0.0,
                0.0,
                "none",
                "Hard Veto: Strong Trend / News / ADX>35",
                0.0,
            )
            self._store_decision_cache(cache_key, decision)
            return decision

        base_threshold = self.cfg.THRESH_RANGING if regime == "RANGING" else self.cfg.THRESH_VOLATILE

        # ============ STEP 3: Evaluate Bearish & Bullish ============
        bear_score, bull_score = 0.0, 0.0
        bear_reasons, bull_reasons = [], []

        # --- BEARISH LOGIC ---
        if latest.get("bear_div", False):
            bear_score += self.cfg.W_DIV
            bear_reasons.append("BearDiv")
        if latest.get("bear_exhaustion", False):
            bear_score += self.cfg.W_EXH
            bear_reasons.append("BearExhaustion")
        if latest.get("bear_bos", False):
            bear_score += self.cfg.W_STR
            bear_reasons.append("Bear_BOS")
        if latest.get("bear_pin", False) or latest.get("bear_engulfing", False):
            bear_score += self.cfg.W_PA
            bear_reasons.append("Bear_PA")
        if latest.get("climax", False):
            bear_score += self.cfg.W_CLX
            bear_reasons.append("Climax")

        # --- BULLISH LOGIC ---
        if latest.get("bull_div", False):
            bull_score += self.cfg.W_DIV
            bull_reasons.append("BullDiv")
        if latest.get("bull_exhaustion", False):
            bull_score += self.cfg.W_EXH
            bull_reasons.append("BullExhaustion")
        if latest.get("bull_bos", False):
            bull_score += self.cfg.W_STR
            bull_reasons.append("Bull_BOS")
        if latest.get("bull_pin", False) or latest.get("bull_engulfing", False):
            bull_score += self.cfg.W_PA
            bull_reasons.append("Bull_PA")
        if latest.get("climax", False):
            bull_score += self.cfg.W_CLX
            bull_reasons.append("Climax")

        # ============ STEP 4: Resolve Direction ============
        action, base_score, core_signals = "NO_TRADE", 0.0, []

        # Conflicted market
        if bear_score > 0.50 and bull_score > 0.50:
            decision = ReversalDecision(
                "NO_TRADE",
                0.0,
                0.0,
                "none",
                "Conflicting Market Signals",
                0.0,
            )
            self._store_decision_cache(cache_key, decision)
            return decision

        # Determine winning direction
        if bear_score > bull_score and bear_score >= base_threshold:
            if htf_trend == "STRONG_BULL":
                decision = ReversalDecision(
                    "NO_TRADE", 0.0, 0.0, "none", "Fighting HTF Bull", 0.0
                )
                self._store_decision_cache(cache_key, decision)
                return decision
            action, base_score, core_signals = "SELL", min(1.0, bear_score), bear_reasons
        elif bull_score > bear_score and bull_score >= base_threshold:
            if htf_trend == "STRONG_BEAR":
                decision = ReversalDecision(
                    "NO_TRADE", 0.0, 0.0, "none", "Fighting HTF Bear", 0.0
                )
                self._store_decision_cache(cache_key, decision)
                return decision
            action, base_score, core_signals = "BUY", min(1.0, bull_score), bull_reasons

        if action == "NO_TRADE":
            decision = ReversalDecision(
                "NO_TRADE",
                0.0,
                0.0,
                "none",
                f"Base score below threshold {base_threshold}",
                0.0,
            )
            self._store_decision_cache(cache_key, decision)
            return decision

        # ============ STEP 5: Multipliers & Penalties (Anti-Compression) ============
        bonus_mult, penalty_mult = 1.0, 1.0
        reasons_log = list(core_signals)

        # A. Gated Liquidity Sweep Bonus
        if (
            action == "SELL"
            and latest.get("liq_sweep_high", False)
            and latest.get("bear_div", False)
        ):
            bonus_mult *= self.cfg.LIQ_SWEEP_BONUS
            core_signals.append("LiqSweep")
            reasons_log.append("LiqSweep")
        elif (
            action == "BUY"
            and latest.get("liq_sweep_low", False)
            and latest.get("bull_div", False)
        ):
            bonus_mult *= self.cfg.LIQ_SWEEP_BONUS
            core_signals.append("LiqSweep")
            reasons_log.append("LiqSweep")

        # B. True Momentum Shift Penalty
        rsi_delta = latest.get("rsi_delta", 0)
        shift_threshold = self.cfg.get_momentum_shift_min(timeframe)
        valid_shift = (
            (action == "BUY" and rsi_delta >= shift_threshold)
            or (action == "SELL" and rsi_delta <= -shift_threshold)
        )
        if not valid_shift:
            penalty_mult *= self.cfg.MOMENTUM_PENALTY
            reasons_log.append("Weak_MomShift")

        # C. Trap Detection
        div_key = "bull_div" if action == "BUY" else "bear_div"
        is_trap = (not latest.get(div_key, False)) and (not latest.get("climax", False))
        if is_trap:
            penalty_mult *= self.cfg.WEAK_STRUCTURE_PENALTY
            reasons_log.append("Weak_Structure")

        # D. Spread, ADX & Session
        cur_spread, avg_spread = spreads
        if cur_spread > (avg_spread * 1.5):
            penalty_mult *= self.cfg.SPREAD_PENALTY
            reasons_log.append("Spread_Penalty")
        if adx > adx_penalty_2:
            penalty_mult *= self.cfg.ADX_PENALTY_2
            reasons_log.append("ADX_Penalty_2")
        elif adx > adx_penalty_1:
            penalty_mult *= self.cfg.ADX_PENALTY_1
            reasons_log.append("ADX_Penalty")
        if session == "ASIA":
            penalty_mult *= self.cfg.SESSION_ASIA_PENALTY
            reasons_log.append("Session_Penalty")

        # E. Math Clamping (Prevent Total Collapse)
        penalty_mult = max(penalty_mult, 1.0 - self.cfg.MAX_TOTAL_PENALTY)

        setup_sig = self._unique_join(core_signals)
        signature_penalty = self.get_signature_penalty(setup_sig)
        if signature_penalty < 1.0:
            penalty_mult *= signature_penalty
            reasons_log.append("LowWinRateSig")
            penalty_mult = max(penalty_mult, 1.0 - self.cfg.MAX_TOTAL_PENALTY)

        final_score = min(1.0, base_score * penalty_mult * bonus_mult)
        if final_score < base_threshold:
            decision = ReversalDecision(
                "NO_TRADE",
                0.0,
                0.0,
                "none",
                f"Penalized below {base_threshold}",
                0.0,
            )
            self._store_decision_cache(cache_key, decision)
            return decision

        # ============ STEP 6: Exponential Confidence & Hard Filter ============
        confidence = final_score ** self.cfg.CONFIDENCE_EXPONENT
        if confidence < self.cfg.CONFIDENCE_FLOOR:
            decision = ReversalDecision(
                "NO_TRADE",
                0.0,
                0.0,
                "none",
                f"Confidence too low ({confidence:.2f})",
                0.0,
            )
            self._store_decision_cache(cache_key, decision)
            return decision

        # ============ STEP 7: Output ============
        entry_type = "aggressive" if final_score > 0.75 else "conservative"
        risk_adj = self.srh.get_waterfall_multiplier(symbol, confidence)

        logger.info(
            f"[REVERSAL_DETECTED] Pair: {symbol} | Score: {final_score:.2f} | Sigs: {setup_sig} | Action: {action} | Conf: {confidence:.2f}"
        )

        decision = ReversalDecision(
            action,
            round(confidence, 3),
            round(final_score, 3),
            entry_type,
            setup_sig,
            round(risk_adj, 2),
        )
        self._store_decision_cache(cache_key, decision)
        return decision

    def _store_decision_cache(self, cache_key: Tuple[Any, ...], decision: ReversalDecision) -> None:
        if len(self._decision_cache) >= self.cfg.DECISION_CACHE_SIZE:
            oldest_key = next(iter(self._decision_cache))
            del self._decision_cache[oldest_key]
        self._decision_cache[cache_key] = decision


class ReversalExitManager:
    """
    Priority-Based Dynamic Exit Manager (Offensive & Defensive).

    Evaluates exits in strict priority hierarchy:
      Offensive 1: Scale Out (1.0R)
      Offensive 2: Free Ride (1.5R -> SL to BE)
      Defensive 1: Structural Failure (price breach > entry_atr * 1.5)
      Defensive 2: Time Stall (>10 bars & <0.3R)
      Defensive 3: Opposite Price Action
      Defensive 4: Momentum Normalization (>5 bars & RSI neutral)

    All exits logged in institutional format.
    """

    @staticmethod
    def evaluate_exit(
        symbol: str,
        action: str,
        entry_price: float,
        entry_atr: float,
        bars_in_trade: int,
        unrealized_r: float,
        current_df: pd.DataFrame,
        partial_taken: bool = False,
        sl_moved: bool = False,
        config: ReversalConfig = ReversalConfig(),
        entry_invalidation_price: Optional[float] = None,
    ) -> ExitDecision:
        """
        Evaluate dynamic exit conditions.

        Args:
            symbol: Trading symbol
            action: "BUY" or "SELL"
            entry_price: Trade entry price
            entry_atr: ATR at entry time
            bars_in_trade: Number of candles since entry
            unrealized_r: Unrealized profit in R-multiples
            current_df: Current market data
            partial_taken: Whether 50% partial already taken
            sl_moved: Whether SL already moved to break-even

        Returns:
            ExitDecision (action, reason)
        """
        latest = current_df.iloc[-1].to_dict()

        # --- OFFENSIVE PROFIT TAKING ---
        if unrealized_r >= config.SCALE_OUT_R and not partial_taken:
            logger.info(
                f"[PROFIT_SECURED] {symbol} | Reached 1.0R. Scaling out 50%."
            )
            return ExitDecision("CLOSE_PARTIAL_50", "1.0R_Target")

        if unrealized_r >= config.FREE_RIDE_R and not sl_moved:
            logger.info(
                f"[PROFIT_SECURED] {symbol} | Reached 1.5R. Moving Stop to Break Even."
            )
            return ExitDecision("MOVE_SL_BE", "1.5R_Target")

        # --- DEFENSIVE LOGIC ---
        # Priority 1: Structural Failure
        invalidation_floor = entry_atr * config.STRUCTURAL_FAILURE_MULT
        long_invalidation = (
            entry_invalidation_price
            if entry_invalidation_price is not None
            else entry_price - invalidation_floor
        )
        short_invalidation = (
            entry_invalidation_price
            if entry_invalidation_price is not None
            else entry_price + invalidation_floor
        )
        if (
            action == "BUY"
            and latest.get("close", 0) < long_invalidation
        ) or (action == "SELL" and latest.get("close", 0) > short_invalidation):
            logger.info(f"[DYNAMIC_EXIT] {symbol} | Structural Failure Detected. Cutting losses.")
            return ExitDecision("CLOSE_FULL", "Structural_Failure")

        # Priority 2: R-multiple decay / time stall
        min_r_required = config.decay_min_r(bars_in_trade)
        if bars_in_trade > 5 and unrealized_r < min_r_required:
            logger.info(
                f"[DYNAMIC_EXIT] {symbol} | R-multiple decay failure. Bars: {bars_in_trade} | "
                f"R: {unrealized_r:.2f} | MinR: {min_r_required:.2f}"
            )
            return ExitDecision("CLOSE_FULL", "RR_Decay_Failure")

        if bars_in_trade >= config.FORCE_EXIT_AFTER_BARS and unrealized_r < config.MIN_EXPECTED_R_BY_BAR_12:
            logger.info(f"[DYNAMIC_EXIT] {symbol} | Max time decay reached without 0.5R progress.")
            return ExitDecision("CLOSE_FULL", "Time_Decay_Max")

        if bars_in_trade > 10 and unrealized_r < 0.3:
            logger.info(f"[DYNAMIC_EXIT] {symbol} | Time Stall ({bars_in_trade} bars). Killing trade.")
            return ExitDecision("CLOSE_FULL", "Time_Stall")

        # Priority 3: Opposite Price Action
        if (action == "BUY" and (latest.get("bear_pin", False) or latest.get("bear_engulfing", False))) or (
            action == "SELL" and (latest.get("bull_pin", False) or latest.get("bull_engulfing", False))
        ):
            logger.info(f"[DYNAMIC_EXIT] {symbol} | Opposite PA detected.")
            return ExitDecision("CLOSE_FULL", "Opposite_PA")

        # Priority 4: Momentum Normalization
        if bars_in_trade > 5:
            if (
                (action == "BUY" and latest.get("rsi", 0) >= config.RSI_NEUTRAL_EXIT_LONG)
                or (action == "SELL" and latest.get("rsi", 0) <= config.RSI_NEUTRAL_EXIT_SHORT)
            ):
                logger.info(f"[DYNAMIC_EXIT] {symbol} | Momentum Normalized.")
                return ExitDecision("CLOSE_FULL", "RSI_Normalization")

        return ExitDecision("HOLD", "")


# ============================================================================
# INTEGRATION EXAMPLE & USAGE
# ============================================================================

def example_integration():
    """
    Example of how to integrate ReversalEngine with existing SRH system.

    Steps:
      1. Instantiate engines with SRH reference
      2. Calculate features on fresh DataFrame
      3. Evaluate symbol on each cycle
      4. Record trades for cooldown tracking
      5. Manage exits for open positions
    """

    # Initialize
    srh = MockSRH()  # Replace with actual SRH instance
    cooldown_mgr = CooldownManager(cooldown_candles=8)
    reversal_engine = ReversalEngine(srh=srh, cooldown_mgr=cooldown_mgr)

    # Create sample data
    df = pd.DataFrame({
        "open": [1.0500, 1.0505, 1.0510],
        "high": [1.0510, 1.0520, 1.0525],
        "low": [1.0490, 1.0500, 1.0505],
        "close": [1.0505, 1.0515, 1.0520],
        "tick_volume": [100, 150, 200],
        "atr": [0.0015, 0.0016, 0.0017],
        "rsi": [35, 40, 45],
        "adx": [20, 22, 21],
        "ema_50": [1.0500, 1.0501, 1.0502],
    })

    # Calculate features
    df = MarketAnalyzer.calculate_features(df)

    # Evaluate symbol
    decision = reversal_engine.evaluate_symbol("EUR/USD", df)
    print(f"Decision: {decision.to_dict()}")

    # If trade is taken, record it for cooldown
    if decision.action != "NO_TRADE":
        cooldown_mgr.record_trade("EUR/USD", len(df) - 1)

    # Later: evaluate exit for open position
    exit_decision = ReversalExitManager.evaluate_exit(
        symbol="EUR/USD",
        action=decision.action,
        entry_price=1.05,
        entry_atr=0.0015,
        bars_in_trade=5,
        unrealized_r=0.75,
        current_df=df,
    )
    print(f"Exit Decision: {exit_decision}")


if __name__ == "__main__":
    example_integration()
