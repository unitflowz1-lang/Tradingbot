"""
Stop Loss and Take Profit calculation based on volatility and technical levels
"""
import logging
from typing import Any, Dict, List, Optional
from src.models import MarketData, Direction


class StopLossTakeProfitCalculator:
    """Calculate intelligent stop loss and take profit levels"""
    
    def __init__(self, atr_period: int = 14, risk_reward_ratio: float = 3.0, min_sl_pips: float = 10.0):
        """
        Initialize calculator
        
        Args:
            atr_period: Period for ATR calculation
            risk_reward_ratio: Ratio of reward to risk (e.g., 3.0 means TP is 3.0x SL distance)
            min_sl_pips: Minimum stop loss distance in pips to prevent noise stop-outs
        """
        self.atr_period = atr_period
        self.risk_reward_ratio = risk_reward_ratio
        self.min_sl_pips = min_sl_pips
        self.logger = logging.getLogger(__name__)
    
    def calculate_atr(self, historical_data: List[MarketData]) -> float:
        """
        Calculate Average True Range (ATR)
        
        Args:
            historical_data: List of market data points
            
        Returns:
            ATR value
        """
        if len(historical_data) < self.atr_period:
            return 0.0
        
        true_ranges = []
        for i in range(1, len(historical_data)):
            high = historical_data[i].high
            low = historical_data[i].low
            prev_close = historical_data[i-1].close
            
            # True Range = max(H-L, |H-PC|, |L-PC|)
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            true_ranges.append(tr)
        
        # ATR = average of true ranges over the period
        atr = sum(true_ranges[-self.atr_period:]) / self.atr_period
        return atr

    def _extract_numeric_field(self, source: Any, *field_names: str) -> float:
        """Best-effort numeric extraction from dict-like or object payloads."""
        if source is None:
            return 0.0

        for field_name in field_names:
            value = None
            if isinstance(source, dict):
                value = source.get(field_name)
            else:
                value = getattr(source, field_name, None)
                if value is None and hasattr(source, "get"):
                    try:
                        value = source.get(field_name)
                    except Exception:
                        value = None
            try:
                numeric_value = float(value or 0.0)
            except Exception:
                numeric_value = 0.0
            if numeric_value > 0.0:
                return numeric_value
        return 0.0

    def resolve_atr_value(
        self,
        *,
        market_snapshot: Any = None,
        strategy_meta: Optional[Dict[str, Any]] = None,
        technical_indicators: Any = None,
        historical_data: Optional[List[MarketData]] = None,
    ) -> float:
        """
        Resolve ATR from the live quote, strategy metadata, technical buffers,
        or a direct recalculation from historical data.
        """
        strategy_meta = dict(strategy_meta or {})
        symbol_report = dict(strategy_meta.get("symbol_report") or {})

        current_atr = self._extract_numeric_field(market_snapshot, "atr")
        if current_atr > 0.0:
            return current_atr

        market_indicators = None
        if isinstance(market_snapshot, dict):
            market_indicators = market_snapshot.get("indicators") or market_snapshot.get("technical_indicators")
        else:
            market_indicators = getattr(market_snapshot, "indicators", None) or getattr(
                market_snapshot, "technical_indicators", None
            )
        current_atr = self._extract_numeric_field(market_indicators, "atr", "ATR")
        if current_atr > 0.0:
            return current_atr

        current_atr = self._extract_numeric_field(
            strategy_meta,
            "atr",
            "current_atr",
        )
        if current_atr > 0.0:
            return current_atr

        current_atr = self._extract_numeric_field(
            symbol_report,
            "atr",
            "current_atr",
            "volatility",
        )
        if current_atr > 0.0:
            return current_atr

        current_atr = self._extract_numeric_field(technical_indicators, "atr", "ATR")
        if current_atr > 0.0:
            return current_atr

        technical_buffer = strategy_meta.get("technical_indicators") or strategy_meta.get("indicator_buffer")
        current_atr = self._extract_numeric_field(technical_buffer, "atr", "ATR")
        if current_atr > 0.0:
            return current_atr

        if historical_data:
            try:
                current_atr = float(self.calculate_atr(historical_data) or 0.0)
            except Exception:
                current_atr = 0.0
            if current_atr > 0.0:
                return current_atr

        return 0.0
    
    def calculate_volatility_percentage(self, historical_data: List[MarketData]) -> float:
        """
        Calculate volatility as percentage of current price
        
        Args:
            historical_data: List of market data points
            
        Returns:
            Volatility as percentage (e.g., 0.01 for 1%)
        """
        if not historical_data:
            return 0.01  # Default 1% if no data
        
        atr = self.calculate_atr(historical_data)
        current_price = historical_data[-1].close
        
        if current_price <= 0:
            return 0.01
        
        volatility = atr / current_price
        return max(volatility, 0.001)  # Minimum 0.1%
    
    def calculate_levels(
        self,
        entry_price: float,
        direction: Direction,
        historical_data: List[MarketData],
        risk_points: Optional[float] = None,
        current_volatility: Optional[float] = None,
        garch_forecast_volatility: Optional[float] = None,
    ) -> dict:
        """
        Calculate intelligent stop loss and take profit levels using swing points and ATR.
        **IMPROVED:** Volatility-adjusted ATR multiplier for dynamic stop placement.
        With Support/Resistance awareness for TP levels.
        
        Args:
            entry_price: Entry price
            direction: Trade direction (LONG/SHORT)
            historical_data: Historical market data
            risk_points: Optional fixed risk points
            current_volatility: Current market volatility (%)
        
        Returns:
            Tuple of (stop_loss, primary_take_profit)
        """
        atr = self.calculate_atr(historical_data)
        symbol = historical_data[0].symbol if historical_data else "Unknown"
        pip_value = self._get_pip_value(entry_price, symbol)
        
        if risk_points:
            sl_distance = risk_points * pip_value
        else:
            # **IMPROVED:** Calculate volatility-adjusted ATR multiplier
            atr_multiplier = 2.5  # Default for H1
            
            if current_volatility is not None:
                vol_ratio = current_volatility / 0.8  # Normalize to 0.8% typical volatility
                
                if vol_ratio > 2.5:    # Extreme volatility spike
                    atr_multiplier = 4.0  # Extra wide for stability
                elif vol_ratio > 1.8:  # High volatility
                    atr_multiplier = 3.5
                elif vol_ratio > 1.2:  # Elevated volatility
                    atr_multiplier = 3.0
                elif vol_ratio < 0.6:  # Quiet periods
                    atr_multiplier = 2.0  # Tighter stops in low volatility
                # else: use default 2.5x ATR
            
            # 1. Base ATR Stop (Volatility-adjusted Multiplier)
            base_sl_dist = atr * atr_multiplier

            if garch_forecast_volatility is not None and entry_price > 0:
                normalized_forecast = max(float(garch_forecast_volatility), 0.0)
                forecast_pct = normalized_forecast * 100.0
                if normalized_forecast > 0.0:
                    widening_factor = 1.0 + min(normalized_forecast * 8.0, 1.5)
                    base_sl_dist *= widening_factor
                    self.logger.info(
                        "[RISK_ADJUST] Widening Stop Loss based on GARCH forecast of %.4f%%.",
                        forecast_pct,
                    )
            
            # 2. Look for recent swing points (last 15 bars)
            lookback = 15
            relevant_data = historical_data[-lookback:] if len(historical_data) >= lookback else historical_data
            
            if direction == Direction.LONG:
                swing_low = min(d.low for d in relevant_data)
                swing_sl_dist = entry_price - (swing_low - (atr * 0.2)) # Tighter buffer 0.2
                
                # Check if swing SL is reasonable (within 1.5x to 5.0x ATR)
                if atr * 1.5 <= swing_sl_dist <= atr * 5.0:
                    sl_distance = swing_sl_dist
                else:
                    sl_distance = base_sl_dist
            else:  # SHORT
                swing_high = max(d.high for d in relevant_data)
                swing_sl_dist = (swing_high + (atr * 0.2)) - entry_price
                
                if atr * 1.5 <= swing_sl_dist <= atr * 5.0:
                    sl_distance = swing_sl_dist
                else:
                    sl_distance = base_sl_dist

        # Enforce minimum stop loss distance (prevents M1 noise stop-outs)
        min_distance = self.min_sl_pips * pip_value
        if sl_distance < min_distance:
            sl_distance = min_distance

        # 3. Calculate Take Profit based on Risk:Reward and S/R
        # Primary target is risk_reward_ratio (default 3.0)
        tp_distance = sl_distance * self.risk_reward_ratio
        raw_tp = entry_price + tp_distance if direction == Direction.LONG else entry_price - tp_distance
        
        # 4. Refine TP based on Support/Resistance (Pivot Points and Psychological Levels)
        refined_tp = self._refine_tp_with_sr(raw_tp, direction, relevant_data, pip_value)
        
        # 2.5: Add Minimum Spread Buffer for low-liquidity sessions
        # London Open and Tokyo can have wider spreads; add extra buffer
        symbol_upper = symbol.upper()
        is_jpy = 'JPY' in symbol_upper
        is_cross = '/' in symbol_upper and 'USD' not in symbol_upper
        
        # Determine if we need extra buffer (pips)
        spread_buffer_pips = 0.0
        if is_jpy or is_cross:
            spread_buffer_pips = 2.5 # Extra 2.5 pips for crosses/JPY
        else:
            spread_buffer_pips = 1.2 # Extra 1.2 pips for majors
            
        sl_distance += (spread_buffer_pips * pip_value)

        stop_loss = entry_price - sl_distance if direction == Direction.LONG else entry_price + sl_distance
        take_profit = refined_tp
        
        # ===== FIX #1: PRICE-BASED RR IS THE ONLY SOURCE OF TRUTH =====
        # Calculate RR using FINAL adjusted prices (after spread buffer, S/R refinement)
        # This is the ACTUAL RR the trade will execute with - no theoretical values
        raw_risk = abs(entry_price - stop_loss)
        raw_reward = abs(take_profit - entry_price)
        final_rr = 0.0
        if raw_risk > 0:
            final_rr = raw_reward / raw_risk
            
        self.logger.info(
            "[SLTP_CALC] %s | FINAL RR %.2fR (price-based) | Entry=%.5f SL=%.5f TP=%.5f | Risk=%.5f Reward=%.5f",
            symbol,
            final_rr,
            entry_price,
            stop_loss,
            take_profit,
            raw_risk,
            raw_reward,
        )
        
        return {
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "rr_ratio": final_rr,  # ONLY price-based RR - no theoretical values
            "expectancy": final_rr  # Synced to prevent ghosting
        }

    def calculate_multi_tp(
        self,
        entry_price: float,
        stop_loss: float,
        direction: Direction,
        historical_data: List[MarketData]
    ) -> List[float]:
        """
        Calculate multiple take profit levels for scaling out
        
        Returns:
            List of [TP1, TP2, TP3]
        """
        risk = abs(entry_price - stop_loss)
        symbol = historical_data[0].symbol if historical_data else "Unknown"
        pip_value = self._get_pip_value(entry_price, symbol)
        
        # Define R-multiples for targets
        targets_R = [1.0, 2.0, 3.5] # TP1: 1:1, TP2: 1:2, TP3: 1:3.5
        tp_levels = []
        
        for r in targets_R:
            dist = risk * r
            tp = entry_price + dist if direction == Direction.LONG else entry_price - dist
            # Refine each level with S/R
            refined_tp = self._refine_tp_with_sr(tp, direction, historical_data[-20:], pip_value)
            tp_levels.append(refined_tp)
            
        return tp_levels

    def _refine_tp_with_sr(self, tp_price: float, direction: Direction, recent_data: List[MarketData], pip_value: float) -> float:
        """Adjust TP to be slightly BEFORE major levels (Support/Resistance/Psychological)"""
        
        # A. Psychological Levels (00, 50 levels)
        # Rounding to nearest 50 pips usually acts as magnet/resistance
        psych_factor = 50 * pip_value
        if direction == Direction.LONG:
            # For LONG, place TP just BELOW a major level
            nearest_psych = (tp_price // psych_factor) * psych_factor
            if abs(tp_price - nearest_psych) < (10 * pip_value): # Within 10 pips
                 return nearest_psych - (2 * pip_value) # 2 pip buffer
        else:
            # For SHORT, place TP just ABOVE a major level
            nearest_psych = ((tp_price // psych_factor) + 1) * psych_factor
            if abs(tp_price - nearest_psych) < (10 * pip_value):
                 return nearest_psych + (2 * pip_value)
                 
        # B. Recent Highs/Lows (Pivot Resistance)
        if direction == Direction.LONG:
            # Look for recent high within 5% of TP
            recent_high = max(d.high for d in recent_data)
            if abs(tp_price - recent_high) / tp_price < 0.002: # Within 0.2%
                return recent_high - (3 * pip_value) # Buffer below high
        else:
            recent_low = min(d.low for d in recent_data)
            if abs(tp_price - recent_low) / tp_price < 0.002:
                return recent_low + (3 * pip_value)
                
        return tp_price

    def _get_pip_value(self, price: float, symbol: str) -> float:
        """
        Get pip value for a symbol (0.0001 for most pairs, 0.01 for JPY pairs)
        """
        if 'JPY' in symbol.upper():
            return 0.01
        return 0.0001
    
    def calculate_max_loss_sl(
        self,
        entry_price: float,
        direction: Direction,
        max_loss_pct: float,
        position_size: float
    ) -> float:
        """
        Calculate stop loss based on max acceptable loss percentage
        
        Args:
            entry_price: Entry price
            direction: LONG or SHORT
            max_loss_pct: Max loss as percentage (e.g., 0.02 for 2%)
            position_size: Position size in lots
            
        Returns:
            Stop loss price
        """
        sl_distance = entry_price * max_loss_pct
        
        if direction == Direction.LONG:
            stop_loss = entry_price - sl_distance
        else:
            stop_loss = entry_price + sl_distance
        
        return stop_loss
