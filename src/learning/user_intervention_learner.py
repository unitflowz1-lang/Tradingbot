"""
User Intervention Learner
=========================
Tracks manual position closures so the bot can avoid instant re-entry.
"""

import csv
import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)

INTERVENTION_HISTORY_FILE = os.path.join(os.getcwd(), "user_intervention_history.json")
COOLDOWNS_FILE = os.path.join(os.getcwd(), "smarter_exit_cooldowns.json")
SMARTER_EXIT_COOLDOWN_MINUTES = 5
AMNESIA_LOSS_STREAK_THRESHOLD = 10


class UserInterventionLearner:
    """
    Monitors shadow positions and records closures that were not initiated
    by the bot itself.
    """

    def __init__(self):
        self._cooldown_file_lock = threading.Lock()
        self.bot_closed_this_cycle: Set[str] = set()
        self._smarter_exit_cooldown: Dict[tuple, datetime] = {}
        self.cooldown_dict = self._smarter_exit_cooldown
        self.manual_exit_cooldowns = self._smarter_exit_cooldown
        self.cooldowns = self._smarter_exit_cooldown
        self._history: List[Dict] = self._load_history()
        self._load_cooldowns()
        self._purge_expired_cooldowns()
        logger.info(
            "[USER_LEARNING] UserInterventionLearner online. Loaded %d historical intervention records.",
            len(self._history),
        )

    def mark_bot_closed(self, ticket_id: str) -> None:
        self.bot_closed_this_cycle.add(str(ticket_id))

    def record_intervention(self, *args, **kwargs):
        ticket_id = str(kwargs.get("ticket_id") or (args[0] if args else "")).strip()
        symbol = str(kwargs.get("symbol") or "").replace("/", "").upper()
        direction = self._normalize_direction(kwargs.get("direction"))
        reason = str(kwargs.get("reason") or "MANUAL_INTERVENTION").upper()
        timestamp_value = kwargs.get("timestamp")
        metadata = kwargs.get("metadata") or {}

        if not ticket_id:
            return None

        if timestamp_value is None:
            timestamp_dt = datetime.now(timezone.utc)
        elif isinstance(timestamp_value, datetime):
            timestamp_dt = timestamp_value if timestamp_value.tzinfo else timestamp_value.replace(tzinfo=timezone.utc)
        else:
            try:
                timestamp_dt = datetime.fromisoformat(str(timestamp_value))
                if timestamp_dt.tzinfo is None:
                    timestamp_dt = timestamp_dt.replace(tzinfo=timezone.utc)
            except Exception:
                timestamp_dt = datetime.now(timezone.utc)

        duplicate = next(
            (
                item for item in reversed(self._history)
                if str(item.get("ticket_id", "")).strip() == ticket_id
                and str(item.get("reason", "")).upper() == reason
            ),
            None,
        )
        if duplicate is not None:
            return duplicate

        record = {
            "timestamp": timestamp_dt.isoformat(),
            "ticket_id": ticket_id,
            "symbol": symbol,
            "direction": direction,
            "reason": reason,
            "metadata": metadata,
        }
        self._history.append(record)
        self._save_history()
        return record

    def reset_cycle(self) -> None:
        self.bot_closed_this_cycle.clear()

    def is_smarter_exit_active(self, symbol: str, direction: str) -> bool:
        symbol_key = str(symbol).replace("/", "").upper()
        direction_key = str(direction).upper()
        now = datetime.now(timezone.utc)
        key = (symbol_key, direction_key)
        expiry = self._smarter_exit_cooldown.get(key)
        if expiry is None:
            return False
        if now < expiry:
            remaining = max(0, int((expiry - now).total_seconds() / 60))
            logger.info(
                "[SMARTER_EXIT] Re-entry blocked for %s %s. Manual exit cooldown active - %dm remaining.",
                symbol_key,
                direction_key,
                remaining,
            )
            return True
        self._smarter_exit_cooldown.pop(key, None)
        self._save_cooldowns()
        return False

    def check_reentry(self, symbol: str, direction: str):
        if self.is_smarter_exit_active(symbol, direction):
            expiry = self._smarter_exit_cooldown.get((str(symbol).replace("/", "").upper(), str(direction).upper()))
            remaining = 0
            if expiry is not None:
                remaining = max(0, int((expiry - datetime.now(timezone.utc)).total_seconds() / 60))
            return (False, remaining)
        return (True, 0)

    def is_on_cooldown(self, symbol: str, direction: str):
        return self.check_reentry(symbol, direction)

    def clear_cooldowns_for_symbols(self, symbols: List[str]) -> int:
        normalized_symbols = {str(symbol).replace("/", "").upper() for symbol in (symbols or [])}
        if not normalized_symbols:
            return 0
        removed = 0
        for key in list(self._smarter_exit_cooldown.keys()):
            if key[0] in normalized_symbols:
                self._smarter_exit_cooldown.pop(key, None)
                removed += 1
        if removed:
            self._save_cooldowns()
            logger.info("[SMARTER_EXIT] Cleared %d cooldown(s) for symbols: %s", removed, sorted(normalized_symbols))
        return removed

    def scan_for_manual_closures(
        self,
        shadow_positions=None,
        live_ticket_ids=None,
        position_manager=None,
        **kwargs,
    ) -> List[str]:
        if shadow_positions is None:
            shadow_positions = kwargs.get("shadow_positions")
        if live_ticket_ids is None:
            live_ticket_ids = kwargs.get("live_mt5_ticket_ids")
        atr_stop_tasks_to_cancel = kwargs.get("atr_stop_tasks_to_cancel")
        live_ids = {str(ticket) for ticket in (live_ticket_ids or set())}
        purged: List[str] = []
        if not isinstance(shadow_positions, dict):
            return purged

        for ticket_id, position_data in list(shadow_positions.items()):
            ticket_str = str(ticket_id)
            if ticket_str in live_ids or ticket_str in self.bot_closed_this_cycle:
                continue

            symbol = self._extract_symbol(position_data)
            direction = self._normalize_direction(self._extract_direction(position_data))
            self.record_intervention(
                ticket_id=ticket_str,
                symbol=symbol,
                direction=direction,
                reason="MANUAL_INTERVENTION",
                timestamp=datetime.now(timezone.utc),
                metadata={"source": "shadow_reconciliation"},
            )
            self._activate_cooldown(symbol, direction)

            shadow_positions.pop(ticket_id, None)
            shadow_positions.pop(ticket_str, None)
            if position_manager is not None and hasattr(position_manager, "_save_shadow_state"):
                try:
                    position_manager._save_shadow_state()
                except Exception as exc:
                    logger.warning("[USER_LEARNING] Failed to persist purged shadow state: %s", exc)

            logger.critical(
                "[USER_LEARNING] Manual closure detected for %s %s | ticket=%s | Smarter Exit cooldown activated.",
                symbol,
                direction,
                ticket_str,
            )
            if isinstance(atr_stop_tasks_to_cancel, list):
                atr_stop_tasks_to_cancel.append(ticket_str)
            purged.append(ticket_str)

        return purged

    def _activate_cooldown(self, symbol: str, direction: str) -> None:
        key = (str(symbol).replace("/", "").upper(), str(direction).upper())
        expiry = datetime.now(timezone.utc) + timedelta(minutes=SMARTER_EXIT_COOLDOWN_MINUTES)
        self._smarter_exit_cooldown[key] = expiry
        self._save_cooldowns()

    def _load_history(self) -> List[Dict]:
        try:
            if not os.path.exists(INTERVENTION_HISTORY_FILE):
                return []
            with open(INTERVENTION_HISTORY_FILE, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            return payload if isinstance(payload, list) else []
        except Exception as exc:
            logger.warning("[USER_LEARNING] Failed to load intervention history: %s", exc)
            return []

    def _save_history(self) -> None:
        try:
            with open(INTERVENTION_HISTORY_FILE, "w", encoding="utf-8") as handle:
                json.dump(self._history, handle, indent=2, ensure_ascii=False)
        except Exception as exc:
            logger.error("[USER_LEARNING] Failed to save intervention history: %s", exc)

    def _load_cooldowns(self) -> None:
        consecutive_losses = self._calculate_consecutive_losses()
        if consecutive_losses >= AMNESIA_LOSS_STREAK_THRESHOLD:
            self._smarter_exit_cooldown.clear()
            logger.critical(
                "[AMNESIA_MODE_ACTIVE] Consecutive losses=%d. Persistent smarter-exit cooldown restore disabled.",
                consecutive_losses,
            )
            return

        if not os.path.exists(COOLDOWNS_FILE):
            return

        try:
            with open(COOLDOWNS_FILE, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception as exc:
            logger.warning("[SMARTER_EXIT] Failed to load persistent cooldowns: %s", exc)
            return

        if not isinstance(payload, dict):
            return

        loaded_count = 0
        now = datetime.now(timezone.utc)
        for cooldown_data in payload.values():
            try:
                symbol = str(cooldown_data.get("symbol", "")).replace("/", "").upper()
                direction = str(cooldown_data.get("direction", "")).upper()
                expiry_unix = cooldown_data.get("expiry_unix_timestamp")
                if not symbol or not direction or expiry_unix is None:
                    continue
                expiry_dt = datetime.fromtimestamp(float(expiry_unix), tz=timezone.utc)
                if now < expiry_dt:
                    self._smarter_exit_cooldown[(symbol, direction)] = expiry_dt
                    loaded_count += 1
            except Exception as exc:
                logger.warning("[SMARTER_EXIT] Could not parse cooldown entry: %s", exc)

        if loaded_count > 0:
            logger.critical(
                "[SMARTER_EXIT_RECOVERY] Recovered %d cooldown(s) from persistent storage. Manual exit boundaries restored.",
                loaded_count,
            )

    def _save_cooldowns(self) -> None:
        payload: Dict[str, Dict[str, object]] = {}
        now = datetime.now(timezone.utc)
        for (symbol, direction), expiry in list(self._smarter_exit_cooldown.items()):
            if expiry <= now:
                self._smarter_exit_cooldown.pop((symbol, direction), None)
                continue
            payload[f"{symbol}_{direction}"] = {
                "symbol": symbol,
                "direction": direction,
                "expiry_unix_timestamp": expiry.timestamp(),
            }
        try:
            with self._cooldown_file_lock:
                with open(COOLDOWNS_FILE, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, indent=2, ensure_ascii=False)
        except Exception as exc:
            logger.warning("[SMARTER_EXIT] Failed to persist cooldowns: %s", exc)

    def _purge_expired_cooldowns(self) -> None:
        now = datetime.now(timezone.utc)
        expired = [key for key, expiry in self._smarter_exit_cooldown.items() if now >= expiry]
        for key in expired:
            self._smarter_exit_cooldown.pop(key, None)
        if expired:
            self._save_cooldowns()

    def _calculate_consecutive_losses(self, trade_history_path: Optional[str] = None) -> int:
        history_path = trade_history_path or os.path.join(os.getcwd(), "trade_history.csv")
        if not os.path.exists(history_path):
            return 0
        try:
            with open(history_path, "r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
        except Exception as exc:
            logger.warning("[AMNESIA_GUARD] Could not read trade history for loss streak detection: %s", exc)
            return 0

        streak = 0
        for row in reversed(rows):
            try:
                pnl = float(row.get("pnl", 0.0) or 0.0)
            except Exception:
                pnl = 0.0
            if pnl < 0.0:
                streak += 1
                continue
            break
        return streak

    def _extract_symbol(self, position_data) -> str:
        if isinstance(position_data, dict):
            return str(position_data.get("symbol", "")).replace("/", "").upper()
        return str(getattr(position_data, "symbol", "")).replace("/", "").upper()

    def _extract_direction(self, position_data):
        if isinstance(position_data, dict):
            return position_data.get("direction")
        return getattr(position_data, "direction", None)

    def _normalize_direction(self, direction) -> str:
        if hasattr(direction, "name"):
            return str(direction.name).upper()
        if isinstance(direction, str):
            normalized = direction.upper()
            if normalized in {"LONG", "SHORT"}:
                return normalized
        if direction == 0:
            return "LONG"
        if direction == 1:
            return "SHORT"
        return "LONG"
