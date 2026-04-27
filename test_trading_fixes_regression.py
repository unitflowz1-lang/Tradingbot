from datetime import datetime, timezone
from types import SimpleNamespace

import numpy as np

from src.analysis.adaptive_signal_scoring import AdaptiveSignalFilterer
from src.analysis.llm_macro_monitor import MacroRiskCache
from src.analysis.market_regime_detector import MarketRegimeDetector, TradingSession
from src.analysis.ml_model import PriceMovementPredictor
from src.analysis.technical_indicators import TechnicalIndicators
from src.models import MarketData
from src.monitoring.decision_matrix import Action, DecisionMatrix, MetricsSnapshot
from src.strategies.trend_strategy import SimpleTrendStrategy


def _bars(symbol: str = "EUR/USD", count: int = 30):
    bars = []
    base = 1.1000
    for i in range(count):
        close = base + (i * 0.0005)
        bars.append(
            MarketData(
                symbol=symbol,
                timestamp=datetime(2026, 3, 23, i % 24, 0, tzinfo=timezone.utc),
                open=close - 0.0002,
                high=close + 0.0004,
                low=close - 0.0004,
                close=close,
                volume=100 + i,
                bid=close - 0.0001,
                ask=close + 0.0001,
                spread=0.0002,
            )
        )
    return bars


def test_market_regime_tokyo_adx_floor_is_relaxed_but_not_disabled():
    detector = MarketRegimeDetector()
    thresholds = detector.get_dynamic_thresholds(TradingSession.TOKYO)
    assert thresholds["adx_weak"] == 10.0


def test_macro_cache_replace_clears_stale_news_reason(tmp_path):
    cache = MacroRiskCache(str(tmp_path / "macro_cache.json"))
    cache.update({"EUR/USD": 0.2}, reasons={"EUR/USD": "High_Impact_News_Pending"})
    cache.update({"EUR/USD": 0.0}, reasons={"EUR/USD": "No_Macro_Risk"})
    assert cache.get_penalty("EUR/USD") == 0.0
    assert cache.get_penalty_reason("EUR/USD") == "No_Macro_Risk"


def test_decision_matrix_does_not_stick_in_defensive_on_zero_macro_penalty():
    matrix = DecisionMatrix()
    action, severity = matrix.get_governance_state(
        MetricsSnapshot(macro_risk=0.0, macro_risk_reason="High_Impact_News_Pending")
    )
    assert action != Action.DEFENSIVE_PRESERVATION
    assert severity == 50.0


def test_ml_predictor_confidence_is_dynamic():
    class IdentityScaler:
        def transform(self, df):
            return df.to_numpy(dtype=float)

    class Model:
        def __init__(self, prob):
            self.prob = prob

        def predict_proba(self, X):
            return np.array([[1.0 - self.prob, self.prob]], dtype=float)

    predictor = PriceMovementPredictor("EUR/USD")
    predictor.is_trained = True
    predictor.scaler = IdentityScaler()
    predictor.model = Model(0.68)
    predictor.meta_model = Model(0.62)
    predictor.feature_names = ["f1", "f2"]
    predictor._prepare_latest_feature_row = lambda *args, **kwargs: __import__("pandas").DataFrame([[0.1, 0.2]], columns=["f1", "f2"])

    indicators = TechnicalIndicators(
        symbol="EUR/USD",
        timestamp=datetime.now(timezone.utc),
        rsi=64.0,
        atr=0.0014,
        adx=26.0,
    )
    _, conf_1, _ = predictor.predict_with_details(_bars(count=30), indicators, bars_since_last_loss=5)

    predictor.model = Model(0.54)
    predictor.meta_model = Model(0.51)
    _, conf_2, _ = predictor.predict_with_details(_bars(count=30), indicators, bars_since_last_loss=1)

    assert conf_1 != conf_2
    assert conf_1 > conf_2


def test_trend_filter_reports_accuracy_gate_not_fake_adx_reason():
    strategy = SimpleTrendStrategy.__new__(SimpleTrendStrategy)
    strategy.symbol = "EUR/USD"
    strategy.logger = SimpleNamespace(info=lambda *a, **k: None, critical=lambda *a, **k: None, debug=lambda *a, **k: None)
    strategy.entry_filters = {"adx_min": 22, "chop_max": 60.0}
    strategy.regime_detector = MarketRegimeDetector()
    strategy.ADX_FLOOR = 10.0
    strategy._last_accuracy_source = "weighted_bayesian_prior"

    indicators = SimpleNamespace(adx=28.7, ml_confidence=0.40, ml_accuracy=0.31, ml_accuracy_source="weighted_bayesian_prior", rsi=55.0)
    passed, reason = SimpleTrendStrategy._check_entry_filters(strategy, indicators, datetime(2026, 3, 23, 1, 0, tzinfo=timezone.utc))
    assert not passed
    assert "Effective Accuracy" in reason
