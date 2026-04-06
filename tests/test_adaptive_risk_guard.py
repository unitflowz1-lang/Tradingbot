import pathlib
import sys
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src.runtime.risk.policy_engine import AdaptiveRiskGuard


def _signal(score=50.0, trade_tier="TIER_C", conviction=None, size_multiplier=1.0):
    predictive = {}
    if conviction is not None:
        predictive["Conviction"] = conviction
    return SimpleNamespace(
        adaptive_score=score,
        trade_tier=trade_tier,
        predictive_attribution=predictive,
        size_multiplier=size_multiplier,
    )


def test_blocks_non_aplus_setup_when_exposure_is_elevated():
    guard = AdaptiveRiskGuard(base_limit_pct=2.0, hard_cap_pct=5.0, excellent_score_threshold=60.0)

    result = guard.evaluate_signal(
        signal=_signal(score=58.0, trade_tier="TIER_C"),
        total_open_risk_pct=2.73,
        proposed_trade_risk_pct=0.35,
        latest_decision=None,
    )

    assert result.allow_trade is False
    assert result.reason == "non_aplus_blocked"


def test_excellent_score_triggers_high_conviction_override():
    guard = AdaptiveRiskGuard(base_limit_pct=2.0, hard_cap_pct=5.0, admission_buffer_pct=0.75, excellent_score_threshold=60.0)

    result = guard.evaluate_signal(
        signal=_signal(score=64.0, trade_tier="TIER_C"),
        total_open_risk_pct=2.73,
        proposed_trade_risk_pct=0.35,
        latest_decision=None,
    )

    assert result.allow_trade is True
    assert result.high_conviction_override is True
    assert result.effective_limit_pct == 2.75
    assert result.reason == "risk_reduction_mode"
    assert result.size_multiplier == 0.5


def test_hard_cap_still_blocks_trade():
    guard = AdaptiveRiskGuard(base_limit_pct=2.0, hard_cap_pct=5.0, excellent_score_threshold=60.0)

    result = guard.evaluate_signal(
        signal=_signal(score=82.0, trade_tier="TIER_A", conviction="MAX"),
        total_open_risk_pct=4.9,
        proposed_trade_risk_pct=0.3,
        latest_decision=None,
    )

    assert result.allow_trade is False
    assert result.reason == "hard_cap_breached"


def test_defensive_preservation_keeps_reduction_floor():
    guard = AdaptiveRiskGuard(base_limit_pct=2.0, hard_cap_pct=5.0, excellent_score_threshold=60.0)
    latest_decision = SimpleNamespace(primary_action=SimpleNamespace(value="DEFENSIVE_PRESERVATION"))

    result = guard.evaluate_signal(
        signal=_signal(score=64.0, trade_tier="TIER_C"),
        total_open_risk_pct=2.3,
        proposed_trade_risk_pct=0.1,
        latest_decision=latest_decision,
    )

    assert result.allow_trade is True
    assert result.size_multiplier == 0.5
