"""
Predictive Price Engine
-----------------------
Additive chart-structure analysis for predictive edge scoring.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict, Any

from src.models import MarketData, Direction


# Dynamic component weighting (tune via analyzer output)
component_weights = {"OB": 0.08, "FVG": 0.05, "Sweep": 0.10}


@dataclass
class Zone:
    kind: str
    low: float
    high: float
    price: float


class PredictivePriceEngine:
    def __init__(self, lookback: int = 150) -> None:
        self.lookback = int(max(50, lookback))

    def evaluate(
        self,
        *,
        symbol: str,
        bars: List[MarketData],
        signal_direction: Direction,
        current_price: float,
        regime: str = "UNKNOWN",
    ) -> Tuple[float, float, float, Dict[str, object], Optional[Dict[str, Any]], Optional[Tuple[str, str]]]:
        """
        Return (edge_modifier, size_multiplier, dynamic_rr, log_tuple(level, message))
        where level is "info" or "warning".
        """
        if not bars or len(bars) < 10:
            attribution = {"OB": False, "FVG": False, "Sweep": False, "Regime": str(regime or "UNKNOWN").upper()}
            return 0.0, 1.0, 2.5, attribution, None, None

        window = bars[-self.lookback :]
        pip = self._pip_size(symbol)
        bullish_ob = self._find_order_block(window, bullish=True)
        bearish_ob = self._find_order_block(window, bullish=False)
        bullish_fvg, bearish_fvg = self._find_fvg(window)
        bullish_sweep_strength = self._find_liquidity_sweep(window, lookback=20, bullish=True, symbol=symbol)
        bearish_sweep_strength = self._find_liquidity_sweep(window, lookback=20, bullish=False, symbol=symbol)
        bullish_sweep = bullish_sweep_strength > 0.0
        bearish_sweep = bearish_sweep_strength > 0.0

        edge = 0.0
        log_msg = None
        sweep_log: Optional[Tuple[str, str]] = None
        bullish_ob_hit = False
        bearish_ob_hit = False
        bullish_fvg_hit = False
        bearish_fvg_hit = False
        bearish_ob_penalty = False
        bullish_ob_penalty = False
        ob_w = float(component_weights.get("OB", 0.08))
        fvg_w = float(component_weights.get("FVG", 0.05))
        sweep_w = float(component_weights.get("Sweep", 0.10))

        if signal_direction == Direction.LONG:
            if bullish_ob and self._in_zone(current_price, bullish_ob):
                edge += ob_w
                bullish_ob_hit = True
            if bullish_fvg and self._in_zone(current_price, bullish_fvg):
                edge += fvg_w
                bullish_fvg_hit = True
            if bearish_ob and self._near_zone(current_price, bearish_ob, 5 * pip):
                edge -= ob_w
                bearish_ob_penalty = True
        else:
            if bearish_ob and self._in_zone(current_price, bearish_ob):
                edge -= ob_w
                bearish_ob_hit = True
            if bearish_fvg and self._in_zone(current_price, bearish_fvg):
                edge -= fvg_w
                bearish_fvg_hit = True
            if bullish_ob and self._near_zone(current_price, bullish_ob, 5 * pip):
                edge -= ob_w
                bullish_ob_penalty = True

        # Regime-based modifier (two-sided).
        regime_upper = str(regime or "UNKNOWN").upper()
        if ("RANGING" in regime_upper) or ("LOW_LIQUIDITY" in regime_upper):
            edge = edge * 0.6 if edge > 0 else edge * 1.2
        elif "TRENDING" in regime_upper:
            edge = edge * 1.2 if edge > 0 else edge * 0.8

        # Liquidity sweep detection (stop-hunt logic).
        if signal_direction == Direction.LONG:
            weighted_strength = float(bullish_sweep_strength) ** 1.5 if bullish_sweep else 0.0
            if bearish_sweep:
                if edge <= 0.0:
                    edge = -0.20
                else:
                    edge = min(edge - 0.15, -0.05)
                sweep_log = (
                    "warning",
                    f"[PREDICTIVE_CHART] {symbol} | BUYING INTO BEARISH SWEEP TRAP | Severe penalty applied",
                )
            elif bullish_sweep:
                boost = sweep_w if (bullish_ob_hit or bullish_fvg_hit) else sweep_w * 0.8
                edge += boost * weighted_strength
                sweep_log = (
                    "info",
                    f"[PREDICTIVE_CHART] {symbol} | LIQUIDITY SWEEP | Edge applied: +{boost * weighted_strength:.2f}",
                )
        else:
            weighted_strength = float(bearish_sweep_strength) ** 1.5 if bearish_sweep else 0.0

        edge = max(-0.20, min(0.20, edge))

        size_mult = 1.0
        dynamic_rr = 2.5
        if edge >= 0.10:
            size_mult = 1.5
            dynamic_rr = 3.5
        elif edge > 0.0:
            size_mult = 1.2
            dynamic_rr = 3.0
        elif edge == 0.0:
            size_mult = 1.0
            dynamic_rr = 2.5
        elif edge > -0.10:
            size_mult = 0.7
            dynamic_rr = 2.0
        else:
            size_mult = 0.0
            dynamic_rr = 1.0

        # Aggression multiplier based on confluence.
        conviction = "STANDARD"
        if bullish_ob_hit and bullish_fvg_hit and bullish_sweep and signal_direction == Direction.LONG:
            size_mult *= 1.25
            conviction = "MAX"
        elif bearish_ob_hit and bearish_fvg_hit and bearish_sweep and signal_direction != Direction.LONG:
            size_mult *= 1.25
            conviction = "MAX"
        elif edge >= 0.18 and "TRENDING" in regime_upper:
            size_mult *= 1.1
            conviction = "HIGH"
        aggression_factor = min(1.4, 1.0 + (weighted_strength * 0.4))
        size_mult *= aggression_factor
        size_mult = min(2.0, size_mult)

        ob_hit = bullish_ob_hit if signal_direction == Direction.LONG else bearish_ob_hit
        fvg_hit = bullish_fvg_hit if signal_direction == Direction.LONG else bearish_fvg_hit
        sweep_hit = bullish_sweep if signal_direction == Direction.LONG else bearish_sweep
        sweep_strength = bullish_sweep_strength if signal_direction == Direction.LONG else bearish_sweep_strength
        attribution = {
            "OB": bool(ob_hit),
            "FVG": bool(fvg_hit),
            "Sweep": bool(sweep_hit),
            "Regime": regime_upper,
            "Strength": float(weighted_strength),
            "Conviction": conviction,
        }
        attribution_str = f"[OB:{'T' if ob_hit else 'F'}|FVG:{'T' if fvg_hit else 'F'}|Sweep:{'T' if sweep_hit else 'F'}]"

        if sweep_log:
            log_msg = sweep_log
        elif edge != 0.0:
            level = "warning" if edge < 0 else "info"
            split_note = " (Split 1.5R/3.5R)" if dynamic_rr >= 3.0 else ""
            log_msg = (
                level,
                f"[PREDICTIVE_CHART] {symbol} | Attribution: {attribution_str} | "
                f"Strength: {weighted_strength:.2f} | Conviction: {conviction} | "
                f"Target: {dynamic_rr:.1f}R{split_note}",
            )
        if size_mult == 0.0:
            log_msg = (
                "warning",
                f"[PREDICTIVE_CHART] {symbol} | LIQUIDITY TRAP DETECTED | Kill-Switch Engaged (Size 0.0x)",
            )
        exit_plan: Optional[Dict[str, Any]] = None
        if weighted_strength > 0.7 and ob_hit:
            exit_plan = {"scale_out_at": 1.5, "move_sl_to_be": True}
        return edge, size_mult, dynamic_rr, attribution, exit_plan, log_msg

    def _find_liquidity_sweep(
        self,
        bars: List[MarketData],
        lookback: int = 20,
        bullish: bool = True,
        symbol: Optional[str] = None,
    ) -> float:
        if len(bars) < lookback + 3:
            return 0.0
        pool_slice = bars[-(lookback + 3):-3]
        if not pool_slice:
            return 0.0
        last_bar = bars[-1]
        pip = self._pip_size(symbol or "")
        min_absolute_body = pip * 2.5
        if bullish:
            pool_low = min(b.low for b in pool_slice)
            for bar in bars[-3:]:
                if bar.low < pool_low and bar.close > pool_low:
                    bar_range = max(1e-9, (bar.high - bar.low))
                    last_range = max(1e-9, (last_bar.high - last_bar.low))
                    body = abs(bar.close - bar.open)
                    last_body = abs(last_bar.close - last_bar.open)
                    strong_now = (body > bar_range * 0.5) and (body >= min_absolute_body)
                    strong_prev = (last_body > last_range * 0.5) and (last_body >= min_absolute_body)
                    if strong_now or strong_prev:
                        strength = abs(bar.close - bar.open) / bar_range
                        return max(0.0, min(1.0, strength))
        else:
            pool_high = max(b.high for b in pool_slice)
            for bar in bars[-3:]:
                if bar.high > pool_high and bar.close < pool_high:
                    bar_range = max(1e-9, (bar.high - bar.low))
                    last_range = max(1e-9, (last_bar.high - last_bar.low))
                    body = abs(bar.close - bar.open)
                    last_body = abs(last_bar.close - last_bar.open)
                    strong_now = (body > bar_range * 0.5) and (body >= min_absolute_body)
                    strong_prev = (last_body > last_range * 0.5) and (last_body >= min_absolute_body)
                    if strong_now or strong_prev:
                        strength = abs(bar.close - bar.open) / bar_range
                        return max(0.0, min(1.0, strength))
        return 0.0

    def _pip_size(self, symbol: str) -> float:
        return 0.01 if "JPY" in symbol.upper() else 0.0001

    def _find_order_block(self, bars: List[MarketData], *, bullish: bool) -> Optional[Zone]:
        """
        Smart Money Concepts Order Block:
        - Last opposite candle before displacement
        - Displacement (1-3 strong candles)
        - Break of Structure (BOS) beyond last 10-bar swing
        """
        if len(bars) < 15:
            return None

        recent = bars[-60:] if len(bars) > 60 else bars
        bodies = [abs(b.close - b.open) for b in recent]
        avg_body = sum(bodies) / max(1, len(bodies))
        volumes = [float(getattr(b, "volume", 0.0) or 0.0) for b in recent]
        avg_vol = sum(volumes) / max(1, len(volumes))

        max_displacement = 3
        for end_idx in range(len(bars) - 1, 3, -1):
            for seq_len in range(1, max_displacement + 1):
                start_idx = end_idx - seq_len + 1
                if start_idx <= 1:
                    continue
                base_idx = start_idx - 1
                base = bars[base_idx]

                # Base candle must be opposite color.
                if bullish:
                    if not (base.close < base.open):
                        continue
                else:
                    if not (base.close > base.open):
                        continue

                displacement_ok = True
                seq = bars[start_idx:end_idx + 1]
                for c in seq:
                    body = abs(c.close - c.open)
                    vol = float(getattr(c, "volume", 0.0) or 0.0)
                    if bullish:
                        if c.close <= c.open:
                            displacement_ok = False
                            break
                    else:
                        if c.close >= c.open:
                            displacement_ok = False
                            break
                    if body < avg_body * 1.2:
                        displacement_ok = False
                        break
                    if avg_vol > 0 and vol < avg_vol * 1.1:
                        displacement_ok = False
                        break
                if not displacement_ok:
                    continue

                lookback_start = max(0, base_idx - 10)
                swing_slice = bars[lookback_start:base_idx]
                if not swing_slice:
                    continue
                if bullish:
                    swing_high = max(b.high for b in swing_slice)
                    displaced_high = max(b.high for b in seq)
                    if displaced_high <= swing_high:
                        continue
                    return Zone(kind="bullish_ob", low=base.low, high=base.high, price=(base.low + base.high) / 2)
                else:
                    swing_low = min(b.low for b in swing_slice)
                    displaced_low = min(b.low for b in seq)
                    if displaced_low >= swing_low:
                        continue
                    return Zone(kind="bearish_ob", low=base.low, high=base.high, price=(base.low + base.high) / 2)

        return None

    def _find_fvg(self, bars: List[MarketData]) -> Tuple[Optional[Zone], Optional[Zone]]:
        bullish_gap = None
        bearish_gap = None
        for i in range(2, len(bars)):
            b0 = bars[i - 2]
            b2 = bars[i]
            if b0.high < b2.low:
                bullish_gap = Zone(kind="bullish_fvg", low=b0.high, high=b2.low, price=(b0.high + b2.low) / 2)
            if b0.low > b2.high:
                bearish_gap = Zone(kind="bearish_fvg", low=b2.high, high=b0.low, price=(b2.high + b0.low) / 2)
        return bullish_gap, bearish_gap

    def _in_zone(self, price: float, zone: Zone) -> bool:
        return zone.low <= price <= zone.high

    def _near_zone(self, price: float, zone: Zone, threshold: float) -> bool:
        if self._in_zone(price, zone):
            return True
        return min(abs(price - zone.low), abs(price - zone.high)) <= threshold
