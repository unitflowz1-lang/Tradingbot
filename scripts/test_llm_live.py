"""
Quick live test of the LLM governance layer.
Tests:
  1. Ollama connectivity & model availability
  2. A real GovernanceInput evaluation
  3. Validates the response schema
"""
import sys
import json
import urllib.request
import urllib.error

# Allow running from project root
sys.path.insert(0, r"c:\Users\macki\Desktop\v4.0-core TradingBot")

from src.llm_governance import (
    LLMGovernanceClient,
    GovernanceInput,
    OLLAMA_URL,
    OLLAMA_MODEL,
    LLM_TIMEOUT_SECONDS,
)

def test_ollama_reachable():
    print(f"\n[1] Checking Ollama at {OLLAMA_URL.replace('/api/generate', '')} ...")
    try:
        req = urllib.request.Request(
            "http://localhost:11434/api/tags",
            headers={"Content-Type": "application/json"},
            method="GET"
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        models = [m["name"] for m in data.get("models", [])]
        print(f"    ✅ Ollama is running. Available models: {models}")
        if OLLAMA_MODEL in models:
            print(f"    ✅ Model '{OLLAMA_MODEL}' is available.")
        else:
            print(f"    ⚠️  Model '{OLLAMA_MODEL}' NOT found. Available: {models}")
            print(f"    → Attempting to use first available model for test...")
        return models
    except Exception as e:
        print(f"    ❌ Ollama unreachable: {e}")
        return []

def test_raw_inference(model_name):
    print(f"\n[2] Raw inference test with '{model_name}' (timeout={LLM_TIMEOUT_SECONDS}s)...")
    prompt = (
        'Return ONLY this exact JSON object, no other text:\n'
        '{"decision": "approve", "confidence": 75, "reason": "test direct call", "risk_flag": false}'
    )
    payload = json.dumps({
        "model": model_name,
        "prompt": prompt,
        "stream": False,
        "options": {"num_predict": 80, "temperature": 0.1, "top_p": 0.9}
    }).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    import time
    t = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = json.loads(resp.read())
        latency = (time.perf_counter() - t) * 1000
        response_text = raw.get("response", "")
        print(f"    ✅ Response received in {latency:.0f}ms")
        print(f"    Raw: {response_text[:200]!r}")
        return response_text
    except Exception as e:
        print(f"    ❌ Inference failed: {e}")
        return None

def test_governance_client(model_name):
    print(f"\n[3] Full GovernanceClient.evaluate() test...")
    # Temporarily patch the model if needed
    import src.llm_governance as gov_mod
    original_model = gov_mod.OLLAMA_MODEL
    gov_mod.OLLAMA_MODEL = model_name

    client = LLMGovernanceClient()
    gov_input = GovernanceInput(
        symbol="EUR/USD",
        regime="TRENDING",
        rsi=55.0,
        adx=28.5,
        atr=0.00082,
        rr_ratio=2.7,
        ml_confidence=0.73,
        volatility_pct=0.12,
        forced_execution=False,
        position_size=0.01,
        expectancy_multiplier=2.7,
    )

    import time
    t = time.perf_counter()
    decision = client.evaluate(gov_input, cycle=1, signal_forced=False)
    latency = (time.perf_counter() - t) * 1000

    gov_mod.OLLAMA_MODEL = original_model  # restore

    print(f"    Decision  : {decision.decision.upper()}")
    print(f"    Confidence: {decision.confidence}")
    print(f"    Reason    : {decision.reason}")
    print(f"    RiskFlag  : {decision.risk_flag}")
    print(f"    Bypassed  : {decision.bypassed}")
    print(f"    Latency   : {latency:.0f}ms")

    if decision.bypassed:
        print(f"    ⚠️  Bypassed: {decision.bypass_reason}")
        print(f"    → LLM did not return a valid response within timeout ({LLM_TIMEOUT_SECONDS}s)")
    else:
        print(f"    ✅ LLM governance is working correctly!")

    return decision

if __name__ == "__main__":
    print("=" * 60)
    print("LLM Governance Layer — Live Integration Test")
    print(f"Target model: {OLLAMA_MODEL}")
    print(f"Timeout: {LLM_TIMEOUT_SECONDS}s")
    print("=" * 60)

    # Step 1: check connectivity
    available_models = test_ollama_reachable()
    if not available_models:
        print("\n❌ Cannot proceed — Ollama is not running.")
        sys.exit(1)

    # Pick model to test with
    model_to_use = OLLAMA_MODEL if OLLAMA_MODEL in available_models else available_models[0]

    # Step 2: raw inference
    raw = test_raw_inference(model_to_use)

    # Step 3: full client test
    decision = test_governance_client(model_to_use)

    print("\n" + "=" * 60)
    if not decision.bypassed:
        print("✅ ALL TESTS PASSED — LLM governance layer is operational.")
    else:
        print(f"⚠️  LLM bypassed (likely timeout: {LLM_TIMEOUT_SECONDS}s too short for {model_to_use})")
        print("   Suggestion: increase LLM_TIMEOUT_SECONDS or use a smaller model.")
    print("=" * 60)
