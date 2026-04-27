"""
RL Tactical Dispatcher
Sits between TradeAdmissionController and PositionSizer to decide execution tactics.
"""

from __future__ import annotations

import json
import math
import os
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from enum import IntEnum
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from src.logging_config import get_logger

logger = get_logger(__name__)


class RLTacticAction(IntEnum):
    HARD_SKIP = 0
    TACTICAL_DELAY = 1
    LOW_AGGRESSION = 2
    FULL_STRIKE = 3
    BOOSTED_STRIKE = 4


ACTION_MULTIPLIERS: Dict[int, float] = {
    RLTacticAction.HARD_SKIP: 0.0,
    RLTacticAction.TACTICAL_DELAY: 0.0,
    RLTacticAction.LOW_AGGRESSION: 0.5,
    RLTacticAction.FULL_STRIKE: 1.0,
    RLTacticAction.BOOSTED_STRIKE: 1.5,
}


@dataclass
class RLTacticalConfig:
    model_type: str = "none"  # "sb3", "torch", "none"
    model_path: str = "models/rl/tactical_dispatcher"
    shadow_mode: bool = False
    warmup_shadow_signals: int = 50
    buffer_path: str = "training_buffer.json"
    fallback_action: int = int(RLTacticAction.LOW_AGGRESSION)
    post_warmup_fallback_action: int = int(RLTacticAction.FULL_STRIKE)


@dataclass
class RLTacticalDecision:
    decision_id: str
    action: RLTacticAction
    multiplier: float
    reason: str
    applied: bool
    shadow_mode: bool
    warmup_complete: bool
    state_vector: List[float]
    raw_features: Dict[str, Any]


class RLTacticalDispatcher:
    """
    Tactical RL dispatcher for trade execution decisions.
    """

    _buffer_lock = threading.Lock()

    def __init__(self, config: Optional[RLTacticalConfig] = None) -> None:
        self.config = config or self._config_from_env()
        self.model = None
        self.model_error: Optional[str] = None
        self._last_news_lockout_end: Optional[datetime] = None
        self._shadow_count_cache: Optional[int] = None
        self._load_model()

    # ---------------------------
    # Public API
    # ---------------------------
    def decide(
        self,
        *,
        symbol: str,
        direction: str,
        admission_approved: bool,
        base_position_size: float,
        spread: float,
        atr: float,
        rsi: float,
        adx: float,
        ml_confidence: float,
        expectancy_r: float,
        hour_of_day: int,
        news_lockout_seconds: int,
        open_drawdown_pct: Optional[float] = None,
        margin_util_pct: Optional[float] = None,
        win_loss_ratio_10: Optional[float] = None,
    ) -> RLTacticalDecision:
        if not admission_approved:
            decision = self._build_decision(
                action=RLTacticAction.HARD_SKIP,
                reason="Admission gate rejected trade",
                applied=False,
                state_vector=[],
                raw_features={},
            )
            return decision

        state_vector, raw_features = self._build_state_vector(
            spread=spread,
            atr=atr,
            rsi=rsi,
            adx=adx,
            ml_confidence=ml_confidence,
            expectancy_r=expectancy_r,
            open_drawdown_pct=open_drawdown_pct,
            margin_util_pct=margin_util_pct,
            win_loss_ratio_10=win_loss_ratio_10,
            hour_of_day=hour_of_day,
            news_lockout_seconds=news_lockout_seconds,
        )

        action = self._predict_action(state_vector)
        reason = "RL policy decision"
        applied = self._should_apply_decision(symbol)
        warmup_complete = self._is_warmup_complete()

        # Shadow mode or warmup blocks execution changes.
        if not applied:
            reason = "Shadow mode or warm-up incomplete"

        multiplier = ACTION_MULTIPLIERS.get(action, 0.5)

        decision = self._build_decision(
            action=action,
            reason=reason,
            applied=applied,
            state_vector=state_vector,
            raw_features=raw_features,
        )

        self._record_decision(
            decision=decision,
            symbol=symbol,
            direction=direction,
            base_position_size=base_position_size,
            action_id=int(action),
            action_multiplier=multiplier,
            warmup_complete=warmup_complete,
        )

        logger.info(
            "[RL_TACTIC] %s | Action: %s | Applied: %s | Warmup: %s | Reason: %s",
            symbol,
            action.name,
            decision.applied,
            warmup_complete,
            decision.reason,
        )

        return decision

    @classmethod
    def record_outcome(
        cls,
        *,
        decision_id: str,
        outcome: Dict[str, Any],
        buffer_path: str = "training_buffer.json",
    ) -> None:
        if not decision_id:
            return
        with cls._buffer_lock:
            data = cls._load_buffer(buffer_path)
            updated = False
            for rec in data.get("records", []):
                if rec.get("decision_id") == decision_id:
                    rec["outcome"] = outcome
                    rec["outcome_recorded_at"] = datetime.now(timezone.utc).isoformat()
                    updated = True
                    break
            if updated:
                cls._save_buffer(buffer_path, data)

    # ---------------------------
    # Reward Function (Training)
    # ---------------------------
    @staticmethod
    def calculate_reward(
        *,
        pnl: float,
        sharpe_modifier: float,
        max_adverse_excursion_ratio: Optional[float],
        spread: float,
        slippage_est: float,
        skipped_loss: bool,
        action_id: Optional[int] = None,
        delay_penalty: float = 0.01,
        potential_profit: Optional[float] = None,
        favorable_move_pips: Optional[float] = None,
        favorable_move_seconds: Optional[float] = None,
        expert_reward_multiplier: float = 1.0,
    ) -> float:
        # Primary reward: PnL scaled by Sharpe modifier
        reward = pnl * max(0.0, sharpe_modifier)

        # Drawdown penalty: exponential penalty if MAE exceeds 50% of SL distance
        if max_adverse_excursion_ratio is not None and max_adverse_excursion_ratio > 0.5:
            penalty = math.exp(3.0 * (max_adverse_excursion_ratio - 0.5)) - 1.0
            reward -= penalty

        # Friction penalty: spread * slippage
        spread_cost = max(0.0, spread) * max(0.0, slippage_est)
        reward -= spread_cost

        # Slippage-aware penalty: spread cost > 20% of potential profit
        if potential_profit is None:
            potential_profit = max(0.0, pnl)
        if potential_profit > 0.0 and spread_cost > 0.20 * potential_profit:
            penalty = min(1.0, spread_cost / max(potential_profit, 1e-9))
            reward -= penalty

        # Efficiency bonus: skipping a losing trade
        if skipped_loss:
            reward += 0.1

        # Momentum burst bonus: >10 pips in our favor within 60 seconds
        if favorable_move_pips is not None and favorable_move_seconds is not None:
            if favorable_move_pips >= 10.0 and favorable_move_seconds <= 60.0:
                reward += 0.2

        # Cost of waiting: discourage repeated delays
        if action_id is not None and int(action_id) == int(RLTacticAction.TACTICAL_DELAY):
            reward -= abs(delay_penalty)

        if expert_reward_multiplier and expert_reward_multiplier > 1.0:
            reward *= float(expert_reward_multiplier)
        return reward

    # ---------------------------
    # Internal helpers
    # ---------------------------
    def _config_from_env(self) -> RLTacticalConfig:
        shadow = str(os.environ.get("RL_SHADOW_MODE", "0")).lower() in {"1", "true", "yes", "on"}
        model_type = os.environ.get("RL_TACTIC_MODEL_TYPE", "none").lower()
        model_path = os.environ.get("RL_TACTIC_MODEL_PATH", "models/rl/tactical_dispatcher")
        warmup = int(os.environ.get("RL_WARMUP_SHADOW_SIGNALS", "50"))
        buffer_path = os.environ.get("RL_TACTIC_BUFFER_PATH", "training_buffer.json")
        return RLTacticalConfig(
            model_type=model_type,
            model_path=model_path,
            shadow_mode=shadow,
            warmup_shadow_signals=warmup,
            buffer_path=buffer_path,
        )

    def _fallback_action_for_state(self) -> RLTacticAction:
        warmup_complete = self._is_warmup_complete()
        action_id = self.config.post_warmup_fallback_action if warmup_complete else self.config.fallback_action
        if action_id not in ACTION_MULTIPLIERS:
            action_id = self.config.fallback_action
        return RLTacticAction(action_id)

    def _load_model(self) -> None:
        model_type = self.config.model_type
        if model_type == "none":
            return

        if model_type == "sb3":
            try:
                from stable_baselines3 import PPO  # type: ignore
                if os.path.exists(self.config.model_path):
                    self.model = PPO.load(self.config.model_path)
            except Exception as exc:
                self.model_error = str(exc)
                logger.warning("[RL_TACTIC] SB3 model load failed: %s", exc)
            return

        if model_type == "torch":
            try:
                import torch  # type: ignore
                if os.path.exists(self.config.model_path):
                    self.model = torch.jit.load(self.config.model_path)
                    self.model.eval()
            except Exception as exc:
                self.model_error = str(exc)
                logger.warning("[RL_TACTIC] Torch model load failed: %s", exc)
            return

    def _predict_action(self, state_vector: List[float]) -> RLTacticAction:
        try:
            if not state_vector:
                return RLTacticAction(self.config.fallback_action)
            if self.model is None:
                return RLTacticAction(self.config.fallback_action)

            if self.config.model_type == "sb3":
                action, _states = self.model.predict(np.array(state_vector, dtype=np.float32), deterministic=True)
                action_id = int(action)
            elif self.config.model_type == "torch":
                import torch  # type: ignore

                with torch.no_grad():
                    obs = torch.tensor(state_vector, dtype=torch.float32).unsqueeze(0)
                    logits = self.model(obs)
                    if isinstance(logits, (tuple, list)):
                        logits = logits[0]
                    action_id = int(torch.argmax(logits, dim=-1).item())
            else:
                action_id = int(self._fallback_action_for_state())

            if action_id not in ACTION_MULTIPLIERS:
                action_id = int(self._fallback_action_for_state())
            return RLTacticAction(action_id)
        except Exception as exc:
            logger.warning("[RL_TACTIC] Model inference failed: %s", exc)
            return self._fallback_action_for_state()

    def _should_apply_decision(self, symbol: str) -> bool:
        if self.config.shadow_mode:
            return False
        if not self._is_warmup_complete() and not self._has_warmup_override(symbol):
            return False
        return True

    @classmethod
    def register_warmup_override(
        cls,
        symbol: str,
        ttl_minutes: int = 60,
        path: str = "memory/rl_warmup_overrides.json",
    ) -> None:
        """Bypass warmup for a specific symbol after manual expert exits."""
        if not symbol:
            return
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=max(1, int(ttl_minutes)))
        symbol_key = str(symbol).upper().replace("/", "")
        with cls._buffer_lock:
            data = cls._load_buffer(path)
            overrides = data.get("overrides", {})
            overrides[symbol_key] = expires_at.isoformat()
            data["overrides"] = overrides
            cls._save_buffer(path, data)

    def _has_warmup_override(self, symbol: str, path: str = "memory/rl_warmup_overrides.json") -> bool:
        if not symbol:
            return False
        symbol_key = str(symbol).upper().replace("/", "")
        data = self._load_buffer(path)
        overrides = data.get("overrides", {})
        expiry_raw = overrides.get(symbol_key)
        if not expiry_raw:
            return False
        try:
            expiry = datetime.fromisoformat(expiry_raw)
        except Exception:
            return False
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if expiry <= datetime.now(timezone.utc):
            # Expired; cleanup on read.
            overrides.pop(symbol_key, None)
            data["overrides"] = overrides
            self._save_buffer(path, data)
            return False
        return True

    @classmethod
    def inject_expert_exits(
        cls,
        *,
        expert_path: str = "memory/expert_exits.json",
        buffer_path: str = "training_buffer.json",
    ) -> int:
        """Inject expert exit demonstrations into the RL training buffer."""
        if not os.path.exists(expert_path):
            return 0
        try:
            with open(expert_path, "r", encoding="utf-8") as f:
                expert_data = json.load(f) or []
        except Exception:
            return 0
        if not isinstance(expert_data, list) or not expert_data:
            return 0

        with cls._buffer_lock:
            data = cls._load_buffer(buffer_path)
            existing = {rec.get("expert_id") for rec in data.get("expert_exits", []) if isinstance(rec, dict)}
            new_records = []
            for rec in expert_data:
                if not isinstance(rec, dict):
                    continue
                rec_id = rec.get("expert_id")
                if rec_id and rec_id in existing:
                    continue
                new_records.append(rec)
                if rec_id:
                    existing.add(rec_id)
            if new_records:
                data.setdefault("expert_exits", []).extend(new_records)
                cls._save_buffer(buffer_path, data)
            return len(new_records)

    def _is_warmup_complete(self) -> bool:
        shadow_count = self._shadow_count()
        return shadow_count >= self.config.warmup_shadow_signals

    def _shadow_count(self) -> int:
        if self._shadow_count_cache is not None:
            return self._shadow_count_cache
        data = self._load_buffer(self.config.buffer_path)
        records = data.get("records", [])
        count = 0
        for rec in records:
            if rec.get("shadow_only"):
                count += 1
        count = max(count, len(records))
        self._shadow_count_cache = count
        return count

    def _build_state_vector(
        self,
        *,
        spread: float,
        atr: float,
        rsi: float,
        adx: float,
        ml_confidence: float,
        expectancy_r: float,
        open_drawdown_pct: Optional[float],
        margin_util_pct: Optional[float],
        win_loss_ratio_10: Optional[float],
        hour_of_day: int,
        news_lockout_seconds: int,
    ) -> Tuple[List[float], Dict[str, Any]]:
        spread = float(spread or 0.0)
        atr = float(atr or 0.0)
        rsi = float(rsi or 50.0)
        adx = float(adx or 0.0)
        ml_confidence = float(ml_confidence or 0.0)
        expectancy_r = float(expectancy_r or 0.0)

        spread_pct_atr = (spread / atr) if atr > 0 else 0.0
        rsi_delta = rsi - 50.0

        news_minutes = self._news_lockout_minutes(news_lockout_seconds)

        raw = {
            "spread_pct_atr": spread_pct_atr,
            "atr": atr,
            "rsi_delta": rsi_delta,
            "adx": adx,
            "ml_confidence": ml_confidence,
            "expectancy_r": expectancy_r,
            "open_drawdown_pct": float(open_drawdown_pct or 0.0),
            "margin_util_pct": float(margin_util_pct or 0.0),
            "win_loss_ratio_10": float(win_loss_ratio_10 or 0.0),
            "hour_of_day": int(hour_of_day),
            "news_lockout_minutes": news_minutes,
        }

        # Normalization (0..1 range)
        spread_norm = min(max(spread_pct_atr / 3.0, 0.0), 1.0)
        atr_norm = min(max(atr / 0.01, 0.0), 1.0)
        rsi_delta_norm = (min(max(rsi_delta, -50.0), 50.0) + 50.0) / 100.0
        adx_norm = min(max(adx / 100.0, 0.0), 1.0)
        ml_conf_norm = min(max(ml_confidence, 0.0), 1.0)
        expectancy_norm = min(max(expectancy_r / 5.0, 0.0), 1.0)
        dd_norm = min(max((open_drawdown_pct or 0.0) / 100.0, 0.0), 1.0)
        margin_norm = min(max((margin_util_pct or 0.0) / 100.0, 0.0), 1.0)
        wl_norm = min(max((win_loss_ratio_10 or 0.0) / 5.0, 0.0), 1.0)
        hour_norm = min(max(hour_of_day / 23.0, 0.0), 1.0)
        news_norm = (min(max(news_minutes, -240.0), 240.0) + 240.0) / 480.0

        state_vector = [
            spread_norm,
            atr_norm,
            rsi_delta_norm,
            adx_norm,
            ml_conf_norm,
            expectancy_norm,
            dd_norm,
            margin_norm,
            wl_norm,
            hour_norm,
            news_norm,
        ]

        return state_vector, raw

    def _news_lockout_minutes(self, news_lockout_seconds: int) -> float:
        now = datetime.now(timezone.utc)
        if news_lockout_seconds and news_lockout_seconds > 0:
            end = now + timedelta(seconds=news_lockout_seconds)
            self._last_news_lockout_end = end
            return news_lockout_seconds / 60.0
        if self._last_news_lockout_end and now > self._last_news_lockout_end:
            return -((now - self._last_news_lockout_end).total_seconds() / 60.0)
        return 0.0

    def _build_decision(
        self,
        *,
        action: RLTacticAction,
        reason: str,
        applied: bool,
        state_vector: List[float],
        raw_features: Dict[str, Any],
    ) -> RLTacticalDecision:
        decision_id = uuid.uuid4().hex[:12]
        return RLTacticalDecision(
            decision_id=decision_id,
            action=action,
            multiplier=ACTION_MULTIPLIERS.get(action, 0.5),
            reason=reason,
            applied=applied,
            shadow_mode=self.config.shadow_mode,
            warmup_complete=self._is_warmup_complete(),
            state_vector=state_vector,
            raw_features=raw_features,
        )

    def _record_decision(
        self,
        *,
        decision: RLTacticalDecision,
        symbol: str,
        direction: str,
        base_position_size: float,
        action_id: int,
        action_multiplier: float,
        warmup_complete: bool,
    ) -> None:
        record = {
            "decision_id": decision.decision_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "direction": direction,
            "action": decision.action.name,
            "action_id": action_id,
            "action_multiplier": action_multiplier,
            "applied": decision.applied,
            "shadow_only": (not decision.applied),
            "warmup_complete": warmup_complete,
            "base_position_size": float(base_position_size or 0.0),
            "state_vector": decision.state_vector,
            "raw_features": decision.raw_features,
            "outcome": None,
        }

        with self._buffer_lock:
            data = self._load_buffer(self.config.buffer_path)
            data.setdefault("records", []).append(record)
            self._save_buffer(self.config.buffer_path, data)

        if record["shadow_only"]:
            self._shadow_count_cache = (self._shadow_count_cache or 0) + 1

    @classmethod
    def _load_buffer(cls, path: str) -> Dict[str, Any]:
        if not os.path.exists(path):
            return {"version": 1, "records": []}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"version": 1, "records": []}

    @classmethod
    def _save_buffer(cls, path: str, data: Dict[str, Any]) -> None:
        temp_path = f"{path}.{threading.get_ident()}.tmp"
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(temp_path, path)
