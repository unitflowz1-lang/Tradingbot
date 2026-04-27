"""
Shared process-level gate for local Ollama requests.

Local Ollama inference is resource constrained; this lock ensures all
modules (macro monitor, governance, etc.) perform one generation at a time.
"""

import threading


OLLAMA_REQUEST_LOCK = threading.Lock()

