#!/usr/bin/env python3
"""Quick test to verify backtest runs without errors"""
import asyncio
import sys
import logging

# Minimal logging
logging.basicConfig(level=logging.CRITICAL)

async def test_backtest():
    try:
        from run_backtest import run_backtest
        print("✓ Import successful")
        
        # Run backtest
        await run_backtest()
        print("✓ Backtest completed successfully!")
        return 0
    except Exception as e:
        print(f"✗ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(test_backtest())
    sys.exit(exit_code)
