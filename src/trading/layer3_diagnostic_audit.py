"""
Layer 3 Diagnostic Audit System
===============================

Read-only diagnostic function to verify Layer 3 (Time-Decay Stop Loss) 
functionality in shadow mode. Reports on position health, constraint validation,
and auto-rotation eligibility without executing any trades.

Can be triggered manually or integrated into heartbeat pulse.
"""

import logging
import asyncio
import MetaTrader5 as mt5
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone
from dataclasses import dataclass

from src.models import Position, Direction
from src.trading.profit_protection_module import ProfitProtectionModule
from src.utils.pip_standardizer import PipStandardizer

logger = logging.getLogger(__name__)


@dataclass
class DiagnosticResult:
    """Result of a single position diagnostic"""
    position_id: int
    symbol: str
    direction: str
    status: str  # PASS, FAIL, WARNING
    bars_since_entry: int
    current_sl: float
    proposed_sl: Optional[float]
    atr: float
    spread_pips: float
    constraints_check: str
    reason: str
    marked_for_auto_rotation: bool
    details: Dict[str, Any]


class Layer3DiagnosticAudit:
    """
    Diagnostic auditor for Layer 3 Time-Decay Stop Loss features.
    
    Usage:
        auditor = Layer3DiagnosticAudit(profit_protection_module)
        results = await auditor.run_full_audit(broker, all_open_positions)
        auditor.print_audit_report(results)
    """
    
    def __init__(self, profit_protection_module: ProfitProtectionModule):
        """Initialize auditor with reference to profit protection module"""
        self.ppm = profit_protection_module
        self.audit_timestamp = datetime.now(timezone.utc)
        
    def _get_pip_value(self, symbol: str) -> float:
        """Get pip value for symbol"""
        if 'JPY' in symbol.upper():
            return 0.01
        return 0.0001
    
    def _get_symbol_digits(self, symbol: str) -> int:
        """Get number of decimal places for symbol"""
        if 'JPY' in symbol.upper():
            return 2
        return 4
    
    async def _get_symbol_info(self, symbol: str) -> Optional[Any]:
        """Fetch symbol info from MT5"""
        try:
            mt5_symbol = symbol.replace("/", "")
            return await asyncio.to_thread(mt5.symbol_info, mt5_symbol)
        except Exception as e:
            logger.error(f"Failed to fetch symbol info for {symbol}: {e}")
            return None
    
    async def _get_current_tick(self, symbol: str) -> Optional[Any]:
        """Fetch current tick from MT5"""
        try:
            mt5_symbol = symbol.replace("/", "")
            return await asyncio.to_thread(mt5.symbol_info_tick, mt5_symbol)
        except Exception as e:
            logger.error(f"Failed to fetch current tick for {symbol}: {e}")
            return None
    
    def _calculate_spread_pips(self, symbol: str, bid: float, ask: float) -> float:
        """Calculate spread in pips"""
        pip_val = self._get_pip_value(symbol)
        if pip_val <= 0:
            return 0.0
        spread_value = ask - bid
        return spread_value / pip_val
    
    async def _get_proposed_sl(
        self,
        position: Position,
        state: Dict[str, Any],
        current_r: float,
        atr: float,
    ) -> Optional[float]:
        """
        Get proposed SL from Layer 3 time_decay_manager.
        
        Returns proposed SL price or None if decay doesn't apply.
        """
        try:
            if not self.ppm.time_decay_enabled:
                return None
            
            # Fetch broker constraints
            symbol_info = await self._get_symbol_info(position.symbol)
            mt5_symbol = position.symbol.replace("/", "")
            current_tick = await asyncio.to_thread(mt5.symbol_info_tick, mt5_symbol)
            
            if not symbol_info or not current_tick:
                return None
            
            # Calculate risk price
            risk_price = state.get('initial_risk_price', 0.0)
            if risk_price <= 0:
                return None
            
            # Get bars_since_entry from state
            bars_since_entry = state.get('bars_since_entry', 0)
            
            # Call Layer 3's check_and_apply_decay (returns Optional[float])
            proposed_sl = await self.ppm.time_decay_manager.check_and_apply_decay(
                position=position,
                state=state,
                current_r=current_r,
                bars_since_entry=bars_since_entry,
                risk_price=risk_price,
                symbol_info=symbol_info,
                current_tick=current_tick,
            )
            
            return proposed_sl
        
        except Exception as e:
            logger.error(f"Error fetching proposed SL for {position.symbol} #{position.position_id}: {e}")
            return None
    
    def _validate_proposed_sl(
        self,
        position: Position,
        current_sl: float,
        proposed_sl: Optional[float],
        spread_pips: float,
        symbol_info: Optional[Any],
        current_tick: Optional[Any],
    ) -> Tuple[str, str]:
        """
        Validate proposed SL against constraints.
        
        Returns: (status, reason)
            status: "PASS", "FAIL", or "WARNING"
            reason: Human-readable explanation
        """
        if proposed_sl is None:
            return "INFO", "No decay proposal (position not stagnant yet)"
        
        pip_val = self._get_pip_value(position.symbol)
        digits = self._get_symbol_digits(position.symbol)
        
        # Extract broker constraints
        trade_stops_level = float(getattr(symbol_info, 'trade_stops_level', 0) or 0) if symbol_info else 0
        freeze_level = float(getattr(symbol_info, 'trade_freeze_level', 0) or 0) if symbol_info else 0
        bid = float(getattr(current_tick, 'bid', 0) or 0) if current_tick else 0
        ask = float(getattr(current_tick, 'ask', 0) or 0) if current_tick else 0
        
        # Current price (bid for LONG, ask for SHORT)
        current_price = bid if position.direction == Direction.LONG else ask
        
        # Validation checks
        checks = []
        
        # Check 1: SL is different from current SL
        sl_delta_pips = abs(proposed_sl - current_sl) / pip_val
        if sl_delta_pips < 0.5:
            checks.append(("No significant change", False))
        else:
            checks.append((f"Significant change: {sl_delta_pips:.1f} pips", True))
        
        # Check 2: SL is in the right direction
        if position.direction == Direction.LONG:
            # For LONG: SL should be below current price
            if proposed_sl >= current_price:
                checks.append(("SL above current price (invalid for LONG)", False))
            else:
                checks.append(("SL below current price (valid for LONG)", True))
        else:
            # For SHORT: SL should be above current price
            if proposed_sl <= current_price:
                checks.append(("SL below current price (invalid for SHORT)", False))
            else:
                checks.append(("SL above current price (valid for SHORT)", True))
        
        # Check 3: Distance from current price respects min distance
        min_distance_pips = 3.0
        distance_from_price_pips = abs(proposed_sl - current_price) / pip_val
        if distance_from_price_pips < min_distance_pips:
            checks.append((f"Too close to current price ({distance_from_price_pips:.1f} < {min_distance_pips} pips)", False))
        else:
            checks.append((f"Adequate distance from price: {distance_from_price_pips:.1f} pips", True))
        
        # Check 4: Respects broker trade_stops_level
        if trade_stops_level > 0:
            trade_stops_pips = trade_stops_level / (pip_val * 10000) if pip_val > 0 else 0
            distance_pips = abs(proposed_sl - current_price) / pip_val
            if distance_pips < trade_stops_pips:
                checks.append((f"Violates trade_stops_level ({distance_pips:.1f} < {trade_stops_pips:.1f} pips)", False))
            else:
                checks.append((f"Respects trade_stops_level ({distance_pips:.1f} >= {trade_stops_pips:.1f})", True))
        
        # Check 5: Outside spread
        if position.direction == Direction.LONG:
            # For LONG, SL should be below bid (away from market)
            if proposed_sl >= bid:
                checks.append((f"SL inside spread (>= bid {bid:.5f})", False))
            else:
                checks.append((f"SL outside spread (< bid {bid:.5f})", True))
        else:
            # For SHORT, SL should be above ask (away from market)
            if proposed_sl <= ask:
                checks.append((f"SL inside spread (<= ask {ask:.5f})", False))
            else:
                checks.append((f"SL outside spread (> ask {ask:.5f})", True))
        
        # Determine overall status
        all_passed = all(passed for _, passed in checks)
        
        if all_passed:
            status = "PASS"
            reason = " | ".join([desc for desc, _ in checks if _])
        else:
            status = "FAIL"
            failures = [desc for desc, passed in checks if not passed]
            reason = " | ".join(failures)
        
        return status, reason
    
    async def check_single_position(
        self,
        position: Position,
        atr: float = 0.005,
    ) -> DiagnosticResult:
        """
        Run diagnostic checks on a single position.
        
        Args:
            position: Position object to audit
            atr: Average True Range (defaults to 0.005)
            
        Returns:
            DiagnosticResult with audit findings
        """
        pos_id = str(position.position_id)
        pip_val = self._get_pip_value(position.symbol)
        
        # Get position state from profit protection module
        state = self.ppm.position_states.get(pos_id)
        if not state:
            return DiagnosticResult(
                position_id=position.position_id,
                symbol=position.symbol,
                direction=position.direction.name,
                status="WARNING",
                bars_since_entry=0,
                current_sl=position.stop_loss,
                proposed_sl=None,
                atr=atr,
                spread_pips=0.0,
                constraints_check="NOT_TRACKED",
                reason="Position not in tracking state (new or not managed)",
                marked_for_auto_rotation=False,
                details={},
            )
        
        # Fetch current market data
        symbol_info = await self._get_symbol_info(position.symbol)
        current_tick = await self._get_current_tick(position.symbol)
        
        if not current_tick:
            return DiagnosticResult(
                position_id=position.position_id,
                symbol=position.symbol,
                direction=position.direction.name,
                status="ERROR",
                bars_since_entry=state.get('bars_since_entry', 0),
                current_sl=position.stop_loss,
                proposed_sl=None,
                atr=atr,
                spread_pips=0.0,
                constraints_check="FAILED",
                reason="Failed to fetch current tick data",
                marked_for_auto_rotation=state.get('marked_for_auto_rotation', False),
                details={"error": "tick_fetch_failed"},
            )
        
        # Calculate metrics
        bid = float(current_tick.bid)
        ask = float(current_tick.ask)
        spread_pips = self._calculate_spread_pips(position.symbol, bid, ask)
        
        # Calculate current R
        entry_price = position.entry_price
        current_price = bid if position.direction == Direction.LONG else ask
        risk_price = state.get('initial_risk_price', 0.0)
        
        if risk_price > 0:
            if position.direction == Direction.LONG:
                profit_price = current_price - entry_price
            else:
                profit_price = entry_price - current_price
            current_r = profit_price / risk_price
        else:
            current_r = 0.0
        
        # Get proposed SL from Layer 3
        proposed_sl = await self._get_proposed_sl(position, state, current_r, atr)
        
        # Validate proposed SL
        constraints_status, constraint_reason = self._validate_proposed_sl(
            position=position,
            current_sl=position.stop_loss,
            proposed_sl=proposed_sl,
            spread_pips=spread_pips,
            symbol_info=symbol_info,
            current_tick=current_tick,
        )
        
        # Check for auto-rotation marking
        marked_for_rotation = state.get('marked_for_auto_rotation', False)
        
        # Determine overall status
        if constraints_status == "PASS":
            overall_status = "PASS"
        elif constraints_status == "FAIL":
            overall_status = "FAIL"
        else:
            overall_status = constraints_status
        
        return DiagnosticResult(
            position_id=position.position_id,
            symbol=position.symbol,
            direction=position.direction.name,
            status=overall_status,
            bars_since_entry=state.get('bars_since_entry', 0),
            current_sl=position.stop_loss,
            proposed_sl=proposed_sl,
            atr=atr,
            spread_pips=spread_pips,
            constraints_check=constraints_status,
            reason=constraint_reason,
            marked_for_auto_rotation=marked_for_rotation,
            details={
                "entry_price": entry_price,
                "current_price": current_price,
                "current_r": current_r,
                "peak_profit_price": state.get('peak_profit_price', 0.0),
                "market_regime": state.get('market_regime'),
                "volatility_regime": state.get('volatility_regime'),
                "time_decay_sl_applied": state.get('time_decay_sl_applied', False),
                "profit_shaving_done": state.get('profit_shaving_done', False),
                "rsi_exhaustion_done": state.get('rsi_exhaustion_done', False),
                "bid": bid,
                "ask": ask,
            },
        )
    
    async def run_full_audit(
        self,
        open_positions: List[Position],
        atr_map: Optional[Dict[str, float]] = None,
    ) -> List[DiagnosticResult]:
        """
        Run diagnostic audit on all open positions.
        
        Args:
            open_positions: List of all currently open positions
            atr_map: Optional dict mapping symbol to ATR value
            
        Returns:
            List of DiagnosticResult objects
        """
        results = []
        
        for position in open_positions:
            atr = atr_map.get(position.symbol, 0.005) if atr_map else 0.005
            result = await self.check_single_position(position, atr=atr)
            results.append(result)
        
        return results
    
    def print_audit_report(self, results: List[DiagnosticResult]) -> None:
        """
        Print formatted diagnostic report to console and logger.
        
        Args:
            results: List of DiagnosticResult objects from audit
        """
        timestamp = self.audit_timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")
        
        logger.info("")
        logger.info("=" * 120)
        logger.info(f"[LAYER3_DIAGNOSTIC_AUDIT] Time: {timestamp}")
        logger.info(f"[LAYER3_DIAGNOSTIC_AUDIT] Shadow Mode: {self.ppm.TIME_DECAY_SHADOW_MODE}")
        logger.info(f"[LAYER3_DIAGNOSTIC_AUDIT] Positions Audited: {len(results)}")
        logger.info("=" * 120)
        
        # Summary stats
        pass_count = sum(1 for r in results if r.status == "PASS")
        fail_count = sum(1 for r in results if r.status == "FAIL")
        warn_count = sum(1 for r in results if r.status == "WARNING")
        info_count = sum(1 for r in results if r.status == "INFO")
        error_count = sum(1 for r in results if r.status == "ERROR")
        rotation_count = sum(1 for r in results if r.marked_for_auto_rotation)
        
        logger.info(f"[LAYER3_AUDIT_SUMMARY] PASS={pass_count} | FAIL={fail_count} | WARNING={warn_count} | INFO={info_count} | ERROR={error_count} | PENDING_ROTATION={rotation_count}")
        logger.info("=" * 120)
        
        # Individual position reports
        for result in results:
            status_tag = f"[DIAGNOSTIC_{result.status}]"
            
            logger.info(f"{status_tag} {result.symbol} #{result.position_id} ({result.direction})")
            logger.info(f"  Bars Since Entry: {result.bars_since_entry}")
            logger.info(f"  Current SL: {result.current_sl:.5f}")
            logger.info(f"  Proposed SL: {result.proposed_sl if result.proposed_sl else 'None'}")
            if result.proposed_sl:
                logger.info(f"    → Delta: {abs(result.proposed_sl - result.current_sl) / self._get_pip_value(result.symbol):.1f} pips")
            logger.info(f"  ATR: {result.atr:.6f} | Spread: {result.spread_pips:.1f} pips")
            logger.info(f"  Constraint Check: {result.constraints_check}")
            logger.info(f"  Reason: {result.reason}")
            
            if result.marked_for_auto_rotation:
                logger.info(f"  ⚠️  [ROTATION_PENDING] Position marked for auto-rotation")
            
            # Additional details
            if result.details:
                logger.debug(f"  Details: {result.details}")
            
            logger.info("")
        
        # Final summary
        logger.info("=" * 120)
        logger.info(f"[LAYER3_AUDIT_COMPLETE] Report timestamp: {timestamp}")
        logger.info("=" * 120)
        logger.info("")


async def run_diagnostic_audit(
    profit_protection_module: ProfitProtectionModule,
    broker,
    atr_map: Optional[Dict[str, float]] = None,
) -> List[DiagnosticResult]:
    """
    Convenience function to run Layer 3 diagnostic audit.
    
    Can be called from heartbeat pulse or manual trigger.
    
    Args:
        profit_protection_module: ProfitProtectionModule instance
        broker: Broker interface to fetch positions
        atr_map: Optional dict mapping symbol -> ATR value
        
    Returns:
        List of DiagnosticResult objects
        
    Example:
        # In your main loop or heartbeat
        results = await run_diagnostic_audit(ppm, broker)
        # Results are automatically logged
    """
    auditor = Layer3DiagnosticAudit(profit_protection_module)
    
    # Fetch all open positions
    try:
        open_positions = await broker.get_open_positions()
    except Exception as e:
        logger.error(f"[DIAGNOSTIC_ERROR] Failed to fetch open positions: {e}")
        return []
    
    # Run audit
    results = await auditor.run_full_audit(open_positions, atr_map=atr_map)
    
    # Print report
    auditor.print_audit_report(results)
    
    return results
