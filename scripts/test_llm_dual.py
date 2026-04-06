"""
Hybrid Dual-Model LLM Governance Test
Tests:
  1. OLLAMA_MODEL_FAST (nemotron-3-nano:4b) - Normal trade
  2. OLLAMA_MODEL_HEAVY (nemotron-3-nano:4b)  - Forced execution escalation
  3. Escalation Audit - Risk detection by FAST causing HEAVY audit
"""
import sys
import json
import time

# Allow running from project root
sys.path.insert(0, r"c:\Users\macki\Desktop\v4.0-core TradingBot")

from src.llm_governance import (
    LLMGovernanceClient,
    GovernanceInput,
    OLLAMA_MODEL_FAST,
    OLLAMA_MODEL_HEAVY,
    LLM_TIMEOUT_SECONDS,
)

def run_test_case(name, gov_input, signal_forced=False):
    print(f"\n{'-'*60}")
    print(f"CASE: {name}")
    print(f"FORCED: {signal_forced} | ML_CONF: {gov_input.ml_confidence}")
    print(f"{'-'*60}")
    
    client = LLMGovernanceClient()
    t_start = time.perf_counter()
    decision = client.evaluate(gov_input, cycle=1, signal_forced=signal_forced)
    latency = (time.perf_counter() - t_start) * 1000

    print(f"    Decision  : {decision.decision.upper()}")
    print(f"    Confidence: {decision.confidence}")
    print(f"    Reason    : {decision.reason}")
    print(f"    RiskFlag  : {decision.risk_flag}")
    print(f"    Bypassed  : {decision.bypassed}")
    print(f"    Latency   : {latency:.0f}ms")
    
    if decision.bypassed:
        print(f"    ❌ BYPASSED: {decision.bypass_reason}")
    else:
        print(f"    ✅ SUCCESS")

if __name__ == "__main__":
    print("=" * 60)
    print("HYBRID LLM GOVERNANCE — DUAL MODEL TEST")
    print(f"FAST Model : {OLLAMA_MODEL_FAST}")
    print(f"HEAVY Model: {OLLAMA_MODEL_HEAVY}")
    print("=" * 60)

    # 1. Standard Trade (FAST)
    inp_standard = GovernanceInput(
        symbol="EUR/USD", regime="TRENDING", rsi=45.0, adx=30.0, atr=0.0001,
        rr_ratio=3.0, ml_confidence=0.7, volatility_pct=0.08,
        forced_execution=False, position_size=0.1, expectancy_multiplier=3.0
    )
    run_test_case("Standard Signal (Fast Path)", inp_standard, signal_forced=False)

    # 2. Forced Execution (HEAVY)
    inp_forced = GovernanceInput(
        symbol="GBP/USD", regime="TRENDING", rsi=50.0, adx=35.0, atr=0.0002,
        rr_ratio=3.5, ml_confidence=0.9, volatility_pct=0.1,
        forced_execution=True, position_size=0.2, expectancy_multiplier=3.5
    )
    run_test_case("Forced Execution (Heavy Path)", inp_forced, signal_forced=True)

    # 3. Risk Escalation (FAST -> HEAVY)
    # Give it an extreme anomaly to trigger FAST rejection
    inp_risky = GovernanceInput(
        symbol="USD/JPY", regime="RANGING", rsi=95.0, adx=10.0, atr=0.05,
        rr_ratio=1.2, ml_confidence=0.4, volatility_pct=0.5,
        forced_execution=False, position_size=0.1, expectancy_multiplier=1.2
    )
    run_test_case("Risk Anomaly (Escalation Path)", inp_risky, signal_forced=False)
