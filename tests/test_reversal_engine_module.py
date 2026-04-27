import pathlib
import sys

import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src.trading.reversal_engine import (
    MarketAnalyzer,
    ReversalEngine,
    ReversalExitManager,
    CooldownManager,
    MockSRH,
    ReversalConfig,
)
from src.trading.reversal_engine_integration import (
    RealSRHAdapter,
    ReversalExecutionPipeline,
)


def _base_market_df(rows: int = 40) -> pd.DataFrame:
    data = {
        "open": [1.1000 + i * 0.0001 for i in range(rows)],
        "high": [1.1004 + i * 0.0001 for i in range(rows)],
        "low": [1.0996 + i * 0.0001 for i in range(rows)],
        "close": [1.1001 + i * 0.0001 for i in range(rows)],
        "tick_volume": [100] * rows,
        "atr": [0.0008] * rows,
        "rsi": [50.0] * rows,
        "adx": [18.0] * rows,
    }
    return pd.DataFrame(data)


def _feature_ready_df(rows: int = 20) -> pd.DataFrame:
    df = _base_market_df(rows)
    feature_defaults = {
        "bull_pin": False,
        "bear_pin": False,
        "bull_engulfing": False,
        "bear_engulfing": False,
        "ema_50": 1.1000,
        "rsi_delta": 0.0,
        "climax": False,
        "liq_sweep_high": False,
        "liq_sweep_low": False,
        "bull_bos": False,
        "bear_bos": False,
        "bull_div": False,
        "bear_div": False,
        "bull_exhaustion": False,
        "bear_exhaustion": False,
    }
    for col, default in feature_defaults.items():
        df[col] = default
    return df


class StableSRH(MockSRH):
    def __init__(self, regime="RANGING", htf="NEUTRAL", session="LONDON_NY_OVERLAP"):
        self._regime = regime
        self._htf = htf
        self._session = session

    def get_regime(self, symbol: str) -> str:
        return self._regime

    def get_htf_trend(self, symbol: str) -> str:
        return self._htf

    def get_session(self, symbol: str) -> str:
        return self._session

    def get_spread_metrics(self, symbol: str):
        return 0.2, 0.2


def test_market_analyzer_zero_lookahead_ema_is_shifted():
    df = _base_market_df()
    featured = MarketAnalyzer.calculate_features(df)

    assert pd.isna(featured.iloc[0]["ema_50"])
    assert featured.iloc[-1]["ema_50"] == df["close"].ewm(span=50, adjust=False).mean().shift(1).iloc[-1]


def test_market_analyzer_uses_timeframe_specific_divergence_threshold():
    df = _base_market_df()
    idx = df.index[-1]
    prior_window = df.index[-15:-1]
    df.loc[prior_window, "low"] = 1.1000
    df.loc[idx, "low"] = 1.0990
    df.loc[prior_window, "rsi"] = 30.0
    df.loc[idx, "rsi"] = 35.8

    m5 = MarketAnalyzer.calculate_features(df, symbol="EUR/USD", timeframe="M5")
    m15 = MarketAnalyzer.calculate_features(df, symbol="EUR/USD", timeframe="M15")

    assert bool(m5.iloc[-1]["bull_div"]) is False
    assert bool(m15.iloc[-1]["bull_div"]) is True


def test_market_analyzer_uses_symbol_specific_stretch_multiplier():
    rows = 40
    df = pd.DataFrame({
        "open": [1.1000] * rows,
        "high": [1.1002] * rows,
        "low": [1.0998] * rows,
        "close": [1.1000] * rows,
        "tick_volume": [100] * rows,
        "atr": [0.0010] * rows,
        "rsi": [60.0] * rows,
        "adx": [18.0] * rows,
    })
    idx = df.index[-1]
    df.loc[idx, "high"] = 1.1027

    eurusd = MarketAnalyzer.calculate_features(df, symbol="EUR/USD", timeframe="M5")
    gbpjpy = MarketAnalyzer.calculate_features(df, symbol="GBP/JPY", timeframe="M5")

    assert bool(eurusd.iloc[-1]["bear_exhaustion"]) is True
    assert bool(gbpjpy.iloc[-1]["bear_exhaustion"]) is False


def test_engine_auto_calculates_missing_features():
    engine = ReversalEngine(srh=StableSRH())
    decision = engine.evaluate_symbol("EUR/USD", _base_market_df())

    assert decision.action == "NO_TRADE"
    assert decision.reason


def test_engine_applies_liquidity_sweep_bonus_and_reason():
    df = _feature_ready_df()
    latest = df.index[-1]
    df.loc[latest, "bear_div"] = True
    df.loc[latest, "bear_exhaustion"] = True
    df.loc[latest, "bear_bos"] = True
    df.loc[latest, "bear_pin"] = True
    df.loc[latest, "rsi_delta"] = -4.5
    df.loc[latest, "liq_sweep_high"] = True
    df.loc[latest, "rsi"] = 79.0

    engine = ReversalEngine(srh=StableSRH(regime="RANGING"))
    decision = engine.evaluate_symbol("EUR/USD", df)

    assert decision.action == "SELL"
    assert decision.reversal_score == 0.978
    assert decision.reason == "BearDiv+BearExhaustion+Bear_BOS+Bear_PA+LiqSweep"
    assert decision.entry_type == "aggressive"


def test_engine_uses_strict_aggressive_threshold():
    df = _feature_ready_df()
    latest = df.index[-1]
    df.loc[latest, "bear_div"] = True
    df.loc[latest, "bear_exhaustion"] = True
    df.loc[latest, "bear_bos"] = True
    df.loc[latest, "bear_pin"] = True
    df.loc[latest, "rsi_delta"] = -4.0

    engine = ReversalEngine(srh=StableSRH(regime="RANGING"))
    decision = engine.evaluate_symbol("EUR/USD", df)

    assert decision.action == "SELL"
    assert decision.reversal_score == 0.85
    assert decision.entry_type == "aggressive"

    df.loc[latest, "bear_bos"] = False
    df.loc[latest, "bear_pin"] = False
    df.loc[latest, "climax"] = True
    decision = engine.evaluate_symbol("GBP/USD", df)

    assert decision.action == "SELL"
    assert decision.reversal_score == 0.7
    assert decision.entry_type == "conservative"


def test_engine_blocks_conflicted_market():
    df = _feature_ready_df()
    latest = df.index[-1]
    for col in ["bear_div", "bear_exhaustion", "bear_bos", "bull_div", "bull_exhaustion", "bull_bos"]:
        df.loc[latest, col] = True
    df.loc[latest, "rsi_delta"] = 4.0

    engine = ReversalEngine(srh=StableSRH(regime="RANGING"))
    decision = engine.evaluate_symbol("EUR/USD", df)

    assert decision.action == "NO_TRADE"
    assert decision.reason == "Conflicting Market Signals"


def test_market_analyzer_raises_on_missing_required_columns():
    df = pd.DataFrame({"open": [1.0], "high": [1.1], "low": [0.9], "close": [1.0]})

    try:
        MarketAnalyzer.calculate_features(df)
        assert False, "Expected ValueError for missing required columns"
    except ValueError as exc:
        assert "missing required columns" in str(exc)


def test_engine_penalizes_low_win_rate_signatures_without_killing_elite_setup():
    df = _feature_ready_df()
    latest = df.index[-1]
    df.loc[latest, "bear_div"] = True
    df.loc[latest, "bear_exhaustion"] = True
    df.loc[latest, "bear_bos"] = True
    df.loc[latest, "bear_pin"] = True
    df.loc[latest, "rsi_delta"] = -4.0

    engine = ReversalEngine(srh=StableSRH(regime="RANGING"))
    signature = "BearDiv+BearExhaustion+Bear_BOS+Bear_PA"
    for _ in range(3):
        engine.record_setup_outcome(signature, won=True)
    for _ in range(5):
        engine.record_setup_outcome(signature, won=False)

    decision = engine.evaluate_symbol("EUR/USD", df)

    assert decision.action == "SELL"
    assert decision.reversal_score == 0.765
    assert decision.entry_type == "aggressive"


def test_exit_priority_prefers_partial_before_break_even():
    df = _feature_ready_df()
    latest = df.index[-1]
    df.loc[latest, "close"] = 1.1050

    exit_decision = ReversalExitManager.evaluate_exit(
        symbol="EUR/USD",
        action="BUY",
        entry_price=1.1000,
        entry_atr=0.0010,
        bars_in_trade=3,
        unrealized_r=1.6,
        current_df=df,
        partial_taken=False,
        sl_moved=False,
    )

    assert exit_decision.action == "CLOSE_PARTIAL_50"
    assert exit_decision.reason == "1.0R_Target"


def test_exit_rr_decay_forces_close_when_progress_is_too_slow():
    df = _feature_ready_df()
    exit_decision = ReversalExitManager.evaluate_exit(
        symbol="EUR/USD",
        action="BUY",
        entry_price=1.1000,
        entry_atr=0.0010,
        bars_in_trade=9,
        unrealized_r=0.20,
        current_df=df,
        partial_taken=True,
        sl_moved=False,
        config=ReversalConfig(),
    )

    assert exit_decision.action == "CLOSE_FULL"
    assert exit_decision.reason == "RR_Decay_Failure"


def test_exit_structural_invalidation_uses_entry_wick_level():
    df = _feature_ready_df()
    latest = df.index[-1]
    df.loc[latest, "close"] = 1.0984

    exit_decision = ReversalExitManager.evaluate_exit(
        symbol="EUR/USD",
        action="BUY",
        entry_price=1.1000,
        entry_atr=0.0020,
        bars_in_trade=2,
        unrealized_r=-0.4,
        current_df=df,
        partial_taken=False,
        sl_moved=False,
        config=ReversalConfig(),
        entry_invalidation_price=1.0985,
    )

    assert exit_decision.action == "CLOSE_FULL"
    assert exit_decision.reason == "Structural_Failure"


def test_execution_pipeline_records_cooldown_on_trade():
    pipeline = ReversalExecutionPipeline(srh_adapter=RealSRHAdapter())
    decision = ReversalEngine(srh=StableSRH(regime="RANGING")).evaluate_symbol(
        "EUR/USD",
        _feature_ready_df().assign(
            bear_div=False,
            bear_exhaustion=False,
            bear_bos=False,
            bear_pin=False,
            bull_div=True,
            bull_exhaustion=True,
            bull_bos=True,
            bull_pin=True,
            rsi_delta=4.0,
            rsi=20.0,
        ),
    )

    trade = pipeline.execute_reversal(
        symbol="EUR/USD",
        decision=decision,
        entry_price=1.1000,
        atr=0.0010,
        current_index=19,
    )

    assert trade is not None
    assert pipeline.cooldown_mgr.is_cooling_down("EUR/USD", 20)
