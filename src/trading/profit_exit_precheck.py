"""
ProfitExitPreCheck: Run profit protection FIRST in cycle before sync/data fetch.

PROBLEM: ProfitProtectionModule memory is wiped when sync_mt5_state() runs 
before profit management logic. Result: orders fail to take profit.

SOLUTION: Execute profit protection checks at the VERY START of the cycle, 
before any MT5 sync or data fetch operations. This ensures:
1. Profit targets are detected while memory intact
2. Trailing stops lock in gains
3. Breakeven protections work as designed
4. All exits execute before state is wiped

CRITICAL TIMING:
1. Increment cycle counter
2. *** RUN PROFIT EXIT PRE-CHECK *** (THIS MODULE)
3. Check for closed positions (PnL tracking)
4. Fetch market data (with DataCoordinator cache)
5. Smart sync (only if needed)
6. Analyze signals
7. Execute entries
"""

import logging
import asyncio
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class ProfitExitPreCheck:
    """
    Pre-cycle profit protection check that runs BEFORE sync and data fetch.
    
    Ensures profit protection module can execute exits with intact memory.
    """
    
    def __init__(self):
        """Initialize profit exit pre-checker."""
        self._check_count = 0
        self._exits_executed = 0
        self._profit_protected = 0.0
        
        logger.info(
            "[PROFIT_PRECHECK_INIT] Profit protection pre-checks enabled. "
            "Will run BEFORE MT5 sync and data fetch each cycle."
        )
    
    async def execute_precheck(
        self,
        cycle_count: int,
        portfolio: Any,
        profit_mgmt: Any,
        position_manager: Any,
        broker: Any,
        strategies: Dict[str, Any],
        data_coordinator: Optional[Any] = None,
    ) -> Tuple[int, float, List[str]]:
        """
        Execute profit protection pre-checks on all open positions.
        
        CRITICAL: Call this BEFORE sync_mt5_state() and data_fetch operations.
        
        Args:
            cycle_count: Current cycle number
            portfolio: Current portfolio object
            profit_mgmt: ProfitProtectionModule instance
            position_manager: PositionManager instance
            broker: Broker interface
            strategies: Dictionary of strategies by symbol
            data_coordinator: Optional DataCoordinator for price data
        
        Returns:
            (exits_executed: int, total_profit_protected: float, exited_symbols: List[str])
        """
        self._check_count += 1
        exits_executed = 0
        total_protected = 0.0
        exited_symbols = []
        
        try:
            # Only run if profit_mgmt is available
            if profit_mgmt is None or not hasattr(profit_mgmt, "manage_position"):
                logger.debug("[PROFIT_PRECHECK] Skipped: profit_mgmt not available")
                return 0, 0.0, []
            
            # Get current positions
            positions = list(getattr(portfolio, "positions", []) or [])
            if not positions:
                logger.debug("[PROFIT_PRECHECK] No open positions to check")
                return 0, 0.0, []
            
            logger.info(
                "[PROFIT_PRECHECK_START] Cycle %d | Checking %d open position(s) for exits...",
                cycle_count,
                len(positions),
            )
            
            # Pre-check each position
            for position in list(positions):
                try:
                    symbol = str(getattr(position, "symbol", "UNKNOWN"))
                    pos_id = str(getattr(position, "position_id", "UNKNOWN"))
                    unrealized_pnl = float(getattr(position, "unrealized_pnl", 0.0) or 0.0)
                    current_price = float(getattr(position, "current_price", 0.0) or 0.0)
                    entry_price = float(getattr(position, "entry_price", 0.0) or 0.0)
                    direction = getattr(position, "direction", None)
                    
                    # Get latest price data for this position
                    try:
                        # Use cached data if DataCoordinator available
                        if data_coordinator:
                            historical_data = data_coordinator.get_latest(
                                symbol,
                                force_refresh=False,  # Use cache
                            )
                        else:
                            historical_data = await broker.get_historical_data(
                                symbol,
                                timeframe=16385,  # M1
                                count=50,
                            )
                        
                        latest_bar = historical_data[-1] if historical_data else None
                        atr = _calculate_atr_simple(historical_data) if historical_data else 0.0
                        
                    except Exception as data_err:
                        logger.warning(
                            "[PROFIT_PRECHECK] Failed to fetch data for %s: %s",
                            symbol,
                            data_err,
                        )
                        latest_bar = None
                        atr = 0.0
                    
                    # Get strategy context if available
                    strategy = strategies.get(symbol)
                    position_ctx = {}
                    if strategy:
                        position_ctx = {
                            "rsi": getattr(strategy, "rsi", None),
                            "adx": getattr(strategy, "adx", None),
                            "mlconfidence": getattr(strategy, "ml_confidence", 0.0),
                        }
                    
                    # Run profit management on this position
                    logger.debug(
                        "[PROFIT_PRECHECK_POS] %s #%s | Entry: %.5f | Current: %.5f | PnL: $%.2f",
                        symbol,
                        pos_id,
                        entry_price,
                        current_price,
                        unrealized_pnl,
                    )
                    
                    action_taken = await profit_mgmt.manage_position(
                        position,
                        latest_bar,
                        atr,
                        regime="UNKNOWN",  # Use unknown, strategy will provide context
                        volatility_regime="UNKNOWN",
                        rsi=position_ctx.get("rsi"),
                        ml_confidence=position_ctx.get("ml_confidence", 0.0),
                    )
                    
                    if action_taken:
                        exits_executed += 1
                        total_protected += abs(unrealized_pnl)
                        exited_symbols.append(symbol)
                        logger.critical(
                            "[PROFIT_PRECHECK_EXIT] %s #%s | Action taken during pre-check | PnL: $%.2f",
                            symbol,
                            pos_id,
                            unrealized_pnl,
                        )
                    else:
                        logger.debug(
                            "[PROFIT_PRECHECK_MANAGED] %s #%s | Position managed (no exit) | PnL: $%.2f",
                            symbol,
                            pos_id,
                            unrealized_pnl,
                        )
                
                except Exception as pos_err:
                    logger.error(
                        "[PROFIT_PRECHECK_ERROR] Failed to check position: %s",
                        pos_err,
                    )
                    continue
            
            self._exits_executed += exits_executed
            self._profit_protected += total_protected
            
            if exits_executed > 0:
                logger.critical(
                    "[PROFIT_PRECHECK_SUMMARY] Cycle %d | %d exit(s) executed | Total protected: $%.2f",
                    cycle_count,
                    exits_executed,
                    total_protected,
                )
            
            return exits_executed, total_protected, exited_symbols
            
        except Exception as e:
            logger.error("[PROFIT_PRECHECK] Unhandled error: %s", e)
            return 0, 0.0, []
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about profit pre-checks."""
        return {
            "total_checks": self._check_count,
            "total_exits_executed": self._exits_executed,
            "total_profit_protected": self._profit_protected,
            "avg_protected_per_exit": (
                self._profit_protected / max(self._exits_executed, 1)
            ),
        }


def _calculate_atr_simple(historical_data: Optional[List], period: int = 14) -> float:
    """Helper: Calculate simple ATR from price data."""
    if not historical_data or len(historical_data) < period:
        return 0.0
    
    try:
        trs = []
        for i in range(1, len(historical_data)):
            bar = historical_data[i]
            prev_bar = historical_data[i - 1]
            
            high = float(getattr(bar, "high", 0.0) or 0.0)
            low = float(getattr(bar, "low", 0.0) or 0.0)
            prev_close = float(getattr(prev_bar, "close", 0.0) or 0.0)
            
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close),
            )
            trs.append(tr)
        
        if trs:
            return sum(trs[-period:]) / len(trs[-period:])
        return 0.0
    except Exception:
        return 0.0


def get_profit_exit_precheck() -> ProfitExitPreCheck:
    """Get profit exit pre-checker instance."""
    return ProfitExitPreCheck()


# ===== INTEGRATION PATTERN =====
# In main.py cycle, BEFORE sync:
#
# # CYCLE START
# cycle_count += 1
#
# # STEP 1: RUN PROFIT PROTECTION PRE-CHECK (FIRST!)
# profit_precheck = get_profit_exit_precheck()
# exits_executed, protected, exited_symbols = await profit_precheck.execute_precheck(
#     cycle_count=cycle_count,
#     portfolio=portfolio,
#     profit_mgmt=profit_mgmt,
#     position_manager=position_manager,
#     broker=broker,
#     strategies=strategies,
#     data_coordinator=data_coordinator,  # Optional
# )
#
# # STEP 2: THEN do MT5 sync (if needed)
# smart_sync = get_smart_sync_manager()
# should_sync, reason = smart_sync.should_sync(portfolio.positions)
# if should_sync:
#     await position_manager.sync_mt5_state(persist=True)
#     smart_sync.mark_synced(portfolio.positions, reason)
#
# # STEP 3: THEN fetch market data
# # ... rest of cycle
#
# Expected: Profit targets locked in BEFORE sync wipes memory
