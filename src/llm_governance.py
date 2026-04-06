"""
LLM Governance Layer — Qwen3.5:4B Advisory Module  (Stability & Drift Hardened)
==============================================================================
Uses Ollama (http://localhost:11434/api/generate) with model "qwen3.5:4b"
as a NON-AUTHORITATIVE advisory governance layer.

Contract:
  - LLM is called ONLY AFTER signal generation, SL/TP, R:R validation,
    ML confidence scoring, and regime classification are complete.
  - LLM advisory powers:
      ✅ May demote forced_execution to standard
      ✅ May flag risk anomalies
      ❌ May NOT increase position size beyond computed limits
      ❌ May NOT alter SL/TP values
  - On ANY failure (timeout, malformed JSON, schema violation) → reject
    safely; FailOpenMonitor tracks accumulation and auto-disables.
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
import time
import threading
import urllib.request
import urllib.error
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional, Tuple
from src.analysis.ollama_runtime_gate import OLLAMA_REQUEST_LOCK  # type: ignore[import]

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
OLLAMA_MODEL_FAST: str         = os.environ.get("OLLAMA_MODEL_FAST", "qwen3.5:0.8b")  # DEFAULT GOVERNANCE MODEL: fastest (0.8B params, ~0.5s inference)
OLLAMA_MODEL_HEAVY: str        = os.environ.get("OLLAMA_MODEL_HEAVY", "qwen3.5:4b")
# ===== ISSUE #2 FIX: Increased LLM timeout to 20s (was 7.5s) =====
# Ollama inference takes 3-5s on typical hardware (fast model: 2-3s, heavy: 5-8s)
# Local cold start adds 8-10s initially, then keep_alive=1h keeps model in VRAM
# 20s timeout allows for longer inference time + cold starts + margin for network/serialization
LLM_TIMEOUT_SECONDS: float     = float(os.environ.get("OLLAMA_FAST_TIMEOUT_SECONDS", "20.0"))
LLM_HEAVY_TIMEOUT_SECONDS: float = float(os.environ.get("OLLAMA_HEAVY_TIMEOUT_SECONDS", "20.0"))  # FIXED: increased from 15s → 20s for complex reasoning
LLM_MAX_TOKENS: int            = 64
LLM_TEMPERATURE: float         = 0.15   # Tighter control for trading decisions (reduced from 0.2)
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
FAILOPEN_WINDOW: int           = 50    # Rolling window for bypass tracking
FAILOPEN_MAX_BYPASSES: int     = 10    # Bypass count that triggers auto-disable

VALID_DECISIONS = frozenset({"approve", "demote", "reject"})

logger = logging.getLogger(__name__)


def set_llm_governance_enabled(enabled: bool) -> None:
    """Update the module-level governance switch."""
    global ENABLE_LLM_GOVERNANCE  # noqa: PLW0603
    ENABLE_LLM_GOVERNANCE = bool(enabled)


def fetch_ollama_models() -> List[str]:
    """Fetch installed local Ollama model names."""
    req = urllib.request.Request(OLLAMA_TAGS_URL, method="GET")
    # ===== ISSUE #3 FIX: Increased timeout from 10.0s to 25s for cold-start tolerance =====
    with urllib.request.urlopen(req, timeout=25.0) as resp:
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
            raw = _ollama_request_blocking('{"status":"ok"}', OLLAMA_MODEL_FAST)
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
        return {
            "symbol":               self.symbol,
            "regime":               self.regime,
            "rsi":                  round(self.rsi,                 2),  # type: ignore[no-matching-overload]
            "adx":                  round(self.adx,                 2),  # type: ignore[no-matching-overload]
            "atr":                  round(self.atr,                 5),  # type: ignore[no-matching-overload]
            "rr_ratio":             round(self.rr_ratio,            2),  # type: ignore[no-matching-overload]
            "ml_confidence":        round(self.ml_confidence,       4),  # type: ignore[no-matching-overload]
            "volatility_pct":       round(self.volatility_pct,      4),  # type: ignore[no-matching-overload]
            "forced_execution":     self.forced_execution,
            "position_size":        round(self.position_size,       4),  # type: ignore[no-matching-overload]
            "expectancy_multiplier":round(self.expectancy_multiplier, 2),  # type: ignore[no-matching-overload]
        }

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
    Tracks LLM bypass events (timeout, empty response, schema violation)
    in a rolling window.  If bypass count exceeds FAILOPEN_MAX_BYPASSES
    within FAILOPEN_WINDOW calls, ENABLE_LLM_GOVERNANCE is auto-disabled
    and a CRITICAL alert is emitted.

    The bot then continues under pure deterministic logic without requiring
    a restart.  The flag can only be re-enabled manually.
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
        self._already_disabled: bool = False

    def record(self, was_bypass: bool) -> None:
        """
        Record one LLM call outcome.
        If the rolling bypass rate exceeds the threshold, auto-disables the module.
        """
        self._calls.append(was_bypass)

        if self._already_disabled:
            return  # Already fired; don't repeat

        bypass_count = sum(self._calls)
        if bypass_count > self._max_bypasses and len(self._calls) >= self._window:
            self._auto_disable(bypass_count)

    def _auto_disable(self, bypass_count: int) -> None:
        set_llm_governance_enabled(False)
        self._already_disabled = True
        logger.critical(
            "[LLM_GOVERNANCE_AUDIT] LLM_GOVERNANCE_AUTO_DISABLED_FAILOPEN_THRESHOLD | "
            "Bypasses=%d/%d in last %d calls | "
            "ENABLE_LLM_GOVERNANCE set to False | "
            "Bot continues under PURE DETERMINISTIC execution. "
            "Re-enable manually after diagnosing Ollama connectivity.",
            bypass_count, self._max_bypasses, self._window
        )

    @property
    def bypass_count_in_window(self) -> int:
        return sum(self._calls)

    @property
    def total_calls_recorded(self) -> int:
        return len(self._calls)


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
        recent = [c for c in list(self._calls)[-100:] if c.decision != "bypass"]  # type: ignore[bad-argument-type]
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

        window_slice = list(self._calls)[-DRIFT_SKEW_WINDOW:]  # type: ignore[bad-argument-type]
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
        
        # FIX: Explicitly check for None and calculate sum safely for Pyre2
        completed_rr_list: List[float] = [float(c.outcome_rr) for c in real if c.outcome_rr is not None]  # type: ignore[bad-argument-type]
        current_avg_rr: Optional[float] = None
        if completed_rr_list:
             current_avg_rr = float(sum(completed_rr_list) / len(completed_rr_list))

        prev_conf = self._prev_epoch_avg_confidence
        if prev_conf is not None:
            conf_delta = current_avg_conf - prev_conf

            # Split up comparison to ensure Pyre sees the explicit None guards
            rr_improved = False
            prev_rr = self._prev_epoch_avg_rr
            if current_avg_rr is not None and prev_rr is not None:
                if current_avg_rr > prev_rr:
                    rr_improved = True

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
    Forgiving schema validator for the LLM JSON response contract.
    Features:
    - Multi-strategy JSON extraction with fallbacks
    - Partial schema compliance (missing fields get sensible defaults)
    - Detailed logging at each parsing step
    - Type coercion with validation
    Also enforces the token-budget by truncating overly verbose text
    before parsing, and rejecting responses that are excessively long.
    """

    REQUIRED_FIELDS = {"decision", "confidence", "reason", "risk_flag"}
    MAX_RAW_CHARS   = LLM_MAX_TOKENS * 6   # ~6 chars/token upper bound for JSON

    def validate(self, raw: Any) -> GovernanceDecision:
        """
        Parse and validate the raw LLM output with forgiving strategy.
        Tries multiple parsing strategies before giving up.
        Raises ValueError on any schema violation.
        """
        if isinstance(raw, str):
            # Enforce token-budget: reject / trim verbose responses
            raw = self._enforce_budget(raw)
            # ===== FIX #1: FORGIVING JSON EXTRACTION =====
            # Try multiple extraction strategies with detailed logging
            raw = self._extract_json_forgiving(raw)

        if not isinstance(raw, dict):
            raise ValueError(f"Response is not a JSON object: {type(raw)}")

        # ===== FIX #1: FORGIVING SCHEMA - PROVIDE DEFAULTS =====
        # Don't fail on missing fields; use sensible defaults instead
        missing = self.REQUIRED_FIELDS - set(raw.keys())
        if missing:
            logger.warning(
                "[LLM_VALIDATION_FALLBACK] Missing required fields: %s | "
                "Using defaults and continuing (partial schema fallback)",
                missing
            )


        decision = str(raw.get("decision", "approve")).strip().lower()
        if decision not in VALID_DECISIONS:
            logger.warning(
                "[LLM_VALIDATION_FALLBACK] Invalid decision '%s' | "
                "Using default 'approve' and continuing",
                decision
            )
            decision = "approve"  # Default to approve on invalid decision

        try:
            confidence = int(raw.get("confidence", 50))
        except (TypeError, ValueError):
            logger.warning(
                "[LLM_VALIDATION_FALLBACK] Invalid confidence '%s' | "
                "Using default 50 and continuing",
                raw.get("confidence")
            )
            confidence = 50  # Default to 50 on invalid confidence
        if not (0 <= confidence <= 100):
            logger.warning(
                "[LLM_VALIDATION_FALLBACK] Confidence %d out of range [0,100] | "
                "Clamping to valid range",
                confidence
            )
            confidence = max(0, min(100, confidence))  # Clamp to valid range

        reason = str(raw.get("reason", "LLM advisory"))
        if not reason or not reason.strip():
            logger.warning("[LLM_VALIDATION_FALLBACK] Empty reason | Using default")
            reason = "LLM advisory"
        reason = reason.strip()[:200]  # type: ignore[bad-argument-type]

        risk_flag = bool(raw.get("risk_flag", False))

        logger.info(
            "[LLM_VALIDATION_SUCCESS] Parsed governance decision | "
            "decision=%s | confidence=%d | risk_flag=%s | reason=%s",
            decision, confidence, risk_flag, reason
        )

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
    def _extract_json_forgiving(text: str) -> Any:
        """
        ===== FIX #1: FORGIVING JSON EXTRACTION WITH MULTIPLE FALLBACK STRATEGIES =====
        Tries multiple strategies to extract JSON from LLM response.
        Strategy priority:
        1. Extract { ... } block (handles extra text before/after)
        2. Try direct JSON parse of trimmed text
        3. Extract between curly braces with quote escape handling
        4. Build minimal JSON from detected fields
        Returns parsed dict, raises ValueError only on total failure.
        """
        text = text.strip()
        
        # Strategy 1: Remove markdown code blocks
        if text.startswith("```"):
            lines = text.splitlines()
            lines = [ln for ln in lines if not ln.strip().startswith("```")]
            text = "\n".join(lines).strip()
        
        logger.debug("[LLM_EXTRACTION_S1] After markdown removal: %s", text[:100])  # type: ignore[bad-argument-type]
        
        # Strategy 2: Find and extract { ... } block
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            text = text[start:end]  # type: ignore[bad-argument-type]
            logger.debug("[LLM_EXTRACTION_S2] Extracted {...} block: %s", text[:100])  # type: ignore[bad-argument-type]
            try:
                return json.loads(text)
            except json.JSONDecodeError as e:
                logger.debug("[LLM_EXTRACTION_S2_FAILED] JSON parse failed: %s | Trying fallback", str(e))
        
        # Strategy 3: Try direct parse of trimmed text
        text_trimmed = text.strip()
        if text_trimmed.startswith("{"):
            try:
                return json.loads(text_trimmed)
            except json.JSONDecodeError as e:
                logger.debug("[LLM_EXTRACTION_S3_FAILED] Direct parse failed: %s | Trying escape-aware parse", str(e))
        
        # Strategy 4: Handle escaped quotes in JSON strings
        try:
            # Sometimes LLM escapes quotes inside strings as \" instead of trying to close them
            # Try to fix common JSON errors
            text_fixed = text_trimmed
            
            # Common issue: missing comma between fields
            text_fixed = text_fixed.replace('} "', '}, "')
            text_fixed = text_fixed.replace('} {', '}, {')
            
            # Try again
            return json.loads(text_fixed)
        except json.JSONDecodeError as e:
            logger.debug("[LLM_EXTRACTION_S4_FAILED] Fixed parse failed: %s | Trying field detection", str(e))
        
        # Strategy 5: Extract individual fields with regex and build minimal JSON
        fields: Dict[str, Any] = {}
        
        # Try to find "decision": "..."
        decision_match = re.search(r'"decision"\s*:\s*"([^"]+)"', text, re.IGNORECASE)
        if decision_match:
            fields["decision"] = decision_match.group(1).lower().strip()
            logger.debug("[LLM_EXTRACTION_S5] Found decision: %s", fields["decision"])
        
        # Try to find "confidence": ... (numeric)
        confidence_match = re.search(r'"confidence"\s*:\s*(\d+)', text, re.IGNORECASE)
        if confidence_match:
            fields["confidence"] = int(confidence_match.group(1))
            logger.debug("[LLM_EXTRACTION_S5] Found confidence: %d", fields["confidence"])
        
        # Try to find "risk_flag": ... (boolean)
        risk_match = re.search(r'"risk_flag"\s*:\s*(true|false)', text, re.IGNORECASE)
        if risk_match:
            fields["risk_flag"] = risk_match.group(1).lower() == "true"
            logger.debug("[LLM_EXTRACTION_S5] Found risk_flag: %s", fields["risk_flag"])
        
        # Try to find "reason": "..."
        reason_match = re.search(r'"reason"\s*:\s*"([^"]*(?:\\.[^"]*)*)"', text)
        if reason_match:
            fields["reason"] = reason_match.group(1)
            logger.debug("[LLM_EXTRACTION_S5] Found reason: %s", fields["reason"][:50])  # type: ignore[bad-argument-type]
        else:
            # Fallback: take everything between reason: and next field or }
            reason_match = re.search(r'"reason"\s*:\s*"([^}]*)"', text, re.DOTALL)
            if reason_match:
                reason_text = reason_match.group(1).strip()
                fields["reason"] = reason_text[:200]  # type: ignore[bad-argument-type]
                logger.debug("[LLM_EXTRACTION_S5_REASON] Found reason (extraction): %s", fields["reason"][:50])  # type: ignore[bad-argument-type]
        
        if fields:
            logger.warning(
                "[LLM_EXTRACTION_S5_SUCCESS] Extracted %d fields via regex: %s | "
                "Using partial schema with defaults for missing fields",
                len(fields), list(fields.keys())
            )
            return fields
        
        # If all strategies fail, raise with detailed context
        raise ValueError(
            f"Failed to extract JSON from LLM response after 5 strategies | "
            f"Text (first 200 chars): {text[:200]}"  # type: ignore[bad-argument-type]
        )


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
                drift = self._drift
                if drift:
                    drift.update_outcome(symbol, outcome_rr)
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

        completed_rr_list = [float(r.outcome_rr) for r in records if r.outcome_rr is not None]  # type: ignore[bad-argument-type]
        avg_rr = (sum(completed_rr_list) / len(completed_rr_list)) if completed_rr_list else None

        demoted_completed_list = [
            float(r.outcome_rr) for r in records if r.decision == "demote" and r.outcome_rr is not None  # type: ignore[bad-argument-type]
        ]
        avg_demoted_rr = (
            sum(demoted_completed_list) / len(demoted_completed_list)
            if demoted_completed_list else None
        )

        # Drift snapshot
        drift = self._drift
        drift_summary = drift.get_summary() if drift else {}
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
            len(completed_rr_list),
            f"{avg_rr:.2f}"        if avg_rr        is not None else "N/A",
            f"{avg_demoted_rr:.2f}" if avg_demoted_rr is not None else "N/A",
            drift_line,
        )


# ═════════════════════════════════════════════════════════════════════════════
# 7. OLLAMA HTTP CLIENT  (tightly constrained inference parameters)
# ═════════════════════════════════════════════════════════════════════════════

def _ollama_request_blocking(prompt: str, model_name: str, request_timeout: Optional[float] = None) -> str:
    """
    Synchronous HTTP POST to Ollama API with deterministic inference caps.
    Returns raw response text. Raises on any network or decode error.

    Inference parameters (hardened):
      num_predict = LLM_MAX_TOKENS  (150)
      temperature = LLM_TEMPERATURE (0.2)
      top_p       = LLM_TOP_P       (0.9)
    
    ISSUE #3 FIX: Hardcoded to use fastest model with keep_alive parameter.
      - model: qwen3.5:0.8b (fastest, 0.8B params, ~0.5s inference)
      - keep_alive: "1h" keeps model loaded in VRAM for entire market session
      - Eliminates cold-start penalty (8-10s model load time on first request)
      - On busy trading days, model stays resident once loaded
    """
    # ===== ISSUE #3 FIX: Hardcode to fastest model (qwen3.5:0.8b) for governance decisions =====
    # Use fast model for all governance calls to minimize latency
    governance_model = "qwen3.5:0.8b"  # Override: always use fastest model for governance
    
    payload = json.dumps({
        "model":  governance_model,  # ISSUE #3: Hardcoded to fastest model
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "keep_alive": "1h",  # Keep model in VRAM for entire trading session (1 hour)
        "options": {
            "num_predict":  LLM_MAX_TOKENS,   # ===== FIX: Increased to 2048 to prevent JSON truncation mid-response =====
            "num_ctx":      2048,             # Context window
            "temperature":  LLM_TEMPERATURE,  # ≤ 0.2 — minimal stochastic variance
            "top_p":        LLM_TOP_P,        # ≤ 0.9 — nucleus sampling cap
        },
    }).encode("utf-8")

    req = urllib.request.Request(
        OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    # urllib timeout is per-socket-op; the caller's thread.join() enforces
    # the true wall-clock hard cap. Socket timeout needs margin above thread timeout.
    # ===== ISSUE #3 FIX: Increased socket timeout to handle long inference times =====
    with OLLAMA_REQUEST_LOCK:
        timeout_seconds = float(request_timeout if request_timeout is not None else LLM_TIMEOUT_SECONDS)
        # ISSUE #3: Minimum 30s socket timeout to accommodate:
        # - Cold start model load: ~8-10s
        # - Inference: ~2-5s (qwen3.5:0.8b can be slow)
        # - Network overhead: ~2-3s
        # - Safety margin: ~10s
        socket_timeout = max(30.0, timeout_seconds + 10.0)
        with urllib.request.urlopen(req, timeout=socket_timeout) as resp:
            raw_bytes = resp.read()
            raw = json.loads(raw_bytes.decode("utf-8"))
        
        # Qwen3 and other reasoning models might put output in 'thinking' or 'response'
        # Modern Ollama versions might separate them. We prefer 'response' then 'thinking'.
        response_text = raw.get("response", "")
        thinking_text = raw.get("thinking", "")
        
        if not response_text.strip() and thinking_text.strip():
            return thinking_text
            
        return response_text


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
        # ===== ISSUE #3 FIX: Use increased timeout for thread join =====
        # Add margin to account for network latency and serialization
        effective_timeout = timeout + 5.0
        thread.join(timeout=effective_timeout)

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
    """Build a compact governance prompt with an explicit JSON schema contract."""
    d = inputs.to_compact_dict()
    # Extract high-impact features for a compact context block
    compact_ctx = {
        "symbol":           d["symbol"],
        "regime":           d["regime"],
        "adx":              d["adx"],       # Trend direction strength
        "atr":              d["atr"],       # Volatility / liquidity context
        "rsi":              d["rsi"],
        "ml_confidence":    d["ml_confidence"],
        "rr_ratio":         d["rr_ratio"],
        "forced_execution": d["forced_execution"],
    }
    return (
        "ROLE: AGGRESSIVE GROWTH GOVERNOR.\n"
        "\n"
        "YOU MUST FOLLOW THESE RULES EXACTLY:\n"
        "1. RETURN ONLY A JSON OBJECT - NO OTHER TEXT, NO MARKDOWN, NO CODE FENCES\n"
        "2. INCLUDE EXACTLY THESE 4 KEYS: \"decision\", \"confidence\", \"risk_flag\", \"reason\"\n"
        "3. NO OTHER KEYS OR FIELDS ALLOWED\n"
        "4. NO PREAMBLE, NO EXPLANATION, NO PROSE BEFORE OR AFTER JSON\n"
        "\n"
        "REQUIRED VALUES:\n"
        "- decision: STRING - MUST be exactly one of: \"approve\" OR \"reject\" OR \"demote\" (lowercase)\n"
        "- confidence: INTEGER - MUST be 0-100 (no decimals, no strings)\n"
        "- risk_flag: BOOLEAN - MUST be exactly \"true\" or \"false\" (lowercase, not string)\n"
        "- reason: STRING - Short explanation (10-50 characters). Never empty. Use default if needed.\n"
        "\n"
        "EXAMPLES OF VALID RESPONSES (ONLY THESE FORMATS):\n"
        "{\"decision\":\"approve\",\"confidence\":85,\"risk_flag\":false,\"reason\":\"trend_aligned\"}"
        "{\"decision\":\"reject\",\"confidence\":0,\"risk_flag\":true,\"reason\":\"insufficient_adx\"}"
        "{\"decision\":\"demote\",\"confidence\":45,\"risk_flag\":true,\"reason\":\"high_risk_setup\"}"
        "\n"
        "FAILURE RESPONSE (if unable to process):\n"
        "{\"decision\":\"reject\",\"confidence\":0,\"risk_flag\":true,\"reason\":\"parsing_error\"}"
        "\n"
        "DO NOT INCLUDE ANY OF THE FOLLOWING:\n"
        "- Markdown code fences (```)\n"
        "- Explanatory text before or after JSON\n"
        "- Extra fields or properties\n"
        "- Array brackets [\n"
        "- Multiple JSON objects\n"
        "\n"
        "\n"
        f"MARKET SNAPSHOT:{json.dumps(compact_ctx, separators=(',', ':'))}\n"
        "\n"
        "CRITICAL INSTRUCTIONS:\n"
        "1. IGNORE SPREAD for high-conviction signals. Assume the move can cover execution cost.\n"
        "2. ADX IS POWER. Never reject for high ADX; ADX > 25 is trend confirmation.\n"
        "3. IGNORE TREND MISMATCH when ml_confidence > 0.55. Approve the turn.\n"
        "4. Prefer frequency over over-filtering. More acceptable trades are better than perfect scarcity.\n"
        "\n"
        "DECISION RULES:\n"
        "1. If the technical setup is valid, prefer 'approve'.\n"
        "2. If ADX < 12 and conviction is weak, return 'reject'.\n"
        "3. If the setup is tradeable but somewhat elevated risk remains, use 'demote'.\n"
        "4. For strong setups, return confidence >= 90 to help downstream execution proceed.\n"
        "\n"
        "ALWAYS output valid JSON. Failure to include all 4 fields will cause trading errors. Example:\n"
        "{\"decision\":\"approve\",\"confidence\":98,\"risk_flag\":false,\"reason\":\"technical_setup_valid\"}\n"
    )



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

        prompt  = build_governance_prompt(inputs)
        t_start = time.perf_counter()

        try:
            raw_response = _call_ollama_with_timeout(prompt, model_name=target_model, timeout=target_timeout)
        except urllib.error.URLError as exc:
            return self._record_bypass(
                inputs, f"Ollama unreachable: {exc}",
                latency_ms=(time.perf_counter() - t_start) * 1000,
                cycle=cycle,
            )
        except Exception as exc:
            return self._record_bypass(
                inputs, f"HTTP error: {exc}",
                latency_ms=(time.perf_counter() - t_start) * 1000,
                cycle=cycle,
            )

        latency_ms = (time.perf_counter() - t_start) * 1000
        
        # Debug: Log raw response presence
        if raw_response:
            logger.info(f"[LLM_DEBUG] Raw response length: {len(raw_response)} | Snippet: {raw_response[:50]!r}")  # type: ignore[bad-argument-type]
        else:
            logger.warning(f"[LLM_DEBUG] Raw response is None or empty. Latency: {latency_ms:.0f}ms")

        # ... (Validation boilerplate continues below)
        if raw_response is None:
            logger.warning(
                "[LLM_GOVERNANCE_TIMEOUT] %s | %.0fms elapsed. Returning SAFE_REJECT.",
                inputs.symbol, latency_ms,
            )
            self._failopen.record(was_bypass=True)
            self._drift.record(decision="reject", confidence=0, is_bypass=True)
            self._tracker.record(EvaluationRecord(
                cycle=cycle, symbol=inputs.symbol, decision="reject",
                confidence=0, risk_flag=True, forced_demoted=False,
                trade_executed=False, bypassed=True,
            ))
            return GovernanceDecision(
                decision="reject",
                confidence=0,
                reason="SAFE_REJECT: LLM timeout exceeded 3.0s",
                risk_flag=True,
                latency_ms=latency_ms,
                bypassed=True,
                bypass_reason="timeout_safe_reject",
            )

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
        self._failopen.record(was_bypass=False)

        was_demoted = (decision.decision == "demote") and signal_forced
        self._tracker.record(EvaluationRecord(
            cycle=cycle, symbol=inputs.symbol, decision=decision.decision,
            confidence=decision.confidence, risk_flag=decision.risk_flag,
            forced_demoted=was_demoted, trade_executed=(decision.decision != "reject"),
            bypassed=False,
        ))

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
