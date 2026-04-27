from pathlib import Path
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.monitoring.decision_matrix import (
    Action,
    DecisionMatrix,
    MetricsSnapshot,
    RiskLevel,
)
from src.models import Direction, TradingSignal


def test_price_action_score_promotes_aggressive_engagement_and_boosts_sizing():
    matrix = DecisionMatrix()
    metrics = MetricsSnapshot(
        price_action_score=90.0,
        pa_type="MATH_REJECTION",
        macro_risk=0.0,
        macro_risk_reason="No_Macro_Risk",
    )

    result = matrix.evaluate(metrics)
    multiplier = matrix.get_position_multiplier(1.0, result)

    assert result.risk_level == RiskLevel.OPTIMAL
    assert result.primary_action == Action.AGGRESSIVE_ENGAGEMENT
    assert result.conviction_multiplier == 1.25
    assert multiplier == 2.0


def test_price_action_sniper_rule_allows_half_size_contrarian_scalp_under_macro_warning():
    matrix = DecisionMatrix()
    metrics = MetricsSnapshot(
        price_action_score=87.0,
        pa_type="MATH_REJECTION",
        macro_risk=0.30,
        macro_risk_reason="Bearish_Sentiment_Warning",
    )

    result = matrix.evaluate(metrics)
    multiplier = matrix.get_position_multiplier(1.0, result)

    assert result.primary_action == Action.MAINTAIN_CURRENT
    assert result.contrarian_scalp is True
    assert result.technical_only_forced_relief is True
    assert multiplier == 0.5


def test_ingest_signal_context_reads_price_action_fields_from_signal_like_object():
    matrix = DecisionMatrix()
    metrics = MetricsSnapshot()
    signal = type(
        "Signal",
        (),
        {
            "price_action_score": 92.0,
            "pa_type": "MATH_REJECTION",
            "price_action_direction": "LONG",
        },
    )()

    hydrated = matrix.ingest_signal_context(metrics=metrics, signal=signal)

    assert hydrated.price_action_score == 92.0
    assert hydrated.pa_type == "MATH_REJECTION"
    assert hydrated.price_action_direction == "LONG"


def test_ingest_signal_context_supports_direct_scalar_handoff():
    matrix = DecisionMatrix()
    metrics = MetricsSnapshot()

    hydrated = matrix.ingest_signal_context(
        metrics=metrics,
        price_action_score=88.0,
        pa_type="MATH_REJECTION",
        direction="SHORT",
    )

    assert hydrated.price_action_score == 88.0
    assert hydrated.pa_type == "MATH_REJECTION"
    assert hydrated.price_action_direction == "SHORT"


def test_trading_signal_defaults_keep_legacy_strategies_backward_compatible():
    signal = TradingSignal(
        symbol="EUR/USD",
        direction=Direction.LONG,
        entry_price=1.1000,
        stop_loss=1.0950,
        take_profit=1.1100,
        position_size=0.10,
        confidence=0.75,
        reasoning="legacy strategy",
        timestamp=datetime.now(timezone.utc),
    )

    assert signal.price_action_score == 0.0
    assert signal.pa_type == "NONE"
