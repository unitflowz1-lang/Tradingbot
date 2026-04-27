#!/usr/bin/env python3
"""Quick test of Finnhub API connectivity"""
import asyncio
import os
import sys

from dotenv import load_dotenv
load_dotenv()

from src.analysis.finnhub_macro_manager import FinnhubMacroManager

async def test_finnhub():
    api_key = os.environ.get("FINNHUB_API_KEY")
    print(f"[TEST] API Key present: {'✅' if api_key else '❌'}")
    print(f"[TEST] API Key length: {len(api_key or '')}")
    
    manager = FinnhubMacroManager(
        api_key=api_key,
        symbols=["EUR/USD", "GBP/USD", "USD/JPY"],
    )
    
    print("[TEST] Testing API connectivity...")
    ok = await manager._test_api_connectivity()
    
    if ok:
        print("[✅ SUCCESS] Finnhub API is reachable and authenticated!")
        print("[NEXT] You can now integrate FinnhubMacroManager into main.py")
        return 0
    else:
        print("[❌ FAILED] Could not connect to Finnhub API")
        print("[CHECK] - Is your internet connection working?")
        print("[CHECK] - Is the API key valid?")
        print("[CHECK] - Is Finnhub service online?")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(test_finnhub())
    sys.exit(exit_code)
