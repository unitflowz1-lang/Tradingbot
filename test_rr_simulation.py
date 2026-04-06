
import logging
import asyncio
from datetime import datetime, timezone
from src.risk.position_sizer import AdaptivePositionSizer, PositionSizingConfig
from src.models import TradingSignal, Direction

# Setup logging to capture the specific messages
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger("src.risk.position_sizer")
logger.setLevel(logging.INFO)

async def run_simulation():
    print("Starting RR Gatekeeping Simulation...")
    
    # Initialize Sizer
    config = PositionSizingConfig()
    sizer = AdaptivePositionSizer(config)
    
    # 1. Simulate Fail Scenario (EURUSD)
    # User requested: Entry=1.17000, SL=1.17200, TP=1.17100.
    # Note: 1.17100 is higher than Entry, which is invalid for Short TP.
    # We use 1.16900 (100 pts profit) instead to ensure signal valid but RR bad.
    print("\n[SIMULATION 1] Fail Scenario: EURUSD (RR < 1.5)")
    try:
        fail_signal = TradingSignal(
            symbol="EURUSD",
            direction=Direction.SHORT,
            entry_price=1.17000,
            stop_loss=1.17200,
            take_profit=1.16900,  # Adjusted to be valid for Short
            position_size=0.01,
            confidence=0.9,
            reasoning="Test Fail Scenario",
            timestamp=datetime.now(timezone.utc),
            rr_ratio=0.5
        )
        
        # Verify Risk/Reward calculation
        risk = abs(fail_signal.entry_price - fail_signal.stop_loss)
        reward = abs(fail_signal.take_profit - fail_signal.entry_price)
        print(f"Risk: {risk:.5f} | Reward: {reward:.5f} | RR: {reward/risk:.2f}")
        
        size_fail = sizer.calculate_position_size(fail_signal, account_balance=10000.0)
        print(f"Resulting Lot Size: {size_fail}")
        
        if size_fail == 0.0:
            print("✅ SUCCESS: Trade Rejected (Lot Size 0.0)")
            print("Expected Log: [RR_REJECTION] ...") 
        else:
            print(f"❌ FAILURE: Trade Accepted (Lot Size {size_fail})")

    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"ERROR: {e}")

    # 2. Simulate Pass Scenario (USDJPY)
    print("\n[SIMULATION 2] Pass Scenario: USDJPY (RR = 2.0)")
    try:
        pass_signal = TradingSignal(
            symbol="USDJPY",
            direction=Direction.LONG,
            entry_price=100.00,
            stop_loss=99.00,
            take_profit=102.00,
            position_size=0.01,
            confidence=0.9,
            reasoning="Test Pass Scenario",
            timestamp=datetime.now(timezone.utc),
            rr_ratio=2.0
        )
        
        risk = abs(pass_signal.entry_price - pass_signal.stop_loss)
        reward = abs(pass_signal.take_profit - pass_signal.entry_price)
        print(f"Risk: {risk:.5f} | Reward: {reward:.5f} | RR: {reward/risk:.2f}")
        
        size_pass = sizer.calculate_position_size(pass_signal, account_balance=10000.0)
        print(f"Resulting Lot Size: {size_pass}")
        
        if size_pass > 0.0:
            print(f"✅ SUCCESS: Trade Accepted (Lot Size {size_pass})")
        else:
            print("❌ FAILURE: Trade Rejected (Lot Size 0.0)")

    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == "__main__":
    asyncio.run(run_simulation())
