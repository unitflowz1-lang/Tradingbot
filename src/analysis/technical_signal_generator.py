"""Technical signal generation from indicators and patterns"""

from typing import List, Dict, Optional
from datetime import datetime
from src.models import TechnicalSignal, SignalType, MarketData
from src.analysis.technical_indicators import TechnicalIndicators, IndicatorCalculator
from src.analysis.pattern_recognition import PatternRecognizer, ChartPattern, SupportResistanceLevel
from src.exceptions import DataValidationError


class TechnicalSignalGenerator:
    """Generate trading signals from technical indicators and patterns"""
    
    def __init__(self, 
                 rsi_oversold: float = 25.0,
                 rsi_overbought: float = 70.0,
                 stoch_oversold: float = 20.0,
                 stoch_overbought: float = 80.0):
        """Initialize signal generator with thresholds"""
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.stoch_oversold = stoch_oversold
        self.stoch_overbought = stoch_overbought
        
        self.indicator_calculator = IndicatorCalculator()
        self.pattern_recognizer = PatternRecognizer()
    
    def generate_signals(self, 
                        market_data: List[MarketData],
                        indicators: TechnicalIndicators,
                        patterns: List[ChartPattern] = None,
                        support_resistance: List[SupportResistanceLevel] = None) -> List[TechnicalSignal]:
        """Generate technical signals from all available data"""
        
        if not market_data:
            raise DataValidationError(
                "Market data is required for signal generation",
                error_code="NO_MARKET_DATA",
                context={}
            )
        
        current_data = market_data[-1]
        signals = []
        
        # Generate signals from indicators
        indicator_signals = self._generate_indicator_signals(indicators, current_data)
        signals.extend(indicator_signals)
        
        # Generate signals from patterns
        if patterns:
            pattern_signals = self._generate_pattern_signals(patterns, current_data)
            signals.extend(pattern_signals)
        
        # Generate signals from support/resistance
        if support_resistance:
            sr_signals = self._generate_support_resistance_signals(
                support_resistance, current_data, market_data[-5:]
            )
            signals.extend(sr_signals)
        
        # Combine and filter signals
        combined_signals = self._combine_signals(signals)
        
        return combined_signals
    
    def _generate_indicator_signals(self, 
                                  indicators: TechnicalIndicators,
                                  current_data: MarketData) -> List[TechnicalSignal]:
        """Generate signals from technical indicators"""
        signals = []
        current_price = current_data.close
        
        # RSI signals
        if indicators.rsi is not None:
            rsi_signal = self._generate_rsi_signal(indicators.rsi, current_data)
            if rsi_signal:
                signals.append(rsi_signal)
        
        # Moving average crossover signals
        if indicators.sma_20 is not None and indicators.sma_50 is not None:
            ma_signal = self._generate_ma_crossover_signal(
                indicators.sma_20, indicators.sma_50, current_data
            )
            if ma_signal:
                signals.append(ma_signal)
        
        # MACD signals
        if (indicators.macd is not None and 
            indicators.macd_signal is not None):
            macd_signal = self._generate_macd_signal(
                indicators.macd, indicators.macd_signal, current_data
            )
            if macd_signal:
                signals.append(macd_signal)
        
        # Bollinger Bands signals
        if (indicators.bollinger_upper is not None and 
            indicators.bollinger_lower is not None):
            bb_signal = self._generate_bollinger_signal(
                current_price, indicators.bollinger_upper, 
                indicators.bollinger_lower, current_data
            )
            if bb_signal:
                signals.append(bb_signal)
        
        # Stochastic signals
        if indicators.stochastic_k is not None:
            stoch_signal = self._generate_stochastic_signal(
                indicators.stochastic_k, current_data
            )
            if stoch_signal:
                signals.append(stoch_signal)

        # Williams %R signals
        if indicators.williams_r is not None:
            w_r_signal = self._generate_williams_r_signal(
                indicators.williams_r, current_data
            )
            if w_r_signal:
                signals.append(w_r_signal)
        
        # Add ADX trend strength as a weight to existing signals (Session-Aware)
        if indicators.adx is not None:
            from src.analysis.market_regime_detector import MarketRegimeDetector
            detector = MarketRegimeDetector()
            session = detector.detect_session(current_data.timestamp)
            thresholds = detector.get_dynamic_thresholds(session)
            
            for signal in signals:
                # Boost signals if trend is strong for this session
                if indicators.adx > thresholds['adx_strong']:
                    signal.strength = min(signal.strength * 1.2, 1.0)
                # Weaken signals if trend is weak for this session
                elif indicators.adx < thresholds['adx_weak']:
                    signal.strength *= 0.7
        
        return signals
    
    def _generate_rsi_signal(self, rsi: float, current_data: MarketData) -> Optional[TechnicalSignal]:
        """Generate signal from RSI with session-aware thresholds"""
        from src.analysis.market_regime_detector import MarketRegimeDetector
        detector = MarketRegimeDetector()
        session = detector.detect_session(current_data.timestamp)
        thresholds = detector.get_dynamic_thresholds(session)
        
        oversold = thresholds['rsi_os']
        overbought = thresholds['rsi_ob']
        
        if rsi <= oversold:
            # Enhance strength calculation for stricter entry
            # Base strength 0.6, scales up as RSI goes deeper below oversold
            depth = oversold - rsi
            # Non-linear scaling: small dips get 0.6, deep dips get closer to 1.0 quickly
            scaled_strength = min(0.6 + (depth / 10.0) * 0.4, 1.0)
            
            return TechnicalSignal(
                symbol=current_data.symbol,
                signal_type=SignalType.BUY,
                strength=scaled_strength,
                indicators={"rsi": rsi, "threshold": oversold, "depth": depth},
                timestamp=current_data.timestamp
            )
        elif rsi >= overbought:
            # Enhance strength calculation for stricter entry
            depth = rsi - overbought
            scaled_strength = min(0.6 + (depth / 10.0) * 0.4, 1.0)
            
            return TechnicalSignal(
                symbol=current_data.symbol,
                signal_type=SignalType.SELL,
                strength=scaled_strength,
                indicators={"rsi": rsi, "threshold": overbought, "depth": depth},
                timestamp=current_data.timestamp
            )
        return None

    def _generate_williams_r_signal(self, w_r: float, current_data: MarketData) -> Optional[TechnicalSignal]:
        """Generate signal from Williams %R"""
        # Overbought usually > -20, Oversold < -80
        if w_r <= -80:
            return TechnicalSignal(
                symbol=current_data.symbol,
                signal_type=SignalType.BUY,
                strength=0.5, # Moderate strength
                indicators={"williams_r": w_r},
                timestamp=current_data.timestamp
            )
        elif w_r >= -20:
            return TechnicalSignal(
                symbol=current_data.symbol,
                signal_type=SignalType.SELL,
                strength=0.5,
                indicators={"williams_r": w_r},
                timestamp=current_data.timestamp
            )
        return None
    
    def _generate_ma_crossover_signal(self, sma_20: float, sma_50: float, 
                                    current_data: MarketData) -> Optional[TechnicalSignal]:
        """Generate signal from moving average crossover"""
        current_price = current_data.close
        
        # Golden cross (bullish)
        if sma_20 > sma_50 and current_price > sma_20:
            # Scale difference for Forex (pips matter)
            strength = min(((sma_20 - sma_50) / sma_50) * 100, 0.8)
            # Ensure a minimum strength if cross exists
            strength = max(strength, 0.3)
            return TechnicalSignal(
                symbol=current_data.symbol,
                signal_type=SignalType.BUY,
                strength=strength,
                indicators={"sma_20": sma_20, "sma_50": sma_50, "price": current_price},
                timestamp=current_data.timestamp
            )
        
        # Death cross (bearish)
        elif sma_20 < sma_50 and current_price < sma_20:
            strength = min(((sma_50 - sma_20) / sma_50) * 100, 0.8)
            strength = max(strength, 0.3)
            return TechnicalSignal(
                symbol=current_data.symbol,
                signal_type=SignalType.SELL,
                strength=strength,
                indicators={"sma_20": sma_20, "sma_50": sma_50, "price": current_price},
                timestamp=current_data.timestamp
            )
        
        return None
    
    def _generate_macd_signal(self, macd: float, macd_signal: float, 
                            current_data: MarketData) -> Optional[TechnicalSignal]:
        """Generate signal from MACD"""
        macd_diff = macd - macd_signal
        
        # MACD bullish crossover
        if macd > macd_signal and macd_diff > 0:
            strength = min(abs(macd_diff) * 1000, 0.8)  # Scale appropriately
            return TechnicalSignal(
                symbol=current_data.symbol,
                signal_type=SignalType.BUY,
                strength=strength,
                indicators={"macd": macd, "macd_signal": macd_signal},
                timestamp=current_data.timestamp
            )
        
        # MACD bearish crossover
        elif macd < macd_signal and macd_diff < 0:
            strength = min(abs(macd_diff) * 1000, 0.8)
            return TechnicalSignal(
                symbol=current_data.symbol,
                signal_type=SignalType.SELL,
                strength=strength,
                indicators={"macd": macd, "macd_signal": macd_signal},
                timestamp=current_data.timestamp
            )
        
        return None
    
    def _generate_bollinger_signal(self, current_price: float, upper_band: float, 
                                 lower_band: float, current_data: MarketData) -> Optional[TechnicalSignal]:
        """Generate signal from Bollinger Bands"""
        # Price touching lower band (oversold)
        if current_price <= lower_band * 1.001:  # Small tolerance
            strength = min(max((lower_band - current_price) / lower_band, 0.0), 0.8)
            return TechnicalSignal(
                symbol=current_data.symbol,
                signal_type=SignalType.BUY,
                strength=strength,
                indicators={
                    "price": current_price,
                    "bb_upper": upper_band,
                    "bb_lower": lower_band
                },
                timestamp=current_data.timestamp
            )
        
        # Price touching upper band (overbought)
        elif current_price >= upper_band * 0.999:  # Small tolerance
            strength = min(max((current_price - upper_band) / upper_band, 0.0), 0.8)
            return TechnicalSignal(
                symbol=current_data.symbol,
                signal_type=SignalType.SELL,
                strength=strength,
                indicators={
                    "price": current_price,
                    "bb_upper": upper_band,
                    "bb_lower": lower_band
                },
                timestamp=current_data.timestamp
            )
        
        return None
    
    def _generate_stochastic_signal(self, stoch_k: float, 
                                  current_data: MarketData) -> Optional[TechnicalSignal]:
        """Generate signal from Stochastic oscillator"""
        if stoch_k <= self.stoch_oversold:
            strength = min((self.stoch_oversold - stoch_k) / self.stoch_oversold, 1.0)
            return TechnicalSignal(
                symbol=current_data.symbol,
                signal_type=SignalType.BUY,
                strength=strength,
                indicators={"stochastic_k": stoch_k},
                timestamp=current_data.timestamp
            )
        elif stoch_k >= self.stoch_overbought:
            strength = min((stoch_k - self.stoch_overbought) / (100 - self.stoch_overbought), 1.0)
            return TechnicalSignal(
                symbol=current_data.symbol,
                signal_type=SignalType.SELL,
                strength=strength,
                indicators={"stochastic_k": stoch_k},
                timestamp=current_data.timestamp
            )
        
        return None
    
    def _generate_pattern_signals(self, patterns: List[ChartPattern], 
                                current_data: MarketData) -> List[TechnicalSignal]:
        """Generate signals from chart patterns"""
        signals = []
        
        for pattern in patterns:
            if pattern.confidence < 0.5:  # Skip low confidence patterns
                continue
            
            signal_type = SignalType.BUY if pattern.expected_direction == "BULLISH" else SignalType.SELL
            
            signal = TechnicalSignal(
                symbol=current_data.symbol,
                signal_type=signal_type,
                strength=pattern.confidence,
                indicators={
                    "pattern_confidence": pattern.confidence,
                    "pattern_strength": 1.0 if pattern.expected_direction == "BULLISH" else -1.0
                },
                timestamp=current_data.timestamp
            )
            signals.append(signal)
        
        return signals
    
    def _generate_support_resistance_signals(self, 
                                           levels: List[SupportResistanceLevel],
                                           current_data: MarketData,
                                           recent_data: List[MarketData]) -> List[TechnicalSignal]:
        """Generate signals from support/resistance levels"""
        signals = []
        current_price = current_data.close
        
        for level in levels:
            if level.strength < 0.5:  # Skip weak levels
                continue
            
            price_diff = abs(current_price - level.price) / level.price
            
            # Price near support level
            if (level.level_type == "SUPPORT" and 
                price_diff < 0.005 and  # Within 0.5%
                current_price > level.price):
                
                # Check if price is bouncing off support
                if self._is_bouncing_off_level(recent_data, level.price, "SUPPORT"):
                    signal = TechnicalSignal(
                        symbol=current_data.symbol,
                        signal_type=SignalType.BUY,
                        strength=level.strength * 0.8,
                        indicators={
                            "support_level": level.price,
                            "level_strength": level.strength,
                            "current_price": current_price
                        },
                        timestamp=current_data.timestamp
                    )
                    signals.append(signal)
            
            # Price near resistance level
            elif (level.level_type == "RESISTANCE" and 
                  price_diff < 0.005 and
                  current_price < level.price):
                
                # Check if price is rejecting at resistance
                if self._is_bouncing_off_level(recent_data, level.price, "RESISTANCE"):
                    signal = TechnicalSignal(
                        symbol=current_data.symbol,
                        signal_type=SignalType.SELL,
                        strength=level.strength * 0.8,
                        indicators={
                            "resistance_level": level.price,
                            "level_strength": level.strength,
                            "current_price": current_price
                        },
                        timestamp=current_data.timestamp
                    )
                    signals.append(signal)
        
        return signals
    
    def _is_bouncing_off_level(self, recent_data: List[MarketData], 
                             level_price: float, level_type: str) -> bool:
        """Check if price is bouncing off support/resistance level"""
        if len(recent_data) < 3:
            return False
        
        tolerance = level_price * 0.002  # 0.2% tolerance
        
        if level_type == "SUPPORT":
            # Check if recent lows touched support and price is moving up
            recent_lows = [d.low for d in recent_data]
            touched_support = any(abs(low - level_price) <= tolerance for low in recent_lows)
            
            if touched_support:
                # Check if latest price is moving away from support
                return recent_data[-1].close > recent_data[-2].close
        
        else:  # RESISTANCE
            # Check if recent highs touched resistance and price is moving down
            recent_highs = [d.high for d in recent_data]
            touched_resistance = any(abs(high - level_price) <= tolerance for high in recent_highs)
            
            if touched_resistance:
                # Check if latest price is moving away from resistance
                return recent_data[-1].close < recent_data[-2].close
        
        return False
    
    def _combine_signals(self, signals: List[TechnicalSignal]) -> List[TechnicalSignal]:
        """Combine and filter signals to avoid conflicts"""
        if not signals:
            return []
        
        # Group signals by type
        buy_signals = [s for s in signals if s.signal_type == SignalType.BUY]
        sell_signals = [s for s in signals if s.signal_type == SignalType.SELL]
        
        combined_signals = []
        
        # Combine buy signals
        if buy_signals:
            combined_buy = self._merge_signals(buy_signals, SignalType.BUY)
            combined_signals.append(combined_buy)
        
        # Combine sell signals
        if sell_signals:
            combined_sell = self._merge_signals(sell_signals, SignalType.SELL)
            combined_signals.append(combined_sell)
        
        # If both buy and sell signals exist, keep the stronger one
        if len(combined_signals) == 2:
            buy_signal = next(s for s in combined_signals if s.signal_type == SignalType.BUY)
            sell_signal = next(s for s in combined_signals if s.signal_type == SignalType.SELL)
            
            if buy_signal.strength > sell_signal.strength:
                return [buy_signal]
            else:
                return [sell_signal]
        
        return combined_signals
    
    def _merge_signals(self, signals: List[TechnicalSignal], 
                      signal_type: SignalType) -> TechnicalSignal:
        """Merge multiple signals of the same type"""
        if len(signals) == 1:
            return signals[0]
        
        # Calculate weighted average strength
        total_strength = sum(s.strength for s in signals)
        avg_strength = min(total_strength / len(signals), 1.0)
        
        # Combine all indicators
        combined_indicators = {}
        for signal in signals:
            combined_indicators.update(signal.indicators)
        
        # Use the most recent timestamp
        latest_timestamp = max(s.timestamp for s in signals)
        
        return TechnicalSignal(
            symbol=signals[0].symbol,
            signal_type=signal_type,
            strength=avg_strength,
            indicators=combined_indicators,
            timestamp=latest_timestamp
        )
    
    def calculate_signal_confluence(self, signals: List[TechnicalSignal]) -> float:
        """Calculate confluence score based on multiple signals"""
        if not signals:
            return 0.0
        
        # Count signals by type
        buy_count = sum(1 for s in signals if s.signal_type == SignalType.BUY)
        sell_count = sum(1 for s in signals if s.signal_type == SignalType.SELL)
        
        # Calculate confluence based on agreement
        total_signals = len(signals)
        max_agreement = max(buy_count, sell_count)
        
        confluence = max_agreement / total_signals
        
        # Boost confluence if multiple strong signals agree
        if max_agreement >= 3:
            confluence = min(confluence * 1.2, 1.0)
        
        return confluence