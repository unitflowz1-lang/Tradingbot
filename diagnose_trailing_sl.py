"""
Diagnostic Test - Trailing Stop Loss Calculation Details
==========================================================

This test dives into the _calculate_new_sl method to identify exactly 
where the SL calculation is failing.
"""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.trading.dynamic_trailing_sl_manager import (
    DynamicTrailingSLManager,
    TrailingConfig,
)

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger(__name__)


class MockBroker:
    """Mock broker."""
    async def modify_order(self, order_id: str, sl: float, tp=None) -> bool:
        logger.info(f"[MOCK_BROKER] modify_order called: ticket={order_id}, sl={sl}")
        return True


async def diagnose_sl_calculation():
    """Diagnose SL calculation step-by-step."""
    logger.info("\n" + "="*80)
    logger.info("TRAILING STOP LOSS - DIAGNOSTIC TEST")
    logger.info("="*80)
    
    broker = MockBroker()
    manager = DynamicTrailingSLManager(
        broker,
        TrailingConfig(
            buffer_pips=5.0,
            min_time_between_mods_seconds=0.5,  # Very short for testing
            min_pip_movement=0.0005,
            enable_profit_lock=True,
            profit_lock_threshold_pips=20.0,
        )
    )
    
    # Setup LONG position
    logger.info("\n[STEP 1] Track a LONG position")
    manager.track_position(
        ticket="DIAG_LONG",
        symbol="EUR/USD",
        side="LONG",
        entry_price=1.0850,
        current_sl=1.0800,
    )
    state = manager._positions["DIAG_LONG"]
    logger.info(f"   Entry price:     {state.entry_price}")
    logger.info(f"   Current SL:      {state.current_sl}")
    logger.info(f"   Highest price:   {state.highest_price_long}")
    logger.info(f"   Last mod price:  {state.last_sl_modification_price}")
    
    # First price update
    logger.info("\n[STEP 2] First price update: 1.0875 (profit +25 pips)")
    logger.info("   Detailed trace of _calculate_new_sl_long():")
    
    # Call it manually to see what happens
    current_price = 1.0875
    
    logger.info(f"     → current_price: {current_price}")
    logger.info(f"     → highest_price_long before: {state.highest_price_long}")
    
    # This happens inside _calculate_new_sl_long
    if current_price > state.highest_price_long:
        state.highest_price_long = current_price
    
    logger.info(f"     → highest_price_long after: {state.highest_price_long}")
    
    # Calculate pip value
    pip_value = manager._get_pip_value("EUR/USD")
    logger.info(f"     → pip_value: {pip_value}")
    
    buffer = manager.config.buffer_pips * pip_value
    logger.info(f"     → buffer_pips: {manager.config.buffer_pips}")
    logger.info(f"     → buffer amount: {buffer}")
    
    trailing_sl = state.highest_price_long - buffer
    logger.info(f"     → trailing_sl = {state.highest_price_long} - {buffer} = {trailing_sl}")
    
    logger.info(f"     → current_sl: {state.current_sl}")
    logger.info(f"     → trailing_sl > current_sl? {trailing_sl} > {state.current_sl} = {trailing_sl > state.current_sl}")
    
    # Check profit
    profit_pips = (current_price - state.entry_price) / pip_value
    logger.info(f"     → profit_pips: {profit_pips}")
    logger.info(f"     → profit_lock_threshold: {manager.config.profit_lock_threshold_pips}")
    
    # Now actually call update_trailing_sl
    logger.info("\n[STEP 3] Call update_trailing_sl()")
    modified, reason = await manager.update_trailing_sl("DIAG_LONG", current_price)
    
    logger.info(f"   Result: modified={modified}, reason='{reason}'")
    logger.info(f"   New current_sl: {state.current_sl}")
    logger.info(f"   Total modifications: {state.total_modifications}")
    
    # Second update
    logger.info("\n[STEP 4] Second price update: 1.0880 (profit +30 pips)")
    await asyncio.sleep(1)  # Wait for throttle
    
    modified2, reason2 = await manager.update_trailing_sl("DIAG_LONG", 1.0880)
    logger.info(f"   Result: modified={modified2}, reason='{reason2}'")
    logger.info(f"   New current_sl: {state.current_sl}")
    
    # Statistics
    logger.info("\n[STEP 5] Final Statistics")
    logger.info(f"   Entry price:       {state.entry_price}")
    logger.info(f"   Highest price hit: {state.highest_price_long}")
    logger.info(f"   Current SL:        {state.current_sl}")
    logger.info(f"   Total mods:        {state.total_modifications}")
    logger.info(f"   SL moves:          {state.times_sl_moved}")
    logger.info(f"   Modification history: {len(state.modification_history)} entries")
    
    for i, mod in enumerate(state.modification_history):
        logger.info(f"     {i+1}. Price={mod['price']:.5f}, SL={mod['new_sl']:.5f}, Profit={mod['profit_pips']:.1f}pips")
    
    # Summary
    logger.info("\n" + "="*80)
    if modified:
        logger.info("✅ DIAGNOSIS: LONG position SL follows price correctly")
    else:
        logger.info("❌ DIAGNOSIS: LONG position SL NOT following price - Check logs above")
    logger.info("="*80)


if __name__ == "__main__":
    asyncio.run(diagnose_sl_calculation())
