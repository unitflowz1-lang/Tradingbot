"""
LLM Governance Layer — Nemotron-3-Nano:4B Advisory Module  (Stability & Drift Hardened)
==============================================================================
Uses Ollama (http://localhost:11434/api/generate) with model "nemotron-3-nano:4b"
as a NON-AUTHORITATIVE advisory governance layer.

Contract:
  - LLM is called ONLY AFTER signal generation, SL/TP, R:R validation,
    ML confidence scoring, and regime classification are complete.
  - LLM advisory powers:
      ✅ May demote forced_execution to standard
      ✅ May flag risk anomalies
      ❌ May NOT increase position size beyond computed limits
      ❌ May NOT alter SL/TP values
  - On ANY failure (timeout, malformed JSON, schema violation) → bypass
    gracefully; FailOpenMonitor tracks accumulation and auto-disables.
  - Feature flag: ENABLE_LLM_GOVERNANCE = True/False for instant rollback.
  - Auto-disable: triggered by FailOpenMonitor when bypass count > 10 in 50 calls.

JSON Response Contract:
  {
    "decision": "approve" | "demote" | "reject",
    "confidence": 0-100,
    "reason": "...",
    "risk_flag": true | false
  }

Drift Monitoring (rolling 200-call window):
  - Approval rate > 90% for 100 consecutive cycles  → CRITICAL flag
  - Reject  rate > 40% in rolling 200-call window   → CRITICAL flag
  - Confidence inflation: current avg > prior avg + 20% → CRITICAL flag
  - Decision skew: > 85% in single category over 150 calls → CRITICAL flag

SHA256 Input Hashing:
  - Canonical JSON hash logged before every LLM call
  - Post-call hash re-validated to detect async mutation

FailOpenMonitor (rolling 50-call window):
  - Bypass count > 10 → auto-disable via ENABLE_LLM_GOVERNANCE = False
  - Emits CRITICAL: LLM_GOVERNANCE_AUTO_DISABLED_FAILOPEN_THRESHOLD

Inference parameters (tightly constrained):
  num_predict=150, temperature=0.2, top_p=0.9

All interactions logged at INFO; rejections/anomalies at CRITICAL with
[LLM_GOVERNANCE_AUDIT] tag including latency and decision output.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import socket
import time
import threading
import urllib.request
import urllib.error
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional, Tuple
from src.analysis.ollama_runtime_gate import OLLAMA_REQUEST_LOCK
from src.analysis.local_llm_fast_path import (
    activate_local_llm_fast_path,
    clear_local_llm_fast_path,
)
from src.runtime.emergency_stop import trigger_emergency_stop

# ─────────────────────────────────────────────────────────────────────────────
# Feature Flag  (module-level so FailOpenMonitor can mutate it at runtime)
# ─────────────────────────────────────────────────────────────────────────────
ENABLE_LLM_GOVERNANCE: bool = True

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────
OLLAMA_BASE_URL: str           = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
OLLAMA_URL: str                = os.environ.get("OLLAMA_URL", f"{OLLAMA_BASE_URL}/api/generate")
OLLAMA_TAGS_URL: str           = os.environ.get("OLLAMA_TAGS_URL", f"{OLLAMA_BASE_URL}/api/tags")
OLLAMA_MODEL_FAST: str         = os.environ.get("OLLAMA_MODEL_FAST", "phi3:mini")
OLLAMA_MODEL_HEAVY: str        = os.environ.get("OLLAMA_MODEL_HEAVY", "phi3:mini")
# Local Ollama timeout: allow qwen3.5:0.8b enough time to warm up and respond before fail-open bypass.
# Increased from 15s to 60s to allow model warm-up time on first load
LLM_TIMEOUT_SECONDS: float     = float(os.environ.get("OLLAMA_FAST_TIMEOUT_SECONDS", "60.0"))
LLM_HEAVY_TIMEOUT_SECONDS: float = float(os.environ.get("OLLAMA_HEAVY_TIMEOUT_SECONDS", "60.0"))
LLM_GOVERNANCE_SOCKET_TIMEOUT: float = float(os.environ.get("LLM_GOVERNANCE_SOCKET_TIMEOUT", "30.0"))
# System Busy Detection: If latency exceeds 10 seconds repeatedly, auto-switch to lighter model
LLM_LATENCY_THRESHOLD_MS: float = 10000.0  # 10 seconds = system busy threshold
LLM_LATENCY_CONSECUTIVE_HITS: int = 3      # 3 consecutive slow calls = auto-downgrade to 0.5b model
LLM_LATENCY_RECOVERY_CYCLES: int = 50      # After downgrade, recovery after 50 normal cycles
LLM_MODEL_LIGHT: str           = os.environ.get("OLLAMA_MODEL_LIGHT", "qwen2.5:0.5b")  # Fallback when system busy
LLM_MAX_TOKENS: int            = 1024   # Nemotron optimized for concise reasoning (reduced from 2048)
LLM_TEMPERATURE: float         = 0.0    # ABSOLUTE ZERO - no randomness, force deterministic response
LLM_TOP_P: float               = 0.85   # Reduced nucleus window for deterministic output (from 0.9)
OLLAMA_RETRY_ATTEMPTS: int     = int(os.environ.get("OLLAMA_RETRY_ATTEMPTS", "1"))
OLLAMA_RETRY_DELAY_SECONDS: float = float(os.environ.get("OLLAMA_RETRY_DELAY_SECONDS", "1.0"))

LLM_EVALUATION_CYCLE_LEN: int  = 50    # Rolling tracker window (outcomes)

# Drift thresholds
DRIFT_WINDOW_CALLS: int        = 200   # Primary rolling window for all drift metrics
DRIFT_SKEW_WINDOW: int         = 150   # Skew detection window
DRIFT_APPROVE_RATE_THRESHOLD   = 0.90  # > 90% approval rate over 100 consecutive cycles
DRIFT_APPROVE_CONSECUTIVE      = 100   # Number of consecutive cycles for approval-rate alert
DRIFT_REJECT_RATE_THRESHOLD    = 0.40  # > 40% reject rate over rolling 200-call window
DRIFT_SKEW_THRESHOLD           = 0.85  # > 85% single-category over 150 calls
DRIFT_CONFIDENCE_DELTA         = 0.20  # +20% confidence inflation trigger (absolute score pts)

# Fail-open thresholds
FAILOPEN_WINDOW: int           = 10    # Rolling window for FailOpen fast-path tracking
FAILOPEN_MAX_BYPASSES: int     = 10    # Window denominator for FailOpen telemetry / fast-path
FAILOPEN_FAST_PATH_THRESHOLD: int = int(os.environ.get("LLM_FAILOPEN_FAST_PATH_THRESHOLD", "5"))
FAILOPEN_FAST_PATH_MINUTES: float = float(os.environ.get("LLM_FAILOPEN_FAST_PATH_MINUTES", "30"))
FAILOPEN_EMERGENCY_STOP_THRESHOLD: int = int(os.environ.get("LLM_FAILOPEN_EMERGENCY_STOP_THRESHOLD", "20"))

VALID_DECISIONS = frozenset({"approve", "demote", "reject"})

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════════════
# FAST-CACHE: Symbol Audit Cache (2-minute TTL)
# ═════════════════════════════════════════════════════════════════════════════

class SymbolAuditCache:
    """Fast-Cache for LLM symbol audits with 2-minute TTL."""
    
    def __init__(self, ttl_seconds: float = 120.0):
        self.ttl_seconds = ttl_seconds
        self._cache: Dict[str, Tuple[GovernanceDecision, float]] = {}
        self._lock = threading.Lock()
    
    def get(self, symbol: str) -> Optional[GovernanceDecision]:
        """
        Retrieve cached audit result if not expired.
        Returns None if cache miss or expired.
        """
        with self._lock:
            if symbol not in self._cache:
                return None
            
            decision, timestamp = self._cache[symbol]
            age_seconds = time.time() - timestamp
            
            if age_seconds > self.ttl_seconds:
                # Expired, remove
                del self._cache[symbol]
                logger.debug(f"[FAST_CACHE] {symbol} cache expired (age: {age_seconds:.0f}s)")
                return None
            
            logger.info(f"[FAST_CACHE_HIT] {symbol} | Cache age: {age_seconds:.1f}s | Decision: {decision.decision}")
            return decision
    
    def set(self, symbol: str, decision: GovernanceDecision) -> None:
        """Store audit result in cache with current timestamp."""
        with self._lock:
            self._cache[symbol] = (decision, time.time())
            logger.info(f"[FAST_CACHE_STORE] {symbol} | Decision: {decision.decision} | TTL: {self.ttl_seconds}s")
    
    def clear(self) -> None:
        """Clear all cached entries."""
        with self._lock:
            self._cache.clear()


# Global fast-cache instance
symbol_audit_cache = SymbolAuditCache(ttl_seconds=120.0)  # 2-minute TTL


def set_llm_governance_enabled(enabled: bool) -> None:
    """Update the module-level governance switch."""
    global ENABLE_LLM_GOVERNANCE  # noqa: PLW0603
    ENABLE_LLM_GOVERNANCE = bool(enabled)


def fetch_ollama_models() -> List[str]:
    """Fetch installed local Ollama model names."""
    req = urllib.request.Request(OLLAMA_TAGS_URL, method="GET")
    with urllib.request.urlopen(req, timeout=12.0) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    models = payload.get("models", []) if isinstance(payload, dict) else []
    names: List[str] = []
    for item in models:
        if isinstance(item, dict):
            name = item.get("name") or item.get("model")
            if name:
                names.append(str(name))
        elif isinstance(item, str):
            names.append(str(item))
    return names


def probe_local_ollama_health(smoke_test: bool = True) -> Dict[str, Any]:
    """Validate local Ollama reachability, model presence, and JSON response mode."""
    required_models = sorted({OLLAMA_MODEL_FAST, OLLAMA_MODEL_HEAVY})
    result: Dict[str, Any] = {
        "service_reachable": False,
        "required_models": required_models,
        "installed_models": [],
        "required_models_available": False,
        "json_smoke_ok": False,
        "error": None,
    }
    try:
        installed_models = fetch_ollama_models()
        result["service_reachable"] = True
        result["installed_models"] = installed_models
        normalized = {str(model).strip().lower() for model in installed_models if str(model).strip()}
        required_normalized = {
            alias
            for model in required_models
            for alias in (str(model).strip().lower(), f"{str(model).strip().lower()}:latest")
        }
        result["required_models_available"] = not required_normalized.isdisjoint(normalized)
        if smoke_test and result["required_models_available"]:
            raw = _ollama_request_blocking('{"status":"ok"}', OLLAMA_MODEL_FAST).strip()
            if not raw:
                raise ValueError("empty response from Ollama JSON smoke test")
            parsed = json.loads(raw)
            result["json_smoke_ok"] = isinstance(parsed, dict)
        else:
            result["json_smoke_ok"] = bool(result["required_models_available"])
    except Exception as exc:
        result["error"] = str(exc)
    return result


# ═════════════════════════════════════════════════════════════════════════════
# 1. DATA STRUCTURES
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class GovernanceInput:
    """Compact structured input supplied to the LLM for each trade decision."""
    symbol: str
    regime: str
    rsi: float
    adx: float
    atr: float
    rr_ratio: float
    ml_confidence: float          # 0.0–1.0
    volatility_pct: float         # e.g. 0.12
    forced_execution: bool
    position_size: float          # lots
    expectancy_multiplier: float  # R-multiple expectancy
    confluence_score: float = 0.0  # Strategy confluence score (0.0-100.0)

    def to_compact_dict(self) -> Dict[str, Any]:
        d = {
            "symbol":               self.symbol,
            "regime":               self.regime,
            "rsi":                  round(self.rsi,                 2),
            "adx":                  round(self.adx,                 2),
            "atr":                  round(self.atr,                 5),
            "rr_ratio":             round(self.rr_ratio,            2),
            "ml_confidence":        round(self.ml_confidence,       4),
            "volatility_pct":       round(self.volatility_pct,      4),
            "forced_execution":     self.forced_execution,
            "position_size":        round(self.position_size,       4),
            "expectancy_multiplier":round(self.expectancy_multiplier, 2),
        }
        # Include macro context if available (from Finnhub)
        if hasattr(self, 'macro') and self.macro:
            d["macro"] = self.macro
        return d

    def canonical_hash(self) -> str:
        """
        SHA256 of the canonicalized JSON representation.
        Keys are sorted for deterministic serialisation; used to detect
        accidental mutation before/after async thread execution.
        """
        canonical = json.dumps(self.to_compact_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class GovernanceDecision:
    """Parsed and validated LLM governance response."""
    decision: str       # "approve" | "demote" | "reject"
    confidence: int     # 0–100
    reason: str
    risk_flag: bool
    latency_ms: float
    input_hash: str     = ""    # SHA256 of GovernanceInput at call time
    bypassed: bool      = False
    bypass_reason: str  = ""

    @property
    def approved(self) -> bool:
        return self.decision == "approve"

    @property
    def demoted(self) -> bool:
        return self.decision == "demote"

    @property
    def rejected(self) -> bool:
        return self.decision == "reject"


@dataclass
class EvaluationRecord:
    """One LLM decision entry in the rolling expectancy tracker."""
    cycle: int
    symbol: str
    decision: str
    confidence: int
    risk_flag: bool
    forced_demoted: bool
    trade_executed: bool
    bypassed: bool      = False
    outcome_rr: Optional[float] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ═════════════════════════════════════════════════════════════════════════════
# 2. SHA-256 INPUT HASH HELPERS
# ═════════════════════════════════════════════════════════════════════════════

def _log_and_capture_hash(inputs: GovernanceInput) -> str:
    """
    Compute the canonical SHA256 hash of GovernanceInput, log it, and return it.
    Called immediately before dispatching to the LLM thread.
    """
    h = inputs.canonical_hash()
    logger.info(
        "[LLM_GOVERNANCE_AUDIT] INPUT_HASH | %s | SHA256=%s",
        inputs.symbol, h
    )
    return h


def _validate_hash_integrity(inputs: GovernanceInput, original_hash: str) -> bool:
    """
    Recompute the hash post-call and compare against the pre-call value.
    Returns True if unchanged; logs CRITICAL and returns False on mismatch.
    """
    post_hash = inputs.canonical_hash()
    if post_hash != original_hash:
        logger.critical(
            "[LLM_GOVERNANCE_AUDIT] HASH_MISMATCH | %s | PRE=%s | POST=%s | "
            "Input mutated during async thread execution — bypassing.",
            inputs.symbol, original_hash, post_hash
        )
        return False
    return True


# ═════════════════════════════════════════════════════════════════════════════
# 3. FAIL-OPEN MONITOR
# ═════════════════════════════════════════════════════════════════════════════

class FailOpenMonitor:
    """
    Tracks LLM bypass events (timeout, empty response, schema violation).
    Uses a rolling 10-call window for the Technical-Only fast-path and a
    consecutive-failure counter for the emergency stop.
    """

    def __init__(
        self,
        window: int = FAILOPEN_WINDOW,
        max_bypasses: int = FAILOPEN_MAX_BYPASSES,
    ):
        self._window = window
        self._max_bypasses = max_bypasses
        # Circular buffer of booleans: True = bypass, False = successful call
        self._calls: Deque[bool] = deque(maxlen=window)
        self._fast_path_active: bool = False
        self._consecutive_bypass_failures: int = 0
        self._emergency_stop_triggered: bool = False

    def record(self, was_bypass: bool, *, reset_hard_stop: bool = False) -> None:
        """
        Record one LLM call outcome.
        """
        self._calls.append(was_bypass)

        if was_bypass:
            self._consecutive_bypass_failures += 1
            if (
                not self._emergency_stop_triggered
                and self._consecutive_bypass_failures > max(0, FAILOPEN_EMERGENCY_STOP_THRESHOLD)
            ):
                self._trigger_emergency_stop()
        elif reset_hard_stop:
            self._consecutive_bypass_failures = 0

        bypass_count = sum(self._calls)
        if bypass_count >= min(self._max_bypasses, max(1, FAILOPEN_FAST_PATH_THRESHOLD)):
            if not self._fast_path_active:
                self._activate_macro_fast_path(bypass_count)
        else:
            self._fast_path_active = False

    def reset_on_success(self) -> None:
        """
        Clear fail-open pressure after a confirmed valid response so the
        advisory path can recover immediately.
        """
        self._calls.clear()
        self._consecutive_bypass_failures = 0
        if self._fast_path_active:
            clear_local_llm_fast_path()
        self._fast_path_active = False

    def _activate_macro_fast_path(self, bypass_count: int) -> None:
        until = activate_local_llm_fast_path(
            duration_minutes=FAILOPEN_FAST_PATH_MINUTES,
            reason=f"failopen_{bypass_count}_of_{self._max_bypasses}",
            source="llm_governance",
        )
        self._fast_path_active = True
        logger.warning(
            "[LLM_GOVERNANCE_FAST_PATH] FailOpen reached %d/%d. "
            "Forcing macro analysis into TECHNICAL_ONLY mode until %s to reduce local CPU load.",
            bypass_count,
            self._max_bypasses,
            until.isoformat(),
        )

    def _trigger_emergency_stop(self) -> None:
        self._emergency_stop_triggered = True
        trigger_emergency_stop("AI_GOVERNANCE_FAILOPEN_HARD_STOP")
        logger.critical(
            "[EMERGENCY_STOP] AI Governance has failed 20 times. Trading disabled to protect equity. Manual restart required. "
            "consecutive_bypasses=%d threshold=%d",
            self._consecutive_bypass_failures,
            FAILOPEN_EMERGENCY_STOP_THRESHOLD,
        )

    @property
    def bypass_count_in_window(self) -> int:
        return sum(self._calls)

    @property
    def total_calls_recorded(self) -> int:
        return len(self._calls)

    @property
    def consecutive_bypass_failures(self) -> int:
        return self._consecutive_bypass_failures


# ═════════════════════════════════════════════════════════════════════════════
# 4. DRIFT MONITORING MODULE
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class _DriftEntry:
    """Single slot in the DriftMonitor's rolling call log."""
    decision: str       # "approve" | "demote" | "reject" | "bypass"
    confidence: int     # 0 if bypassed
    outcome_rr: Optional[float] = None


class DriftMonitoringModule:
    """
    Maintains a rolling window of the last DRIFT_WINDOW_CALLS (200) LLM
    decisions and exposes continuous drift detection across four axes:

    1. Approval-rate spike  — >90% approve for 100 consecutive cycles
    2. Reject-rate spike    — >40% reject in the rolling 200-call window
    3. Confidence inflation — current 200-call avg confidence vs prior 200-call
                              avg rises >20 points without R-multiple improvement
    4. Decision skew        — >85% of the last 150 calls fall in one category

    All drift conditions emit a CRITICAL [LLM_GOVERNANCE_AUDIT] DRIFT_ alert.
    Each condition has an independent cooldown so it fires at most once per
    DRIFT_WINDOW_CALLS successful calls, preventing log-flooding.
    """

    def __init__(self) -> None:
        self._calls: Deque[_DriftEntry] = deque(maxlen=DRIFT_WINDOW_CALLS)

        # Rolling confidence history for inflation detection
        # We keep two non-overlapping 200-call epochs
        self._prev_epoch_avg_confidence: Optional[float] = None
        self._prev_epoch_avg_rr: Optional[float] = None
        self._epoch_call_count: int = 0

        # Consecutive-high-approval counter (for the 100-cycle threshold)
        self._consecutive_high_approval: int = 0

        # Per-condition cooldowns (call counts since last fire)
        self._cooldown_approval:    int = 0
        self._cooldown_reject:      int = 0
        self._cooldown_confidence:  int = 0
        self._cooldown_skew:        int = 0
        _COOLDOWN = DRIFT_WINDOW_CALLS
        self._COOLDOWN = _COOLDOWN

    # ── Public API ────────────────────────────────────────────────────────────

    def record(self, decision: str, confidence: int, is_bypass: bool = False) -> None:
        """
        Add one resolved LLM call to the drift window.
        Call this for every LLM interaction (including bypasses, coded as 'bypass').
        """
        label = "bypass" if is_bypass else decision
        self._calls.append(_DriftEntry(decision=label, confidence=confidence))
        self._epoch_call_count += 1

        # Tick cooldowns down
        self._cooldown_approval    = max(0, self._cooldown_approval    - 1)
        self._cooldown_reject      = max(0, self._cooldown_reject      - 1)
        self._cooldown_confidence  = max(0, self._cooldown_confidence  - 1)
        self._cooldown_skew        = max(0, self._cooldown_skew        - 1)

        # Only run drift checks when we have enough data
        if len(self._calls) < 20:
            return

        self._check_approval_rate()
        self._check_reject_rate()
        self._check_skew()

        # Epoch boundary: every DRIFT_WINDOW_CALLS, snapshot for inflation check
        if self._epoch_call_count % DRIFT_WINDOW_CALLS == 0:
            self._snapshot_epoch_and_check_inflation()

    def update_outcome(self, symbol: str, outcome_rr: float) -> None:
        """Retroactively attach an R-multiple to the most recent un-filled entry."""
        for entry in reversed(self._calls):
            if entry.outcome_rr is None and entry.decision not in ("bypass",):
                entry.outcome_rr = outcome_rr
                return

    def get_summary(self) -> Dict[str, Any]:
        """Return current window statistics (used by 50-cycle interval summary)."""
        calls = list(self._calls)
        n = len(calls)
        if n == 0:
            return {}

        real_calls = [c for c in calls if c.decision != "bypass"]
        n_real = len(real_calls)

        return {
            "total_in_window":    n,
            "approve_count":      sum(1 for c in real_calls if c.decision == "approve"),
            "demote_count":       sum(1 for c in real_calls if c.decision == "demote"),
            "reject_count":       sum(1 for c in real_calls if c.decision == "reject"),
            "bypass_count":       sum(1 for c in calls      if c.decision == "bypass"),
            "avg_confidence":     (
                sum(c.confidence for c in real_calls) / n_real if n_real else 0
            ),
            "approval_rate":      (
                sum(1 for c in real_calls if c.decision == "approve") / n_real
                if n_real else 0
            ),
            "reject_rate":        (
                sum(1 for c in real_calls if c.decision == "reject") / n_real
                if n_real else 0
            ),
        }

    # ── Private checks ────────────────────────────────────────────────────────

    def _check_approval_rate(self) -> None:
        """
        Consecutive >90% approval rate over the last 100 calls.
        Uses a streaming counter: increments when the window rate is high,
        resets when it dips below the threshold.
        """
        # Compute rate over last 100 real calls
        recent = [c for c in list(self._calls)[-100:] if c.decision != "bypass"]
        if len(recent) < 30:           # Not enough data yet
            return

        approve_rate = sum(1 for c in recent if c.decision == "approve") / len(recent)

        if approve_rate > DRIFT_APPROVE_RATE_THRESHOLD:
            self._consecutive_high_approval += 1
        else:
            self._consecutive_high_approval = 0
            return

        if (
            self._consecutive_high_approval >= DRIFT_APPROVE_CONSECUTIVE
            and self._cooldown_approval == 0
        ):
            logger.critical(
                "[LLM_GOVERNANCE_AUDIT] DRIFT_APPROVAL_SPIKE | "
                "Approval rate=%.1f%% for %d consecutive evaluations "
                "(threshold >%.0f%% / %d calls) | "
                "Possible model drift or behavioral collapse — review LLM output.",
                approve_rate * 100,
                self._consecutive_high_approval,
                DRIFT_APPROVE_RATE_THRESHOLD * 100,
                DRIFT_APPROVE_CONSECUTIVE,
            )
            self._cooldown_approval = self._COOLDOWN

    def _check_reject_rate(self) -> None:
        """Reject rate > 40% in rolling 200-call window."""
        if self._cooldown_reject > 0:
            return

        real = [c for c in self._calls if c.decision != "bypass"]
        if len(real) < 40:
            return

        reject_rate = sum(1 for c in real if c.decision == "reject") / len(real)
        if reject_rate > DRIFT_REJECT_RATE_THRESHOLD:
            logger.critical(
                "[LLM_GOVERNANCE_AUDIT] DRIFT_REJECT_SPIKE | "
                "Reject rate=%.1f%% in last %d real calls "
                "(threshold >%.0f%%) | "
                "Possible over-conservative drift — verify LLM calibration.",
                reject_rate * 100,
                len(real),
                DRIFT_REJECT_RATE_THRESHOLD * 100,
            )
            self._cooldown_reject = self._COOLDOWN

    def _check_skew(self) -> None:
        """
        >85% of last 150 real calls fall in a single decision category.
        Indicates behavioral collapse (model stuck in one mode).
        """
        if self._cooldown_skew > 0:
            return

        window_slice = list(self._calls)[-DRIFT_SKEW_WINDOW:]
        real = [c for c in window_slice if c.decision != "bypass"]
        if len(real) < 50:
            return

        counts = {
            "approve": sum(1 for c in real if c.decision == "approve"),
            "demote":  sum(1 for c in real if c.decision == "demote"),
            "reject":  sum(1 for c in real if c.decision == "reject"),
        }
        dominant = max(counts, key=counts.__getitem__)
        dominant_rate = counts[dominant] / len(real)

        if dominant_rate > DRIFT_SKEW_THRESHOLD:
            logger.critical(
                "[LLM_GOVERNANCE_AUDIT] DRIFT_DECISION_SKEW | "
                "Category '%s' dominates %.1f%% of last %d real calls "
                "(threshold >%.0f%%) | "
                "Behavioral collapse suspected — LLM may not be differentiating signals.",
                dominant,
                dominant_rate * 100,
                len(real),
                DRIFT_SKEW_THRESHOLD * 100,
            )
            self._cooldown_skew = self._COOLDOWN

    def _snapshot_epoch_and_check_inflation(self) -> None:
        """
        At each 200-call epoch boundary, compare current avg confidence and
        avg R-multiple vs the previous epoch.  Flag if confidence rose >20
        points without a corresponding R-multiple improvement.
        """
        real = [c for c in self._calls if c.decision != "bypass"]
        if not real:
            return

        current_avg_conf = sum(c.confidence for c in real) / len(real)

        completed = [c for c in real if c.outcome_rr is not None]
        current_avg_rr = (
            sum(c.outcome_rr for c in completed) / len(completed)
            if completed else None
        )

        if self._prev_epoch_avg_confidence is not None:
            conf_delta = current_avg_conf - self._prev_epoch_avg_confidence

            rr_improved = (
                current_avg_rr is not None
                and self._prev_epoch_avg_rr is not None
                and current_avg_rr > self._prev_epoch_avg_rr
            )

            if conf_delta > DRIFT_CONFIDENCE_DELTA * 100 and not rr_improved:
                if self._cooldown_confidence == 0:
                    logger.critical(
                        "[LLM_GOVERNANCE_AUDIT] DRIFT_CONFIDENCE_INFLATION | "
                        "Confidence avg rose %.1f pts (prev=%.1f → now=%.1f) "
                        "without R-multiple improvement "
                        "(prev_R=%s, curr_R=%s) | "
                        "Possible model over-confidence or calibration drift.",
                        conf_delta,
                        self._prev_epoch_avg_confidence,
                        current_avg_conf,
                        f"{self._prev_epoch_avg_rr:.2f}" if self._prev_epoch_avg_rr else "N/A",
                        f"{current_avg_rr:.2f}" if current_avg_rr else "N/A",
                    )
                    self._cooldown_confidence = self._COOLDOWN

        # Update epoch snapshot
        self._prev_epoch_avg_confidence = current_avg_conf
        self._prev_epoch_avg_rr = current_avg_rr


# ═════════════════════════════════════════════════════════════════════════════
# 5. SCHEMA VALIDATOR
# ═════════════════════════════════════════════════════════════════════════════

class GovernanceResponseValidator:
    """
    Strict schema validator for the LLM JSON response contract.
    Also enforces the token-budget by truncating overly verbose text
    before parsing, and rejecting responses that are excessively long.
    """

    REQUIRED_FIELDS = {"decision", "confidence", "reason", "risk_flag"}
    MAX_RAW_CHARS   = LLM_MAX_TOKENS * 6   # ~6 chars/token upper bound for JSON
    JSON_OBJECT_PATTERN = re.compile(r"\{.*\}", re.DOTALL)

    def validate(self, raw: Any) -> GovernanceDecision:
        """
        Parse and validate the raw LLM output.
        Supports both short form (conf, risk) and long form (confidence, risk_flag).
        Handles both structured JSON responses and emergency one-word responses.
        Raises ValueError on any schema violation.
        """
        if isinstance(raw, str):
            # Check for ONE-WORD EMERGENCY RESPONSE (APPROVE or REJECT)
            # This bypasses JSON parsing for speed optimization
            stripped = raw.strip().upper()
            if stripped in ("APPROVE", "REJECT"):
                # Convert one-word response to structured decision
                logger.info("[LLM_FAST_MODE] One-word response: %s (latency optimized)", stripped)
                return GovernanceDecision(
                    decision="approve" if stripped == "APPROVE" else "reject",
                    confidence=75 if stripped == "APPROVE" else 80,  # Conservative defaults
                    reason="Emergency one-word mode (fast execution)",
                    risk_flag=False,
                    latency_ms=0.0,
                )
            
            # Enforce token-budget: reject / trim verbose responses
            raw = self._enforce_budget(raw)
            raw = self._extract_json(raw)

        if not isinstance(raw, dict):
            raise ValueError(f"Response is not a JSON object: {type(raw)}")

        # Normalize field names: support both short (conf, risk) and long (confidence, risk_flag)
        if "conf" in raw and "confidence" not in raw:
            raw["confidence"] = raw.pop("conf")
        if "risk" in raw and "risk_flag" not in raw:
            raw["risk_flag"] = raw.pop("risk")

        missing = self.REQUIRED_FIELDS - set(raw.keys())
        if missing:
            # ISSUE 2 FIX: Instead of raising error, apply SAFE DEFAULTS
            # This prevents FailOpen bypass and keeps bot in governance mode
            logger.warning(
                "[LLM_SCHEMA_FALLBACK] Missing required fields: %s | Applying safe defaults",
                missing
            )
            
            # Safe defaults: Default to "demote" (conservative), high confidence in the rejection,
            # risk_flag=True (safe mode), and clear reason
            if "decision" not in raw:
                raw["decision"] = "demote"  # Conservative default: demote instead of reject
            if "confidence" not in raw:
                raw["confidence"] = 75  # High confidence in conservative decision
            if "reason" not in raw:
                raw["reason"] = "Schema fallback: Missing required fields, applying conservative defaults"
            if "risk_flag" not in raw:
                raw["risk_flag"] = True  # TRUE = treat as risky, apply extra caution

        decision = str(raw["decision"]).strip().lower()
        if decision not in VALID_DECISIONS:
            raise ValueError(
                f"Invalid decision '{decision}'; must be one of {VALID_DECISIONS}"
            )

        try:
            confidence = int(raw["confidence"])
        except (TypeError, ValueError):
            raise ValueError(
                f"confidence must be integer 0-100, got: {raw['confidence']}"
            )
        if not (0 <= confidence <= 100):
            raise ValueError(f"confidence {confidence} out of range [0, 100]")

        reason = str(raw.get("reason", "")).strip()
        if not reason:
            raise ValueError("reason must be a non-empty string")
        # Trim excessively verbose reason text to 200 chars
        reason = reason[:200]

        # Handle risk_flag as string ("LOW", "MEDIUM", "HIGH", "L", "M", "H") or boolean
        raw_risk_flag = raw.get("risk_flag", "LOW")
        if isinstance(raw_risk_flag, str):
            # Map string risk levels: HIGH/MEDIUM/M → True (risky), LOW/L → False (safe)
            risk_str = raw_risk_flag.upper()
            risk_flag = risk_str in ("HIGH", "MEDIUM", "M", "H")
        else:
            risk_flag = bool(raw_risk_flag)

        return GovernanceDecision(
            decision=decision,
            confidence=confidence,
            reason=reason,
            risk_flag=risk_flag,
            latency_ms=0.0,
        )

    def _enforce_budget(self, text: str) -> str:
        """
        Reject and log overly verbose responses (>MAX_RAW_CHARS characters).
        We discard everything outside the first { ... } JSON block on purpose
        so verbose preamble/postamble cannot pollute the structured contract.
        """
        if len(text) > self.MAX_RAW_CHARS:
            logger.critical(
                "[LLM_GOVERNANCE_AUDIT] TOKEN_BUDGET_EXCEEDED | "
                "Raw response length=%d chars (limit=%d) | "
                "Trimming to first JSON block only.",
                len(text), self.MAX_RAW_CHARS
            )
        return text  # Actual extraction happens in _extract_json

    @staticmethod
    def _extract_json(text: str) -> Any:
        """Strip markdown fences and extract JSON from raw text with lenient parsing."""
        text = text.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            lines = [ln for ln in lines if not ln.strip().startswith("```")]
            text = "\n".join(lines).strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try regex extraction first (more robust for imperfect JSON)
        match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text)
        if match:
            candidate = match.group(0)
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

        # Fallback to depth-based extraction
        for start_index, char in enumerate(text):
            if char != "{":
                continue
            depth = 0
            for end_index in range(start_index, len(text)):
                current = text[end_index]
                if current == "{":
                    depth += 1
                elif current == "}":
                    depth -= 1
                    if depth == 0:
                        candidate = text[start_index:end_index + 1]
                        try:
                            return json.loads(candidate)
                        except json.JSONDecodeError:
                            break

        raise json.JSONDecodeError("No valid JSON object found in response", text, 0)


# ═════════════════════════════════════════════════════════════════════════════
# 6. ROLLING EVALUATION TRACKER  (50-cycle outcomes)
# ═════════════════════════════════════════════════════════════════════════════

class RollingEvaluationTracker:
    """
    Tracks LLM governance decisions vs. actual trade outcomes over rolling
    50-cycle windows to measure expectancy impact.  Summary emitted every
    50 entries with drift module snapshot.
    """

    def __init__(
        self,
        window: int                   = LLM_EVALUATION_CYCLE_LEN,
        drift: Optional[DriftMonitoringModule] = None,
    ):
        self.window = window
        self._records: deque[EvaluationRecord] = deque(maxlen=window)
        self._completed_cycle_count: int = 0
        self._drift = drift  # Shared reference to DriftMonitoringModule

    def record(self, record: EvaluationRecord) -> None:
        self._records.append(record)
        self._completed_cycle_count += 1
        if self._completed_cycle_count % self.window == 0:
            self._emit_interval_summary()

    def update_outcome(self, symbol: str, outcome_rr: float) -> None:
        """Called post-trade close to fill outcome R-multiple."""
        for rec in reversed(self._records):
            if rec.symbol == symbol and rec.outcome_rr is None and rec.trade_executed:
                rec.outcome_rr = outcome_rr
                if self._drift:
                    self._drift.update_outcome(symbol, outcome_rr)
                logger.info(
                    "[LLM_GOVERNANCE_AUDIT] Outcome recorded | %s | "
                    "Decision=%s | OutcomeR=%.2f",
                    symbol, rec.decision, outcome_rr
                )
                return

    def _emit_interval_summary(self) -> None:
        records = list(self._records)
        total = len(records)
        if total == 0:
            return

        approvals        = sum(1 for r in records if r.decision == "approve")
        demotions        = sum(1 for r in records if r.decision == "demote")
        rejections       = sum(1 for r in records if r.decision == "reject")
        bypasses         = sum(1 for r in records if r.bypassed)
        risk_flags       = sum(1 for r in records if r.risk_flag)
        forced_demotions = sum(1 for r in records if r.forced_demoted)

        completed = [r for r in records if r.outcome_rr is not None]
        avg_rr = (
            sum(r.outcome_rr for r in completed) / len(completed)
            if completed else None
        )
        demoted_completed = [
            r for r in completed if r.decision == "demote"
        ]
        avg_demoted_rr = (
            sum(r.outcome_rr for r in demoted_completed) / len(demoted_completed)
            if demoted_completed else None
        )

        # Drift snapshot
        drift_summary = self._drift.get_summary() if self._drift else {}
        drift_line = (
            " | DriftWindow(200): "
            f"ApproveRate={drift_summary.get('approval_rate', 0):.1%} "
            f"RejectRate={drift_summary.get('reject_rate', 0):.1%} "
            f"AvgConf={drift_summary.get('avg_confidence', 0):.1f}"
        ) if drift_summary else ""

        logger.info(
            "[LLM_GOVERNANCE_AUDIT] === 50-CYCLE INTERVAL SUMMARY ===\n"
            "  Total: %d | Approve: %d | Demote: %d | Reject: %d | Bypass: %d\n"
            "  RiskFlags: %d | ForcedDemotions: %d\n"
            "  Outcomes: %d | AvgR: %s | AvgDemotedR: %s%s",
            total, approvals, demotions, rejections, bypasses,
            risk_flags, forced_demotions,
            len(completed),
            f"{avg_rr:.2f}"        if avg_rr        is not None else "N/A",
            f"{avg_demoted_rr:.2f}" if avg_demoted_rr is not None else "N/A",
            drift_line,
        )


# ═════════════════════════════════════════════════════════════════════════════
# 7. OLLAMA HTTP CLIENT  (tightly constrained inference parameters)
# ═════════════════════════════════════════════════════════════════════════════

def _test_ollama_heartbeat() -> bool:
    """
    Quick heartbeat check (2 seconds) to verify Ollama is responding.
    Returns True if Ollama responds with 200 OK, False otherwise.
    
    This distinguishes between:
    - Ollama is running but busy (heartbeat succeeds, main request times out)
    - Ollama is unreachable (heartbeat fails immediately)
    """
    try:
        # Use the dedicated tags endpoint rather than appending to /api/generate.
        heartbeat_url = OLLAMA_TAGS_URL
        heartbeat_req = urllib.request.Request(
            heartbeat_url,
            headers={"Content-Type": "application/json"},
            method="GET",
        )
        
        # 2-second timeout for quick feedback
        with urllib.request.urlopen(heartbeat_req, timeout=2.0) as resp:
            if resp.getcode() == 200:
                logger.debug("[OLLAMA_HEARTBEAT_OK] Ollama is responding")
                return True
            else:
                logger.warning("[OLLAMA_HEARTBEAT_FAILED] HTTP %d from heartbeat endpoint", resp.getcode())
                return False
    
    except socket.timeout:
        # Timeout on heartbeat = Ollama may be slow/busy
        logger.warning("[OLLAMA_HEARTBEAT_TIMEOUT] Ollama not responding within 2 seconds")
        return False
    except (urllib.error.URLError, ConnectionError) as e:
        # Connection refused/network error = Ollama unreachable
        logger.warning("[OLLAMA_HEARTBEAT_UNREACHABLE] %s", str(e)[:100])
        return False
    except Exception as e:
        logger.warning("[OLLAMA_HEARTBEAT_ERROR] Unexpected error: %s", str(e)[:100])
        return False


def _ollama_request_blocking(prompt: str, model_name: str, request_timeout: Optional[float] = None) -> str:
    """
    Synchronous HTTP POST to Ollama API with deterministic inference caps.
    
    IMPROVEMENTS:
    1. ✅ Heartbeat check: 2-second ping before main request
    2. ✅ Increased timeout from 15s to 60s (configurable via env)
    3. ✅ Detailed exception handling: HTTP status codes, connection errors, JSON parsing
    4. ✅ Keep-alive parameter to keep model in memory between calls
    5. ✅ Comprehensive logging for debugging
    
    Returns: raw response text (empty string on any error, never raises)
    
    Inference parameters (hardened):
      num_predict = LLM_MAX_TOKENS  (150)
      temperature = LLM_TEMPERATURE (0.0)
      top_p       = LLM_TOP_P       (0.85)
      keep_alive  = "5m"            (keeps model in memory for 5 minutes)
    """
    base_options = {
        "num_predict": LLM_MAX_TOKENS,
        "num_ctx": 2048,
        "temperature": LLM_TEMPERATURE,
        "top_p": LLM_TOP_P,
    }

    def _build_request(force_cpu: bool = False) -> urllib.request.Request:
        options = dict(base_options)
        if force_cpu:
            options["num_gpu"] = 0
        payload = json.dumps({
            "model": model_name,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "keep_alive": "5m",
            "options": options,
        }).encode("utf-8")
        return urllib.request.Request(
            OLLAMA_URL,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Connection": "keep-alive",
            },
            method="POST",
        )

    # urllib timeout is per-socket-op; the caller's thread.join() enforces
    # the true wall-clock timeout.
    with OLLAMA_REQUEST_LOCK:
        timeout_seconds = float(request_timeout if request_timeout is not None else LLM_TIMEOUT_SECONDS)
        socket_timeout = max(float(LLM_GOVERNANCE_SOCKET_TIMEOUT), timeout_seconds + 2.0)
        
        # STEP 1: HEARTBEAT CHECK (NEW - 2 seconds)
        # ==========================================
        heartbeat_ok = _test_ollama_heartbeat()
        if not heartbeat_ok:
            logger.error(
                "[OLLAMA_GOVERNANCE] Ollama appears unreachable (heartbeat failed) | model=%s",
                model_name,
            )
            return ""
        
        # STEP 2: MAIN REQUEST (original 60s timeout)
        # ===========================================
        def _run_request(force_cpu: bool = False) -> str:
            req = _build_request(force_cpu=force_cpu)
            with urllib.request.urlopen(req, timeout=socket_timeout) as resp:
                http_code = resp.getcode()
                raw_bytes = resp.read()
                if http_code < 200 or http_code >= 300:
                    logger.warning(
                        "[LLM_GOVERNANCE] Ollama HTTP %d (model=%s timeout=%.1fs)",
                        http_code,
                        model_name,
                        timeout_seconds,
                    )
                    return ""
                try:
                    raw = json.loads(raw_bytes.decode("utf-8"))
                except json.JSONDecodeError as e:
                    logger.warning(
                        "[LLM_GOVERNANCE] JSON parse error (model=%s timeout=%.1fs): %s | Response: %s",
                        model_name,
                        timeout_seconds,
                        str(e)[:80],
                        raw_bytes.decode("utf-8", errors="replace")[:200],
                    )
                    return ""
                response_text = raw.get("response", "")
                thinking_text = raw.get("thinking", "")
                if not response_text.strip() and thinking_text.strip():
                    logger.debug("[LLM_GOVERNANCE] Extracted from 'thinking' field (reasoning model)")
                    return thinking_text
                return response_text or ""

        try:
            return _run_request(force_cpu=False)

        except urllib.error.HTTPError as e:
            # Handle HTTP-level errors (4xx, 5xx)
            http_code = e.code
            error_body = ""
            try:
                error_body = e.read().decode("utf-8", errors="replace")[:200]
            except Exception:
                error_body = "<unable to read error body>"
            
            error_text = str(error_body).lower()
            if "cuda" in error_text:
                logger.warning(
                    "[LLM_GOVERNANCE] CUDA error detected for model %s, retrying on CPU fallback (num_gpu=0).",
                    model_name,
                )
                try:
                    return _run_request(force_cpu=True)
                except Exception:
                    pass

            logger.warning(
                "[LLM_GOVERNANCE_HTTP_ERROR] Ollama HTTP %d | model=%s | timeout=%.1fs | URL=%s | Body=%s",
                http_code,
                model_name,
                timeout_seconds,
                OLLAMA_URL,
                error_body,
            )
            return ""
        
        except urllib.error.URLError as e:
            # Handle connection-level errors (DNS, connection refused, etc.)
            reason = str(getattr(e, "reason", e))
            
            # Detect timeout vs connection error
            if isinstance(e.reason, OSError):
                errno_val = getattr(e.reason, "errno", None)
                # errno 110 = ETIMEDOUT, 54/60 = ECONNRESET / ETIMEDOUT on macOS
                is_timeout = errno_val in (110, 54, 60, 110) or "timed out" in reason.lower()
            else:
                is_timeout = "timed out" in reason.lower()
            
            reason_lower = reason.lower()
            if "cuda" in reason_lower:
                logger.warning(
                    "[LLM_GOVERNANCE] CUDA transport error detected for model %s, retrying on CPU fallback (num_gpu=0).",
                    model_name,
                )
                try:
                    return _run_request(force_cpu=True)
                except Exception:
                    pass
            if is_timeout:
                logger.warning(
                    "[LLM_GOVERNANCE_TIMEOUT] Ollama timeout after %.1fs | model=%s | URL=%s | Reason=%s",
                    timeout_seconds,
                    model_name,
                    OLLAMA_URL,
                    reason[:100],
                )
            else:
                logger.warning(
                    "[LLM_GOVERNANCE_CONNECTION_ERROR] Ollama unreachable | model=%s | URL=%s | Reason=%s",
                    model_name,
                    OLLAMA_URL,
                    reason[:100],
                )
            return ""
        
        except (TimeoutError, socket.timeout) as e:
            # Handle Python-level timeouts
            logger.warning(
                "[LLM_GOVERNANCE_SOCKET_TIMEOUT] Ollama socket timeout after %.1fs | model=%s | Error=%s",
                timeout_seconds,
                model_name,
                str(e)[:80],
            )
            return ""
        
        except Exception as e:
            # Catch-all for unexpected errors
            err_text = str(e).lower()
            if "cuda" in err_text:
                logger.warning(
                    "[LLM_GOVERNANCE] CUDA error detected for model %s, retrying on CPU fallback (num_gpu=0).",
                    model_name,
                )
                try:
                    return _run_request(force_cpu=True)
                except Exception:
                    pass
            logger.warning(
                "[LLM_GOVERNANCE_ERROR] Ollama request failed | model=%s | timeout=%.1fs | Error=%s",
                model_name,
                timeout_seconds,
                str(e)[:100],
            )
            return ""


def _call_ollama_with_timeout(
    prompt: str, model_name: str, timeout: float = LLM_TIMEOUT_SECONDS
) -> Optional[str]:
    """
    Calls Ollama in a daemon thread with a hard wall-clock timeout.
    Returns the raw response string, or None if the thread times out.
    Re-raises network/decode errors for the caller to classify.
    """
    last_error: Optional[Exception] = None
    for attempt in range(1, max(1, OLLAMA_RETRY_ATTEMPTS) + 1):
        result_container: Dict[str, Any] = {"response": None, "error": None}

        def _worker() -> None:
            try:
                result_container["response"] = _ollama_request_blocking(prompt, model_name, request_timeout=timeout)
            except Exception as exc:
                result_container["error"] = exc

        thread = threading.Thread(
            target=_worker, daemon=True, name="LLM-Governance-Worker"
        )
        thread.start()
        thread.join(timeout=timeout)

        if thread.is_alive():
            last_error = TimeoutError(f"Ollama timeout after {timeout:.1f}s (attempt {attempt}/{OLLAMA_RETRY_ATTEMPTS})")
        elif result_container["error"] is not None:
            last_error = result_container["error"]
        else:
            return result_container["response"]

        if attempt < max(1, OLLAMA_RETRY_ATTEMPTS):
            logger.warning(
                "[LLM_GOVERNANCE_RETRY] Ollama call failed on attempt %d/%d for model %s: %s",
                attempt,
                OLLAMA_RETRY_ATTEMPTS,
                model_name,
                last_error,
            )
            time.sleep(max(0.0, OLLAMA_RETRY_DELAY_SECONDS))

    if isinstance(last_error, TimeoutError):
        return None
    if last_error is not None:
        raise last_error
    return None


# ═════════════════════════════════════════════════════════════════════════════
# 8. PROMPT BUILDER
# ═════════════════════════════════════════════════════════════════════════════

def build_governance_prompt(inputs: GovernanceInput) -> str:
    """
    Build a system-prompt-optimized governance query for Qwen 0.8b.
    
    OPTIMIZATIONS FOR SMALL MODELS:
    - Explicit JSON-only instruction
    - No reasoning traces (no <think> tags)
    - Direct validation rules
    - Field-by-field decision tree
    - Guaranteed schema compliance output
    """
    d = inputs.to_compact_dict()
    
    # Extract key trading parameters
    rsi = d.get("rsi", 50.0)
    atr = d.get("atr", 0.0)
    ml_confidence = d.get("ml_confidence", 0.5)
    rr_ratio = d.get("rr_ratio", 2.0)
    regime = d.get("regime", "RANGING")
    
    # Build ultra-concise prompt (optimized for token budget)
    system_instructions = (
        "### SYSTEM INSTRUCTIONS FOR TRADING GOVERNOR ###\n"
        "You are the CRITICAL_RISK_AUDIT system for an HFT bot.\n"
        "Your ONLY job is to validate a trade and return ONLY valid JSON.\n"
        "Do NOT include conversational text, thoughts, or markdown formatting.\n"
        "\n"
        "### VALIDATION RULES ###\n"
        "1. REJECT if RSI is < 30 or > 70 while the Regime is RANGING.\n"
        "2. REJECT if RR (Risk Reward) is below 2.0.\n"
        "3. REJECT if ML Confidence is below 0.45.\n"
        "4. APPROVE if the ML Direction matches the Trend and Volatility is > 0.10%.\n"
        "\n"
        "### REQUIRED JSON SCHEMA ###\n"
        "Output EXACTLY this format (no extra text before or after):\n"
        "{\"decision\":\"approve\",\"confidence\":75,\"risk_flag\":false,\"reason\":\"RSI OK, RR 2.5R, ML 65%\"}\n"
        "OR for rejection:\n"
        "{\"decision\":\"reject\",\"confidence\":85,\"risk_flag\":true,\"reason\":\"RSI 78 > 70 in RANGING\"}\n"
        "\n"
        "### CURRENT MARKET TICKET ###\n"
    )
    
    ticket_data = (
        f"Symbol: {d.get('symbol', 'UNKNOWN')}\n"
        f"Direction: {d.get('direction', 'UNKNOWN')}\n"
        f"Price: {d.get('price', 0.0)}\n"
        f"RSI: {rsi:.1f}\n"
        f"ATR: {atr:.6f}\n"
        f"ML Confidence: {ml_confidence:.2f}\n"
        f"Expected RR: {rr_ratio:.2f}R\n"
        f"Market Regime: {regime}\n"
    )
    
    # ISSUE 3 FIX: Omit raw bars/candles to reduce context window
    # Only send aggregated indicators, not 150 candles
    output_instruction = (
        "\n### OUTPUT ###\n"
        "Return ONLY the JSON object. No markdown. No backticks. No preamble.\n"
        "Validate: All 4 fields present, decision lowercase, confidence 0-100, reason < 120 chars.\n"
    )
    
    return system_instructions + ticket_data + output_instruction



# ═════════════════════════════════════════════════════════════════════════════
# 9. MAIN GOVERNANCE CLIENT
# ═════════════════════════════════════════════════════════════════════════════

class LLMGovernanceClient:
    """
    Primary interface for the LLM Advisory Governance Layer.

    Integrates:
      • SHA256 input hashing (pre/post call integrity check)
      • FailOpenMonitor      (auto-disable on repeated bypass)
      • DriftMonitoringModule(rolling drift detection)
      • RollingEvaluationTracker (50-cycle expectancy measurement)
      • GovernanceResponseValidator (strict JSON schema + token budget)

    Usage (inside analyze_and_trade_symbol, AFTER all deterministic checks):

        gov = llm_governance_client.evaluate(gov_input, cycle=cycle_count,
                                             signal_forced=signal.forced_execution)
        if gov.demoted and signal.forced_execution:
            signal.forced_execution = False
        if gov.rejected:
            return
    """

    def __init__(self) -> None:
        self._validator  = GovernanceResponseValidator()
        self._drift      = DriftMonitoringModule()
        self._tracker    = RollingEvaluationTracker(drift=self._drift)
        self._failopen   = FailOpenMonitor()
        # ISSUE 3 FIX: System Busy Detection
        self._latency_history: Deque[float] = deque(maxlen=LLM_LATENCY_CONSECUTIVE_HITS)
        self._consecutive_slow_calls: int = 0
        self._is_system_busy: bool = False
        self._recovery_cycles_remaining: int = 0
        self._pending_requests: Deque[Tuple[str, datetime]] = deque(maxlen=128)
        self._last_heartbeat_check_at: float = 0.0
        self._last_heartbeat_ok: bool = True

    def _ollama_heartbeat_ok(self, ttl_seconds: float = 5.0) -> bool:
        now = time.time()
        if (now - self._last_heartbeat_check_at) <= ttl_seconds:
            return self._last_heartbeat_ok
        self._last_heartbeat_ok = _test_ollama_heartbeat()
        self._last_heartbeat_check_at = now
        return self._last_heartbeat_ok

    def _queue_deferred_request(self, inputs: GovernanceInput, reason: str) -> None:
        queued_at = datetime.now(timezone.utc)
        self._pending_requests.append((inputs.symbol, queued_at))
        logger.warning(
            "[LLM_GOVERNANCE_QUEUE] %s | Deferred advisory request | reason=%s | queue_depth=%d",
            inputs.symbol,
            reason,
            len(self._pending_requests),
        )

    def _dequeue_ready_symbol(self, symbol: str) -> None:
        if not self._pending_requests:
            return
        self._pending_requests = deque(
            [(queued_symbol, queued_at) for queued_symbol, queued_at in self._pending_requests if queued_symbol != symbol],
            maxlen=128,
        )

    # ── Evaluate ─────────────────────────────────────────────────────────────

    def evaluate(
        self,
        inputs: GovernanceInput,
        cycle: int = 0,
        *,
        signal_forced: bool = False,
    ) -> GovernanceDecision:
        """
        Query the LLM and return a validated GovernanceDecision.

        Falls back to a bypass on any failure.  All bypass events are
        recorded by FailOpenMonitor and may trigger auto-disable.

        Returns GovernanceDecision.  Never raises.
        """
        # ── FAST-CACHE CHECK: 2-minute symbol audit cache ────────────────────
        # If this symbol was recently audited, reuse cached decision
        cached_decision = symbol_audit_cache.get(inputs.symbol)
        if cached_decision:
            self._drift.record(decision=cached_decision.decision, confidence=cached_decision.confidence, is_bypass=False)
            return cached_decision
        
        # ── LLM Fast Track Bypass (Sniper Mode) ─────────────────────────────
        # High confidence (ML), high strategy score, or forced trades bypass LLM audit 
        # to reduce latency and slippage.
        is_high_conf_ml = inputs.ml_confidence > 0.90
        is_high_conf_strat = inputs.confluence_score > 90.0
        
        if signal_forced or is_high_conf_ml or is_high_conf_strat:
            logger.critical(
                f"[LLM_GOVERNANCE_FAST_TRACK] {inputs.symbol} | "
                f"ML: {inputs.ml_confidence:.2f} | Strat: {inputs.confluence_score:.1f} | "
                f"Forced: {signal_forced} | Bypassing audit."
            )
            return GovernanceDecision(
                decision="approve",
                confidence=100,
                reason="Fast Track: High Confidence/Forced",
                risk_flag=False,
                latency_ms=0.0,
                bypassed=True,
                bypass_reason="fast_track"
            )


        # ── Feature flag check ───────────────────────────────────────────────
        if not ENABLE_LLM_GOVERNANCE:
            return self._bypass("ENABLE_LLM_GOVERNANCE=False")


        # ── Step 1: Hash input before dispatch ───────────────────────────────
        pre_hash = _log_and_capture_hash(inputs)

        # ── Step 2: Determine Model Tier ─────────────────────────────────────
        # Start with the fast model for every trade, including Tier-A / forced signals.
        # Heavy reasoning is reserved for the final audit escalation path.
        target_model = OLLAMA_MODEL_FAST
        is_escalated = False
        target_timeout = LLM_TIMEOUT_SECONDS

        if self._is_system_busy:
            target_model = LLM_MODEL_LIGHT
            target_timeout = min(target_timeout, max(5.0, LLM_TIMEOUT_SECONDS * 0.5))

        if not self._ollama_heartbeat_ok():
            self._queue_deferred_request(inputs, "heartbeat_unreachable")
            cached_decision = symbol_audit_cache.get(inputs.symbol)
            if cached_decision is not None:
                logger.warning(
                    "[LLM_GOVERNANCE_CACHE_FALLBACK] %s | Reusing cached advisory decision while Ollama heartbeat is unavailable.",
                    inputs.symbol,
                )
                return cached_decision
            return self._record_bypass(
                inputs,
                "Ollama heartbeat unavailable; request deferred",
                latency_ms=0.0,
                cycle=cycle,
            )

        prompt  = build_governance_prompt(inputs)
        t_start = time.perf_counter()

        try:
            raw_response = _call_ollama_with_timeout(prompt, model_name=target_model, timeout=target_timeout)
        except urllib.error.URLError as exc:
            self._queue_deferred_request(inputs, "ollama_unreachable")
            cached_decision = symbol_audit_cache.get(inputs.symbol)
            if cached_decision is not None:
                logger.warning(
                    "[LLM_GOVERNANCE_CACHE_FALLBACK] %s | Reusing cached advisory decision while Ollama is unreachable.",
                    inputs.symbol,
                )
                return cached_decision
            return self._record_bypass(
                inputs, f"Ollama unreachable: {exc}",
                latency_ms=(time.perf_counter() - t_start) * 1000,
                cycle=cycle,
            )
        except Exception as exc:
            self._queue_deferred_request(inputs, "ollama_http_error")
            cached_decision = symbol_audit_cache.get(inputs.symbol)
            if cached_decision is not None:
                logger.warning(
                    "[LLM_GOVERNANCE_CACHE_FALLBACK] %s | Reusing cached advisory decision after transient Ollama error.",
                    inputs.symbol,
                )
                return cached_decision
            return self._record_bypass(
                inputs, f"HTTP error: {exc}",
                latency_ms=(time.perf_counter() - t_start) * 1000,
                cycle=cycle,
            )

        latency_ms = (time.perf_counter() - t_start) * 1000
        
        # ISSUE 3 FIX: System Busy Detection - Track latency and auto-downgrade if needed
        self._latency_history.append(latency_ms)
        if latency_ms > LLM_LATENCY_THRESHOLD_MS:
            self._consecutive_slow_calls += 1
            if self._consecutive_slow_calls >= LLM_LATENCY_CONSECUTIVE_HITS:
                self._is_system_busy = True
                self._recovery_cycles_remaining = LLM_LATENCY_RECOVERY_CYCLES
                logger.warning(
                    "[LLM_GOVERNANCE_SYSTEM_BUSY] System detected as busy: %d consecutive calls exceeded %.0fms threshold. "
                    "Switching to lighter model (%s) and skipping LLM checks for %d cycles.",
                    self._consecutive_slow_calls, LLM_LATENCY_THRESHOLD_MS, LLM_MODEL_LIGHT, LLM_LATENCY_RECOVERY_CYCLES
                )
        else:
            self._consecutive_slow_calls = 0
        
        # Recovery tracking: decrement if system was busy
        if self._is_system_busy and self._recovery_cycles_remaining > 0:
            self._recovery_cycles_remaining -= 1
            if self._recovery_cycles_remaining == 0:
                self._is_system_busy = False
                logger.info("[LLM_GOVERNANCE_SYSTEM_RECOVERY] System recovered. Resuming normal LLM checks.")
        
        # Debug: Log raw response presence
        if raw_response:
            logger.info(f"[LLM_DEBUG] Raw response length: {len(raw_response)} | Latency: {latency_ms:.0f}ms | Snippet: {raw_response[:50]!r}")
        else:
            logger.warning(f"[LLM_DEBUG] Raw response is None or empty. Latency: {latency_ms:.0f}ms")

        # ... (Validation boilerplate continues below)
        if raw_response is None:
            self._queue_deferred_request(inputs, "timeout_exceeded")
            cached_decision = symbol_audit_cache.get(inputs.symbol)
            if cached_decision is not None:
                logger.warning(
                    "[LLM_GOVERNANCE_CACHE_FALLBACK] %s | Reusing cached advisory decision after Ollama timeout.",
                    inputs.symbol,
                )
                return cached_decision
            return self._record_bypass(inputs, "Timeout exceeded; request deferred", latency_ms=latency_ms, cycle=cycle)

        if not raw_response.strip():
            return self._record_bypass(inputs, "Empty LLM response", latency_ms=latency_ms, cycle=cycle)

        if not _validate_hash_integrity(inputs, pre_hash):
            return self._record_bypass(inputs, "Input hash mismatch", latency_ms=latency_ms, cycle=cycle)

        try:
            decision = self._validator.validate(raw_response)
            decision.latency_ms  = latency_ms
            decision.input_hash  = pre_hash
        except (ValueError, json.JSONDecodeError) as schema_err:
            return self._record_bypass(inputs, f"Schema violation: {schema_err}", latency_ms=latency_ms, cycle=cycle)

        # ── Step 8: Multi-Model Escalation / Audit ───────────────────────────
        # If FAST model flags a risk or rejects, but we didn't use HEAVY yet, 
        # ESCALATE to HEAVY for a second opinion logic.
        if not is_escalated and (decision.risk_flag or decision.decision == "reject"):
            logger.info(
                "[LLM_GOVERNANCE_AUDIT] ESCALATING | %s | %s flagged risk (Conf=%d). "
                "Consulting %s for heavy reasoning...",
                inputs.symbol, OLLAMA_MODEL_FAST, decision.confidence, OLLAMA_MODEL_HEAVY
            )
            
            t_audit_start = time.perf_counter()
            try:
                # Audit prompt includes the first model's doubt
                audit_prompt = (
                    f"{prompt}\n\n"
                    f"Note: A smaller model flagged this trade for '{decision.reason}' "
                    f"with confidence {decision.confidence}. Please provide a heavy-reasoning "
                    "audit and confirm if this rejection/risk is valid."
                )
                raw_audit = _call_ollama_with_timeout(
                    audit_prompt, model_name=OLLAMA_MODEL_HEAVY, timeout=LLM_HEAVY_TIMEOUT_SECONDS
                )
                
                if raw_audit and raw_audit.strip():
                    audit_decision = self._validator.validate(raw_audit)
                    audit_latency = (time.perf_counter() - t_audit_start) * 1000
                    
                    logger.info(
                        "[LLM_GOVERNANCE_AUDIT] ESCALATION_COMPLETE | %s | %s Decision: %s | Conf: %d | "
                        "Original Reason: %s | Audit Reason: %s",
                        inputs.symbol, OLLAMA_MODEL_HEAVY, audit_decision.decision.upper(),
                        audit_decision.confidence, decision.reason, audit_decision.reason
                    )
                    
                    # Override with HEAVY model's wisdom
                    decision = audit_decision
                    decision.latency_ms += audit_latency
                    is_escalated = True

            except Exception as audit_exc:
                logger.warning(
                    "[LLM_GOVERNANCE_AUDIT] ESCALATION_FAILED | %s | Failed to verify with %s: %s",
                    inputs.symbol, OLLAMA_MODEL_HEAVY, audit_exc
                )

        # ── Step 9: Final Logging & Data Feed ────────────────────────────────
        logger.info(
            "[LLM_GOVERNANCE_AUDIT] %s | Decision=%s | Confidence=%d | "
            "RiskFlag=%s | Latency=%.0fms | Tier=%s | Reason: %s",
            inputs.symbol, decision.decision.upper(), decision.confidence,
            decision.risk_flag, decision.latency_ms,
            "HEAVY" if is_escalated else "FAST",
            decision.reason,
        )

        if decision.risk_flag or decision.decision == "reject":
            logger.critical(
                "[LLM_GOVERNANCE_AUDIT] RISK_ANOMALY | %s | Decision=%s | Confidence=%d | "
                "Tier=%s | Reason: %s",
                inputs.symbol, decision.decision.upper(), decision.confidence,
                "HEAVY" if is_escalated else "FAST", decision.reason,
            )

        self._drift.record(decision=decision.decision, confidence=decision.confidence, is_bypass=False)
        self._failopen.record(was_bypass=False, reset_hard_stop=True)
        self._failopen.reset_on_success()

        was_demoted = (decision.decision == "demote") and signal_forced
        self._tracker.record(EvaluationRecord(
            cycle=cycle, symbol=inputs.symbol, decision=decision.decision,
            confidence=decision.confidence, risk_flag=decision.risk_flag,
            forced_demoted=was_demoted, trade_executed=(decision.decision != "reject"),
            bypassed=False,
        ))

        # ── FAST-CACHE STORE: Cache this decision for 2 minutes ──────────────
        symbol_audit_cache.set(inputs.symbol, decision)
        self._dequeue_ready_symbol(inputs.symbol)

        return decision

    # ── Public helpers ────────────────────────────────────────────────────────

    def record_trade_outcome(self, symbol: str, outcome_rr: float) -> None:
        """Called after a trade closes to record the actual outcome R-multiple."""
        self._tracker.update_outcome(symbol, outcome_rr)

    @property
    def failopen(self) -> FailOpenMonitor:
        return self._failopen

    @property
    def drift(self) -> DriftMonitoringModule:
        return self._drift

    # ── Private helpers ───────────────────────────────────────────────────────

    def _record_bypass(
        self,
        inputs: GovernanceInput,
        reason: str,
        latency_ms: float = 0.0,
        cycle: int = 0,
    ) -> GovernanceDecision:
        """
        Unified bypass path.  Records the bypass in both FailOpenMonitor and
        DriftMonitoringModule, then emits the standard INFO log.
        """
        self._failopen.record(was_bypass=True)
        self._drift.record(decision="bypass", confidence=0, is_bypass=True)

        self._tracker.record(EvaluationRecord(
            cycle=cycle,
            symbol=inputs.symbol,
            decision="approve",  # Bypass defaults to approve in the evaluation record
            confidence=0,
            risk_flag=False,
            forced_demoted=False,
            trade_executed=True,
            bypassed=True,
        ))

        logger.info(
            "[LLM_GOVERNANCE_AUDIT] BYPASS | %s | Reason: %s | "
            "FailOpen: %d/%d bypasses | Deterministic logic continues.",
            inputs.symbol, reason,
            self._failopen.bypass_count_in_window,
            FAILOPEN_MAX_BYPASSES,
        )

        return GovernanceDecision(
            decision="approve",
            confidence=0,
            reason=reason,
            risk_flag=False,
            latency_ms=latency_ms,
            bypassed=True,
            bypass_reason=reason,
        )

    @staticmethod
    def _bypass(reason: str, latency_ms: float = 0.0) -> GovernanceDecision:
        """
        Static lightweight bypass (used only for the ENABLE_LLM_GOVERNANCE=False
        fast-exit path; no drift/failopen accounting needed since the module is off).
        """
        logger.debug(
            "[LLM_GOVERNANCE_AUDIT] BYPASS | Reason: %s | Module disabled.",
            reason,
        )
        return GovernanceDecision(
            decision="approve",
            confidence=0,
            reason=reason,
            risk_flag=False,
            latency_ms=latency_ms,
            bypassed=True,
            bypass_reason=reason,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Module-level singleton  (imported by main.py)
# ─────────────────────────────────────────────────────────────────────────────
llm_governance_client = LLMGovernanceClient()
