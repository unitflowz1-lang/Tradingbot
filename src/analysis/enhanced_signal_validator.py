"""
Enhanced Signal Validator - Advanced Trading Decision Engine

Integrates multiple technical analysis components into a unified signal-confidence score:
1. Multi-Timeframe Confirmation (MTF)
2. Volatility Regime Detection
3. Momentum Divergence Analysis
4. Liquidity Filters
5. Indicator Confluence Scoring
6. Risk-Adjusted Quality Threshold

Only allows entry when all conditions align above configurable thresholds.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from enum import Enum
from datetime import datetime, timezone
import numpy as np

from src.models import MarketData, TradingSignal, Direction
from src.utils.pip_standardizer import PipStandardizer


class VolatilityRegime(Enum):
    """Market volatility classification"""
    LOW = "low"           # Ranging/consolidating
    NORMAL = "normal"     # Trending smoothly
    HIGH = "high"         # Volatile/news-driven
    EXTREME = "extreme"   # Crisis/flash crash


class MarketContext(Enum):
    """Overall market context"""
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGING = "ranging"
    BREAKOUT = "breakout"
    REVERSAL = "reversal"


@dataclass
class TimeframeAnalysis:
    """Analysis result for a single timeframe"""
    timeframe: str
    direction: Direction
    strength: float  # 0-1
    trend_aligned: bool
    rsi: float
    macd_signal: str  # "bullish", "bearish", "neutral"
    ema_alignment: bool  # Price above/below EMA stack


@dataclass
class VolatilityAnalysis:
    """Volatility regime analysis"""
    regime: VolatilityRegime
    atr_percentile: float  # Current ATR vs historical (0-100)
    bollinger_width: float
    is_expanding: bool
    recommended_position_scale: float  # 0.5-1.5 multiplier


@dataclass
class MomentumDivergence:
    """Momentum divergence detection"""
    has_divergence: bool
    divergence_type: str  # "bullish", "bearish", "hidden_bullish", "hidden_bearish", "none"
    strength: float  # 0-1
    indicator: str  # "RSI", "MACD", "Stochastic"


@dataclass
class LiquidityFilter:
    """Liquidity and spread analysis"""
    spread_acceptable: bool
    volume_sufficient: bool
    session_active: bool  # London/NY overlap preferred
    avoid_news: bool
    liquidity_score: float  # 0-1
    spread_pips: float = 0.0
    max_allowed_spread_pips: float = 0.0


@dataclass
class ConfluenceScore:
    """Unified signal confidence score"""
    total_score: float  # 0-100
    mtf_score: float
    volatility_score: float
    momentum_score: float
    liquidity_score: float
    indicator_confluence: float
    risk_alignment: float
    
    # Component details
    timeframe_analyses: List[TimeframeAnalysis] = field(default_factory=list)
    volatility_analysis: Optional[VolatilityAnalysis] = None
    divergence: Optional[MomentumDivergence] = None
    liquidity: Optional[LiquidityFilter] = None
    
    # Decision
    signal_approved: bool = False
    rejection_reasons: List[str] = field(default_factory=list)
    recommended_entry: bool = False
    position_size_multiplier: float = 1.0


@dataclass
class EnhancedSignalConfig:
    """Configuration for enhanced signal validation"""
    # Quality thresholds
    min_confluence_score: float = 45.0  # Minimum validator score to pass full validation
    min_mtf_alignment: int = 2  # Minimum timeframes that must agree
    
    # Volatility settings
    max_volatility_regime: VolatilityRegime = VolatilityRegime.HIGH
    volatility_scale_high: float = 0.7  # Reduce size in high volatility
    volatility_scale_low: float = 1.2  # Increase size in low volatility
    
    # Momentum settings
    require_no_divergence: bool = False  # If True, reject signals with bearish divergence on buys
    divergence_bonus: float = 15.0  # Bonus score for confirming divergence
    
    # Liquidity settings
    max_spread_pips: float = 5.0
    min_volume_percentile: float = 30.0
    preferred_sessions: List[str] = field(default_factory=lambda: ["london", "newyork", "overlap"])
    
    # Risk settings
    max_correlation_exposure: float = 0.7  # Max correlation with existing positions
    require_trend_alignment: bool = True
    
    # Indicator weights for confluence
    weights: Dict[str, float] = field(default_factory=lambda: {
        "mtf": 0.25,
        "volatility": 0.15,
        "momentum": 0.20,
        "liquidity": 0.15,
        "indicators": 0.15,
        "risk": 0.10
    })


class EnhancedSignalValidator:
    """
    Advanced signal validation engine that combines multiple analysis dimensions
    into a unified confidence score for high-quality trade entries.
    """
    
    def __init__(self, config: Optional[EnhancedSignalConfig] = None):
        self.config = config or EnhancedSignalConfig()
        self.logger = logging.getLogger(__name__)
        
        # Historical data for percentile calculations
        self.atr_history: Dict[str, List[float]] = {}
        self.volume_history: Dict[str, List[float]] = {}
        
    def validate_signal(
        self,
        signal: TradingSignal,
        historical_data: List[MarketData],
        higher_tf_data: Optional[Dict[str, List[MarketData]]] = None,
        current_positions: Optional[List] = None
    ) -> ConfluenceScore:
        """
        Comprehensive signal validation with multi-dimensional analysis.
        
        Args:
            signal: The trading signal to validate
            historical_data: Primary timeframe data
            higher_tf_data: Dict of higher timeframe data {"H4": [...], "D1": [...]}
            current_positions: List of current open positions for correlation check
            
        Returns:
            ConfluenceScore with detailed analysis and recommendation
        """
        override_mode = str(getattr(signal, "mode", "") or "").upper()
        structure_override = bool(getattr(signal, "structure_override", False))
        signal_source = str(getattr(signal, "source", getattr(signal, "signal_source", "")) or "").upper()
        forced_execution = bool(getattr(signal, "forced_execution", False))
        admission_locked = bool(getattr(signal, "admission_locked", False))  # NEW: Bypass Tug-of-War
        
        # ===== FIX #5: REMOVED - AUTHORITY LEVEL CANNOT BYPASS VALIDATOR =====
        # OLD BEHAVIOR: admission_locked=True bypassed all downstream validators
        # NEW REQUIREMENT: EnhancedValidator is FINAL AUTHORITY
        # Authority Level 3 and Level 2 cannot bypass validation gates without full validation
        #
        # REMOVED CODE (intentionally disabled per Requirement #5):
        # if admission_locked:
        #     confluence_score = ConfluenceScore(...total_score=100.0...)  # REMOVED
        #     return confluence_score  # REMOVED
        #
        # Now EnhancedValidator is the FINAL YES/NO authority for all trades
        logger.debug(
            "[VALIDATOR_ENFORCED] %s | EnhancedValidator is FINAL authority | Authority Levels cannot bypass validation",
            signal.symbol,
        )
        
        # ===== FIX #5: FORCE-PASS GATES DISABLED - REQUIREMENT #5: AUTH LEVEL CANNOT BYPASS =====
        # OLD: Authority Levels could force-pass signals (override_active = forced_execution or ...)
        # NEW: All signals must pass standard validation - no force-pass gates allowed
        override_active = False  # HARDCODED DISABLED per Requirement #5
        
        if False and override_active:
            broker_safe = bool(
                float(getattr(signal, "entry_price", 0.0) or 0.0) > 0.0
                and float(getattr(signal, "stop_loss", 0.0) or 0.0) > 0.0
                and float(getattr(signal, "take_profit", 0.0) or 0.0) > 0.0
            )
            approved = bool(broker_safe)
            reasons = [] if approved else ["Broker-breaking price payload"]
            confluence_score = ConfluenceScore(
                total_score=100.0 if approved else 0.0,
                mtf_score=100.0 if approved else 0.0,
                volatility_score=100.0 if approved else 0.0,
                momentum_score=100.0 if approved else 0.0,
                liquidity_score=100.0 if approved else 0.0,
                indicator_confluence=100.0 if approved else 0.0,
                risk_alignment=100.0 if approved else 0.0,
                signal_approved=approved,
                rejection_reasons=reasons,
                recommended_entry=approved,
                position_size_multiplier=1.0,
            )
            if approved:
                self.logger.critical(
                    "[VALIDATOR_OVERRIDE_ACCEPTED] %s | Override_Accepted | forced=%s | structure_override=%s | source=%s | mode=%s",
                    signal.symbol,
                    forced_execution,
                    structure_override,
                    signal_source or "STANDARD",
                    override_mode or "STANDARD",
                )
            else:
                self.logger.critical(
                    "[VALIDATOR_OVERRIDE_REJECTED] %s | Override payload invalid for broker send.",
                    signal.symbol,
                )
            return confluence_score
        
        symbol = signal.symbol
        direction = signal.direction

        # ===== FIX #4: LIQUIDITY TRAP PRE-ADMISSION CHECK =====
        # Detect and reject signals that would enter into liquidity traps (stop-hunts)
        # This runs BEFORE admission to prevent signals from reaching "STRIKING" status
        is_trap, trap_reason = self._check_liquidity_trap(
            symbol=symbol,
            direction=direction,
            historical_data=historical_data,
            signal_entry=float(getattr(signal, "entry_price", 0.0) or 0.0)
        )
        if is_trap:
            self.logger.critical(trap_reason)
            confluence_score = ConfluenceScore(
                total_score=0.0,
                mtf_score=0.0,
                volatility_score=0.0,
                momentum_score=0.0,
                liquidity_score=0.0,
                indicator_confluence=0.0,
                risk_alignment=0.0,
                signal_approved=False,
                rejection_reasons=[trap_reason],
                recommended_entry=False,
                position_size_multiplier=0.0,
            )
            self.logger.critical(
                "[VALIDATOR_LIQUIDITY_TRAP_REJECTION] %s | Pre-admission trap detection | Signal rejected before striking",
                symbol,
            )
            return confluence_score

        # rr_ratio-only bypass removed; EV gatekeeper handles expectancy admission.
        
        # Initialize score components
        scores = {
            "mtf": 0.0,
            "volatility": 0.0,
            "momentum": 0.0,
            "liquidity": 0.0,
            "indicators": 0.0,
            "risk": 0.0
        }
        rejection_reasons = []
        
        # 1. Multi-Timeframe Analysis
        mtf_analyses = self._analyze_multiple_timeframes(
            symbol, direction, historical_data, higher_tf_data
        )
        scores["mtf"], mtf_aligned = self._score_mtf_alignment(mtf_analyses, direction)
        
        if not mtf_aligned and self.config.require_trend_alignment:
            rejection_reasons.append("Multi-timeframe trend not aligned")
        
        # 2. Volatility Regime Analysis
        vol_analysis = self._analyze_volatility_regime(symbol, historical_data)
        scores["volatility"] = self._score_volatility(vol_analysis)
        
        if vol_analysis.regime == VolatilityRegime.EXTREME:
            rejection_reasons.append("Extreme volatility regime - avoid trading")
        
        # 3. Momentum Divergence Analysis
        divergence = self._detect_momentum_divergence(historical_data, direction)
        scores["momentum"] = self._score_momentum(divergence, direction)
        
        if self.config.require_no_divergence and divergence.has_divergence:
            if (direction == Direction.LONG and divergence.divergence_type == "bearish") or \
               (direction == Direction.SHORT and divergence.divergence_type == "bullish"):
                rejection_reasons.append(f"Counter-trend {divergence.divergence_type} divergence detected")
        
        # 4. Liquidity Filter
        liquidity = self._analyze_liquidity(symbol, historical_data, signal=signal)
        scores["liquidity"] = liquidity.liquidity_score * 100
        
        if not liquidity.spread_acceptable:
            rejection_reasons.append("Spread too wide")
        
        # 5. Indicator Confluence
        scores["indicators"] = self._calculate_indicator_confluence(
            historical_data, direction, signal
        )
        
        # 6. Risk Alignment
        scores["risk"] = self._calculate_risk_alignment(
            signal, current_positions, vol_analysis
        )
        
        # Calculate weighted total score
        # Component scores are already 0-100, weights sum to 1.0
        total_score = sum(
            scores[key] * self.config.weights[key]
            for key in scores
        )
        
        # Normalize to 0-100 (just in case)
        total_score = min(100, max(0, total_score))
        
        # Determine position size multiplier based on volatility
        position_multiplier = self._calculate_position_multiplier(vol_analysis, total_score)
        
        # FINAL DECISION & LIQUIDITY LOGIC
        # ===== FIX #4: LIQUIDITY BLOCK REMOVAL =====
        # Lower min liquidity threshold (implicit via volume/session check bypass)
        # Verify 4-hour window override
        current_hour = datetime.now(timezone.utc).hour
        liquidity_override_active = False
        
        if not liquidity_override_active and (not liquidity.session_active or not liquidity.volume_sufficient):
            if total_score >= 75:
                # Strong signal: reduce size to 50% instead of rejecting
                position_multiplier *= 0.5
                self.logger.info(f"[SOFT-LIQUIDITY] Strong signal (>=75) in low liquidity - reducing size to {position_multiplier:.2f}x")
            elif total_score < 70:
                # Weak signal: reject
                rejection_reasons.append("Low liquidity & sub-70 score")

        # Score check (Liquidity session logic now handled by soft-filter above)
        if total_score < self.config.min_confluence_score:
             rejection_reasons.append(f"Total score {total_score:.1f} below minimum {self.config.min_confluence_score}")
             
        signal_approved = (
            total_score >= self.config.min_confluence_score and
            len(rejection_reasons) == 0
        )
        
        confluence_score = ConfluenceScore(
            total_score=total_score,
            mtf_score=scores["mtf"],
            volatility_score=scores["volatility"],
            momentum_score=scores["momentum"],
            liquidity_score=scores["liquidity"],
            indicator_confluence=scores["indicators"],
            risk_alignment=scores["risk"],
            timeframe_analyses=mtf_analyses,
            volatility_analysis=vol_analysis,
            divergence=divergence,
            liquidity=liquidity,
            signal_approved=signal_approved,
            rejection_reasons=rejection_reasons,
            recommended_entry=signal_approved,
            position_size_multiplier=position_multiplier
        )
        
        # Log the analysis
        self._log_analysis(signal, confluence_score)
        
        return confluence_score
    
    def _analyze_multiple_timeframes(
        self,
        symbol: str,
        direction: Direction,
        primary_data: List[MarketData],
        higher_tf_data: Optional[Dict[str, List[MarketData]]]
    ) -> List[TimeframeAnalysis]:
        """Analyze trend alignment across multiple timeframes"""
        analyses = []
        
        # Primary timeframe (H1)
        primary_analysis = self._analyze_single_timeframe(
            "H1", primary_data, direction
        )
        analyses.append(primary_analysis)
        
        # Higher timeframes if available
        if higher_tf_data:
            for tf_name, tf_data in higher_tf_data.items():
                if tf_data and len(tf_data) >= 20:
                    tf_analysis = self._analyze_single_timeframe(
                        tf_name, tf_data, direction
                    )
                    analyses.append(tf_analysis)
        
        return analyses
    
    def _analyze_single_timeframe(
        self,
        timeframe: str,
        data: List[MarketData],
        signal_direction: Direction
    ) -> TimeframeAnalysis:
        """Analyze a single timeframe for trend and indicators"""
        if len(data) < 20:
            return TimeframeAnalysis(
                timeframe=timeframe,
                direction=Direction.LONG,
                strength=0.0,
                trend_aligned=False,
                rsi=50.0,
                macd_signal="neutral",
                ema_alignment=False
            )
        
        closes = [d.close for d in data]
        
        # Calculate EMAs
        ema_8 = self._ema(closes, 8)
        ema_21 = self._ema(closes, 21)
        ema_50 = self._ema(closes, 50) if len(closes) >= 50 else ema_21
        
        # Determine direction based on EMA stack
        current_price = closes[-1]
        if current_price > ema_8 > ema_21:
            tf_direction = Direction.LONG
            ema_aligned = True
        elif current_price < ema_8 < ema_21:
            tf_direction = Direction.SHORT
            ema_aligned = True
        else:
            tf_direction = Direction.LONG if current_price > ema_21 else Direction.SHORT
            ema_aligned = False
        
        # Calculate RSI
        rsi = self._calculate_rsi(closes, 14)
        
        # Calculate MACD
        macd_line, signal_line = self._calculate_macd(closes)
        if macd_line > signal_line:
            macd_signal = "bullish"
        elif macd_line < signal_line:
            macd_signal = "bearish"
        else:
            macd_signal = "neutral"
        
        # Trend strength based on ADX-like calculation
        strength = self._calculate_trend_strength(data)
        
        # Check alignment with signal
        trend_aligned = (tf_direction == signal_direction)
        
        return TimeframeAnalysis(
            timeframe=timeframe,
            direction=tf_direction,
            strength=strength,
            trend_aligned=trend_aligned,
            rsi=rsi,
            macd_signal=macd_signal,
            ema_alignment=ema_aligned
        )
    
    def _analyze_volatility_regime(
        self,
        symbol: str,
        data: List[MarketData]
    ) -> VolatilityAnalysis:
        """Analyze current volatility regime"""
        if len(data) < 20:
            return VolatilityAnalysis(
                regime=VolatilityRegime.NORMAL,
                atr_percentile=50.0,
                bollinger_width=0.0,
                is_expanding=False,
                recommended_position_scale=1.0
            )
        
        # Calculate ATR
        atr = self._calculate_atr(data, 14)
        
        # Calculate ATR percentile vs history
        if symbol not in self.atr_history:
            self.atr_history[symbol] = []
        self.atr_history[symbol].append(atr)
        
        # Keep last 100 ATR values
        if len(self.atr_history[symbol]) > 100:
            self.atr_history[symbol] = self.atr_history[symbol][-100:]
        
        atr_percentile = self._percentile_rank(atr, self.atr_history[symbol])
        
        # Calculate Bollinger Band width
        closes = [d.close for d in data[-20:]]
        sma = sum(closes) / len(closes)
        std = np.std(closes)
        bb_width = (std * 2) / sma * 100  # As percentage
        
        # Check if volatility expanding
        recent_atr = self._calculate_atr(data[-7:], 7) if len(data) >= 7 else atr
        is_expanding = recent_atr > atr * 1.1
        
        # Determine regime
        if atr_percentile >= 90:
            regime = VolatilityRegime.EXTREME
            scale = 0.5
        elif atr_percentile >= 70:
            regime = VolatilityRegime.HIGH
            scale = self.config.volatility_scale_high
        elif atr_percentile >= 30:
            regime = VolatilityRegime.NORMAL
            scale = 1.0
        else:
            regime = VolatilityRegime.LOW
            scale = self.config.volatility_scale_low
        
        return VolatilityAnalysis(
            regime=regime,
            atr_percentile=atr_percentile,
            bollinger_width=bb_width,
            is_expanding=is_expanding,
            recommended_position_scale=scale
        )
    
    def _detect_momentum_divergence(
        self,
        data: List[MarketData],
        direction: Direction
    ) -> MomentumDivergence:
        """Detect RSI/MACD divergence patterns"""
        if len(data) < 30:
            return MomentumDivergence(
                has_divergence=False,
                divergence_type="none",
                strength=0.0,
                indicator="RSI"
            )
        
        closes = [d.close for d in data]
        
        # Calculate RSI series
        rsi_values = []
        for i in range(14, len(closes)):
            rsi = self._calculate_rsi(closes[:i+1], 14)
            rsi_values.append(rsi)
        
        if len(rsi_values) < 10:
            return MomentumDivergence(
                has_divergence=False,
                divergence_type="none",
                strength=0.0,
                indicator="RSI"
            )
        
        # Find recent price highs/lows
        recent_prices = closes[-20:]
        recent_rsi = rsi_values[-20:] if len(rsi_values) >= 20 else rsi_values
        
        # Detect bearish divergence: higher price high, lower RSI high
        price_highs = self._find_peaks(recent_prices)
        rsi_highs = self._find_peaks(recent_rsi)
        
        # Detect bullish divergence: lower price low, higher RSI low
        price_lows = self._find_troughs(recent_prices)
        rsi_lows = self._find_troughs(recent_rsi)
        
        divergence_type = "none"
        strength = 0.0
        has_divergence = False
        
        # Check for bearish divergence (price making higher highs, RSI making lower highs)
        if len(price_highs) >= 2 and len(rsi_highs) >= 2:
            if price_highs[-1] > price_highs[-2] and rsi_highs[-1] < rsi_highs[-2]:
                has_divergence = True
                divergence_type = "bearish"
                strength = abs(rsi_highs[-2] - rsi_highs[-1]) / 100
        
        # Check for bullish divergence (price making lower lows, RSI making higher lows)
        if len(price_lows) >= 2 and len(rsi_lows) >= 2:
            if price_lows[-1] < price_lows[-2] and rsi_lows[-1] > rsi_lows[-2]:
                has_divergence = True
                divergence_type = "bullish"
                strength = abs(rsi_lows[-1] - rsi_lows[-2]) / 100
        
        return MomentumDivergence(
            has_divergence=has_divergence,
            divergence_type=divergence_type,
            strength=min(1.0, strength),
            indicator="RSI"
        )
    
    def _analyze_liquidity(
        self,
        symbol: str,
        data: List[MarketData],
        signal: Optional[TradingSignal] = None,
    ) -> LiquidityFilter:
        """Analyze market liquidity conditions"""
        if not data:
            return LiquidityFilter(
                spread_acceptable=False,
                volume_sufficient=False,
                session_active=False,
                avoid_news=True,
                liquidity_score=0.0,
                spread_pips=0.0,
                max_allowed_spread_pips=0.0,
            )
        
        current_bar = data[-1]

        current_spread = float(getattr(current_bar, "spread", 0.0) or 0.0)
        if current_spread <= 0.0:
            current_spread = (float(current_bar.high) - float(current_bar.low)) * 0.1
        spread_pips = PipStandardizer.broker_value_to_pips(current_spread, symbol)

        atr_14 = self._calculate_atr_14(data)
        atr_relative_limit = PipStandardizer.broker_value_to_pips(float(atr_14) * 0.3, symbol) if atr_14 > 0 else 0.0
        max_allowed_spread_pips = max(float(self.config.max_spread_pips), float(atr_relative_limit))

        structure_override = bool(getattr(signal, "structure_override", False))
        if structure_override:
            max_allowed_spread_pips *= 2.0

        spread_acceptable = spread_pips <= max_allowed_spread_pips
        
        # Check volume
        if symbol not in self.volume_history:
            self.volume_history[symbol] = []
        
        current_volume = current_bar.volume if current_bar.volume else 0
        self.volume_history[symbol].append(current_volume)
        
        if len(self.volume_history[symbol]) > 100:
            self.volume_history[symbol] = self.volume_history[symbol][-100:]
        
        volume_percentile = self._percentile_rank(current_volume, self.volume_history[symbol])
        volume_sufficient = volume_percentile >= self.config.min_volume_percentile
        
        # Check trading session
        current_hour = datetime.now(timezone.utc).hour
        asian_active = 0 <= current_hour <= 9
        london_active = 8 <= current_hour <= 16
        ny_active = 13 <= current_hour <= 21
        overlap = 13 <= current_hour <= 16
        
        session_active = asian_active or london_active or ny_active
        
        # Calculate liquidity score
        score = 0.0
        if spread_acceptable:
            score += 0.3
        if volume_sufficient:
            score += 0.3
        if session_active:
            score += 0.25
        if overlap:
            score += 0.15
        
        return LiquidityFilter(
            spread_acceptable=spread_acceptable,
            volume_sufficient=volume_sufficient,
            session_active=session_active,
            avoid_news=False,  # Would need news calendar integration
            liquidity_score=score,
            spread_pips=float(spread_pips),
            max_allowed_spread_pips=float(max_allowed_spread_pips),
        )

    def _calculate_atr_14(self, data: List[MarketData]) -> float:
        """Lightweight ATR(14) from recent bars for spread-relative validation."""
        if len(data) < 2:
            return 0.0

        recent = data[-15:]
        true_ranges: List[float] = []
        prev_close = float(recent[0].close)
        for bar in recent[1:]:
            high = float(bar.high)
            low = float(bar.low)
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close),
            )
            true_ranges.append(tr)
            prev_close = float(bar.close)

        if not true_ranges:
            return 0.0
        return float(sum(true_ranges) / len(true_ranges))
    
    def _calculate_indicator_confluence(
        self,
        data: List[MarketData],
        direction: Direction,
        signal: TradingSignal
    ) -> float:
        """Calculate indicator confluence score"""
        if len(data) < 50:
            return 50.0
        
        closes = [d.close for d in data]
        confirming_indicators = 0
        total_indicators = 6
        
        current_price = closes[-1]
        
        # 1. EMA Stack (8, 21, 50)
        ema_8 = self._ema(closes, 8)
        ema_21 = self._ema(closes, 21)
        ema_50 = self._ema(closes, 50)
        
        if direction == Direction.LONG:
            if current_price > ema_8 > ema_21 > ema_50:
                confirming_indicators += 1
        else:
            if current_price < ema_8 < ema_21 < ema_50:
                confirming_indicators += 1
        
        # 2. RSI
        rsi = self._calculate_rsi(closes, 14)
        if direction == Direction.LONG and 30 < rsi < 70:
            confirming_indicators += 1
        elif direction == Direction.SHORT and 30 < rsi < 70:
            confirming_indicators += 1
        
        # 3. MACD
        macd, signal_line = self._calculate_macd(closes)
        if direction == Direction.LONG and macd > signal_line:
            confirming_indicators += 1
        elif direction == Direction.SHORT and macd < signal_line:
            confirming_indicators += 1
        
        # 4. Stochastic
        stoch_k, stoch_d = self._calculate_stochastic(data, 14, 3)
        if direction == Direction.LONG and stoch_k > stoch_d and stoch_k < 80:
            confirming_indicators += 1
        elif direction == Direction.SHORT and stoch_k < stoch_d and stoch_k > 20:
            confirming_indicators += 1
        
        # 5. Price above/below SMA 200
        if len(closes) >= 200:
            sma_200 = sum(closes[-200:]) / 200
            if direction == Direction.LONG and current_price > sma_200:
                confirming_indicators += 1
            elif direction == Direction.SHORT and current_price < sma_200:
                confirming_indicators += 1
        else:
            confirming_indicators += 0.5  # Neutral if not enough data
        
        # 6. Volume confirmation
        if len(data) >= 20:
            avg_volume = sum(d.volume for d in data[-20:]) / 20
            current_volume = data[-1].volume
            if current_volume > avg_volume * 0.8:
                confirming_indicators += 1
        
        return (confirming_indicators / total_indicators) * 100
    
    def _calculate_risk_alignment(
        self,
        signal: TradingSignal,
        current_positions: Optional[List],
        volatility: VolatilityAnalysis
    ) -> float:
        """Calculate risk alignment score"""
        score = 100.0
        
        # Penalize if adding to existing exposure in same direction
        if current_positions:
            same_direction_count = sum(
                1 for p in current_positions
                if hasattr(p, 'direction') and p.direction == signal.direction
            )
            if same_direction_count >= 3:
                score -= 20
            if same_direction_count >= 5:
                score -= 30
        
        # Penalize high volatility
        if volatility.regime == VolatilityRegime.HIGH:
            score -= 15
        elif volatility.regime == VolatilityRegime.EXTREME:
            score -= 40
        
        # Bonus for expanding volatility in trend direction (breakout potential)
        if volatility.is_expanding and volatility.regime == VolatilityRegime.NORMAL:
            score += 10
        
        return max(0, min(100, score))
    
    def _score_mtf_alignment(
        self,
        analyses: List[TimeframeAnalysis],
        direction: Direction
    ) -> Tuple[float, bool]:
        """Score multi-timeframe alignment"""
        if not analyses:
            return 50.0, False
        
        aligned_count = sum(1 for a in analyses if a.trend_aligned)
        total = len(analyses)
        
        # Calculate weighted score (higher TFs count more)
        tf_weights = {"M15": 0.5, "H1": 1.0, "H4": 1.5, "D1": 2.0}
        weighted_score = 0
        weight_sum = 0
        
        for analysis in analyses:
            weight = tf_weights.get(analysis.timeframe, 1.0)
            if analysis.trend_aligned:
                weighted_score += weight * analysis.strength * 100
            weight_sum += weight
        
        score = weighted_score / weight_sum if weight_sum > 0 else 50
        
        meets_minimum = aligned_count >= self.config.min_mtf_alignment
        
        return score, meets_minimum
    
    def _score_volatility(self, vol: VolatilityAnalysis) -> float:
        """Score volatility conditions (prefer normal volatility)"""
        regime_scores = {
            VolatilityRegime.LOW: 70,
            VolatilityRegime.NORMAL: 100,
            VolatilityRegime.HIGH: 60,
            VolatilityRegime.EXTREME: 20
        }
        return regime_scores.get(vol.regime, 50)
    
    def _score_momentum(self, divergence: MomentumDivergence, direction: Direction) -> float:
        """Score momentum conditions"""
        base_score = 70
        
        if divergence.has_divergence:
            # Confirming divergence (bullish div for longs, bearish for shorts)
            if (direction == Direction.LONG and divergence.divergence_type == "bullish") or \
               (direction == Direction.SHORT and divergence.divergence_type == "bearish"):
                base_score += self.config.divergence_bonus * divergence.strength
            # Counter divergence
            elif (direction == Direction.LONG and divergence.divergence_type == "bearish") or \
                 (direction == Direction.SHORT and divergence.divergence_type == "bullish"):
                base_score -= 25 * divergence.strength
        
        return min(100, max(0, base_score))
    
    def _calculate_position_multiplier(
        self,
        volatility: VolatilityAnalysis,
        confluence_score: float
    ) -> float:
        """Calculate position size multiplier based on conditions"""
        base = volatility.recommended_position_scale
        
        # Scale based on confluence score
        if confluence_score >= 80:
            base *= 1.2
        elif confluence_score >= 70:
            base *= 1.0
        elif confluence_score >= 60:
            base *= 0.8
        else:
            base *= 0.6
        
        return min(1.5, max(0.3, base))
    
    # === Helper Functions ===
    
    def _ema(self, values: List[float], period: int) -> float:
        """Calculate Exponential Moving Average"""
        if len(values) < period:
            return sum(values) / len(values) if values else 0
        
        multiplier = 2 / (period + 1)
        ema = sum(values[:period]) / period
        
        for value in values[period:]:
            ema = (value - ema) * multiplier + ema
        
        return ema
    
    def _calculate_rsi(self, closes: List[float], period: int = 14) -> float:
        """Calculate RSI"""
        if len(closes) < period + 1:
            return 50.0
        
        gains = []
        losses = []
        
        for i in range(1, len(closes)):
            change = closes[i] - closes[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    def _calculate_macd(
        self,
        closes: List[float],
        fast: int = 12,
        slow: int = 26,
        signal: int = 9
    ) -> Tuple[float, float]:
        """Calculate MACD and Signal line"""
        if len(closes) < slow:
            return 0.0, 0.0
        
        ema_fast = self._ema(closes, fast)
        ema_slow = self._ema(closes, slow)
        macd_line = ema_fast - ema_slow
        
        # For signal line, we'd need historical MACD values
        # Simplified: use current value
        signal_line = macd_line * 0.9  # Approximation
        
        return macd_line, signal_line
    
    def _calculate_stochastic(
        self,
        data: List[MarketData],
        k_period: int = 14,
        d_period: int = 3
    ) -> Tuple[float, float]:
        """Calculate Stochastic %K and %D"""
        if len(data) < k_period:
            return 50.0, 50.0
        
        recent = data[-k_period:]
        highest = max(d.high for d in recent)
        lowest = min(d.low for d in recent)
        current_close = data[-1].close
        
        if highest == lowest:
            stoch_k = 50.0
        else:
            stoch_k = ((current_close - lowest) / (highest - lowest)) * 100
        
        # Simplified %D
        stoch_d = stoch_k * 0.9
        
        return stoch_k, stoch_d
    
    def _calculate_atr(self, data: List[MarketData], period: int = 14) -> float:
        """Calculate Average True Range"""
        if len(data) < 2:
            return 0.0
        
        tr_values = []
        for i in range(1, len(data)):
            high = data[i].high
            low = data[i].low
            prev_close = data[i-1].close
            
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            tr_values.append(tr)
        
        if len(tr_values) < period:
            return sum(tr_values) / len(tr_values) if tr_values else 0
        
        return sum(tr_values[-period:]) / period
    
    def _calculate_trend_strength(self, data: List[MarketData]) -> float:
        """Calculate trend strength (0-1)"""
        if len(data) < 20:
            return 0.5
        
        closes = [d.close for d in data[-20:]]
        
        # Simple trend strength: direction consistency
        positive_moves = sum(1 for i in range(1, len(closes)) if closes[i] > closes[i-1])
        strength = positive_moves / (len(closes) - 1)
        
        # Normalize around 0.5
        if strength > 0.5:
            return (strength - 0.5) * 2
        else:
            return (0.5 - strength) * 2
    
    def _percentile_rank(self, value: float, history: List[float]) -> float:
        """Calculate percentile rank of value in history"""
        if not history:
            return 50.0
        
        below = sum(1 for h in history if h < value)
        return (below / len(history)) * 100
    
    def _find_peaks(self, values: List[float]) -> List[float]:
        """Find local peaks in values"""
        peaks = []
        for i in range(1, len(values) - 1):
            if values[i] > values[i-1] and values[i] > values[i+1]:
                peaks.append(values[i])
        return peaks
    
    def _find_troughs(self, values: List[float]) -> List[float]:
        """Find local troughs in values"""
        troughs = []
        for i in range(1, len(values) - 1):
            if values[i] < values[i-1] and values[i] < values[i+1]:
                troughs.append(values[i])
        return troughs
    
    def _check_liquidity_trap(
        self,
        symbol: str,
        direction: Direction,
        historical_data: List[MarketData],
        signal_entry: float
    ) -> Tuple[bool, str]:
        """
        Detect liquidity traps (stop-hunts) that would result in immediate reversal.
        
        ===== FIX #4: LIQUIDITY TRAP PRE-ADMISSION =====
        Moved from post-admission to pre-admission validation stage.
        Returns (is_trap, reason_message)
        """
        if not historical_data or len(historical_data) < 10:
            return False, ""
        
        recent = historical_data[-10:]
        last_bar = historical_data[-1]
        prev_bar = historical_data[-2] if len(historical_data) > 1 else last_bar
        
        # Check for extreme sweep patterns (stop-hunt signature)
        recent_highs = [d.high for d in recent]
        recent_lows = [d.low for d in recent]
        recent_closes = [d.close for d in recent]
        
        range_10bars = max(recent_highs) - min(recent_lows)
        body_last = abs(last_bar.close - last_bar.open)
        
        if range_10bars == 0:
            return False, ""
        
        # Calculate ATR-like measure
        atr_estimate = self._calculate_atr(historical_data[-14:] if len(historical_data) >= 14 else historical_data, period=7)
        
        # Trap Pattern 1: Price hit recent low/high with size 0.0 rejection
        # (Extreme move with reversal signature)
        if body_last > 0:
            if direction == Direction.LONG:
                # Going long: check if we hit a recent swing low then reversed hard up
                recent_min = min(recent_lows[:-1]) if len(recent_lows) > 1 else recent_lows[0]
                if last_bar.low <= recent_min + (atr_estimate * 0.5) and last_bar.close > last_bar.open + (body_last * 0.7):
                    # Hit low and reversed sharply - potential trap
                    return True, f"[LIQUIDITY_TRAP] {symbol} | Price hit recent swing low then reversed | Potential stop-hunt detected"
            else:  # SHORT
                # Going short: check if we hit a recent swing high then reversed hard down
                recent_max = max(recent_highs[:-1]) if len(recent_highs) > 1 else recent_highs[0]
                if last_bar.high >= recent_max - (atr_estimate * 0.5) and last_bar.close < last_bar.open - (body_last * 0.7):
                    # Hit high and reversed sharply - potential trap
                    return True, f"[LIQUIDITY_TRAP] {symbol} | Price hit recent swing high then reversed | Potential stop-hunt detected"
        
        # Trap Pattern 2: Extreme volatility spike that collapses (signature squeeze-then-release trap)
        if len(recent) >= 5:
            last_5_range = max(recent_highs[-5:]) - min(recent_lows[-5:])
            earlier_range = max(recent_highs[:-5]) - min(recent_lows[:-5]) if len(recent) > 5 else last_5_range
            if earlier_range > 0 and last_5_range > earlier_range * 2.5:
                # Extreme spike in last 5 bars - could be liquidity grab
                if body_last < (last_bar.high - last_bar.low) * 0.2:  # Body is tiny relative to range
                    return True, f"[LIQUIDITY_TRAP] {symbol} | Extreme volatility spike with tiny body | Liquidity grab pattern detected"
        
        return False, ""
    
    def _log_analysis(self, signal: TradingSignal, score: ConfluenceScore):
        """Log the analysis results"""
        status = "[APPROVED]" if score.signal_approved else "[REJECTED]"
        
        self.logger.info(
            f"[ENHANCED VALIDATOR] {signal.symbol} {signal.direction.value} | "
            f"{status} | Score: {score.total_score:.1f}/100"
        )
        
        if score.signal_approved:
            self.logger.info(
                f"  MTF: {score.mtf_score:.0f} | Vol: {score.volatility_score:.0f} | "
                f"Mom: {score.momentum_score:.0f} | Liq: {score.liquidity_score:.0f} | "
                f"Confluence: {score.indicator_confluence:.0f} | "
                f"Size Mult: {score.position_size_multiplier:.2f}x"
            )
        else:
            for reason in score.rejection_reasons:
                self.logger.info(f"  [BLOCK] {reason}")
