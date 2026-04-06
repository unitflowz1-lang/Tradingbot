"""Full integrity audit for the AI Forex Trading Bot.

This script performs a safe, offline structural audit:
- Parses `main.py` and `config/` for wiring checks
- Imports key modules directly to catch broken references
- Runs safe dummy-data integrity tests with mocked broker/MT5 objects
- Writes a human-readable report to `logs/audit_report.txt`
- Writes fix/patch metadata to `patches/`

It does not connect to MT5 and does not execute live trades.
"""

from __future__ import annotations

import ast
import importlib
import json
import logging
import os
import re
import shutil
import sys
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LOGS_DIR = ROOT / "logs"
PATCHES_DIR = ROOT / "patches"
REPORT_PATH = LOGS_DIR / "audit_report.txt"


class Color:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    RESET = "\033[0m"


@dataclass
class AuditResult:
    name: str
    passed: bool
    details: str
    fixes: List[str] = field(default_factory=list)


class MockBroker:
    """No-op broker used to guarantee no live actions occur."""

    def __init__(self) -> None:
        self.closed_positions: List[str] = []

    async def close_position(self, position_id: str) -> bool:
        self.closed_positions.append(str(position_id))
        return True


@dataclass
class MockMT5Position:
    ticket: int
    symbol: str
    type: int
    price_open: float
    price_current: float
    sl: float
    tp: float
    profit: float
    volume: float
    time: int


def ensure_dirs() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    PATCHES_DIR.mkdir(parents=True, exist_ok=True)


def emit(result: AuditResult) -> None:
    color = Color.GREEN if result.passed else Color.RED
    status = "PASS" if result.passed else "FAIL"
    print(f"{color}[{status}]{Color.RESET} {result.name} | {result.details}")
    if result.fixes:
        for fix in result.fixes:
            print(f"{Color.YELLOW}[FIX]{Color.RESET} {fix}")


def write_report(results: List[AuditResult]) -> None:
    lines: List[str] = []
    lines.append(f"Integrity Audit Report | {datetime.now(timezone.utc).isoformat()}")
    lines.append("=" * 88)
    for item in results:
        status = "PASS" if item.passed else "FAIL"
        lines.append(f"[{status}] {item.name} | {item.details}")
        for fix in item.fixes:
            lines.append(f"  FIX: {fix}")
    passed = sum(1 for item in results if item.passed)
    lines.append("=" * 88)
    lines.append(f"Summary | Passed={passed} | Failed={len(results) - passed} | Total={len(results)}")
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def write_patch_log(applied_fixes: List[str]) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    patch_path = PATCHES_DIR / f"integrity_audit_{stamp}.txt"
    payload = [
        f"Integrity audit patch log | {datetime.now(timezone.utc).isoformat()}",
        f"Repository: {ROOT}",
    ]
    if applied_fixes:
        payload.append("Applied fixes:")
        payload.extend(f"- {fix}" for fix in applied_fixes)
    else:
        payload.append("Applied fixes: none")
    patch_path.write_text("\n".join(payload), encoding="utf-8")


def load_json_file(path: Path) -> Tuple[bool, str]:
    try:
        json.loads(path.read_text(encoding="utf-8"))
        return True, "parsed successfully"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def audit_config_directory() -> AuditResult:
    config_dir = ROOT / "config"
    required = [
        "config.base.json",
        "config.dev.json",
        "config.mt5.json",
        "config.prod.json",
        "config.staging.json",
        "logging.json",
        "optimized_config.json",
        "rl_config.json",
    ]
    missing = [name for name in required if not (config_dir / name).exists()]
    broken: List[str] = []
    for name in required:
        path = config_dir / name
        if path.exists():
            ok, detail = load_json_file(path)
            if not ok:
                broken.append(f"{name}: {detail}")
    passed = not missing and not broken
    details = f"required={len(required)} | missing={len(missing)} | broken_json={len(broken)}"
    if missing:
        details += f" | missing_files={','.join(missing)}"
    if broken:
        details += f" | broken={'; '.join(broken)}"
    return AuditResult("Config Directory", passed, details)


def _read_ast(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def audit_main_connectivity() -> AuditResult:
    main_path = ROOT / "main.py"
    source = main_path.read_text(encoding="utf-8")

    checks = {
        "TradeAdmissionController": [
            "from src.ml.trade_admission_controller import TradeAdmissionController",
            "admit_controller = TradeAdmissionController()",
            "admit_controller.",
        ],
        "ExitManager": [
            "from src.trading.exit_manager import ExitManager",
            "exit_manager = ExitManager(",
            "exit_manager.check_exit_conditions(",
        ],
        "ThreeLayerArchitecture": [
            "TradeManagementLayer(",
            "RiskGovernor(",
            "ProfitProtectionModule(",
        ],
        "UserTradeLearner": [
            "from src.analysis.user_trade_learner import UserTradeLearner",
            "user_learner = UserTradeLearner()",
            "user_learner.capture_trade_entry(",
            "user_learner.capture_trade_exit(",
        ],
        "UserInterventionLearner": [
            "from src.learning.user_intervention_learner import UserInterventionLearner",
            "user_intervention_learner = UserInterventionLearner()",
            "user_intervention_learner.record_intervention(",
            "user_intervention_learner.scan_for_manual_closures(",
        ],
    }

    missing: Dict[str, List[str]] = {}
    for module_name, patterns in checks.items():
        absent = [pattern for pattern in patterns if pattern not in source]
        if absent:
            missing[module_name] = absent

    trend_source = (ROOT / "src" / "strategies" / "trend_strategy.py").read_text(encoding="utf-8")
    adaptive_patterns = [
        "AdaptiveSignalFilterer(",
        "self.signal_filterer.should_trade_signal(",
        "self.strictness_controller.apply_adjustments_to_filterer(",
    ]
    adaptive_missing = [pattern for pattern in adaptive_patterns if pattern not in trend_source]
    if adaptive_missing:
        missing["AdaptiveFilter"] = adaptive_missing

    passed = not missing
    detail = "all required modules initialized and invoked"
    if missing:
        fragments = [f"{name}: {len(items)} missing marker(s)" for name, items in missing.items()]
        detail = "; ".join(fragments)
    return AuditResult("Main Connectivity", passed, detail)


def audit_imports() -> AuditResult:
    modules = [
        "src.trading.exit_manager",
        "src.analysis.adaptive_signal_scoring",
        "src.ml.trade_admission_controller",
        "src.analysis.user_trade_learner",
        "src.learning.user_intervention_learner",
        "src.strategies.trend_strategy",
        "src.strategies.range_strategy",
    ]
    failed: List[str] = []
    for name in modules:
        try:
            importlib.import_module(name)
        except Exception as exc:
            failed.append(f"{name}: {type(exc).__name__}: {exc}")
    return AuditResult(
        "Import Integrity",
        not failed,
        "all target modules imported cleanly" if not failed else " | ".join(failed),
    )


def test_exit_manager() -> AuditResult:
    from src.models import Direction, Position
    from src.trading.exit_manager import ExitManager, ExitManagerConfig, ExitSignalType

    manager = ExitManager(
        config=ExitManagerConfig(
            enable_time_based_exit=True,
            stagnation_limit_bars=40,
            bar_duration_minutes=60,
            enable_hard_loss_stop=True,
            max_loss_threshold_usd=-4.0,
            enable_reversal_exit=False,
            log_all_checks=False,
        ),
        logger=logging.getLogger("integrity.exit_manager"),
        broker=MockBroker(),
    )

    stale_position = Position(
        position_id="P1",
        symbol="EUR/USD",
        direction=Direction.LONG,
        quantity=0.01,
        entry_price=1.1000,
        current_price=1.0950,
        unrealized_pnl=-5.0,
        stop_loss=1.0900,
        take_profit=1.1150,
        opened_at=datetime.now(timezone.utc) - timedelta(hours=50),
    )
    should_exit, _, signal_type = manager.check_exit_conditions(
        stale_position,
        strategy_indicators={"rsi": 50.0, "momentum": 0.0},
        current_bar_time=datetime.now(timezone.utc),
    )
    if not should_exit or signal_type not in {ExitSignalType.ACTION_CLOSE_IMMEDIATE, ExitSignalType.HARD_LOSS_THRESHOLD}:
        return AuditResult("ExitManager", False, "expected stale or loss position to trigger an exit")

    healthy_position = Position(
        position_id="P2",
        symbol="EUR/USD",
        direction=Direction.LONG,
        quantity=0.01,
        entry_price=1.1000,
        current_price=1.1010,
        unrealized_pnl=1.0,
        stop_loss=1.0950,
        take_profit=1.1100,
        opened_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    should_exit, _, _ = manager.check_exit_conditions(
        healthy_position,
        strategy_indicators={"rsi": 50.0, "momentum": 1.0},
        current_bar_time=datetime.now(timezone.utc),
    )
    if should_exit:
        return AuditResult("ExitManager", False, "healthy position incorrectly triggered an exit")

    return AuditResult("ExitManager", True, "hard-loss/time-exit logic responded as expected")


def test_adaptive_filter() -> AuditResult:
    from src.analysis.adaptive_signal_scoring import AdaptiveSignalFilterer

    filterer = AdaptiveSignalFilterer(min_score=50, ml_accuracy_target=0.55)
    now = datetime.now(timezone.utc)
    signal = {
        "symbol": "GBP/USD",
        "entry_price": 1.2500,
        "stop_loss": 1.2480,
        "take_profit": 1.2560,
    }
    analysis_data = {
        "adx": 22.0,
        "rsi": 44.0,
        "atr": 0.0012,
        "atr_mean": 0.0010,
    }
    try:
        should_trade, score, reason = filterer.should_trade_signal(
            signal=signal,
            analysis_data=analysis_data,
            timestamp=now,
            ml_confidence=0.85,
        )
    except Exception as exc:
        return AuditResult("AdaptiveFilter", False, f"raised {type(exc).__name__}: {exc}")

    if not isinstance(should_trade, bool) or not isinstance(score, (int, float)) or not isinstance(reason, str):
        return AuditResult("AdaptiveFilter", False, "returned malformed result tuple")
    if not should_trade:
        return AuditResult("AdaptiveFilter", False, f"high-confidence dummy signal should pass, got: {reason}")
    return AuditResult("AdaptiveFilter", True, "dummy high-confidence signal evaluated cleanly")


def test_admission_controller() -> AuditResult:
    from src.ml.trade_admission_controller import TradeAdmissionController

    controller = TradeAdmissionController()
    rejected = controller._apply_final_hard_gates(
        symbol="EUR/USD",
        admitted=True,
        final_multiplier=1.0,
        action_taken="ADMITTED",
        reason="precheck",
        confidence=0.90,
        ev=1.0,
        min_confidence_threshold=0.20,
        expectancy=0.50,
        rr_for_ev=0.50,
        position_size_multiplier=1.0,
        current_spread=0.0001,
        current_atr=0.0100,
        signal_score=90.0,
    )
    if rejected[0]:
        return AuditResult("AdmissionController", False, "RR 0.50R should be rejected by final hard gate")

    admitted = controller._apply_final_hard_gates(
        symbol="EUR/USD",
        admitted=True,
        final_multiplier=1.0,
        action_taken="ADMITTED",
        reason="precheck",
        confidence=0.90,
        ev=2.0,
        min_confidence_threshold=0.20,
        expectancy=3.00,
        rr_for_ev=3.00,
        position_size_multiplier=1.0,
        current_spread=0.0001,
        current_atr=0.0100,
        signal_score=90.0,
    )
    if not admitted[0]:
        return AuditResult("AdmissionController", False, f"RR 3.00R should be admitted, got: {admitted[3]}")
    return AuditResult("AdmissionController", True, "RR hard gate rejects 0.5R and admits 3.0R")


def test_user_trade_learner() -> AuditResult:
    from src.analysis.user_trade_learner import UserTradeLearner
    from src.models import Direction, Position

    temp_dir = LOGS_DIR / "integrity_learner_tmp"
    shutil.rmtree(temp_dir, ignore_errors=True)
    temp_dir.mkdir(parents=True, exist_ok=True)
    try:
        learner = UserTradeLearner(storage_dir=str(temp_dir))
        position = Position(
            position_id="UL1",
            symbol="USD/JPY",
            direction=Direction.SHORT,
            quantity=0.01,
            entry_price=150.00,
            current_price=149.90,
            unrealized_pnl=0.066711140760507,
            stop_loss=150.20,
            take_profit=149.40,
            opened_at=datetime.now(timezone.utc) - timedelta(minutes=30),
        )
        entry_context = {
            "adx": 18.0,
            "rsi": 68.0,
            "atr": 0.15,
            "price": 150.00,
            "mtf_score": 0.6,
            "volatility_score": 0.5,
            "momentum_score": 0.7,
            "liquidity_score": 0.4,
            "indicator_score": 0.65,
            "risk_score": 0.55,
        }
        learner.capture_trade_entry(position, entry_context, source="audit")
        if "UL1" not in learner.trades:
            return AuditResult("UserTradeLearner", False, "failed to persist dummy entry")
        learner.capture_trade_exit(
            "UL1",
            profit=12.50,
            exit_time=datetime.now(timezone.utc),
            market_context_at_exit={"rsi": 52.0, "atr": 0.15, "price": 149.70},
        )
        trade = learner.trades.get("UL1")
        if trade is None or trade.outcome != 12.50:
            return AuditResult("UserTradeLearner", False, "failed to persist dummy exit")
        weights = learner.get_weights()
        if not weights or not isinstance(weights, dict):
            return AuditResult("UserTradeLearner", False, "get_weights returned empty/invalid data")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
    return AuditResult("UserTradeLearner", True, "entry/exit capture and learned weights are functional")


def audit_ast_for_cycles() -> AuditResult:
    """Very lightweight static scan for obvious circular/self import patterns."""
    py_files = list((ROOT / "src").rglob("*.py"))
    self_imports: List[str] = []
    for path in py_files:
        try:
            tree = _read_ast(path)
        except Exception:
            continue
        module_name = ".".join(path.relative_to(ROOT).with_suffix("").parts)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == module_name:
                self_imports.append(str(path.relative_to(ROOT)))
    return AuditResult(
        "Circular Import Scan",
        not self_imports,
        "no self-import cycles detected" if not self_imports else ", ".join(self_imports),
    )


def main() -> int:
    ensure_dirs()
    logging.basicConfig(level=logging.CRITICAL)

    results: List[AuditResult] = []
    applied_fixes: List[str] = [
        "Pre-audit structural fix: initialized AdaptiveSignalFilterer.ml_accuracy_required default path to prevent unbound local errors.",
    ]

    for fn in (
        audit_config_directory,
        audit_main_connectivity,
        audit_imports,
        audit_ast_for_cycles,
        test_exit_manager,
        test_adaptive_filter,
        test_admission_controller,
        test_user_trade_learner,
    ):
        try:
            result = fn()
        except Exception as exc:
            result = AuditResult(
                fn.__name__,
                False,
                f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=3)}",
            )
        results.append(result)
        emit(result)

    write_report(results)
    write_patch_log(applied_fixes)

    failed = any(not result.passed for result in results)
    summary = f"Report written to {REPORT_PATH}"
    print(f"{Color.CYAN}[REPORT]{Color.RESET} {summary}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
