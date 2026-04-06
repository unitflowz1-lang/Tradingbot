"""
Trade Context Tracker - Persists metadata about entries to evaluate performance later
"""
import logging
import json
import os
import time
import threading
from datetime import datetime, timezone
from typing import Dict, Any, Optional

class TradeContextTracker:
    """Tracks metadata for open trades to analyze regime-based performance"""
    _file_lock = threading.Lock()
    
    def __init__(self, storage_path: str = "data/shadow_state.json"):
        self.logger = logging.getLogger(__name__)
        self.storage_path = storage_path
        self.contexts: Dict[str, Dict[str, Any]] = {}
        self._load_contexts()
        
    def _load_contexts(self):
        """Load tracked contexts from disk"""
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, 'r') as f:
                    self.contexts = json.load(f)
            except Exception as e:
                self.logger.error(f"Failed to load trade contexts: {e}")
                self.contexts = {}
                
    def _save_contexts(self):
        """Save tracked contexts with lock + retry when file is busy (WinError 32)."""
        max_attempts = 3
        retry_delay_s = 0.1
        for attempt in range(1, max_attempts + 1):
            temp_path = f"{self.storage_path}.{threading.get_ident()}.tmp"
            try:
                parent = os.path.dirname(self.storage_path)
                if parent:
                    os.makedirs(parent, exist_ok=True)
                with self.__class__._file_lock:
                    with open(temp_path, 'w') as f:
                        json.dump(self.contexts, f, indent=4)
                    os.replace(temp_path, self.storage_path)
                return
            except OSError as e:
                winerr = getattr(e, "winerror", None)
                is_file_lock = (winerr == 32) or ("being used by another process" in str(e).lower())
                if is_file_lock and attempt < max_attempts:
                    time.sleep(retry_delay_s)
                    continue
                self.logger.error(f"CRITICAL: Failed to save shadow state (atomic): {e}")
            except Exception as e:
                self.logger.error(f"CRITICAL: Failed to save shadow state (atomic): {e}")
            finally:
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except Exception:
                        pass
            
    def record_context(self, ticket_id: str, context: Dict[str, Any]):
        """Record context for a new trade entry"""
        ticket_id = str(ticket_id)
        context['recorded_at'] = datetime.now(timezone.utc).isoformat()
        self.contexts[ticket_id] = context
        self._save_contexts()
        self.logger.debug(f"[TRACKER] Recorded context for ticket {ticket_id}")
        
    def get_context(self, ticket_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve context for a closed trade"""
        return self.contexts.get(str(ticket_id))
        
    def remove_context(self, ticket_id: str):
        """Remove context after it's been used for performance update"""
        ticket_id = str(ticket_id)
        if ticket_id in self.contexts:
            del self.contexts[ticket_id]
            self._save_contexts()
            self.logger.debug(f"[TRACKER] Removed context for ticket {ticket_id}")

    def reconstruct_missing(self, ticket_id: str, symbol: str, direction: str, entry_price: float):
        """Reconstruct a basic context for a position found in MT5 but missing in shadow state"""
        ticket_id = str(ticket_id)
        if ticket_id not in self.contexts:
            self.logger.warning(f"[SYNC] Reconstructing shadow state for orphan ticket {ticket_id} ({symbol})")
            self.contexts[ticket_id] = {
                'reconstructed': True,
                'recorded_at': datetime.now(timezone.utc).isoformat(),
                'symbol': symbol,
                'direction': direction,
                'entry_price': entry_price,
                'note': 'Recovered from MT5-live-sync'
            }
            self._save_contexts()

# Singleton instance
trade_context_tracker = TradeContextTracker()
